"""segments.json 加载/落盘 helper — 消除多处重复的「task 目录 → 项目级 fallback」链"""
import json
from pathlib import Path

from config import PROJECT_DIR, resolve_task_dir


def find_segments_file(task_name: str = None) -> Path | None:
    """统一的 segments.json 加载链：task 目录 → 项目级 → 文案脚本.json"""
    task_dir = resolve_task_dir(task_name)
    for p in (task_dir / "segments.json",
              PROJECT_DIR / "tasks" / "segments.json",
              PROJECT_DIR / "tasks" / "文案脚本.json"):
        if p.exists():
            return p
    return None


def load_segments(task_name: str = None) -> dict | None:
    """加载 segments.json，返回完整数据 dict 或 None"""
    path = find_segments_file(task_name)
    if not path:
        return None
    try:
        return json.load(open(path))
    except Exception:
        return None


def save_segments(task_name: str, data: dict) -> Path:
    """落盘 segments.json 到任务目录"""
    task_dir = resolve_task_dir(task_name)
    task_dir.mkdir(parents=True, exist_ok=True)
    path = task_dir / "segments.json"
    json.dump(data, open(path, "w"), ensure_ascii=False, indent=2)
    return path
