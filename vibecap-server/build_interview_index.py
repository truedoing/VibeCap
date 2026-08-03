#!/usr/bin/env python3
"""为口播采访项目构建 BGE 语义索引，支持按意义搜索 ASR 转写
v2: 优先使用 classified_enhanced.json (含 cleaned_text + speaker),
    用 cleaned_text 编码, 保留 original_text 用于显示, 默认跳过 host 句。
"""
import json, argparse, numpy as np
from pathlib import Path
from sentence_transformers import SentenceTransformer
import os

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
BASE_DIR = Path("/Users/zgl/VIBECAP")

def build_index(project_name):
    project_dir = BASE_DIR / project_name
    sources_dir = project_dir / "sources"
    clean_dir = project_dir / "sources_clean"
    output_npy = project_dir / "semantic_embeddings.npy"
    output_meta = project_dir / "semantic_metas.json"

    # ── v2: 优先使用 enhanced 数据 ──
    enhanced_file = clean_dir / "classified_enhanced.json"
    if enhanced_file.exists():
        print(f"[index] 使用 enhanced 数据: {enhanced_file}")
        enhanced = json.load(open(enhanced_file))
        # 只索引 guest 的 content 层 (跳过 host/filler/meta)
        indexable = [s for s in enhanced
                     if s.get('speaker') == 'guest'
                     and s.get('layer') in ('content', 'guide')]
        print(f"[index] guest content: {len(indexable)}句 "
              f"(跳过host:{sum(1 for s in enhanced if s.get('speaker')=='host')}句, "
              f"filler/meta:{sum(1 for s in enhanced if s.get('layer') in ('filler','meta'))}句)")

        # 构建 ~15s 语义单元, 用 cleaned_text 编码, 保留 original_text
        # v3: 在 speaker 边界断开 (不同说话人不合并)
        all_segments = []
        chunk_texts = []
        chunk_originals = []
        chunk_start = None
        last_speaker = None

        for seg in sorted(indexable, key=lambda s: s.get('start_sec', 0)):
            speaker = seg.get('speaker', 'guest')
            cleaned = seg.get('cleaned_text', seg.get('text', '')).strip()
            original = seg.get('text', cleaned).strip()
            if len(cleaned) < 2: continue

            # speaker 切换 → 结束当前 chunk
            if last_speaker and speaker != last_speaker and chunk_texts:
                merged_cleaned = " ".join(chunk_texts)
                merged_original = " ".join(chunk_originals)
                if len(merged_cleaned) > 8:
                    all_segments.append({
                        "source": "学习新东方",
                        "start": chunk_start,
                        "end": seg.get('start_sec', chunk_start),
                        "text": merged_cleaned,
                        "original_text": merged_original,
                    })
                chunk_texts = []
                chunk_originals = []
                chunk_start = None

            last_speaker = speaker

            if chunk_start is None:
                chunk_start = seg['start_sec']
            chunk_texts.append(cleaned)
            chunk_originals.append(original)

            seg_end = seg.get('start_sec', 0) + max(len(cleaned) // 5, 3)
            if seg_end - chunk_start >= 15 or len(chunk_texts) >= 5:
                merged_cleaned = " ".join(chunk_texts)
                merged_original = " ".join(chunk_originals)
                if len(merged_cleaned) > 8:
                    all_segments.append({
                        "source": "学习新东方",
                        "start": chunk_start,
                        "end": seg_end,
                        "text": merged_cleaned,
                        "original_text": merged_original,
                    })
                chunk_texts = []
                chunk_originals = []
                chunk_start = None

        # 剩余
        if chunk_texts and len(" ".join(chunk_texts)) > 8:
            all_segments.append({
                "source": "学习新东方",
                "start": chunk_start,
                "end": indexable[-1].get('start_sec', chunk_start) + 10,
                "text": " ".join(chunk_texts),
                "original_text": " ".join(chunk_originals),
            })

        print(f"[index] 语义单元: {len(all_segments)}个 (仅guest, ~15s/单元)")

        # 编码
        print("[index] 加载 BGE 模型...")
        model = SentenceTransformer("BAAI/bge-base-zh-v1.5", local_files_only=True)
        texts = [s["text"] for s in all_segments]
        print(f"[index] 编码 {len(texts)} 段...")
        embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=True, batch_size=64)

        np.save(str(output_npy), embeddings)
        json.dump(all_segments, open(output_meta, "w"), ensure_ascii=False, indent=2)
        print(f"[index] ✅ 索引: {output_npy} ({embeddings.shape})")
        print(f"[index] ✅ 元数据: {output_meta} ({len(all_segments)}条)")
        return embeddings, all_segments

    # ── Fallback: 使用原始 ASR ──
    print("[index] 未找到 enhanced 数据, 使用原始 ASR")
    all_segments = []
    for asr_file in sorted(sources_dir.glob("asr_*.json")):
        source_name = asr_file.stem.replace("asr_", "")
        data = json.load(open(asr_file))

        # 合并短片段为 ~15s 语义单元
        chunk = []
        chunk_start = None
        for seg in data:
            text = seg.get("text", "").strip()
            if len(text) < 1: continue
            if chunk_start is None:
                chunk_start = seg["start"]
            chunk.append(text)
            # 累积超过 15s 或自然断句 → 合并
            if seg["end"] - chunk_start >= 15 or text.endswith(("。","？","！","吗","呢","吧")):
                merged_text = " ".join(chunk)
                if len(merged_text) > 8:  # 至少8字才有语义价值
                    all_segments.append({
                        "source": source_name,
                        "start": chunk_start,
                        "end": seg["end"],
                        "text": merged_text,
                    })
                chunk = []
                chunk_start = None
        # 剩余片段
        if chunk and len(" ".join(chunk)) > 8:
            all_segments.append({
                "source": source_name,
                "start": chunk_start,
                "end": data[-1]["end"],
                "text": " ".join(chunk),
            })

    print(f"合并后语义单元: {len(all_segments)} 个 (~15s/单元)")

    # 编码
    print("加载 BGE 模型...")
    model = SentenceTransformer("BAAI/bge-base-zh-v1.5")

    texts = [s["text"] for s in all_segments]
    print(f"编码 {len(texts)} 段...")
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=True, batch_size=64)
    print(f"嵌入维度: {embeddings.shape}")

    # 保存 (mmap 模式，省内存)
    np.save(str(output_npy), embeddings)
    json.dump(all_segments, open(output_meta, "w"), ensure_ascii=False, indent=2)

    print(f"✅ 索引已保存: {output_npy} ({embeddings.shape[0]}条, {embeddings.shape[1]}维)")
    print(f"   元数据: {output_meta}")
    return embeddings, all_segments

def search(query, embeddings, metas, top_k=10):
    """快速语义搜索"""
    model = SentenceTransformer("BAAI/bge-base-zh-v1.5")
    q_emb = model.encode([query], normalize_embeddings=True)[0]
    scores = np.dot(embeddings, q_emb)
    top = np.argsort(scores)[-top_k:][::-1]

    results = []
    for i in top:
        if scores[i] < 0.3: continue
        results.append({**metas[i], "score": round(float(scores[i]) * 100, 1)})
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="杨老师教育")
    parser.add_argument("--query", default=None, help="测试搜索")
    args = parser.parse_args()

    embeddings, metas = build_index(args.project)

    if args.query:
        results = search(args.query, embeddings, metas)
        print(f"\n搜索: {args.query}")
        for r in results[:5]:
            print(f"  [{r['source']} {r['start']:.0f}s] score={r['score']:.0f} | {r['text'][:100]}")
