#!/usr/bin/env python3
"""新半段 VLM 重跑 — 为拆分产生的 needs_vlm 场景生成画面描述

输入: 场景的 chars/location/event (拆分后正确) + 定向帧 + 字幕
输出: visual_summary/shot_size/... 写入 vlm_seg_cache_v3.json

用法:
  python3 cli/rerun_split_vlm.py --ep 32
  python3 cli/rerun_split_vlm.py
"""

import argparse, base64, glob, json, os, re, subprocess, sys, tempfile, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SOURCES_DIR = BASE_DIR / "都挺好" / "sources"
PROXY_DIR = BASE_DIR / "都挺好" / "proxies"


def video_for_ep(ep):
    for res in (540, 360):
        p = PROXY_DIR / f"都挺好_{ep:02d}_{res}p.mp4"
        if p.exists():
            return str(p)
    raise FileNotFoundError(f"EP{ep} 代理视频不存在")


def extract_frames(video, a, b, n=3):
    """在 [a,b] 内抽 n 帧 → 返回 b64 列表"""
    tmp = tempfile.mkdtemp()
    points = [a + (b - a) * k // (n + 1) for k in range(1, n + 1)]
    out = []
    for i, t in enumerate(points):
        r = subprocess.run(["ffmpeg", "-ss", str(t), "-i", video, "-frames:v", "1",
                            "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, timeout=30)
        out.append(base64.b64encode(r.stdout).decode())
    return out


def vlm_scene(video, a, b, chars, loc, event, subs):
    frames = extract_frames(video, a, b)
    prompt = (
        f"场景 [{a}s-{b}s]。对话字幕: {subs[:300]}\n\n"
        "描述这个画面场景。输出 JSON (不要markdown): "
        "{\"visual_summary\": \"≤60字画面描述\", \"shot_size\": \"特写/近景/中景/全景/远景\", "
        "\"composition\": \"单人/双人/三人/群像\", \"angle\": \"平视/俯拍/仰拍\", "
        "\"emotional_tone\": \"情绪\", \"intensity\": 1-5, \"lighting\": \"自然光/暖调/冷调/暗调\", "
        "\"actions\": [\"动作\"]}"
    )
    content = [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{f}"}} for f in frames]
    content.append({"type": "text", "text": prompt})
    payload = json.dumps({"model": "mimo-v2.5", "messages": [{"role": "user", "content": content}],
                          "max_tokens": 800}).encode()
    for attempt in range(3):
        try:
            req = urllib.request.Request("https://api.xiaomimimo.com/v1/chat/completions", data=payload,
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": f'Bearer {os.environ.get("MIMO_API_KEY", "")}'})
            resp = json.loads(urllib.request.urlopen(req, timeout=90).read())
            raw = resp["choices"][0]["message"].get("content", "") or resp["choices"][0]["message"].get("reasoning_content", "")
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if m:
                try:
                    d = json.loads(m.group(0))
                    return {"visual_summary": str(d.get("visual_summary", ""))[:200],
                            "shot_size": d.get("shot_size", ""), "composition": d.get("composition", ""),
                            "angle": d.get("angle", ""), "emotional_tone": d.get("emotional_tone", ""),
                            "intensity": d.get("intensity", 3), "lighting": d.get("lighting", ""),
                            "actions": d.get("actions", [])}
                except json.JSONDecodeError:
                    pass
            return {"visual_summary": raw[:200], "error": "parse"}
        except Exception as e:
            if attempt == 2:
                return {"visual_summary": "", "error": str(e)[:60]}
            time.sleep(3)
    return {"visual_summary": "", "error": "unknown"}


def rerun_episode(ep: int, workers: int = 4) -> int:
    ep_dir = SOURCES_DIR / f"ep{ep}"
    sm_file = ep_dir / "scene_map.json"
    vlm_file = ep_dir / "vlm_seg_cache_v3.json"
    sub_file = ep_dir / "subtitle_result.json"
    if not sm_file.exists() or not vlm_file.exists():
        return 0
    scene_map = json.load(open(sm_file))
    vlm = json.load(open(vlm_file))
    subs = json.load(open(sub_file)) if sub_file.exists() else []
    video = video_for_ep(ep)

    todo = [i for i, v in vlm.items() if v.get("needs_vlm")]
    if not todo:
        return 0
    print(f"EP{ep}: {len(todo)} 个新半段跑 VLM ({workers} 并发)...", flush=True)

    def work(i):
        s = scene_map[int(i)]
        a, b = s['time_range']
        win = [t['text'] for t in subs if t['start'] >= a and t['start'] < b]
        r = vlm_scene(video, a, b, s.get('characters', []), s.get('location', ''),
                      s.get('event', ''), ' | '.join(win[:10]))
        r["scene_map_index"] = int(i)
        r["start"] = a; r["end"] = b
        return i, r

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(work, i): i for i in sorted(todo, key=int)}
        for fut in as_completed(futures):
            i, r = fut.result()
            vlm[i] = r
            json.dump(vlm, open(vlm_file, "w"), ensure_ascii=False, indent=2)
            print(f"  S{i} [{r['start']}-{r['end']}]: {r.get('visual_summary','')[:40]}", flush=True)
    return len(todo)


def main():
    p = argparse.ArgumentParser(description="新半段 VLM 重跑 (并发)")
    p.add_argument("--ep", default=None)
    p.add_argument("--workers", type=int, default=4, help="并发数 (默认4)")
    args = p.parse_args()
    if args.ep:
        eps = [int(e.strip()) for e in args.ep.split(",")]
    else:
        eps = sorted(int(d.name[2:]) for d in SOURCES_DIR.iterdir()
                     if d.is_dir() and d.name.startswith("ep") and d.name[2:].isdigit())
    total = 0
    for ep in eps:
        total += rerun_episode(ep, args.workers)
    print(f"\n共重跑 {total} 个新半段 VLM")


if __name__ == "__main__":
    main()
