#!/usr/bin/env python3
"""
A3: 文案 ↔ ASR 文本匹配 → 切分解说音频 → 生成 narration.json + tts_meta.json

使用 difflib.SequenceMatcher 做全文对齐，然后映射每段解说词的时间戳。
"""

import json
import re
import subprocess
import os
from pathlib import Path
from difflib import SequenceMatcher

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # cli/ 目录上移两层到 VIBECAP/
DRAMA_DIR = BASE_DIR / os.environ.get("VibeCut_DRAMA", "都挺好")
TASK_DIR = DRAMA_DIR / "tasks" / os.environ.get("VibeCut_TASK", "Task7024")
SEGMENTS_PATH = TASK_DIR / "segments.json"
ASR_PATH = TASK_DIR / "narration_asr.json"
WORK_DIR = TASK_DIR / "work_dir"
TTS_DIR = WORK_DIR / "tts_segments"
AUDIO_PATH = TASK_DIR / "解说音频.wav"

NARRATION_JSON = WORK_DIR / "narration.json"
TTS_META_JSON = WORK_DIR / "tts_meta.json"

PUNCT = {
    '，', '。', '！', '？', '、', '“', '”', '‘', '’',
    '\n', '\r', ',', '.', '!', '?', "'", '"', '-', '—', '…',
    ' ', '\t', '　', '：', '；', '（', '）', '《', '》',
}


def strip_punct(text):
    """去标点空格，只保留汉字、字母、数字"""
    return ''.join(c for c in text if c not in PUNCT)


def build_char_timeline(asr_segments):
    """为 ASR 文本的每个字符分配时间戳"""
    full_text = ""
    char_times = []
    for seg in asr_segments:
        text = seg["text"]
        start = seg["start"]
        end = seg["end"]
        chars = len(text)
        if chars > 0:
            step = (end - start) / chars if end > start else 0.05
            for j, ch in enumerate(text):
                full_text += ch
                char_times.append(start + j * step)
    return full_text, char_times


def find_time_for_position(char_times, pos, default=None):
    """根据字符位置返回时间"""
    if 0 <= pos < len(char_times):
        return round(char_times[pos], 2)
    if pos >= len(char_times):
        return round(char_times[-1], 2) if char_times else default
    return round(char_times[0], 2) if char_times else default


def main():
    # 加载
    with open(SEGMENTS_PATH) as f:
        segments = json.load(f)["segments"]
    with open(ASR_PATH) as f:
        asr_segments = json.load(f)

    asr_text, char_times = build_char_timeline(asr_segments)
    print(f"ASR 全文: {len(asr_text)}字符, {char_times[0]:.1f}s - {char_times[-1]:.1f}s")

    # 拼接所有解说词
    docx_texts = [s["narration_text"] for s in segments if s["narration_text"]]
    full_docx = "".join(docx_texts)
    print(f"文案全文: {len(full_docx)}字符")

    # 用 SequenceMatcher 对齐去标点版本
    asr_clean = strip_punct(asr_text)
    docx_clean = strip_punct(full_docx)
    print(f"对齐: ASR({len(asr_clean)}chars) ↔ 文案({len(docx_clean)}chars)")

    matcher = SequenceMatcher(None, asr_clean, docx_clean)
    blocks = matcher.get_matching_blocks()
    print(f"匹配块数: {len(blocks)}")

    # 构建从 文案字符位置 → ASR字符位置 的映射
    # docx_pos → asr_pos (对于匹配块内的字符)
    docx_to_asr = {}  # docx_clean_idx → asr_clean_idx
    for a_start, d_start, length in blocks:
        if length > 0:
            for offset in range(length):
                docx_to_asr[d_start + offset] = a_start + offset

    def docx_pos_to_asr_pos(docx_clean_pos):
        """将去标点文案位置映射到去标点ASR位置（找不到时插值）"""
        if docx_clean_pos in docx_to_asr:
            return docx_to_asr[docx_clean_pos]
        # 找最近已知映射
        keys = sorted(docx_to_asr.keys())
        if not keys:
            return 0
        # 二分查找最近
        import bisect
        idx = bisect.bisect_left(keys, docx_clean_pos)
        if idx == 0:
            return docx_to_asr[keys[0]] - max(0, keys[0] - docx_clean_pos)
        if idx >= len(keys):
            return docx_to_asr[keys[-1]] + max(0, docx_clean_pos - keys[-1])
        # 插值
        left_key = keys[idx - 1]
        right_key = keys[idx]
        left_val = docx_to_asr[left_key]
        right_val = docx_to_asr[right_key]
        ratio = (docx_clean_pos - left_key) / (right_key - left_key) if right_key > left_key else 0
        return int(left_val + ratio * (right_val - left_val))

    def docx_pos_to_time(docx_pos):
        """文案原始字符位置 → 音频时间"""
        # 先找到这个原始字符在去标点文案中的位置
        clean_pos = len(strip_punct(full_docx[:docx_pos]))
        # 映射到 ASR 去标点位置
        asr_clean_pos = docx_pos_to_asr_pos(clean_pos)
        # 找到 ASR 去标点位置对应的原始 ASR 位置
        asr_pos = 0
        count = 0
        for i, ch in enumerate(asr_text):
            if ch not in PUNCT:
                if count >= asr_clean_pos:
                    asr_pos = i
                    break
                count += 1
        else:
            asr_pos = len(asr_text) - 1

        return find_time_for_position(char_times, asr_pos)

    # 为每段解说词计算时间
    results = []
    docx_cursor = 0  # 当前在 full_docx 中的位置

    for seg in segments:
        narration = seg["narration_text"]
        if not narration:
            results.append({
                "seg_id": seg["seg_id"],
                "time_start": 0, "time_end": 0, "duration": 0,
                "narration": "",
                "highlight_text": seg["highlight_text"],
                "episode_marker": seg["episode_marker"],
            })
            continue

        # 在 full_docx 中定位这一段
        seg_start_in_docx = full_docx.find(narration, docx_cursor)
        if seg_start_in_docx < 0:
            # 模糊查找：用前50个字符定位
            prefix = strip_punct(narration[:50])
            docx_clean_all = strip_punct(full_docx)
            idx = docx_clean_all.find(prefix, strip_punct(full_docx[:docx_cursor]))
            if idx >= 0:
                # 映射回去
                count = 0
                for i, ch in enumerate(full_docx):
                    if ch not in PUNCT:
                        if count >= idx:
                            seg_start_in_docx = i
                            break
                        count += 1
            if seg_start_in_docx < 0:
                seg_start_in_docx = docx_cursor

        seg_end_in_docx = seg_start_in_docx + len(narration)
        docx_cursor = seg_end_in_docx

        # 映射到音频时间
        time_start = docx_pos_to_time(seg_start_in_docx)
        time_end = docx_pos_to_time(seg_end_in_docx)
        # 给 end 加一点余量（句末停顿）
        time_end = min(time_end + 0.3, char_times[-1] if char_times else 216.3)

        results.append({
            "seg_id": seg["seg_id"],
            "time_start": round(time_start, 2),
            "time_end": round(time_end, 2),
            "duration": round(time_end - time_start, 2),
            "narration": narration,
            "highlight_text": seg["highlight_text"],
            "episode_marker": seg["episode_marker"],
        })

        print(f"  seg_{seg['seg_id']}: [{time_start:.1f}s - {time_end:.1f}s] "
              f"({time_end - time_start:.1f}s) | {narration[:50]}...")

    # 生成 narration.json（时间相对于输出片，从0开始）
    time_offset = results[0]["time_start"] if results else 0
    narration_json = []
    for r in results:
        if r["narration"]:
            narration_json.append({
                "start": round(r["time_start"] - time_offset, 2),
                "end": round(r["time_end"] - time_offset, 2),
                "narration": r["narration"],
                "pause_after_ms": 250,
                "overlaps_speech": True,
                "emotion": "自然叙述",
            })

    with open(NARRATION_JSON, 'w', encoding='utf-8') as f:
        json.dump(narration_json, f, ensure_ascii=False, indent=2)
    print(f"\n✅ narration.json → {NARRATION_JSON}")

    # 切分音频
    TTS_DIR.mkdir(exist_ok=True)
    tts_segments = []

    for r in results:
        if not r["narration"]:
            continue
        wav_path = TTS_DIR / f"narr_{r['seg_id']:03d}.wav"

        cmd = ["ffmpeg", "-y", "-i", str(AUDIO_PATH),
               "-ss", str(r["time_start"]), "-to", str(r["time_end"]),
               "-ar", "44100", "-ac", "1", str(wav_path)]
        subprocess.run(cmd, capture_output=True)

        tts_segments.append({
            "index": r["seg_id"],
            "start": round(r["time_start"] - time_offset, 2),
            "end": round(r["time_end"] - time_offset, 2),
            "narration": r["narration"],
            "audio_path": str(wav_path),
            "pause_after_ms": 250,
            "overlaps_speech": True,
        })

    tts_meta = {
        "segments": tts_segments,
        "engine": "pre_recorded",
        "narration": str(NARRATION_JSON),
    }
    with open(TTS_META_JSON, 'w', encoding='utf-8') as f:
        json.dump(tts_meta, f, ensure_ascii=False, indent=2)
    print(f"✅ tts_meta.json → {TTS_META_JSON}")
    print(f"✅ 音频切分到: {TTS_DIR}/")

    print(f"\n📊 时间线:")
    total = 0
    for r in results:
        print(f"  seg_{r['seg_id']} [{r['time_start']:6.1f}s - {r['time_end']:6.1f}s] "
              f"({r['duration']:5.1f}s)")
        total += r['duration']
    print(f"  总时长: {total:.1f}s")


if __name__ == "__main__":
    main()
