"""选题推荐 API — GET /topics/recommend

带进程内缓存（按剧名），第一次实时计算（40-120s），之后秒开。
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import project_name, PROJECT_DIR, project_config

router = APIRouter(prefix="/topics", tags=["选题推荐"])

# 进程内缓存：{drama_name: {"result": {...}, "timestamp": ...}}
_cache = {}


@router.get("/recommend")
async def api_recommend_topics(drama: str = None):
    from handlers.topics import recommend_topics

    drama_name = drama or project_name
    total_episodes = project_config.get("episodes", 46)

    # 缓存命中直接返回
    if drama_name in _cache:
        return JSONResponse(_cache[drama_name]["result"])

    # 实时计算并缓存
    result = recommend_topics(PROJECT_DIR, drama_name, total_episodes)
    if result.get("ok"):
        _cache[drama_name] = {"result": result, "timestamp": __import__("time").time()}
    return JSONResponse(result)
