#!/usr/bin/env python3
"""
口播采访 Phase A: LLM 分类流水线
输入: sources/asr_*.json
输出: sources_clean/classified.json
"""
import json, urllib.request, time, os, sys, argparse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

def load_env():
    env_file = Path(__file__).resolve().parent / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")

def classify(project_name, progress_callback=None):
    """对项目所有 ASR 文件进行 LLM 分类"""
    project_dir = BASE_DIR / project_name
    sources_dir = project_dir / "sources"
    output_dir = project_dir / "sources_clean"
    output_dir.mkdir(parents=True, exist_ok=True)

    api_key = os.environ.get("MOONSHOT_API_KEY", "")
    if not api_key:
        print("❌ 未配置 MOONSHOT_API_KEY")
        return None

    all_results = {}

    for asr_file in sorted(sources_dir.glob("asr_*.json")):
        source_name = asr_file.stem.replace("asr_", "")
        print(f"\n📝 {source_name}")
        data = json.load(open(asr_file))
        classified = []
        chunk_size = 30
        total_chunks = (len(data) + chunk_size - 1) // chunk_size

        for ci in range(0, len(data), chunk_size):
            chunk = data[ci:ci + chunk_size]
            lines = '\n'.join(f"[{s.get('start', s.get('start_sec', 0)):.1f}s] {s['text']}" for s in chunk)

            payload = json.dumps({
                "model": "moonshot-v1-8k",
                "messages": [{
                    "role": "system",
                    "content": (
                        "你是采访素材分类助手。对每行标注 layer 和 importance。\n\n"
                        "layer 规则:\n"
                        "  content = 被采访者正式讲述知识/经验/观点(流畅完整)\n"
                        "  meta = 讨论怎么讲/自我评价/重述尝试/商量要不要重拍/剪辑方向\n"
                        "  guide = 主持人引导/短问句/肯定词/方向建议\n"
                        "  filler = 单字填充/极短无意义句/卡壳\n\n"
                        "importance: 5=金句hook, 4=核心观点/数据, 3=细节, 2=过渡, 1=冗余\n"
                        "meta/guide/filler类默认importance<=2\n\n"
                        "输出严格JSON(无markdown):\n"
                        '{"results":[{"start_sec":0.0,"text":"原文","layer":"content","importance":4}]}'
                    )
                }, {"role": "user", "content": lines}],
                "temperature": 0.2, "max_tokens": 2000,
            }).encode()

            for attempt in range(3):
                try:
                    req = urllib.request.Request(
                        "https://api.moonshot.cn/v1/chat/completions",
                        data=payload,
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
                    )
                    resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
                    text = resp["choices"][0]["message"]["content"].strip()
                    if text.startswith("```"): text = text.split("\n",1)[1].split("```")[0].strip()
                    result = json.loads(text)
                    classified.extend(result["results"])
                    break
                except Exception as e:
                    if attempt == 2:
                        print(f"  ✗ chunk {ci} failed: {e}")
                        for s in chunk:
                            classified.append({"start_sec": s["start"], "text": s["text"], "layer": "meta", "importance": 2})
                    time.sleep(2)

            chunk_num = ci // chunk_size + 1
            pct = min(99, int(chunk_num / total_chunks * 100))
            print(f"  [{chunk_num}/{total_chunks}] {pct}%", end='\r')
            if progress_callback:
                progress_callback(pct, f"分类 {source_name} {chunk_num}/{total_chunks}")
            time.sleep(0.3)

        # 统计
        stats = {}
        for s in classified: stats[s['layer']] = stats.get(s['layer'], 0) + 1
        print(f"\n  ✅ {source_name}: {len(classified)}段 {stats}")

        output_file = output_dir / f"classified_{source_name}.json"
        json.dump(classified, open(output_file, 'w'), ensure_ascii=False, indent=2)
        all_results[source_name] = {"file": str(output_file), "count": len(classified), "stats": stats}

    # 汇总清单
    manifest = output_dir / "classified_manifest.json"
    json.dump(all_results, open(manifest, 'w'), ensure_ascii=False, indent=2)
    print(f"\n✅ 分类完成: {len(all_results)} 个素材 → {output_dir}")
    return all_results


if __name__ == "__main__":
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="杨老师教育")
    args = parser.parse_args()
    classify(args.project)
