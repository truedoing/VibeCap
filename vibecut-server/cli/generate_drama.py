#!/usr/bin/env python3
"""编剧Agent 命令行生成入口 — 真正生产解说脚本

用法:
  cd vibecut-server
  /opt/anaconda3/bin/python3 cli/generate_drama.py \
      --topic "苏明成人物线:从妈宝到守护者" --target 240 [--task TaskXXXX]

说明:
  - 不指定 --episodes 时走「深层 RAG」自动选集
  - 指定 --episodes "1,21,35,39,41" 时走「浅层 RAG」指定集
  - 产出: 文案脚本.json + tasks/<task>/segments.json + SQLite 同步
"""
import argparse
import sys
import time
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(SERVER_DIR.parent))

from lib.env import load_env
load_env()


def _parse_own_args():
    ap = argparse.ArgumentParser(description="编剧Agent 命令行生成解说脚本")
    ap.add_argument("--topic", required=True, help="选题（如 苏明成人物线:从妈宝到守护者）")
    ap.add_argument("--target", type=int, default=240, help="目标时长(秒)")
    ap.add_argument("--episodes", default=None, help="指定集号，逗号分隔；不填则自动选集")
    ap.add_argument("--task", default=None, help="任务名")
    return ap.parse_args()


OWN_ARGS = _parse_own_args()

# config 模块在 import 时会 parse_args() 消费 sys.argv。
# 这里清掉自定义参数，只留程序名，避免 config 报"unrecognized arguments"。
sys.argv = [sys.argv[0]]

from config import args as cfg_args, PROJECT_DIR, project_name
from agents.drama_script_agents import run_drama_pipeline
from handlers.script_drama import (
    _save_drama_segments, _save_to_task_dir, _sync_to_db,
)


def main():
    args = OWN_ARGS

    # 指定 task
    if args.task:
        cfg_args.task = args.task

    focus_episodes = None
    if args.episodes:
        focus_episodes = [int(x.strip()) for x in args.episodes.split(",") if x.strip()]

    print(f"🎬 编剧Agent · 剧目 {project_name} · 选题 {args.topic}")
    print(f"   目标时长 {args.target}s · "
          f"{'指定集 ' + str(focus_episodes) if focus_episodes else '自动选集(深层RAG)'}")

    t0 = time.time()
    result = run_drama_pipeline(
        project_dir=PROJECT_DIR,
        topic=args.topic,
        focus_episodes=focus_episodes,
        target_duration=args.target,
        emit_progress=lambda step, msg, data=None: print(f"  [{step}] {msg}", flush=True),
    )
    elapsed = time.time() - t0

    if not (result.get("ok") and result.get("segments")):
        print(f"\n❌ 生成失败: {result.get('error', '未产出有效文案')}")
        return 1

    # 保存（复用 handler 的三个保存函数）
    _save_drama_segments(result, args.topic)
    _save_to_task_dir(result)
    _sync_to_db(result)

    print(f"\n✅ 生成完成 · {len(result['segments'])} 段 · "
          f"{result.get('total_chars')} 字 · 预估 {result['time_estimate'].get('estimated_sec')}s "
          f"· 耗时 {elapsed:.0f}s")
    print(f"   封面: {result.get('cover', '')}")
    print(f"   脚本: {PROJECT_DIR}/tasks/文案脚本.json")


if __name__ == "__main__":
    sys.exit(main())
