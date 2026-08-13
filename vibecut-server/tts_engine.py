"""
vibecut-server/tts_engine.py — 统一 TTS 引擎 v2.0

双引擎:
  F5-TTS (主):   零样本音色克隆, 通过 f5_worker.py 常驻子进程调用
  MiMo API (备):  云端 TTS, 速度快, 支持预设音色和声音克隆

用法:
  from tts_engine import generate_speech, ensure_f5_worker, shutdown_f5_worker
  result = generate_speech("测试", out_path, voice="default_zh", ref_audio_path="...")
"""

import atexit
import base64
import json
import os
import select
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

# ── 预设音色 ──
PRESET_VOICES = {
    "default_zh":       {"voice": "default_zh",       "label": "默认女声"},
    "narrator_male":    {"voice": "narrator_male",    "label": "沉稳男声"},
    "narrator_female":  {"voice": "narrator_female",  "label": "温柔女声"},
    "storyteller_male": {"voice": "storyteller_male", "label": "激昂男声"},
}

# ── F5 Worker 常量 ──
F5_WORKER_SCRIPT = str(Path(__file__).resolve().parent / "lib" / "f5_worker.py")
F5_PYTHON = "/opt/anaconda3/envs/cosyvoice/bin/python3"
F5_DEFAULT_REF_AUDIO = "/Users/zgl/VIBECAP/都挺好/tasks/Task0804/work_dir/解说音频_30s.wav"
F5_DEFAULT_REF_TEXT = "如果一个男人，没家庭，没事业、没道德、那他就没有弱点。他不光窝里横，在外边他也照样狂。"
F5_NFE_STEP = 32
F5_SPEED = 1.05

# ── 全局 Worker 锁 ──
_f5_lock = threading.Lock()
_f5_proc: subprocess.Popen | None = None
_f5_loaded = False


def ensure_f5_worker(timeout: float = 120) -> bool:
    """确保 F5 worker 进程已启动且模型已加载（幂等）"""
    global _f5_proc, _f5_loaded
    with _f5_lock:
        if _f5_proc is not None and _f5_loaded:
            # 检查进程是否还活着
            if _f5_proc.poll() is not None:
                _f5_proc = None
                _f5_loaded = False
            else:
                return True

        if _f5_proc is None:
            _f5_proc = subprocess.Popen(
                [F5_PYTHON, "-u", F5_WORKER_SCRIPT],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True, bufsize=1,
            )

        # 发送 load_model
        _f5_proc.stdin.write(json.dumps({"action": "load_model"}) + "\n")
        _f5_proc.stdin.flush()

        ready, _, _ = select.select([_f5_proc.stdout], [], [], timeout)
        if ready:
            resp = json.loads(_f5_proc.stdout.readline())
            if resp.get("ok"):
                _f5_loaded = True
                return True

        return False


def shutdown_f5_worker():
    """关闭 F5 worker"""
    global _f5_proc, _f5_loaded
    with _f5_lock:
        if _f5_proc and _f5_proc.poll() is None:
            try:
                _f5_proc.stdin.write(json.dumps({"action": "quit"}) + "\n")
                _f5_proc.stdin.flush()
                _f5_proc.wait(timeout=5)
            except Exception:
                _f5_proc.kill()
        _f5_proc = None
        _f5_loaded = False


atexit.register(shutdown_f5_worker)


def generate_speech(text: str, out_path: str, *,
                    voice: str = "default_zh",
                    speed: float = 1.0,
                    ref_audio_path: str = None,
                    ref_text: str = None,
                    style_hint: str = None,
                    output_format: str = "wav",
                    timeout: int = 600,
                    retries: int = 1,
                    engine: str = "auto",
                    ) -> dict:
    """TTS 语音合成

    Returns: {"ok": True, "path": str, "duration": float, "engine": str}
    """
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    if engine == "auto":
        if ref_audio_path and os.path.exists(ref_audio_path):
            engine = "f5"
        else:
            engine = "mimo"

    if engine == "f5":
        return _generate_f5(text, out_path, voice=voice,
                            ref_audio_path=ref_audio_path,
                            ref_text=ref_text,
                            speed=speed, timeout=timeout)
    return _generate_mimo(text, out_path, voice=voice, speed=speed,
                          ref_audio_path=ref_audio_path,
                          style_hint=style_hint,
                          output_format=output_format,
                          timeout=min(timeout, 120), retries=retries)


# ═══ F5-TTS ═══

def _generate_f5(text: str, out_path: str, *,
                 voice: str = "default_zh",
                 ref_audio_path: str = None,
                 ref_text: str = None,
                 speed: float = 1.0,
                 timeout: int = 600) -> dict:
    global _f5_proc

    ref_audio = ref_audio_path or F5_DEFAULT_REF_AUDIO
    if not os.path.exists(ref_audio):
        return {"ok": False, "error": f"参考音频不存在: {ref_audio}", "engine": "f5"}

    ref_t = ref_text or text  # 没提供 ref_text 则用 gen_text (短文本可接受)

    out_abs = str(Path(out_path).resolve())

    with _f5_lock:
        if not ensure_f5_worker(timeout=30):
            return {"ok": False, "error": "F5 worker 未就绪", "engine": "f5"}

        _f5_proc.stdin.write(json.dumps({
            "action": "infer",
            "ref_audio": ref_audio,
            "ref_text": ref_t,
            "gen_text": text,
            "out_path": out_abs,
            "speed": speed,
        }, ensure_ascii=False) + "\n")
        _f5_proc.stdin.flush()

    ready, _, _ = select.select([_f5_proc.stdout], [], [], timeout)
    if not ready:
        return {"ok": False, "error": f"F5 推理超时 ({timeout}s)", "engine": "f5"}

    try:
        resp = json.loads(_f5_proc.stdout.readline())
    except json.JSONDecodeError:
        return {"ok": False, "error": "F5 worker 返回异常", "engine": "f5"}

    if resp.get("ok"):
        return {
            "ok": True, "path": out_abs,
            "duration": round(resp["duration"], 2),
            "size": resp.get("size", 0),
            "engine": "f5",
        }
    return {"ok": False, "error": resp.get("error", "F5 推理失败"), "engine": "f5"}


# ═══ MiMo API ═══

def _generate_mimo(text: str, out_path: str, *,
                   voice: str = "default_zh",
                   speed: float = 1.0,
                   ref_audio_path: str = None,
                   style_hint: str = None,
                   output_format: str = "wav",
                   timeout: int = 120,
                   retries: int = 2) -> dict:
    api_key = os.environ.get("MIMO_API_KEY", "")
    if not api_key:
        return {"ok": False, "error": "未配置 MIMO_API_KEY", "engine": "mimo"}

    api_url = os.environ.get("MIMO_API_URL", "https://api.xiaomimimo.com/v1")

    messages = []
    hints = []
    if style_hint:
        hints.append(style_hint)
    if speed != 1.0:
        hints.append(f"语速{'放慢' if speed < 1 else '加快'}至{speed:.1f}x")
    if hints:
        messages.append({"role": "user", "content": "；".join(hints)})
    messages.append({"role": "assistant", "content": text})

    audio_config = {"format": output_format, "voice": voice}
    if ref_audio_path and os.path.exists(ref_audio_path):
        with open(ref_audio_path, "rb") as f:
            ab = f.read()
        if len(ab) > 10 * 1024 * 1024:
            ab = ab[:10 * 1024 * 1024]
        ext = os.path.splitext(ref_audio_path)[1].lstrip(".").lower()
        mime = "mp3" if ext == "mp3" else "wav"
        audio_config["input_audio"] = f"data:audio/{mime};base64,{base64.b64encode(ab).decode()}"

    payload = json.dumps({"model": "mimo-v2.5-tts-voiceclone", "messages": messages, "audio": audio_config}).encode()

    last_error = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                f"{api_url}/chat/completions", data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                r = json.loads(resp.read())
            audio_b64 = r["choices"][0]["message"]["audio"]["data"]
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(audio_b64))
            dur = _get_audio_duration(out_path)
            return {"ok": True, "path": out_path, "duration": dur, "size": len(base64.b64decode(audio_b64)), "engine": "mimo"}
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code} {e.reason}: {e.read().decode()[:200]}"
        except Exception as e:
            last_error = str(e)[:200]
        if attempt < retries:
            time.sleep(2.0 * (attempt + 1))
    return {"ok": False, "error": last_error or "未知错误", "engine": "mimo"}


def _get_audio_duration(path: str) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", path],
                           capture_output=True, text=True, timeout=10)
        return float(r.stdout.strip())
    except Exception:
        return 0.0
