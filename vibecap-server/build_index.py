#!/usr/bin/env python3
"""构建语义搜索索引: VLM + ASR → BGE embedding → 保存
- 自动发现 sources_clean/ 下所有集数
- 字幕(sub)权重 2x，校准后 ASR 权重 1.5x
"""
import json, pickle, numpy as np, os
from pathlib import Path

# 国内 HF 镜像
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

ROOT_DIR = Path(__file__).parent.parent  # VIBECAP
DRAMA = os.environ.get("VIBECAP_DRAMA", "都挺好")
SOURCES_DIR = ROOT_DIR / DRAMA / "sources_clean"
INDEX_FILE = ROOT_DIR / DRAMA / "semantic_index.pkl"

# 如果清洗数据不存在，降级到原始数据
if not SOURCES_DIR.exists() or not any(SOURCES_DIR.iterdir()):
    SOURCES_DIR = ROOT_DIR / DRAMA / "sources"
    print("[build_index] 使用原始数据源")

from sentence_transformers import SentenceTransformer

def build_index():
    print("加载 BGE-base-zh-v1.5 模型 (CPU)...")
    model = SentenceTransformer("BAAI/bge-base-zh-v1.5", device="cpu")

    # 自动发现所有集数
    eps = sorted(set(
        int(d.name[2:]) for d in SOURCES_DIR.iterdir()
        if d.is_dir() and d.name.startswith("ep") and d.name[2:].isdigit()
    ))
    print(f"发现集数: {eps}")

    texts = []
    metas = []
    vlm_count = asr_count = sub_count = 0

    for ep in eps:
        # 优先读取合并后的 VLM（clean_data 产出），fallback 原版
        vlm_path = SOURCES_DIR / f"ep{ep}" / "vlm_merged.json"
        if not vlm_path.exists():
            vlm_path = SOURCES_DIR / f"ep{ep}" / "vlm_analysis.json"
        if vlm_path.exists():
            for s in json.load(open(vlm_path)):
                if s is None: continue
                tags = s.get("tags", [])
                if "skip_opening" in tags:
                    continue
                text = s.get("description", "")
                if len(text) > 10:
                    texts.append(text)
                    metas.append({
                        "type": "vlm", "ep": ep,
                        "scene_id": s["scene_id"],
                        "start": s["start"], "end": s["end"],
                        "text": text[:200]
                    })
                    vlm_count += 1
                # VLM 结构化字幕 → 权重 2x（精确匹配源）
                for sub in s.get("subtitles", []):
                    if len(sub) >= 3:
                        texts.append(sub)
                        metas.append({
                            "type": "sub", "ep": ep,
                            "scene_id": s["scene_id"],
                            "start": s["start"], "end": s["end"],
                            "text": sub[:200]
                        })
                        sub_count += 1

        asr_path = SOURCES_DIR / f"ep{ep}" / "asr_result.json"
        if asr_path.exists():
            for a in json.load(open(asr_path)):
                text = a.get("text", "")
                if len(text) > 8:
                    texts.append(text)
                    metas.append({
                        "type": "asr", "ep": ep,
                        "start": a["start"], "end": a["end"],
                        "text": text[:200],
                    })
                    asr_count += 1

    print(f"编码 {len(texts)} 条 (VLM:{vlm_count} ASR:{asr_count} SUB:{sub_count})...")
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=32,
                               normalize_embeddings=True)

    data = {
        "embeddings": embeddings.astype(np.float32),
        "metas": metas,
        "texts": texts
    }
    # pickle 格式 (兼容)
    with open(INDEX_FILE, "wb") as f:
        pickle.dump(data, f)

    # npy + json 格式 (mmap 零拷贝)
    npy_path = ROOT_DIR / DRAMA / "semantic_embeddings.npy"
    meta_path = ROOT_DIR / DRAMA / "semantic_metas.json"
    np.save(npy_path, embeddings.astype(np.float32))
    with open(meta_path, "w") as f:
        json.dump(metas, f, ensure_ascii=False)

    print(f"✅ 索引: {INDEX_FILE} + {npy_path.name} ({len(texts)} 条, {embeddings.shape[1]}维)")
    print(f"   pickle: {INDEX_FILE.stat().st_size/1024/1024:.0f}MB")
    print(f"   mmap:   {npy_path.stat().st_size/1024/1024:.0f}MB + {meta_path.stat().st_size/1024/1024:.0f}MB")

if __name__ == "__main__":
    build_index()
