#!/usr/bin/env python3
"""VLM 独立辨认重跑 — 用帧 + 参考照 + 字幕辨认在场人物 + 生成新描述

斩断回声链：prompt 中【不出现 scene_map 的 characters】，MiMo 靠
  - verify_frames（定向抽帧，每场景 3 张）
  - character_portraits 参考照（身份比对）
  - 场景窗口 SRT 字幕（身份锚）
独立判断「谁实际在场」，并生成新画面描述。

输出: sources/epN/vlm_verify_cache_v4.json
  {idx: {verified_chars, visual_summary, shot_size, ..., frames: [文件名], subtitle_count}}
  不覆盖旧 v3 缓存，可回滚。

用法:
  python3 cli/rerun_vlm_verify.py --ep 32            # 单集试点
  python3 cli/rerun_vlm_verify.py --ep 32 --refs all # 参考照全量
  python3 cli/rerun_vlm_verify.py --refs core        # 全量(默认 core 参考照)
"""

import argparse, base64, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import os, time, urllib.request

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # → VIBECAP/
SOURCES_DIR = BASE_DIR / "都挺好" / "sources"
PORTRAITS_DIR = BASE_DIR / "都挺好" / "character_portraits"

CORE_CHARS = ['苏大强', '苏明哲', '苏明成', '苏明玉', '朱丽', '吴非', '小蔡', '老聂']
MIMO_MODEL = "mimo-v2.5"

VERIFY_PROMPT = """你是《都挺好》的场记兼画面分析师。给你这个场景的几张画面帧、角色参考照、和该场景的对话字幕。

【任务】判断画面里【实际在场】的人物，并描述画面。

★ 铁律（最重要）：
1. 在场人物 = 画面里实际出现的人。判断依据：参考照比对 + 画面中人的动作/位置 + 字幕中"谁在说话"。
2. 【不在场】的人绝不列入：只在字幕里被提到、打电话听到、回忆里的人，都不在场。
   例：字幕说"打电话给明哲"→ 明哲不在画面里，不列。字幕说"向苏明成解释"→ 说话对象若不在画面，不列。
3. 你没有任何现成的人物标注，全靠画面+字幕独立判断。宁缺毋滥，看不清就不写。
4. 人物用标准全名：苏大强/苏明哲/苏明成/苏明玉/朱丽/吴非/小蔡/老聂，以及配角（周姐/柳青/小蒙/石天冬/老聂/舅舅等）。

【画面描述】输出该场景的视觉信息：
- visual_summary: ≤80字，描述在场人物的动作/表情/关系/氛围
- shot_size/composition/angle/lighting: 景别/构图/机位/光线
- emotional_tone: 情绪标签(≤8字)  intensity: 1-5
- actions: 动作数组

输出严格 JSON（不要 markdown）：
{"verified_chars": ["苏明成", "苏大强"], "visual_summary": "...", "shot_size": "中景",
 "composition": "双人", "angle": "平视", "emotional_tone": "紧张", "intensity": 4,
 "lighting": "自然光", "actions": ["拍桌"]}"""


def b64(p):
    return base64.b64encode(open(p, 'rb').read()).decode()


def load_references(mode: str) -> list:
    """加载参考照 → [(name, b64)]"""
    refs = []
    if mode == "all":
        chars = sorted(d.name for d in PORTRAITS_DIR.iterdir() if d.is_dir())
    else:  # core
        chars = CORE_CHARS
    for name in chars:
        d = PORTRAITS_DIR / name
        if not d.is_dir():
            continue
        imgs = sorted(d.glob("*.jpg")) or sorted(d.glob("*.png")) or sorted(d.glob("*.jpeg"))
        for img in imgs[:2]:  # 每人最多2张参考
            refs.append((name, b64(img)))
    return refs


def analyze_scene(ep: int, idx: int, scene: dict, subtitles: list,
                  refs: list, verify_frames_dir: Path, retries: int = 3) -> dict:
    """分析单个场景 → {verified_chars, visual_summary, frames, ...}"""
    frames = sorted((verify_frames_dir / f"scene_{idx:03d}_*.jpg").parent.glob(f"scene_{idx:03d}_*.jpg"))
    if not frames:
        return {"error": f"S{idx} 无 verify_frames", "verified_chars": [], "frames": []}

    # 字幕窗口
    a, b = scene['time_range']
    win = [t['text'] for t in subtitles if t['start'] >= a and t['start'] < b]
    sub_text = ' | '.join(win[:12])[:600]

    content = []
    # 参考照
    for name, img in refs:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}})
    # 场景帧
    for f in frames:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64(f)}"}})
    content.append({"type": "text", "text": f"场景 [{a}s-{b}s] 对话字幕: {sub_text}\n请判断在场人物并描述画面。"})

    api_key = os.environ.get("MIMO_API_KEY", "")
    api_url = os.environ.get("MIMO_API_URL", "https://api.xiaomimimo.com/v1")
    if not api_key:
        return {"error": "MIMO_API_KEY 未配置", "verified_chars": [], "frames": [f.name for f in frames]}

    for attempt in range(retries):
        try:
            payload = json.dumps({"model": MIMO_MODEL,
                                  "messages": [{"role": "user", "content": content}],
                                  "max_tokens": 2000}).encode()
            req = urllib.request.Request(f"{api_url}/chat/completions", data=payload,
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": f"Bearer {api_key}"})
            resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
            raw = resp["choices"][0]["message"].get("content", "") or ""
            if not raw.strip():
                raw = resp["choices"][0]["message"].get("reasoning_content", "") or ""
            data = parse_vlm(raw)
            if data:
                data["frames"] = [f.name for f in frames]
                data["subtitle_count"] = len(win)
                return data
            print(f"  ⚠ S{idx} 解析失败, 重试")
            time.sleep(2)
        except Exception as e:
            if attempt == retries - 1:
                return {"error": str(e)[:100], "verified_chars": [], "frames": [f.name for f in frames]}
            time.sleep(3)
    return {"error": "unknown", "verified_chars": [], "frames": [f.name for f in frames]}


def parse_vlm(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m:
        return {}
    try:
        d = json.loads(m.group(0))
        return d if isinstance(d, dict) else {}
    except json.JSONDecodeError:
        return {}


def rerun_episode(ep: int, refs_mode: str) -> int:
    sm_file = SOURCES_DIR / f"ep{ep}" / "scene_map.json"
    sub_file = SOURCES_DIR / f"ep{ep}" / "subtitle_result.json"
    vf_dir = SOURCES_DIR / f"ep{ep}" / "verify_frames"
    if not sm_file.exists() or not vf_dir.exists():
        print(f"EP{ep}: 缺 scene_map/verify_frames, 先跑 extract_scene_frames")
        return 0
    scene_map = json.load(open(sm_file))
    subtitles = json.load(open(sub_file)) if sub_file.exists() else []
    refs = load_references(refs_mode)
    print(f"EP{ep}: {len(scene_map)} 场景, {len(refs)} 张参考照, 串行分析...")

    out_file = SOURCES_DIR / f"ep{ep}" / "vlm_verify_cache_v4.json"
    cache = json.load(open(out_file)) if out_file.exists() else {}

    for i, s in enumerate(scene_map):
        key = str(i)
        if key in cache and cache[key].get("verified_chars"):
            continue  # 已分析
        r = analyze_scene(ep, i, s, subtitles, refs, vf_dir)
        cache[key] = r
        if r.get("verified_chars"):
            print(f"  S{i}: {r['verified_chars']} | {r.get('visual_summary','')[:40]}")
        else:
            print(f"  S{i}: ❌ {r.get('error','失败')}")
        json.dump(cache, open(out_file, "w"), ensure_ascii=False, indent=2)  # 增量落盘
        time.sleep(0.3)

    ok = sum(1 for v in cache.values() if v.get("verified_chars"))
    print(f"EP{ep}: 完成 {ok}/{len(scene_map)} 场景 → {out_file.name}")
    return ok


def main():
    p = argparse.ArgumentParser(description="VLM 独立辨认重跑")
    p.add_argument("--ep", default=None, help="单集/多集")
    p.add_argument("--refs", default="core", choices=["core", "all"], help="参考照范围")
    args = p.parse_args()
    if args.ep:
        eps = [int(e.strip()) for e in args.ep.split(",")]
    else:
        eps = sorted(int(d.name[2:]) for d in SOURCES_DIR.iterdir()
                     if d.is_dir() and d.name.startswith("ep") and d.name[2:].isdigit())
    for ep in eps:
        rerun_episode(ep, args.refs)


if __name__ == "__main__":
    main()
