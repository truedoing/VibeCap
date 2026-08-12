"""路由注册 + 启动时间初始化 — 从 main.py 提取

所有 router 共用的全局搜索状态在这里定义。
"""

import json
import os
import threading
import time

import numpy as np

from config import (
    project_name, project_type, PROJECT_DIR,
    SOURCES_DIR, PROXY_DIR, PROXY_MANIFEST, CLEAN_DIR,
    INDEX_NPY, INDEX_META, INDEX_FILE,
    SOURCE_VIDEOS, args,
    resolve_task_dir, resolve_clip_dir, resolve_work_dir,
)
from db import VibeCutDB
from lib.env import load_env
from lib.embeddings import get_model as get_bge_model, encode as bge_encode

# ── 全局搜索状态 (所有 router 共享) ──
semantic_emb = None
semantic_metas = None
vlm_data = []
asr_data = {}
interview_asr = None
available_eps = []

DB_PATH = PROJECT_DIR.parent / "vibecut.db"
db = VibeCutDB(str(DB_PATH))


def startup(app, _args):
    """启动时加载索引和 BGE 模型"""
    global semantic_emb, semantic_metas, vlm_data, asr_data, interview_asr, available_eps

    load_env()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    if not os.environ.get("HF_ENDPOINT"):
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

    print(f"[init] project={project_name} (type={project_type})")

    # ── 初始化 VLM 缓存 ──
    from lib.vlm_cache import set_project_dir
    set_project_dir(PROJECT_DIR)

    # ── 加载语义索引 ──
    if project_type == "drama":
        if INDEX_NPY.exists() and INDEX_META.exists():
            semantic_emb = np.load(str(INDEX_NPY), mmap_mode='r')
            semantic_metas = json.load(open(INDEX_META))
            print(f"[search] 语义索引 (mmap): {semantic_emb.shape[0]} 条, {semantic_emb.shape[1]}维")
        elif INDEX_FILE.exists():
            import pickle
            index = pickle.load(open(INDEX_FILE, "rb"))
            semantic_emb = np.array(index["embeddings"])
            semantic_metas = index["metas"]
            print(f"[search] 语义索引 (pkl): {semantic_emb.shape[0]} 条")
    else:
        if INDEX_NPY.exists() and INDEX_META.exists():
            semantic_emb = np.load(str(INDEX_NPY), mmap_mode='r')
            semantic_metas = json.load(open(INDEX_META))
            print(f"[search] 语义索引 (mmap): {semantic_emb.shape[0]} 条, {semantic_emb.shape[1]}维")

    # ── 加载 ASR + VLM 数据 ──
    if project_type == "drama":
        for ep in range(1, 47):
            ep_str = f"{ep:02d}"
            asr_file = SOURCES_DIR / f"ep{ep}" / "asr_result.json"
            if not asr_file.exists():
                asr_file = SOURCES_DIR / f"ep{ep_str}" / "asr_result.json"
            if not asr_file.exists():
                asr_file = SOURCES_DIR / f"asr_ep{ep_str}.json"
            if not asr_file.exists():
                asr_file = SOURCES_DIR / f"asr_{ep_str}.json"
            if asr_file.exists():
                asr_data[ep] = json.load(open(asr_file))
                available_eps.append(ep)

            vlm_file = SOURCES_DIR / f"vlm_ep{ep_str}.json"
            if not vlm_file.exists():
                vlm_file = SOURCES_DIR / f"vlm_ep{ep_str}_scene.json"
            if vlm_file.exists():
                vlm_list = json.load(open(vlm_file))
                for s in vlm_list:
                    s["_ep"] = ep
                vlm_data.extend(vlm_list)

        print(f"[data] 加载: {len(asr_data)} 集 ASR, {len(vlm_data)} 条 VLM")
    elif project_type == "interview":
        for cf in sorted(CLEAN_DIR.glob("classified_*.json")):
            if cf.name != "classified_enhanced.json":
                interview_asr = json.load(open(cf))
                print(f"[data] 口播 ASR: {cf.name} ({len(interview_asr)} 句)")
                break

    # ── 注入 Agent 搜索 ──
    try:
        from agents.script_agents import set_search_fn

        def _agent_search(query, limit=15):
            if semantic_emb is None:
                return []
            q_emb = bge_encode(query)
            scores = np.dot(semantic_emb, q_emb)
            top = np.argsort(scores)[-limit * 2:][::-1]
            results = []
            for i in top:
                if scores[i] <= 0.25:
                    continue
                m = semantic_metas[i]
                display_text = m.get("original_text", m.get("text", ""))
                results.append({
                    "start": m.get("start", 0),
                    "end": m.get("end", m.get("start", 0) + 4),
                    "description": display_text[:200],
                    "asr": display_text[:200],
                    "cleaned_text": m.get("text", "")[:200],
                    "score": round(float(scores[i]) * 100, 1),
                })
            return sorted(results, key=lambda x: -x["score"])[:limit]

        set_search_fn(_agent_search)

        print("[agent] 预热 BGE 模型...")
        warm_ready = threading.Event()

        def _warm():
            try:
                _agent_search("预热", limit=1)
                print("[agent] BGE 模型预热完成 ✓")
                warm_ready.set()
            except Exception as e:
                print(f"[agent] 预热失败: {e}")
                warm_ready.set()

        threading.Thread(target=_warm, daemon=True).start()
        if not warm_ready.wait(timeout=30):
            print("[agent] ⚠️ 预热超时(30s)")
    except Exception as e:
        print(f"[agent] search injection failed: {e}")

    # 注入 handlers 所需的全局搜索状态
    import handlers.search as hs
    hs.semantic_emb = semantic_emb
    hs.semantic_metas = semantic_metas
    hs.asr_data = asr_data
    hs.vlm_data = vlm_data
    hs.interview_asr = interview_asr

    print(f"[init] 就绪 — http://0.0.0.0:{_args.port}/")


def shutdown():
    """应用关闭时的清理"""
    print("[init] 关闭")
