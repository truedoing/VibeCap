#!/usr/bin/env python3
"""
MiMo TTS 声音克隆 — 用参考音频克隆音色，生成新解说词
模型: mimo-v2.5-tts-voiceclone

用法:
  python3 tts_voice_clone.py \
    --ref work_dir/tts_segments/narr_000.wav \
    --text "测试文本" \
    --out /tmp/cloned_output.wav
"""

import os, sys, json, base64, argparse
import urllib.request

API_KEY = os.environ.get("MIMO_API_KEY", "")
API_URL = os.environ.get("MIMO_API_URL", "https://api.xiaomimimo.com/v1")

if not API_KEY:
    print("❌ 请设置 MIMO_API_KEY 环境变量")
    sys.exit(1)


def clone_and_speak(ref_audio_path: str, text: str, out_path: str,
                    format: str = "wav", style_hint: str = None):
    """
    声音克隆 + 语音合成
    - ref_audio_path: 参考人声音频 (wav/mp3, ≤10MB)
    - text: 要合成的文本
    - format: wav 或 mp3
    - style_hint: 可选的情绪指导，如 "沉稳叙述，略带情感"
    """
    # 读参考音频 → base64
    with open(ref_audio_path, "rb") as f:
        audio_bytes = f.read()
    if len(audio_bytes) > 10 * 1024 * 1024:
        print(f"⚠️  参考音频过大 ({len(audio_bytes)/1024/1024:.1f}MB)，建议 ≤10MB")

    ext = os.path.splitext(ref_audio_path)[1].lstrip(".").lower()
    mime = "mp3" if ext == "mp3" else "wav"
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

    # 构建 messages
    messages = []
    if style_hint:
        messages.append({"role": "user", "content": style_hint})
    messages.append({"role": "assistant", "content": text})

    payload = json.dumps({
        "model": "mimo-v2.5-tts-voiceclone",
        "messages": messages,
        "audio": {
            "format": format,
            "voice": "default_zh",
            "input_audio": f"data:audio/{mime};base64,{audio_b64}"
        }
    }).encode("utf-8")

    print(f"📤 发送请求... (文本: {len(text)} 字, 参考音频: {len(audio_bytes)/1024:.1f}KB)")

    req = urllib.request.Request(
        f"{API_URL}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"❌ API 错误: {e.code} {e.reason}")
        print(e.read().decode()[:500])
        sys.exit(1)

    # 解析响应
    try:
        audio_data_b64 = result["choices"][0]["message"]["audio"]["data"]
    except (KeyError, IndexError) as e:
        print(f"❌ 响应解析失败: {e}")
        print(json.dumps(result, ensure_ascii=False, indent=2)[:500])
        sys.exit(1)

    output_bytes = base64.b64decode(audio_data_b64)
    with open(out_path, "wb") as f:
        f.write(output_bytes)

    print(f"✅ 已保存: {out_path} ({len(output_bytes)/1024:.1f}KB)")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MiMo TTS 声音克隆")
    parser.add_argument("--ref", required=True, help="参考人声音频路径 (wav/mp3)")
    parser.add_argument("--text", required=True, help="要合成的文本")
    parser.add_argument("--out", default="/tmp/cloned_output.wav", help="输出路径")
    parser.add_argument("--format", default="wav", choices=["wav", "mp3"])
    parser.add_argument("--style", default=None, help="情绪/风格指导")
    args = parser.parse_args()

    clone_and_speak(args.ref, args.text, args.out, args.format, args.style)
