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

