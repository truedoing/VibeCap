#!/usr/bin/env python3
"""
口播采访 Phase A: LLM 分段流水线
输入: sources_clean/classified_*.json
输出: sources_clean/segmented.json (标准化文案)
"""
import json, urllib.request, time, os, argparse
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

def segment(project_name, progress_callback=None):
    """对分类后的 ASR 进行主题分段，生成标准化文案"""
    project_dir = BASE_DIR / project_name
    output_dir = project_dir / "sources_clean"
    output_dir.mkdir(parents=True, exist_ok=True)

    api_key = os.environ.get("MOONSHOT_API_KEY", "")

    all_groups = {}
    total = len(list(output_dir.glob("classified_*.json")))
    done = 0

    for cf in sorted(output_dir.glob("classified_*.json")):
        source_name = cf.stem.replace("classified_", "")
        data = json.load(open(cf))
        # 只取 content 层
        content = [s for s in data if s['layer'] == 'content']
        if not content:
            print(f"  ⚠️ {source_name}: 无 content 数据，跳过")
            continue

        # 均匀采样
        step = max(1, len(content) // 40)
        sampled = content[::step]
        transcript = '\n'.join(f"[{s['start_sec']:.0f}s|imp={s['importance']}] {s['text']}" for s in sampled)

        print(f"  📝 {source_name}: {len(content)} content句, 采样{len(sampled)}句")

        payload = json.dumps({
            "model": "moonshot-v1-8k",
            "messages": [{
                "role": "system",
                "content": (
                    "你是采访素材编辑。将一段采访的精华内容分成5-8个有意义的段落组(segments)。\n"
                    "每个段落是一个完整的'观点单元'，围绕一个子主题展开。\n\n"
                    "输出严格JSON(无markdown):\n"
                    '{"source":"素材名","duration":总秒数,"groups":['
                    '  {"title":"段落标题(≤12字)","summary":"本段讲什么(≤20字)","start_sec":0,"end_sec":120}\n'
                    ']}'
                )
            }, {"role": "user", "content": f"采访内容精华:\n{transcript}"}],
            "temperature": 0.3, "max_tokens": 2000,
        }).encode()

        try:
            req = urllib.request.Request(
                "https://api.moonshot.cn/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            )
            resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
            text = resp["choices"][0]["message"]["content"].strip()
            if text.startswith("```"): text = text.split("\n",1)[1].split("```")[0].strip()
            groups = json.loads(text)

            # 为每个 group 填充 lines
            for g in groups.get("groups", []):
                g["lines"] = [
                    {"start_sec": s["start_sec"], "text": s["text"], "importance": s.get("importance", 3)}
                    for s in content if g["start_sec"] <= s["start_sec"] <= g["end_sec"]
                ]

            all_groups[source_name] = groups

        except Exception as e:
            print(f"  ✗ {source_name} 分段失败: {e}")
            continue

        done += 1
        pct = int(done / max(total, 1) * 100)
        if progress_callback: progress_callback(pct, f"分段 {source_name}")
        time.sleep(0.5)

    # 保存
    output_file = output_dir / "segmented.json"
    json.dump(all_groups, open(output_file, 'w'), ensure_ascii=False, indent=2)

    total_groups = sum(len(v.get("groups", [])) for v in all_groups.values())
    print(f"\n✅ 分段完成: {len(all_groups)} 素材, {total_groups} 组 → {output_file}")
    return all_groups


if __name__ == "__main__":
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="杨老师教育")
    args = parser.parse_args()
    segment(args.project)
