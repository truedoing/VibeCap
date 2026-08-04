#!/usr/bin/env python3
"""
A4: 在视频 ASR 结果中搜索高亮台词 → 生成 clip_plan.json

v2: 跨集搜索 + 未匹配时用相邻段位置估算
"""

import json
import sys
import bisect
import os
from pathlib import Path
from difflib import SequenceMatcher

BASE_DIR = Path(__file__).resolve().parent.parent
DRAMA_DIR = BASE_DIR / os.environ.get("VibeCut_DRAMA", "都挺好")
TASK_DIR = DRAMA_DIR / "tasks" / os.environ.get("VibeCut_TASK", "Task7024")
SEGMENTS_PATH = TASK_DIR / "segments.json"
WORK_DIR = TASK_DIR / "work_dir"
SOURCES_DIR = WORK_DIR / "sources"

OUTPUT_CLIP_PLAN = WORK_DIR / "clip_plan.json"
OUTPUT_SEGMENTS_LOCATED = TASK_DIR / "segments_located.json"

PUNCT = set('，。！？、""''：；\n\r ,.!?\'\"-—…\t　（）《》~')


def strip_punct(text):
    return ''.join(c for c in text if c not in PUNCT)


def load_asr(episode_num):
    asr_path = SOURCES_DIR / f"ep{episode_num}" / "asr_result.json"
    if not asr_path.exists():
        return []
    with open(asr_path) as f:
        return json.load(f)


def search_in_all_eps(hl_text, all_asr, prefer_ep=None, time_range=None, wide=False):
    """在所有集的 ASR 中搜索，返回最佳匹配"""
    hl_clean = strip_punct(hl_text)
    if len(hl_clean) < 3:
        return None

    best = None  # {ep, start, end, score, text}

    # 搜索顺序：优先集 → 其他集
    ep_order = []
    if prefer_ep and prefer_ep in all_asr:
        ep_order.append(prefer_ep)
    ep_order += sorted([ep for ep in all_asr if ep not in ep_order])

    for ep_num in ep_order:
        asr_data = all_asr[ep_num]
        # 过滤时间范围
        if not wide and time_range:
            candidates = [(i, s) for i, s in enumerate(asr_data)
                          if s["end"] >= time_range[0] and s["start"] <= time_range[1]]
            if len(candidates) < 2:
                # 扩大范围
                candidates = list(enumerate(asr_data))
        elif wide:
            candidates = list(enumerate(asr_data))
        else:
            candidates = list(enumerate(asr_data))

        # 滑动窗口搜索
        max_window = 6 if wide else 5
        for window_size in range(1, min(max_window + 1, len(candidates) + 1)):
            for idx in range(len(candidates) - window_size + 1):
                window_indices = candidates[idx:idx + window_size]
                i = window_indices[0][0]
                j = window_indices[-1][0]
                window_segs = asr_data[i:j + 1]
                combined = "".join(s["text"] for s in window_segs)
                combined_clean = strip_punct(combined)
                ratio = SequenceMatcher(None, combined_clean, hl_clean).ratio()

                if best is None or ratio > best["score"]:
                    best = {
                        "ep": ep_num,
                        "start": window_segs[0]["start"],
                        "end": window_segs[-1]["end"],
                        "score": ratio,
                        "text": combined[:120],
                    }

    if best is None or best["score"] < 0.35:
        return None
    return best


def main():
    with open(SEGMENTS_PATH) as f:
        segments = json.load(f)["segments"]

    # 加载所有 ASR
    print("加载 ASR 数据...")
    all_asr = {}
    for ep in [27, 28, 29]:
        asr_data = load_asr(ep)
        if asr_data:
            all_asr[ep] = asr_data
            total_text = "".join(s["text"] for s in asr_data)
            print(f"  ep{ep}: {len(asr_data)} 段, {len(total_text)} 字, "
                  f"{asr_data[0]['start']:.0f}s - {asr_data[-1]['end']:.0f}s")

    if not all_asr:
        print("❌ 没有任何 ASR 数据")
        sys.exit(1)

    clips = []
    located_segments = []
    last_known_ep = 27
    last_known_time = 0  # 上一段视频时间
    search_start = 0

    for seg in segments:
        hl = seg["highlight_text"]
        ep_marker = seg["episode_marker"]

        # 确定搜索参数
        if ep_marker:
            prefer_ep = ep_marker["episode"]
            approx_min = ep_marker["approx_minute"] * 60
            time_range = (max(0, approx_min - 180), approx_min + 180)
            search_start = time_range[0]
            wide = False
        else:
            prefer_ep = last_known_ep
            # 在当前已知位置的后面 ±5 分钟
            time_range = (max(0, search_start - 60), search_start + 600)
            wide = False

        print(f"\nseg_{seg['seg_id']}: 优先 ep{prefer_ep} [{time_range[0]:.0f}s - {time_range[1]:.0f}s]")
        print(f"  台词: {hl[:60]}...")

        # 先窄范围搜
        result = search_in_all_eps(hl, all_asr, prefer_ep=prefer_ep, time_range=time_range, wide=False)

        # 窄范围失败 → 扩大到全范围
        if result is None:
            print(f"  ↳ 窄范围未命中，扩大搜索...")
            result = search_in_all_eps(hl, all_asr, prefer_ep=prefer_ep, time_range=None, wide=True)

        if result and result["score"] >= 0.35:
            clip_start = max(0, result["start"] - 1)
            clip_end = min(result["end"] + 2,
                           all_asr[result["ep"]][-1]["end"] if result["ep"] in all_asr else result["end"] + 5)

            clips.append({
                "source_id": f"ep{result['ep']}",
                "start": round(clip_start, 2),
                "end": round(clip_end, 2),
                "reason": (f"seg_{seg['seg_id']} | {seg['narration_text'][:40]} | "
                           f"match={result['score']:.2f}"),
            })

            located_segments.append({
                **{k: v for k, v in seg.items() if k not in ('highlight_text', 'narration_text', 'episode_marker')},
                "highlight_text": seg["highlight_text"],
                "narration_text": seg["narration_text"],
                "episode_marker": seg["episode_marker"],
                "video_episode": result["ep"],
                "video_start": result["start"],
                "video_end": result["end"],
                "clip_start": round(clip_start, 2),
                "clip_end": round(clip_end, 2),
                "match_score": round(result["score"], 3),
                "matched_text": result["text"],
            })

            last_known_ep = result["ep"]
            search_start = result["end"] + 1
            print(f"  ✅ ep{result['ep']} [{result['start']:.0f}s - {result['end']:.0f}s] "
                  f"score={result['score']:.0%}")
        else:
            # 完全未匹配 → 用相邻段推断
            # seg_4 特殊处理：在 seg_3 和 seg_5 之间
            if located_segments:
                prev = located_segments[-1]
                est_ep = prev["video_episode"]
                est_start = prev["video_end"]
                est_end = est_start + 10
            else:
                est_ep = prefer_ep
                est_start = search_start
                est_end = est_start + 15

            print(f"  ⚠️ 未匹配 → 估计 ep{est_ep} [{est_start:.0f}s - {est_end:.0f}s]")

            clips.append({
                "source_id": f"ep{est_ep}",
                "start": round(est_start, 2),
                "end": round(est_end, 2),
                "reason": f"seg_{seg['seg_id']} | ESTIMATED | {seg['narration_text'][:40]}",
            })

            located_segments.append({
                **{k: v for k, v in seg.items() if k not in ('highlight_text', 'narration_text', 'episode_marker')},
                "highlight_text": seg["highlight_text"],
                "narration_text": seg["narration_text"],
                "episode_marker": seg["episode_marker"],
                "video_episode": est_ep,
                "video_start": est_start,
                "video_end": est_end,
                "clip_start": round(est_start, 2),
                "clip_end": round(est_end, 2),
                "match_score": 0,
                "matched_text": "",
            })

            search_start = est_end + 1

    # 输出
    clip_plan = {"target_duration": "4m", "clips": clips}
    with open(OUTPUT_CLIP_PLAN, 'w', encoding='utf-8') as f:
        json.dump(clip_plan, f, ensure_ascii=False, indent=2)
    with open(OUTPUT_SEGMENTS_LOCATED, 'w', encoding='utf-8') as f:
        json.dump({"segments": located_segments}, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"✅ clip_plan.json → {OUTPUT_CLIP_PLAN}")
    print(f"✅ segments_located.json → {OUTPUT_SEGMENTS_LOCATED}")

    matched = sum(1 for s in located_segments if s["match_score"] > 0)
    print(f"\n📊 定位: {matched}/{len(located_segments)} 匹配成功")
    for s in located_segments:
        icon = "✅" if s["match_score"] > 0.5 else ("⚠️" if s["match_score"] > 0 else "🔧")
        print(f"  {icon} seg_{s['seg_id']} ep{s['video_episode']} "
              f"[{s['video_start']:.0f}s - {s['video_end']:.0f}s] "
              f"→ clip[{s['clip_start']:.0f}s - {s['clip_end']:.0f}s] "
              f"score={s['match_score']:.0%}")


if __name__ == "__main__":
    main()
