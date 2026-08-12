#!/usr/bin/env python3
"""
生成低分辨率代理视频（540p），用于 Web 端剪辑定位。
从 1080p 原剧批量转码，为分镜台提供轻量素材。

用法:
  python generate_proxies.py --drama 都挺好 --all
  python generate_proxies.py --drama 都挺好 --ep 1,3,5
  python generate_proxies.py --drama 都挺好 --ep 1-10
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

# ── 配置 ──
DEFAULT_INPUT_DIR = Path("/Users/zgl/解说剪辑/都挺好原剧")
BASE_DIR = Path(__file__).resolve().parent.parent
PROXY_RESOLUTION = (960, 540)  # 宽度x高度
CRF = 28                      # 画质 (0=无损, 51=最差)
PRESET = "fast"               # ffmpeg preset
GOP = 50                      # 关键帧间隔 (帧, 25fps=2秒)
AUDIO_BITRATE = "64k"         # 单声道够用
FPS = 25


def find_episodes(input_dir: Path) -> dict[int, Path]:
    """扫描输入目录，返回 {ep: filepath}"""
    episodes = {}
    for f in sorted(input_dir.iterdir()):
        if not f.is_file():
            continue
        name = f.stem
        # 匹配 "都挺好 01_1080p" 或 "都挺好 01" 格式
        parts = name.split()
        if len(parts) >= 2:
            try:
                ep = int(parts[1].split("_")[0])  # "01_1080p" → 1
                episodes[ep] = f
            except ValueError:
                continue
    return episodes


def generate_proxy(ep: int, src_path: Path, output_dir: Path, overwrite: bool = False) -> dict:
    """生成单集代理视频。返回 metadata dict。"""
    output_path = output_dir / f"都挺好_{ep:02d}_540p.mp4"
    if output_path.exists() and not overwrite:
        print(f"  [跳过] {output_path.name} 已存在")
        # 仍获取 duration 用于 manifest
        probe = get_video_info(src_path)
        return {
            "ep": ep,
            "file": output_path.name,
            "width": PROXY_RESOLUTION[0],
            "height": PROXY_RESOLUTION[1],
            "fps": FPS,
            "duration_sec": probe.get("duration_sec", 0),
            "size_bytes": output_path.stat().st_size,
            "src_file": src_path.name,
        }

    print(f"  [转码] {src_path.name} → {output_path.name} ...", end=" ", flush=True)
    t0 = time.time()

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src_path),
        "-vf", f"scale={PROXY_RESOLUTION[0]}:{PROXY_RESOLUTION[1]},fps={FPS}",
        "-c:v", "libx264",
        "-preset", PRESET,
        "-crf", str(CRF),
        "-g", str(GOP),
        "-keyint_min", str(GOP),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", AUDIO_BITRATE,
        "-ac", "1",
        "-movflags", "+faststart",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - t0

    if result.returncode != 0:
        print(f"失败!")
        print(f"  stderr: {result.stderr[:500]}")
        return None

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"ok ({size_mb:.1f}MB, {elapsed:.0f}s)")

    probe = get_video_info(src_path)
    return {
        "ep": ep,
        "file": output_path.name,
        "width": PROXY_RESOLUTION[0],
        "height": PROXY_RESOLUTION[1],
        "fps": FPS,
        "duration_sec": probe.get("duration_sec", 0),
        "size_bytes": output_path.stat().st_size,
        "src_file": src_path.name,
    }


def get_video_info(path: Path) -> dict:
    """使用 ffprobe 获取视频时长（秒）"""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True,
        )
        return {"duration_sec": float(result.stdout.strip())}
    except Exception:
        return {"duration_sec": 0}


def parse_ep_args(ep_str: str) -> list[int]:
    """解析 --ep 参数: "1,3,5-10" → [1,3,5,6,7,8,9,10]"""
    eps = []
    for part in ep_str.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            eps.extend(range(int(a), int(b) + 1))
        else:
            eps.append(int(part))
    return eps


def main():
    parser = argparse.ArgumentParser(description="生成代理视频")
    parser.add_argument("--drama", default="都挺好", help="剧名")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR, help="1080p 原剧目录")
    parser.add_argument("--ep", help="指定剧集, 如 1,3,5 或 1-10")
    parser.add_argument("--all", action="store_true", help="处理所有剧集")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已有代理")
    parser.add_argument("--dry-run", action="store_true", help="仅显示将要处理的剧集")
    args = parser.parse_args()

    # 输出目录
    drama_dir = BASE_DIR / args.drama
    output_dir = drama_dir / "proxies"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 发现输入文件
    all_eps = find_episodes(args.input_dir)
    if not all_eps:
        print(f"[错误] 在 {args.input_dir} 中未找到任何剧集文件")
        sys.exit(1)

    # 选择剧集
    if args.all:
        selected = sorted(all_eps.keys())
    elif args.ep:
        selected = parse_ep_args(args.ep)
        missing = [e for e in selected if e not in all_eps]
        if missing:
            print(f"[警告] 以下剧集在输入目录中未找到: {missing}")
        selected = [e for e in selected if e in all_eps]
    else:
        print("请指定 --ep 或 --all")
        print(f"可用剧集: {sorted(all_eps.keys())}")
        sys.exit(1)

    if not selected:
        print("[错误] 没有要处理的剧集")
        sys.exit(1)

    print(f"输入: {args.input_dir}")
    print(f"输出: {output_dir}")
    print(f"剧集: {selected}")
    if args.dry_run:
        print("[dry-run] 不执行转码")
        sys.exit(0)

    # 批量转码
    manifest = []
    ok, fail = 0, 0
    for ep in selected:
        src = all_eps[ep]
        meta = generate_proxy(ep, src, output_dir, overwrite=args.overwrite)
        if meta:
            manifest.append(meta)
            ok += 1
        else:
            fail += 1

    # 写入 manifest（增量更新：先读取已有 manifest，合并后写回）
    manifest_path = output_dir / ".proxies_manifest.json"
    existing = {}
    if manifest_path.exists():
        try:
            old = json.loads(manifest_path.read_text())
            for p in old.get("proxies", []):
                existing[p["ep"]] = p
        except Exception:
            pass
    # 合并：新数据覆盖同集号的旧条目
    for m in manifest:
        existing[m["ep"]] = m
    merged = sorted(existing.values(), key=lambda x: x["ep"])
    manifest_path.write_text(
        json.dumps({"drama": args.drama, "proxies": merged, "generated_at": time.time()},
                   ensure_ascii=False, indent=2)
    )

    total_mb = sum(m["size_bytes"] for m in manifest) / (1024 * 1024)
    print(f"\n完成: {ok} 成功, {fail} 失败, 总计 {total_mb:.0f}MB")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
