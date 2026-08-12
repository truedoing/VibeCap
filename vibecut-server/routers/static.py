"""路由: 静态文件 + SPA fallback (必须最后注册)"""
from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from fastapi import HTTPException
from config import resolve_task_dir, args

router = APIRouter(tags=["静态文件"])


@router.get("/{filename:path}")
def api_task_static(filename: str, task: str = Query(None)):
    """任务目录下的各类文件（docx, json, mp4, wav 等）"""
    task_name = task or args.task
    from handlers.static import get_static_file
    file_path, mime = get_static_file(resolve_task_dir(task_name), f"/{filename}")
    if file_path:
        return FileResponse(file_path, media_type=mime)
    raise HTTPException(404)
