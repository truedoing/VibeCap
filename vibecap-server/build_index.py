#!/usr/bin/env python3
"""构建语义搜索索引: VLM + ASR → BGE embedding → 保存"""
import json, pickle, numpy as np, os
from pathlib import Path

# 国内 HF 镜像
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

ROOT_DIR = Path(__file__).parent.parent  # VIBECAP
# 支持环境变量指定电视剧
DRAMA = os.environ.get("VIBECAP_DRAMA", "都挺好")
SOURCES_DIR = ROOT_DIR / DRAMA / "sources"
INDEX_FILE = ROOT_DIR / DRAMA / "semantic_index.pkl"

from sentence_transformers import SentenceTransformer

def build_index():
    print("加载 BGE-large-zh-v1.5 模型...")
    model = SentenceTransformer("BAAI/bge-base-zh-v1.5")

    texts = []
    metas = []

    for ep in [1, 2, 27, 28, 29]:
        vlm_path = SOURCES_DIR / f"ep{ep}" / "vlm_analysis.json"
        if vlm_path.exists():
            for s in json.load(open(vlm_path)):
                text = s.get("description", "")
                if len(text) > 10 and "片头" not in text and "片尾" not in text:
                    texts.append(text)
                    metas.append({
                        "type": "vlm", "ep": ep,
                        "scene_id": s["scene_id"],
                        "start": s["start"], "end": s["end"],
                        "text": text[:200]
                    })

        asr_path = SOURCES_DIR / f"ep{ep}" / "asr_result.json"
        if asr_path.exists():
            for a in json.load(open(asr_path)):
                text = a.get("text", "")
                if len(text) > 8:
                    texts.append(text)
                    metas.append({
                        "type": "asr", "ep": ep,
                        "start": a["start"], "end": a["end"],
                        "text": text[:200]
                    })

    print(f"编码 {len(texts)} 条文本 (1024维)...")
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=32,
                               normalize_embeddings=True)

    data = {
        "embeddings": embeddings.astype(np.float32),
        "metas": metas,
        "texts": texts
    }
    with open(INDEX_FILE, "wb") as f:
        pickle.dump(data, f)

    print(f"✅ 新索引: {INDEX_FILE} ({len(texts)} 条, {embeddings.shape[1]}维)")

if __name__ == "__main__":
    build_index()
