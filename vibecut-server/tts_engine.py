"""
vibecut-server/tts_engine.py — 统一 TTS 引擎 v1.0

重构自 tts_voice_clone.py，模块化为可调用库。
支持默认音色 + 声音克隆双模式。

用法:
    from tts_engine import generate_speech
    result = generate_speech("测试文本", "/tmp/out.wav", voice="default_zh")
    if result["ok"]:
        print(f"duration={result['duration']:.1f}s")
"""

import base64
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

# ── 预设音色表 ──
PRESET_VOICES = {
    "default_zh":         {"voice": "default_zh",         "label": "默认女声"},
    "narrator_male":      {"voice": "narrator_male",      "label": "沉稳男声"},
    "narrator_female":    {"voice": "narrator_female",    "label": "温柔女声"},
    "storyteller_male":   {"voice": "storyteller_male",   "label": "激昂男声"},
}


def generate_speech(text: str, out_path: str, *,
                    voice: str = "default_zh",
                    speed: float = 1.0,
                    ref_audio_path: str = None,
                    style_hint: str = None,
                    output_format: str = "wav",
                    timeout: int = 120,
                    retries: int = 2,
                    ) -> dict:
    """TTS 语音合成 (MiMo API)

    Args:
        text: 要合成的文本
        out_path: 输出音频路径
        voice: 预设音色 ID (default_zh / narrator_male / narrator_female / storyteller_male)
        speed: 语速倍率 (通过 style_hint 传递)
        ref_audio_path: 可选参考音频路径 (触发声音克隆)
        style_hint: 可选情绪/风格指导
        output_format: wav 或 mp3
        timeout: API 超时秒数
        retries: 重试次数

    Returns:
        {"ok": True, "path": str, "duration": float} |
        {"ok": False, "error": str}
    """
    api_key = os.environ.get("MIMO_API_KEY", "")
    if not api_key:
        return {"ok": False, "error": "未配置 MIMO_API_KEY"}

    api_url = os.environ.get("MIMO_API_URL", "https://api.xiaomimimo.com/v1")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    # ── 构建 messages ──
    messages = []

    # 速度指令
    speed_hint = ""
    if speed != 1.0:
        if speed < 1.0:
            speed_hint = f"语速放慢至{speed:.1f}x，咬字清晰"
        else:
            speed_hint = f"语速加快至{speed:.1f}x，保持自然"

    if style_hint or speed_hint:
        hint_parts = []
        if style_hint:
            hint_parts.append(style_hint)
        if speed_hint:
            hint_parts.append(speed_hint)
        messages.append({"role": "user", "content": "；".join(hint_parts)})

    messages.append({"role": "assistant", "content": text})

    # ── 构建 payload ──
    audio_config = {"format": output_format, "voice": voice}

    if ref_audio_path and os.path.exists(ref_audio_path):
        # 声音克隆模式
        with open(ref_audio_path, "rb") as f:
            audio_bytes = f.read()
        if len(audio_bytes) > 10 * 1024 * 1024:
            print(f"[tts] ⚠️ 参考音频过大 ({len(audio_bytes)/1024/1024:.1f}MB)")
        ext = os.path.splitext(ref_audio_path)[1].lstrip(".").lower()
        mime = "mp3" if ext == "mp3" else "wav"
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        audio_config["input_audio"] = f"data:audio/{mime};base64,{audio_b64}"

    payload = json.dumps({
        "model": "mimo-v2.5-tts-voiceclone",
        "messages": messages,
        "audio": audio_config,
    }).encode("utf-8")

    # ── 带重试的 API 调用 ──
    last_error = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                f"{api_url}/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())

            # 解析音频
            try:
                audio_data_b64 = result["choices"][0]["message"]["audio"]["data"]
            except (KeyError, IndexError):
                return {"ok": False, "error": f"API 响应格式异常: {json.dumps(result, ensure_ascii=False)[:300]}"}

            output_bytes = base64.b64decode(audio_data_b64)
            with open(out_path, "wb") as f:
                f.write(output_bytes)

            # ── 获取音频时长 ──
            duration = _get_audio_duration(out_path)

            return {"ok": True, "path": out_path, "duration": duration,
                    "size": len(output_bytes)}

        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code} {e.reason}: {e.read().decode()[:200]}"
        except Exception as e:
            last_error = str(e)[:200]

        if attempt < retries:
            time.sleep(2.0 * (attempt + 1))

    return {"ok": False, "error": last_error or "未知错误"}


def _get_audio_duration(path: str) -> float:
    """通过 ffprobe 获取音频时长 (秒)"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0
