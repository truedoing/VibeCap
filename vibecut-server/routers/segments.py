"""路由: 分段 + 旁白 + 脚本文件"""
import json
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from config import project_name, project_type, PROJECT_DIR, args, resolve_task_dir
from routers._lifespan import db

router = APIRouter(tags=["分段"])


@router.get("/segments.json")
def api_segments(task: str = Query(None)):
    """任务分段 (DB→文件fallback)"""
    task_name = task or args.task
    drama_id = db.get_drama_id(project_name)
    if drama_id:
        task_obj = db.get_task(drama_id, task_name)
        if task_obj:
            segments = db.get_task_segments(task_obj["id"])
            if segments and len(segments) > 0:
                result = {"segments": segments, "total_segments": len(segments),
                          "project_type": project_type}
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
    seg_file = resolve_task_dir(task_name) / "segments.json"
    if seg_file.exists():
        data = json.load(open(seg_file))
        data["project_type"] = project_type
        return JSONResponse(data)

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
