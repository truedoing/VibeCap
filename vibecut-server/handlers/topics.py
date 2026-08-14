"""选题推荐 handler — 供 API 和 CLI 共用的核心逻辑

抽取自 cli/topic_recommend.py，做两件事：
1. 参数化（PROJECT_DIR / episodes 从 config 读，不再硬编码"都挺好"/46集）
2. 抽候选组装逻辑，避免 CLI/API 重复
"""
import sys
from collections import defaultdict
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(SERVER_DIR.parent))

from lib.vlm_cache import KNOWN_CHARACTERS
from lib.synopsis import load_synopsis

# 关系质变词（relations_change 里标记"弧边界"的词）
TURN_WORDS = ['破裂', '决裂', '离婚', '恶化', '冰点', '和解', '和好', '觉醒', '道歉',
              '认错', '还债', '救赎', '守护', '原谅', '回归', '改善', '决裂', '冲突',
              '分手', '崩', '翻脸', '决裂', '对立', '联手', '反目']


def load_all_arc_points(project_dir: Path, total_episodes: int = 46):
    """从结构化 synopsis 提取每个角色的「关系质变点」，作为弧边界候选。

    返回: {char: [(ep, arc_summary, relations_change_text), ...]}
    """
    points = defaultdict(list)
    for ep in range(1, total_episodes + 1):
        d = load_synopsis(project_dir, ep)
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


def mine_arcs(project_dir: Path, total_episodes: int = 46, min_eps=2, max_eps=5, top=10):
    """按关系质变点切弧：把连续/相近的质变点聚成 2-5 集窗口。

    返回: [{title, type, episodes, evidence, arc_type}]
    """
    points = load_all_arc_points(project_dir, total_episodes)
    arcs = []

    for char, pts in points.items():
        pts = sorted(pts, key=lambda x: x[0])
        i = 0
        while i < len(pts):
            window = [pts[i]]
            j = i + 1
            while j < len(pts) and pts[j][0] - window[-1][0] <= 2:
                window.append(pts[j])
                j += 1
            ep_span = [w[0] for w in window]
            span = max(ep_span) - min(ep_span) + 1
            if min_eps <= span <= max_eps:
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

    arcs.sort(key=lambda x: -len(x["episodes"]))
    return arcs[:top]


def build_candidates(arcs: list, story_map: dict = None) -> list:
    """组装候选选题（弧挖掘 + 故事师叙事向选题），统一成 {title, type, episodes, evidence}。

    复用点：CLI 和 API 都调这个，避免各写一遍。
    """
    candidates = []
    for a in arcs:
        candidates.append({
            "title": a["title"],
            "type": a["type"],
            "episodes": a["episodes"],
            "evidence": a["evidence"],
        })
    if story_map:
        for t in story_map.get("topic_suggestions", []):
            candidates.append({
                "title": t.get("title"),
                "type": t.get("type", "narrative"),
                "episodes": t.get("episodes_covered", []),
                "evidence": t.get("hook", t.get("angle", "")),
            })
    return candidates


def recommend_topics(project_dir: Path, drama_name: str,
                     total_episodes: int = 46, top: int = 10) -> dict:
    """完整选题推荐：弧挖掘 → 故事师叙事向 → 制片排序。

    返回: {"ok": True, "ranked": [...], "top_pick": ..., "strategy_note": ...}
    """
    from agents.drama_script_agents import story_master_agent, producer_agent

    arcs = mine_arcs(project_dir, total_episodes)
    story_res = story_master_agent(project_dir, drama_name, None)
    if not story_res.get("ok"):
        return {"ok": False, "error": f"故事师失败: {story_res.get('error', '?')}"}

    candidates = build_candidates(arcs, story_res.get("result"))
    prod_res = producer_agent(candidates)
    if not prod_res.get("ok"):
        return {"ok": False, "error": f"制片失败: {prod_res.get('error', '?')}"}

    result = prod_res["result"]
    # 给 ranked 每个选题回填 episodes（制片可能已带，兜底按标题匹配候选）
    cand_eps = {c["title"]: c.get("episodes", []) for c in candidates}
    for r in result.get("ranked", []):
        if not r.get("episodes"):
            # 制片重写标题后 title 对不上候选，用"部分重叠"匹配
            best = []
            for c in candidates:
                if _overlap(r.get("title", ""), c["title"]) >= 3 and c.get("episodes"):
                    best = c["episodes"]
                    break
            r["episodes"] = best or cand_eps.get(r.get("title", ""), [])
    return {"ok": True, **result}


def _overlap(a: str, b: str) -> int:
    """两个字符串的最长公共子串长度（用于宽松匹配）"""
    if not a or not b:
        return 0
    best = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            best = max(best, k)
    return best
