"""路由: 配音台端点（音色库 + TTS 生成）"""
from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse
from config import args
from lib.sse import sse_stream, make_emitter

router = APIRouter(prefix="/voiceover", tags=["配音台"])


@router.get("/voices")
def api_list_voices():
    """列出所有音色（预设 + 克隆）"""
    from lib.voice_store import list_voices
    return {"ok": True, "voices": list_voices()}


@router.post("/create_voice")
async def api_create_voice(
    name: str = Form(...),
    ref_text: str = Form(""),
    audio: UploadFile = File(...),
):
    """新建克隆音色（全局共享）。上传参考音频 + 音色名。"""
    from pathlib import Path
    from lib.voice_store import create_clone_voice, GLOBAL_VOICES_DIR

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
    """全量配音 SSE — 规则驱动方案 + 逐段 TTS 生成"""
    from handlers.voiceover import generate_voiceover

    data = await request.json()
    task_name = data.get("task", args.task)
    voice = data.get("voice", "白桦")
    speed = float(data.get("speed", 1.0))
    pause_ms = int(data.get("pause_ms", 300))

    def _run(task_name, emit):
        emit_progress, emit_complete, emit_error = make_emitter(emit)
        generate_voiceover(
            task_name=task_name, voice=voice, speed=speed, pause_ms=pause_ms,
            emit_progress=emit_progress, emit_complete=emit_complete, emit_error=emit_error)

    return StreamingResponse(sse_stream(_run, task_name), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@router.post("/regenerate_segment")
async def api_regenerate_segment(request: Request):
    """单段重生成 SSE — 重新合成指定段落的配音"""
    from handlers.voiceover import regenerate_segment

    data = await request.json()
    task_name = data.get("task", args.task)
    seg_id = data["seg_id"]
    voice = data.get("voice")
    speed = data.get("speed")

    def _run(task_name, emit):
        emit_progress, emit_complete, emit_error = make_emitter(emit)
        regenerate_segment(
            task_name=task_name, seg_id=seg_id, voice=voice,
            emotion=None, speed=speed, pause_ms=None, ref_audio_path=None,
            emit_progress=emit_progress, emit_complete=emit_complete, emit_error=emit_error)

    return StreamingResponse(sse_stream(_run, task_name), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})
