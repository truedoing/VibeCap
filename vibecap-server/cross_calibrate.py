#!/usr/bin/env python3
"""
ASR ↔ VLM 交叉校准脚本
输入: sources/epN/asr_result.json + sources/epN/vlm_analysis.json
输出: sources/epN/asr_calibrated.json + sources/epN/calibration_report.json

校准策略:
1. VLM 结构化字幕 ↔ ASR 文本时间窗口匹配
2. 双向补漏: VLM有ASR无→补充 / ASR低置信度→VLM修正
3. 人物交叉验证: ASR称呼 ↔ VLM画面人物
4. 置信度加权: 双确认 > 单源 > 低置信

用法:
  python3 cross_calibrate.py --ep 3
  python3 cross_calibrate.py --ep 1,2,3
"""

import json, re, argparse, os
from pathlib import Path
from difflib import SequenceMatcher

BASE_DIR = Path("/Users/zgl/VIBECAP")
DRAMA_DIR = BASE_DIR / "都挺好"
SOURCES_DIR = DRAMA_DIR / "sources"

# 人物名映射: ASR常用称呼 → 正式名
CHARACTER_NAMES = {
    "明玉": "苏明玉", "苏明玉": "苏明玉",
    "大强": "苏大强", "苏大强": "苏大强",
    "明成": "苏明成", "苏明成": "苏明成",
    "明哲": "苏明哲", "苏明哲": "苏明哲",
    "蒙总": "蒙总", "老蒙": "蒙总",
    "蒙太": "蒙太", "嫂子": "蒙太",
    "丽丽": "朱丽", "朱丽": "朱丽",
    "石天冬": "石天冬", "小石": "石天冬",
    "吴非": "吴非", "菲菲": "吴非",
    "小咪": "小咪",
    "沈浩": "沈浩",
    "柳青": "柳青",
    "蔡根花": "蔡根花",
}


def text_similarity(a, b):
    """两个文本的相似度 (0-1)"""
    if not a or not b:
        return 0.0
    a_clean = re.sub(r'[，。！？、\s]', '', a)
    b_clean = re.sub(r'[，。！？、\s]', '', b)
    return SequenceMatcher(None, a_clean, b_clean).ratio()


def load_json(path):
    if path.exists():
        return json.load(open(path))
    return None


def calibrate_episode(ep):
    """对单集执行交叉校准"""
    ep_dir = SOURCES_DIR / f"ep{ep}"
    asr_file = ep_dir / "asr_result.json"
    vlm_file = ep_dir / "vlm_analysis.json"

    asr_data = load_json(asr_file)
    vlm_data = load_json(vlm_file)

    if not asr_data:
        print(f"  ❌ EP{ep}: asr_result.json 不存在")
        return None
    if not vlm_data:
        print(f"  ⚠️  EP{ep}: vlm_analysis.json 不存在，跳过 VLM 校准")
        return None

    vlm_valid = [s for s in vlm_data if s is not None]

    report = {
        "ep": ep,
        "asr_total": len(asr_data),
        "vlm_scenes": len(vlm_valid),
        "vlm_scenes_with_subtitles": 0,
        "confirmed": 0,        # ASR+VLM 双确认
        "vlm_only": 0,         # VLM有字幕、ASR无 → 已补充
        "asr_low_conf": 0,     # ASR低置信度
        "asr_corrected": 0,    # ASR被VLM修正
        "char_mismatches": 0,  # 人物名不匹配
        "patches": [],         # 详细修补记录
    }

    # ── Step 1: 构建校准后的 ASR ──
    calibrated = []
    for a in asr_data:
        calibrated.append(dict(a))  # 复制

    # ── Step 2: VLM 字幕 → ASR 匹配 ──
    for scene in vlm_valid:
        subtitles = scene.get("subtitles", [])
        if not subtitles:
            continue
        report["vlm_scenes_with_subtitles"] += 1
        scene_start = scene["start"]
        scene_end = scene["end"]
        window = 3.0  # 前后扩展窗口

        # 找到时间窗口内的 ASR 段
        asr_in_window = [
            (i, a) for i, a in enumerate(asr_data)
            if a["start"] >= scene_start - window and a["end"] <= scene_end + window
        ]

        for sub in subtitles:
            best_match = None
            best_score = 0.0
            best_idx = None

            for idx, a in asr_in_window:
                score = text_similarity(sub, a["text"])
                if score > best_score:
                    best_score = score
                    best_match = a
                    best_idx = idx

            if best_score >= 0.55:
                # 确认匹配 → 提升置信度，用 VLM 字幕精修 ASR 文本
                report["confirmed"] += 1
                old_text = calibrated[best_idx]["text"]
                if best_score < 0.9:
                    # 不完全匹配 → 用 VLM 字幕替换（字幕更准确）
                    calibrated[best_idx]["text"] = sub
                    calibrated[best_idx]["confidence"] = max(
                        calibrated[best_idx].get("confidence", -99), -0.3
                    )  # 标记为可信
                    calibrated[best_idx]["_calibrated"] = True
                    calibrated[best_idx]["_vlm_sub"] = sub
                    calibrated[best_idx]["_old_text"] = old_text
                    report["asr_corrected"] += 1
                    report["patches"].append({
                        "type": "corrected",
                        "time": f"{best_match['start']:.0f}s",
                        "old": old_text[:60],
                        "new": sub[:60],
                        "score": round(best_score, 2),
                    })
                else:
                    # 高匹配 → 提升置信度
                    calibrated[best_idx]["confidence"] = max(
                        calibrated[best_idx].get("confidence", -99), -0.5
                    )
            else:
                # VLM 有字幕但 ASR 无匹配 → 补充
                mid = (scene_start + scene_end) / 2
                calibrated.append({
                    "start": round(mid - 0.5, 1),
                    "end": round(mid + 0.5, 1),
                    "text": sub,
                    "confidence": -0.1,  # 高置信度（VLM来源）
                    "_source": "vlm_subtitle",
                })
                report["vlm_only"] += 1
                report["patches"].append({
                    "type": "inserted",
                    "time": f"{mid:.0f}s",
                    "text": sub[:80],
                })

    # ── Step 3: 低置信度标记 ──
    for a in calibrated:
        if a.get("confidence", -99) < -1.5:
            report["asr_low_conf"] += 1
            a["_low_confidence"] = True

    # ── Step 4: 人物交叉验证 ──
    for scene in vlm_valid:
        frame_facts = scene.get("frame_facts", {})
        vlm_chars = set()
        for ts, facts in frame_facts.items():
            for f in facts:
                if f in CHARACTER_NAMES.values():
                    vlm_chars.add(f)

        if not vlm_chars:
            continue

        # 找到该场景内的 ASR 文本
        scene_texts = []
        for a in asr_data:
            if a["start"] >= scene["start"] - 1 and a["end"] <= scene["end"] + 1:
                scene_texts.append(a["text"])
        combined = " ".join(scene_texts)

        # 检查 ASR 中提到的称呼是否与 VLM 画面人物一致
        for alias, formal in CHARACTER_NAMES.items():
            if alias in combined:
                if formal not in vlm_chars and len(alias) > 1:
                    # ASR提到了某人但VLM画面中没看到 → 可能是画外音或VLM漏标
                    pass  # 不报警，画外音是正常的
                # 反之：VLM看到的人、ASR没提 → VLM可能幻觉
                # 暂不计入统计

    # ── 输出 ──
    # 按时间排序
    # 过滤演职人员表字幕（片头片尾常见）
    CREDIT_KEYWORDS = ['出品人', '总监制', '监制', '策划', '导演', '编剧', '制片',
                       '主演', '领衔', '摄影', '美术', '音乐', '剪辑', '录音',
                       '出品', '联合', '总策划', '总导演', '总编剧', '艺术总监',
                       '技术', '灯光', '服装', '化妆', '道具', '场记', '统筹']
    calibrated = [a for a in calibrated
                  if not any(kw in a['text'] for kw in CREDIT_KEYWORDS)]

    calibrated.sort(key=lambda x: x["start"])

    cal_file = ep_dir / "asr_calibrated.json"
    json.dump(calibrated, open(cal_file, 'w'), ensure_ascii=False, indent=2)

    rpt_file = ep_dir / "calibration_report.json"
    json.dump(report, open(rpt_file, 'w'), ensure_ascii=False, indent=2)

    print(f"  EP{ep}: ASR {len(asr_data)}→{len(calibrated)}段, "
          f"确认{report['confirmed']} 修正{report['asr_corrected']} "
          f"补充{report['vlm_only']} 低置信{report['asr_low_conf']}")
    for p in report["patches"][:5]:
        print(f"    [{p['type']}] {p['time']}: {p.get('old', '')[:40]} → {p.get('new', p.get('text', ''))[:40]}")

    return report


def main():
    parser = argparse.ArgumentParser(description="ASR ↔ VLM 交叉校准")
    parser.add_argument("--ep", default="1", help="集数，逗号分隔")
    args = parser.parse_args()

    episodes = [int(e.strip()) for e in args.ep.split(",")]
    print(f"交叉校准 EP {episodes}...\n")

    total = {"confirmed": 0, "asr_corrected": 0, "vlm_only": 0, "asr_low_conf": 0}
    for ep in episodes:
        r = calibrate_episode(ep)
        if r:
            for k in total:
                total[k] += r[k]

    print(f"\n汇总: 确认{total['confirmed']} 修正{total['asr_corrected']} "
          f"补充{total['vlm_only']} 低置信{total['asr_low_conf']}")


if __name__ == "__main__":
    main()
