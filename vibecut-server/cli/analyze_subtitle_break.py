#!/usr/bin/env python3
"""L1.5 DeepSeek 字幕断裂分析 — 与 L1 视觉断点互补, 确认/否决亮度可疑点

对 SUSPECT 场景(已有视觉断点), 用 DeepSeek 分析字幕是否也在同一处断裂:
  - 字幕也断 (MIXED)  → 真混合, 自动标重切
  - 字幕连贯 (SINGLE) → 视觉断点是光线变化, 清除
  - 字幕含糊 (UNCERTAIN) → 人工
输出更新 scene_mix.json: {..., ds_verdict, ds_break_time, ds_reason, final}

用法:
  python3 cli/analyze_subtitle_break.py --ep 32
  python3 cli/analyze_subtitle_break.py                # 全部 SUSPECT
"""

import argparse, json, sys
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from lib.llm import call_deepseek

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SOURCES_DIR = BASE_DIR / "都挺好" / "sources"

PROMPT = """你是《都挺好》的场记。给你一段字幕(带场景时间范围), 判断这段字幕是一个【连贯剧情段】还是【两个不同剧情段拼在一起】。

判断依据:
- 连贯(SINGLE): 同一话题/同一地点/同一组人物持续对话 (一场吵架、一场谈话、一场饭局)
- 断裂(MIXED): 话题明显切换(如从"离婚告知"跳到"请客吃饭"), 或地点/人物组明显变化, 或一段对话结束接另一段不同对话
- 注意: 一场对话内的普通话题转折不算断裂; 只有像"换了场景/换了一批人/换了话题主线"才算

输出 JSON: {"verdict": "SINGLE/MIXED/UNCERTAIN", "break_time": 断裂秒数或null, "reason": "≤25字理由"}"""


def analyze(ep: int, idx: int, subs: list, a: int, b: int) -> dict:
    sub_text = ' | '.join(t for t in subs[:24])
    r = call_deepseek(PROMPT, f"场景[{a}s-{b}s] 字幕: {sub_text}",
                      temperature=0.1, max_tokens=300, timeout=60, label=f"ds_break_ep{ep}")
    if not r.get("ok"):
        return {"ds_verdict": "UNCERTAIN", "ds_reason": f"err:{r.get('error','')[:40]}"}
    import re
    text = (r.get("content") or "")
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if not m:
        return {"ds_verdict": "UNCERTAIN", "ds_reason": "解析失败"}
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"ds_verdict": "UNCERTAIN", "ds_reason": "JSON失败"}
    verdict = str(d.get("verdict", "UNCERTAIN")).strip().upper()
    if verdict not in ("SINGLE", "MIXED", "UNCERTAIN"):
        verdict = "UNCERTAIN"
    bt = d.get("break_time")
    try:
        bt = int(bt) if bt else None
    except (TypeError, ValueError):
        bt = None
    return {"ds_verdict": verdict, "ds_break_time": bt,
            "ds_reason": str(d.get("reason", ""))[:60]}


def combine(l1_verdict: str, ds: dict) -> str:
    """L1 视觉 + DeepSeek 字幕 → final"""
    v = ds.get("ds_verdict", "UNCERTAIN")
    if l1_verdict != "SUSPECT":
        return "CLEAR"
    if v == "MIXED":
        return "MIXED"
    if v == "SINGLE":
        return "SINGLE"
    return "UNCERTAIN"


def process_episode(ep: int):
    mix_file = SOURCES_DIR / f"ep{ep}" / "scene_mix.json"
    sm_file = SOURCES_DIR / f"ep{ep}" / "scene_map.json"
    sub_file = SOURCES_DIR / f"ep{ep}" / "subtitle_result.json"
    if not mix_file.exists():
        return 0
    mix = json.load(open(mix_file))
    scene_map = json.load(open(sm_file))
    subs = json.load(open(sub_file)) if sub_file.exists() else []

    todo = [r for r in mix if r.get("verdict") == "SUSPECT" and not r.get("ds_verdict")]
    done = 0
    for r in todo:
        idx = r["idx"]
        s = scene_map[idx]
        a, b = s['time_range']
        win = [t['text'] for t in subs if t['start'] >= a and t['start'] < b]
        ds = analyze(ep, idx, win, a, b)
        r.update(ds)
        r["final"] = combine(r.get("verdict"), ds)
        done += 1
        print(f"  S{idx} [{a}-{b}] L1={r['verdict']} DS={ds['ds_verdict']} → {r['final']} | {ds.get('ds_reason','')[:30]}")
        json.dump(mix, open(mix_file, "w"), ensure_ascii=False, indent=2)
    return done


def main():
    p = argparse.ArgumentParser(description="DeepSeek 字幕断裂分析")
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
    print(f"\n共分析 {total} 个 SUSPECT 场景")


if __name__ == "__main__":
    main()
