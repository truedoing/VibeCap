#!/usr/bin/env python3
"""L1 本地场景质检 — 亮度 regime 检测（已验证: S6 能标, 单场景不标）

对每个 scene_map 场景, 抽取窗口内每 3s 一帧的亮度(L通道均值),
比较前 1/3 与后 1/3 平均亮度, 差 > 阈值 → SUSPECT(可能混合窗口), 进 L2。

用法:
  python3 cli/score_scene_mix.py --ep 32
  python3 cli/score_scene_mix.py              # 全部
  python3 cli/score_scene_mix.py --threshold 20
"""

import argparse, glob, json, subprocess, tempfile
from pathlib import Path
import numpy as np
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # → VIBECAP/
SOURCES_DIR = BASE_DIR / "都挺好" / "sources"
PROXY_DIR = BASE_DIR / "都挺好" / "proxies"


def video_for_ep(ep: int) -> str:
    for res in (540, 360):
        p = PROXY_DIR / f"都挺好_{ep:02d}_{res}p.mp4"
        if p.exists():
            return str(p)
    raise FileNotFoundError(f"EP{ep} 代理视频不存在")


def luminance_series(video: str, a: int, b: int, step: int = 3) -> np.ndarray:
    """窗口内每 step 秒抽一帧, 返回 L 通道均值序列"""
    tmp = tempfile.mkdtemp()
    subprocess.run(["ffmpeg", "-ss", str(max(0, a)), "-i", video, "-t", str(b - max(0, a)),
                    "-vf", f"fps={1/step},scale=16:9", "-f", "image2", f"{tmp}/f%03d.png"],
                   capture_output=True, timeout=60)
    vals = []
    for f in sorted(glob.glob(f"{tmp}/*.png")):
        vals.append(float(np.array(Image.open(f).convert("L")).mean()))
    return np.array(vals) if vals else np.array([])


def score_episode(ep: int, threshold: float) -> list:
    video = video_for_ep(ep)
    sm_file = SOURCES_DIR / f"ep{ep}" / "scene_map.json"
    if not sm_file.exists():
        print(f"EP{ep}: 无 scene_map")
        return []
    scene_map = json.load(open(sm_file))

    results = []
    for i, s in enumerate(scene_map):
        a, b = s['time_range']
        v = luminance_series(video, a, b)
        if len(v) < 9:
            results.append({"idx": i, "verdict": "TOO_SHORT", "luminance_diff": None})
            continue
        n3 = len(v) // 3
        diff = abs(v[:n3].mean() - v[-n3:].mean())
        verdict = "SUSPECT" if diff > threshold else "CLEAR"
        results.append({"idx": i, "verdict": verdict,
                        "luminance_diff": round(float(diff), 1),
                        "time_range": s['time_range'],
                        "location": s.get('location', '')})
    return results


def main():
    p = argparse.ArgumentParser(description="L1 亮度 regime 场景质检")
    p.add_argument("--ep", default=None)
    p.add_argument("--threshold", type=float, default=20.0)
    p.add_argument("--save", action="store_true", help="落盘 scene_mix.json")
    args = p.parse_args()

    if args.ep:
        eps = [int(e.strip()) for e in args.ep.split(",")]
    else:
        eps = sorted(int(d.name[2:]) for d in SOURCES_DIR.iterdir()
                     if d.is_dir() and d.name.startswith("ep") and d.name[2:].isdigit())

    total, suspect = 0, 0
    for ep in eps:
        results = score_episode(ep, args.threshold)
        s_cnt = sum(1 for r in results if r["verdict"] == "SUSPECT")
        total += len(results)
        suspect += s_cnt
        print(f"EP{ep}: {len(results)} 场景, SUSPECT {s_cnt}")
        for r in results:
            if r["verdict"] == "SUSPECT":
                print(f"    S{r['idx']} [{r['time_range'][0]}-{r['time_range'][1]}] 亮度差={r['luminance_diff']} @ {r['location']}")
        if args.save and results:
            json.dump(results, open(SOURCES_DIR / f"ep{ep}" / "scene_mix.json", "w"),
                      ensure_ascii=False, indent=2)

    print(f"\n总计: {total} 场景, SUSPECT {suspect} ({suspect/max(total,1)*100:.0f}%) → 进 L2 MiMo 分辨")


if __name__ == "__main__":
    main()
