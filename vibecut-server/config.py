"""VibeCut 配置中心 — 统一 CLI 参数、项目配置、路径解析"""

import argparse
import json
import os
from pathlib import Path


# ── 基础路径 ──
BASE_DIR = Path(__file__).resolve().parent.parent
SERVER_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "vibecut-web" / "dist"
PYTHON_BIN = "/opt/anaconda3/bin/python3"


# ── CLI 参数 ──
def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="VibeCut 后端服务")
    parser.add_argument("--project", default=os.environ.get("VibeCut_PROJECT", ""),
                        help="项目名")
    parser.add_argument("--drama", default=os.environ.get("VibeCut_DRAMA", ""),
                        help="电视剧名 (兼容旧参数)")
    parser.add_argument("--task", default=os.environ.get("VibeCut_TASK", "Task7024"),
                        help="任务名")
    parser.add_argument("--port", type=int, default=8765, help="端口")
    return parser.parse_args(argv)


args = parse_args()

# ── 项目名 & 类型 ──
project_name = args.project or args.drama or "都挺好"
project_type = "drama"  # drama | interview
project_config = {}

PROJECT_DIR = BASE_DIR / project_name

# 加载项目配置
cfg_path = BASE_DIR / "projects" / f"{project_name}.json"
if cfg_path.exists():
    project_config = json.load(open(cfg_path))
    project_type = project_config.get("type", "drama")
    print(f"[project] {project_name} (type={project_type})")
else:
    print(f"[project] {project_name} (legacy mode, no project config)")


# ── 路径解析 ──
def resolve_task_dir(task_name: str = None) -> Path:
    name = task_name or args.task
    return PROJECT_DIR / "tasks" / name


def resolve_clip_dir(task_name: str = None) -> Path:
    d = resolve_task_dir(task_name) / "素材clips"
    d.mkdir(exist_ok=True)
    return d


def resolve_work_dir(task_name: str = None) -> Path:
    d = resolve_task_dir(task_name) / "work_dir"
    d.mkdir(exist_ok=True)
    return d


# ── 通用路径 ──
SOURCES_DIR = PROJECT_DIR / "sources"
PROXY_DIR = PROJECT_DIR / "proxies"
PROXY_MANIFEST = PROXY_DIR / ".proxies_manifest.json"
CLEAN_DIR = PROJECT_DIR / "sources_clean"
PROXY_DIR.mkdir(exist_ok=True)

# 索引路径
INDEX_NPY = PROJECT_DIR / "semantic_embeddings.npy"
INDEX_META = PROJECT_DIR / "semantic_metas.json"
INDEX_FILE = PROJECT_DIR / "semantic_index.pkl"  # drama only

# 全局音色库（克隆音色，跨项目共享）
GLOBAL_VOICES_DIR = BASE_DIR / "voices"


# ── 源视频索引 ──
SOURCE_VIDEOS: dict = {}

if project_type == "drama":
    video_dir = Path(project_config.get("source_videos",
                     f"/Users/zgl/解说剪辑/{project_name}原剧"))
    for ep in range(1, project_config.get("episodes", 46) + 1):
        p = video_dir / f"{project_name} {ep:02d}_1080p.mp4"
        if p.exists():
            SOURCE_VIDEOS[f"ep{ep}"] = p
elif project_type == "interview":
    video_dir = Path(project_config.get("source_videos", ""))
    if video_dir.exists():
        for f in sorted(video_dir.glob("*.mp4")):
            SOURCE_VIDEOS[f.stem] = f
    print(f"[project] 口播素材: {len(SOURCE_VIDEOS)} 个视频")
