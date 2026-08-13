#!/usr/bin/env python3
"""规范化 scene_map 的 mood 标签 —— 治本：把词表外标签映射回标准 15 词。

背景：场记Agent 生成 scene_map 时，99% 遵守了 15 个标准 mood 词，
但有 13 处用了词表外的精确词（坚定/震惊/感慨…），导致事实校验时
"情绪不符"误报。治本方案：压缩回 15 词，保持词表单一事实来源。

用法:
  cd vibecut-server
  python3 cli/normalize_mood.py --dry-run   # 预览改动
  python3 cli/normalize_mood.py             # 实际写回
"""
import argparse
import json
import sys
from pathlib import Path

# 词表外 → 标准 15 词映射
MAPPING = {
    "坚定": "严肃",
    "得意": "轻松",
    "惊喜": "温馨",
    "感慨": "感动",
    "孤独": "压抑",
    "满意": "平静",
    "震惊": "紧张",
    "神秘": "严肃",
    "疑惑": "焦虑",
    "疲惫": "压抑",
}

# 标准 15 词（单一事实来源，与 scene_map.py / script_drama.py / harness 对齐）
VOCAB = {"温馨", "激烈", "紧张", "愤怒", "悲伤", "轻松", "焦虑",
         "压抑", "尴尬", "感动", "严肃", "平静", "无奈", "期待", "担忧"}


def find_scene_maps(project_dir: Path):
    for ep_dir in sorted(project_dir.glob("sources/ep*")):
        if not ep_dir.is_dir():
            continue
        f = ep_dir / "scene_map.json"
        if f.exists():
            yield int(ep_dir.name[2:]), f


def normalize(project_dir: Path, dry_run: bool = True):
    total_changed = 0
    for ep, f in find_scene_maps(project_dir):
        data = json.load(open(f))
        changed = False
        for i, scene in enumerate(data):
            mood = scene.get("mood", "")
            if mood in MAPPING:
                new = MAPPING[mood]
                print(f"  EP{ep} 场景[{i}]: '{mood}' → '{new}'  "
                      f"(event='{scene.get('event','')[:25]}')")
                if not dry_run:
                    scene["mood"] = new
                total_changed += 1
                changed = True
        if changed and not dry_run:
            json.dump(data, open(f, "w"), ensure_ascii=False, indent=2)
    print(f"\n共 {total_changed} 处 mood 标签规范化" + ("（dry-run，未写回）" if dry_run else "（已写回）"))
    return total_changed


def verify(project_dir: Path):
    """规范化后校验：词表外标签应为 0"""
    import collections
    out = collections.Counter()
    for ep, f in find_scene_maps(project_dir):
        for scene in json.load(open(f)):
            m = scene.get("mood", "")
            if m not in VOCAB:
                out[m] += 1
    if out:
        print("⚠️ 仍有词表外 mood:", dict(out))
        return False
    print("✅ 全部 mood 标签已落在标准 15 词表内")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只预览不写回")
    args = ap.parse_args()

    project_dir = Path(__file__).resolve().parent.parent.parent / "都挺好"
    print("=" * 60)
    print("scene_map mood 标签规范化（压缩回 15 词）")
    print("=" * 60)
    normalize(project_dir, dry_run=args.dry_run)
    if not args.dry_run:
        print()
        verify(project_dir)
