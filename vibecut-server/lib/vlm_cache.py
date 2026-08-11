"""VLM 场景缓存加载器 — 惰性加载 46 集 vlm_seg_cache_v3 到内存

供 handlers/storyboard.py、handlers/search.py 等模块共用。
"""

import json
from pathlib import Path

# ── 项目配置 (由 main.py 启动时通过 set_project_dir 注入) ──
_project_dir = None


def set_project_dir(path):
    """由 main.py 调用，设置项目数据目录"""
    global _project_dir
    _project_dir = Path(path)


# ── 模块级缓存 ──
_cache = None    # {ep: {scene_idx: dict}}
_char_counts = {}  # {"苏明玉": 120, ...}

# ── 匹配引擎常量 ──
HIGH_CONFLICT_MOODS = {
    '激烈', '愤怒', '争执', '冲突', '激动', '绝望', '对峙',
    '质问', '愤怒无奈', '紧张争执', '冲突激烈'
}
LOW_ENERGY_VLM_TONES = {
    '温和', '平静', '轻松', '日常', '关切', '温馨', '柔和', '自然',
    '温和关切', '平静正式', '轻松日常'
}
KNOWN_CHARACTERS = ['苏大强', '苏明哲', '苏明成', '苏明玉', '朱丽', '吴非', '小蔡', '老聂']


def load():
    """惰性加载 46 集 vlm_seg_cache_v3 到内存，统计角色出场次数"""
    global _cache, _char_counts
    if _cache is not None:
        return _cache

    if _project_dir is None:
        raise RuntimeError("vlm_cache.set_project_dir() 尚未调用")

    sources = _project_dir / "sources"
    _cache = {}
    _char_counts = {}

    for ep_dir in sources.iterdir():
        if not ep_dir.is_dir() or not ep_dir.name.startswith("ep"):
            continue
        ep = int(ep_dir.name[2:])
        vlm_f = ep_dir / "vlm_seg_cache_v3.json"
        sm_f = ep_dir / "scene_map.json"
        if not vlm_f.exists() or not sm_f.exists():
            continue
        try:
            vlm = json.load(open(vlm_f))
            sm = json.load(open(sm_f))
        except Exception:
            continue

        ep_data = {}
        for i, seg in enumerate(sm):
            v = vlm.get(str(i), {})
            actions = v.get("actions", [])
            if isinstance(actions, list):
                flat = []
                for a in actions:
                    if isinstance(a, list):
                        flat.extend(a)
                    else:
                        flat.append(str(a))
                actions = flat

            chars = seg.get("characters", [])
            for ch in chars:
                _char_counts[ch] = _char_counts.get(ch, 0) + 1

            ep_data[i] = {
                "ep": ep, "scene_id": i,
                "start": seg["time_range"][0], "end": seg["time_range"][1],
                "characters": seg.get("characters", []),
                "location": seg.get("location", ""),
                "event": seg.get("event", ""),
                "mood": seg.get("mood", ""),
                "visual_summary": v.get("visual_summary", ""),
                "shot_size": v.get("shot_size", ""),
                "composition": v.get("composition", ""),
                "angle": v.get("angle", ""),
                "emotional_tone": v.get("emotional_tone", ""),
                "intensity": v.get("intensity", 3),
                "lighting": v.get("lighting", ""),
                "actions": actions,
            }
        _cache[ep] = ep_data

    return _cache


def get_char_counts():
    """返回角色出场统计 (确保缓存已加载)"""
    if _cache is None:
        load()
    return dict(_char_counts)


def reset():
    """清除缓存 (测试/调试用)"""
    global _cache, _char_counts
    _cache = None
    _char_counts = {}
