"""搜索 handlers — 6 种搜索引擎 + 台词匹配"""

import json
import re
import os
import time
import numpy as np

from config import project_type, PROJECT_DIR, INDEX_NPY, INDEX_META
from lib.embeddings import encode


# ── 全局搜索状态（由 main.py 启动时填充） ──
semantic_emb = None
semantic_metas = None
asr_data: dict = {}
vlm_data: list = []
interview_asr = None


# ── 文本归一化 ──
try:
    from opencc import OpenCC
    _cc = OpenCC("t2s")
    def _norm(text):
        return _cc.convert(text)
except ImportError:
    def _norm(text):
        return text


# ── 搜索入口 ──
def search(query, limit=10, mode="hybrid", eps=None):
    if not query:
        return []

    if project_type == "interview" and mode in ("keyword", "hybrid"):
        kw_results = _interview_keyword_search(query, limit)
        if mode == "keyword":
            return kw_results
        sem_results = _semantic_search(query, limit)
        return _merge_results(kw_results, sem_results, limit)

    if mode == "keyword":
        results = _keyword_search(query, limit)
    elif mode == "semantic":
        results = _semantic_search(query, limit)
    elif mode == "hybrid":
        results = _hybrid_search(query, limit)
    elif mode == "deep":
        results = _deep_search(query, limit)
    elif mode == "asr_first":
        results = _asr_first_search(query, limit)
    else:
        results = _hybrid_search(query, limit)

    if eps:
        ep_set = set(int(e) for e in str(eps).split(",") if e.strip().isdigit())
        if ep_set:
            results = [r for r in results if r.get("ep") in ep_set]
    return results


# ── 辅助函数 ──
def _make_result(ep, start, end, scene_id, desc, asr, score):
    return {
        "ep": ep, "start": start, "end": end,
        "scene_id": scene_id,
        "duration": round(end - start, 1),
        "description": desc, "asr": asr,
        "score": round(score, 1),
    }


def _filter_low_scores(sorted_results, min_score=10):
    if not sorted_results:
        return []
    best = sorted_results[0]["score"]
    if best < 20:
        return []
    if best >= 30:
        threshold = max(min_score, best * 0.15)
    else:
        threshold = min_score
    return [r for r in sorted_results if r["score"] >= threshold]


def _merge_results(kw_results, sem_results, limit=10):
    merged = {}
    max_kw = max((r["score"] for r in kw_results), default=1)
    for r in kw_results:
        k = f"{r.get('source', '')}_{r['start']:.0f}"
        merged[k] = {**r, "score": r["score"] / max_kw * 40}

    max_sem = max((r["score"] for r in sem_results), default=1)
    for r in sem_results:
        k = f"{r.get('source', '')}_{r['start']:.0f}"
        sem_score = r["score"] / max_sem * 60
        if k in merged:
            merged[k]["score"] += sem_score
        else:
            merged[k] = {**r, "score": sem_score}

    return sorted(merged.values(), key=lambda x: -x["score"])[:limit]


# ── N-gram 加权 ──
def _build_ngram_kws(query_clean, include_full=True):
    """构建加权 n-gram 关键词表"""
    kws = {}
    qlen = len(query_clean)
    for n in range(2, min(qlen + 1, 9)):
        w = 3 ** (n - 2) if n <= 5 else 27
        seen = set()
        for i in range(qlen - n + 1):
            kw = query_clean[i:i + n]
            if kw not in seen:
                seen.add(kw)
                kws[kw] = max(kws.get(kw, 0), w)
    if include_full and qlen > 1:
        kws[query_clean] = 81
    return kws


# ── 语义搜索 ──
def _semantic_search(query, limit=10):
    if semantic_emb is None:
        return []
    emb = semantic_emb
    metas = semantic_metas
    q_emb = encode(query)
    scores = np.dot(emb, q_emb)
    top = np.argsort(scores)[-200:][::-1]  # 扩大取top, storyboard_suggest 需要更多候选
    results = {}

    if project_type == "interview":
        for i in top:
            if scores[i] <= 0.30:
                continue
            m = metas[i]
            r = {
                "ep": 0, "start": m["start"], "end": m["end"],
                "scene_id": 0, "description": m["text"][:200], "asr": m["text"][:200],
                "source": m.get("source", ""),
                "score": round(float(scores[i]) * 100, 1),
                "duration": round(m["end"] - m["start"], 1),
            }
            k = f"{m['source']}_{m['start']:.0f}"
            if k not in results or r["score"] > results[k]["score"]:
                results[k] = r
        return sorted(results.values(), key=lambda x: -x["score"])[:limit]

    # drama 模式
    for i in top:
        if scores[i] < 0.25:
            continue
        m = metas[i]
        asr_txt = ""
        for a in asr_data.get(m["ep"], []):
            if a["start"] < m["end"] and a["end"] > m["start"]:
                asr_txt += a["text"]
        r = _make_result(m["ep"], m["start"], m["end"],
                         m.get("scene_id", 0), m["text"][:200], asr_txt[:200],
                         round(float(scores[i]) * 50, 1))
        k = f"{m['ep']}_{m['start']:.0f}"
        if k not in results or r["score"] > results[k]["score"]:
            results[k] = r
    return sorted(results.values(), key=lambda x: -x["score"])[:limit]


# ── 关键词搜索 (drama) ──
def _keyword_search(query, limit=10):
    results = {}
    query = _norm(query)
    kws = _build_ngram_kws(query)

    for ep in sorted(asr_data.keys()):
        asr_list = asr_data.get(ep, [])
        for i, a in enumerate(asr_list):
            asr_text = a["text"]
            score = sum(asr_text.count(kw) * w for kw, w in kws.items())
            if score <= 0:
                continue
            start, end, text = a["start"], a["end"], asr_text
            merged_count = 0
            if i > 0 and sum(asr_list[i-1]["text"].count(kw) * w for kw, w in kws.items()) > 0:
                start = asr_list[i-1]["start"]; text = asr_list[i-1]["text"] + " " + text
                merged_count += 1
            if i > 1 and sum(asr_list[i-2]["text"].count(kw) * w for kw, w in kws.items()) > 0:
                start = asr_list[i-2]["start"]; text = asr_list[i-2]["text"] + " " + text
                merged_count += 1
            if i+1 < len(asr_list) and sum(asr_list[i+1]["text"].count(kw) * w for kw, w in kws.items()) > 0:
                end = asr_list[i+1]["end"]; text += " " + asr_list[i+1]["text"]
                merged_count += 1
            if i+2 < len(asr_list) and sum(asr_list[i+2]["text"].count(kw) * w for kw, w in kws.items()) > 0:
                end = asr_list[i+2]["end"]; text += " " + asr_list[i+2]["text"]
            score += merged_count * 5
            k = f"{ep}_{start:.0f}_kw"
            r = _make_result(ep, start, end, 0, text[:200], "", score)
            if k not in results or r["score"] > results[k]["score"]:
                results[k] = r

    for s in vlm_data:
        desc = s.get("description", "")
        score = sum(desc.count(kw) * w * 3 for kw, w in kws.items())
        if score <= 0:
            continue
        k = f"{s['_ep']}_{s['start']:.0f}"
        r = _make_result(s["_ep"], s["start"], s["end"],
                         s["scene_id"], desc[:200], "", score)
        if k in results:
            r["score"] += results[k]["score"]
        results[k] = r
    return sorted(results.values(), key=lambda x: -x["score"])[:limit]


# ── 口播关键词搜索 ──
def _interview_keyword_search(query, limit=10):
    results = {}
    q_clean = _norm(query)
    kws = _build_ngram_kws(q_clean)

    classified = []
    for cf in (PROJECT_DIR / "sources_clean").glob("classified_*.json"):
        if cf.name != "classified_enhanced.json":
            classified = json.load(open(cf))
            break
    if classified:
        for s in classified:
            text = _norm(s.get('text', ''))
            score = sum(text.count(kw) * w for kw, w in kws.items())
            if score <= 0:
                continue
            k = f"{s.get('start_sec', 0):.0f}"
            r = {
                "ep": 0, "start": s.get('start_sec', 0), "end": s.get('start_sec', 0) + 3,
                "scene_id": 0, "description": text[:200], "asr": text[:200],
                "score": round(score * 1.5, 1),
                "duration": 3, "source": "学习新东方",
            }
            if k not in results or r["score"] > results[k]["score"]:
                results[k] = r

    return sorted(results.values(), key=lambda x: -x["score"])[:limit]


# ── 混合搜索 (drama) ──
def _hybrid_search(query, limit=10):
    semantic_results = _semantic_search(query, 30)
    keyword_results = _keyword_search(query, 30)

    merged = {}
    max_s = max((r["score"] for r in semantic_results), default=1)
    for r in semantic_results:
        k = f"{r['ep']}_{r['start']:.0f}"
        merged[k] = {**r, "score": r["score"] / max_s * 70}

    max_k = max((r["score"] for r in keyword_results), default=1)
    for r in keyword_results:
        k = f"{r['ep']}_{r['start']:.0f}"
        kw_score = r["score"] / max_k * 30
        if k in merged:
            merged[k]["score"] += kw_score
        else:
            merged[k] = {**r, "score": kw_score}

    return sorted(merged.values(), key=lambda x: -x["score"])[:limit]


# ── ASR 优先搜索 ──
def _asr_first_search(query, limit=10, min_score=10, eps=None):
    query = _norm(query)
    results = {}

    kws = _build_ngram_kws(query)

    for ep in sorted(asr_data.keys()):
        asr_list = asr_data.get(ep, [])
        for i, a in enumerate(asr_list):
            asr_text = a["text"]
            score = sum(asr_text.count(kw) * w for kw, w in kws.items())
            if score <= 0:
                continue
            start, end, text = a["start"], a["end"], asr_text
            if i > 0 and sum(asr_list[i-1]["text"].count(kw) * w for kw, w in kws.items()) > 0:
                start = asr_list[i-1]["start"]; text = asr_list[i-1]["text"] + " " + text
            if i > 1 and sum(asr_list[i-2]["text"].count(kw) * w for kw, w in kws.items()) > 0:
                start = asr_list[i-2]["start"]; text = asr_list[i-2]["text"] + " " + text
            if i+1 < len(asr_list) and sum(asr_list[i+1]["text"].count(kw) * w for kw, w in kws.items()) > 0:
                end = asr_list[i+1]["end"]; text += " " + asr_list[i+1]["text"]
            if i+2 < len(asr_list) and sum(asr_list[i+2]["text"].count(kw) * w for kw, w in kws.items()) > 0:
                end = asr_list[i+2]["end"]; text += " " + asr_list[i+2]["text"]
            score = min(score * 1.5, 95)
            k = f"{ep}_{start:.0f}"
            r = _make_result(ep, start, end, 0, text[:200], text[:200], score)
            if k not in results or r["score"] > results[k]["score"]:
                results[k] = r

    if len(results) < limit:
        seen = set(results.keys())
        semantic = _semantic_search(query, 20)
        for r in semantic:
            k = f"{r['ep']}_{r['start']:.0f}"
            if k in seen:
                continue
            ep = r["ep"]
            asr_txt = ""
            for a in asr_data.get(ep, []):
                if a["start"] < r["end"] and a["end"] > r["start"]:
                    asr_txt += a["text"]
            if asr_txt:
                r["description"] = asr_txt[:200]
                r["asr"] = asr_txt[:200]
            r["score"] = r["score"] * 0.4
            results[k] = r
            seen.add(k)

    sorted_results = sorted(results.values(), key=lambda x: -x["score"])
    return _filter_low_scores(sorted_results, min_score)[:limit]


# ── 深度搜索 (query 扩展 + LLM 重排) ──
def _deep_search(query, limit=10):
    variants = _expand_query(query)
    all_hits = {}
    for q in [query] + variants:
        for r in _hybrid_search(q, 20):
            k = f"{r['ep']}_{r['start']:.0f}"
            if k not in all_hits or r["score"] > all_hits[k]["score"]:
                all_hits[k] = r
    candidates = sorted(all_hits.values(), key=lambda x: -x["score"])[:20]
    if len(candidates) <= limit:
        return candidates
    return _llm_rerank(query, candidates, limit)


def _expand_query(query):
    """LLM 扩展查询：生成 2-3 个不同角度的搜索词"""
    from lib.llm import call_mimo
    result = call_mimo(
        "将用户的分镜描述改写为2-3个具体的画面搜索关键词（每行一个，10-20字），用于搜索视频素材库。直接输出关键词，不要编号。",
        f"分镜描述：{query}",
        max_tokens=200, timeout=15, label="expand_query",
    )
    if result["ok"]:
        return [l.strip().lstrip("- 123456789.）)") for l in result["content"].strip().split("\n") if l.strip()][:3]
    return []


def _llm_rerank(query, candidates, top_n=10):
    """LLM 对候选画面重排序"""
    from lib.llm import call_mimo
    cand_text = "\n".join(
        f"[{i}] EP{c['ep']} {c['start']:.0f}s-{c['end']:.0f}s | {c['description'][:120]}"
        for i, c in enumerate(candidates)
    )
    result = call_mimo(
        "你是视频素材匹配助手。根据分镜描述的画面内容，对候选素材进行相关性排序。只输出最相关的5-10个编号（如：3,7,1,12,5），不要解释。",
        f"分镜描述：{query}\n\n候选素材：\n{cand_text}\n\n请选出最相关的素材编号（逗号分隔）：",
        max_tokens=100, timeout=15, label="llm_rerank",
    )
    if result["ok"]:
        text = result["content"]
        ids = [int(s.strip()) for s in re.findall(r'\d+', text) if s.strip().isdigit()]
        reranked = [candidates[i] for i in ids if 0 <= i < len(candidates)]
        return reranked[:top_n] if reranked else candidates[:top_n]
    return candidates[:top_n]


# ── 台词说话人注入 ──
def inject_speaker(query, results, context):
    """台词结果注入说话人：封面标题人物 > highlight_text 集数定位 + VLM 分析"""
    CHARS = ['苏大强', '苏明哲', '苏明成', '苏明玉', '明玉', '朱丽', '吴非', '石天冬',
             '蒙总', '老蒙', '蒙太', '沈浩', '柳青', '赵美兰', '小咪', '蔡根花']
    CHAR_ALIAS = {'明玉': '苏明玉', '老蒙': '蒙总'}

    if not results:
        return results

    cover = context.get("cover", "")
    cover_chars = [c for c in CHARS if c in cover]
    speaker = CHAR_ALIAS.get(cover_chars[0], cover_chars[0]) if cover_chars else None

    if not speaker:
        hl = context.get("highlight_text", "")
        ep_match = re.search(r'(\d{1,2})集|(\d{1,2})\.\d{1,2}$|EP\s*(\d{1,2})', str(hl))
        if ep_match:
            target_ep = ep_match.group(1) or ep_match.group(2) or ep_match.group(3)
            best = None
            for r in results:
                if str(r.get("ep")) == target_ep:
                    if best is None or r["score"] > best["score"]:
                        best = r
            if best:
                start = best["start"]
                end = best["end"]
                vlm_entries = [m for m in (semantic_metas or [])
                               if str(m.get("ep", "")) == target_ep and m.get("type") == "vlm"
                               and float(m.get("start", 0)) <= end + 5
                               and float(m.get("end", 0)) >= start - 5]
                char_freq = {}
                for vlm in vlm_entries:
                    text = vlm.get("text", "")
                    for c in CHARS:
                        if c in text:
                            char_freq[c] = char_freq.get(c, 0) + 1
                if char_freq:
                    top = sorted(char_freq.items(), key=lambda x: -x[1])[0][0]
                    speaker = CHAR_ALIAS.get(top, top)

    if speaker:
        for r in results:
            prefix = f"【{speaker}】"
            if not r.get("description", "").startswith(prefix):
                r["description"] = prefix + r.get("description", "")
                if r.get("asr"):
                    r["asr"] = prefix + r.get("asr", "")

    return results


# ── 台词 ASR 搜索（对话匹配用） ──
def search_asr_text(query, limit=3):
    """关键字搜索 ASR + 字幕数据（字幕权重 x2）"""
    results = {}
    q_clean = re.sub(r'[，。！？、\s　]', '', query)
    kws = []
    for n in [2, 3]:
        for i in range(len(q_clean) - n + 1):
            kw = q_clean[i:i+n]
            stopwords2 = {'你想', '想去', '去跟', '跟他', '他的', '她的', '一个', '这个', '那个',
                          '什么', '怎么', '不是', '就是', '还是', '可以', '已经', '因为', '所以',
                          '但是', '不过', '虽然', '如果', '只是', '还不', '不了', '哪个', '那儿'}
            if kw not in stopwords2:
                kws.append(kw)

    for ep, asr_list in asr_data.items():
        for a in asr_list:
            text = a["text"]
            score = sum((text.count(k) * 3) for k in kws)
            if score <= 0:
                continue
            k = f"asr_{ep}_{a['start']:.0f}"
            r = {"ep": ep, "start": a["start"], "end": a["end"], "text": text[:200], "score": score}
            if k not in results or r["score"] > results[k]["score"]:
                results[k] = r

    if semantic_metas:
        for i, m in enumerate(semantic_metas):
            if m.get("type") != "sub":
                continue
            text = m["text"]
            score = sum((text.count(k) * 6) for k in kws)
            if score <= 0:
                continue
            k = f"sub_{m['ep']}_{m['start']:.0f}"
            r = {"ep": m["ep"], "start": m["start"], "end": m["end"], "text": text[:200], "score": score}
            if k not in results or r["score"] > results[k]["score"]:
                results[k] = r

    return sorted(results.values(), key=lambda x: -x["score"])[:limit]


def search_asr_anchor(kws: list, limit: int = 10) -> list:
    """用 2-4 字关键词列表在 ASR 中快速锚定台词位置

    用于高亮台词（原剧对话）的定位。

    策略: cluster scoring — 在同一集内密集出现的高分片段
    比孤立的偶然匹配更可靠。对每集所有命中求和 + cluster density bonus。
    """
    # Phase 1: 收集所有命中
    ep_hits = {}
    for ep, asr_list in asr_data.items():
        hits = []
        for a in asr_list:
            text = a["text"]
            score = sum(text.count(k) * (3 if len(k) >= 3 else 2) for k in kws)
            if score > 5:
                hits.append((score, a))
        if hits:
            ep_hits[ep] = sorted(hits, key=lambda x: -x[0])

    if not ep_hits:
        return []

    # Phase 2: 对每集计算 cluster total score
    ep_scores = {}
    for ep, hits in ep_hits.items():
        top = hits[0]
        top_time = top[1]["start"]
        # total score: 所有 >10 分的命中加总
        total = sum(s for s, a in hits if s > 10)
        # cluster bonus: 前30s内有多少个 >10 分的命中
        cluster = sum(1 for s, a in hits
                      if s > 10 and abs(a["start"] - top_time) < 30)
        ep_scores[ep] = (total + cluster * 10, top)

    # Phase 3: 按 ep 总得分排序
    ranked = sorted(ep_scores.items(), key=lambda x: -x[1][0])

    results = []
    for ep, (ep_total, (score, a)) in ranked[:limit]:
        results.append({
            "ep": ep, "start": a["start"], "end": a["end"],
            "text": a["text"][:200], "score": score,
        })
    return results
