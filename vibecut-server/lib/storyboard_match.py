"""分镜结构化匹配引擎 v8.5

给定一个 LLM 生成的 shot query，从 VLM 场景缓存中评分匹配最优场景段。

纯函数，无 FastAPI/Flask 依赖，可独立测试。
"""

from lib.vlm_cache import load as load_vlm_cache
from lib.vlm_cache import HIGH_CONFLICT_MOODS, LOW_ENERGY_VLM_TONES


def match_shot_query(query: dict, num: int = 5, used_scene_keys: set = None,
                     main_char: str = "", focus_eps: set = None):
    """给定一个分镜查询，从 v3 缓存中匹配最优场景段

    used_scene_keys: 已在前置分镜中使用的场景键集合，用于跨镜去重
    main_char: 推断的主角名，用于验证 visual_summary 是否真正描述该人物
    focus_eps: 锚定的剧集号集合，这些剧集的场景优先匹配
        支持多层权重: set(int) 或 list of (weight, set(int))
    """
    cache = load_vlm_cache()
    scored = []

    target_chars = set(query.get("characters", []))
    target_emotions = set(query.get("emotional_tone", []))
    min_intensity = query.get("intensity_min", 1)
    target_shot = query.get("shot_size", "")
    location_hint = query.get("location_hint", "")
    action_hint = query.get("action_hint", "")
    used = used_scene_keys or set()
    focus = focus_eps or set()

    # v8.4: 兼容旧版 set 和新版 list of (weight, set) 格式
    focus_layers = []
    if isinstance(focus, list):
        focus_layers = focus
    elif focus:
        focus_layers = [(10, focus)]  # 旧版兼容: 统一+10

    for ep, ep_data in cache.items():
        for idx, s in ep_data.items():
            score = 0
            scene_key = f"{s['ep']}_{s['scene_id']}"
            desc = s["visual_summary"] + " " + s["event"] + " " + s["location"]

            # 0. 跨镜去重
            if scene_key in used:
                score -= 30

            # 0.5 剧集锚定: 三层权重
            if focus_layers:
                for ep_w, eps_set in focus_layers:
                    if s["ep"] in eps_set:
                        score += ep_w
                        break

            # 1. 人物精确匹配
            chars = set(s["characters"])
            if target_chars:
                overlap = chars & target_chars
                if overlap:
                    score += len(overlap) * 15
                else:
                    score -= 10

            # 1.5 画面主体验证
            if main_char and main_char in s["visual_summary"]:
                score += 5
            elif main_char and main_char in chars:
                score -= 4
            if len(s["visual_summary"]) > 30:
                score += 2

            # ── v8.5: scene_map mood vs VLM 情绪冲突检测 ──
            effective_intensity = s["intensity"]
            scene_mood = s.get("mood", "")
            vlm_tone = str(s.get("emotional_tone", ""))
            vlm_intensity = s.get("intensity", 3)

            mood_high = any(m in scene_mood for m in HIGH_CONFLICT_MOODS)
            tone_low = any(t in vlm_tone for t in LOW_ENERGY_VLM_TONES) or vlm_intensity <= 2

            # 先算 location 是否匹配（mood 补偿门槛）
            loc_relevant = _location_relevant(location_hint, s.get("location", ""))

            if mood_high and tone_low and loc_relevant:
                score += 8
                effective_intensity = max(vlm_intensity, 3)
                for te in target_emotions:
                    if te in scene_mood:
                        score += 5

            # 1.6 情绪匹配
            for emo in target_emotions:
                if emo in desc:
                    score += 8

            # 强度匹配
            if effective_intensity >= min_intensity:
                score += max(0, (effective_intensity - min_intensity + 1)) * 3

            # 景别匹配
            score += _shot_size_score(target_shot, s.get("shot_size", ""))

            # 地点匹配
            score += _location_score(location_hint, s.get("location", ""))

            # 动作匹配
            score += _action_score(action_hint, desc)

            scored.append((score, s))

    scored.sort(key=lambda x: -x[0])
    seen = set()
    results = []
    for score, s in scored:
        key = f"{s['ep']}_{s['scene_id']}"
        if key in seen:
            continue
        seen.add(key)
        results.append({**s, "match_score": score})
        if len(results) >= num:
            break
    return results


# ── 评分辅助函数 ──

def _shot_size_score(target_shot: str, scene_shot: str) -> int:
    """景别匹配评分"""
    if not target_shot or not scene_shot:
        return 0
    if target_shot == scene_shot:
        return 6
    shot_order = ["特写", "近景", "中景", "全景", "远景"]
    try:
        ts_i = shot_order.index(target_shot)
        ss_i = shot_order.index(scene_shot)
        dist = abs(ts_i - ss_i)
        return max(0, 5 - dist)
    except ValueError:
        return 0


def _location_relevant(hint: str, loc: str) -> bool:
    """判断 location_hint 和 scene location 是否可关联"""
    if not hint:
        return True  # 无约束时不限制
    if hint in loc or loc in hint:
        return True
    stop_suffixes = ['客厅', '餐厅', '卧室', '厨房', '走廊', '门口', '会议室', '办公室']
    hc, lc = hint, loc
    for sfx in stop_suffixes:
        hc = hc[:-len(sfx)] if hc.endswith(sfx) else hc
        lc = lc[:-len(sfx)] if lc.endswith(sfx) else lc
    return bool(hc and lc and (hc in lc or lc in hc))


def _location_score(hint: str, loc: str) -> int:
    """地点匹配评分"""
    if not hint:
        return 0
    if hint in loc or loc in hint:
        return 4
    stop_suffixes = ['客厅', '餐厅', '卧室', '厨房', '走廊', '门口', '会议室', '办公室']
    hc, lc = hint, loc
    for sfx in stop_suffixes:
        hc = hc[:-len(sfx)] if hc.endswith(sfx) else hc
        lc = lc[:-len(sfx)] if lc.endswith(sfx) else lc
    if hc and lc and (hc in lc or lc in hc):
        return 3
    return 0


def _action_score(hint: str, desc: str) -> int:
    """动作匹配评分 (步长1的2字+3字滑窗)"""
    if not hint:
        return 0
    # 2字滑窗
    sliding_kws = [hint[i:i+2] for i in range(len(hint)-1)
                   if len(hint[i:i+2]) == 2]
    sliding_hits = sum(1 for kw in sliding_kws if kw in desc)
    # 3字滑窗
    trim_kws = [hint[i:i+3] for i in range(len(hint)-2)
                if len(hint[i:i+3]) == 3]
    trim_hits = sum(1 for kw in trim_kws if kw in desc)

    total_hits = sliding_hits * 2 + trim_hits
    total_kws = len(sliding_kws) * 2 + len(trim_kws)

    if total_kws > 0 and total_hits >= total_kws * 0.3:
        return 4
    elif sliding_hits >= 2:
        return 2
    return 0
