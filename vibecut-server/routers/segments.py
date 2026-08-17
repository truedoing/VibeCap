"""路由: 分段 + 旁白 + 脚本文件"""
import json
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from config import project_name, project_type, PROJECT_DIR, args, resolve_task_dir
from routers._lifespan import db

router = APIRouter(tags=["分段"])


@router.post("/script/import_external_json")
async def api_import_external_json(request: Request):
    """编辑台内导入外部解说 JSON（扣子/WorkBuddy 产出）→ 解析成 segments.json

    body: {"task": "TaskNew", "data": {外部JSON}}
    解析后落盘到 task 目录 segments.json，并同步 DB。
    """
    body = await request.json()
    task_name = body.get("task") or args.task
    ext_data = body.get("data") or body

    if not isinstance(ext_data, dict) or "segments" not in ext_data:
        return JSONResponse({"ok": False, "error": "JSON 缺少 segments 字段"}, status_code=400)

    # 复用解析器（子进程方式，避免 argparse 副作用；或直接 import 纯函数）
    import sys
    from pathlib import Path
    SERVER_DIR = Path(__file__).resolve().parent.parent
    if str(SERVER_DIR) not in sys.path:
        sys.path.insert(0, str(SERVER_DIR))
    from cli.parse_external_json import normalize_external

    sources_dir = PROJECT_DIR / "sources"
    result = normalize_external(ext_data, sources_dir)

    # 落盘
    from lib.segments_store import save_segments
    save_segments(task_name, result)

    # 同步 DB
    drama_id = db.get_drama_id(project_name)
    if drama_id:
        task_obj = db.get_task(drama_id, task_name)
        if task_obj:
            db.save_task_segments(task_obj["id"], result.get("segments", []))

    return {"ok": True, "task": task_name, "total_segments": result.get("total_segments", 0)}


@router.get("/segments.json")
def api_segments(task: str = Query(None)):
    """任务分段 (DB→文件fallback)"""
    task_name = task or args.task
    drama_id = db.get_drama_id(project_name)
    # 优先从文件读完整数据（含 meta/theme/core_insight），DB 只作为 segments 的来源补充
    seg_file = resolve_task_dir(task_name) / "segments.json"
    file_data = None
    if seg_file.exists():
        try:
            file_data = json.load(open(seg_file))
        except Exception:
            file_data = None

    if drama_id:
        task_obj = db.get_task(drama_id, task_name)
        if task_obj:
            segments = db.get_task_segments(task_obj["id"])
            if segments and len(segments) > 0:
                result = {"segments": segments, "total_segments": len(segments),
                          "project_type": project_type}
                # 合并文件里的 meta 信息（方案全文）
                if file_data:
                    for k in ("meta", "theme", "core_insight", "cover", "hook_line", "closing_line", "device", "type"):
                        if file_data.get(k) is not None:
                            result[k] = file_data[k]
                    # 合并文件版 segments 的配音字段（audio_duration/audio_path 反写只落在文件，DB 版没有）
                    file_segs = {s.get("seg_id"): s for s in file_data.get("segments", [])}
                    for seg in result["segments"]:
                        sid = seg.get("seg_id")
                        fs = file_segs.get(sid) if sid is not None else None
                        if fs:
                            for k in ("audio_duration", "audio_path", "audio_emotion"):
                                if fs.get(k) is not None:
                                    seg[k] = fs[k]
                located_file = resolve_task_dir(task_name) / "segments_located.json"
                if located_file.exists():
                    try:
                        located = json.load(open(located_file))
                        located_map = {s.get("seg_id"): s for s in located.get("segments", [])}
                        for seg in result["segments"]:
                            lid = seg.get("seg_id")
                            if lid is not None and lid in located_map:
                                loc = located_map[lid]
                                seg["video_start"] = loc.get("video_start")
                                seg["video_end"] = loc.get("video_end")
                                seg["ep"] = loc.get("ep")
                    except Exception:
                        pass
                return JSONResponse(result)

    # Fallback: 文件系统
    if file_data is not None:
        file_data["project_type"] = project_type
        return JSONResponse(file_data)

    # 项目级兜底
    project_seg = PROJECT_DIR / "tasks" / "segments.json"
    if project_seg.exists():
        return JSONResponse({"segments": json.load(open(project_seg)).get("segments", [])})

    return JSONResponse({}, status_code=404)


@router.get("/narration.json")
def api_narration(task: str = Query(None)):
    task_name = task or args.task
    from config import resolve_work_dir
    narr_file = resolve_work_dir(task_name) / "narration.json"
    if narr_file.exists():
        raw = json.load(open(narr_file))
        if isinstance(raw, list):
            wrapped = [{"index": s.get("index", i), "start": s["start"], "end": s["end"],
                        "narration": s.get("narration", ""),
                        "pause_after_ms": s.get("pause_after_ms", 0),
                        "overlaps_speech": s.get("overlaps_speech", False),
                        "emotion": s.get("emotion", "")}
                       for i, s in enumerate(raw)]
            return JSONResponse({"segments": wrapped})
        return JSONResponse(raw)
    return JSONResponse({}, status_code=404)


@router.get("/tasks/文案脚本.json")
def api_script_file(task: str = Query(None)):
    task_name = task or args.task
    script_file = resolve_task_dir(task_name) / "文案脚本.json"
    if not script_file.exists():
        script_file = PROJECT_DIR / "tasks" / "文案脚本.json"
    if script_file.exists():
        return JSONResponse(json.load(open(script_file)))
    return JSONResponse({"ok": False, "error": "文案脚本尚未生成"}, status_code=404)


@router.get("/storyboard.json")
def api_storyboard(task: str = Query(None)):
    """分镜脚本（扣子/WorkBuddy 导入的全局分镜，含 shot_sequence）"""
    task_name = task or args.task
    sb_file = resolve_task_dir(task_name) / "storyboard.json"
    if not sb_file.exists():
        sb_file = PROJECT_DIR / "tasks" / "storyboard.json"
    if sb_file.exists():
        data = json.load(open(sb_file))
        # 附文件 mtime：前端轮询检测外部导入的新脚本（只提示，不自动替换）
        data["_mtime"] = int(sb_file.stat().st_mtime)
        return JSONResponse(data)
    return JSONResponse({"ok": False, "error": "分镜脚本尚未导入"}, status_code=404)


@router.get("/vlm/lookup")
def api_vlm_lookup(ep: int = Query(...), sec: float = Query(...)):
    """按剧集+秒数查找命中的 VLM 场景段详情（分镜台核对镜头用）

    复用 lib.vlm_cache.load()（scene_map time_range + VLM 描述合并后的内存缓存），
    返回 start <= sec < end 的段；无命中时返回时间上最近的一段。
    """
    from lib.vlm_cache import load as load_vlm
    try:
        cache = load_vlm()
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"VLM 缓存未初始化: {e}"}, status_code=500)

    ep_scenes = cache.get(ep)
    if not ep_scenes:
        return JSONResponse({"ok": False, "error": f"EP{ep} 无 VLM 缓存"}, status_code=404)

    hit = None
    for idx in sorted(ep_scenes):
        s = ep_scenes[idx]
        if s["start"] <= sec < s["end"]:
            hit = s
            break
    if hit is None:
        hit = min(ep_scenes.values(), key=lambda s: abs(s["start"] - sec))

    return {"ok": True, "ep": ep, "sec": sec, "scene": hit, "total_scenes": len(ep_scenes)}
