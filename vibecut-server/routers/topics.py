"""选题推荐 API — GET /topics/recommend

带磁盘持久化缓存（按剧名）：第一次实时计算（40-120s），之后秒开，进程重启也不重跑。
force=true 时绕过缓存强制重新生成（前端「重新推荐」按钮）。
"""
import json
import time
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import project_name, PROJECT_DIR, project_config

router = APIRouter(prefix="/topics", tags=["选题推荐"])

# 进程内缓存：{drama_name: {"result": {...}, "timestamp": ...}}
_cache = {}


def _cache_file() -> str:
    """磁盘缓存路径（按项目 tasks 目录）"""
    tasks_dir = PROJECT_DIR / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    return tasks_dir / "topic_recommend_cache.json"


def _load_disk_cache() -> dict:
    """读磁盘缓存（进程启动时 / 缓存未命中时调用）"""
    try:
        data = json.load(open(_cache_file()))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_disk_cache(data: dict):
    """写磁盘缓存"""
    try:
        json.dump(data, open(_cache_file(), "w"), ensure_ascii=False, indent=2)
    except Exception:
        pass


@router.get("/recommend")
async def api_recommend_topics(drama: str = None, force: bool = False):
    from handlers.topics import recommend_topics

    drama_name = drama or project_name
    total_episodes = project_config.get("episodes", 46)

    # 进程内缓存命中直接返回
    if not force and drama_name in _cache:
        return JSONResponse(_cache[drama_name]["result"])

    # 磁盘缓存命中直接返回（进程重启后也能秒开）
    if not force:
        disk = _load_disk_cache()
        if drama_name in disk:
            _cache[drama_name] = disk[drama_name]
            return JSONResponse(disk[drama_name]["result"])

    # 实时计算并缓存（内存 + 磁盘）
    result = recommend_topics(PROJECT_DIR, drama_name, total_episodes)
    if result.get("ok"):
        entry = {"result": result, "timestamp": time.time()}
        _cache[drama_name] = entry
        disk = _load_disk_cache()
        disk[drama_name] = entry
        _save_disk_cache(disk)
    return JSONResponse(result)
