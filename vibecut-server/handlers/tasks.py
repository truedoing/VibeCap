"""任务 CRUD — POST /tasks/create, /tasks/status, /tasks/delete"""

import json
import os
import shutil
import traceback
from pathlib import Path

from config import project_name, BASE_DIR, PROJECT_DIR, SERVER_DIR, args
from db import VibeCutDB
from lib.subprocess_runner import run_script


DB_PATH = BASE_DIR / "vibecut.db"
db = VibeCutDB(str(DB_PATH))


def list_dramas():
    """列出所有项目"""
    dramas = db.list_dramas()
    seen = {d["name"] for d in dramas}
    projects_dir = BASE_DIR / "projects"
    if projects_dir.exists():
        for cfg_file in sorted(projects_dir.glob("*.json")):
            name = cfg_file.stem
            if name in seen:
                continue
            try:
                cfg = json.load(open(cfg_file))
                dramas.append({
                    "name": name,
                    "type": cfg.get("type", "drama"),
                    "description": cfg.get("description", ""),
                    "task_count": 0,
                })
            except Exception:
                pass
    return dramas


def list_tasks(drama_name: str):
    """列出项目所有任务"""
    tasks = []
    drama_id = db.get_drama_id(drama_name)
    if drama_id:
        tasks = db.list_tasks(drama_id)
    seen = {t.get("name", "") for t in tasks}
    tasks_dir = BASE_DIR / drama_name / "tasks"
    if tasks_dir.exists():
        for task_dir in sorted(tasks_dir.iterdir()):
            if not task_dir.is_dir():
                continue
            name = task_dir.name
            if name in seen:
                continue
            seg_count = 0
            seg_file = task_dir / "segments.json"
            if seg_file.exists():
                try:
                    seg_count = len(json.load(open(seg_file)).get("segments", []))
                except Exception:
                    pass
            tasks.append({
                "name": name, "status": "editing",
                "segments": seg_count, "duration": 0,
            })
    return tasks


def create_task(data: dict, docx_bytes: bytes = None, audio_bytes: bytes = None,
                docx_name: str = "解说文案.docx", audio_name: str = "解说音频.wav") -> dict:
    """创建任务目录 + 处理解说素材"""
    drama_name = data.get("drama", project_name)
    task_name = data.get("name", "").strip()
    local_path = data.get("local_path", "").strip()

    if not task_name:
        return {"ok": False, "error": "缺少任务名称"}

    task_dir = BASE_DIR / drama_name / "tasks" / task_name
    if task_dir.exists():
        return {"ok": False, "error": f"任务目录已存在: {task_dir}"}

    try:
        task_dir.mkdir(parents=True)
        (task_dir / "work_dir").mkdir()
        (task_dir / "素材clips").mkdir()

        if local_path:
            src_dir = Path(local_path)
            if not src_dir.exists():
                return {"ok": False, "error": f"源目录不存在: {local_path}"}
            for f in src_dir.iterdir():
                if f.suffix == ".docx":
                    shutil.copy(f, task_dir / "解说文案.docx")
                elif f.suffix in (".wav", ".mp3"):
                    shutil.copy(f, task_dir / f"解说音频{f.suffix}")
        else:
            if docx_bytes:
                (task_dir / "解说文案.docx").write_bytes(docx_bytes)
            if audio_bytes:
                ext = Path(audio_name).suffix or ".wav"
                (task_dir / f"解说音频{ext}").write_bytes(audio_bytes)

        docx_file = task_dir / "解说文案.docx"
        if not docx_file.exists():
            # docx 不是必需的 — 新任务允许不传解说文案，由 AI 编剧生成
            print(f"[create_task] 无解说文案.docx，跳过A1解析步骤 ({task_name})")
            drama_id = db.get_drama_id(drama_name)
            if not drama_id:
                drama_id = db.ensure_drama(drama_name)
            if drama_id:
                db.create_task(drama_id, task_name)
            return {"ok": True, "task": task_name, "steps": [],
                    "note": "未上传docx，脚本可由AI编剧生成"}

        results = {"ok": True, "task": task_name, "steps": []}

        # 使用统一的子进程执行器
        env = {"VibeCut_DRAMA": drama_name, "VibeCut_TASK": task_name}
        r = run_script("parse_docx.py", timeout=60, env_extra=env)
        results["steps"].append({"step": "parse_docx", "ok": r["ok"],
                                 "output": "\n".join(r.get("log_lines", [])[-3:])})

        drama_id = db.get_drama_id(drama_name)
        if not drama_id:
            drama_id = db.ensure_drama(drama_name)
        if drama_id:
            task_id = db.create_task(drama_id, task_name)
            if r["ok"] and (task_dir / "segments.json").exists():
                seg_data = json.load(open(task_dir / "segments.json"))
                db.save_task_segments(task_id, seg_data.get("segments", []))

        if r["ok"] and (task_dir / "segments.json").exists():
            audio_file = task_dir / "解说音频.wav"
            if audio_file.exists():
                env_a2 = {**env, "KMP_DUPLICATE_LIB_OK": "TRUE"}
                r2 = run_script("asr_narration.py", timeout=300, env_extra=env_a2)
                results["steps"].append({"step": "asr_narration", "ok": r2["ok"],
                                         "output": "\n".join(r2.get("log_lines", [])[-3:])})

                if r2["ok"]:
                    r3 = run_script("match_split.py", timeout=60, env_extra=env_a2)
                    results["steps"].append({"step": "match_split", "ok": r3["ok"],
                                             "output": "\n".join(r3.get("log_lines", [])[-3:])})

        return results

    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


def update_task_status(drama_name: str, task_name: str, status: str) -> dict:
    """更新任务状态"""
    if status not in ("editing", "reviewing", "delivered"):
        return {"ok": False, "error": "状态无效"}
    drama_id = db.get_drama_id(drama_name)
    if not drama_id:
        return {"ok": False, "error": f"项目不存在: {drama_name}"}
    db.update_task_status(drama_id, task_name, status)
    return {"ok": True}


def delete_task(drama_name: str, task_name: str) -> dict:
    """删除任务（DB + 磁盘）"""
    drama_id = db.get_drama_id(drama_name)
    if not drama_id:
        return {"ok": False, "error": f"项目不存在: {drama_name}"}
    ok = db.delete_task(drama_id, task_name)
    task_dir = BASE_DIR / drama_name / "tasks" / task_name
    if task_dir.exists():
        shutil.rmtree(task_dir)
        ok = True
    if ok:
        return {"ok": True}
    return {"ok": False, "error": "任务不存在"}
