"""路由: 编剧台 SSE 流式端点"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional
from config import project_name, args
from lib.sse import sse_stream

router = APIRouter(prefix="/script", tags=["编剧台 SSE"])


@router.post("/generate_script_stream")
async def api_generate_script_stream(request: Request):
    """v3 Agent 流水线 SSE"""
    data = await request.json()
    topic = data.get("topic", "").strip()
    if not topic:
        return JSONResponse({"ok": False, "error": "请提供视频主题"}, status_code=400)

    from handlers.script_gen import generate_script_stream

    def _run(topic, emit):
        def emit_progress(step, msg, data=None):
            emit("progress", {"step": step, "status": "running", "msg": msg, **(data or {})})
        def emit_complete(result): emit("complete", result)
        def emit_error(error, detail=""): emit("error", {"error": error, "detail": detail})
        generate_script_stream(topic, emit_progress, emit_complete, emit_error)

    return StreamingResponse(sse_stream(_run, topic), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@router.post("/generate_story_first")
async def api_generate_story_first(request: Request):
    """v4 故事优先 SSE"""
    data = await request.json()
    topic = data.get("topic", "").strip()
    if not topic:
        return JSONResponse({"ok": False, "error": "请提供视频主题"}, status_code=400)

    from handlers.script_gen import generate_story_first

    def _run(topic, emit):
        def emit_progress(step, msg, data=None):
            emit("progress", {"step": step, "status": "running", "msg": msg, **(data or {})})
        def emit_complete(result): emit("complete", result)
        def emit_error(error, detail=""): emit("error", {"error": error, "detail": detail})
        generate_story_first(topic, emit_progress, emit_complete, emit_error)

    return StreamingResponse(sse_stream(_run, topic), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@router.post("/refine")
async def api_refine(request: Request):
    """精切 SSE"""
    from handlers.script_gen import refine_segments

    def _run(task_name, emit):
        def emit_progress(step, msg, data=None):
            emit("progress", {"step": step, "status": "running", "msg": msg, **(data or {})})
        def emit_complete(result): emit("complete", result)
        def emit_error(error, detail=""): emit("error", {"error": error, "detail": detail})
        refine_segments(task_name, emit_progress, emit_complete, emit_error)

    return StreamingResponse(sse_stream(_run, args.task), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


class DramaScriptRequest(BaseModel):
    topic: str
    episodes: Optional[list[int]] = None
    target_duration: int = 480
    drama: Optional[str] = None
    thesis: Optional[dict] = None


@router.post("/generate_thesis")
async def api_generate_thesis(body: DramaScriptRequest):
    """论点阶段（普通 JSON，非 SSE）— 产出候选论点 + 装置，供人拍板。

    返回 {"ok": true, "candidates": [{thesis, device, why_not_common, ...}], "story_map": {...}}
    """
    from handlers.script_drama import generate_thesis

    topic = body.topic.strip()
    if not topic:
        return JSONResponse({"ok": False, "error": "请提供选题描述 (topic)"}, status_code=400)

    drama_name = body.drama or project_name
    return JSONResponse(generate_thesis(topic, drama_name))


@router.post("/generate_drama_script")
async def api_generate_drama_script(body: DramaScriptRequest):
    """编剧Agent SSE — 电视剧解说脚本生成"""
    from handlers.script_drama import generate_drama_script

    topic = body.topic.strip()
    if not topic:
        return JSONResponse({"ok": False, "error": "请提供选题描述 (topic)"}, status_code=400)

    drama_name = body.drama or project_name

    def _run(topic, emit):
        def emit_progress(step, msg, data=None):
            emit("progress", {"step": step, "status": "running", "msg": msg, **(data or {})})
        def emit_complete(result): emit("complete", result)
        def emit_error(error, detail=""): emit("error", {"error": error, "detail": detail})
        generate_drama_script(
            topic=topic, emit_progress=emit_progress, emit_complete=emit_complete,
            emit_error=emit_error, drama_name=drama_name,
            focus_episodes=body.episodes, target_duration=body.target_duration,
            thesis=body.thesis)

    return StreamingResponse(sse_stream(_run, topic), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})
