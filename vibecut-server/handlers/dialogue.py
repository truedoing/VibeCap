"""对话/台词/分镜 → dialouge_match, chat, storyboard_suggest, analyze_transcript, generate_from_outline"""

import json
import os
import re
import time

from config import project_name, project_type, PROJECT_DIR
from lib.llm import call_moonshot, call_moonshot_json
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
def storyboard_suggest(narration: str, segment_context: dict = None, cover: str = "", num: int = 3) -> list:
    """分镜推荐 v2.6 — scene_map + VLM 直接匹配 (不依赖BGE)"""
    if not narration or not narration.strip():
        return []

    seg_ctx_str = ""
    if segment_context:
        sents = segment_context.get("sentences", [])
        if sents:
            seg_ctx_str = "上下文解说词：\n" + "\n".join(
                f"句{i}：{s}" for i, s in enumerate(sents)
            ) + "\n\n"

    # ── Step 1: 从解说词中推断人物 ──
    KNOWN_CHARS = ['苏大强', '苏明哲', '苏明成', '苏明玉', '朱丽', '吴非', '小蔡', '老聂']
    target_chars = set()
    context_text = (cover or '') + ' ' + narration
    if segment_context:
        context_text += ' ' + ' '.join(segment_context.get("sentences", []))
    for name in KNOWN_CHARS:
        if name in context_text:
            target_chars.add(name)

    # ── Step 2: scene_map 匹配 — 找有目标人物的所有场景段 ──
    import os
    from pathlib import Path
    sources_dir = PROJECT_DIR / "sources"

    matches = []  # [(ep, seg_info, vlm_desc)]
    for ep_dir in sources_dir.iterdir():
        if not ep_dir.is_dir() or not ep_dir.name.startswith("ep"):
            continue
        ep = int(ep_dir.name[2:])
        sm_file = ep_dir / "scene_map.json"
        vlm_file = ep_dir / "vlm_seg_cache_v2.json"  # 优先VLM描述
        if not sm_file.exists():
            continue
        try:
            sm = json.load(open(sm_file))
            vlm = json.load(open(vlm_file)) if vlm_file.exists() else {}
            for i, seg in enumerate(sm):
                seg_chars = set(seg.get('characters', []))
                # 如果有目标人物且匹配, 或无目标人物(不限)
                if target_chars and not (seg_chars & target_chars):
                    continue
                # 获取VLM描述(如有)
                vlm_desc = vlm.get(str(i), {}).get('description', '') if vlm else ''
                if not vlm_desc:
                    vlm_desc = seg.get('event', '')
                matches.append({
                    'ep': ep,
                    'scene_id': i,
                    'start': seg.get('time_range', [0, 0])[0],
                    'end': seg.get('time_range', [0, 0])[1],
                    'location': seg.get('location', ''),
                    'chars': list(seg_chars),
                    'event': seg.get('event', ''),
                    'vlm_desc': vlm_desc,
                })
        except Exception:
            pass

    # ── Step 3: 关键词重排 — 从 VLM描述中匹配情绪/情境 ──
    # 从解说词和上下文中提取情绪关键词
    emotion_kw_map = {
        '愤怒_对峙': ['对峙', '质问', '愤怒', '冲突', '紧绷', '剑拔弩张', '激动', '攥拳', '瞪眼', '怒视', '愤懑'],
        '压抑_低落': ['压抑', '低落', '落寞', '沮丧', '痛苦', '绝望', '憔悴', '颓废'],
        '温馨_日常': ['温馨', '日常', '聊天', '微笑', '平和', '宁静', '亲密', '期待'],
        '谈判_说理': ['谈判', '谈判', '说服', '解释', '陈述', '讨论', '协商'],
        '冲突_争执': ['争执', '争吵', '吵架', '指责', '斥责', '激动', '拍桌'],
    }
    # 从解说词 extract emotion context
    all_text = narration + ' ' + context_text
    emotion_scores = {}
    for category, kws in emotion_kw_map.items():
        emotion_scores[category] = sum(1 for kw in kws if kw in all_text)

    # 对每个场景评分
    scored = []
    for m in matches:
        score = 0
        desc = (m['vlm_desc'] + ' ' + m['event'] + ' ' + m['location'])
        # 人物精确匹配
        if target_chars and set(m['chars']) & target_chars:
            score += 10
        # 情绪关键词匹配
        for cat, cat_score in emotion_scores.items():
            if cat_score > 0:
                for kw in emotion_kw_map[cat]:
                    if kw in desc:
                        score += 1
        # 地点匹配 (解说词中提到办公室/家/医院?)
        for loc_kw in ['办公室', '家中', '医院', '客厅', '餐厅']:
            if loc_kw in all_text and loc_kw in m['location']:
                score += 2

        if score > 0:
            scored.append((score, m))

    scored.sort(key=lambda x: -x[0])

    # ── Step 4: 格式化返回 ──
    # 去重: 同一 scene_id 只取最高分
    seen = set()
    top = []
    for score, m in scored:
        key = f"{m['ep']}_{m['scene_id']}"
        if key in seen:
            continue
        seen.add(key)
        # 格式化为 LLM 友好的描述
        if m['vlm_desc']:
            desc = m['vlm_desc'][:100]
        else:
            desc = f"{m['location']}。人物: {', '.join(m['chars'])}。{m['event']}"
        top.append(f"EP{m['ep']} {m['start']:.0f}s-{m['end']:.0f}s {desc}")
        if len(top) >= num * 2:  # 返回稍多的候选
            break

    # ── Step 5: LLM 精排 (可选) ──
    if top and len(top) > num:
        from lib.llm import call_moonshot
        candidates = "\n".join(f"[{i+1}] {t}" for i, t in enumerate(top[:8]))
        result = call_moonshot(
            "你是视频剪辑分镜助手。根据解说词，从候选镜头中挑选最匹配的3个。"
            "直接输出「镜头N：推荐描述」格式，每行一个。",
            f"解说词：{narration}\n{seg_ctx_str}候选镜头：\n{candidates}\n\n请选择最匹配的3个镜头：",
            temperature=0.5, max_tokens=600, timeout=30, label="storyboard",
        )
        if result["ok"]:
            lines = [l.strip() for l in result["content"].strip().split("\n")
                     if l.strip() and len(l.strip()) > 15 and re.match(r'^镜头\d+[：:]', l.strip())]
            if lines:
                return lines[:num]

    return top[:num]


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
