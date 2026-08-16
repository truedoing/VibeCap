"""
vibecut-server/tts_engine.py — 统一 TTS 引擎 v2.0

MiMo API TTS: 云端 TTS, 支持预设音色和声音克隆。

用法:
  from tts_engine import generate_speech
  result = generate_speech("测试", out_path, voice="白桦", ref_audio_path="...")
"""

import base64
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

# ── 预设音色 (MiMo mimo-v2.5-tts 模型, 中文音色名) ──
PRESET_VOICES = {
    "冰糖": {"voice": "冰糖", "label": "冰糖 (活泼少女)"},
    "茉莉": {"voice": "茉莉", "label": "茉莉 (知性女声)"},
    "苏打": {"voice": "苏打", "label": "苏打 (阳光少年)"},
    "白桦": {"voice": "白桦", "label": "白桦 (成熟男声)"},
}


def generate_speech(text: str, out_path: str, *,
                    voice: str = "白桦",
                    speed: float = 1.0,
                    ref_audio_path: str = None,
                    ref_text: str = None,
                    style_hint: str = None,
                    output_format: str = "wav",
                    timeout: int = 600,
                    retries: int = 1,
                    ) -> dict:
    """TTS 语音合成 (MiMo API)

    Returns: {"ok": True, "path": str, "duration": float, "engine": str}
    """
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    return _generate_mimo(text, out_path, voice=voice, speed=speed,
                          ref_audio_path=ref_audio_path,
                          ref_text=ref_text,
                          style_hint=style_hint,
                          output_format=output_format,
                          timeout=min(timeout, 120), retries=retries)


# ═══ MiMo API ═══

def _generate_mimo(text: str, out_path: str, *,
                   voice: str = "白桦",
                   speed: float = 1.0,
                   ref_audio_path: str = None,
                   ref_text: str = None,
                   style_hint: str = None,
                   output_format: str = "wav",
                   timeout: int = 120,
                   retries: int = 2) -> dict:
    """MiMo TTS (双模型)

    - 有 ref_audio_path → mimo-v2.5-tts-voiceclone (音色克隆, voice=DataURL)
    - 无 ref_audio_path → mimo-v2.5-tts (预设音色, voice=中文音色名)
    """
    # 语音独立 key, fallback 到通用 MIMO_API_KEY
    api_key = os.environ.get("MIMO_TTS_API_KEY", "") or os.environ.get("MIMO_API_KEY", "")
    if not api_key:
        return {"ok": False, "error": "未配置 MIMO_TTS_API_KEY / MIMO_API_KEY", "engine": "mimo"}

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

    # ── 音色克隆 vs 预设音色 ──
    if ref_audio_path and os.path.exists(ref_audio_path):
        # 克隆模式: voice 字段放 DataURL 音频
        with open(ref_audio_path, "rb") as f:
            ab = f.read()
        if len(ab) > 10 * 1024 * 1024:
            ab = ab[:10 * 1024 * 1024]
        ext = os.path.splitext(ref_audio_path)[1].lstrip(".").lower()
        mime = "mpeg" if ext == "mp3" else "wav"
        model = "mimo-v2.5-tts-voiceclone"
        audio_config = {
            "format": output_format,
            "voice": f"data:audio/{mime};base64,{base64.b64encode(ab).decode()}",
        }
    else:
        # 预设音色模式: voice 字段放中文音色名 (冰糖/茉莉/苏打/白桦)
        model = "mimo-v2.5-tts"
        preset = PRESET_VOICES.get(voice, {"voice": voice})
        audio_config = {"format": output_format, "voice": preset["voice"]}

    payload = json.dumps({"model": model, "messages": messages, "audio": audio_config}).encode()

    last_error = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                f"{api_url}/chat/completions", data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                r = json.loads(resp.read())
            audio_b64 = r["choices"][0]["message"]["audio"]["data"]
            out_bytes = base64.b64decode(audio_b64)
            with open(out_path, "wb") as f:
                f.write(out_bytes)
            dur = _get_audio_duration(out_path)
            return {"ok": True, "path": out_path, "duration": dur,
                    "size": len(out_bytes), "engine": "mimo"}
        except urllib.error.HTTPError as e:
            code = e.code
            body = e.read().decode()
            last_error = f"HTTP {code}: {body[:200]}"
            # 429 限流: 指数退避 (60s, 120s...)
            if code == 429 and attempt < retries:
                wait = 60 * (attempt + 1)
                print(f"[mimo] 429 限流, {wait}s 后重试 ({attempt+1}/{retries})...")
                time.sleep(wait)
                continue
        except Exception as e:
            last_error = str(e)[:200]
        if attempt < retries and "429" not in last_error:
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
