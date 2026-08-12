"""路由: 配音台 SSE 端点"""
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from config import args
from lib.sse import sse_stream

router = APIRouter(prefix="/voiceover", tags=["配音台 SSE"])


@router.post("/generate_stream")
async def api_voiceover_generate(request: Request):
    """配音师Agent SSE — 脚本→配音方案→TTS生成"""
    from handlers.voiceover import generate_voiceover

    data = await request.json()
    task_name = data.get("task", args.task)
    voice = data.get("voice", "default_zh")
    speed = float(data.get("speed", 1.0))
    pause_ms = int(data.get("pause_ms", 300))
    ref_audio_path = data.get("ref_audio_path", None)

    def _run(task_name, emit):
        def emit_progress(step, msg, data=None):
            emit("progress", {"step": step, "status": "running", "msg": msg, **(data or {})})
        def emit_complete(result): emit("complete", result)
        def emit_error(error, detail=""): emit("error", {"error": error, "detail": detail})
        generate_voiceover(
            task_name=task_name, voice=voice, speed=speed, pause_ms=pause_ms,
            ref_audio_path=ref_audio_path,
            emit_progress=emit_progress, emit_complete=emit_complete, emit_error=emit_error)

    return StreamingResponse(sse_stream(_run, task_name), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})
