#!/usr/bin/env python3
"""
A2: 对解说音频做本地 ASR → 带时间戳的文本（faster-whisper）

输入: 解说音频.wav
输出: narration_asr.json — [{start, end, text}, ...]
"""

import sys, os, json, subprocess
from pathlib import Path

BASE_DIR = Path("/Users/zgl/VIBECAP")
DRAMA_DIR = BASE_DIR / os.environ.get("VIBECAP_DRAMA", "都挺好")
TASK_DIR = DRAMA_DIR / "tasks" / os.environ.get("VIBECAP_TASK", "Task7024")
AUDIO_PATH = TASK_DIR / "解说音频.wav"
OUTPUT_PATH = TASK_DIR / "narration_asr.json"


def main():
    if not AUDIO_PATH.exists():
        print(f"❌ 解说音频不存在: {AUDIO_PATH}")
        sys.exit(1)

    print(f"解说音频: {AUDIO_PATH}")

    # 转换为 16kHz 单声道
    audio_16k = TASK_DIR / "work_dir" / "narration_16k.wav"
    audio_16k.parent.mkdir(exist_ok=True)

    if not audio_16k.exists():
        print("转换为 16kHz 单声道...")
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(AUDIO_PATH),
             "-ar", "16000", "-ac", "1", str(audio_16k)],
            capture_output=True
        )

    # 本地 faster-whisper 转写
    print("ASR 转写中 (faster-whisper base)...")
    from faster_whisper import WhisperModel

    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments_out, info = model.transcribe(str(audio_16k), language="zh", beam_size=5)

    segments = []
    for seg in segments_out:
        segments.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip()
        })

    # 保存
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)

    total_text = " ".join(s["text"] for s in segments if s["text"])
    empty_count = sum(1 for s in segments if not s["text"])
    print(f"\n✅ A2 完成: {len(segments)} 段, 共 {len(total_text)} 字")
    if empty_count:
        print(f"   ⚠️ {empty_count} 段无文本（静音）")

    # 打印每段结果
    for s in segments:
        preview = s["text"][:80] + "..." if len(s["text"]) > 80 else s["text"]
        print(f"   [{s['start']:6.1f}s - {s['end']:6.1f}s] {preview}")


if __name__ == "__main__":
    main()
