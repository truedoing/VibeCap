"""路由: 搜索 + 状态检查"""
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from config import project_name, project_type, args

router = APIRouter(tags=["搜索"])


@router.get("/status")
def health_check():
    return {
        "status": "ok",
        "project": project_name,
        "type": project_type,
        "task": args.task,
        "version": "1.3.0",
    }


@router.get("/search")
def api_search(
    q: str = Query(""),
    mode: str = Query("hybrid"),
    limit: int = Query(10),
    eps: str = Query(None),
):
    from handlers.search import search
    return search(q, limit=limit, mode=mode, eps=eps)
