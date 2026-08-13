#!/usr/bin/env python3
"""ep_synopsis 结构化升级迁移 — 把旧的纯文本剧情简介重新生成为宏观叙事索引

新结构 (每集严格 JSON):
  theme / plot_arc / character_arcs / key_conflicts / emotional_curve / key_events

用法:
  python3 cli/regenerate_synopsis.py --ep 41            # 单集验证
  python3 cli/regenerate_synopsis.py --ep 41,39,1       # 多集
  python3 cli/regenerate_synopsis.py                    # 全部 46 集
  python3 cli/regenerate_synopsis.py --force            # 即使已是新结构也重生成
  python3 cli/regenerate_synopsis.py --dry-run          # 只统计不生成
"""

import json, argparse, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # cli/ → vibecut-server/

from lib.scene_map import SceneMapAgent
from lib.synopsis import load_synopsis

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # cli/ → vibecut-server/ → VIBECAP/
DRAMA_DIR = BASE_DIR / "都挺好"
SOURCES_DIR = DRAMA_DIR / "sources"

STRUCT_KEYS = ("theme", "plot_arc", "character_arcs", "key_conflicts",
               "emotional_curve", "key_events")


def _is_structured(data: dict) -> bool:
    return "theme" in data


def _has_real_content(data: dict) -> bool:
    """新结构是否真正生成成功 (theme/plot_arc 至少一个非空)。"""
    if not _is_structured(data):
        return False
    return bool((data.get("theme") or "").strip()) or bool((data.get("plot_arc") or "").strip())


def _load_asr(ep: int) -> list:
    f = SOURCES_DIR / f"ep{ep}" / "asr_result.json"
    if f.exists():
        try:
            return json.load(open(f))
        except Exception:
            return []
    return []


def main():
    p = argparse.ArgumentParser(description="ep_synopsis 结构化升级迁移")
    p.add_argument("--ep", default=None, help="单集/多集 (逗号分隔)")
    p.add_argument("--force", action="store_true", help="已是新结构也重生成")
    p.add_argument("--dry-run", action="store_true", help="只统计不生成")
    args = p.parse_args()

    if args.ep:
        eps = [int(e.strip()) for e in args.ep.split(",")]
    else:
        eps = sorted(
            int(d.name[2:]) for d in SOURCES_DIR.iterdir()
            if d.is_dir() and d.name.startswith("ep") and d.name[2:].isdigit()
        )

    agent = SceneMapAgent()
    regenerated, skipped, failed = [], [], []

    for ep in eps:
        syn_file = SOURCES_DIR / f"ep{ep}" / "ep_synopsis.json"
        current = load_synopsis(DRAMA_DIR, ep)

        if _has_real_content(current) and not args.force:
            skipped.append(ep)
            print(f"EP{ep}: 已是新结构, 跳过 (--force 覆盖)")
            continue

        if not args.force and not _load_asr(ep):
            failed.append(ep)
            print(f"EP{ep}: 无 asr_result.json, 跳过")
            continue

        if args.dry_run:
            print(f"EP{ep}: [dry-run] 将重生成")
            continue

        data = agent.build_synopsis(_load_asr(ep), ep)
        if _has_real_content(data):
            json.dump(data, open(syn_file, "w"), ensure_ascii=False, indent=2)
            regenerated.append(ep)
            n_ev = len(data.get("key_events") or [])
            n_arc = len(data.get("character_arcs") or [])
            print(f"EP{ep}: ✅ 已生成 ({n_arc}弧光 / {n_ev}关键事件)")
        else:
            failed.append(ep)
            print(f"EP{ep}: ❌ 生成失败 (空结果), 保留原文件")

    print(f"\n{'='*50}")
    print(f"完成: 重生成 {len(regenerated)} 集 / 跳过 {len(skipped)} 集 / 失败 {len(failed)} 集")
    if regenerated:
        print(f"重生成: {regenerated}")
    if failed:
        print(f"失败: {failed}")


if __name__ == "__main__":
    main()
