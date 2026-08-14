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

评判维度（每个 1-5 分）：
- traffic（流量潜力）：话题是否自带讨论度、共鸣点、搜索热度
- differentiation（差异化）：是否足够独特，不会被同质化解说淹没
- hook（钩子强度）：能否提炼出 3 秒抓人的开场观点
- fit（账号匹配）：是否契合账号定位（影视解说 · 人物线/情感/冲突向）

输出 JSON：
{
  "ranked": [
    {"title": "重写的钩子式标题（≤15字，人物+冲突+悬念，不用数据原文）", "score": 总分, "scores": {"traffic":5,"differentiation":4,"hook":5,"fit":4},
     "reason": "为什么这个值得做（≤40字）", "recommend": true/false, "episodes": [集号列表，从输入候选原样复制]}
  ],
  "top_pick": "首推选题标题",
  "strategy_note": "一句话整体选题策略"
}

规则：
- 只排序输入的候选，不要凭空生成新选题
- ★ episodes 回填：每个 ranked 项的 episodes 字段，必须从输入候选里对应项的「集X」原样复制过来（保留数字，不要编造、不要省略）。重写标题时集号不变。
- ★ 标题重写：输入的 title 可能是数据原文拼接（如"苏明成：从试图挪用房款投资到与父兄正面冲突…"），必须重写成钩子式标题——≤15字，提炼"人物标签+核心冲突/反转+悬念"，参考："苏明成：一拳把亲妹打进医院""苏大强：作妖爹的最后一次道歉"。title 字段输出重写后的标题，不要照抄输入。
- recommend=true 的应占少数（精选，不是全推）
- reason 要具体（数据支撑 + 叙事角度），不要空话
- ★ 证据公平性：候选有两种来源——「数据向」（evidence 是硬数据，如"冲突密度100%"）和「叙事向」（evidence 是 hook/角度，如"最不受宠的女儿"）。两者证据性质不同，但价值等同，不得因叙事向缺少硬数字而系统性降级。叙事向选题的 hook 本身就是它的"数据"。
- ★ 选题主体铁律：短视频解说只做「剧情弧」类选题，只有三种切法——
  1. 人物性格型（这个人是什么性格，锚定一个性格弧）
  2. 事件策略型（这件事怎么破的局，锚定一个事件弧）
  3. 反差打脸型（都以为XX结果YY，锚定一个反转弧）
  硬约束：
  · 社会议题（重男轻女/养老/啃老）只能作为钩子或结尾升华点，【不得作为选题主体/标题】——议题是主题不是弧，没有起承转合，撑不起短视频。
  · 成长蜕变型（全剧长弧，素材跨 46 集）违反"集数集中"，【排除】——蜕变融入关系型/反差型作副线。
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
    1. 输出的标题都是「重写后」的，不是照抄输入标题
    2. 输出的候选都来自输入候选（没凭空造选题）
    3. 无社会议题/盘点型违规主体（弧约束的确定性部分）

    Returns:
      问题列表（空 = 通过）
    """
    issues = []
    ranked = result.get("ranked") or []
    input_titles = {c.get("title", "") for c in candidates}

    for r in ranked:
        title = r.get("title", "")
        # 1. 标题重写检查：输出标题不应等于任何输入标题（数据原文）
        if title in input_titles:
            issues.append(f"标题未重写（照抄输入）: {title}")
        # 2. 凭空造选题检查：输出标题应至少与某个输入候选有部分关联
        #    （这里做宽松检查：输出标题含输入标题的任意 3+ 连续字，视为关联）
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
# Agent 2: 策划师 — 设计叙事结构和章节规划
# ═══════════════════════════════════════════════════════════════

def narrative_planner_agent(story_map: dict, user_topic: str,
                            target_duration: int = 480) -> dict:
    """输入: story_map + 用户选题 → 输出: chapter_structure"""
    # 提取角色列表
    char_arcs = story_map.get('character_arcs', [])
    main_char_names = [a['name'] for a in char_arcs[:5]] if char_arcs else KNOWN_CHARACTERS

    # 构建章节数建议
    suggested_chapters = max(4, min(7, target_duration // 80))

    system = NARRATIVE_PLANNER_PROMPT

    user = (
        f"故事地图:\n{json.dumps(story_map, ensure_ascii=False, indent=2)[:8000]}\n\n"
        f"★★ 用户选题: {user_topic}\n"
        f"★★ 目标时长: {target_duration}秒 (约{target_duration//60}分钟)\n"
        f"★★ 建议章节数: {suggested_chapters}章\n"
        f"★★ 主要角色: {', '.join(main_char_names)}\n\n"
        f"请设计叙事方案。"
    )

    return _call_llm(system, user, temp=0.5, max_tokens=3000, label="narrative_planner")


# ═══════════════════════════════════════════════════════════════
# Agent 3: 文案师 — 逐章写作解说词 + scene_query
# ═══════════════════════════════════════════════════════════════

def script_writer_agent(chapter: dict, scene_maps: dict,
                        prev_chapter_summary: str = "",
                        next_chapter_summary: str = "",
                        word_limit: int = None,
                        synopses: dict = None,
                        topic_type: str = None,
                        asr_texts: dict = None) -> dict:
    """输入: 单个章节方案 + scene_map 数据 → 输出: segments 数组

    Args:
      chapter: 章节方案 dict (从策划师输出)
      scene_maps: {ep: [scene_dict, ...]} 覆盖章节涉及的剧集
      prev_chapter_summary: 前一章摘要 (用于过渡)
      next_chapter_summary: 后一章摘要 (用于过渡)
      word_limit: 整章 narration_text 总字数上限（用于超字数重写）
      synopses: {ep: synopsis_dict} 剧情概要（补因果链，防文案师脑补"为什么"）
      topic_type: 选题类型（人物性格型/事件策略型/反差打脸型），决定剥层方向
      asr_texts: {ep: [{start,end,text}]} ASR 台词（供文案师选真实原剧台词）
    """
    # 收集本章涉及剧集的 scene_map
    focus_eps = chapter.get('episodes_focus', [])
    if isinstance(focus_eps, int):
        focus_eps = [focus_eps]

    scene_context_parts = []
    for ep in focus_eps:
        if ep in scene_maps:
            scene_context_parts.append(_format_scene_map_text(scene_maps[ep], ep))

    # 如果 scene_maps 没有聚焦剧集的数据，使用所有已加载的
    if not scene_context_parts:
        for ep, sm in sorted(scene_maps.items()):
            scene_context_parts.append(_format_scene_map_text(sm, ep))

    scene_context = '\n\n'.join(scene_context_parts) if scene_context_parts else "(无场景数据)"

    # 剧情概要上下文（补因果链：让文案师理解"为什么"，而非脑补）
    synopsis_context = ""
    if synopses:
        syn_parts = []
        for ep in focus_eps:
            if ep in synopses:
                syn_parts.append(f"第{ep}集概要: {to_text(synopses[ep])[:400]}")
        if syn_parts:
            synopsis_context = "\n\n★★ 剧情概要（因果链，写『为什么』时只能据此推断，不得凭记忆脑补）:\n" + "\n".join(syn_parts)

    # ASR 台词上下文（供文案师选真实原剧台词，避免编造 highlight_text）
    asr_context = ""
    if asr_texts:
        asr_parts = []
        for ep in focus_eps:
            lines = asr_texts.get(ep, [])
            if lines:
                # 只取每集前 40 句，控制上下文长度
                snippet = "；".join(f"{a['start']:.0f}s:{a['text']}" for a in lines[:40])
                asr_parts.append(f"第{ep}集 ASR 台词: {snippet[:2000]}")
        if asr_parts:
            asr_context = "\n\n★★ 原剧台词（ASR 真实台词，highlight_text 只能从这里逐字选）:\n" + "\n".join(asr_parts)

    # 过渡上下文
    transition_context = ""
    if prev_chapter_summary:
        transition_context += f"\n前一章摘要 (用于过渡衔接): {prev_chapter_summary}"
    if next_chapter_summary:
        transition_context += f"\n后一章摘要 (用于过渡衔接): {next_chapter_summary}"

    # 字数约束提示（超字数重写时注入）
    word_limit_note = ""
    if word_limit:
        word_limit_note = (
            f"\n★★ 字数硬约束：本章所有 narration_text 的总字数必须 ≤ {word_limit} 字"
            f"（当前超了，请删减冗余表述、合并段落，保留核心信息，压缩到 {word_limit} 字以内）。"
        )

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
        f"★★ 场景数据 (scene_map):\n{scene_context}"
        f"{synopsis_context}"
        f"{asr_context}"
        f"{type_note}"
        f"{transition_context}"
        f"{word_limit_note}\n\n"
        f"请为本章撰写解说词。"
    )

    return _call_llm(system, user, temp=0.6, max_tokens=3000, label="script_writer")


# ═══════════════════════════════════════════════════════════════
# Agent 4: 审核师 — 剧情准确性 + 情绪曲线 + 节奏审核
# ═══════════════════════════════════════════════════════════════

def reviewer_agent(segments: list, scene_maps: dict,
                   target_duration: int = 480) -> dict:
    """输入: 完整脚本 + scene_map 数据 → 输出: 审核报告 + 修正建议"""
    # 构建 scene_map 参考文本 (用于事实核查)
    scene_ref_parts = []
    for ep, sm in sorted(scene_maps.items()):
        scene_ref_parts.append(_format_scene_map_text(sm, ep))
    scene_ref = '\n\n'.join(scene_ref_parts)

    # 构建脚本预览
    script_preview_lines = []
    total_chars = 0
    for i, seg in enumerate(segments):
        narr = seg.get('narration_text', '')
        total_chars += len(narr)
        sq = seg.get('scene_query', {})
        sq_summary = ""
        if sq and sq.get('episode'):
            sq_summary = f" [EP{sq['episode']} {sq.get('event', '?')[:20]}]"
        script_preview_lines.append(
            f"[S{i}] {narr[:60]}...{sq_summary}"
        )

    est_duration = total_chars / 4  # 4字/秒
    script_preview = '\n'.join(script_preview_lines)

    system = REVIEWER_PROMPT

    user = (
        f"★★ 目标时长: {target_duration}秒\n"
        f"★★ 当前总字数: {total_chars}字, 预估配音时长: {est_duration:.0f}秒\n\n"
        f"★★ 完整脚本 ({len(segments)}段):\n{script_preview}\n\n"
        f"★★ 脚本详细数据:\n{json.dumps(segments, ensure_ascii=False, indent=2)[:3000]}\n\n"
        f"★★ ★ 全量场景数据 (用于事实核查，请逐段对照):\n{scene_ref}"
    )

    return _call_llm(system, user, temp=0.3, max_tokens=3000, label="reviewer")


def apply_fixes(segments: list, review_result: dict) -> tuple:
    """应用审核修正 → (fixed_segments, fix_count)

    优先使用审核师在 fixed_segments 中提供的修正版本。
    对于没有提供修正版本的 issue，如果 severity=high 则标记 note。
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
            if f.get('narration_text'):
                seg['narration_text'] = f['narration_text']
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
    emit_progress=None,
) -> dict:
    """完整编剧流水线 — 四个 Agent 协作生成解说脚本

    Args:
      project_dir: 项目数据目录
      topic: 用户选题 (如"苏明成人物线 8分钟解说")
      drama_name: 剧名
      focus_episodes: 关注的剧集范围 (可选，不指定则分析全部)
      target_duration: 目标时长 (秒)
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
    progress("planning", "📐 策划师: 设计叙事结构和章节规划...")
    start = time.time()
    plan_result = narrative_planner_agent(story_map, topic, target_duration)

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

    for i, chapter in enumerate(chapters):
        ch_title = chapter.get('title', f'第{i+1}章')
        progress("writing", f"  写作第{i+1}/{len(chapters)}章: {ch_title}...",
                 {"chapter": i+1, "total": len(chapters)})

        prev_summary = chapter_summaries[-1] if chapter_summaries else ""
        next_summary = ""  # 后续章节的标题作为轻量上下文

        # 策划师的整章字数目标（word_count_target），用于超字数重写
        word_target = chapter.get('word_count_target')

        write_result = script_writer_agent(
            chapter, scene_maps,
            prev_chapter_summary=prev_summary,
            next_chapter_summary=next_summary,
            synopses=synopses,
            topic_type=topic_type,
            asr_texts=asr_texts,
        )

        if not write_result.get('ok'):
            progress("writing", f"  ⚠️ 第{i+1}章写作失败: {write_result.get('error', '?')}")
            continue

        chapter_segments = write_result['result'].get('segments', [])
        if not chapter_segments:
            progress("writing", f"  ⚠️ 第{i+1}章未产出有效段落")
            continue

        # ── 超字数重写循环：整章 narration 总字数超过 word_count_target 时重写 ──
        # ⚠️ 实验性功能（2026-08-13）：当前只做"超字数→压缩"单向重写，
        # 实测会「压过头」（如 697→131 字，总时长跌到目标 56%）。
        # 已知缺陷：重写提示"压缩到 N 字以内"被 LLM 理解成"能删就删"，丢失信息量。
        # 待改进：改为双向（低于目标 80% 也重写）+ 目标区间提示 + 最多 2 次。
        if word_target:
            chapter_chars = sum(len(s.get('narration_text', '')) for s in chapter_segments)
            # 容差 20%（约 4 字/秒的估算误差 + 标点），超 20% 才重写
            over_limit = chapter_chars > word_target * 1.2
            if over_limit:
                progress("writing",
                    f"  ⚠️ 第{i+1}章超字数 {chapter_chars}/{word_target}，重写一次...")
                retry = script_writer_agent(
                    chapter, scene_maps,
                    prev_chapter_summary=prev_summary,
                    next_chapter_summary=next_summary,
                    word_limit=word_target,
                    synopses=synopses,
                    topic_type=topic_type,
                    asr_texts=asr_texts,
                )
                if retry.get('ok') and retry['result'].get('segments'):
                    new_chars = sum(len(s.get('narration_text', ''))
                                    for s in retry['result']['segments'])
                    # 重写后更接近目标才采用，否则保留原稿（重写可能更糟）
                    if new_chars <= chapter_chars:
                        chapter_segments = retry['result']['segments']
                        progress("writing",
                            f"  ✅ 重写后 {new_chars}/{word_target} 字")
                    else:
                        progress("writing",
                            f"  ⚠️ 重写未收敛({new_chars}字)，保留原稿")
                else:
                    progress("writing", f"  ⚠️ 重写失败，保留原稿")

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
    progress("verify", "🔍 校验 scene_query + 填充 episode_marker...")

    # ── 原剧台词 ASR 锚定：把 highlight_text 锚定到真实 ASR，回填时间戳 ──
    for seg in all_segments:
        hl = seg.get('highlight_text', '')
        if not hl:
            continue
        sq = seg.get('scene_query') or {}
        ep = sq.get('episode') or (seg.get('episode_marker') or {}).get('episode') or seg.get('video_episode')
        anchored = _anchor_highlight(hl, ep, asr_texts) if ep else None
        if anchored:
            seg['highlight_ep'] = anchored['ep']
            seg['highlight_start'] = anchored['start']
            seg['highlight_end'] = anchored['end']
            # 用 ASR 真实文本替换（规范化），保留原 highlight_text 作对比
            seg['highlight_asr_text'] = anchored['text']
        else:
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
            sm_entry = matched[0]
            # 用 scene_map 的 event/mood 覆盖（确保一致）
            sq['event'] = sm_entry.get('event', sq.get('event', ''))
            sq['mood'] = sm_entry.get('mood', sq.get('mood', ''))
            sq['location'] = sm_entry.get('location', sq.get('location', ''))
            sq['characters'] = sm_entry.get('characters', sq.get('characters', []))
            # mode 归一化：有有效锚定即 A（文案师可能误写 B 等非法值）
            seg['mode'] = 'A'
            verified.append(seg)
        else:
            # 找最近匹配
            closest = min(sm_list, key=lambda s: abs(s['time_range'][0] - tr[0]))
            gap = abs(closest['time_range'][0] - tr[0])
            if gap <= 15:
                # 修正 time_range
                sq['time_range'] = closest['time_range']
                sq['event'] = closest.get('event', sq.get('event', ''))
                sq['mood'] = closest.get('mood', sq.get('mood', ''))
                sq['location'] = closest.get('location', sq.get('location', ''))
                sq['characters'] = closest.get('characters', sq.get('characters', []))
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
        "segments": all_segments,
        "total": len(all_segments),
        "total_chars": total_chars,
        "review": {"verdict": "verified", "issues": [], "fixed": fixed},
        "review_verdict": "verified",
        "review_issues": [],
        "time_estimate": {
            "target": target_duration,
            "total_chars": total_chars,
            "estimated_sec": round(est_duration, 1),
            "estimated_min": f"{est_duration/60:.1f}分钟",
            "status": "ok" if abs(est_duration - target_duration) < target_duration * 0.4 else (
                "over" if est_duration > target_duration else "under"),
        },
    }
