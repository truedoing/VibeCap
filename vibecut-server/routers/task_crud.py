"""路由: 任务 CRUD, 剧集列表, 任务列表

/dramas + /tasks 列表需要不加 prefix 挂在根路径。
/tasks/* CRUD 操作使用 prefix。
用两个独立的 router 分别处理。
"""
from fastapi import APIRouter, Request, Form, UploadFile, File, Query
from fastapi.responses import JSONResponse
from config import project_name, args
from routers._lifespan import db

# Router 1: 根路径端点 (无 prefix)
root_router = APIRouter(tags=["项目"])

# Router 2: CRUD 端点
crud_router = APIRouter(prefix="/tasks", tags=["任务"])


# ── 根路径: 剧集和任务列表 ──

@root_router.get("/dramas")
def api_list_dramas():
    from handlers.tasks import list_dramas
    return list_dramas()


@root_router.get("/tasks")
def api_list_tasks(drama: str = Query(None)):
    drama_name = drama or project_name
    from handlers.tasks import list_tasks
    return list_tasks(drama_name)


# ── CRUD: /tasks/* ──

@crud_router.post("/create")
async def api_create_task(
    drama: str = Form(None),
    name: str = Form(None),
    description: str = Form(None),
    local_path: str = Form(None),
    docx: UploadFile = File(None),
    json: UploadFile = File(None),
    audio: UploadFile = File(None),
):
    """创建任务 — 支持 JSON 或 multipart"""
    from handlers.tasks import create_task
    data = {"drama": drama or "", "name": name or "", "local_path": local_path or "",
            "description": description or ""}
    docx_bytes = await docx.read() if docx else None
    json_bytes = await json.read() if json else None
    audio_bytes = await audio.read() if audio else None
    docx_name = docx.filename if docx else "解说文案.docx"
    audio_name = audio.filename if audio else "解说音频.wav"
    return create_task(data, docx_bytes, audio_bytes, docx_name, audio_name, json_bytes=json_bytes)


@crud_router.post("/status")
async def api_update_task_status(request: Request):
    from handlers.tasks import update_task_status
    data = await request.json()
    return update_task_status(
        data.get("drama", project_name), data.get("name", ""), data.get("status", ""))


@crud_router.post("/delete")
async def api_delete_task(request: Request):
    from handlers.tasks import delete_task
    data = await request.json()
    return delete_task(data.get("drama", project_name), data.get("name", ""))
