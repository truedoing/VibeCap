"""路由: AI 端点 (非流式)"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/script", tags=["AI"])


@router.post("/chat")
async def api_chat(request: Request):
    from handlers.dialogue import chat
    data = await request.json()
    return chat(data.get("messages", []), data.get("context", {}), data.get("eps", None))


@router.post("/dialogue_match")
async def api_dialogue_match(request: Request):
    from handlers.dialogue import dialogue_match
    data = await request.json()
    return dialogue_match(data.get("dialogue", ""))


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


@router.post("/script/analyze_transcript")
async def api_analyze_transcript(request: Request):
    from handlers.storyboard import analyze_transcript
    data = await request.json()
    return analyze_transcript(data.get("transcript", ""))


@router.post("/script/generate_from_outline")
async def api_generate_from_outline(request: Request):
    from handlers.storyboard import generate_from_outline
    data = await request.json()
    return generate_from_outline(
        data.get("topic", ""), data.get("outline", []), data.get("transcript", ""))


@router.post("/script/generate_script")
async def api_generate_script(request: Request):
    from handlers.script_gen import generate_script
    data = await request.json()
    topic = data.get("topic", "").strip()
    if not topic:
        return JSONResponse({"ok": False, "error": "请提供视频主题"}, status_code=400)
    return generate_script(topic)
