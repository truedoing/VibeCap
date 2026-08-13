#!/usr/bin/env python3
"""ASR 人名标准化 — 修复 whisper 转写的同音字误识别人名

扫描所有集的 asr_result.json，把误识别的人名替换为标准名。

误识别映射表（来自全量扫描统计）:
  朱莉  → 朱丽  (107次, 同音)
  明诚  → 明成  (107次, 同音)
  明城  → 明成  (5次)
  明昌  → 明成  (4次)
  宋明  → 苏明  (54次, 宋=苏 误识)
  宋家  → 苏家  (1次)
  小菜  → 小蔡  (6次)
  吴飞  → 吴非  (5次)
  吴菲  → 吴非  (5次)

用法:
  python3 cli/normalize_asr_names.py            # 全部46集
  python3 cli/normalize_asr_names.py --ep 41    # 单集
  python3 cli/normalize_asr_names.py --dry-run  # 只统计不改
"""

import json, argparse
from pathlib import Path
from collections import Counter

# 误识别 → 标准名映射统一从 lib.names 引入 (单一真相，与 scene_map prompt 一致)
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.names import NAME_MAP, normalize_names

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # cli/ → vibecut-server/ → VIBECAP/
DRAMA_DIR = BASE_DIR / "都挺好"
SOURCES_DIR = DRAMA_DIR / "sources"


def normalize_episode(ep: int, dry_run: bool = False) -> Counter:
    asr_file = SOURCES_DIR / f"ep{ep}" / "asr_result.json"
    if not asr_file.exists():
        return Counter()

    data = json.load(open(asr_file))
    counter = Counter()
    changed = 0

    for seg in data:
        if "text" not in seg or not seg["text"]:
            continue
        new_text = normalize_names(seg["text"])
        if new_text != seg["text"]:
            for wrong in NAME_MAP:
                if wrong in seg["text"]:
                    counter[wrong] += seg["text"].count(wrong)
            seg["text"] = new_text
            changed += 1

    if not dry_run and changed > 0:
        json.dump(data, open(asr_file, "w"), ensure_ascii=False, indent=2)

    return counter


def main():
    p = argparse.ArgumentParser(description="ASR 人名标准化")
    p.add_argument("--ep", default=None, help="单集处理 (逗号分隔多集)")
    p.add_argument("--dry-run", action="store_true", help="只统计不改")
    args = p.parse_args()

    if args.ep:
        eps = [int(e.strip()) for e in args.ep.split(",")]
    else:
        eps = sorted(
            int(d.name[2:]) for d in SOURCES_DIR.iterdir()
            if d.is_dir() and d.name.startswith("ep") and d.name[2:].isdigit()
        )

    total = Counter()
    for ep in eps:
        c = normalize_episode(ep, args.dry_run)
        if c:
            total.update(c)
            detail = ", ".join(f"{k}→{NAME_MAP[k]}×{v}" for k, v in c.most_common())
            print(f"EP{ep}: {detail}")
        else:
            print(f"EP{ep}: 无误识别")

    print(f"\n{'[dry-run] ' if args.dry_run else ''}总修复: {sum(total.values())} 处")
    for wrong, cnt in total.most_common():
        print(f"  {wrong} → {NAME_MAP[wrong]}: {cnt}次")


if __name__ == "__main__":
    main()
