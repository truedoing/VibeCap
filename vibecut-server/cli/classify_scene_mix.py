#!/usr/bin/env python3
"""L2 MiMo 场景分辨 — 对 L1 SUSPECT 场景判定 SINGLE/MIXED/UNCERTAIN

输入: scene_mix.json 中 verdict=SUSPECT 的场景
方法: 取场景 1/4 与 3/4 处两帧 + 窗口字幕 → MiMo 判断是否同一场景(非认人)
输出: 更新 scene_mix.json → {idx, verdict, luminance_diff, l2_verdict, l2_scenes, break_point}

用法:
  python3 cli/classify_scene_mix.py --ep 32
  python3 cli/classify_scene_mix.py               # 全部 SUSPECT
"""

import argparse, base64, json, os, re, subprocess, sys, tempfile, time, urllib.request, glob
from pathlib import Path
import numpy as np
from PIL import Image
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SOURCES_DIR = BASE_DIR / "都挺好" / "sources"
PROXY_DIR = BASE_DIR / "都挺好" / "proxies"


def luminance_series(video: str, a: int, b: int, step: int = 3):
    """窗口内每 step 秒一帧的亮度序列 → (times, values)"""
    tmp = tempfile.mkdtemp()
    subprocess.run(["ffmpeg", "-ss", str(max(0, a)), "-i", video, "-t", str(b - max(0, a)),
                    "-vf", f"fps={1/step},scale=16:9", "-f", "image2", f"{tmp}/f%03d.png"],
                   capture_output=True, timeout=60)
    times, vals = [], []
    for i, f in enumerate(sorted(glob.glob(f"{tmp}/*.png"))):
        times.append(max(0, a) + i * step)
        vals.append(float(np.array(Image.open(f).convert("L")).mean()))
    return times, vals


def find_break_point(video: str, a: int, b: int):
    """找亮度变化最大的断点 → break_time"""
    times, vals = luminance_series(video, a, b)
    if len(vals) < 6:
        return None
    best_k, best_score = None, -1
    for k in range(2, len(vals) - 2):
        left = np.mean(vals[:k]); right = np.mean(vals[k:])
        # 组间差 × 组大小均衡度
        score = abs(left - right) * min(k, len(vals) - k)
        if score > best_score:
            best_score, best_k = score, k
    if best_k is None:
        return None
    return times[best_k]

PROMPT = (
    "这是某场景里两个时间点的画面({t1}s 和 {t2}s)。对话字幕: {subs}\n\n"
    "判断: 这两个画面是【同一个场景】(同一地点/同一组人物/连续时空) 还是【两个不同场景】?\n"
    "若不同, 分别简述各是什么场景(地点/环境/人物大致)。只判断场景异同, 不用确认人物身份。\n"
    "输出 JSON: {{\"verdict\": \"SINGLE/MIXED/UNCERTAIN\", \"scene1\": \"简述\", \"scene2\": \"简述\"}}"
)


def video_for_ep(ep):
    for res in (540, 360):
        p = PROXY_DIR / f"都挺好_{ep:02d}_{res}p.mp4"
        if p.exists():
            return str(p)
    raise FileNotFoundError(f"EP{ep} 代理视频不存在")


def frame_b64(video, t):
    r = subprocess.run(["ffmpeg", "-ss", str(t), "-i", video, "-frames:v", "1",
                        "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, timeout=30)
    return base64.b64encode(r.stdout).decode()


def mimo_classify(video, t1, t2, subs):
    prompt = PROMPT.format(t1=t1, t2=t2, subs=subs[:400])
    content = [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{frame_b64(video, t1)}"}},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{frame_b64(video, t2)}"}},
        {"type": "text", "text": prompt},
    ]
    payload = json.dumps({"model": "mimo-v2.5", "messages": [{"role": "user", "content": content}],
                          "max_tokens": 800}).encode()
    import time
    for attempt in range(3):
        try:
            req = urllib.request.Request("https://api.xiaomimimo.com/v1/chat/completions", data=payload,
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": f'Bearer {os.environ.get("MIMO_API_KEY", "")}'})
            resp = json.loads(urllib.request.urlopen(req, timeout=90).read())
            raw = resp["choices"][0]["message"].get("content", "") or resp["choices"][0]["message"].get("reasoning_content", "")
            import re
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if m:
                try:
                    d = json.loads(m.group(0))
                    verdict = str(d.get("verdict", "UNCERTAIN")).strip().upper()
                    if verdict not in ("SINGLE", "MIXED", "UNCERTAIN"):
                        verdict = "UNCERTAIN"
                    return {"verdict": verdict,
                            "scene1": str(d.get("scene1", "") or ""), "scene2": str(d.get("scene2", "") or "")}
                except json.JSONDecodeError:
                    pass
            # 无法解析 → 若文本里有"同一个场景"字样则判 SINGLE
            if "同一" in raw and "不同" not in raw:
                return {"verdict": "SINGLE", "scene1": raw[:100], "scene2": ""}
            return {"verdict": "UNCERTAIN", "scene1": raw[:100], "scene2": ""}
        except Exception as e:
            if attempt == 2:
                print(f"    ⚠ 重试3次失败: {str(e)[:60]}")
                return {"verdict": "UNCERTAIN", "scene1": f"error:{str(e)[:50]}", "scene2": ""}
            time.sleep(3 * (attempt + 1))
    return {"verdict": "UNCERTAIN", "scene1": "", "scene2": ""}


def classify_episode(ep: int):
    mix_file = SOURCES_DIR / f"ep{ep}" / "scene_mix.json"
    sm_file = SOURCES_DIR / f"ep{ep}" / "scene_map.json"
    sub_file = SOURCES_DIR / f"ep{ep}" / "subtitle_result.json"
    if not mix_file.exists():
        print(f"EP{ep}: 无 scene_mix.json, 先跑 L1")
        return
    mix = json.load(open(mix_file))
    scene_map = json.load(open(sm_file))
    subs = json.load(open(sub_file)) if sub_file.exists() else []
    video = video_for_ep(ep)

    suspect = [r for r in mix if r.get("verdict") == "SUSPECT" and not r.get("l2_verdict")]
    if not suspect:
        print(f"EP{ep}: 无待处理 SUSPECT")
        return

    print(f"EP{ep}: {len(suspect)} 个 SUSPECT 场景进 L2...")
    for r in suspect:
        idx = r["idx"]
        s = scene_map[idx]
        a, b = s['time_range']
        # 亮度断点两侧取帧 (确认亮度标出的可疑点是否真场景分界)
        break_t = find_break_point(video, a, b)
        if break_t is None:
            t1, t2 = a + (b - a) // 4, a + 3 * (b - a) // 4
        else:
            t1, t2 = max(a + 2, break_t - 3), min(b - 2, break_t + 3)
        win = [t['text'] for t in subs if t['start'] >= a and t['start'] < b]
        result = mimo_classify(video, t1, t2, ' | '.join(win[:10]))
        r["l2_verdict"] = result.get("verdict", "UNCERTAIN")
        r["l2_scenes"] = [result.get("scene1", ""), result.get("scene2", "")]
        r["break_point"] = (t1, t2)
        print(f"  S{idx} [{a}-{b}] 断点@{break_t}s→帧{t1}/{t2}: L2={r['l2_verdict']} | {r['l2_scenes'][0][:30]} / {r['l2_scenes'][1][:30]}")
        json.dump(mix, open(mix_file, "w"), ensure_ascii=False, indent=2)


def main():
    p = argparse.ArgumentParser(description="L2 MiMo 场景分辨")
    p.add_argument("--ep", default=None)
    args = p.parse_args()
    if args.ep:
        eps = [int(e.strip()) for e in args.ep.split(",")]
    else:
        eps = sorted(int(d.name[2:]) for d in SOURCES_DIR.iterdir()
                     if d.is_dir() and d.name.startswith("ep") and d.name[2:].isdigit())
    for ep in eps:
        classify_episode(ep)


if __name__ == "__main__":
    main()
