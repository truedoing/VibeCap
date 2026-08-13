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
    seg_overrides = data.get("seg_overrides", None)  # {seg_id: {voice, emotion, speed, pauseMs}}

    def _run(task_name, emit):
        def emit_progress(step, msg, data=None):
            emit("progress", {"step": step, "status": "running", "msg": msg, **(data or {})})
        def emit_complete(result): emit("complete", result)
        def emit_error(error, detail=""): emit("error", {"error": error, "detail": detail})
        generate_voiceover(
            task_name=task_name, voice=voice, speed=speed, pause_ms=pause_ms,
            ref_audio_path=ref_audio_path,
            emit_progress=emit_progress, emit_complete=emit_complete, emit_error=emit_error,
            seg_overrides=seg_overrides)

    return StreamingResponse(sse_stream(_run, task_name), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@router.post("/import_audio")
async def api_import_audio(request: Request):
    """导入整段解说音频 SSE — ASR转写 → 文案对齐 → 切分"""
    from handlers.voiceover import import_voiceover_audio

    data = await request.json()
    task_name = data.get("task", args.task)
    audio_path = data.get("audio_path", "")

    def _run(task_name, emit):
        def emit_progress(step, msg, d=None):
            emit("progress", {"step": step, "status": "running", "msg": msg, **(d or {})})
        def emit_complete(result): emit("complete", result)
        def emit_error(error, detail=""): emit("error", {"error": error, "detail": detail})
        import_voiceover_audio(
            task_name=task_name, audio_path=audio_path,
            emit_progress=emit_progress, emit_complete=emit_complete, emit_error=emit_error)

    return StreamingResponse(sse_stream(_run, task_name), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@router.post("/preview_voice")
async def api_preview_voice(request: Request):
    """音色试听 — 生成短样本音频（磁盘缓存）"""
    from handlers.voiceover import preview_voice

    data = await request.json()
    task_name = data.get("task", args.task)
    voice = data.get("voice", "default_zh")
    force = data.get("force", False)
    return preview_voice(task_name, voice, force=force)


@router.post("/regenerate_segment")
async def api_regenerate_segment(request: Request):
    """单段重生成 SSE — 重新合成指定段落的配音"""
    from handlers.voiceover import regenerate_segment

    data = await request.json()
    task_name = data.get("task", args.task)
    seg_id = data["seg_id"]
    voice = data.get("voice")
    emotion = data.get("emotion")
    speed = data.get("speed")
    pause_ms = data.get("pause_ms")
    ref_audio_path = data.get("ref_audio_path")

    def _run(task_name, emit):
        def emit_progress(step, msg, d=None):
            emit("progress", {"step": step, "status": "running", "msg": msg, **(d or {})})
        def emit_complete(result): emit("complete", result)
        def emit_error(error, detail=""): emit("error", {"error": error, "detail": detail})
        regenerate_segment(
            task_name=task_name, seg_id=seg_id,
            voice=voice, emotion=emotion, speed=speed, pause_ms=pause_ms,
            ref_audio_path=ref_audio_path,
            emit_progress=emit_progress, emit_complete=emit_complete, emit_error=emit_error)

    return StreamingResponse(sse_stream(_run, task_name), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})
