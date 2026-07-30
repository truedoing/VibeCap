#!/usr/bin/env python3
"""
数据清洗台：ASR 碎片合并 + VLM 字幕提取 + 质量标记
输出 cleaned/ 目录，build_index 改读此目录
"""

import json, re
from pathlib import Path

BASE = Path("/Users/zgl/VIBECAP/都挺好/sources")
CLEAN = Path("/Users/zgl/VIBECAP/都挺好/sources_clean")
CLEAN.mkdir(exist_ok=True)

def clean_asr(ep):
    """合并相邻的短 ASR 片段为完整句子"""
    raw = json.load(open(BASE / f"ep{ep}" / "asr_result.json"))
    cleaned = []
    buf = {"start": 0, "end": 0, "text": ""}

    for a in raw:
        text = a["text"].strip()
        # 跳过纯噪声
        if not text or text in ('啊','嗯','哦','哎','呃','喂','呵','嘿','哈','嘻'):
            continue

        if not buf["text"]:
            buf = {"start": a["start"], "end": a["end"], "text": text}
        elif a["start"] - buf["end"] < 3 and len(buf["text"]) < 30:
            # 合并：间隔 < 3s 且当前缓冲区 < 30 字
            buf["end"] = a["end"]
            buf["text"] += text
        else:
            if len(buf["text"]) >= 3:
                cleaned.append(buf)
            buf = {"start": a["start"], "end": a["end"], "text": text}

    if len(buf["text"]) >= 3:
        cleaned.append(buf)

    out = CLEAN / f"ep{ep}"
    out.mkdir(exist_ok=True)
    json.dump(cleaned, open(out / "asr_result.json", 'w'), ensure_ascii=False, indent=2)

    before = len(raw)
    after = len(cleaned)
    text_before = sum(len(a["text"]) for a in raw)
    text_after = sum(len(s["text"]) for s in cleaned)
    print(f"  EP{ep} ASR: {before}→{after}段(-{before-after}), 字量:{text_before}→{text_after}")
    return cleaned


def clean_vlm(ep):
    """提取字幕 + 质量标记"""
    raw = json.load(open(BASE / f"ep{ep}" / "vlm_analysis.json"))
    cleaned = []
    issues = {"片头片尾": 0, "短描述": 0, "空深度": 0, "字幕提取": 0}

    for s in raw:
        if s is None: continue
        desc = s.get("description", "")
        depth = s.get("depth_analysis", "")

        # 质量标记
        tags = []
        if any(kw in desc for kw in ['片头','片尾','水墨','演职人员','字幕滚动']):
            tags.append("skip_opening")
            issues["片头片尾"] += 1
        if len(desc) < 20:
            tags.append("short_desc")
            issues["短描述"] += 1
        if len(depth) < 30:
            tags.append("shallow_depth")
            issues["空深度"] += 1

        # 提取字幕
        subtitles = []
        patterns = [
            r'字幕[^，。！？\n]{0,20}(?:显示|揭示|写着|是|为|c显示)[：:\s]{0,3}[「「]?([^」」\n]{4,80})',
            r'字幕[^，。！？\n]{0,10}"([^"]{4,80})"',
            r'字幕[^，。！？\n]{0,10}「([^」]{4,80})」',
            r'字幕[：:]\s*([^，。！？\n]{4,80})',
        ]
        for pat in patterns:
            for sub in re.findall(pat, desc):
                sub = sub.strip()
                if sub and len(sub) >= 3:
                    subtitles.append(sub)
        if depth:
            for pat in patterns:
                for sub in re.findall(pat, depth):
                    sub = sub.strip()
                    if sub and len(sub) >= 3 and sub not in subtitles:
                        subtitles.append(sub)

        if subtitles:
            issues["字幕提取"] += 1

        cleaned.append({
            "scene_id": s["scene_id"],
            "start": s["start"],
            "end": s["end"],
            "description": desc,
            "depth_analysis": depth,
            "frame_facts": s.get("frame_facts", {}),
            "subtitles": subtitles,
            "tags": tags,
        })

    out = CLEAN / f"ep{ep}"
    out.mkdir(exist_ok=True)
    json.dump(cleaned, open(out / "vlm_analysis.json", 'w'), ensure_ascii=False, indent=2)

    total = len(cleaned)
    print(f"  EP{ep} VLM: {total}场景, 字幕{issues['字幕提取']}, "
          f"排除{issues['片头片尾']}片头尾, {issues['短描述']}短描述, {issues['空深度']}浅深度")
    return cleaned


if __name__ == "__main__":
    for ep in [1, 2, 3, 4, 27, 28, 29]:
        print(f"--- EP{ep} ---")
        clean_asr(ep)
        clean_vlm(ep)

    print(f"\n✅ 清洗完成 → {CLEAN}/")
