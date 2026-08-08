#!/usr/bin/env python3
"""
A1: 解析解说文案.docx → 结构化 JSON
输出: segments.json
  [
    {
      "seg_id": 0,
      "highlight_text": "原剧台词（用于视频定位）",
      "episode_marker": "27.5",       // 可选，集数+大致分钟
      "episode": 27,
      "approx_minute": 5.0,
      "narration_text": "解说词段落…",
      "mode": "A"                      // A/B/C 剪辑模式
    },
    ...
  ]
"""

import json
import re
import os
from docx import Document
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DRAMA_DIR = BASE_DIR / os.environ.get("VibeCut_DRAMA", "都挺好")
TASK_DIR = DRAMA_DIR / "tasks" / os.environ.get("VibeCut_TASK", "Task7024")
DOCX_PATH = TASK_DIR / "解说文案.docx"
OUTPUT_PATH = TASK_DIR / "segments.json"


def parse_episode_marker(text: str) -> dict | None:
    """从高亮文本末尾提取集数标记，如 '27.5' → episode=27, approx_minute=5.0"""
    # 匹配末尾的纯数字.数字模式
    m = re.search(r'([\d]+)\.(\d+)\s*$', text)
    if m:
        ep = int(m.group(1))
        minute_approx = float(m.group(2))
        return {"episode": ep, "approx_minute": minute_approx, "raw": f"{ep}.{minute_approx}"}

    # S0 的 highlight 有 "41集" → episode=41, approx_minute=0
    m = re.search(r'([\d]+)集\s*$', text)
    if m:
        ep = int(m.group(1))
        return {"episode": ep, "approx_minute": 0, "raw": f"{ep}.0"}
    m2 = re.search(r'([\d]+)\.(\d+)', text)
    if m2:
        ep = int(m2.group(1))
        minute_approx = float(m2.group(2))
        # 检查是否是合理范围 (剧集 20-40, 分钟 0-60)
        if 20 <= ep <= 46 and 0 <= minute_approx <= 60:
            return {"episode": ep, "approx_minute": minute_approx, "raw": f"{ep}.{minute_approx}"}

    return None


def clean_highlight_text(text: str, marker: dict | None) -> str:
    """清理高亮文本，去掉末尾的集数标记"""
    if marker:
        # 移除末尾的 episode marker
        cleaned = re.sub(r'\s*' + re.escape(marker["raw"]) + r'\s*$', '', text).strip()
        return cleaned
    return text.strip()


def main():
    doc = Document(str(DOCX_PATH))
    paragraphs = [p for p in doc.paragraphs if p.text.strip()]

    # 第一步：分离高亮段和普通段
    entries = []

    for i, p in enumerate(paragraphs):
        text = p.text.strip()
        if not text:
            continue

        # 检查是否含高亮
        has_highlight = False
        for run in p.runs:
            if run.font.highlight_color is not None:
                has_highlight = True
                break

        entries.append({
            "index": i,
            "text": text,
            "has_highlight": has_highlight
        })

    # 第二步：分离封面描述 —— 开头连续的无高亮段落
    cover_lines = []
    body_start = 0
    for entry in entries:
        if not entry["has_highlight"]:
            cover_lines.append(entry["text"])
            body_start += 1
        else:
            break

    cover = "\n".join(cover_lines) if cover_lines else ""

    # 第三步：配对 —— 高亮段 + 紧随其后的白色解说段（仅从 body_start 开始）
    segments = []
    i = body_start
    while i < len(entries):
        if entries[i]["has_highlight"]:
            highlight_text = entries[i]["text"]
            marker = parse_episode_marker(highlight_text)
            cleaned_highlight = clean_highlight_text(highlight_text, marker)

            # 下一个非高亮段是解说词
            narration_text = ""
            if i + 1 < len(entries) and not entries[i + 1]["has_highlight"]:
                narration_text = entries[i + 1]["text"]
                i += 2  # 消费了两个
            else:
                # 没有后续解说词
                i += 1

            seg = {
                "seg_id": len(segments),
                "highlight_text": cleaned_highlight,
                "episode_marker": marker,
                "narration_text": narration_text,
                "mode": "A"  # 默认剧情再现
            }
            segments.append(seg)
        else:
            # body 中间的孤立解说词 — 追加到上一段
            if segments:
                segments[-1]["narration_text"] += "\n" + entries[i]["text"]
            else:
                # 理论上不会到这里（body 已跳过 cover 段）
                pass
            i += 1

    # 第三步：标记剪辑模式
    for seg in segments:
        if not seg["highlight_text"]:
            seg["mode"] = "C"  # 叙事推进（无原剧台词定位）
        elif not seg["narration_text"]:
            seg["mode"] = "A"  # 有台词但解说在别处

    # 输出
    output = {
        "source_docx": str(DOCX_PATH),
        "total_segments": len(segments),
        "cover": cover,  # 封面描述文案（不需要选镜头）
        "segments": segments
    }

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 打印摘要
    print(f"✅ A1 完成：解析出 {len(segments)} 个段落对")
    print(f"   输出: {OUTPUT_PATH}")
    print()
    for seg in segments:
        marker_str = f" [第{seg['episode_marker']['episode']}集约{seg['episode_marker']['approx_minute']}分]" if seg['episode_marker'] else " [无标记]"
        hl_preview = seg['highlight_text'][:50] + "..." if len(seg['highlight_text']) > 50 else seg['highlight_text']
        narr_preview = seg['narration_text'][:60] + "..." if len(seg['narration_text']) > 60 else seg['narration_text']
        print(f"  seg_{seg['seg_id']} [{seg['mode']}]{marker_str}")
        print(f"    🟡 台词: {hl_preview}")
        print(f"    📝 解说: {narr_preview}")
        print()


if __name__ == "__main__":
    main()
