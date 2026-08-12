"""路由: Picks 同步"""
from fastapi import APIRouter, Request
from config import project_name, args
from routers._lifespan import db

router = APIRouter(tags=["Picks"])


@router.post("/picks")
async def api_picks(request: Request):
    """同步 picks 到 SQLite"""
    data = await request.json()
    drama_name = data.get("drama", project_name)
    task_name = data.get("task", args.task)
    picks = data.get("picks", [])

    drama_id = db.get_drama_id(drama_name)
    if not drama_id:
        drama_id = db.ensure_drama(drama_name)

    existing = db.get_task(drama_id, task_name)
    if existing:
        task_id = existing["id"]
    else:
        task_id = db.create_task(drama_id, task_name)

    picks_map = {}
    for p in picks:
        seg_id = p.get("seg_id")
        if seg_id is not None:
            picks_map[seg_id] = p

    segments = db.get_task_segments(task_id)
    for seg in segments:
        sid = seg.get("seg_id")
        if sid in picks_map:
            seg["picked"] = picks_map[sid]

    db.save_task_segments(task_id, segments)
    return {"ok": True, "synced": len(picks)}
