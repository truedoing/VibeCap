"""路由: 导出"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from config import args

router = APIRouter(prefix="/export", tags=["导出"])


@router.post("/extract_clips")
async def api_export_extract_clips(request: Request):
    from handlers.media import export_extract_clips
    data = await request.json()
    task_name = data.get("task", args.task)
    clips = data.get("clips", [])
    if not clips:
        return JSONResponse({"ok": False, "error": "no clips provided"}, status_code=400)
    return export_extract_clips(task_name, clips)
