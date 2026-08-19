#!/usr/bin/env python3
"""应用拆分方案 — 将 MIXED 场景按断点拆成两个场景, 重建 scene_map + VLM 缓存

- scene_map: MIXED 场景替换为两个半段 (用 split_plan 生成的 chars/loc/event/mood)
- VLM 缓存: 未拆分场景复用旧条目(重排索引), 新半段标记 needs_vlm 待重跑
- 备份: 已由外部做 (scene_map.json.presplit)

用法:
  python3 cli/apply_splits.py --ep 32
  python3 cli/apply_splits.py              # 全部
"""

import argparse, json, sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SOURCES_DIR = BASE_DIR / "都挺好" / "sources"


def apply_episode(ep: int) -> int:
    ep_dir = SOURCES_DIR / f"ep{ep}"
    sm_file = ep_dir / "scene_map.json"
    plan_file = ep_dir / "split_plan.json"
    vlm_file = ep_dir / "vlm_seg_cache_v3.json"
    if not sm_file.exists() or not plan_file.exists():
        return 0
    scene_map = json.load(open(sm_file))
    plan = json.load(open(plan_file))
    old_vlm = json.load(open(vlm_file)) if vlm_file.exists() else {}

    new_sm = []
    idx_map = {}      # old_idx -> new_idx (未拆分场景)
    new_halves = []   # (new_idx, half_data)

    for i, s in enumerate(scene_map):
        if str(i) in plan:
            p = plan[str(i)]
            for half in (p['half1'], p['half2']):
                if "error" in half:
                    # 半段生成失败 → 保留原场景不拆
                    idx_map[i] = len(new_sm)
                    new_sm.append(s)
                    break
                new_sm.append({
                    "time_range": half.get("range", []),
                    "characters": half.get("chars", []),
                    "location": half.get("location", ""),
                    "event": half.get("event", ""),
                    "mood": half.get("mood", ""),
                })
                new_halves.append((len(new_sm) - 1, half))
        else:
            idx_map[i] = len(new_sm)
            new_sm.append(s)

    # 重建 VLM 缓存
    new_vlm = {}
    for old_i, new_i in idx_map.items():
        if str(old_i) in old_vlm:
            new_vlm[str(new_i)] = old_vlm[str(old_i)]
    for new_i, half in new_halves:
        rng = half.get("range", [0, 0])
        new_vlm[str(new_i)] = {
            "needs_vlm": True,
            "start": rng[0], "end": rng[1],
            "scene_map_index": new_i,
            "characters_hint": half.get("chars", []),
            "location_hint": half.get("location", ""),
            "event_hint": half.get("event", ""),
        }

    json.dump(new_sm, open(sm_file, "w"), ensure_ascii=False, indent=2)
    json.dump(new_vlm, open(vlm_file, "w"), ensure_ascii=False, indent=2)
    print(f"EP{ep}: {len(scene_map)} → {len(new_sm)} 场景 (+{len(new_halves)} 半段待VLM)")
    return len(new_halves)


def main():
    p = argparse.ArgumentParser(description="应用拆分方案")
    p.add_argument("--ep", default=None)
    args = p.parse_args()
    if args.ep:
        eps = [int(e.strip()) for e in args.ep.split(",")]
    else:
        eps = sorted(int(d.name[2:]) for d in SOURCES_DIR.iterdir()
                     if d.is_dir() and d.name.startswith("ep") and d.name[2:].isdigit())
    total = 0
    for ep in eps:
        total += apply_episode(ep)
    print(f"\n共拆分出 {total} 个新半段 (需跑 VLM)")


if __name__ == "__main__":
    main()
