"""编剧台 Drama SSE 处理函数 — POST /script/generate_drama_script

对标 handlers/script_gen.py 的模式：
  generate_drama_script() 作为 SSE 回调函数
  负责加载数据 → 调用 Agent → 保存结果 → 发送 SSE 事件
"""

import json
import os
import time
from pathlib import Path

from config import project_name, PROJECT_DIR, BASE_DIR, args
from db import VibeCutDB

DB_PATH = BASE_DIR / "vibecut.db"
db = VibeCutDB(str(DB_PATH))


# ── 辅助函数 ──

def generate_drama_script_v2(
    topic: str,
    emit_progress,
    emit_complete,
    emit_error,
    *,
    drama_name: str = None,
    target_duration: int = 300,
):
    """编剧台 V2：单 LLM + 方法论，一次产出完整解说脚本（放弃多 Agent）。

    流程：
      1. 调一次 DeepSeek（SCRIPT_V2_PROMPT），一次产出 title/theme/device/segments
      2. 把 segments 映射成下游契约（narration_text/highlight_text/episode_marker）
      3. 落盘 segments.json + 文案脚本.json，发送 complete
    """
    from lib.llm import call_deepseek_json
    from handlers.prompts.script_drama import SCRIPT_V2_PROMPT

    drama = drama_name or project_name
    emit_progress("init", f"🎬 编剧台V2（单LLM+方法论） · 剧目: {drama} · 选题: {topic[:40]}")

    emit_progress("writing", "✍️ 单 LLM 一次性创作完整脚本（论点+装置+起承转合+名场面）...")
    user = f"选题：{topic}\n\n请按方法论一次写出完整解说脚本。"
    res = call_deepseek_json(SCRIPT_V2_PROMPT, user, temperature=0.7, max_tokens=4000,
                             timeout=300, label="script_v2")

    if not res.get("ok"):
        emit_error(f"生成失败: {res.get('error', '?')[:200]}")
        return

    data = res.get("data") or {}
    raw_segments = data.get("segments", [])
    if not raw_segments:
        emit_error("生成失败: 未产出有效段落")
        return

    # 映射：{seq, type, content, episode, function} → 下游契约
    segments = []
    for i, s in enumerate(raw_segments):
        seg_type = s.get("type", "narration")
        content = (s.get("content") or "").strip()
        ep = s.get("episode")
        func = s.get("function")

        if seg_type == "dialogue":
            # 原声段：highlight_text = 台词，narration_text 空
            seg = {
                "seg_id": i,
                "narration_text": "",
                "highlight_text": content,
                "mode": "A",
                "function": func or "举证",
            }
            if ep:
                seg["video_episode"] = ep
                seg["episode_marker"] = {
                    "episode": ep,
                    "approx_minute": None,
                    "raw": f"EP{ep}",
                }
        else:
            # 解说段：narration_text = 解说词
            seg = {
                "seg_id": i,
                "narration_text": content,
                "highlight_text": "",
                "mode": "A",
                "function": func,
            }
            if ep:
                seg["video_episode"] = ep
                seg["episode_marker"] = {
                    "episode": ep,
                    "approx_minute": None,
                    "raw": f"EP{ep}",
                }
        segments.append(seg)

    cover = data.get("title") or topic[:25]
    result = {
        "ok": True,
        "pipeline": "drama-v2-single-llm",
        "topic": topic,
        "cover": cover,
        "title": data.get("title", ""),
        "theme": data.get("theme", ""),
        "device": data.get("device", ""),
        "segments": segments,
        "total": len(segments),
        "total_chars": sum(len(s.get("narration_text", "")) for s in segments),
    }

    # 落盘（复用现有保存函数，但 v2 结果结构不同，需构造兼容字段）
    _save_drama_segments_v2(result, topic)
    _save_to_task_dir_v2(result)
    _sync_to_db(result)
    emit_complete(result)


def _save_drama_segments_v2(result: dict, topic: str):
    """保存 v2 结果到项目级 文案脚本.json"""
    tasks_dir = PROJECT_DIR / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    script_file = tasks_dir / "文案脚本.json"
    save_data = {
        "pipeline": "drama-v2-single-llm",
        "topic": topic,
        "cover": result.get("cover", ""),
        "title": result.get("title", ""),
        "theme": result.get("theme", ""),
        "device": result.get("device", ""),
        "segments": result["segments"],
        "total": result.get("total", len(result["segments"])),
        "total_chars": result.get("total_chars", 0),
    }
    json.dump(save_data, open(script_file, "w"), ensure_ascii=False, indent=2)
    result["script_file"] = str(script_file)
    print(f"[drama_script_v2] 保存文案脚本 → {script_file}")


def _save_to_task_dir_v2(result: dict):
    """同步写入任务级 segments.json (兼容 VibeEdit 加载)"""
    tasks_dir = PROJECT_DIR / "tasks"
    task_dir = tasks_dir / (args.task or "default")
    task_dir.mkdir(parents=True, exist_ok=True)
    seg_file = task_dir / "segments.json"

    seg_data = {
        "task_type": "drama",
        "source": "AI编剧V2单LLM",
        "pipeline": "drama-v2-single-llm",
        "project_type": "drama",
        "total_segments": len(result["segments"]),
        "cover": result.get("cover", ""),
        "hook_line": result.get("theme", "")[:60],
        "closing_line": "",
        "audio_verified": False,
        "segments": result["segments"],
    }
    json.dump(seg_data, open(seg_file, "w"), ensure_ascii=False, indent=2)
    print(f"[drama_script_v2] segments.json 同步 → {seg_file}")


def _sync_to_db(result: dict):
    """同步写入 SQLite (和 interview 一样)"""
    try:
        drama_id = db.get_drama_id(project_name)
        if drama_id:
            task_name = args.task or f"drama_{int(time.time())}"
            existing = db.get_task(drama_id, task_name)
            if existing:
                task_id = existing["id"]
                db.save_task_segments(task_id, result["segments"])
            else:
                task_id = db.create_task(drama_id, task_name)
                db.save_task_segments(task_id, result["segments"])
            print(f"[drama_script] DB: task={task_name} task_id={task_id} segs={len(result['segments'])}")
            result["task_id"] = task_id
    except Exception as e:
        print(f"[drama_script] DB save failed (non-critical): {e}")
