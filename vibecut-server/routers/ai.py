"""路由: 分镜台导演 Agent (storyboard_suggest)

注意: 端点挂在根路径 /storyboard_suggest（前端直接 fetch 此路径）。
"""
from fastapi import APIRouter, Request

router = APIRouter(tags=["分镜"])


@router.post("/storyboard_suggest")
async def api_storyboard_suggest(request: Request):
    from handlers.storyboard import storyboard_suggest
    data = await request.json()
    return storyboard_suggest(
        data.get("narration", ""),
        segment_context=data.get("segment_context"),
        cover=data.get("cover", ""),
        prev_highlight=data.get("prev_highlight", ""),
        next_highlight=data.get("next_highlight", ""),
        focus_episodes=data.get("focus_episodes", []),
    )
