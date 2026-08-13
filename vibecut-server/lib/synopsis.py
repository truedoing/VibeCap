"""ep_synopsis 加载器 — 双格式兼容读取

升级前: {"synopsis": "纯文本流水账"}
升级后: {"theme": ..., "plot_arc": ..., "character_arcs": [...],
         "key_conflicts": [...], "emotional_curve": [...], "key_events": [...]}

load_synopsis() 对两种格式都返回 dict，并附带 _legacy 标记；
to_text() 把任意格式转成下游 LLM 可读的纯文本，统一消费方接入点。
"""

import json
from pathlib import Path

# 结构化格式的必填键（用于判定是否为新结构）
STRUCT_KEYS = ("theme", "plot_arc", "character_arcs", "key_conflicts",
               "emotional_curve", "key_events")


def load_synopsis(project_dir: Path, ep: int) -> dict:
    """加载单集概要，兼容新旧格式。

    返回 dict，键含 synopsis 数据；未找到/解析失败时返回空 dict。
    通过 data.get("_legacy") 判断是否为旧格式。
    """
    for name in (f"ep{ep}", f"ep{ep:02d}"):
        f = project_dir / "sources" / name / "ep_synopsis.json"
        if f.exists():
            try:
                data = json.load(open(f))
            except Exception:
                return {}
            data.setdefault("_legacy", "synopsis" in data and "theme" not in data)
            return data
    return {}


def to_text(data: dict) -> str:
    """把概要 dict 转成下游 LLM 可读文本（新/旧结构都支持）。"""
    if not data:
        return ""
    if data.get("_legacy") or "theme" not in data:
        return (data.get("synopsis") or "").strip()

    lines = []
    if data.get("theme"):
        lines.append(f"主题: {data['theme']}")
    if data.get("plot_arc"):
        lines.append(f"剧情脉络: {data['plot_arc']}")
    arcs = data.get("character_arcs") or []
    if arcs:
        items = []
        for a in arcs:
            s = a.get("character", "")
            if a.get("arc"):
                s += f": {a['arc']}"
            rc = a.get("relations_change") or []
            if rc:
                s += f"（{'；'.join(rc)}）"
            items.append(s)
        lines.append("人物弧线: " + " | ".join(items))
    conflicts = data.get("key_conflicts") or []
    if conflicts:
        lines.append("关键冲突: " + "、".join(conflicts))
    curve = data.get("emotional_curve") or []
    if curve:
        lines.append("情感曲线: " + " → ".join(curve))
    events = data.get("key_events") or []
    if events:
        ev = []
        for e in events:
            tr = e.get("time_range")
            s = e.get("event", "")
            if isinstance(tr, (list, tuple)) and len(tr) == 2:
                s += f" [{tr[0]}s-{tr[1]}s]"
            ev.append(s)
        lines.append("关键事件: " + "；".join(ev))
    return "\n".join(lines)
