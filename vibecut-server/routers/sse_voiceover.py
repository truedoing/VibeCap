"""路由: 配音台 SSE 端点"""
from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse
from config import args
from lib.sse import sse_stream

router = APIRouter(prefix="/voiceover", tags=["配音台 SSE"])


@router.get("/voices")
def api_list_voices():
    """列出所有音色（预设 + 克隆）"""
    from handlers.voiceover import list_voices
    return {"ok": True, "voices": list_voices()}


@router.post("/create_voice")
async def api_create_voice(
    name: str = Form(...),
    ref_text: str = Form(""),
    audio: UploadFile = File(...),
):
    """新建克隆音色（全局共享）。上传参考音频 + 音色名。"""
    from pathlib import Path
    from handlers.voiceover import create_clone_voice, GLOBAL_VOICES_DIR

    ext = Path(audio.filename or "").suffix.lower() or ".wav"
    if ext not in (".wav", ".mp3"):
        return JSONResponse({"ok": False, "error": f"仅支持 wav/mp3，收到: {ext}"}, status_code=400)

    GLOBAL_VOICES_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_") or "voice"
    save_path = GLOBAL_VOICES_DIR / f"ref_{safe_name}{ext}"
    save_path.write_bytes(await audio.read())

    result = create_clone_voice(name, str(save_path), ref_text)
    return JSONResponse(result)


@router.post("/generate_stream")
async def api_voiceover_generate(request: Request):
    """配音师Agent SSE — 脚本→配音方案→TTS生成"""
    from handlers.voiceover import generate_voiceover

    data = await request.json()
    task_name = data.get("task", args.task)
    voice = data.get("voice", "白桦")
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
    voice = data.get("voice", "白桦")
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
