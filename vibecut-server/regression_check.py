#!/usr/bin/env python3
"""回归测试: 对比 match_data.json 与 approved_snapshot.json, 标记变化"""
import json, sys
from pathlib import Path

WORK_DIR = Path(__file__).parent.parent / "work_dir"
SNAPSHOT = WORK_DIR / "approved_snapshot.json"
MATCH_DATA = WORK_DIR / "match_data.json"

def main():
    if not MATCH_DATA.exists():
        print("❌ match_data.json 不存在，先跑 sentence_clip_builder_v3.py")
        return

    with open(MATCH_DATA) as f:
        current = json.load(f)

    # 如果没有快照, 保存当前为基准
    if not SNAPSHOT.exists():
        with open(SNAPSHOT, 'w', encoding='utf-8') as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        print("✅ 已保存基准快照 approved_snapshot.json")
        return

    with open(SNAPSHOT) as f:
        approved = json.load(f)

    changes = []
    for sid in sorted(current.keys(), key=int):
        if sid not in approved: continue
        for i, (cur, app) in enumerate(zip(current[sid]["narr"], approved[sid]["narr"])):
            # 对比关键字段
            for key in ["file", "has_supp", "supp_file", "score"]:
                cv = cur.get(key); av = app.get(key)
                if cv != av:
                    changes.append(f"⚠️ S{sid}-{i}: {key} {av} → {cv}")

    if changes:
        print(f"🔴 回归检测到 {len(changes)} 处变化:")
        for c in changes:
            print(f"  {c}")
        print(f"\n如需接受新结果: cp {MATCH_DATA} {SNAPSHOT}")
    else:
        print("🟢 回归测试通过 — 与审核快照一致")

    # 如果用户想接受新结果
    if "--accept" in sys.argv:
        with open(SNAPSHOT, 'w', encoding='utf-8') as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        print("✅ 已更新基准快照")

if __name__ == "__main__":
    main()
