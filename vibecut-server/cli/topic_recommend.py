#!/usr/bin/env python3
"""选题推荐 — 从 1511 个结构化场景做「数据向」选题挖掘

三类统计信号（与故事师的「叙事向」选题互补）：
1. 冲突密度榜：冲突情绪占比 TOP 集 → "最窒息的一集"选题
2. 关系强度榜：人物共现 TOP 关系 → "这对父子/夫妻/兄妹"选题
3. 情绪弧线榜：人物主情绪「负转正/正转负」→ "救赎/崩塌弧线"选题

用法:
  cd vibecut-server
  /opt/anaconda3/bin/python3 cli/topic_recommend.py
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(SERVER_DIR.parent))

from lib.vlm_cache import KNOWN_CHARACTERS

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent / "都挺好"

# 冲突 / 缓和情绪词表（与 lib/scene_map.py 对齐）
CONFLICT = {'愤怒', '激烈', '紧张', '压抑', '冲突', '对抗', '尴尬', '焦虑', '严肃', '担忧', '无奈', '悲伤'}
SOFT = {'感动', '释然', '温馨', '轻松', '平静', '期待'}


def load_all_scenes():
    scenes = []
    for ep_dir in sorted((PROJECT_DIR / "sources").iterdir()):
        if not ep_dir.is_dir() or not ep_dir.name.startswith("ep"):
            continue
        try:
            ep = int(ep_dir.name[2:])
        except ValueError:
            continue
        f = ep_dir / "scene_map.json"
        if not f.exists():
            continue
        for s in json.load(open(f)):
            scenes.append({'ep': ep, **s})
    return scenes


def conflict_density(scenes, top=5):
    """冲突情绪占比 TOP 集"""
    ep_conf = defaultdict(lambda: [0, 0])
    for s in scenes:
        ep_conf[s['ep']][1] += 1
        if any(c in s['mood'] for c in CONFLICT):
            ep_conf[s['ep']][0] += 1
    ranked = sorted(ep_conf.items(), key=lambda x: -(x[1][0] / x[1][1]))
    return [(ep, c, total) for ep, (c, total) in ranked[:top]]


def relationship_strength(scenes, top=8):
    """人物共现 TOP 关系（只算主要角色之间的）"""
    co = Counter()
    for s in scenes:
        chars = [c for c in s.get('characters', []) if c in KNOWN_CHARACTERS]
        for i in range(len(chars)):
            for j in range(i + 1, len(chars)):
                pair = tuple(sorted([chars[i], chars[j]]))
                co[pair] += 1
    return co.most_common(top)


def emotion_arc(scenes, top=6):
    """人物主情绪「负转正/正转负」弧线（按集情绪符号序列）"""
    char_ep_sig = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # char -> ep -> [pos, neg]
    for s in scenes:
        for ch in s.get('characters', []):
            if ch not in KNOWN_CHARACTERS:
                continue
            if any(c in s['mood'] for c in CONFLICT):
                char_ep_sig[ch][s['ep']][1] += 1
            elif any(c in s['mood'] for c in SOFT):
                char_ep_sig[ch][s['ep']][0] += 1

    arcs = []
    for ch, ep_sig in char_ep_sig.items():
        eps = sorted(ep_sig.keys())
        if len(eps) < 5:
            continue
        # 序列符号：正主导 = pos > neg，负主导 = neg > pos
        sign = {ep: (1 if ep_sig[ep][0] > ep_sig[ep][1] else -1) for ep in eps}
        early = eps[:max(1, len(eps)//3)]
        late = eps[2*max(1, len(eps)//3):]
        early_neg = sum(1 for ep in early if sign[ep] < 0) / len(early)
        # 结尾尖峰：最后 3 集里是否存在正主导
        late_pos = any(sign[ep] > 0 for ep in eps[-3:])
        # 救赎弧：前段负主导 + 结尾正尖峰
        if early_neg > 0.5 and late_pos:
            arcs.append((ch, "救赎(负转正)", early_neg, late_pos, len(eps)))
        # 崩塌弧：前段正主导 + 结尾负尖峰
        elif early_neg < 0.3 and any(sign[ep] < 0 for ep in eps[-3:]):
            arcs.append((ch, "崩塌(正转负)", early_neg, late_pos, len(eps)))
    arcs.sort(key=lambda x: -(x[3]))  # 按结尾尖峰强度排序
    return arcs[:top]


def main():
    scenes = load_all_scenes()
    print("=" * 70)
    print("选题推荐 — 数据向挖掘（scene_map 1511 场景）")
    print("=" * 70)

    # 收集数据向候选
    candidates = []
    for ep, c, total in conflict_density(scenes):
        candidates.append({
            "title": f"EP{ep}：全剧最窒息的一集",
            "type": "conflict",
            "episodes": [ep],
            "evidence": f"冲突密度 {c}/{total}={c/total:.0%}",
        })
    for (a, b), n in relationship_strength(scenes):
        candidates.append({
            "title": f"{a}与{b}：全剧最抓马的关系",
            "type": "relationship",
            "episodes": [],
            "evidence": f"同框 {n} 场",
        })
    for ch, kind, early, late, n_eps in emotion_arc(scenes):
        candidates.append({
            "title": f"{ch}的{kind}弧线",
            "type": "arc",
            "episodes": [],
            "evidence": f"出场 {n_eps} 集",
        })

    # 叙事向候选（故事师产出）
    from agents.drama_script_agents import story_master_agent, producer_agent
    from lib.env import load_env
    load_env()
    print("\n📖 故事师: 生成叙事向选题...")
    story_res = story_master_agent(PROJECT_DIR, "都挺好", None)
    if story_res.get("ok"):
        for t in story_res["result"].get("topic_suggestions", []):
            candidates.append({
                "title": t.get("title"),
                "type": t.get("type", "narrative"),
                "episodes": t.get("episodes_covered", []),
                "evidence": t.get("hook", t.get("angle", "")),
            })

    print("\n" + "=" * 70)
    print(f"共 {len(candidates)} 个候选选题，制片 Agent 决策中...")
    print("=" * 70)

    # 制片 Agent 决策
    prod_res = producer_agent(candidates)
    if not prod_res.get("ok"):
        print(f"❌ 制片 Agent 失败: {prod_res.get('error')}")
        return

    result = prod_res["result"]
    print(f"\n🎬 首推选题：{result.get('top_pick', '')}")
    print(f"📌 策略：{result.get('strategy_note', '')}")
    print("\n【制片排序结果】")
    for r in result.get("ranked", []):
        flag = "✅推荐" if r.get("recommend") else "  "
        s = r.get("scores", {})
        print(f"  {flag} {r.get('score')}分 {r.get('title')} "
              f"(流量{s.get('traffic')} 差异{s.get('differentiation')} 钩子{s.get('hook')} 匹配{s.get('fit')})")
        print(f"       理由: {r.get('reason', '')}")

    print("\n" + "=" * 70)
    print("提示：首推选题可直接喂给 cli/generate_drama.py --topic。")
    print("=" * 70)


if __name__ == "__main__":
    main()
