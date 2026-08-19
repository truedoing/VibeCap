#!/usr/bin/env python3
"""拆分方案生成 — 对 MIXED 场景按断点拆两半, DeepSeek 给每半生成 chars/loc/event

产出 sources/epN/split_plan.json:
  {scene_idx: {time_range, break_time,
    half1: {subs_head, chars, location, event, mood},
    half2: {subs_head, chars, location, event, mood}}}

用法:
  python3 cli/generate_split_plan.py --ep 32
  python3 cli/generate_split_plan.py
"""

import argparse, json, re, sys
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from lib.llm import call_deepseek

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SOURCES_DIR = BASE_DIR / "都挺好" / "sources"

HALF_PROMPT = """你是《都挺好》的场记。这是某场景拆出来的【半段】字幕(连续对话), 时间范围 {a}-{b}s。
根据这段字幕, 生成这半段戏的标注。

铁律:
1. characters = 这半段戏【实际在场】的人物(说话的人+在场的人)。电话里/只被提到的人【不在场】, 不列。
2. 亲属称谓要解析成正式名: 大哥→苏明哲、二哥/明成→苏明成、爸→苏大强(按上下文)、丽丽→朱丽。
3. location = 这段戏实际发生的地点, 从对话推断。
4. event = 这段戏发生的事(≤18字)。
5. mood = 一个词(平静/愤怒/紧张/温馨/悲伤/轻松/无奈/期待等)。
6. 人物用标准全名。

字幕: {subs}

输出 JSON: {{"characters": ["..."], "location": "...", "event": "...", "mood": "..."}}"""


def gen_half(a: int, b: int, subs: list) -> dict:
    text = ' | '.join(subs[:20])
    r = call_deepseek(HALF_PROMPT.format(a=a, b=b, subs=text),
                      "", temperature=0.1, max_tokens=300, timeout=60, label=f"half_{a}")
    if not r.get("ok"):
        return {"error": r.get("error", "")[:50], "subs_head": text[:40]}
    m = re.search(r'\{.*\}', (r.get("content") or ""), re.DOTALL)
    if not m:
        return {"error": "parse", "subs_head": text[:40]}
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"error": "json", "subs_head": text[:40]}
    return {"chars": d.get("characters", []), "location": d.get("location", ""),
            "event": d.get("event", ""), "mood": d.get("mood", ""),
            "subs_head": text[:40]}


def process_episode(ep: int) -> int:
    mix_file = SOURCES_DIR / f"ep{ep}" / "scene_mix.json"
    sm_file = SOURCES_DIR / f"ep{ep}" / "scene_map.json"
    sub_file = SOURCES_DIR / f"ep{ep}" / "subtitle_result.json"
    if not mix_file.exists():
        return 0
    mix = json.load(open(mix_file))
    scene_map = json.load(open(sm_file))
    subs = json.load(open(sub_file)) if sub_file.exists() else []

    plan = json.load(open(SOURCES_DIR / f"ep{ep}" / "split_plan.json")) if (SOURCES_DIR / f"ep{ep}" / "split_plan.json").exists() else {}
    mixed = [r for r in mix if r.get("final") == "MIXED" and str(r["idx"]) not in plan]
    if not mixed:
        return 0

    print(f"EP{ep}: {len(mixed)} 个 MIXED 生成拆分方案...")
    for r in mixed:
        idx = r["idx"]
        s = scene_map[idx]
        a, b = s['time_range']
        bt = r.get("ds_break_time")
        # 断点边界保护: 不能在场景边缘, 否则退化为半段过短
        if bt is None or bt <= a + 15 or bt >= b - 15:
            bt = a + (b - a) // 2
        win = [(t['start'], t['text']) for t in subs if t['start'] >= a and t['start'] < b]
        sub1 = [t for st, t in win if st < bt]
        sub2 = [t for st, t in win if st >= bt]
        h1 = gen_half(a, bt, sub1) if sub1 else {"error": "no_subs", "subs_head": ""}
        h2 = gen_half(bt, b, sub2) if sub2 else {"error": "no_subs", "subs_head": ""}
        plan[str(idx)] = {
            "time_range": [a, b], "break_time": bt,
            "original": {"location": s.get("location"), "characters": s.get("characters"),
                         "event": s.get("event")},
            "half1": {"range": [a, bt], **h1},
            "half2": {"range": [bt, b], **h2},
        }
        print(f"  S{idx} [{a}-{b}] 断{bt}: → [{a}-{bt}] {h1.get('location','?')} | [{bt}-{b}] {h2.get('location','?')}")
        json.dump(plan, open(SOURCES_DIR / f"ep{ep}" / "split_plan.json", "w"),
                  ensure_ascii=False, indent=2)
    return len(mixed)


def main():
    p = argparse.ArgumentParser(description="拆分方案生成")
    p.add_argument("--ep", default=None)
    args = p.parse_args()
    if args.ep:
        eps = [int(e.strip()) for e in args.ep.split(",")]
    else:
        eps = sorted(int(d.name[2:]) for d in SOURCES_DIR.iterdir()
                     if d.is_dir() and d.name.startswith("ep") and d.name[2:].isdigit())
    total = 0
    for ep in eps:
        total += process_episode(ep)
    print(f"\n共生成 {total} 个拆分方案")


if __name__ == "__main__":
    main()
