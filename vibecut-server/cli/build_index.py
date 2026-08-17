#!/usr/bin/env python3
"""
构建语义搜索索引 — 统一入口 (v0.11)
  python3 build_index.py --project 都挺好     # 电视剧: VLM + ASR → BGE
  python3 build_index.py --project 杨老师教育  # 口播: enhanced ASR → BGE
"""
import json, pickle, numpy as np, os, argparse
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

ROOT_DIR = Path(__file__).parent.parent  # VibeCut

def build_drama_index(project_dir, drama_name):
    """电视剧索引: VLM + ASR → BGE"""
    from sentence_transformers import SentenceTransformer
    sources_dir = project_dir / "sources_clean"
    if not sources_dir.exists() or not any(sources_dir.iterdir()):
        sources_dir = project_dir / "sources"

    print("[drama] 加载 BGE 模型...")
    model = SentenceTransformer("BAAI/bge-base-zh-v1.5", local_files_only=True)

    eps = sorted(set(
        int(d.name[2:]) for d in sources_dir.iterdir()
        if d.is_dir() and d.name.startswith("ep") and d.name[2:].isdigit()
    ))
    print(f"[drama] 发现 {len(eps)} 集: {eps}")

    texts, metas = [], []
    vlm_count = 0
    for ep in eps:
        # v3: 场景段级结构化数据 (不再切片), fallback v2 sliced
        cache_v3 = sources_dir / f"ep{ep}" / "vlm_seg_cache_v3.json"
        if cache_v3.exists():
            cache = json.load(open(cache_v3))
            for key, s in cache.items():
                if s is None: continue
                visual = s.get("visual_summary", "")
                if len(visual) < 10: continue

                tags_parts = []
                if s.get("shot_size"):     tags_parts.append(f"景别:{s['shot_size']}")
                if s.get("composition"):   tags_parts.append(f"构图:{s['composition']}")
                if s.get("angle"):         tags_parts.append(f"视角:{s['angle']}")
                if s.get("emotional_tone"): tags_parts.append(f"情绪:{s['emotional_tone']}")
                if s.get("lighting"):      tags_parts.append(f"光线:{s['lighting']}")
                tag_prefix = " ".join(f"[{t}]" for t in tags_parts)
                text = f"{tag_prefix} {visual}".strip()

                meta_entry = {
                    "type": "vlm", "ep": ep,
                    "scene_id": s.get("scene_map_index", int(key)),
                    "start": s["start"], "end": s["end"],
                    "text": text[:300],
                    "shot_size": s.get("shot_size", ""),
                    "composition": s.get("composition", ""),
                    "angle": s.get("angle", ""),
                    "emotional_tone": s.get("emotional_tone", ""),
                    "intensity": s.get("intensity", 3),
                    "lighting": s.get("lighting", ""),
                    "actions": s.get("actions", []),
                }
                texts.append(text)
                metas.append(meta_entry)
                vlm_count += 1
        else:
            # v2 fallback: 切片文件
            vlm_path = sources_dir / f"ep{ep}" / "vlm_analysis_sliced.json"
            if not vlm_path.exists():
                vlm_path = sources_dir / f"ep{ep}" / "vlm_merged.json"
            if not vlm_path.exists():
                vlm_path = sources_dir / f"ep{ep}" / "vlm_analysis.json"
            if vlm_path.exists():
                for s in json.load(open(vlm_path)):
                    if s is None: continue
                    if "skip_opening" in s.get("tags", []): continue
                    text = s.get("description", "")
                    cal_marker = "\n[人物校准:"
                    if cal_marker in text:
                        text = text[:text.index(cal_marker)]
                    if len(text) > 10:
                        texts.append(text)
                        metas.append({"type": "vlm", "ep": ep, "scene_id": s.get("scene_id", 0),
                                      "start": s["start"], "end": s["end"], "text": text[:200]})
                        vlm_count += 1
                    for sub in s.get("subtitles", []):
                        if len(sub) >= 3:
                            texts.append(sub)
                            metas.append({"type": "sub", "ep": ep, "scene_id": s.get("scene_id", 0),
                                          "start": s["start"], "end": s["end"], "text": sub[:200]})
        asr_path = sources_dir / f"ep{ep}" / "subtitle_result.json"
        if asr_path.exists():
            for a in json.load(open(asr_path)):
                text = a.get("text", "")
                if len(text) > 8:
                    texts.append(text)
                    metas.append({"type": "asr", "ep": ep, "start": a["start"], "end": a["end"],
                                  "text": text[:200]})

    print(f"[drama] 编码 {len(texts)} 条 (VLM:{vlm_count} ASR:{len(texts)-vlm_count})...")
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=32, normalize_embeddings=True)
    save_index(project_dir, embeddings, metas, texts)
    return embeddings, metas


def build_interview_index(project_dir):
    """口播索引: enhanced ASR (guest-only) → BGE"""
    from sentence_transformers import SentenceTransformer
    clean_dir = project_dir / "sources_clean"
    enhanced_file = clean_dir / "classified_enhanced.json"

    if enhanced_file.exists():
        print("[interview] 使用 enhanced 数据")
        data = json.load(open(enhanced_file))
        indexable = [s for s in data if s.get('speaker') == 'guest'
                     and s.get('layer') in ('content', 'guide')]
    else:
        cf = list(clean_dir.glob("classified_*.json"))
        if not cf:
            print("[interview] ❌ 未找到 classified 数据")
            return None, None
        data = json.load(open(cf[0]))
        indexable = [s for s in data if s.get('layer') in ('content', 'guide')]

    print(f"[interview] guest content: {len(indexable)}句")

    # speaker 边界断开 + cleaned_text 编码
    texts, metas = [], []
    chunk_texts, chunk_originals = [], []
    chunk_start, last_speaker = None, None

    for seg in sorted(indexable, key=lambda s: s.get('start_sec', 0)):
        speaker = seg.get('speaker', 'guest')
        cleaned = seg.get('cleaned_text', seg.get('text', '')).strip()
        original = seg.get('text', cleaned).strip()
        if len(cleaned) < 2: continue

        if last_speaker and speaker != last_speaker and chunk_texts:
            merged = " ".join(chunk_texts)
            merged_orig = " ".join(chunk_originals)
            if len(merged) > 8:
                texts.append(merged)
                metas.append({"source": "学习新东方", "start": chunk_start,
                              "end": seg.get('start_sec', chunk_start),
                              "text": merged, "original_text": merged_orig})
            chunk_texts, chunk_originals = [], []
            chunk_start = None
        last_speaker = speaker

        if chunk_start is None: chunk_start = seg['start_sec']
        chunk_texts.append(cleaned)
        chunk_originals.append(original)

        seg_end = seg.get('start_sec', 0) + max(len(cleaned) // 5, 3)
        if seg_end - chunk_start >= 15 or len(chunk_texts) >= 5:
            merged = " ".join(chunk_texts); merged_orig = " ".join(chunk_originals)
            if len(merged) > 8:
                texts.append(merged)
                metas.append({"source": "学习新东方", "start": chunk_start,
                              "end": seg_end, "text": merged, "original_text": merged_orig})
            chunk_texts, chunk_originals = [], []
            chunk_start = None

    if chunk_texts and len(" ".join(chunk_texts)) > 8:
        texts.append(" ".join(chunk_texts))
        metas.append({"source": "学习新东方", "start": chunk_start,
                      "end": indexable[-1].get('start_sec', chunk_start) + 10,
                      "text": " ".join(chunk_texts),
                      "original_text": " ".join(chunk_originals)})

    print(f"[interview] 语义单元: {len(texts)}个")
    print("[interview] 加载 BGE 模型...")
    model = SentenceTransformer("BAAI/bge-base-zh-v1.5", local_files_only=True)
    print(f"[interview] 编码 {len(texts)} 段...")
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=64, normalize_embeddings=True)
    save_index(project_dir, embeddings, metas, texts)
    return embeddings, metas


def save_index(project_dir, embeddings, metas, texts):
    """统一保存: pickle + npy + json"""
    pkl_path = project_dir / "semantic_index.pkl"
    npy_path = project_dir / "semantic_embeddings.npy"
    meta_path = project_dir / "semantic_metas.json"

    data = {"embeddings": embeddings.astype(np.float32), "metas": metas, "texts": texts}
    with open(pkl_path, "wb") as f: pickle.dump(data, f)
    np.save(str(npy_path), embeddings.astype(np.float32))
    with open(meta_path, "w") as f: json.dump(metas, f, ensure_ascii=False, indent=2)

    print(f"✅ 索引: {pkl_path} ({len(texts)}条, {embeddings.shape[1]}维)")
    print(f"   pickle: {pkl_path.stat().st_size/1024/1024:.0f}MB")
    print(f"   mmap:   {npy_path.stat().st_size/1024/1024:.0f}MB + {meta_path.stat().st_size/1024/1024:.0f}MB")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=os.environ.get("VibeCut_PROJECT", "都挺好"))
    args = parser.parse_args()

    project_dir = ROOT_DIR / args.project
    # 检测项目类型
    cfg_file = ROOT_DIR / "projects" / f"{args.project}.json"
    project_type = "drama"
    if cfg_file.exists():
        cfg = json.load(open(cfg_file))
        project_type = cfg.get("type", "drama")

    print(f"[build_index] project={args.project} type={project_type}")

    if project_type == "interview":
        build_interview_index(project_dir)
    else:
        build_drama_index(project_dir, args.project)


if __name__ == "__main__":
    main()
