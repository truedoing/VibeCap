#!/usr/bin/env python3
"""
精切引擎 — 用 classified_enhanced.json 的标注数据，将粗段拆分为精确子段。

逻辑:
  对每个 segment 的 [source_start, source_end] 区间，找到所有 utterance，
  按规则标注 KEEP / CUT，连续的 KEEP 合并为一个 sub_clip。

CUT 规则:
  - layer = 'filler' 或 'meta' → CUT
  - speaker = 'host' 且 layer ≠ 'content' → CUT
  - importance ≤ 1 → CUT

输出:
  segments.json 新增 sub_clips 字段，每个 sub_clip 含:
    {start, end, text, speaker, decision: KEEP|CUT, utterances: [...]}
"""

import json, sys
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent.parent

CUT_RULES = {
    "filler": True,
    "meta": True,
}

def is_cut(utt):
    """判断一条 utterance 是否应该被剪掉"""
    # 明确的废料层
    if CUT_RULES.get(utt.get("layer")):
        return True
    # 主持人非内容类发言
    if utt.get("speaker") == "host" and utt.get("layer") != "content":
        return True
    # 重要性最低
    if utt.get("importance", 2) <= 1:
        return True
    return False


def refine(segments, utterances):
    """
    对每个 segment 做精切，返回带 sub_clips 的 segments。

    Args:
        segments: [{"seg_id": 0, "source_start": 2.5, "source_end": 16.9, ...}, ...]
        utterances: [{"start_sec": 2.5, "text": "...", "layer": "content", ...}, ...]
                    按 start_sec 升序排列

    Returns:
        精切后的 segments，每段新增 sub_clips 和 stats 字段
    """
    refined = []
    cuts_total = 0
    keeps_total = 0

    for seg in segments:
        ss = seg.get("source_start", 0)
        se = seg.get("source_end", ss + 5)

        # 找到区间内的所有 utterance
        seg_utts = [u for u in utterances if u["start_sec"] >= ss - 0.5 and u["start_sec"] < se + 0.5]

        if not seg_utts:
            # 没有细粒度数据，保留原段
            seg["sub_clips"] = [{
                "start": ss, "end": se,
                "text": seg.get("highlight_text", ""),
                "speaker": "unknown",
                "decision": "KEEP",
                "utterances": [],
            }]
            seg["refine_stats"] = {"total": 0, "keep": 1, "cut": 0}
            refined.append(seg)
            continue

        # 逐条标注 decision，并推算 end
        annotated = []
        for i, u in enumerate(seg_utts):
            # 推算 end_sec：取下一条的 start，最后一条用 source_end 封顶
            if i + 1 < len(seg_utts):
                end_sec = seg_utts[i + 1]["start_sec"]
            else:
                end_sec = min(se, u["start_sec"] + 8)  # fallback: 最多 8s

            # 边界处理：第一条不早于 source_start，最后一条不晚于 source_end
            start_sec = max(ss, u["start_sec"])
            end_sec = min(se, end_sec)

            decision = "CUT" if is_cut(u) else "KEEP"

            annotated.append({
                "start": round(start_sec, 2),
                "end": round(end_sec, 2),
                "text": u.get("cleaned_text", u.get("text", "")),
                "speaker": u.get("speaker", "unknown"),
                "layer": u.get("layer", ""),
                "importance": u.get("importance", 0),
                "decision": decision,
            })

        # 合并连续的 KEEP 块 → sub_clips
        sub_clips = []
        buf = None  # 当前正在合并的 sub_clip

        for a in annotated:
            if a["decision"] == "KEEP":
                if buf is None:
                    buf = {
                        "start": a["start"],
                        "end": a["end"],
                        "text": a["text"],
                        "speaker": a["speaker"],
                        "decision": "KEEP",
                        "utterances": [a],
                    }
                else:
                    buf["end"] = a["end"]
                    buf["text"] += " " + a["text"]
                    buf["utterances"].append(a)
                    # 合并后说话人取多数
                    if a["speaker"] == buf["speaker"]:
                        pass  # same speaker, keep
            else:
                # CUT 项单独成 sub_clip（方便剪映里定位删除）
                if buf is not None:
                    sub_clips.append(buf)
                    buf = None
                sub_clips.append({
                    "start": a["start"],
                    "end": a["end"],
                    "text": a["text"],
                    "speaker": a["speaker"],
                    "decision": "CUT",
                    "utterances": [a],
                })

        if buf is not None:
            sub_clips.append(buf)

        # 统计
        n_keep = sum(1 for s in sub_clips if s["decision"] == "KEEP")
        n_cut = sum(1 for s in sub_clips if s["decision"] == "CUT")
        cuts_total += n_cut
        keeps_total += n_keep

        seg["sub_clips"] = sub_clips
        seg["refine_stats"] = {
            "total": len(sub_clips),
            "keep": n_keep,
            "cut": n_cut,
            "keep_duration": round(sum(s["end"] - s["start"] for s in sub_clips if s["decision"] == "KEEP"), 1),
            "cut_duration": round(sum(s["end"] - s["start"] for s in sub_clips if s["decision"] == "CUT"), 1),
        }

        refined.append(seg)

    return refined


def load_data(project_name, task_name):
    """加载 segments 和 classified_enhanced"""
    project_dir = BASE_DIR / project_name

    # segments
    seg_file = project_dir / "tasks" / task_name / "segments.json"
    if not seg_file.exists():
        print(f"❌ segments.json 不存在: {seg_file}")
        return None, None
    segments_data = json.load(open(seg_file))
    segments = segments_data.get("segments", [])

    # classified_enhanced
    ce_file = project_dir / "sources_clean" / "classified_enhanced.json"
    if not ce_file.exists():
        print(f"❌ classified_enhanced.json 不存在: {ce_file}")
        return segments, None
    utterances = json.load(open(ce_file))
    # 确保按时间排序
    utterances.sort(key=lambda u: u.get("start_sec", 0))

    return segments, utterances


def save_result(segments_data, project_name, task_name, refined_segments):
    """写回 segments.json，保留原有字段，只更新 segments 数组"""
    project_dir = BASE_DIR / project_name
    seg_file = project_dir / "tasks" / task_name / "segments.json"

    out = dict(segments_data)
    out["segments"] = refined_segments
    out["refined"] = True

    # 全局统计
    total_keep = sum(s["refine_stats"]["keep"] for s in refined_segments)
    total_cut = sum(s["refine_stats"]["cut"] for s in refined_segments)
    out["refine_summary"] = {
        "total_sub_clips": total_keep + total_cut,
        "keep": total_keep,
        "cut": total_cut,
        "cut_pct": round(total_cut / max(total_keep + total_cut, 1) * 100, 0),
    }

    json.dump(out, open(seg_file, "w"), ensure_ascii=False, indent=2)
    return seg_file


def main():
    import argparse
    parser = argparse.ArgumentParser(description="粗段 → 精切子段")
    parser.add_argument("--project", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--dry-run", action="store_true", help="只打印不写入")
    args = parser.parse_args()

    segments, utterances = load_data(args.project, args.task)
    if segments is None:
        return 1

    print(f"📝 粗段: {len(segments)} 段")
    print(f"🔬 细粒度标注: {len(utterances) if utterances else 0} 条")

    if not utterances:
        print("⚠️  没有 classified_enhanced 数据，跳过精切")
        return 0

    refined = refine(segments, utterances)

    # 打印每段精切结果
    total_keep_s = 0
    total_cut_s = 0
    for seg in refined:
        stats = seg["refine_stats"]
        total_keep_s += stats["keep_duration"]
        total_cut_s += stats["cut_duration"]
        sc_list = seg["sub_clips"]
        # 显示 KEEP 块摘要
        keep_texts = [s["text"][:40] for s in sc_list if s["decision"] == "KEEP"]
        cut_texts = [s["text"][:30] for s in sc_list if s["decision"] == "CUT"]
        print(f"\n  S{seg['seg_id']}: {stats['keep']}K + {stats['cut']}C "
              f"({stats['keep_duration']}s keep / {stats['cut_duration']}s cut)")
        for kt in keep_texts[:3]:
            print(f"    ✅ {kt}...")
        for ct in cut_texts[:2]:
            print(f"    ❌ {ct}...")
        if len(cut_texts) > 2:
            print(f"    ❌ ... 还有 {len(cut_texts) - 2} 段待删除")

    print(f"\n📊 总计: {sum(s['refine_stats']['keep'] for s in refined)} KEEP + "
          f"{sum(s['refine_stats']['cut'] for s in refined)} CUT")
    print(f"   保留时长: {total_keep_s:.0f}s / 删除: {total_cut_s:.0f}s")
    print(f"   删除占比: {total_cut_s / max(total_keep_s + total_cut_s, 1) * 100:.0f}%")

    if args.dry_run:
        print("\n🔍 dry-run 模式，未写入")
        return 0

    # 重新加载原始 segments.json 保留元字段
    original = json.load(open(BASE_DIR / args.project / "tasks" / args.task / "segments.json"))
    out_file = save_result(original, args.project, args.task, refined)
    print(f"\n✅ 精切完成 → {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
