"""路由: 编剧台 SSE 流式端点 (drama V2 单 LLM)"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional
from config import project_name, args
from lib.sse import sse_stream, make_emitter

router = APIRouter(prefix="/script", tags=["编剧台 SSE"])


class DramaScriptRequest(BaseModel):
    topic: str
    episodes: Optional[list[int]] = None
    target_duration: int = 480
    drama: Optional[str] = None
    thesis: Optional[dict] = None


@router.post("/generate_drama_script_v2")
async def api_generate_drama_script_v2(body: DramaScriptRequest):
    """编剧台 V2 SSE — 单 LLM + 方法论一次产出完整解说脚本"""
    from handlers.script_drama import generate_drama_script_v2

    topic = body.topic.strip()
    if not topic:
        return JSONResponse({"ok": False, "error": "请提供选题描述 (topic)"}, status_code=400)

    drama_name = body.drama or project_name

    def _run(topic, emit):
        emit_progress, emit_complete, emit_error = make_emitter(emit)
        generate_drama_script_v2(
            topic=topic, emit_progress=emit_progress, emit_complete=emit_complete,
            emit_error=emit_error, drama_name=drama_name,
            target_duration=body.target_duration)

    return StreamingResponse(sse_stream(_run, topic), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})
