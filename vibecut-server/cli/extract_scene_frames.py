#!/usr/bin/env python3
"""定向抽帧 — 只抽每个场景要分析的帧（不抽全量）

从代理视频按场景 time_range 直接抽 1/4, 1/2, 3/4 位置的帧，
落盘到 sources/epN/verify_frames/scene_{idx}_{n}.jpg。

为什么不用全量 fps=1 抽帧：
  - frames/ 全量目录只被 VLM 分析自己用，前端用代理视频
  - 17 集旧全量帧不完整（只到 ~900s），但定向抽帧直接从视频按时间抽，不受影响
  - 省 90%+ 抽帧量

用法:
  python3 cli/extract_scene_frames.py --ep 32          # 单集
  python3 cli/extract_scene_frames.py                  # 全部
  python3 cli/extract_scene_frames.py --ep 32 --frames 3  # 每场景帧数(默认3)
"""

import argparse, json, subprocess, sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # → VIBECAP/
DRAMA_DIR = BASE_DIR / "都挺好"
SOURCES_DIR = DRAMA_DIR / "sources"
PROXY_DIR = DRAMA_DIR / "proxies"


def run_ffmpeg(cmd, timeout=60):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {r.stderr[-200:]}")
    return r


def video_for_ep(ep: int) -> Path:
    """找该集代理视频(优先540p)"""
    for res in (540, 360):
        p = PROXY_DIR / f"都挺好_{ep:02d}_{res}p.mp4"
        if p.exists():
            return p
    raise FileNotFoundError(f"EP{ep} 代理视频不存在")


def extract_scene_frames(ep: int, n_frames: int = 3, force: bool = False) -> int:
    sm_file = SOURCES_DIR / f"ep{ep}" / "scene_map.json"
    if not sm_file.exists():
        print(f"EP{ep}: 无 scene_map, 跳过")
        return 0
    scene_map = json.load(open(sm_file))
    out_dir = SOURCES_DIR / f"ep{ep}" / "verify_frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    video = video_for_ep(ep)

    extracted = 0
    for i, s in enumerate(scene_map):
        start, end = s['time_range']
        # 采样位置: 等分 n_frames 个点 (避开两端边界)
        times = []
        for k in range(1, n_frames + 1):
            t = round(start + (end - start) * k / (n_frames + 1))
            if t >= start and t < end:
                times.append(t)
        for n, t in enumerate(times):
            out = out_dir / f"scene_{i:03d}_{n}.jpg"
            if out.exists() and not force:
                continue
            try:
                run_ffmpeg(["ffmpeg", "-y", "-ss", str(t), "-i", str(video),
                            "-frames:v", "1", "-q:v", "3", str(out)])
                extracted += 1
            except RuntimeError as e:
                print(f"  ⚠ S{i} t={t}s: {str(e)[:60]}")
    print(f"EP{ep}: {len(scene_map)} 场景 → {out_dir} 新增/覆盖 {extracted} 帧")
    return extracted


def main():
    p = argparse.ArgumentParser(description="定向抽帧")
    p.add_argument("--ep", default=None, help="单集/多集 (逗号分隔)")
    p.add_argument("--frames", type=int, default=3, help="每场景帧数 (默认3)")
    p.add_argument("--force", action="store_true", help="覆盖已有帧")
    args = p.parse_args()

    if args.ep:
        eps = [int(e.strip()) for e in args.ep.split(",")]
    else:
        eps = sorted(int(d.name[2:]) for d in SOURCES_DIR.iterdir()
                     if d.is_dir() and d.name.startswith("ep") and d.name[2:].isdigit())

    total = 0
    for ep in eps:
        total += extract_scene_frames(ep, args.frames, args.force)
    print(f"\n共抽取 {total} 帧")


if __name__ == "__main__":
    main()
