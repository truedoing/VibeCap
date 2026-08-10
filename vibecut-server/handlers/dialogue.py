"""对话/台词/分镜 → dialouge_match, chat, storyboard_suggest, analyze_transcript, generate_from_outline"""

import json
import os
import re
import time

from config import project_name, project_type, PROJECT_DIR
from lib.llm import call_moonshot, call_moonshot_json, call_deepseek_json
from handlers.search import search, _asr_first_search, inject_speaker, search_asr_text
from handlers.media import serve_preview


# ── POST /dialogue_match ──
def dialogue_match(dialogue: str) -> dict:
    """拆解台词 + 匹配原剧 ASR"""
    if not dialogue or not dialogue.strip():
        return {"lines": []}

    lines = _dialogue_split_normalize(dialogue)

    results = []
    for line in lines:
        original = line.get("original", "")
        variants = line.get("variants", [original])
        best_match = None
        best_variant = ""

        for v in variants:
            matches = search_asr_text(v, limit=1)
            if matches:
                m = matches[0]
                if not best_match or m["score"] > best_match["score"]:
                    best_match = m
                    best_variant = v

        if best_match and best_match["score"] >= 5:
            normalized = best_match["text"][:80]
            confident = True
        else:
            normalized = variants[0] if variants else original
            confident = False

        results.append({
            "original": original,
            "normalized": normalized,
            "confident": confident,
            "variant_used": best_variant,
            "matches": [best_match] if best_match and confident else [],
        })

    return {"lines": results}


def _dialogue_split_normalize(dialogue: str) -> list:
    """DeepSeek 拆解台词 + 生成多个变体"""
    prompt = (
        "你是一个影视台词校对助手。用户给你一段解说脚本中的'高亮台词'，"
        "这段台词可能由多句拼凑而成，且经过了改写，与演员实际说的话不完全一致。\n\n"
        "请完成：\n"
        "1. 把台词拆成独立的对白句（去掉叙述性文字）\n"
        "2. 对每句，生成 3-5 个可能的原剧说法变体——想象演员实际可能怎么说出这句话。"
        "变体要覆盖不同的措辞、语序、省略方式。\n\n"
        '输出 JSON：{"lines":[{"original":"原文","variants":["变体1","变体2","变体3"]}]}\n\n'
        "示例：\n"
        '输入: "爸，你是想跟大哥去美国吧？"\n'
        '输出: {"lines":[{"original":"爸，你是想跟大哥去美国吧？","variants":["你想跟大哥去美国","他跟大哥去美国","他想跟你去美国","你要去美国找大哥","跟大哥去美国是吧"]}]}'
    )

    result = call_moonshot_json(prompt, f"高亮台词：{dialogue}\n\n输出JSON：",
                                temperature=0.7, max_tokens=1500, timeout=20,
                                label="dialogue_split")
    if result["ok"]:
        return result["data"].get("lines", [])

    # Fallback: 简单按标点拆分
    parts = re.split(r'[。！？?！]', dialogue)
    return [{"original": p.strip(), "variants": [p.strip()]} for p in parts if len(p.strip()) > 2]


# ── POST /chat ──
def chat(messages: list, context: dict, eps=None) -> dict:
    """对话式素材搜索"""
    if not messages:
        return {"reply": "请描述你想找的画面", "results": []}

    strategy = context.get("strategy", "")
    if not strategy and str(context.get("seq", "")) == "D":
        strategy = "asr_first"

    # ASR 优先路径
    if strategy == "asr_first":
        query = messages[-1].get("content", "")
        for prefix in ["ASR匹配：", "asr匹配：", "匹配台词：", "ASR台词匹配："]:
            if query.startswith(prefix):
                query = query[len(prefix):]
                break
        results = _asr_first_search(query, limit=5, eps=eps)
        enriched = inject_speaker(query, results, context)
        reply = _format_chat_reply(enriched or results, query)
        return {"reply": reply, "results": enriched or results, "action": "search"}

    # 语义搜索路径：LLM 意图理解
    intent = _chat_intent(messages, context)
    action = intent.get("action", "search")

    if action == "search":
        query = intent.get("query", "")
        if not query:
            query = messages[-1].get("content", "") if messages else ""
        mode = intent.get("mode", "semantic")
        results = search(query, mode=mode, limit=5, eps=eps)
        reply = intent.get("reply", "") or _format_chat_reply(results, query)
    elif action == "preview":
        ep = intent.get("ep", 1)
        t = intent.get("start", 0)
        sid = f"chat_{int(time.time())}"
        serve_preview(str(ep), float(t), sid)
        return {"reply": "预览生成中", "results": [], "action": "preview"}
    else:
        reply = intent.get("reply", "")
        results = search(messages[-1].get("content", ""), mode="semantic", limit=3)

    return {"reply": reply, "results": results, "action": action}


def _chat_intent(messages, context):
    """DeepSeek 理解对话意图"""
    sid = context.get("sid", "?")
    seq = context.get("seq", "?")
    narration = context.get("narration", "")

    mode_hint = (
        "当前匹配策略：语义搜索（画面匹配模式）\n"
        "规则：\n"
        "- 用视觉关键词：表情（严肃/愤怒/微笑）、动作（拍桌/站起/低头）、场景（办公室/老宅/客厅）\n"
        "- mode 固定为 \"semantic\"\n"
        "- query 控制在 50 字内\n"
    )

    system_prompt = (
        "你是 VibeCut 的 AI 剪辑助手，名字叫「小 V」。\n"
        "你正在帮助一位视频剪辑师，从电视剧《都挺好》的原剧素材中搜索匹配的镜头画面。\n\n"
        "你的风格：专业、热情、简洁。像一个熟悉这部剧的剪辑搭档。\n\n"
        f"当前工作上下文：解说段 S{sid}-{seq}\n"
        f"解说词内容：{narration[:200]}\n\n"
        + mode_hint + "\n"
        "你的任务：理解剪辑师的意图，输出 JSON。\n\n"
        "支持的 action:\n"
        '- "search": 剪辑师描述想要的画面 → 你精炼为搜索 query，附带 mode 字段\n'
        '- "chat": 闲聊、打招呼、问功能\n\n'
        '输出格式（严格 JSON）:\n'
        '{"action":"search", "query":"搜索词", "mode":"asr_first|semantic", "reply":"自然的回复"}\n'
        '{"action":"chat", "reply":"你的回复"}\n\n'
        "通用精炼规则：\n"
        "- 累积多轮对话中的条件，不要丢失之前的约束\n"
        "- 用户说'不要XX'→排除XX；'换XX'→替换条件\n"
        "- 用角色真名（苏大强、蒙总、苏明玉等），禁止用他/她\n"
        "- reply 要自然亲切，20 字内"
    )

    api_messages = [{"role": "system", "content": system_prompt}]
    for m in messages[-6:]:
        role = "assistant" if m.get("role") == "ai" else "user"
        api_messages.append({"role": role, "content": m.get("content", "")[:500]})
    api_messages.append({"role": "user", "content": "输出JSON："})

    result = call_moonshot_json(
        system_prompt,
        "\n".join(f"{m['role']}: {m['content']}" for m in api_messages[1:]),
        temperature=0.7, max_tokens=400, timeout=15, label="chat_intent",
    )
    if result["ok"]:
        return result["data"]
    return {"action": "search", "query": messages[-1].get("content", "") if messages else "",
            "reply": "让我帮你找找~"}


def _format_chat_reply(results, query):
    if not results:
        return '没找到匹配的镜头，换个角度描述试试？'
    return f'找到 {len(results)} 个匹配镜头，看看哪个合适~'


# ── POST /storyboard_suggest ──
# v4: 导演Agent — LLM 叙事理解 + 结构化分镜查询 + v3数据匹配

# 导演Agent prompt
DIRECTOR_PROMPT = """你是电视剧《都挺好》的分镜导演。根据解说词策划一个分镜序列，用原剧场景来匹配。

人物推断规则（按优先级）：
1. 封面/标题中出现的角色名 = 主角，权重最高（如"苏明成/炸弹视角" → 主角确定是苏明成）
2. 上下文解说词中出现的角色名 = 辅助信息
3. 解说词本身描述的行为特征 → 对照角色出场统计推断
4. 角色列表 + 出场次数: {KNOWN_CHARS}
5. 推断的主角必须填写在 main_char 字段中

可选景别：特写、近景、中景、全景、远景。
可选光线：自然光、暖调、冷调、暗调、高调。

任务：
1. 确定主角（基于封面 > 上下文 > 行为推断）
2. 设计 3 个分镜，每个分镜说明叙事目的
3. 为每个分镜输出结构化的素材查询条件

输出 JSON（严格格式，不要 markdown）：
{{
  "main_char": "主角名（必须填，从角色列表选）",
  "shots": [
    {{
      "purpose": "镜头1的叙事目的（≤12字）",
      "characters": ["人物名"],
      "shot_size": "景别",
      "emotional_tone": ["情绪标签"],
      "intensity_min": 强度下限1-5,
      "location_hint": "场景提示",
      "action_hint": "动作提示"
    }}
  ]
}}

规则：
- 人物必须从角色列表中选择，不得超过已知范围
- emotional_tone 从常见情绪词中选择（对峙/愤怒/压抑/低落/争执/温馨/紧张/冲突/激动/冷漠/冲动/兴奋/无奈/悲痛/严肃等）
- intensity_min 1=平静 3=有明显情绪 5=激烈爆发
- 3个分镜要有叙事递进关系（建立→发展→高潮或揭示）"""

# 结构化匹配引擎缓存
_vlm_cache = None  # {ep: {scene_idx: vlm_entry}}
_char_counts = {}  # {"苏明玉": 120, ...}

def _load_vlm_cache():
    """惰性加载 46 集 vlm_seg_cache_v3 到内存，统计角色出场次数"""
    global _vlm_cache, _char_counts
    if _vlm_cache is not None:
        return _vlm_cache
    from pathlib import Path
    sources = PROJECT_DIR / "sources"
    _vlm_cache = {}
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
            # 展平嵌套列表
            if isinstance(actions, list):
                flat = []
                for a in actions:
                    if isinstance(a, list): flat.extend(a)
                    else: flat.append(str(a))
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
        _vlm_cache[ep] = ep_data
    return _vlm_cache


def _match_shot_query(query: dict, num: int = 5):
    """给定一个分镜查询，从 v3 缓存中匹配最优场景段"""
    cache = _load_vlm_cache()
    scored = []

    target_chars = set(query.get("characters", []))
    target_emotions = set(query.get("emotional_tone", []))
    min_intensity = query.get("intensity_min", 1)
    target_shot = query.get("shot_size", "")
    location_hint = query.get("location_hint", "")
    action_hint = query.get("action_hint", "")

    for ep, ep_data in cache.items():
        for idx, s in ep_data.items():
            score = 0
            desc = s["visual_summary"] + " " + s["event"] + " " + s["location"]

            # 1. 人物精确匹配 (核心权重)
            chars = set(s["characters"])
            if target_chars:
                overlap = chars & target_chars
                if overlap:
                    score += len(overlap) * 15
                else:
                    score -= 10  # 惩罚不包含目标人物的场景

            # 2. 情绪匹配
            s_emo = s["emotional_tone"]
            for te in target_emotions:
                if te in s_emo:
                    score += 8

            # 3. 强度匹配
            if s["intensity"] >= min_intensity:
                score += (s["intensity"] - min_intensity + 1) * 3

            # 4. 景别匹配
            if target_shot and s["shot_size"] == target_shot:
                score += 6
            elif target_shot:
                # 近似景别也给部分分
                size_order = {"特写": 0, "近景": 1, "中景": 2, "全景": 3, "远景": 4}
                if s["shot_size"] in size_order and target_shot in size_order:
                    dist = abs(size_order[s["shot_size"]] - size_order[target_shot])
                    score += max(0, 6 - dist * 3)

            # 5. 地点提示匹配
            if location_hint and location_hint in s["location"]:
                score += 4

            # 6. 动作提示匹配
            if action_hint:
                acts_str = " ".join(s["actions"]) if isinstance(s["actions"], list) else str(s["actions"])
                if action_hint in acts_str:
                    score += 4

            # 7. VLM 视觉描述丰富度
            if len(s["visual_summary"]) > 30:
                score += 2

            scored.append((score, s))

    scored.sort(key=lambda x: -x[0])
    # 去重 ep + scene_id
    seen = set()
    results = []
    for score, s in scored:
        key = f"{s['ep']}_{s['scene_id']}"
        if key in seen: continue
        seen.add(key)
        results.append({**s, "match_score": score})
        if len(results) >= num: break
    return results


def director_agent(narration: str, segment_context: dict = None, cover: str = "", num_shots: int = 3) -> dict:
    """导演Agent — LLM叙事理解 → 分镜设计 → 结构化匹配 + 人物交叉校验"""
    if not narration or not narration.strip():
        return {"shots": []}

    # 加载缓存 + 角色统计
    _ = _load_vlm_cache()
    known = sorted(_char_counts.keys(), key=lambda c: -_char_counts[c])
    known_str = ", ".join(f"{c}({_char_counts[c]}场)" for c in known)

    # Step 1: LLM 导演推理 — 注入角色统计 + cover 上下文
    ctx_text = ""
    if cover:
        ctx_text += f"封面/标题: {cover}\n"
    if segment_context and segment_context.get("sentences"):
        ctx_text += "上下文解说:\n" + "\n".join(
            f"- {s}" for s in segment_context["sentences"]
        ) + "\n"
    ctx_text += f"\n角色出场统计（46集总计）: {known_str}"

    user_prompt = f"{ctx_text}\n当前解说词：{narration}\n\n请推断主角并设计分镜序列，输出JSON。"

    formatted_prompt = DIRECTOR_PROMPT.replace("{KNOWN_CHARS}", known_str)

    llm_result = call_deepseek_json(
        formatted_prompt, user_prompt,
        temperature=0.5, max_tokens=1200, timeout=30, label="director_agent",
    )

    if not llm_result.get("ok"):
        return {"shots": [], "fallback": True, "error": llm_result.get("error", "LLM失败")}

    data = llm_result["data"]
    shots_spec = data.get("shots", [])
    main_char = data.get("main_char", "")

    # Step 2: 人物交叉校验 — cover 中的人物是决定性线索
    cover_chars = [c for c in sorted(_char_counts.keys(), key=lambda x: -_char_counts[x])
                   if c in (cover or '')]
    if cover_chars:
        definitive = cover_chars[0]  # 封面人物 = 主角
        if main_char and main_char != definitive:
            print(f"[director] ⚠️ LLM推断 {main_char}, 但封面明确是 {definitive}, 修正")
        elif not main_char:
            print(f"[director] 📌 封面人物 {definitive} 确定为主角")
        main_char = definitive
        # 修正所有分镜的 characters
        for spec in shots_spec:
            chars = spec.get("characters", [])
            # 替换错误推断的人物
            spec["characters"] = [definitive if ch != definitive and ch in _char_counts else ch for ch in chars]
            if definitive not in spec["characters"]:
                spec["characters"] = [definitive] + spec["characters"][:1]

    # 校验 main_char 是否在已知角色中
    if main_char and main_char not in _char_counts:
        print(f"[director] ⚠️ 主角 {main_char} 不在已知角色中!")
        main_char = ""

    if not shots_spec:
        return {"shots": [], "fallback": True, "error": "LLM未返回有效分镜"}

    # Step 3: 逐镜结构化匹配 (无结果时放宽限制重试)
    result_shots = []
    for spec in shots_spec:
        candidates = _match_shot_query(spec, num=5)
        if not candidates:
            relaxed = {**spec, "shot_size": "", "location_hint": ""}
            candidates = _match_shot_query(relaxed, num=5)
        result_shots.append({
            "purpose": spec.get("purpose", ""),
            "query": spec,
            "candidates": [
                {
                    "ep": c["ep"],
                    "start": c["start"],
                    "end": c["end"],
                    "visual_summary": c["visual_summary"][:120],
                    "shot_size": c["shot_size"],
                    "emotional_tone": c["emotional_tone"],
                    "intensity": c["intensity"],
                    "location": c["location"],
                    "characters": c["characters"],
                    "match_score": c["match_score"],
                }
                for c in candidates
            ],
        })

    return {"shots": result_shots, "narration": narration, "main_char": main_char}


def storyboard_suggest(narration: str, segment_context: dict = None, cover: str = "", num: int = 3) -> dict:
    """分镜推荐 v4 — 导演Agent优先, 降级为v3分层匹配
    返回: {"suggestions": [...], "shots": [...]}  — shots 为结构化分镜序列"""
    if not narration or not narration.strip():
        return {"suggestions": [], "shots": []}

    # 尝试导演Agent
    shots = []
    try:
        result = director_agent(narration, segment_context, cover, num)
        if result.get("shots") and not result.get("fallback"):
            shots = result["shots"]
            # 转换为前端兼容文本格式
            suggestions = []
            for shot in result["shots"]:
                for c in shot["candidates"][:1]:
                    label = shot.get("purpose", "")
                    entry = f"镜头{len(suggestions)+1}：{label} | EP{c['ep']} [{c['start']:.0f}s-{c['end']:.0f}s] {c['visual_summary'][:80]}"
                    if c.get("shot_size"):
                        entry += f" [{c['shot_size']}]"
                    suggestions.append(entry)
                if len(suggestions) >= num: break
            if suggestions:
                return {"suggestions": suggestions[:num], "shots": shots, "main_char": result.get("main_char", "")}
    except Exception as e:
        print(f"[storyboard] 导演Agent失败, 降级v3: {e}")

    # 降级：原有v3分层匹配逻辑
    fallback = _fallback_storyboard_suggest(narration, segment_context, cover, num)
    return {"suggestions": fallback, "shots": shots, "main_char": ""}


def _fallback_storyboard_suggest(narration: str, segment_context: dict = None, cover: str = "", num: int = 3) -> list:
    """分镜推荐 v3 — 分层结构化匹配: scene_map人物过滤 + VLM描述语义评分 + ASR时间锚定"""
    if not narration or not narration.strip():
        return []

    import os, re
    from pathlib import Path

    KNOWN_CHARS = ['苏大强', '苏明哲', '苏明成', '苏明玉', '朱丽', '吴非', '小蔡', '老聂']
    sources_dir = PROJECT_DIR / "sources"

    # ── Step 1: 提取目标人物 ──
    context_text = (cover or '') + ' ' + narration
    if segment_context:
        context_text += ' ' + ' '.join(segment_context.get("sentences", []))
    target_chars = {name for name in KNOWN_CHARS if name in context_text}

    # ── Step 2: scene_map 人物过滤 ──
    matches = []
    for ep_dir in sources_dir.iterdir():
        if not ep_dir.is_dir() or not ep_dir.name.startswith("ep"):
            continue
        ep = int(ep_dir.name[2:])
        sm_file = ep_dir / "scene_map.json"
        # v3 优先, v2 fallback
        vlm_file = ep_dir / "vlm_seg_cache_v3.json"
        if not vlm_file.exists():
            vlm_file = ep_dir / "vlm_seg_cache_v2.json"
        if not sm_file.exists():
            continue
        try:
            sm = json.load(open(sm_file))
            vlm = json.load(open(vlm_file)) if vlm_file.exists() else {}
        except Exception:
            continue
        for i, seg in enumerate(sm):
            seg_chars = set(seg.get('characters', []))
            if target_chars and not (seg_chars & target_chars):
                continue
            vlm_entry = vlm.get(str(i), {})
            # v3: visual_summary | v2: description
            vlm_desc = vlm_entry.get('visual_summary', '') or vlm_entry.get('description', '') or seg.get('event', '')
            match = {
                'ep': ep, 'scene_id': i,
                'start': seg.get('time_range', [0, 0])[0],
                'end': seg.get('time_range', [0, 0])[1],
                'location': seg.get('location', ''),
                'chars': list(seg_chars),
                'event': seg.get('event', ''),
                'vlm_desc': vlm_desc,
            }
            # v3 结构化字段 (用于增强评分精度)
            if 'shot_size' in vlm_entry:
                match['shot_size'] = vlm_entry['shot_size']
            if 'composition' in vlm_entry:
                match['composition'] = vlm_entry['composition']
            if 'emotional_tone' in vlm_entry:
                match['emotional_tone'] = vlm_entry['emotional_tone']
            if 'intensity' in vlm_entry:
                match['intensity'] = vlm_entry['intensity']
            if 'lighting' in vlm_entry:
                match['lighting'] = vlm_entry['lighting']
            if 'actions' in vlm_entry:
                match['actions'] = vlm_entry['actions']
            matches.append(match)

    # ── Step 3: 语义评分 ──
    KW_MAP = {
        '愤怒_对峙': ['对峙','质问','愤怒','冲突','紧绷','剑拔弩张','激动','攥拳','瞪眼','怒视','愤懑','持刀','失控','闯入'],
        '压抑_低落': ['压抑','低落','落寞','沮丧','痛苦','绝望','憔悴','颓废','孤独','悲哀','无助','凄凉'],
        '温馨_期待': ['温馨','日常','微笑','平和','宁静','亲密','期待','温暖','商量','领证','试衣'],
        '谈判_智斗': ['谈判','说服','解释','陈述','协商','智退','冷静','假装','支持','房贷','月供','贷款'],
        '争执_冲突': ['争执','争吵','指责','斥责','拍桌','激动','争辩','反对','不同意','抗议'],
        '出走_决绝': ['离家','出走','卖房','行李','背影','孤独','决绝','陌生','流浪','街头','蜷缩'],
        '家庭_日常': ['电话','通知','商量','反思','讨论','对话','劝说','劝解'],
    }
    all_text = narration + ' ' + context_text

    # 计算解说词触发的情绪类别
    active_cats = {}
    for cat, kws in KW_MAP.items():
        hits = sum(1 for kw in kws if kw in all_text)
        if hits:
            active_cats[cat] = hits

    scored = []
    for m in matches:
        score = 0
        desc = m['vlm_desc'] + ' ' + m['event'] + ' ' + m['location']
        # 人物匹配 (核心权重, 不再必须)
        if target_chars and set(m['chars']) & target_chars:
            score += 15
        elif target_chars:
            score -= 5  # 弱惩罚, 但不排除
        # 情绪关键词匹配: 只在解说道触发的情绪类别中匹配
        for cat, hits in active_cats.items():
            for kw in KW_MAP[cat]:
                if kw in desc:
                    score += 1.5  # 提高评分精度
        # 从VLM描述中匹配所有情绪词 (即使解说词没有)
        for cat, kws in KW_MAP.items():
            score += sum(0.3 for kw in kws if kw in desc)  # 基础情绪分数
        # 地点锚定
        for loc_kw in ['办公室','客厅','餐厅','医院','派出所','机场','家中']:
            if loc_kw in all_text and loc_kw in m['location']:
                score += 2
        scored.append((score, m))
    scored.sort(key=lambda x: -x[0])

    # 取 top-20 候选, 保证多样性
    top20 = []
    seen = set()
    for score, m in scored:
        key = f"{m['ep']}_{m['scene_id']}"
        if key in seen: continue
        seen.add(key)
        top20.append((score, m))
        if len(top20) >= 20: break

    # ── Step 3.5: BGE 轻量重排 (仅对 top20 候选) ──
    if len(top20) > num:
        try:
            from handlers.search import _semantic_search
            bge_results = _semantic_search(narration, limit=50)
            # 建立 EP_start → BGE rank 映射
            bge_rank = {}
            for rank, r in enumerate(bge_results):
                key = f"{r.get('ep',0)}_{(r.get('start',0)//60)*60}"
                if key not in bge_rank:
                    bge_rank[key] = rank
            # 用 BGE rank 调整分数
            for idx, (score, m) in enumerate(top20):
                key = f"{m['ep']}_{(m['start']//60)*60}"
                bge_r = bge_rank.get(key, 999)
                if bge_r < 10:   score += 5
                elif bge_r < 20: score += 3
                elif bge_r < 30: score += 1
                top20[idx] = (score, m)
            top20.sort(key=lambda x: -x[0])
        except Exception:
            pass

    # ── Step 4: 去重 + ASR 时间精确定位 ──
    seen2 = set()
    results = []
    for score, m in top20:
        key = f"{m['ep']}_{m['scene_id']}"
        if key in seen2:
            continue
        seen2.add(key)

        # ASR 精确定位: 在场景段内找最优对话锚点
        asr_time = None
        asr_text = ""
        try:
            asr_file = sources_dir / f"ep{m['ep']}" / "asr_result.json"
            if asr_file.exists():
                asr_data = json.load(open(asr_file))
                # 在场景段的时间范围内找情绪相关的ASR段落
                best_asr = None
                for a in asr_data:
                    if m['start'] <= a['start'] <= m['end']:
                        kw_score = sum(1 for kws in KW_MAP.values() for kw in kws if kw in a.get('text',''))
                        if best_asr is None or kw_score > best_asr[0]:
                            best_asr = (kw_score, a)
                if best_asr and best_asr[0] > 0:
                    asr_time = best_asr[1]['start']
                    asr_text = best_asr[1]['text'][:80]
        except Exception:
            pass

        # 格式化输出
        desc = m['vlm_desc'] or f"{m['location']}。人物: {', '.join(m['chars'])}。{m['event']}"
        time_info = f" [{asr_time:.0f}s]" if asr_time else f" [{m['start']:.0f}s-{m['end']:.0f}s]"
        entry = f"EP{m['ep']}{time_info} {desc[:100]}"
        if asr_text:
            entry += f" | ASR: \"{asr_text}\""
        results.append(entry)
        if len(results) >= num * 2:
            break

    # ── Step 5: LLM 精排 (可选, 候选>num触发) ──
    if results and len(results) > num:
        from lib.llm import call_moonshot
        seg_ctx_str = ""
        if segment_context and segment_context.get("sentences"):
            seg_ctx_str = "上下文:\n" + "\n".join(
                f"句{i}: {s}" for i, s in enumerate(segment_context["sentences"])
            ) + "\n\n"
        candidates = "\n".join(f"[{i+1}] {t}" for i, t in enumerate(results[:8]))
        llm_result = call_moonshot(
            "你是视频剪辑分镜助手。根据解说词从候选镜头中挑选最匹配的3个。"
            "直接输出「镜头N：推荐描述」格式，每行一个。",
            f"解说词：{narration}\n{seg_ctx_str}候选镜头：\n{candidates}\n\n请选择最匹配的3个镜头：",
            temperature=0.5, max_tokens=600, timeout=30, label="storyboard",
        )
        if llm_result["ok"]:
            raw = llm_result["content"].strip()
            lines = []
            for line in raw.split("\n"):
                line = line.strip()
                if not line or len(line) < 10:
                    continue
                if re.match(r'^镜头\d+[：:]', line):
                    lines.append(line)
                elif re.match(r'^\d+[\.\、\s]', line):
                    line = re.sub(r'^\d+[\.\、\s]+', '', line)
                    lines.append(f"镜头{len(lines)+1}：{line}")
            if len(lines) >= 2:
                return lines[:num]
                return lines[:num]

    return results[:num]


# ── POST /script/analyze_transcript ──
def analyze_transcript(transcript: str) -> dict:
    """LLM 分析采访转写，标注金句+识别结构"""
    if not transcript.strip():
        return {"ok": False, "error": "请提供转写文本"}

    result = call_moonshot_json(
        "你是短视频口播剪辑策划助手。分析引导式采访转写，找到最有价值的内容。\n\n"
        "素材特征：引导式聊天中有两层——内容层(正式讲述，可入正片)和元讨论层(商量怎么讲/自我评价/重述尝试，不入正片)。主持人的短问句和肯定词也不入正片。\n\n"
        "标注每句：\n"
        "  speaker: guest/host\n"
        "  layer: content(正式讲述)/meta(元讨论)/guide(主持人引导)\n"
        "  importance: 1-5 (5=金句hook, 4=核心观点/数据, 3=细节, 2=过渡, 1=冗余。meta/guide类默认-2)\n"
        "  narrative_role: hook_tension(激将式)/hook_promise(价值承诺)/personal_reveal(个人揭示)/empathy(共情)/evidence(方法论)/bridge(过桥)/turn(反转)/proof(案例)/insight(洞见)\n"
        "  is_golden: 适合做hook或收尾的标题级金句\n\n"
        "识别：\n"
        "  hook_candidates: 可重复锚定2-4次的核心金句列表\n"
        "  opening_strategy: tension_first或promise_first\n"
        "  empathy_moment: 共情句(如'爱学习但别乱学')或null\n"
        "  exclusive_moment: 独家揭示句(如'从没对外分享过')或null\n\n"
        "输出严格JSON(无markdown代码块)",
        f"采访转写文本：\n{transcript}",
        temperature=0.3, max_tokens=8000, timeout=120, label="analyze_transcript",
    )

    if result["ok"]:
        return {"ok": True, **result["data"]}
    return {"ok": False, "error": result.get("error", "AI 返回格式异常"), "raw": result.get("raw", "")[:500]}


# ── POST /script/generate_from_outline ──
def generate_from_outline(topic: str, outline: list, transcript: str) -> dict:
    """根据主题和结构大纲生成 segments"""
    if not topic or not outline:
        return {"ok": False, "error": "请提供 topic 和 outline"}

    outline_desc = "\n".join(
        f"{i+1}. [{o.get('narrative_role', '?')}] {o.get('label', '')}"
        for i, o in enumerate(outline)
    )

    result = call_moonshot_json(
        "你是短视频口播剪辑的文案助手。根据剪辑师确定的主题和大纲，从采访转写中提取最合适的原话，生成 segments.json。\n\n"
        "规则：\n"
        "1. 每段 highlight_text 必须是转写中真实存在的原话（可做最小限度的去口头禅），不要自己编造\n"
        "2. 每段标注 source_start / source_end（从转写时间戳中取）\n"
        "3. 根据 narrative_role 选择合适的表达力度\n"
        "4. 每段 edit_type: 短句用trim, 多句合并用merge\n"
        "5. topic 标签用于分段组织\n\n"
        "输出严格JSON:\n"
        '{"segments":[{"seg_id":0,"highlight_text":"原话","source_start":63.0,"source_end":67.0,"topic":"开场hook","edit_type":"trim","narration_text":"","note":"为什么选这句"}]}',

        f"视频主题：{topic}\n\n结构大纲：\n{outline_desc}\n\n采访转写（带时间戳）：\n{transcript[:4000]}",
        temperature=0.4, max_tokens=4000, timeout=120, label="generate_from_outline",
    )

    if result["ok"]:
        return {"ok": True, "topic": topic, "segments": result["data"].get("segments", [])}
    return {"ok": False, "error": result.get("error", "AI 返回格式异常")}
