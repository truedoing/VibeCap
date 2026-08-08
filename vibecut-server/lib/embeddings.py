"""BGE 模型统一管理 — 单例加载 + 编码"""

import os
import numpy as np

_enc_model = None


def get_model(model_name: str = "BAAI/bge-base-zh-v1.5"):
    """延迟加载 BGE 模型（单例）"""
    global _enc_model
    if _enc_model is None:
        from sentence_transformers import SentenceTransformer
        _enc_model = SentenceTransformer(model_name)
    return _enc_model


def encode(text: str, normalize: bool = True) -> np.ndarray:
    """对文本进行 BGE 编码，返回归一化向量"""
    model = get_model()
    return model.encode([text], normalize_embeddings=normalize)[0]
