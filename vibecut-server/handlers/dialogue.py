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
    """两步生成分镜推荐：1) BGE搜索真实VLM镜头 2) LLM基于结果生成推荐"""
    if not narration or not narration.strip():
        return []

    from handlers.search import _semantic_search

    seg_ctx_str = ""
    cover_info = ""
    if cover and cover.strip():
        cover_info = f"封面标题/主角线索：{cover[:200]}\n\n"
    if segment_context:
        sents = segment_context.get("sentences", [])
        if sents:
            seg_ctx_str = "该句所在段落的所有解说词：\n" + "\n".join(
                f"句{i}：{s}" for i, s in enumerate(sents)
            ) + "\n\n"

    char_ctx = ""
    try:
        char_file = PROJECT_DIR / "characters.json"
        if char_file.exists():
            chars = json.load(open(char_file)).get("characters", {})
            parts = []
            for name, info in chars.items():
                aliases = "/".join(info.get("static_names", []))
                alt = "、".join(info.get("aliases", [])[:3])
                parts.append(f"{name}（{aliases}）" + (f" 也称：{alt}" if alt else ""))
            if parts:
                char_ctx = "已知角色：\n" + "\n".join(parts) + "\n\n"
    except Exception:
        pass

    # Step 1: BGE 语义搜索
    real_vlm_results = _semantic_search(narration, limit=8)
    vlm_samples = ""
    if real_vlm_results:
        samples = real_vlm_results[:8]
        vlm_samples = "以下是搜索到的真实VLM镜头描述（必须从这些镜头中挑选和引用）：\n"
        for i, r in enumerate(samples):
            ep = r.get("ep", "?")
            t = r.get("start", 0)
            desc = r.get("description", r.get("asr", ""))[:120]
            vlm_samples += f"[{i+1}] EP{ep} {t:.0f}s — {desc}\n"
        vlm_samples += "\n"

    # Step 2: LLM 生成推荐
    result = call_moonshot(
        "你是视频剪辑分镜推荐助手。你的任务是根据一句解说词，从下方提供的"
        "真实VLM镜头描述中挑选最匹配的几个，改写为自然的分镜推荐语。\n\n"
        "输出格式：每行一个，格式为「镜头N：推荐描述」\n\n"
        "核心规则：\n"
        "1. 【必须基于真实镜头】只能从下面提供的VLM镜头中挑选，不允许编造\n"
        "2. 【1-3个镜头】一句解说词通常对应1-3个镜头\n"
        "3. 【自然口语化】用剪辑师的语气改写VLM描述\n"
        "4. 【30-60字】推荐语简短有力，聚焦核心画面\n"
        "5. 【与解说词匹配】推荐的镜头画面必须能配合这句解说词使用\n"
        "6. 【人物准确】如果封面/上下文提到了角色名，优先推荐该角色的镜头",

        f"{cover_info}{char_ctx}{seg_ctx_str}{vlm_samples}解说词：{narration}\n\n请基于真实VLM镜头生成分镜推荐：",
        temperature=0.5, max_tokens=1200, timeout=30, label="storyboard",
    )

    if result["ok"]:
        lines = [l.strip() for l in result["content"].strip().split("\n")
                 if l.strip() and len(l.strip()) > 15 and re.match(r'^镜头\d+[：:]', l.strip())]
        return lines[:num]
    return []


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
