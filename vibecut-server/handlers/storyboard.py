"""分镜台 handler — 导演Agent + 分镜推荐 + 口播分析

POST /storyboard_suggest   → storyboard_suggest()
POST /script/analyze_transcript   → analyze_transcript()
POST /script/generate_from_outline → generate_from_outline()
"""

import json
import os
import re
import time
from pathlib import Path

from config import PROJECT_DIR
from lib.llm import call_moonshot, call_moonshot_json, call_deepseek_json
from lib.vlm_cache import load as load_vlm_cache, get_char_counts
from lib.synopsis import load_synopsis, to_text
from lib.storyboard_match import match_shot_query
from handlers.search import search, _asr_first_search
from handlers.prompts.director import DIRECTOR_PROMPT


# ── POST /storyboard_suggest ──

def storyboard_suggest(narration: str, segment_context: dict = None, cover: str = "",
                       num: int = 3, prev_highlight: str = "", next_highlight: str = "",
                       focus_episodes: list = []) -> dict:
    """分镜推荐 v8 — PRIMARY+SECONDARY主辅镜头"""
    if not narration or not narration.strip():
        return {"suggestions": [], "shots": []}

    shots = []
    try:
        result = _director_agent(narration, segment_context, cover, num,
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


# ── 导演Agent ──

def _director_agent(narration: str, segment_context: dict = None, cover: str = "",
                    num_shots: int = 3, focus_episodes: list = []) -> dict:
    """导演Agent v8 — 叙事节拍拆解 + 主辅镜头(PRIMARY+SECONDARY)"""
    if not narration or not narration.strip():
        return {"shots": []}

    _ = load_vlm_cache()
    char_counts = get_char_counts()
    known = sorted(char_counts.keys(), key=lambda c: -char_counts[c])
    known_str = ", ".join(f"{c}({char_counts[c]}场)" for c in known)

    # v8.4: 三层剧集权重
    focus_eps_list = list(focus_episodes) if focus_episodes else []
    focus_eps = set(focus_eps_list)
    bridge_eps = set()
    if focus_eps_list:
        if len(focus_eps_list) >= 2:
            bridge_eps = {focus_eps_list[0], focus_eps_list[1]}
            print(f"[director] 🎯 承上启下: EP{focus_eps_list[0]}↔EP{focus_eps_list[1]} (权重+15)")
        print(f"[director]   标的集: {focus_eps_list} (权重+5)")
        synopsis_text = ""
        for ep in focus_eps_list:
            syn = load_synopsis(PROJECT_DIR, ep)
            text = to_text(syn)
            if text:
                synopsis_text += f"\n★ EP{ep} 剧情概要: {text}\n"
                print(f"[director]   📖 EP{ep} 概要 ({len(text)}字)")

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

    # 人物交叉校验 — cover 中的人物是决定性线索
    cover_chars = [c for c in sorted(char_counts.keys(), key=lambda x: -char_counts[x])
                   if c in (cover or '')]
    if cover_chars:
        definitive = cover_chars[0]
        if main_char and main_char != definitive:
            print(f"[director] ⚠️ LLM推断 {main_char}, 但封面明确是 {definitive}, 修正")
        elif not main_char:
            print(f"[director] 📌 封面人物 {definitive} 确定为主角")
        main_char = definitive
        def _fix_chars(spec):
            chars = spec.get("characters", [])
            spec["characters"] = [definitive if ch != definitive and ch in char_counts else ch for ch in chars]
            if definitive not in spec["characters"]:
                spec["characters"] = [definitive] + spec["characters"][:1]
        for shot_entry in shots_spec:
            if "primary" in shot_entry:
                _fix_chars(shot_entry["primary"])
                for sec in shot_entry.get("secondary", []):
                    _fix_chars(sec)

    if main_char and main_char not in char_counts:
        print(f"[director] ⚠️ 主角 {main_char} 不在已知角色中!")
        main_char = ""

    if not shots_spec:
        return {"shots": [], "fallback": True, "error": "LLM未返回有效分镜"}

    # ── 节拍分析 ──
    beats = data.get("beats", [])
    n_visual = sum(1 for b in beats if b.get("has_visual"))
    n_context = sum(1 for b in beats if b.get("type") == "context")
    print(f"[director] 📐 叙事分析: {len(beats)}个节拍 ({n_visual}画面化, {n_context}解说留白) → {len(shots_spec)}组主镜")

    # ── matching ──
    result_shots = []
    used_scene_keys = set()
    for i, shot_entry in enumerate(shots_spec):
        primary_spec = shot_entry.get("primary", shot_entry)
        secondary_specs = shot_entry.get("secondary", [])
        beat_idx = shot_entry.get("beat_index", i)
        technique = shot_entry.get("director_technique", "")

        # PRIMARY
        pri_focus = set(focus_eps) if focus_eps else set()
        bridge_layer = [(15, bridge_eps)] if bridge_eps else []
        focus_layer = [(5, pri_focus)] if pri_focus else []
        neighbor_eps = set()
        if pri_focus:
            for ep in list(pri_focus):
                for d in [-3, -2, -1, 1, 2, 3]:
                    n = ep + d
                    if 1 <= n <= 46:
                        neighbor_eps.add(n)
        neighbor_layer = [(2, neighbor_eps)] if neighbor_eps else []
        layered_focus = bridge_layer + focus_layer + neighbor_layer

        pri_cands = match_shot_query(primary_spec, num=5, used_scene_keys=used_scene_keys,
                                     main_char=main_char, focus_eps=layered_focus if layered_focus else None)
        relaxed_used = False
        if not pri_cands:
            relaxed = {**primary_spec, "shot_size": "", "location_hint": ""}
            pri_cands = match_shot_query(relaxed, num=5, used_scene_keys=used_scene_keys,
                                         main_char=main_char, focus_eps=layered_focus if layered_focus else None)
            relaxed_used = True

        # PRIMARY低分保护
        if pri_cands and pri_cands[0].get("match_score", 0) < 35 and pri_focus:
            expanded_focus = set(pri_focus)
            for ep in list(pri_focus):
                for d in [-5, -4, -3, -2, -1, 1, 2, 3, 4, 5]:
                    n = ep + d
                    if 1 <= n <= 46:
                        expanded_focus.add(n)
            expanded_cands = match_shot_query(primary_spec, num=5, used_scene_keys=used_scene_keys,
                                              main_char=main_char, focus_eps=expanded_focus)
            if expanded_cands and expanded_cands[0].get("match_score", 0) > pri_cands[0].get("match_score", 0) + 5:
                print(f"[director]   ⚡ 标的内低分(score={pri_cands[0]['match_score']})→扩展±5集, "
                      f"EP{expanded_cands[0]['ep']} score={expanded_cands[0]['match_score']}")
                pri_cands = expanded_cands
                relaxed_used = True

        global_fallback = False
        if not pri_cands:
            pri_cands = match_shot_query(primary_spec, num=5, used_scene_keys=used_scene_keys,
                                         main_char=main_char)
            global_fallback = True

        if pri_cands and primary_spec.get("priority", "KEY") == "KEY":
            used_scene_keys.add(f"{pri_cands[0]['ep']}_{pri_cands[0]['scene_id']}")

        purp = primary_spec.get("purpose", "")[:15]
        print(f"[director] 拍{i+1} PRIMARY ({purp}) → "
              f"EP{pri_cands[0]['ep']} [{pri_cands[0]['start']:.0f}s] "
              f"(score={pri_cands[0]['match_score']})" if pri_cands else f"[director] 拍{i+1} PRIMARY ({purp}) → 无匹配")

        # ── SECONDARY ──
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
                            if 1 <= n <= 46:
                                sec_focus.add(n)

            sec_cands = match_shot_query(sec_spec, num=3, used_scene_keys=set(),
                                         main_char=main_char if sec_role != "CONTRAST" else "",
                                         focus_eps=sec_focus)
            if sec_cands:
                print(f"[director]   +{sec_role} ({sec_spec.get('purpose','')[:12]}) → EP{sec_cands[0]['ep']} "
                      f"(score={sec_cands[0]['match_score']})")

            sec_results.append({
                "purpose": sec_spec.get("purpose", ""),
                "shot_role": sec_role,
                "query": sec_spec,
                "candidates": _make_candidates(sec_cands),
            })

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

    # ── reasoning summary ──
    reasoning = _build_reasoning(beats, focus_eps, bridge_eps, result_shots)

    return {"shots": result_shots, "narration": narration, "main_char": main_char,
            "beats": beats, "focus_eps": sorted(focus_eps), "reasoning": reasoning}


# ── Fallback (v3) ──

def _fallback_storyboard_suggest(narration: str, segment_context: dict = None, cover: str = "", num: int = 3) -> list:
    """分镜推荐 v3 — 分层结构化匹配: scene_map人物过滤 + VLM描述语义评分 + ASR时间锚定"""
    if not narration or not narration.strip():
        return []

    from lib.vlm_cache import KNOWN_CHARACTERS
    from handlers.search import _semantic_search

    sources_dir = PROJECT_DIR / "sources"
    context_text = (cover or '') + ' ' + narration
    if segment_context:
        context_text += ' ' + ' '.join(segment_context.get("sentences", []))
    target_chars = {name for name in KNOWN_CHARACTERS if name in context_text}

    # 用共享 VLM 缓存代替独立遍历
    cache = load_vlm_cache()
    matches = []
    for ep, ep_data in cache.items():
        for idx, s in ep_data.items():
            seg_chars = set(s.get('characters', []))
            if target_chars and not (seg_chars & target_chars):
                continue
            match = {
                'ep': ep, 'scene_id': idx,
                'start': s['start'], 'end': s['end'],
                'location': s['location'],
                'chars': list(seg_chars),
                'event': s['event'],
                'vlm_desc': s['visual_summary'],
            }
            if s.get('shot_size'): match['shot_size'] = s['shot_size']
            if s.get('composition'): match['composition'] = s['composition']
            if s.get('emotional_tone'): match['emotional_tone'] = s['emotional_tone']
            if s.get('intensity'): match['intensity'] = s['intensity']
            if s.get('lighting'): match['lighting'] = s['lighting']
            if s.get('actions'): match['actions'] = s['actions']
            matches.append(match)

    # 语义评分 (同原逻辑)
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
    active_cats = {}
    for cat, kws in KW_MAP.items():
        hits = sum(1 for kw in kws if kw in all_text)
        if hits:
            active_cats[cat] = hits

    scored = []
    for m in matches:
        score = 0
        desc = m['vlm_desc'] + ' ' + m['event'] + ' ' + m['location']
        if target_chars and set(m['chars']) & target_chars:
            score += 15
        elif target_chars:
            score -= 5
        for cat, hits in active_cats.items():
            for kw in KW_MAP[cat]:
                if kw in desc:
                    score += 1.5
        for cat, kws in KW_MAP.items():
            score += sum(0.3 for kw in kws if kw in desc)
        for loc_kw in ['办公室','客厅','餐厅','医院','派出所','机场','家中']:
            if loc_kw in all_text and loc_kw in m['location']:
                score += 2
        scored.append((score, m))
    scored.sort(key=lambda x: -x[0])

    top20 = []
    seen = set()
    for score, m in scored:
        key = f"{m['ep']}_{m['scene_id']}"
        if key in seen: continue
        seen.add(key)
        top20.append((score, m))
        if len(top20) >= 20: break

    # BGE 轻量重排
    if len(top20) > num:
        try:
            bge_results = _semantic_search(narration, limit=50)
            bge_rank = {}
            for rank, r in enumerate(bge_results):
                key = f"{r.get('ep',0)}_{(r.get('start',0)//60)*60}"
                if key not in bge_rank:
                    bge_rank[key] = rank
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

    seen2 = set()
    results = []
    for score, m in top20:
        key = f"{m['ep']}_{m['scene_id']}"
        if key in seen2: continue
        seen2.add(key)

        desc = m['vlm_desc'] or f"{m['location']}。人物: {', '.join(m['chars'])}。{m['event']}"
        time_info = f" [{m['start']:.0f}s-{m['end']:.0f}s]"
        entry = f"EP{m['ep']}{time_info} {desc[:100]}"
        results.append(entry)
        if len(results) >= num * 2:
            break

    # LLM 精排
    if results and len(results) > num:
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

    return results[:num]


# ── helpers ──

def _make_candidates(clist):
    if not clist: return []
    return [{"ep": c["ep"], "start": c["start"], "end": c["end"],
             "visual_summary": c["visual_summary"][:120],
             "shot_size": c["shot_size"], "emotional_tone": c["emotional_tone"],
             "intensity": c["intensity"], "location": c["location"],
             "characters": c["characters"], "match_score": c["match_score"]}
            for c in clist]


def _build_reasoning(beats, focus_eps, bridge_eps, result_shots):
    reasoning = {"anchor": {}, "beats": [], "shots_matching": [], "statistics": {}}

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

    for i, b in enumerate(beats):
        b["has_visual"] = b.get("has_visual", b.get("type") != "context")
    reasoning["beats"] = [{
        "index": b.get("index", i), "type": b.get("type", "?"),
        "text": b.get("text", ""), "has_visual": b.get("has_visual", True)
    } for i, b in enumerate(beats)]

    n_visual = sum(1 for b in beats if b.get("has_visual"))
    n_context = sum(1 for b in beats if b.get("type") == "context")

    for shot_entry in result_shots:
        pri = shot_entry.get("primary", {})
        pri_cands = pri.get("candidates", [])
        pri_reasoning = {
            "beat_index": shot_entry.get("beat_index", 0),
            "primary_purpose": pri.get("purpose", ""),
            "director_technique": shot_entry.get("director_technique", ""),
            "query": pri.get("query", {}),
            "focus_eps": sorted(focus_eps),
            "search_strategy": "标的集约束搜索",
            "top3_candidates": [
                {"rank": j+1, "ep": c["ep"], "start": c["start"], "end": c["end"],
                 "score": c["match_score"], "visual": c["visual_summary"][:80],
                 "why": f"人物={c['characters']}, 情绪={c['emotional_tone']}, 强度={c['intensity']}, 地点={c['location']}"}
                for j, c in enumerate((pri_cands or [])[:3])
            ],
            "secondary_reasoning": [],
        }
        for sec in shot_entry.get("secondary", []):
            sc = sec.get("candidates", [])
            pri_reasoning["secondary_reasoning"].append({
                "role": sec.get("shot_role", ""),
                "purpose": sec.get("purpose", ""),
                "top_candidate": {} if not sc else {
                    "ep": sc[0]["ep"], "score": sc[0]["match_score"],
                    "visual": sc[0]["visual_summary"][:80]
                }
            })
        reasoning["shots_matching"].append(pri_reasoning)

    reasoning["statistics"] = {
        "total_beats": len(beats),
        "visual_beats": n_visual,
        "context_beats": n_context,
        "primary_shots": len(result_shots),
        "secondary_shots": sum(len(s.get("secondary", [])) for s in result_shots),
        "anchor_hit_rate": f"{sum(1 for s in result_shots if s['primary'].get('candidates') and any(c['ep'] in focus_eps for c in s['primary']['candidates']))}/{len(result_shots)}" if focus_eps else "N/A"
    }

    return reasoning


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
