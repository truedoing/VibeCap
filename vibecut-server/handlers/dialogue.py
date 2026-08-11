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
# v8: 导演Agent — 叙事节拍拆解 + 主辅镜头(PRIMARY+SECONDARY)

# 导演Agent prompt v8
DIRECTOR_PROMPT = """你是电视剧《都挺好》的分镜导演。根据解说词策划一个分镜序列，用原剧场景来匹配。

人物推断规则（按优先级）：
1. 封面/标题中出现的角色名 = 主角，权重最高
2. 上下文解说词中出现的角色名 = 辅助信息
3. 解说词本身描述的行为特征 → 对照角色出场统计推断
4. 角色列表 + 出场次数: {KNOWN_CHARS}
5. 推断的主角必须填写在 main_char 字段中

可选景别：特写、近景、中景、全景、远景。

{ANCHOR_INFO}

★★ 任务 —— 分三步 ★★

第1步：叙事节拍拆解
  节拍类型:
    action    — 动作/事件（如"拍桌""打架"）→ 必须有原剧画面
    emotion   — 情绪/表情（如"愤怒""落寞"）→ 需要表情画面
    context   — 评述/解释 → 不生成分镜，仅留白
    punchline — 金句/主题句 → 需情绪强烈画面
    argument  — 论证/主题句（如"不光X也Y""表面X实际Y""没X没Y就没Z"）
                解说词在论证一个观点，必须拆解为 ≥2 个 PRIMARY shot
                每个 PRIMARY 对应论证的一个面（两面/多面对比）

  ★ 论证式拆解特别规则:
    - 识别标记: "不光X也Y" "没X没Y" "表面X实际Y" "不是X而是Y"
    - beat type 设为 argument，一个 argument beat 拆 ≥2 个 PRIMARY shot
    - shot1 对应论证前半（如"窝里横"→找家庭内部冲突场景）
    - shot2 对应论证后半（如"在外狂"→找外部对峙场景）
    - 可叠加 CONTRAST: 家庭内 vs 外部 对比并置

  论证拆解示例:
    "他不光窝里横，在外边他也照样狂"
      → beat1 type=argument, text="论证：窝里横+在外狂"
      → shot1 PRIMARY: purpose="在家发狠", location_hint="苏家场景",
           emotional_tone=["愤怒","凶横"], match_type="character"
      → shot2 PRIMARY: purpose="对外嚣张", location_hint="外部",
           emotional_tone=["冲突","狂妄"], match_type="character"
      → 可加 CONTRAST: 家内凶横 vs 外部嚣张 对比并置

第2步：导演手法运用 (v8.1)
  根据解说词的叙事特点，在适当位置运用以下导演手法。这些手法让画面层次更丰富。
  不要为了用而用——只在解说结构自然需要时才使用，一个节拍至多一个手法。

  ★ 六种导演手法:

  1. REACTION 反应镜头 — 人物情绪/反应特写（面部、眼神、手部细节）
     用途: 外化内心活动，让观众"看到"心理状态
     时机: 内心戏、"表面X实际Y"的反差时刻
     例: "表面认真，实际只记住八个字" → PRIMARY电话中景 + REACTION眼神失焦

  2. FLASHBACK 闪回 — 插入过去的关键画面（1-2秒即可）
     用途: 将"过去事件"与"当前情绪"在时间线上并置
     时机: 解说明确提到过去事件（如"母亲去世""上次打架"）
     特点: prefer_episodes可跳出当前标的剧集
     例: "母亲去世后位置无法取代" → FLASHBACK闪回母亲遗像

  3. CONTRAST 对比并置 — 同时呈现对立状态的两组画面
     用途: 制造戏剧张力，呈现"表面vs内心"或"一方vs另一方"
     时机: 解说描述矛盾关系、强烈反差
     特点: characters必须包含对比双方人物
     例: "苏大强谈婚论嫁，苏明成视为背叛" → CONTRAST苏大强高兴 vs 苏明成阴沉

  4. CUTAWAY 空镜留白 — 环境/物品/氛围画面（不需要人物）
     用途: 给观众情绪沉淀的呼吸空间
     时机: 解说进入评述/升华段落，情感需要沉淀
     特点: 不进行画面匹配，标注建议留给剪辑师（如"空椅子""母亲遗像""窗外雨景"）

  5. ARC 情绪递进 — 同一情绪由弱到强跨多个节拍递进
     用途: 让情绪爆发有铺垫，而非突兀出现
     实现: 相邻PRIMARY的intensity_min从低到高自然递进
     例: "表面平静"(int1) → "眼神变冷"(int3) → "拍桌怒吼"(int5)

  6. CROSS 交叉剪辑 — 提示两个场景可交替使用
     用途: "同一时刻，不同空间"制造紧张感和信息密度
     时机: 解说同时描述两个平行事件（如"苏明成打电话时，苏大强正在和保姆谈笑"）
     实现: 在note字段标注"CROSS-可交叉剪辑"，提示剪辑师不需要单独生成镜头

输出 JSON（严格格式）：
{{
  "main_char": "主角名（从角色列表选）",
  "beats": [
    {{"index": 0, "type": "context", "text": "节拍描述(≤15字)", "has_visual": false}},
    {{"index": 1, "type": "action",  "text": "节拍描述(≤15字)", "has_visual": true, "prefer_ep": 41}},
    ...
  ],
  "shots": [
    {{
      "beat_index": 1,
      "director_technique": "REACTION",
      "technique_hint": "给剪辑师的操作建议(≤30字)",
      "primary": {{
        "purpose": "核心画面描述(≤12字)",
        "priority": "KEY",
        "characters": ["人物名"],
        "shot_size": "景别",
        "emotional_tone": ["情绪标签"],
        "intensity_min": 强度1-5,
        "location_hint": "场景提示",
        "action_hint": "动作提示",
        "prefer_episodes": [推荐剧集],
        "match_type": "narrative 或 character"
      }},
      "secondary": [
        {{
          "purpose": "辅助画面描述(≤12字)",
          "shot_role": "REACTION or FLASHBACK or CONTRAST",
          "characters": ["人物名"],
          "shot_size": "特写",
          "emotional_tone": ["情绪标签"],
          "intensity_min": 强度1-5,
          "action_hint": "表情/动作提示",
          "prefer_episodes": [推荐剧集],
          "match_type": "character"
        }}
      ]
    }}
  ]
}}

规则（精简）：
- 人物必须从角色列表中选择；characters填该镜头需出现的人物
- emotional_tone从常见情绪词中选择；intensity_min 1=平静 5=激烈
- match_type: narrative=叙事性, character=表现性
- context节拍只记录beats不生成shots
- CONTRAST的characters必须包含对比双方
- FLASHBACK的prefer_episodes可跳出当前标的剧集
- CUTAWAY不匹配画面，留空给剪辑师
- CROSS在note中标注，不生成单独镜头

"""

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


def _match_shot_query(query: dict, num: int = 5, used_scene_keys: set = None,
                      main_char: str = "", focus_eps: set = None):
    """给定一个分镜查询，从 v3 缓存中匹配最优场景段

    used_scene_keys: 已在前置分镜中使用的场景键集合，用于跨镜去重
    main_char: 推断的主角名，用于验证 visual_summary 是否真正描述该人物
    focus_eps: 锚定的剧集号集合，这些剧集的场景优先匹配
        v8.4: focus_eps 支持多层权重 — 可以是 set(int) 或 list of (weight, set(int))
    """
    cache = _load_vlm_cache()
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

    # ── v8.5: scene_map mood 高冲突词 / VLM 低能情绪词 ──
    HIGH_CONFLICT_MOODS = {'激烈', '愤怒', '争执', '冲突', '激动', '绝望', '对峙',
                           '质问', '对峙', '愤怒无奈', '紧张争执', '冲突激烈'}
    LOW_ENERGY_VLM_TONES = {'温和', '平静', '轻松', '日常', '关切', '温馨', '柔和', '自然',
                            '温和关切', '平静正式', '轻松日常'}

    for ep, ep_data in cache.items():
        for idx, s in ep_data.items():
            score = 0
            scene_key = f"{s['ep']}_{s['scene_id']}"
            desc = s["visual_summary"] + " " + s["event"] + " " + s["location"]

            # 0. 跨镜去重
            if scene_key in used:
                score -= 30

            # 0.5 剧集锚定: 三层权重
            # L1: 承上启下(上下文直接关联的原剧) = +15, 强约束
            # L2: 标的剧集(episode_marker) = +5, 中等约束
            # L3: 扩展邻近集(±2) = +2, 弱约束
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
            # 当 scene_map 记录了高冲突 mood，但 VLM 输出低能情绪时，
            # 很可能是 VLM 采样帧未捕捉到冲突画面（选帧偏差）。
            # 给予补偿分，让 scene_map 的结构化先验修正 VLM 数据误差。
            #
            # v8.5.1: 补偿仅在 location 可关联时生效
            # 防止"地点无关但 mood 补偿"的噪声场景超过地点正确的内容场景
            effective_intensity = s["intensity"]  # 用于强度匹配的有效强度
            scene_mood = s.get("mood", "")
            vlm_tone = str(s.get("emotional_tone", ""))
            vlm_intensity = s.get("intensity", 3)

            # 检测冲突：scene_map 高冲突 + VLM 低能情绪
            mood_high = any(m in scene_mood for m in HIGH_CONFLICT_MOODS)
            tone_low = any(t in vlm_tone for t in LOW_ENERGY_VLM_TONES) or vlm_intensity <= 2

            # 先算 location 是否匹配（在 mood 补偿前，用作补偿门槛）
            loc_relevant = False
            if location_hint:
                loc = s.get("location", "")
                if location_hint in loc or loc in location_hint:
                    loc_relevant = True
                else:
                    stop_suffixes = ['客厅','餐厅','卧室','厨房','走廊','门口','会议室','办公室']
                    hc, lc = location_hint, loc
                    for sfx in stop_suffixes:
                        hc = hc[:-len(sfx)] if hc.endswith(sfx) else hc
                        lc = lc[:-len(sfx)] if lc.endswith(sfx) else lc
                    if hc and lc and (hc in lc or lc in hc):
                        loc_relevant = True
            else:
                loc_relevant = True  # 没有 location 约束时不限制

            if mood_high and tone_low and loc_relevant:
                # 情绪穿透补偿：相信 scene_map 的情绪标注
                score += 8
                # 强度补偿：使用合理的最低强度值
                effective_intensity = max(vlm_intensity, 3)
                # 如果 scene_map mood 明确包含目标情绪词，额外加分
                for te in target_emotions:
                    if te in scene_mood:
                        score += 5  # 半额情绪命中分 (vs 正常的 +8)

            # 1.6 情绪匹配 (使用有效强度)
            for emo in target_emotions:
                if emo in desc:
                    score += 8
            # 强度匹配
            if effective_intensity >= min_intensity:
                score += max(0, (effective_intensity - min_intensity + 1)) * 3
            # 景别匹配 — v8.5.1: 放宽距离补偿
            # 1级距离(近景↔中景)补偿从 +3-dist 提升到 +5，减少"精确但不相关内容"
            # 因 shot_size 精确匹配而击败"地点正确"场景的情况
            if target_shot and s.get("shot_size", "") == target_shot:
                score += 6
            elif target_shot and s.get("shot_size", ""):
                # 距离补偿: 近景↔特写 距离=1, 近景↔全景 距离=2
                shot_order = ["特写", "近景", "中景", "全景", "远景"]
                try:
                    ts_i = shot_order.index(target_shot)
                    ss_i = shot_order.index(s.get("shot_size", ""))
                    dist = abs(ts_i - ss_i)
                    score += max(0, 5 - dist)  # v8.5.1: 更宽松的补偿
                except ValueError:
                    pass
            # 地点匹配 — v8.5.1: 双向子串匹配 + 同义词
            # "苏大强家客厅" in "苏大强家" → False (子串反了)
            # 改为: hint 的任意非停用词片段出现在 location 中即命中
            if location_hint:
                loc_lower = s.get("location", "")
                hint_lower = location_hint
                # 精确子串
                if hint_lower in loc_lower or loc_lower in hint_lower:
                    score += 4
                else:
                    # 去掉 "客厅""办公室""餐厅" 等后缀后模糊匹配
                    stop_suffixes = ['客厅','餐厅','卧室','厨房','走廊','门口','会议室','办公室']
                    hint_core = hint_lower
                    loc_core = loc_lower
                    for sfx in stop_suffixes:
                        if hint_core.endswith(sfx):
                            hint_core = hint_core[:-len(sfx)]
                        if loc_core.endswith(sfx):
                            loc_core = loc_core[:-len(sfx)]
                    if hint_core and loc_core and (hint_core in loc_core or loc_core in hint_core):
                        score += 3  # 半额命中
            # 动作匹配 — v8.5.1: 关键词子串匹配
            if action_hint:
                # 拆为 2-3 字关键词，命中半数即加分
                action_kws = [action_hint[i:i+2] for i in range(0, len(action_hint), 2) if len(action_hint[i:i+2]) >= 2]
                hits = sum(1 for kw in action_kws if kw in desc)
                if hits >= len(action_kws) * 0.5:
                    score += 4
                elif hits >= 2:
                    score += 2  # 部分命中

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


def director_agent(narration: str, segment_context: dict = None, cover: str = "",
                   num_shots: int = 3, focus_episodes: list = []) -> dict:
    """导演Agent v8 — 叙事节拍拆解 + 主辅镜头(PRIMARY+SECONDARY)

    focus_episodes: segments.json的episode_marker提取的解说标的剧集
    """
    if not narration or not narration.strip():
        return {"shots": []}

    _ = _load_vlm_cache()
    known = sorted(_char_counts.keys(), key=lambda c: -_char_counts[c])
    known_str = ", ".join(f"{c}({_char_counts[c]}场)" for c in known)

    # v8.4: 三层剧集权重 (保持原始上下文顺序, 不排序!)
    focus_eps_list = list(focus_episodes) if focus_episodes else []
    focus_eps = set(focus_eps_list)
    bridge_eps = set()
    if focus_eps_list:
        # 前两个 = 承上启下(前后段直接关联的原剧)
        if len(focus_eps_list) >= 2:
            bridge_eps = {focus_eps_list[0], focus_eps_list[1]}
            print(f"[director] 🎯 承上启下: EP{focus_eps_list[0]}↔EP{focus_eps_list[1]} (权重+15)")
        print(f"[director]   标的集: {focus_eps_list} (权重+5)")
        # 加载剧情概要
        synopsis_text = ""
        for ep in focus_eps_list:
            syn_file = PROJECT_DIR / "sources" / f"ep{ep}" / "ep_synopsis.json"
            if syn_file.exists():
                try:
                    syn = json.load(open(syn_file)).get("synopsis", "")
                    if syn:
                        synopsis_text += f"\n★ EP{ep} 剧情概要: {syn}\n"
                        print(f"[director]   📖 EP{ep} 概要 ({len(syn)}字)")
                except Exception:
                    pass

    ctx_text = ""
    if cover:
        ctx_text += f"封面/标题: {cover}\n"
    if focus_eps:
        ctx_text += f"★ 解说标的剧集: {focus_eps_list}\n"
        if len(focus_eps_list) >= 2:
            ctx_text += (f"  ★★★ 短解说词桥接规则 (必须遵守) ★★★\n"
                        f"    这段解说词桥接上文原剧EP{focus_eps_list[0]}和下文原剧EP{focus_eps_list[1]}。\n"
                        f"    镜1 prefer_episodes={focus_eps_list[0]}(上文场景), 镜2 prefer_episodes={focus_eps_list[1]}(下文场景)。\n"
                        f"    不允许把两个分镜都锚定到同一个集!\n")
    if synopsis_text:
        ctx_text += f"\n★★ 标的剧集剧情概要 ★★{synopsis_text}\n"
    if segment_context and segment_context.get("sentences"):
        ctx_text += "上下文解说:\n" + "\n".join(f"- {s}" for s in segment_context["sentences"]) + "\n"
    ctx_text += f"\n角色出场统计（46集总计）: {known_str}"

    user_prompt = f"{ctx_text}\n当前解说词：{narration}\n\n请推断主角并设计分镜序列，输出JSON。"

    anchor_info = ""
    if focus_eps:
        anchor_info = (f"★ 解说标的剧集: {', '.join(f'EP{ep}' for ep in sorted(focus_eps))}\n"
                       f"  优先从这些剧集中选画面。仅情绪/表情镜头可灵活选择。")
    formatted_prompt = DIRECTOR_PROMPT.replace("{KNOWN_CHARS}", known_str)
    formatted_prompt = formatted_prompt.replace("{ANCHOR_INFO}", anchor_info if anchor_info else
                                                 "未获取到锚定信息，从全剧集中搜索匹配。")
    if not anchor_info:
        formatted_prompt = formatted_prompt.replace("{ANCHOR_INFO}\n", "")

    llm_result = call_deepseek_json(
        formatted_prompt, user_prompt,
        temperature=0.5, max_tokens=2000, timeout=30, label="director_agent",
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
        # v8: 修正 primary + secondary 的 characters
        def _fix_chars(spec):
            chars = spec.get("characters", [])
            spec["characters"] = [definitive if ch != definitive and ch in _char_counts else ch for ch in chars]
            if definitive not in spec["characters"]:
                spec["characters"] = [definitive] + spec["characters"][:1]

        for shot_entry in shots_spec:
            if "primary" in shot_entry:
                _fix_chars(shot_entry["primary"])
                for sec in shot_entry.get("secondary", []):
                    _fix_chars(sec)

    if main_char and main_char not in _char_counts:
        print(f"[director] ⚠️ 主角 {main_char} 不在已知角色中!")
        main_char = ""

    if not shots_spec:
        return {"shots": [], "fallback": True, "error": "LLM未返回有效分镜"}

    # ── v8.2: Agent推理过程 ──
    reasoning = {
        "anchor": {},
        "beats_summary": {},
        "shots_matching": []
    }

    # 锚定分析
    if focus_eps:
        eps_with_synopsis = []
        for ep in sorted(focus_eps):
            syn_file = PROJECT_DIR / "sources" / f"ep{ep}" / "ep_synopsis.json"
            has_syn = "✅" if syn_file.exists() else "❌"
            eps_with_synopsis.append(f"EP{ep}(synopsis={has_syn})")
        reasoning["anchor"] = {
            "source": "segments.json episode_marker",
            "focus_episodes": sorted(focus_eps),
            "synopsis_loaded": eps_with_synopsis,
            "method": "直接读取segments的episode_marker字段，不需要ASR关键词锚定",
            "constraint": f"PRIMARY必须在标的剧集内匹配, SECONDARY/emotion可扩展到±3集"
        }
    else:
        reasoning["anchor"] = {"source": "无episode_marker", "focus_episodes": [], "method": "全剧集搜索"}

    # 提取beats (从LLM输出的data中)
    beats = data.get("beats", [])

    # 节拍分析
    for b in beats:
        b["has_visual"] = b.get("has_visual", b.get("type") != "context")
    reasoning["beats_summary"] = {
        "total": len(beats),
        "visual": sum(1 for b in beats if b.get("has_visual")),
        "context_skip": sum(1 for b in beats if b.get("type") == "context"),
        "beats": [{"index": b.get("index", i), "type": b.get("type", "?"),
                    "text": b.get("text", ""), "has_visual": b.get("has_visual", True)}
                   for i, b in enumerate(beats)]
    }

    # 匹配细节 (收集完成后填充)

    # Step 3: v8 主辅镜头匹配
    def _make_candidates(clist):
        if not clist: return []
        return [{"ep": c["ep"], "start": c["start"], "end": c["end"],
                 "visual_summary": c["visual_summary"][:120],
                 "shot_size": c["shot_size"], "emotional_tone": c["emotional_tone"],
                 "intensity": c["intensity"], "location": c["location"],
                 "characters": c["characters"], "match_score": c["match_score"]}
                for c in clist]

    # v8.2: Agent推理过程 — 记录每个决策步骤
    reasoning = {
        "anchor": {},
        "beats": [],
        "shots_matching": [],
        "statistics": {}
    }

    # 锚定分析
    if focus_eps:
        eps_detail = []
        for ep in sorted(focus_eps):
            syn_file = PROJECT_DIR / "sources" / f"ep{ep}" / "ep_synopsis.json"
            eps_detail.append(f"EP{ep}(synopsis={'已加载' if syn_file.exists() else '未找到'})")
        reasoning["anchor"] = {
            "source": "segments.json episode_marker",
            "focus_episodes": sorted(focus_eps),
            "bridge_eps": sorted(bridge_eps) if bridge_eps else [],
            "synopsis_status": eps_detail,
            "method": "三层权重: 承上启下EP(+15) > 标的集(+5) > 邻近集(+2) > 全剧集(0)",
            "constraint": "PRIMARY必须在标的剧集内, SECONDARY/emotion可扩展到邻近集"
        }
    else:
        reasoning["anchor"] = {"source": "episode_marker缺失", "focus_episodes": [], "method": "全剧46集搜索"}

    # 节拍分析
    for i, b in enumerate(beats):
        b["has_visual"] = b.get("has_visual", b.get("type") != "context")
    reasoning["beats"] = [{
        "index": b.get("index", i), "type": b.get("type", "?"),
        "text": b.get("text", ""), "has_visual": b.get("has_visual", True)
    } for i, b in enumerate(beats)]
    n_visual = sum(1 for b in beats if b.get("has_visual"))
    n_context = sum(1 for b in beats if b.get("type") == "context")
    print(f"[director] 📐 叙事分析: {len(beats)}个节拍 ({n_visual}画面化, {n_context}解说留白) → {len(shots_spec)}组主镜")

    result_shots = []
    used_scene_keys = set()
    for i, shot_entry in enumerate(shots_spec):
        primary_spec = shot_entry.get("primary", shot_entry)
        secondary_specs = shot_entry.get("secondary", [])
        beat_idx = shot_entry.get("beat_index", i)
        technique = shot_entry.get("director_technique", "")

        # ── PRIMARY 匹配 ──
        pri_focus = set(focus_eps) if focus_eps else set()
        pri_prefer = primary_spec.get("prefer_episodes", [])

        # v8.4: 三层权重
        # L1=承上启下(bridge_eps): 前两个标的剧集, 权重+15
        # L2=标的集(focus_eps): 所有权重+5
        # L3=邻近扩展(±3): 权重+2
        bridge_layer = [(15, bridge_eps)] if bridge_eps else []
        focus_layer = [(5, pri_focus)] if pri_focus else []
        neighbor_eps = set()
        if pri_focus:
            for ep in list(pri_focus):
                for d in [-3, -2, -1, 1, 2, 3]:
                    n = ep + d
                    if 1 <= n <= 46: neighbor_eps.add(n)
        neighbor_layer = [(2, neighbor_eps)] if neighbor_eps else []
        layered_focus = bridge_layer + focus_layer + neighbor_layer

        pri_cands = _match_shot_query(primary_spec, num=5, used_scene_keys=used_scene_keys,
                                       main_char=main_char, focus_eps=layered_focus if layered_focus else None)
        relaxed_used = False
        if not pri_cands:
            relaxed = {**primary_spec, "shot_size": "", "location_hint": ""}
            pri_cands = _match_shot_query(relaxed, num=5, used_scene_keys=used_scene_keys,
                                           main_char=main_char, focus_eps=layered_focus if layered_focus else None)
            relaxed_used = True

        # v8.3: PRIMARY低分保护 — 标的集内最高分<35时, 自动扩展到邻近集(±5)
        #       标的episode_marker可能漏标了该解说的关键场景, 或者VLM数据质量问题
        if pri_cands and pri_cands[0].get("match_score", 0) < 35 and pri_focus:
            expanded_focus = set(pri_focus)
            for ep in list(pri_focus):
                for d in [-5, -4, -3, -2, -1, 1, 2, 3, 4, 5]:
                    n = ep + d
                    if 1 <= n <= 46:
                        expanded_focus.add(n)
            expanded_cands = _match_shot_query(primary_spec, num=5, used_scene_keys=used_scene_keys,
                                                main_char=main_char, focus_eps=expanded_focus)
            if expanded_cands and expanded_cands[0].get("match_score", 0) > pri_cands[0].get("match_score", 0) + 5:
                print(f"[director]   ⚡ 标的内低分(score={pri_cands[0]['match_score']})→扩展±5集, "
                      f"EP{expanded_cands[0]['ep']} score={expanded_cands[0]['match_score']}")
                pri_cands = expanded_cands
                relaxed_used = True  # 标记为扩展搜索

        global_fallback = False
        if not pri_cands:
            pri_cands = _match_shot_query(primary_spec, num=5, used_scene_keys=used_scene_keys,
                                           main_char=main_char)
            global_fallback = True

        if pri_cands and primary_spec.get("priority", "KEY") == "KEY":
            used_scene_keys.add(f"{pri_cands[0]['ep']}_{pri_cands[0]['scene_id']}")

        purp = primary_spec.get("purpose", "")[:15]
        print(f"[director] 拍{i+1} PRIMARY ({purp}) → "
              f"EP{pri_cands[0]['ep']} [{pri_cands[0]['start']:.0f}s] "
              f"(score={pri_cands[0]['match_score']})" if pri_cands else f"[director] 拍{i+1} PRIMARY ({purp}) → 无匹配")

        # v8.2: 记录PRIMARY匹配推理
        pri_reasoning = {
            "beat_index": beat_idx,
            "primary_purpose": primary_spec.get("purpose", ""),
            "director_technique": technique,
            "query": {
                "characters": primary_spec.get("characters", []),
                "shot_size": primary_spec.get("shot_size", ""),
                "emotional_tone": primary_spec.get("emotional_tone", []),
                "intensity_min": primary_spec.get("intensity_min", 1),
                "location_hint": primary_spec.get("location_hint", ""),
                "action_hint": primary_spec.get("action_hint", ""),
                "match_type": primary_spec.get("match_type", ""),
            },
            "focus_eps": sorted(pri_focus) if pri_focus else [],
            "search_strategy": ("全局回退" if global_fallback else ("放宽景别+场景" if relaxed_used else "标的集约束搜索")),
            "top3_candidates": [
                {"rank": j+1, "ep": c["ep"], "start": c["start"], "end": c["end"],
                 "score": c["match_score"], "visual": c["visual_summary"][:80],
                 "why": f"人物={c['characters']}, 情绪={c['emotional_tone']}, 强度={c['intensity']}, 地点={c['location']}"}
                for j, c in enumerate((pri_cands or [])[:3])
            ],
            "secondary_reasoning": [],
        }

        # ── SECONDARY 匹配 ──
        sec_results = []
        for sec_spec in secondary_specs:
            sec_role = sec_spec.get("shot_role", "REACTION")
            sec_prefer = sec_spec.get("prefer_episodes", [])

            if sec_role == "FLASHBACK" and sec_prefer:
                sec_focus = set(sec_prefer)
            elif sec_role == "CONTRAST":
                sec_focus = None
            else:
                sec_focus = set(pri_focus) if pri_focus else None
                if sec_focus:
                    for ep in list(sec_focus):
                        for d in [-3, -2, -1, 1, 2, 3]:
                            n = ep + d
                            if 1 <= n <= 46: sec_focus.add(n)

            sec_cands = _match_shot_query(sec_spec, num=3, used_scene_keys=set(),
                                           main_char=main_char if sec_role != "CONTRAST" else "",
                                           focus_eps=sec_focus)
            if sec_cands:
                print(f"[director]   +{sec_role} ({sec_spec.get('purpose','')[:12]}) → EP{sec_cands[0]['ep']} "
                      f"(score={sec_cands[0]['match_score']})")

            sec_reasoning = {
                "role": sec_role,
                "purpose": sec_spec.get("purpose", ""),
                "search_scope": (f"标的集±3集" if sec_focus else ("指定集EP{sorted(sec_prefer)}" if sec_prefer else "全剧集")),
                "top_candidate": {} if not sec_cands else {
                    "ep": sec_cands[0]["ep"], "score": sec_cands[0]["match_score"],
                    "visual": sec_cands[0]["visual_summary"][:80]
                }
            }
            pri_reasoning["secondary_reasoning"].append(sec_reasoning)

            sec_results.append({
                "purpose": sec_spec.get("purpose", ""),
                "shot_role": sec_role,
                "query": sec_spec,
                "candidates": _make_candidates(sec_cands),
            })

        reasoning["shots_matching"].append(pri_reasoning)

        result_shots.append({
            "beat_index": beat_idx,
            "director_technique": technique,
            "technique_hint": shot_entry.get("technique_hint", ""),
            "primary": {
                "purpose": primary_spec.get("purpose", ""),
                "query": primary_spec,
                "candidates": _make_candidates(pri_cands),
            },
            "secondary": sec_results,
        })

    reasoning["statistics"] = {
        "total_beats": len(beats),
        "visual_beats": n_visual,
        "context_beats": n_context,
        "primary_shots": len(result_shots),
        "secondary_shots": sum(len(s.get("secondary", [])) for s in result_shots),
        "anchor_hit_rate": f"{sum(1 for s in result_shots if s['primary'].get('candidates') and any(c['ep'] in focus_eps for c in s['primary']['candidates']))}/{len(result_shots)}" if focus_eps else "N/A"
    }

    return {"shots": result_shots, "narration": narration, "main_char": main_char,
            "beats": beats, "focus_eps": sorted(focus_eps), "reasoning": reasoning}


def storyboard_suggest(narration: str, segment_context: dict = None, cover: str = "",
                       num: int = 3, prev_highlight: str = "", next_highlight: str = "",
                       focus_episodes: list = []) -> dict:
    """分镜推荐 v8 — PRIMARY+SECONDARY主辅镜头
    返回: {"suggestions": [...], "shots": [...]}
    """
    if not narration or not narration.strip():
        return {"suggestions": [], "shots": []}

    shots = []
    try:
        result = director_agent(narration, segment_context, cover, num,
                                focus_episodes=focus_episodes)
        if result.get("shots") and not result.get("fallback"):
            shots = result["shots"]
            suggestions = []
            for shot_entry in result["shots"]:
                pri = shot_entry.get("primary", {})
                for c in pri.get("candidates", [])[:1]:
                    label = pri.get("purpose", "")
                    suggestions.append(
                        f"[PRIMARY] {label} | EP{c['ep']} [{c['start']:.0f}s-{c['end']:.0f}s] "
                        f"{c['visual_summary'][:80]}" + (f" [{c['shot_size']}]" if c.get("shot_size") else ""))
                for sec in shot_entry.get("secondary", []):
                    for c in sec.get("candidates", [])[:1]:
                        role = sec.get("shot_role", "SEC")
                        suggestions.append(
                            f"  +{role} {sec.get('purpose','')} | EP{c['ep']} [{c['start']:.0f}s] "
                            f"{c['visual_summary'][:60]}")
            if suggestions:
                return {"suggestions": suggestions, "shots": shots,
                        "main_char": result.get("main_char", ""),
                        "beats": result.get("beats", []),
                        "focus_eps": result.get("focus_eps", []),
                        "reasoning": result.get("reasoning", {})}
    except Exception as e:
        print(f"[storyboard] 导演Agent失败, 降级v3: {e}")

    fallback = _fallback_storyboard_suggest(narration, segment_context, cover, num)
    return {"suggestions": fallback, "shots": shots, "main_char": "", "focus_eps": [], "reasoning": {}}


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
