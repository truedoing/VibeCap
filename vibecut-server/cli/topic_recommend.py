#!/usr/bin/env python3
"""选题推荐 — 「剧情弧」挖掘（取代全局散统计）

核心：选题主体是「剧情弧」（2-5 集、有起有收的连续冲突），
不是关系强度/冲突密度这种全局散点（散抽会变成金句盘点型）。

弧挖掘键：结构化 synopsis 的 character_arcs[].relations_change 的「关系质变点」，
这些质变点天然标记了弧的起止边界。

用法:
  cd vibecut-server
  /opt/anaconda3/bin/python3 cli/topic_recommend.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(SERVER_DIR.parent))

from lib.vlm_cache import KNOWN_CHARACTERS
from lib.synopsis import load_synopsis

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent / "都挺好"

# 关系质变词（relations_change 里标记"弧边界"的词）
TURN_WORDS = ['破裂', '决裂', '离婚', '恶化', '冰点', '和解', '和好', '觉醒', '道歉',
              '认错', '还债', '救赎', '守护', '原谅', '回归', '改善', '决裂', '冲突',
              '分手', '崩', '翻脸', '决裂', '对立', '联手', '反目']


def load_all_arc_points():
    """从结构化 synopsis 提取每个角色的「关系质变点」，作为弧边界候选。

    返回: {char: [(ep, arc_summary, relations_change_text), ...]}
    """
    points = defaultdict(list)
    for ep in range(1, 47):
        d = load_synopsis(PROJECT_DIR, ep)
        for a in d.get("character_arcs", []):
            char = a.get("character", "")
            if char not in KNOWN_CHARACTERS:
                continue
            arc = a.get("arc", "")
            rc = "；".join(a.get("relations_change", []))
            # 只有含质变词的集才作为弧边界
            if any(w in (arc + rc) for w in TURN_WORDS):
                points[char].append((ep, arc, rc))
    return points


def mine_arcs(min_eps=2, max_eps=5, top=10):
    """按关系质变点切弧：把连续/相近的质变点聚成 2-5 集窗口。

    返回: [{title, type, episodes, evidence, arc_type}]
    """
    points = load_all_arc_points()
    arcs = []

    for char, pts in points.items():
        # 按集号排序质变点
        pts = sorted(pts, key=lambda x: x[0])
        # 滑窗聚合：连续质变点间距 ≤2 集视为同一弧
        i = 0
        while i < len(pts):
            start_ep = pts[i][0]
            window = [pts[i]]
            j = i + 1
            while j < len(pts) and pts[j][0] - window[-1][0] <= 2:
                window.append(pts[j])
                j += 1
            # 窗口集数范围
            ep_span = [w[0] for w in window]
            span = max(ep_span) - min(ep_span) + 1
            if min_eps <= span <= max_eps:
                # 判断弧类型：起承转合里有没有"反转"
                first_rc = window[0][2]
                last_rc = window[-1][2]
                arc_type = "性格弧"
                if any(w in first_rc for w in ['恶化', '冰点', '破裂', '离婚']) and \
                   any(w in last_rc for w in ['和解', '和好', '觉醒', '守护']):
                    arc_type = "救赎弧"
                elif any(w in first_rc for w in ['和好', '和解', '承诺']) and \
                     any(w in last_rc for w in ['离婚', '破裂', '决裂']):
                    arc_type = "崩塌弧"

                title = f"{char}：{window[0][1][:20]}→{window[-1][1][:20]}"
                arcs.append({
                    "title": title,
                    "type": "arc",
                    "episodes": sorted(set(ep_span)),
                    "evidence": f"弧窗口 {min(ep_span)}-{max(ep_span)}（{span}集）· {arc_type}",
                    "arc_type": arc_type,
                })
            i = j

    # 排序：弧内质变点多的（戏剧性强）优先
    arcs.sort(key=lambda x: -len(x["episodes"]))
    return arcs[:top]


def conflict_density(scenes, top=3):
    """（保留，作补充信号）冲突情绪占比 TOP 集 — 单集爆发型选题"""
    ep_conf = defaultdict(lambda: [0, 0])
    for s in scenes:
        ep_conf[s['ep']][1] += 1
        if any(c in s['mood'] for c in {'愤怒', '激烈', '紧张', '压抑', '冲突'}):
            ep_conf[s['ep']][0] += 1
    ranked = sorted(ep_conf.items(), key=lambda x: -(x[1][0] / x[1][1]))
    return [(ep, c, total) for ep, (c, total) in ranked[:top]]


def main():
    scenes = None
    # 弧挖掘（主体）：只挖人物性格弧；事件弧由故事师产出（读全局概要，懂事件）
    arcs = mine_arcs()

    print("=" * 70)
    print("选题推荐 — 「剧情弧」挖掘（人物弧 + 事件弧）")
    print("=" * 70)
    print(f"\n共识别 {len(arcs)} 个剧情弧候选：")
    for a in arcs:
        print(f"  [{a['arc_type']}] {a['title']}")
        print(f"        集 {a['episodes']} · {a['evidence']}")

    # 构建候选给制片 Agent
    candidates = []
    for a in arcs:
        candidates.append({
            "title": a["title"],
            "type": a["type"],
            "episodes": a["episodes"],
            "evidence": a["evidence"],
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

