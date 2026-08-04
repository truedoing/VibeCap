#!/usr/bin/env python3
"""
数据清洗台 v2: ASR 碎片合并 + VLM 结构化字幕 + 质量标记
- ASR: 优先读 asr_calibrated.json (cross_calibrate 产出)，fallback asr_result.json
- VLM: 直接使用结构化 subtitles 字段（analyze_episodes v2 产出），不再正则硬扒
- 输出 sources_clean/epN/

用法:
  python3 clean_data.py
  python3 clean_data.py --ep 3
"""

import json, re, argparse
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "都挺好" / "sources"
CLEAN = Path(__file__).resolve().parent.parent / "都挺好" / "sources_clean"
CLEAN.mkdir(exist_ok=True)

def get_all_eps():
    """自动发现所有已分析的集数"""
    eps = []
    for d in sorted(BASE.iterdir()):
        if d.is_dir() and d.name.startswith("ep") and d.name[2:].isdigit():
            eps.append(int(d.name[2:]))
    return eps


def clean_asr(ep):
    """合并相邻短 ASR 片段 → 完整句子（优先读校准版）"""
    ep_dir = BASE / f"ep{ep}"
    cal_file = ep_dir / "asr_calibrated.json"
    asr_file = ep_dir / "asr_result.json"

    # 优先校准版，fallback 原始版
    if cal_file.exists():
        raw = json.load(open(cal_file))
        source = "calibrated"
    elif asr_file.exists():
        raw = json.load(open(asr_file))
        source = "raw"
    else:
        print(f"  EP{ep}: 无 ASR 数据")
        return None

    cleaned = []
    buf = {"start": 0, "end": 0, "text": "", "confidence": 0, "calibrated": False}

    for a in raw:
        text = a["text"].strip()
        if not text or text in ('啊','嗯','哦','哎','呃','喂','呵','嘿','哈','嘻'):
            continue

        conf = a.get("confidence", -99)
        is_cal = a.get("_calibrated", False) or a.get("_source") == "vlm_subtitle"

        if not buf["text"]:
            buf = {"start": a["start"], "end": a["end"], "text": text,
                   "confidence": conf, "calibrated": is_cal}
        elif a["start"] - buf["end"] < 3 and len(buf["text"]) < 30:
            buf["end"] = a["end"]
            buf["text"] += text
            buf["confidence"] = max(buf.get("confidence", -99), conf)
            buf["calibrated"] = buf.get("calibrated", False) or is_cal
        else:
            if len(buf["text"]) >= 3:
                cleaned.append(buf)
            buf = {"start": a["start"], "end": a["end"], "text": text,
                   "confidence": conf, "calibrated": is_cal}

    if len(buf["text"]) >= 3:
        cleaned.append(buf)

    out = CLEAN / f"ep{ep}"
    out.mkdir(exist_ok=True)
    json.dump(cleaned, open(out / "asr_result.json", 'w'), ensure_ascii=False, indent=2)

    before = len(raw)
    after = len(cleaned)
    text_before = sum(len(a["text"]) for a in raw)
    text_after = sum(len(s["text"]) for s in cleaned)
    cal_count = sum(1 for s in cleaned if s.get("calibrated"))
    print(f"  EP{ep} ASR[{source}]: {before}→{after}段(-{before-after}), "
          f"字量:{text_before}→{text_after}, 已校准:{cal_count}")
    return cleaned


def clean_vlm(ep):
    """提取结构化字幕 + 质量标记（使用 VLM 原生 subtitles 字段）"""
    ep_dir = BASE / f"ep{ep}"
    vlm_file = ep_dir / "vlm_analysis.json"
    if not vlm_file.exists():
        print(f"  EP{ep}: 无 VLM 数据")
        return None

    raw = json.load(open(vlm_file))
    cleaned = []
    issues = {"片头片尾": 0, "短描述": 0, "空深度": 0, "字幕场景": 0, "字幕总数": 0}

    for s in raw:
        if s is None:
            continue
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

        # 使用 VLM 结构化字幕（v2 prompt 的【字幕】段）
        subtitles = s.get("subtitles", [])
        if subtitles:
            issues["字幕场景"] += 1
            issues["字幕总数"] += len(subtitles)
        elif len(desc) > 0:
            # fallback: 正则匹配描述中可能的字幕（兼容旧数据）
            pats = [
                r'字幕[^，。！？\n]{0,20}(?:显示|揭示|写着|是|为)[：:\s]{0,3}[「「]?([^」」\n]{4,80})',
                r'字幕[：:]\s*([^，。！？\n]{4,80})',
            ]
            for pat in pats:
                for sub in re.findall(pat, desc):
                    sub = sub.strip()
                    if sub and len(sub) >= 3 and sub not in subtitles:
                        subtitles.append(sub)
            if subtitles:
                issues["字幕场景"] += 1
                issues["字幕总数"] += len(subtitles)

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

    # ── VLM 场景智能合并 ──
    merged = merge_similar_scenes(cleaned)
    json.dump(merged, open(out / "vlm_merged.json", 'w'), ensure_ascii=False, indent=2)

    total = len(cleaned)
    print(f"  EP{ep} VLM: {total}场景, {issues['字幕场景']}含字幕({issues['字幕总数']}条), "
          f"排除{issues['片头片尾']}片头尾, {issues['短描述']}短描述, {issues['空深度']}浅深度"
          f" | 合并后→{len(merged)}场景 (-{total-len(merged)})")
    return cleaned


def merge_similar_scenes(scenes, sim_threshold=0.65):
    """合并相邻的相似 VLM 场景（同一对话/同一地点）

    相似度 = 人物重叠×0.4 + 关键词Jaccard×0.4 + 时长均匀性×0.2
    """
    if len(scenes) <= 1:
        return scenes

    def extract_chars(desc):
        """提取描述中的角色名"""
        chars = ["苏大强", "苏明哲", "苏明成", "苏明玉", "明玉", "朱丽", "吴非",
                 "石天冬", "蒙总", "蒙太", "沈浩", "柳青", "赵美兰", "小咪", "老蒙"]
        return {c for c in chars if c in desc}

    def extract_keywords(desc):
        """提取场景关键词"""
        scene_words = {"办公室", "客厅", "厨房", "卧室", "餐厅", "走廊", "门口",
                       "站立", "坐着", "行走", "对话", "争吵", "沉默", "吃饭",
                       "白天", "夜晚", "室内", "室外", "近景", "远景", "特写"}
        return {w for w in scene_words if w in desc}

    merged = []
    current = dict(scenes[0])

    for nxt in scenes[1:]:
        desc1, desc2 = current.get("description", ""), nxt.get("description", "")
        chars1, chars2 = extract_chars(desc1), extract_chars(desc2)
        kw1, kw2 = extract_keywords(desc1), extract_keywords(desc2)

        # 人物重叠度
        char_overlap = len(chars1 & chars2) / max(len(chars1 | chars2), 1) if (chars1 or chars2) else 0.5
        # 关键词 Jaccard
        kw_overlap = len(kw1 & kw2) / max(len(kw1 | kw2), 1) if (kw1 or kw2) else 0.5
        # 时长均匀性：过长的合并降低权重
        dur1 = current["end"] - current["start"]
        dur2 = nxt["end"] - nxt["start"]
        dur_score = 1.0 if (dur1 + dur2) < 60 else max(0, 0.5 + 30 / (dur1 + dur2))

        sim = char_overlap * 0.4 + kw_overlap * 0.4 + dur_score * 0.2

        if sim >= sim_threshold:
            # 合并：扩展 end + 拼接描述 + 合并字幕
            current["end"] = nxt["end"]
            if len(current["description"]) + len(desc2) < 300:
                current["description"] += " " + desc2
            # 合并字幕（去重）
            subs = current.get("subtitles", []) + nxt.get("subtitles", [])
            current["subtitles"] = list(dict.fromkeys(subs))  # 保序去重
            tags = set(current.get("tags", []) + nxt.get("tags", []))
            current["tags"] = list(tags)
        else:
            merged.append(current)
            current = dict(nxt)

    merged.append(current)
    return merged


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="数据清洗")
    parser.add_argument("--ep", default=None, help="指定集数，逗号分隔。不指定则清洗全部")
    args = parser.parse_args()

    if args.ep:
        episodes = [int(e.strip()) for e in args.ep.split(",")]
    else:
        episodes = get_all_eps()

    for ep in episodes:
        print(f"--- EP{ep} ---")
        clean_asr(ep)
        clean_vlm(ep)

    print(f"\n✅ 清洗完成 → {CLEAN}/")
