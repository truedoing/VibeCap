"""
编剧 Agent 系统 — 电视剧解说脚本生成

四个独立 Agent 角色，通过编排器 run_drama_pipeline() 协调。

Agent 协议:
  输入: 结构化数据 (story_map / chapter_plan / scene_data)
  输出: {"ok": True, "result": {...}} | {"ok": False, "error": "..."}

对标 script_agents.py 的 Agent 模式，但：
  - 口播 Agent 是"选句"（从 ASR 挑原话）
  - 编剧 Agent 是"创作"（写旁白 + 生成 scene_query）
"""

import json
import re
import time
from collections import Counter
from pathlib import Path

from lib.llm import call_deepseek_json, call_deepseek
from lib.vlm_cache import KNOWN_CHARACTERS, get_char_counts
from lib.synopsis import load_synopsis, to_text

# ── Prompt 模板 ──
from handlers.prompts.script_drama import (
    STORY_MASTER_PROMPT,
    THESIS_AGENT_PROMPT,
    NARRATIVE_PLANNER_PROMPT,
    SCRIPT_WRITER_PROMPT,
    REVIEWER_PROMPT,
)


def _call_llm(system_prompt, user_content, temp=0.4, max_tokens=4000, timeout=180, label="agent"):
    """底层 LLM 调用 — 兼容 script_agents.py 的协议"""
    result = call_deepseek_json(
        system_prompt, user_content,
        temperature=temp, max_tokens=max_tokens,
        timeout=timeout, retries=3, label=label,
    )
    if result["ok"]:
        data = result["data"]
        if isinstance(data, list):
            data = {"items": data}
        return {"ok": True, "result": data}
    return {"ok": False, "error": result.get("error", "?")[:200]}


# ═══════════════════════════════════════════════════════════════
# 数据加载辅助函数
# ═══════════════════════════════════════════════════════════════

def _load_all_synopses(project_dir: Path, episodes: list[int] = None) -> dict:
    """加载剧集剧情概要 → {ep: synopsis_dict}

    episodes: 指定则只加载这些集（浅层 RAG 的检索键），None 则加载全部。
    兼容旧纯文本结构与新结构化结构，统一返回 dict (经 lib.synopsis)。
    """
    synopses = {}
    sources = project_dir / "sources"
    if not sources.exists():
        return synopses

    for ep_dir in sorted(sources.iterdir()):
        if not ep_dir.is_dir() or not ep_dir.name.startswith("ep"):
            continue
        try:
            ep = int(ep_dir.name[2:])
        except ValueError:
            continue
        if episodes is not None and ep not in episodes:
            continue
        data = load_synopsis(project_dir, ep)
        if data:
            synopses[ep] = data
    return synopses


def _load_scene_maps(project_dir: Path, episodes: list[int]) -> dict:
    """加载指定剧集的 scene_map → {ep: [scene_dict, ...]}"""
    scene_maps = {}
    sources = project_dir / "sources"
    for ep in episodes:
        sm_file = sources / f"ep{ep}" / "scene_map.json"
        if not sm_file.exists():
            sm_file = sources / f"ep{ep:02d}" / "scene_map.json"
        if sm_file.exists():
            scene_maps[ep] = json.load(open(sm_file))
    return scene_maps


def _load_asr_text(project_dir: Path, episodes: list[int]) -> dict:
    """加载指定剧集的 ASR 台词 → {ep: [{start, end, text}]}"""
    asr_texts = {}
    sources = project_dir / "sources"
    for ep in episodes:
        asr_file = sources / f"ep{ep}" / "asr_result.json"
        if not asr_file.exists():
            asr_file = sources / f"ep{ep:02d}" / "asr_result.json"
        if asr_file.exists():
            try:
                asr_texts[ep] = json.load(open(asr_file))
            except Exception:
                asr_texts[ep] = []
    return asr_texts


# ASR 关键词锚点停用词（复用 dialogue.py 的思路）
_ASR_STOPWORDS = {
    '一个', '这个', '那个', '什么', '怎么', '就是', '还是', '可以', '已经',
    '因为', '所以', '但是', '不过', '虽然', '如果', '只是', '还不', '不了',
    '哪个', '哪儿', '不是', '我们', '我是', '他们', '你想', '想去',
    '去跟', '跟他', '还不',
}


def _anchor_highlight(highlight_text: str, ep: int, asr_texts: dict) -> dict:
    """把 highlight_text 锚定到指定集的 ASR，返回真实 {ep, start, end, text} 或 None。

    滑窗关键词匹配（零 LLM），复用 dialogue.py 的思路。
    """
    if not highlight_text or not ep:
        return None
    asr_list = asr_texts.get(ep, [])
    if not asr_list:
        return None

    # 清洗：去掉标点，取前 15 字做锚
    import re as _re
    anchor = _re.sub(r'[，。！？、\s""''「」『』【】《》（）]', '', highlight_text)[:15]
    if len(anchor) < 2:
        return None

    # 生成 2-4 字滑窗关键词
    kws = []
    for n in [2, 3, 4]:
        for i in range(len(anchor) - n + 1):
            kw = anchor[i:i + n]
            if kw not in _ASR_STOPWORDS:
                kws.append(kw)
    if not kws:
        return None

    # 在 ASR 里找最高分命中
    best = None
    best_score = 0
    for a in asr_list:
        text = a.get("text", "")
        score = sum(text.count(k) * (3 if len(k) >= 3 else 2) for k in kws)
        if score > best_score:
            best_score = score
            best = a

    if best and best_score > 5:
        return {"ep": ep, "start": best["start"], "end": best["end"], "text": best["text"][:200]}
    return None


def _pick_line_from_window(ep: int, time_range: list, asr_texts: dict) -> dict:
    """从指定集的 ASR 时间窗内，挑一句最有冲击力的真实台词。

    这是「先场景后台词」的程序实现：场景选对（episode + time_range），
    台词就从 ASR 里自然取出来，杜绝文案师编造。
    返回 {"ep", "start", "end", "text"} 或 None。
    """
    if not ep or not time_range or len(time_range) != 2:
        return None
    asr_list = asr_texts.get(ep, [])
    if not asr_list:
        return None

    start, end = time_range
    # 取时间窗内的 ASR 句
    window = [a for a in asr_list if a["start"] >= start - 2 and a["end"] <= end + 2]
    if not window:
        # 时间窗内无台词，放宽到 ±5 秒
        window = [a for a in asr_list if a["start"] >= start - 5 and a["start"] <= end + 5]
    if not window:
        return None

    # 挑一句：字数适中（6-30字）、有情绪冲击（含感叹/反问/否定词的加分）
    def _score(a):
        t = a.get("text", "")
        s = len(t)
        # 长度：太短(<=3字)或无意义的不选，6-30字最佳
        if s < 4:
            return -100
        score = 0
        if 6 <= s <= 30:
            score += 10
        elif s > 30:
            score -= 5  # 太长，可能是一段连续转写
        # 情绪冲击词
        for w in ["！", "？", "不", "别", "你", "我", "滚", "闭嘴", "报警", "打"]:
            if w in t:
                score += 2
        return score

    best = max(window, key=_score)
    if best and _score(best) > 0:
        return {"ep": ep, "start": best["start"], "end": best["end"], "text": best["text"][:200]}
    return None


def _load_vlm_descriptions(project_dir: Path, episodes: list[int]) -> dict:
    """加载 VLM 描述（可选，用于增强写作上下文）→ {ep: {scene_idx: vlm_data}}"""
    vlm = {}
    sources = project_dir / "sources"
    for ep in episodes:
        vlm_file = sources / f"ep{ep}" / "vlm_seg_cache_v3.json"
        if not vlm_file.exists():
            vlm_file = sources / f"ep{ep:02d}" / "vlm_seg_cache_v3.json"
        if vlm_file.exists():
            vlm[ep] = json.load(open(vlm_file))
    return vlm


def _format_synopses_text(synopses: dict) -> str:
    """将全部剧集概要格式化为 LLM 输入文本 (兼容旧纯文本/新结构化)"""
    lines = []
    for ep in sorted(synopses.keys()):
        text = to_text(synopses[ep])
        # 清理 markdown 格式
        text = re.sub(r'\*\*|#{1,4}\s*', '', text)
        lines.append(f"═══ 第{ep}集 ═══\n{text[:600]}")
    return '\n\n'.join(lines)


def _format_scene_map_text(scene_map: list, ep: int) -> str:
    """将单集 scene_map 格式化为 LLM 输入文本"""
    lines = [f"═══ 第{ep}集 场景分段 ═══"]
    for i, sm in enumerate(scene_map):
        chars = '、'.join(sm.get('characters', []))
        time_str = f"{sm['time_range'][0]}s-{sm['time_range'][1]}s"
        lines.append(
            f"[场景{i}] {time_str} | 📍{sm.get('location', '?')} | "
            f"👤{chars} | 事件:{sm.get('event', '?')} | 情绪:{sm.get('mood', '?')}"
        )
    return '\n'.join(lines)


def _anchor_to_fact_cards(scene_anchors: list, scene_maps: dict, asr_texts: dict) -> list:
    """把 scene_anchors 精确锚回 scene_map 原始条目，产出「锁定的事实卡片」。

    这是 LCAS 的 Core Anchor + Permanent Red Line 落地：
    - 每张卡片 = {who, action(锁死 scene_map 原文), where, when{ep,time_range}, mood, dialogue}
    - 匹配不上 → 丢弃该锚，绝不编造。

    锚定策略（按可靠性从高到低）：
    1. character_focus 人物匹配：anchor 指定的人物与 scene_map 场景人物有交集
       （人物是稳定锚点，LLM 概括的 event 文本不可靠，所以以人物为主）
    2. event 字符串重叠兜底：锚 event 与 scene_map event 有 3+ 字重叠
    3. 两者都无 → 丢弃

    文案师只拿这些卡片写作，看不到 scene_map 全文，物理上无法引入卡片外的事实。
    """
    if not scene_anchors:
        return []

    cards = []
    for anchor in scene_anchors:
        ep = anchor.get('ep')
        ev = (anchor.get('event') or '').strip()
        focus_chars = set(anchor.get('character_focus') or [])
        if not ep:
            continue
        sm_list = scene_maps.get(ep, [])
        if not sm_list:
            continue

        # 锚回 scene_map：优先「人物匹配」，其次「event 重叠」
        matched_sm = None
        # 第一优先级：character_focus 与场景人物有交集（选交集最多的）
        if focus_chars:
            best = None
            best_overlap = 0
            for sm in sm_list:
                sm_chars = set(sm.get('characters', []))
                overlap = len(focus_chars & sm_chars)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best = sm
            if best is not None and best_overlap > 0:
                matched_sm = best
        # 第二优先级：event 字符串重叠（≥3 字）
        if matched_sm is None and ev:
            for sm in sm_list:
                if _overlap(ev, sm.get('event', '')) >= 3:
                    matched_sm = sm
                    break
        if matched_sm is None:
            continue  # 锚不回 scene_map = 弃锚，不编造

        start, end = matched_sm['time_range']
        # 关联 ASR 台词（供文案师写"谁说了什么"时查证 + 原声段提取）
        dialogue = ''
        if asr_texts:
            asr_list = asr_texts.get(ep, [])
            window = [a for a in asr_list if a['start'] >= start - 1 and a['end'] <= end + 1]
            dialogue = ' '.join(a['text'] for a in window)[:600]

        cards.append({
            'card_id': len(cards),
            'ep': ep,
            'who': matched_sm.get('characters', []),
            'action': matched_sm.get('event', ''),   # 锁死 scene_map 原文
            'where': matched_sm.get('location', ''),
            'time_range': [start, end],
            'mood': matched_sm.get('mood', ''),
            'dialogue': dialogue,
            'anchor_event': ev,                       # 策划师的原始描述（可对照）
            'use_original_dialogue': anchor.get('use_original_dialogue', False),
            'dialogue_hook': anchor.get('dialogue_hook', ''),
        })

    return cards


def _format_fact_cards(cards: list) -> str:
    """把事实卡片格式化为文案师的输入文本（LCAS 的 Core Anchor 注入）。"""
    if not cards:
        return "(无事实卡片)"
    lines = ["以下是你唯一能写的事实依据（★ 锁死的真实剧情，卡片外的事实一律不能写）："]
    for c in cards:
        who = '、'.join(c['who']) or '?'
        # 名场面卡片标记：提示文案师这里要留「原声段」，让角色亲口说
        mark = ' 🎬 名场面·播原声' if c.get('use_original_dialogue') else ''
        lines.append(
            f"[卡片{c['card_id']}]{mark} EP{c['ep']} {c['where']} | 人物:{who} | "
            f"事件:{c['action']} | 情绪:{c['mood']}"
        )
        if c.get('dialogue_hook'):
            lines.append(f"   原声钩子: {c['dialogue_hook']}")
        if c['dialogue']:
            lines.append(f"   原声台词: {c['dialogue'][:200]}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# 【已停用】_verify_narration 事后校验（Load Integrity Audit 的粗粒度版）
# 停用原因：事实卡片分离（_anchor_to_fact_cards）已从源头杜绝硬事实幻觉，
#   这个「人名+动词」的事后校验频繁误报（"扇耳光"比喻、"推开门"日常动作、
#   主语错配等），边际价值为负。保留代码备查，不再被 pipeline 调用。
# ─────────────────────────────────────────────────────────────
# 强动作动词：当「人名 + 这些动词」出现在 narration 里，才可能是"编造的具体动作"。
# 只收「谁主动对谁施加」的强动作；不收：
#   - 被动状态/结果（停职/辞职/开除/住院）→ 主语难判，且多为剧情结果转述，不算幻觉
#   - 日常歧义动词（推/撞/拉）→ "推开门""撞见"不是事实性动作
_ACTION_VERBS = {
    '扇', '踢', '砍', '刺', '杀', '掐', '揍', '踹',
    '离婚', '报警', '起诉', '撤诉', '挪用',
    '偷', '骗', '赌', '跳楼', '自杀', '出轨', '包养',
}
# "打人"的确切含义：打 后直接跟 人名/代词/"了"（"打她""打苏明玉""打了"）
import re as _re
_PUNCH_PATTERN = _re.compile(r'打(?:了|过)?(?:她|他|你|我|人|苏明玉|苏明成|苏大强|苏明哲|朱丽|吴非|众邦|舅舅|舅妈)')


def _verify_narration(narration_text: str, cards: list) -> list:
    """程序校验 narration 是否引入了卡片外的事实（LCAS 的 Load Integrity Audit 落地）。

    ★ 判据（收窄后）：只抓「人名 + 强动作动词」构成的事实性陈述——
    - 例：『苏大强扇了苏明玉』（人名+动作，卡片里没有这个动作 → 幻觉）
    - 不抓：『朱丽哭着求』（合理提及人物，无强动作动词 → 放过）
    纯提到人名不做判断，避免误伤解说里的正常议论。

    Returns: 风险提示列表（空 = 通过）。
    """
    if not narration_text or not cards:
        return []

    # 卡片里已知的人名集合
    known_names = set()
    for c in cards:
        known_names.update(c['who'])

    # 提取 narration 里出现的人名（KNOWN_CHARACTERS + 配角白名单）
    all_names = set(KNOWN_CHARACTERS) | {'柳青', '蒙总', '老蒙', '石天冬', '孙副总', '小蒙总', '蒙太', '朱丽母亲', '朱丽父亲', '舅舅', '舅妈', '苏母', '小咪'}
    mentioned_names = [n for n in all_names if n in narration_text]

    risks = []
    for name in mentioned_names:
        # 只查「人名 + 强动作动词」的事实陈述
        for verb in _ACTION_VERBS:
            if verb in narration_text:
                if name not in known_names:
                    risks.append(f"人物「{name}」不在本章事实卡片中，却出现动作「{verb}」（疑似幻觉）")
                    break  # 一个人名只报一次
        # "打人"单独处理（打 + 人称宾语）
        if name not in known_names and _PUNCH_PATTERN.search(narration_text):
            risks.append(f"人物「{name}」不在本章事实卡片中，却出现打人动作（疑似幻觉）")

    return risks


def _build_char_summary() -> str:
    """构建角色统计文本"""
    counts = get_char_counts()
    if not counts:
        counts = {c: 0 for c in KNOWN_CHARACTERS}
    items = sorted(counts.items(), key=lambda x: -x[1])
    return '、'.join(f"{c}({cnt}场)" for c, cnt in items)


def _infer_episodes_from_topic(project_dir: Path, topic: str, limit: int = 8) -> list[int]:
    """深层 RAG 检索键：从选题文本反推相关剧集（无需用户指定）

    策略：遍历 scene_map，统计每个场景的 characters/event/location 与选题里
    出现的人名/关键词的重合度，按命中强度排序取 top-N 集。
    —— 这是「身份查询」而非「语义相似」，零 LLM 调用。
    """
    names_hit = [n for n in KNOWN_CHARACTERS if n in topic]
    # 关键词：非人名的实义片段（粗暴分词：按标点/空格切，保留 2+ 字）
    raw_kws = re.split(r'[，。、：:；;\s]+', topic)
    kws = [w for w in raw_kws if len(w) >= 2 and w not in names_hit]

    scores = Counter()
    sources = project_dir / "sources"
    for ep_dir in sorted(sources.iterdir()):
        if not ep_dir.is_dir() or not ep_dir.name.startswith("ep"):
            continue
        try:
            ep = int(ep_dir.name[2:])
        except ValueError:
            continue
        sm_file = ep_dir / "scene_map.json"
        if not sm_file.exists():
            continue
        try:
            scene_map = json.load(open(sm_file))
        except Exception:
            continue
        for s in scene_map:
            chars = set(s.get('characters', []))
            text = (s.get('event', '') + ' ' + s.get('location', ''))
            # 人名命中：强信号，每命中一个 +3
            for n in names_hit:
                if n in chars:
                    scores[ep] += 3
            # 关键词命中：弱信号，每个 +1
            for kw in kws:
                if kw in text:
                    scores[ep] += 1

    # 按得分排序，取 top-N
    ranked = [ep for ep, _ in scores.most_common(limit)]
    return sorted(ranked) if ranked else None


def _emotion_signature(project_dir: Path, char: str, limit: int = 8) -> dict:
    """计算某人物在每集的「情绪签名」：冲突场数 vs 缓和场数。

    用于区分"纯冲突"集（如 EP35 冲突11/缓和0）和"冲突→缓和转折"集
    （如 EP39 冲突6/缓和11）——后者才是"觉醒/守护"类弧线的关键拐点，
    synopsis 概要层区分不了，必须下沉到 scene_map 的情绪维度。
    零 LLM 调用。
    """
    CONFLICT = {'愤怒','激烈','紧张','压抑','冲突','对抗','尴尬','焦虑','严肃','担忧','无奈','悲伤'}
    SOFT = {'感动','释然','温馨','轻松','平静','期待','坚定'}
    sig = {}
    sources = project_dir / "sources"
    for ep_dir in sorted(sources.iterdir()):
        if not ep_dir.is_dir() or not ep_dir.name.startswith("ep"):
            continue
        try:
            ep = int(ep_dir.name[2:])
        except ValueError:
            continue
        sm_file = ep_dir / "scene_map.json"
        if not sm_file.exists():
            continue
        try:
            scene_map = json.load(open(sm_file))
        except Exception:
            continue
        c = s = 0
        for sc in scene_map:
            if char in sc.get('characters', []):
                m = sc.get('mood', '')
                if any(x in m for x in CONFLICT):
                    c += 1
                elif any(x in m for x in SOFT):
                    s += 1
        if c or s:
            sig[ep] = (c, s, '转折' if (c > 0 and s > 0) else '单向')
    return sig


def _infer_episodes_from_topic_llm(project_dir: Path, topic: str, limit: int = 8) -> list[int]:
    """深层 RAG 检索键（Agentic 版）：让 LLM 基于选题 + 各集梗概 + 情绪签名反推关键集。

    为什么不用统计/BGE：叙事弧线（如"妈宝→守护者"）是语义概念，for 循环的
    频率统计和 BGE 的概要相似度都抓不到转折点，只有 LLM 能理解"弧线节点"。
    这是「检索本身也由 LLM 承担」的 Agentic RAG 形态。

    优化点（v2）：
    1. LLM 显式标注「弧线角色」（起点/转折/高潮/终点），避免漏掉头尾。
    2. 注入 scene_map 的情绪签名（冲突/缓和/转折），区分"纯冲突集"(EP35)
       与"冲突→缓和转折集"(EP39)——后者才是"觉醒/守护"类弧线的拐点。
    """
    # 提取主角名（KNOWN_CHARACTERS 中命中 topic 的第一个）
    names_hit = [n for n in KNOWN_CHARACTERS if n in topic]
    main_char = names_hit[0] if names_hit else None

    # 字段级检索：直接喂 LLM 结构化 synopsis 的「人物弧线 + 关键冲突」字段，
    # 不再取 to_text() 前 N 字（会把关键人物弧线字段截掉，见 V4 教训）。
    # 若识别到主角，额外把该主角的 arc 单独拎出来（弧线信号最精确）。
    lines = []
    sources = project_dir / "sources"

    # 情绪签名（若识别到主角）
    sig = _emotion_signature(project_dir, main_char) if main_char else {}

    for ep in range(1, 47):
        syn = load_synopsis(project_dir, ep)
        if not syn:
            continue
        if syn.get("_legacy"):
            # 旧纯文本：取前 200 字兜底
            brief = to_text(syn).strip().replace("\n", " ")[:200]
        else:
            # 新结构化：拼「关键冲突 + 该主角人物弧线」两个字段
            parts = []
            conflicts = syn.get("key_conflicts") or []
            if conflicts:
                parts.append("冲突:" + "；".join(conflicts[:3]))
            if main_char:
                for a in (syn.get("character_arcs") or []):
                    if a.get("character") == main_char:
                        seg = f"弧线:{a.get('arc','')}"
                        rc = a.get("relations_change") or []
                        if rc:
                            seg += "(" + "；".join(rc) + ")"
                        parts.append(seg)
                        break
            if not parts:
                # 该集无主角弧线 → 用主题兜底
                parts.append("主题:" + (syn.get("theme") or "")[:40])
            brief = " ".join(parts)
        # 拼情绪签名
        emo = ""
        if ep in sig:
            c, s, t = sig[ep]
            emo = f" [情绪:冲突{c}/缓和{s}/{t}]"
        lines.append(f"EP{ep}: {brief}{emo}")
    brief_text = "\n".join(lines)

    system = (
        "你是影视解说选题策划。用户给出一条人物线/主题线选题（通常是『从X到Y』格式），"
        "你要从下面的 46 集剧情梗概中，找出最能支撑这条叙事弧线的关键剧集。\n"
        "每集末尾的 [情绪:冲突X/缓和Y/转折或单向] 是该集主角场景的情绪签名：\n"
        "- 『转折』= 冲突与缓和并存，通常是觉醒/和解/守护的拐点\n"
        "- 『单向』= 纯冲突或纯缓和，通常是冲突升级或日常戏\n"
        "★ 关键：你必须覆盖弧线的完整结构（起点/转折/高潮/终点），"
        "尤其注意『转折』集——如『从冲突到守护』的拐点，情绪签名会从单向冲突转为转折。\n"
        "只返回 JSON，格式：\n"
        "{\"arc\": [{\"ep\": 1, \"role\": \"起点\"}, {\"ep\": 21, \"role\": \"转折\"}, ...]}"
    )
    user = (
        f"选题：{topic}\n\n"
        f"46 集梗概（含情绪签名）：\n{brief_text}\n\n"
        f"请选出最多 {limit} 集，按叙事顺序（起点→转折→高潮→终点）排列，"
        f"role 取值：起点/转折/高潮/终点/铺垫。"
    )
    res = call_deepseek_json(system, user, temperature=0.2, max_tokens=400,
                             timeout=120, label="deep_rag_infer")
    if not res.get("ok"):
        return None
    data = res.get("data") or {}
    arc = data.get("arc") or data.get("episodes") or []
    eps = []
    if arc and isinstance(arc, list) and isinstance(arc[0], dict):
        # 新版：带 role 的结构
        for item in arc:
            ep = item.get("ep") if isinstance(item, dict) else item
            try:
                eps.append(int(ep))
            except (TypeError, ValueError):
                continue
    else:
        # 兼容旧版：纯集号列表
        try:
            eps = [int(e) for e in arc if isinstance(e, (int, float))]
        except Exception:
            return None
    return eps[:limit] if eps else None


def _extract_key_episodes_from_story_map(story_map: dict, topic: str, limit: int = 8) -> list[int]:
    """从故事师产出的 story_map 提取关键集（替代独立反推的选集方案）。

    为什么：故事师已通读全 46 集概要，产出的 character_arcs[].key_episodes
    就是「人物弧线的关键集」，比 _infer_episodes_from_topic_llm 的逐集字段匹配
    精确得多（后者漏掉了 EP45 这种"主动守护"的弧线终点）。
    """
    # 找到与选题最相关的主角（topic 命中的人名）
    from lib.vlm_cache import KNOWN_CHARACTERS as _KC
    names_hit = [n for n in _KC if n in topic]
    arcs = story_map.get("character_arcs", [])

    target_arcs = []
    if names_hit:
        target_arcs = [a for a in arcs if a.get("name") in names_hit]
    if not target_arcs:
        target_arcs = arcs  # 未命中则取全部弧光

    eps = []
    for a in target_arcs:
        for ep in (a.get("key_episodes") or []):
            try:
                eps.append(int(ep))
            except (TypeError, ValueError):
                continue

    # 去重保序，取 top-N
    seen = set()
    ordered = []
    for ep in eps:
        if ep not in seen:
            seen.add(ep)
            ordered.append(ep)
    return ordered[:limit] if ordered else None


# ═══════════════════════════════════════════════════════════════
# Agent 0: 制片 — 选题决策层（评判候选 + 排序 + 推荐理由）
# ═══════════════════════════════════════════════════════════════

PRODUCER_PROMPT = """你是影视解说工作室的「制片人」。你的职责不是生成选题，而是从候选选题中【评判、排序、拍板】——决定哪个选题最值得做成解说视频。

★ 职责边界（重要）：你只回答「值不值得做」（市场判断），【不负责】「怎么讲才精彩」（那是论点师的活）。所以你不写钩子标题、不做反转/悬念/差异化角度——那些留给后续的论点师。

评判维度（每个 1-5 分）：
- traffic（流量潜力）：话题是否自带讨论度、共鸣点、搜索热度
- fit（账号匹配）：是否契合账号定位（影视解说 · 人物线/情感/冲突向）
- material（素材质量）：有没有足够集中的剧集、足够的冲突密度、足够的高光场面支撑一条解说

输出 JSON：
{
  "ranked": [
    {"title": "选题名（保留输入标题，或简化为「人物名+题材」，不写钩子、不写反转/悬念）", "score": 总分, "scores": {"traffic":5,"fit":4,"material":4},
     "reason": "为什么这个题材值得做（流量/素材角度，≤40字）", "recommend": true/false, "episodes": [集号列表，从输入候选原样复制]}
  ],
  "top_pick": "首推选题名",
  "strategy_note": "一句话整体选题策略"
}

规则：
- 只排序输入的候选，不要凭空生成新选题
- ★ episodes 回填：每个 ranked 项的 episodes 字段，必须从输入候选里对应项的「集X」原样复制过来（保留数字，不要编造、不要省略）。
- ★ 标题：不要重写成钩子式标题。保留输入标题，或简化为「人物名 + 题材」（如"苏明成：从啃老到打亲妹"）。禁止写"一拳把亲妹打进医院"这种带反转/悬念的钩子——那是论点师的活。
- recommend=true 的应占少数（精选，不是全推）
- reason 要具体（流量 + 素材数据支撑），不要空话
- ★ 选题主体铁律：短视频解说只做「剧情弧」类选题，只有三种切法——
  1. 人物性格型（这个人是什么性格，锚定一个性格弧）
  2. 事件策略型（这件事怎么破的局，锚定一个事件弧）
  3. 反差打脸型（都以为XX结果YY，锚定一个反转弧）
  硬约束：
  · 社会议题（重男轻女/养老/啃老）只能作为升华点，【不得作为选题主体/标题】——议题是主题不是弧，撑不起短视频。
  · 成长蜕变型（全剧长弧，素材跨 46 集）违反"集数集中"，【排除】。
  · 金句盘点型（全剧金句合集）是碎片无主体，【排除】。
  当候选里出现上述三类违规选题时，即使数据好看也要降级或不推荐，并在 reason 里说明"违反弧约束"。
"""


def _load_account_profile() -> dict:
    """加载账号画像配置（从项目 json 的 account 字段）。

    账号级画像挂在项目配置里，跨生成复用。返回 dict，缺失时返回空。
    """
    try:
        from config import project_config
        return project_config.get("account", {}) or {}
    except Exception:
        return {}


def producer_agent(candidates: list, account_positioning: str = None) -> dict:
    """制片 Agent（决策层）：消费候选选题，评判排序，输出推荐。

    Args:
      candidates: 候选选题列表，每项 {"title", "type", "episodes"/"evidence", "hook"/"angle"}
      account_positioning: 账号定位（None 时从项目配置的 account 字段读取）

    Returns:
      {"ok": True, "result": {...}} | {"ok": False, "error": ...}
    """
    if not candidates:
        return {"ok": False, "error": "无候选选题"}

    # 账号画像：优先入参，否则读配置
    profile = _load_account_profile()
    if account_positioning is None:
        account_positioning = profile.get("positioning", "影视解说 · 人物线/情感/冲突向")

    # 拼完整账号画像（定位 + 受众 + 价值主张）
    account_desc = f"账号定位：{account_positioning}"
    if profile.get("core_audience"):
        account_desc += f"\n核心受众：{profile['core_audience']}"
    if profile.get("audience_want"):
        account_desc += f"\n受众要什么：{profile['audience_want']}"

    # 候选序列化为文本（限长，控制 token）
    cand_text = "\n".join(
        f"{i+1}. {c.get('title','')} [{c.get('type','')}] "
        f"集{c.get('episodes', c.get('episodes_covered', []))} "
        f"| 证据:{c.get('evidence', c.get('hook', ''))}"
        for i, c in enumerate(candidates[:15])
    )

    user = (
        f"{account_desc}\n\n"
        f"候选选题（共 {len(candidates)} 个）：\n{cand_text}\n\n"
        f"请评判、排序，给出首推选题和推荐理由。"
    )

    res = call_deepseek_json(PRODUCER_PROMPT, user, temperature=0.4, max_tokens=2000,
                             timeout=180, label="producer_agent")
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error", "?")[:200]}
    return {"ok": True, "result": res.get("data") or {}}


def validate_producer_output(candidates: list, result: dict) -> list:
    """制片 Agent 输出的「守规矩」轻量检查（确定性断言，0 LLM）。

    只测可客观验证的约束，不测排序品味（那无标准答案，靠人审）：
    1. 输出的候选都来自输入候选（没凭空造选题）
    2. 无社会议题/盘点型违规主体（弧约束的确定性部分）

    注意：不再检查"标题是否重写"——职责边界调整后，制片不再重写钩子标题，
    只保留/简化选题名，所以"照抄输入标题"是允许的。

    Returns:
      问题列表（空 = 通过）
    """
    issues = []
    ranked = result.get("ranked") or []
    input_titles = {c.get("title", "") for c in candidates}

    for r in ranked:
        title = r.get("title", "")
        # 凭空造选题检查：输出标题应至少与某个输入候选有部分关联
        # （宽松检查：输出标题含输入标题的任意 3+ 连续字，视为关联）
        related = any(_overlap(title, it) >= 3 for it in input_titles)
        if not related and input_titles:
            issues.append(f"疑似凭空造选题: {title}")

    return issues


def _overlap(a: str, b: str, min_len: int = 3) -> int:
    """两个字符串的最长公共子串长度（用于宽松的关联判断）"""
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


# ═══════════════════════════════════════════════════════════════
# Agent 1: 故事师 — 通读全部剧集概要，提取故事地图
# ═══════════════════════════════════════════════════════════════

def story_master_agent(project_dir: Path, drama_name: str,
                       focus_episodes: list[int] = None) -> dict:
    """输入: 全部剧集概要 → 输出: story_map

    如果指定 focus_episodes，额外加载对应 scene_map 辅助分析。
    """
    # 加载数据（浅层 RAG：指定集则只读这些集，不再全量 46 集）
    synopses = _load_all_synopses(project_dir, focus_episodes)
    if not synopses:
        return {"ok": False, "error": f"未找到任何剧集概要数据 (sources/ep*/ep_synopsis.json)"}

    syn_text = _format_synopses_text(synopses)

    # 可选：加载焦点剧集的 scene_map 辅助
    if focus_episodes:
        scene_maps = _load_scene_maps(project_dir, focus_episodes)
        scene_context = '\n\n'.join(
            _format_scene_map_text(sm, ep) for ep, sm in sorted(scene_maps.items())
        )
        scene_note = f"\n\n★★ 以下是用户关注的剧集的详细场景分段（辅助分析）：\n{scene_context[:8000]}"
    else:
        scene_note = ""

    episode_constraint = ""
    if focus_episodes:
        ep_list = '、'.join(str(e) for e in sorted(focus_episodes))
        episode_constraint = f"\n★ 用户当前关注剧集: 第{ep_list}集。请在 highlight_scenes 和 topic_suggestions 中优先覆盖这些剧集。"

    system = STORY_MASTER_PROMPT.format(
        drama_name=drama_name,
        known_characters='、'.join(KNOWN_CHARACTERS),
        episode_constraint=episode_constraint,
    )

    user = (
        f"★★ 全部剧集剧情概要 (共{len(synopses)}集):\n\n"
        f"{syn_text}"
        f"{scene_note}"
    )

    return _call_llm(system, user, temp=0.3, max_tokens=8000, timeout=300, label="story_master")


# ═══════════════════════════════════════════════════════════════
# Agent 2: 论点师 — 从故事地图提炼反常识论点 + 叙事装置（候选，人拍板）
# ═══════════════════════════════════════════════════════════════

def thesis_agent(story_map: dict, topic: str, scene_maps: dict = None, focus_eps: list = None) -> dict:
    """输入: story_map + 用户选题 +（可选）聚焦集 scene_map → 输出: 3~5 个候选论点+装置

    复用故事师已产出的 story_map，不重复读 46 集概要。
    产出候选供「人拍板」，每个候选带 why_not_common 说明认知增量。

    scene_maps: {ep: [scene_dict,...]} 选题聚焦剧集的场景细节。
      论点必须锚定这些集里的事件，而不是全剧主题（防论点漂移到"原生家庭"这种大词）。
    focus_eps: 聚焦剧集号列表，用于 prompt 提示。
    """
    # 压缩 story_map 到 LLM 可读的精华（highlight_scenes + turning_points + character_arcs 概要）
    highlights = story_map.get('highlight_scenes', [])
    turnings = story_map.get('turning_points', [])
    arcs = story_map.get('character_arcs', [])

    hl_text = "\n".join(
        f"- EP{h.get('ep')} {h.get('event','')} (情绪:{h.get('mood','')}, 叙事价值:{h.get('narrative_value','')})"
        for h in highlights[:15]
    )
    tp_text = "\n".join(
        f"- EP{t.get('ep')} {t.get('event','')} (影响:{t.get('impact','')})"
        for t in turnings[:10]
    )
    arc_text = "\n".join(
        f"- {a.get('name','')}: {a.get('arc_summary','')} (关键集:{a.get('key_episodes',[])})"
        for a in arcs[:6]
    )

    # 聚焦集 scene_map 细节：论点必须锚定这些事件
    scene_context = ""
    if scene_maps:
        scene_parts = []
        for ep in sorted(scene_maps.keys()):
            scene_parts.append(_format_scene_map_text(scene_maps[ep], ep))
        if scene_parts:
            scene_context = (
                "\n\n★★ 选题聚焦剧集的场景细节（论点必须锚定这些具体事件，不能漂到全剧主题）:\n"
                + '\n\n'.join(scene_parts)[:6000]
            )

    focus_note = ""
    if focus_eps:
        focus_note = f"\n★ 选题聚焦剧集: 第{'、'.join(str(e) for e in focus_eps)}集。论点必须解释这些集里的具体事件（如『打人』），不能是贯穿全剧的大词（如『原生家庭』『权力结构』）。"

    user = (
        f"★★ 用户选题: {topic}\n\n"
        f"★★ 故事地图 — 人物弧光:\n{arc_text}\n\n"
        f"★★ 关键转折点:\n{tp_text}\n\n"
        f"★★ 高光场景:\n{hl_text}\n"
        f"{scene_context}"
        f"{focus_note}\n\n"
        f"请为这个选题提炼 3~5 个反常识论点候选（每个带叙事装置 + 认知增量说明）。"
    )

    res = _call_llm(THESIS_AGENT_PROMPT, user, temp=0.6, max_tokens=2500, label="thesis_agent")
    if res.get("ok"):
        # 程序校验 supporting_events 是否真实：过滤掉"为论点脑补的剧情"的候选
        res["result"] = _filter_fabricated_candidates(res["result"], story_map, scene_maps)
    return res


def _filter_fabricated_candidates(result: dict, story_map: dict, scene_maps: dict = None) -> dict:
    """校验论点候选的 supporting_events 是否能在 story_map/scene_map 查到原文。

    LLM 会为了"反常识"脑补剧情细节（如"奔账本而去"），程序把这种候选过滤掉。
    只保留 supporting_events 里事件能在真实数据里找到依据的候选。
    """
    candidates = result.get("candidates", [])
    if not candidates:
        return result

    # 收集所有真实事件文本（story_map 的 highlight_scenes/turning_points + scene_map 的 event）
    real_events = set()
    for h in story_map.get("highlight_scenes", []):
        real_events.add((h.get("event") or "").strip())
    for t in story_map.get("turning_points", []):
        real_events.add((t.get("event") or "").strip())
    if scene_maps:
        for ep, sm in scene_maps.items():
            for s in sm:
                real_events.add((s.get("event") or "").strip())

    kept = []
    for c in candidates:
        evs = c.get("supporting_events", [])
        if not evs:
            # 无支撑事件 → 无戏可唱，过滤
            continue
        # 至少一个支撑事件能在真实数据里找到（重叠≥6字，比 3 字严格，防止"动手"这类短词误判）
        has_real = any(
            any(_overlap((e.get("event") or ""), real) >= 6 for real in real_events)
            for e in evs
        )
        if has_real:
            kept.append(c)

    result["candidates"] = kept
    return result


def _format_thesis_note(thesis: dict) -> str:
    """把选定论点格式化为注入文案师/策划师/审核师的锚点文本。"""
    if not thesis:
        return ""
    thesis_text = thesis.get('thesis', '')
    device = thesis.get('device', '')
    why = thesis.get('why_not_common', '')
    lines = [f"★★ 你的核心论点（唯一的锚）: {thesis_text}"]
    if device:
        lines.append(f"   叙事装置: {device}")
    if why:
        lines.append(f"   认知增量（观众想不到的点）: {why}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Agent 3: 策划师 — 围绕论点设计事件链骨架
# ═══════════════════════════════════════════════════════════════

def narrative_planner_agent(story_map: dict, user_topic: str,
                            target_duration: int = 480, thesis: dict = None) -> dict:
    """输入: story_map + 用户选题 → 输出: chapter_structure"""
    # 提取角色列表
    char_arcs = story_map.get('character_arcs', [])
    main_char_names = [a['name'] for a in char_arcs[:5]] if char_arcs else KNOWN_CHARACTERS

    # 构建章节数建议
    suggested_chapters = max(4, min(7, target_duration // 80))

    system = NARRATIVE_PLANNER_PROMPT

    # 论点锚：策划师设计的每个章节必须指向它
    thesis_note = _format_thesis_note(thesis)
    if thesis_note:
        thesis_note += "\n\n"

    user = (
        f"故事地图:\n{json.dumps(story_map, ensure_ascii=False, indent=2)[:8000]}\n\n"
        f"{thesis_note}"
        f"★★ 用户选题: {user_topic}\n"
        f"★★ 目标时长: {target_duration}秒 (约{target_duration//60}分钟)\n"
        f"★★ 建议章节数: {suggested_chapters}章\n"
        f"★★ 主要角色: {', '.join(main_char_names)}\n\n"
        f"请设计叙事方案（事件链，围绕论点）。"
    )

    return _call_llm(system, user, temp=0.5, max_tokens=3000, label="narrative_planner")


# ═══════════════════════════════════════════════════════════════
# Agent 3: 文案师 — 逐章写作解说词 + scene_query
# ═══════════════════════════════════════════════════════════════

def script_writer_agent(chapter: dict, fact_cards: list,
                        prev_chapter_summary: str = "",
                        next_chapter_summary: str = "",
                        synopses: dict = None,
                        topic_type: str = None,
                        thesis: dict = None,
                        argued_note: str = "") -> dict:
    """输入: 单个章节方案 + 锁定的事实卡片 → 输出: segments 数组

    Args:
      chapter: 章节方案 dict (从策划师输出)
      fact_cards: 本章锚定的事实卡片列表（_anchor_to_fact_cards 产出），文案师唯一事实依据
      prev_chapter_summary: 前一章摘要 (用于过渡)
      next_chapter_summary: 后一章摘要 (用于过渡)
      synopses: {ep: synopsis_dict} 剧情概要（补因果链，防文案师脑补"为什么"）
      topic_type: 选题类型（人物性格型/事件策略型/反差打脸型），决定剥层方向
      thesis: 选定论点 dict（核心锚，每段议论都必须指向它）
      argued_note: 增量快照（前面章节已论证过的论点步骤，禁止重复论证）
    """
    # 事件弧完整因果链集数（元数据：策划师产出，覆盖事件的前因后果）
    focus_eps = chapter.get('episodes_focus', [])
    if isinstance(focus_eps, int):
        focus_eps = [focus_eps]
    arc_eps = chapter.get('arc_episodes', [])
    if isinstance(arc_eps, int):
        arc_eps = [arc_eps]

    # 事实卡片上下文（LCAS 的 Core Anchor：唯一事实依据，物理杜绝编造）
    cards_context = _format_fact_cards(fact_cards)

    # 剧情概要上下文（补因果链：让文案师理解"为什么"，而非脑补）
    # 用「事件弧完整因果链 arc_eps」∪「焦点 focus_eps」的并集，确保前因不被漏掉。
    synopsis_context = ""
    if synopses:
        syn_parts = []
        eps_for_synopsis = sorted(set(arc_eps + focus_eps))
        for ep in eps_for_synopsis:
            if ep in synopses:
                syn_parts.append(f"第{ep}集概要: {to_text(synopses[ep])[:400]}")
        if syn_parts:
            synopsis_context = "\n\n★★ 剧情概要（因果链，写『为什么』时只能据此推断，不得凭记忆脑补）:\n" + "\n".join(syn_parts)

    # 过渡上下文
    transition_context = ""
    if prev_chapter_summary:
        transition_context += f"\n前一章摘要 (用于过渡衔接): {prev_chapter_summary}"
    if next_chapter_summary:
        transition_context += f"\n后一章摘要 (用于过渡衔接): {next_chapter_summary}"

    # 账号画像注入：文案师继承账号级画像（受众 + 价值主张）
    profile = _load_account_profile()
    audience_note = ""
    if profile.get("core_audience"):
        audience_note += f"〔账号受众〕{profile['core_audience']}。"
    if profile.get("audience_want"):
        audience_note += f"〔受众要什么〕{profile['audience_want']}。"
    if profile.get("topic_types"):
        audience_note += f"〔选题类型〕{'/'.join(profile['topic_types'])}。"
    if audience_note:
        audience_note = "★ ★ 账号画像（据此调整剥层方向）:\n  " + audience_note

    system = SCRIPT_WRITER_PROMPT.format(
        known_characters='、'.join(KNOWN_CHARACTERS),
        audience_note=audience_note,
        thesis_note=_format_thesis_note(thesis),
    )

    # 选题类型 → 剥层方向提示（元数据传递：制片选题的 type 传导到文案师）
    type_note = ""
    if topic_type:
        type_guide = {
            "人物性格型": "剥层聚焦「这个人的性格/心理动机」——他为什么是这种人",
            "事件策略型": "剥层聚焦「这件事的博弈逻辑」——他/她怎么破的局、用了什么招",
            "反差打脸型": "剥层聚焦「表象 vs 真相」——所有人都以为X，结果Y",
        }
        guide = type_guide.get(topic_type, "")
        if guide:
            type_note = f"\n\n★★ 选题类型：{topic_type}。{guide}。"

    user = (
        f"★★ 当前章节方案:\n{json.dumps(chapter, ensure_ascii=False, indent=2)}\n\n"
        f"★★ 事实卡片 (唯一事实依据):\n{cards_context}"
        f"{synopsis_context}"
        f"{type_note}"
        f"{transition_context}"
        f"{argued_note}"
        f"\n\n"
        f"请为本章撰写解说词。"
    )

    return _call_llm(system, user, temp=0.6, max_tokens=3000, label="script_writer")


# ═══════════════════════════════════════════════════════════════
# Agent 4: 审核师 — 剧情准确性 + 情绪曲线 + 节奏审核
# ═══════════════════════════════════════════════════════════════

def reviewer_agent(segments: list, scene_maps: dict = None,
                   target_duration: int = 480, thesis: dict = None) -> dict:
    """输入: 完整脚本 → 输出: 逻辑审核报告 + 改写建议

    审「逻辑断层 / 过度拔高 / 指代不清 / 重复金句 / 常识议论 / 为论点硬编的事实」。
    注入论点，让审核师能判断"这段议论是否贴论点、是否废话"。
    注入 scene_map 事实清单，让审核师能查证"narration 里的具体事实是否真在剧里"。
    """
    # 构建脚本预览（按段号 + narration 全文，让审核师能看到前后逻辑）
    script_preview_lines = []
    total_chars = 0
    for i, seg in enumerate(segments):
        narr = seg.get('narration_text', '')
        total_chars += len(narr)
        hl = seg.get('highlight_text', '')
        hl_str = f" 〔原声:{hl[:30]}〕" if hl else ""
        script_preview_lines.append(f"[S{i}] {narr}{hl_str}")

    est_duration = total_chars / 4  # 4字/秒
    script_preview = '\n'.join(script_preview_lines)

    # 事实清单：把 scene_map 的 event 拼成"剧中真实发生的事"列表，供审核师查证 narration 是否编造
    fact_context = ""
    if scene_maps:
        facts = []
        for ep, sm in sorted(scene_maps.items()):
            for s in sm:
                facts.append(f"EP{ep}·{s.get('time_range',['?','?'])[0]}s: {s.get('event','')}")
        if facts:
            fact_context = (
                "\n\n★★ 剧中真实事件清单（这是「唯一事实依据」，narration 里出现但这里查不到的具体动作/身份，就是编造）:\n"
                + "\n".join(facts)
            )

    system = REVIEWER_PROMPT

    thesis_note = _format_thesis_note(thesis)
    if thesis_note:
        thesis_note = f"{thesis_note}\n\n"

    user = (
        f"★★ 目标时长: {target_duration}秒\n"
        f"★★ 当前总字数: {total_chars}字, 预估配音时长: {est_duration:.0f}秒\n"
        f"{thesis_note}"
        f"★★ 完整脚本 ({len(segments)}段，请逐段检查前后逻辑):\n{script_preview}\n"
        f"{fact_context}\n\n"
        f"请找出逻辑断层、过度拔高、指代不清、重复金句、常识议论、为论点硬编事实的段落，并给出改写。"
    )

    return _call_llm(system, user, temp=0.3, max_tokens=4000, label="reviewer")


# 审核师/文案师偶发把「删除此段」「S4衔接S2」这类操作批注写进 narration_text，
# 污染成片文案。这里是防御性过滤：判成操作指令则跳过该 fix，保留原文（避免播出批注）。
_JUNK_OP_PATTERN = re.compile(
    r'删除|合并|衔接|此段|这段|本段|下段|上段|保留原|S\d|第\S*段'
)


def _is_junk_narration(text: str) -> bool:
    """判断 narration_text 是否为「操作批注」而非成文解说词。"""
    if not text:
        return False
    t = text.strip()
    # 短文本 + 含操作词 = 批注（正常解说词不会短到只有一句删除指令）
    if len(t) < 30 and _JUNK_OP_PATTERN.search(t):
        return True
    # 全角/半角括号开头且含操作词，也判脏
    if t[:1] in '（(' and _JUNK_OP_PATTERN.search(t):
        return True
    return False


def _norm_text(text: str) -> str:
    """归一化文本用于重复检测：去标点/空白，只留汉字。"""
    import re as _re
    return _re.sub(r'[^一-鿿]', '', text or '')


def apply_fixes(segments: list, review_result: dict) -> tuple:
    """应用审核修正 → (fixed_segments, fix_count)

    优先使用审核师在 fixed_segments 中提供的修正版本。
    防御（不靠 LLM 自觉）：
    1. 修正内容是"删除此段"这类批注 → 跳过，保留原文。
    2. 改写后的文本与脚本其他段落重复（归一化后相同/高度相似）→ 跳过，防止审核师改出重复段。
    """
    fixes = review_result.get('fixed_segments', [])
    if not fixes:
        return segments, 0

    fix_map = {}
    for f in fixes:
        idx = f.get('segment_index', -1)
        if 0 <= idx < len(segments):
            fix_map[idx] = f

    fixed = []
    applied = 0
    for i, seg in enumerate(segments):
        if i in fix_map:
            f = fix_map[i]
            seg = dict(seg)
            new_narr = f.get('narration_text', '')
            # 防御1：操作批注 → 跳过
            if new_narr and _is_junk_narration(new_narr):
                seg['note'] = (seg.get('note', '') + " | 审核建议删除(已跳过)").strip(' |')
            else:
                # 防御2：改写后与【已产出段落】重复 → 跳过
                is_dup = False
                if new_narr:
                    new_norm = _norm_text(new_narr)
                    # 用"已生成的 fixed 列表 + 当前 seg 之外的原始段落"比对
                    # （fixed 里已含前面段落的改写结果，能抓到"前一段刚改成同样文本"）
                    for other in fixed:
                        other_narr = (other.get('narration_text') or '').strip()
                        if other_narr:
                            other_norm = _norm_text(other_narr)
                            if new_norm == other_norm or (
                                len(new_norm) >= 30 and (new_norm in other_norm or other_norm in new_norm)
                            ):
                                is_dup = True
                                break
                    if not is_dup:
                        # 还要比对 i 之后的原始段落（它们还没进 fixed）
                        for j in range(i + 1, len(segments)):
                            other_narr = (segments[j].get('narration_text') or '').strip()
                            if other_narr:
                                other_norm = _norm_text(other_narr)
                                if new_norm == other_norm or (
                                    len(new_norm) >= 30 and (new_norm in other_norm or other_norm in new_norm)
                                ):
                                    is_dup = True
                                    break
                if is_dup:
                    seg['note'] = (seg.get('note', '') + " | 审核改写重复(已跳过)").strip(' |')
                else:
                    if new_narr:
                        seg['narration_text'] = new_narr
                    if f.get('scene_query'):
                        seg['scene_query'] = f['scene_query']
                    seg['note'] = (seg.get('note', '') + f" | 审核修正: {f.get('fix_reason', '')}").strip(' |')
                    applied += 1
        fixed.append(seg)

    return fixed, applied


# ═══════════════════════════════════════════════════════════════
# 编排器: 协调四个 Agent 完成完整流程
# ═══════════════════════════════════════════════════════════════

def run_drama_pipeline(
    project_dir: Path,
    topic: str,
    *,
    drama_name: str = "都挺好",
    focus_episodes: list[int] = None,
    target_duration: int = 480,
    topic_type: str = None,
    thesis: dict = None,
    story_map: dict = None,
    emit_progress=None,
) -> dict:
    """完整编剧流水线 — 五 Agent 协作生成解说脚本

    Args:
      project_dir: 项目数据目录
      topic: 用户选题 (如"苏明成人物线 8分钟解说")
      drama_name: 剧名
      focus_episodes: 关注的剧集范围 (可选，不指定则分析全部)
      target_duration: 目标时长 (秒)
      topic_type: 选题类型（人物性格型/事件策略型/反差打脸型）
      thesis: 选定论点 dict（人拍板的结果，含 thesis/device/why_not_common）
      story_map: 已产出的故事地图（两段式：论点阶段已跑过故事师，此处复用避免重跑）
      emit_progress: 进度回调 fn(step, msg, data=None)

    Returns:
      {"ok": True, "segments": [...], "cover": "...", "story_map": {...}, ...}
    """
    def progress(step, msg, data=None):
        if emit_progress:
            emit_progress(step, msg, data)

    # ── Phase 0 + 1: 故事师（读全 46 集，其 key_episodes 即选集答案）──
    # 优化（2026-08-13）：不再用独立的 _infer_episodes_from_topic_llm 反推，
    # 而是让故事师读全 46 集概要，从它的 character_arcs[].key_episodes 提取关键集。
    # 理由：故事师懂全局弧线，比逐集字段匹配反推精确（后者漏掉 EP45 弧线终点）。
    if story_map is not None:
        # 两段式：论点阶段已跑过故事师，复用传入的 story_map，不重跑
        progress("story_done",
            f"✅ 故事地图: 复用（两段式，{len(story_map.get('character_arcs', []))}个人物弧光）",
            {"story_map": story_map})
    else:
        if focus_episodes is None:
            progress("story", "📖 故事师: 通读全部剧情概要（其人物弧光 key_episodes 即选集）...")
        else:
            progress("story", f"📖 故事师: 通读剧情概要（指定集 {focus_episodes}）...")
        start = time.time()
        story_result = story_master_agent(project_dir, drama_name, focus_episodes)

        if not story_result.get('ok'):
            return {"ok": False, "error": f"故事师失败: {story_result.get('error', '?')}"}

        story_map = story_result['result']
        elapsed = time.time() - start
        char_count = len(story_map.get('character_arcs', []))
        topic_count = len(story_map.get('topic_suggestions', []))
        progress("story_done",
            f"✅ 故事地图: {char_count}个人物弧光 · {len(story_map.get('turning_points', []))}个转折点 · {topic_count}个选题 · {elapsed:.0f}s",
            {"story_map": story_map})

    # 深层 RAG 选集：未指定集时，从故事师的弧光 key_episodes 提取（复用其全局理解）
    if focus_episodes is None:
        focus_episodes = _extract_key_episodes_from_story_map(story_map, topic)
        if focus_episodes:
            progress("story", f"🔎 深层RAG: 从故事师弧光提取关键集 → {focus_episodes}")
        else:
            progress("story", "⚠️ 深层RAG: 未提取到关键集，回退全量 scene_map")

    # ── Phase 2: 策划师 ──
    progress("planning", "📐 策划师: 围绕论点设计事件链骨架...")
    start = time.time()
    plan_result = narrative_planner_agent(story_map, topic, target_duration, thesis=thesis)

    if not plan_result.get('ok'):
        return {"ok": False, "error": f"策划师失败: {plan_result.get('error', '?')}"}

    chapter_structure = plan_result['result']
    chapters = chapter_structure.get('chapters', [])
    elapsed = time.time() - start

    if not chapters:
        return {"ok": False, "error": "策划师未产出章节方案"}

    progress("planning_done",
        f"✅ 叙事方案: {chapter_structure.get('title', '?')} · {len(chapters)}章 · 目标{target_duration}s",
        {"chapter_structure": chapter_structure})

    # ── 准备 scene_map 数据 (供文案师和审核师共享) ──
    # 只加载用户指定剧集范围内的 scene_map — 不加载全量46集
    all_eps = set()
    for ch in chapters:
        eps = ch.get('episodes_focus', [])
        if isinstance(eps, int):
            eps = [eps]
        all_eps.update(eps)
    if focus_episodes:
        all_eps.update(focus_episodes)
    # 扩展邻近集 (±2集, 用于过渡)
    expanded_eps = set()
    for ep in all_eps:
        for e in range(max(1, ep-2), min(47, ep+3)):
            expanded_eps.add(e)
    scene_maps = _load_scene_maps(project_dir, sorted(expanded_eps))
    # 剧情概要（因果链）：文案师写"为什么"时据此推断，防脑补
    synopses = _load_all_synopses(project_dir, sorted(expanded_eps))
    # ASR 台词（供文案师选真实原剧台词 + Phase 4 锚定回填）
    asr_texts = _load_asr_text(project_dir, sorted(expanded_eps))

    # ── Phase 3: 文案师 (逐章写作) ──
    progress("writing", f"✍️ 文案师: 逐章写作解说词 (共{len(chapters)}章)...")
    all_segments = []
    chapter_summaries = []
    argued_roles = []   # 增量快照：已论证过的论点步骤（LCAS Dynamic Refreshing），防车轱辘话
    used_events = []    # 增量快照：已用过的剧情动作/场景，防"同一动作跨章重述"

    for i, chapter in enumerate(chapters):
        ch_title = chapter.get('title', f'第{i+1}章')
        progress("writing", f"  写作第{i+1}/{len(chapters)}章: {ch_title}...",
                 {"chapter": i+1, "total": len(chapters)})

        prev_summary = chapter_summaries[-1] if chapter_summaries else ""
        next_summary = ""  # 后续章节的标题作为轻量上下文

        # 增量快照：告诉文案师「前面章节已论证过这些论点步骤 + 已讲过这些剧情，不要再重复，要推进」
        argued_note = ""
        snapshot_parts = []
        if argued_roles:
            snapshot_parts.append(
                "已论证过的论点步骤（严禁重复论证）:\n" +
                "\n".join(f"  - 第{idx+1}章: {role}" for idx, role in enumerate(argued_roles))
            )
        if used_events:
            snapshot_parts.append(
                "已讲过的具体剧情（严禁再重述，本章直接推进，不要回头复述）:\n" +
                "\n".join(f"  - {ev}" for ev in used_events)
            )
        if snapshot_parts:
            argued_note = (
                "\n★★ 增量快照（前面章节已覆盖的内容，★ 严禁重复）:\n"
                + "\n".join(snapshot_parts)
            )

        # ── 事实卡片：把 scene_anchors 锚回 scene_map，产出锁定的唯一事实依据 ──
        fact_cards = _anchor_to_fact_cards(
            chapter.get('scene_anchors', []), scene_maps, asr_texts)
        if not fact_cards:
            progress("writing",
                f"  ⚠️ 第{i+1}章 scene_anchors 全部锚定失败（event 与 scene_map 不匹配），跳过")
            continue

        write_result = script_writer_agent(
            chapter, fact_cards,
            prev_chapter_summary=prev_summary,
            next_chapter_summary=next_summary,
            synopses=synopses,
            topic_type=topic_type,
            thesis=thesis,
            argued_note=argued_note,
        )

        if not write_result.get('ok'):
            progress("writing", f"  ⚠️ 第{i+1}章写作失败: {write_result.get('error', '?')}")
            continue

        chapter_segments = write_result['result'].get('segments', [])
        if not chapter_segments:
            progress("writing", f"  ⚠️ 第{i+1}章未产出有效段落")
            continue

        # 注：_verify_narration 事后校验已停用——事实卡片分离已从源头杜绝硬事实幻觉，
        # 该「人名+动词」校验频繁误报（如"扇耳光"比喻、"推开门"），边际价值为负。
        # 硬事实防线 = _anchor_to_fact_cards 的卡片隔离，而非事后粗粒度校验。

        # 注入章节元数据
        for seg in chapter_segments:
            seg['chapter_title'] = ch_title
            seg['chapter_idx'] = i
            seg['section_role'] = chapter.get('narrative_function', 'context')

        # 提取文案师产的 cover 字段
        if i == 0:
            first_cover = write_result['result'].get('cover', '')
            if first_cover:
                chapter_segments[0]['_cover'] = first_cover

        all_segments.extend(chapter_segments)
        chapter_summaries.append(f"[{ch_title}] {chapter.get('narrative_goal', '')[:60]}")
        # 增量快照更新：记录本章论证的论点步骤 + 用过的剧情动作
        thesis_role = chapter.get('thesis_role') or chapter.get('narrative_goal', '')
        if thesis_role:
            argued_roles.append(thesis_role)
        for card in fact_cards:
            ev = f"EP{card['ep']} {card['action']}"
            if ev not in used_events:
                used_events.append(ev)

        progress("writing_chapter_done",
            f"  ✅ 第{i+1}章 {ch_title}: {len(chapter_segments)}段",
            {"chapter": i+1, "segments": len(chapter_segments)})

        time.sleep(0.5)  # 避免 API 限流

    if not all_segments:
        return {"ok": False, "error": "文案师未产出任何有效章节"}

    # 统一分配 seg_id
    for i, seg in enumerate(all_segments):
        seg['seg_id'] = i

    total_chars = sum(len(s.get('narration_text', '')) for s in all_segments)
    est_duration = total_chars / 4
    progress("writing_done",
        f"✅ 文案完成: {len(all_segments)}段 · {total_chars}字 · 预估{est_duration:.0f}s",
        {"total_segments": len(all_segments), "total_chars": total_chars,
         "est_duration": round(est_duration, 1)})

    # ── Phase 4: 后处理 (校验 + 补漏 + episode_marker) ──
    progress("verify", "🔍 校验 scene_query + 程序提取原声台词...")

    # ── 原声台词程序化提取：从 scene_query 时间窗的 ASR 取真实台词 ──
    # 先场景后台词：文案师只选场景（scene_query），台词由程序从 ASR 取，杜绝编造。
    for seg in all_segments:
        narr = (seg.get('narration_text') or '').strip()
        hl = (seg.get('highlight_text') or '').strip()
        # 只处理原声段（narration 空），且当前 highlight 为空或疑似编造（一律重新取）
        if narr:
            continue
        sq = seg.get('scene_query') or {}
        ep = sq.get('episode')
        tr = sq.get('time_range')
        if not ep or not tr:
            continue
        picked = _pick_line_from_window(ep, tr, asr_texts)
        if picked:
            seg['highlight_text'] = picked['text']
            seg['highlight_ep'] = picked['ep']
            seg['highlight_start'] = picked['start']
            seg['highlight_end'] = picked['end']
        elif hl:
            # 时间窗内取不到真实台词，清空编造的
            seg['highlight_text'] = ''
            seg['highlight_unverified'] = True

    # 程序级验证：逐个 segment 检查 scene_query 是否匹配 scene_map
    verified = []
    fixed = 0
    for seg in all_segments:
        sq = seg.get('scene_query', {})
        if sq is None:
            sq = {}
            seg['scene_query'] = sq
        if not isinstance(sq, dict):
            sq = {}
            seg['scene_query'] = sq
        ep = sq.get('episode')
        tr = sq.get('time_range')

        # 填充 episode_marker 和 source_start/source_end (兼容前端显示)
        if ep and tr and isinstance(tr, list) and len(tr) == 2:
            seg['episode_marker'] = {
                "episode": ep,
                "approx_minute": tr[0] / 60.0,
                "raw": f"{ep}~{tr[0]//60:.0f}m{tr[0]%60:.0f}s",
            }
            seg['source_start'] = float(tr[0])
            seg['source_end'] = float(tr[1])
            seg['video_episode'] = ep
        else:
            seg['episode_marker'] = None
            seg['mode'] = 'C'

        if not ep:
            # 没有 scene_query — 自动转为 mode C
            seg['mode'] = 'C'
            verified.append(seg)
            continue

        sm_list = scene_maps.get(ep, [])
        if not sm_list:
            # scene_map 不存在 — 降级为 mode C
            sq['episode'] = None
            sq['time_range'] = None
            sq['event'] = sq.get('event', '') + ' (scene_map缺失)'
            seg['mode'] = 'C'
            fixed += 1
            verified.append(seg)
            continue

        # 精确匹配 time_range
        matched = [s for s in sm_list if s['time_range'] == tr]
        if matched:
            # time_range 有效 → 模式归一化 A。event/mood/characters 不再用 scene_map 覆盖，
            # 它们是文案师的创作快照（可选），下游只用 episode+source_start/end。
            seg['mode'] = 'A'
            verified.append(seg)
        else:
            # 找最近匹配
            closest = min(sm_list, key=lambda s: abs(s['time_range'][0] - tr[0]))
            gap = abs(closest['time_range'][0] - tr[0])
            if gap <= 15:
                # 修正 time_range（保证 source_start/end 指向真实可截取的原剧区间）
                sq['time_range'] = closest['time_range']
                seg['source_start'] = float(closest['time_range'][0])
                seg['source_end'] = float(closest['time_range'][1])
                seg['episode_marker'] = {
                    "episode": ep,
                    "approx_minute": closest['time_range'][0] / 60.0,
                    "raw": f"{ep}~{closest['time_range'][0]//60:.0f}m{closest['time_range'][0]%60:.0f}s",
                }
                seg['mode'] = 'A'  # 归一化：有有效锚定即 A
                fixed += 1
                verified.append(seg)
            else:
                # 找不到匹配 — 降级
                sq['episode'] = None
                sq['time_range'] = None
                sq['event'] = sq.get('event', '') + f' (无匹配,最近:EP{ep}{closest["time_range"]})'
                seg['mode'] = 'C'
                fixed += 1
                verified.append(seg)

    progress("verify_done",
        f"✅ 校验完成: {len(all_segments)}段, 修正{fixed}处, 0个LLM审核",
        {"verified": len(all_segments), "fixed": fixed})

    # ── Phase 4.5: 逻辑审核师（Self-Reflection）──
    # 文案师一次成稿会有"逻辑断层/过度拔高"（自回归生成无法自我监控）。
    # 审核师事后整体审（含逻辑、重复金句、硬事实幻觉），【只报问题不负责改写】，
    # 问题清单交给前端展示，由人工决定改不改（避免 LLM 过度改写破坏成稿质量）。
    progress("review", "🔍 逻辑审核师: 整体审查逻辑/金句/事实编造...")
    review_start = time.time()
    review_result = reviewer_agent(all_segments, scene_maps=scene_maps,
                                   target_duration=target_duration, thesis=thesis)
    review_elapsed = time.time() - review_start

    review_verdict = "pass"
    review_issues = []
    fixed_by_review = 0
    if review_result.get('ok'):
        review_data = review_result['result']
        review_verdict = review_data.get('verdict', 'pass')
        review_issues = review_data.get('issues', [])
        # 只报不改：不 apply_fixes，issues 原样传给前端展示
    else:
        progress("review", f"⚠️ 审核师不可用: {review_result.get('error', '?')[:80]}")

    progress("review_done",
        f"✅ 逻辑审核: {review_verdict} · 问题{len(review_issues)}处 · 耗时{review_elapsed:.0f}s",
        {"verdict": review_verdict, "issues": len(review_issues)})

    # ── 提取 cover（封面钩子 — 由文案师写） ──
    cover = ''
    # 文案师输出的 cover 字段
    if all_segments:
        first = all_segments[0]
        # 优先用文案师指定的 cover，其次用 narration_text 的前2句
        cover = first.pop('_cover', '')
        if not cover:
            narr = first.get('narration_text', '')
            # 取前两句话作为封面钩子
            sentences = narr.replace('？','。').replace('！','。').split('。')
            cover = '。'.join(sentences[:2]) + '。' if len(sentences) > 1 else narr[:40]
            cover = cover[:60]  # 截断到60字
    if not cover:
        cover = chapter_structure.get('title', '')

    # ── 组装最终输出 ──
    # episode_marker 已在 Phase 4 中填充，这里做兜底

    return {
        "ok": True,
        "pipeline": "drama-agent-v1",
        "topic": topic,
        "cover": cover,
        "story_map": story_map,
        "chapter_structure": chapter_structure,
        "thesis": thesis,
        "segments": all_segments,
        "total": len(all_segments),
        "total_chars": total_chars,
        "review": {"verdict": review_verdict, "issues": review_issues, "fixed": fixed_by_review},
        "review_verdict": review_verdict,
        "review_issues": review_issues,
        "time_estimate": {
            "target": target_duration,
            "total_chars": total_chars,
            "estimated_sec": round(est_duration, 1),
            "estimated_min": f"{est_duration/60:.1f}分钟",
            "status": "ok" if abs(est_duration - target_duration) < target_duration * 0.4 else (
                "over" if est_duration > target_duration else "under"),
        },
    }
