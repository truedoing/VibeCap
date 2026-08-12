#!/usr/bin/env python3
"""
B2: 从三集原剧中按 clip_plan.json 提取片段 → 拼接为 edited_source.mp4
（替代 video-cut，做最小化裁剪拼接）
"""

import json
import subprocess
import shutil
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DRAMA_DIR = BASE_DIR / os.environ.get("VibeCut_DRAMA", "都挺好")
TASK_DIR = DRAMA_DIR / "tasks" / os.environ.get("VibeCut_TASK", "Task7024")
WORK_DIR = TASK_DIR / "work_dir"
CLIP_PLAN_PATH = WORK_DIR / "final_clip_plan.json"  # 使用智能场景计划
CLIPS_DIR = WORK_DIR / "extracted_clips"
CONCAT_LIST = WORK_DIR / "concat_list.txt"
OUTPUT = WORK_DIR / "edited_source.mp4"

# Source video mapping
SOURCE_VIDEOS = {
    "ep27": TASK_DIR / "原剧" / "都挺好 27_1080p.mp4",
    "ep28": TASK_DIR / "原剧" / "都挺好 28_1080p.mp4",
    "ep29": TASK_DIR / "原剧" / "都挺好 29_1080p.mp4",
}


def main():
    with open(CLIP_PLAN_PATH) as f:
        clip_plan = json.load(f)
    clips = clip_plan.get("clips", clip_plan if isinstance(clip_plan, list) else [])

    print(f"共 {len(clips)} 个片段需要提取")
    CLIPS_DIR.mkdir(exist_ok=True)

    # 清空旧文件
    for f in CLIPS_DIR.glob("clip_*.mp4"):
        f.unlink()

    concat_entries = []

    for i, clip in enumerate(clips):
        source_id = clip["source_id"]
        src_video = SOURCE_VIDEOS.get(source_id)
        if not src_video or not src_video.exists():
            print(f"  ❌ clip_{i}: source '{source_id}' 不存在!")
            continue

        start = clip["start"]
        end = clip["end"]
        duration = end - start

        output_clip = CLIPS_DIR / f"clip_{i:03d}.mp4"
        print(f"  clip_{i:03d}: {source_id} [{start:.1f}s - {end:.1f}s] ({duration:.1f}s)")

        # ffmpeg: 提取视频+原声音频
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", str(src_video),
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            "-avoid_negative_ts", "make_zero",
            str(output_clip)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"    ⚠️ 提取失败: {result.stderr[-200:]}")
            continue

        concat_entries.append(str(output_clip))

    # 写入 concat 列表
    with open(CONCAT_LIST, 'w') as f:
        for entry in concat_entries:
            f.write(f"file '{entry}'\n")

    print(f"\n拼接 {len(concat_entries)} 个片段...")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(CONCAT_LIST),
        "-c", "copy",
        str(OUTPUT)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        size_mb = OUTPUT.stat().st_size / 1024 / 1024
        print(f"✅ edited_source.mp4 → {OUTPUT} ({size_mb:.1f}MB)")

        # 获取时长
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(OUTPUT)],
            capture_output=True, text=True
        )
        dur = float(probe.stdout.strip()) if probe.stdout.strip() else 0
        print(f"   总时长: {dur:.1f}s ({dur/60:.1f}min)")
    else:
        print(f"❌ 拼接失败: {result.stderr[-300:]}")


if __name__ == "__main__":
    main()
