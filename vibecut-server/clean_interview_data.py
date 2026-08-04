#!/usr/bin/env python3
"""
口播采访数据增强管线
Step A: LLM 清洗文本 + 说话人识别 → classified_enhanced.json
Step B: 用 cleaned_text 重建 BGE 语义索引

用法:
  python3 clean_interview_data.py --project 杨老师教育
  python3 clean_interview_data.py --project 杨老师教育 --skip-clean  # 跳过清洗,只重建索引
"""
import json, os, time, urllib.request, argparse, re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
API_URL = "https://api.deepseek.com/v1/chat/completions"

def load_env():
    env_file = Path(__file__).resolve().parent / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if not os.environ.get(k):
                        os.environ[k] = v

def call_llm(system, user, temp=0.3, max_tokens=3000):
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    payload = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": temp, "max_tokens": max_tokens,
    }).encode()
    for attempt in range(3):
        try:
            req = urllib.request.Request(API_URL, data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())
            text = result["choices"][0]["message"]["content"].strip()
            if text.startswith("```"): text = text.split("\n", 1)[1].split("```")[0].strip()
            return json.loads(text)
        except Exception as e:
            if attempt == 2:
                print(f"  LLM call failed: {e}")
                return None
            time.sleep(3)
    return None


def clean_and_identify_speakers(items, batch_size=25):
    """
    批量清洗文本 + 识别说话人。
    输入: [{start_sec, text, layer, importance}, ...]
    输出: 同列表, 增加 cleaned_text 和 speaker 字段
    """
    # 只处理 content 和 guide 层 (有实质内容)
    processable = [s for s in items if s.get('layer') in ('content', 'guide')]
    filler_meta = [s for s in items if s.get('layer') not in ('content', 'guide')]

    # filler/meta 自动标记为 host (废句通常是主持人的)
    for s in filler_meta:
        s['speaker'] = 'host'
        s['cleaned_text'] = s.get('text', '')

    results = []
    total = len(processable)
    for batch_start in range(0, total, batch_size):
        batch = processable[batch_start:batch_start + batch_size]
        batch_end = min(batch_start + batch_size, total)
        print(f"  清洗+识别 [{batch_start+1}-{batch_end}/{total}]...", end=" ", flush=True)

        # 构建输入
        items_text = "\n".join(
            f"[{i}][{s.get('layer','?')}|imp={s.get('importance','?')}] {s['text']}"
            for i, s in enumerate(batch)
        )

        system = (
            "你是采访稿编辑。对下面每行做两件事:\n\n"
            "1. ★清洗文本★: 修正明显的ASR转写错误, 删除口语废词/重复/口误, 补全不完整的句子。"
            "★注意: 只做最小修正, 保留原意和原语气, 不要改写成书面语。\n"
            "2. ★识别说话人★: 判断每句是谁说的。\n"
            "   - host(主持人): 提问、引导、接话、过渡、捧场、简短确认。典型模式: 疑问句、'对''好''嗯'开头的短句\n"
            "   - guest(嘉宾): 回答问题、讲述方法论、分享案例数据、长篇论述。典型模式: 陈述句、数据、故事\n\n"
            "★铁律:\n"
            "- cleaned_text 不能增加原文没有的信息\n"
            "- 只删除口语废词, 不改变句意\n"
            "- 如果文本已是干净的陈述句, cleaned_text 保持原样\n"
            "- speaker 从上下文判断, 不是从文本长度判断\n\n"
            '输出JSON: {"items":[{"index":0,"cleaned_text":"清洗后","speaker":"guest"}]}'
        )

        result = call_llm(system, f"需要处理的句子:\n{items_text}")
        if result and 'items' in result:
            # 建立索引映射
            result_map = {r['index']: r for r in result['items']}
            for i, s in enumerate(batch):
                r = result_map.get(i, {})
                s['cleaned_text'] = r.get('cleaned_text', s['text'])
                s['speaker'] = r.get('speaker', 'guest' if s.get('layer') == 'content' else 'host')
                results.append(s)
                # 验证: cleaned_text 不能为空
                if not s['cleaned_text'] or len(s['cleaned_text'].strip()) < 2:
                    s['cleaned_text'] = s['text']
        else:
            # LLM 失败, 保留原文
            print("⚠️ 失败,保留原文")
            for s in batch:
                s['cleaned_text'] = s['text']
                s['speaker'] = 'guest' if s.get('layer') == 'content' else 'host'
                results.append(s)
            continue

        print(f"✓ ({len(batch)}条)")
        time.sleep(0.5)

    return results + filler_meta


def rebuild_index(project_name, enhanced_file, output_dir):
    """用 cleaned_text 重建 BGE 语义索引, 保留 original_text 用于显示"""
    import numpy as np
    from sentence_transformers import SentenceTransformer

    data = json.load(open(enhanced_file))
    # 只索引 content+guide 层的句子 (跳过 filler/meta)
    indexable = [s for s in data if s.get('layer') in ('content', 'guide')]

    print(f"  索引对象: {len(indexable)}句 (跳过{len(data)-len(indexable)}句filler/meta)")

    # 构建 ~15s 语义单元
    all_segments = []
    chunk = []
    chunk_start = None

    for seg in sorted(indexable, key=lambda s: s.get('start_sec', 0)):
        text = seg.get('cleaned_text', seg.get('text', '')).strip()
        if len(text) < 2: continue
        if chunk_start is None:
            chunk_start = seg['start_sec']
        chunk.append(text)
        # 累积超过 15s 或遇到 guest 说话结束 → 合并
        seg_end = seg.get('start_sec', 0) + max(len(text) // 5, 3)
        if seg_end - chunk_start >= 15 or len(chunk) >= 5:
            merged_text = " ".join(chunk)
            if len(merged_text) > 8:
                # 同时保存 original_text
                orig_texts = [s.get('text', s.get('cleaned_text', '')).strip()
                              for s in indexable
                              if chunk_start <= s.get('start_sec', 0) <= seg_end]
                all_segments.append({
                    "source": "学习新东方",
                    "start": chunk_start,
                    "end": seg_end,
                    "text": merged_text,  # cleaned text for embedding
                    "original_text": " ".join(orig_texts),  # original for display
                })
            chunk = []
            chunk_start = None

    # 剩余片段
    if chunk and len(" ".join(chunk)) > 8:
        seg_end = indexable[-1].get('start_sec', chunk_start) + 10
        all_segments.append({
            "source": "学习新东方",
            "start": chunk_start,
            "end": seg_end,
            "text": " ".join(chunk),
            "original_text": " ".join(s.get('text', s.get('cleaned_text', '')) for s in indexable if s.get('start_sec', 0) >= chunk_start),
        })

    print(f"  语义单元: {len(all_segments)}个 (~15s/单元)")

    # 编码
    print("  加载 BGE 模型...")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    model = SentenceTransformer("BAAI/bge-base-zh-v1.5", local_files_only=True)

    texts = [s["text"] for s in all_segments]
    print(f"  编码 {len(texts)} 段...")
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=True, batch_size=64)

    # 保存
    out_npy = output_dir / "semantic_embeddings.npy"
    out_meta = output_dir / "semantic_metas.json"
    np.save(str(out_npy), embeddings)
    json.dump(all_segments, open(out_meta, "w"), ensure_ascii=False, indent=2)

    print(f"  ✅ 索引: {out_npy} ({embeddings.shape})")
    print(f"  ✅ 元数据: {out_meta} ({len(all_segments)}条)")
    return embeddings, all_segments


def main():
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="杨老师教育")
    parser.add_argument("--skip-clean", action="store_true", help="跳过清洗,只重建索引")
    args = parser.parse_args()

    project_dir = BASE_DIR / args.project
    clean_dir = project_dir / "sources_clean"
    enhanced_file = clean_dir / "classified_enhanced.json"

    if not args.skip_clean:
        # ── Step A: LLM 清洗 + 说话人识别 ──
        print("=" * 50)
        print("Step A: LLM 文本清洗 + 说话人识别")
        print("=" * 50)

        # 找到 classified 文件
        classified_files = list(clean_dir.glob("classified_*.json"))
        if not classified_files:
            print("  ❌ 未找到 classified_*.json, 请先运行 classify_transcript.py")
            return

        cf = classified_files[0]
        print(f"  输入: {cf.name}")
        data = json.load(open(cf))
        print(f"  总计: {len(data)}条 (content:{sum(1 for s in data if s.get('layer')=='content')}, "
              f"guide:{sum(1 for s in data if s.get('layer')=='guide')}, "
              f"filler:{sum(1 for s in data if s.get('layer')=='filler')}, "
              f"meta:{sum(1 for s in data if s.get('layer')=='meta')})")

        t0 = time.time()
        enhanced = clean_and_identify_speakers(data, batch_size=25)
        elapsed = time.time() - t0

        # 统计
        guest = sum(1 for s in enhanced if s.get('speaker') == 'guest')
        host = sum(1 for s in enhanced if s.get('speaker') == 'host')
        cleaned_changed = sum(1 for s in enhanced if s.get('cleaned_text') != s.get('text'))
        print(f"\n  ✅ 完成 ({elapsed:.0f}s):")
        print(f"     guest: {guest}句, host: {host}句")
        print(f"     文本清洗: {cleaned_changed}句被修正")

        json.dump(enhanced, open(enhanced_file, "w"), ensure_ascii=False, indent=2)
        print(f"     输出: {enhanced_file}")
    else:
        if not enhanced_file.exists():
            print(f"  ❌ {enhanced_file} 不存在, 请先运行完整清洗")
            return
        print("  ⏭️  跳过清洗, 使用已有 enhanced 数据")

    # ── Step B: 重建 BGE 索引 ──
    print()
    print("=" * 50)
    print("Step B: 重建 BGE 语义索引 (用 cleaned_text)")
    print("=" * 50)

    rebuild_index(args.project, enhanced_file, project_dir)


if __name__ == "__main__":
    main()
