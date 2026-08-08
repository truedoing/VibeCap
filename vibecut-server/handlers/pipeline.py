"""后台加工流水线 — 电视剧 + 口播数据管线 (v1.1: 消除子进程重复代码)"""

import threading
import time
from pathlib import Path

from config import project_name, BASE_DIR
from lib.subprocess_runner import pipeline_step

# 流水线任务状态
_process_tasks: dict = {}  # {task_id: {episodes, steps, current}}
_process_lock = threading.Lock()


def run_pipeline(task_id: str, episodes: list, drama_name: str) -> None:
    """后台执行电视剧数据加工流水线"""
    all_eps_str = ",".join(str(e) for e in episodes)

    steps = [
        {"id": "analyze", "label": f"分析 EP{all_eps_str}", "status": "pending",
         "progress": 0, "detail": "", "elapsed": 0, "log_lines": []},
        {"id": "calibrate", "label": "交叉校准", "status": "pending",
         "progress": 0, "detail": "", "elapsed": 0, "log_lines": []},
        {"id": "clean", "label": "数据清洗", "status": "pending",
         "progress": 0, "detail": "", "elapsed": 0, "log_lines": []},
        {"id": "build", "label": "重建索引", "status": "pending",
         "progress": 0, "detail": "", "elapsed": 0, "log_lines": []},
        {"id": "migrate", "label": "导入数据库", "status": "pending",
         "progress": 0, "detail": "", "elapsed": 0, "log_lines": []},
    ]

    with _process_lock:
        _process_tasks[task_id] = {"episodes": episodes, "steps": steps,
                                    "started_at": time.time()}

    def _run(step_idx, script_name, args_list, timeout):
        pipeline_step(step_idx, script_name, args_list, timeout,
                      steps, task_id, _process_lock, _process_tasks)

    def _run_all():
        try:
            eps_args = ["--episodes"] + [str(e) for e in episodes]
            _run(0, "analyze_episodes.py", eps_args, timeout=3600)
            _run(1, "cross_calibrate.py", eps_args, timeout=600)
            _run(2, "clean_data.py", eps_args, timeout=600)
            _run(3, "build_index.py", ["--project", drama_name], timeout=300)
            _run(4, "migrate_db.py", ["--project", drama_name], timeout=120)
        except Exception as e:
            print(f"[pipeline] 流水线异常: {e}")

    threading.Thread(target=_run_all, daemon=True).start()


def get_process_status(task_id: str) -> dict:
    """获取流水线状态"""
    with _process_lock:
        t = _process_tasks.get(task_id)
        if t:
            return {
                "ok": True,
                "task_id": task_id,
                "episodes": t["episodes"],
                "steps": [dict(s) for s in t["steps"]],
                "started_at": t["started_at"],
            }
    return {"ok": False, "error": "task not found"}


def run_interview_pipeline(task_id: str, task_name: str) -> None:
    """口播数据加工流水线"""
    steps = [
        {"id": "classify", "label": "ASR 分类", "status": "pending",
         "progress": 0, "detail": "", "elapsed": 0, "log_lines": []},
        {"id": "clean", "label": "数据清洗 + 说话人", "status": "pending",
         "progress": 0, "detail": "", "elapsed": 0, "log_lines": []},
        {"id": "segment", "label": "主题分段", "status": "pending",
         "progress": 0, "detail": "", "elapsed": 0, "log_lines": []},
        {"id": "build", "label": "重建索引", "status": "pending",
         "progress": 0, "detail": "", "elapsed": 0, "log_lines": []},
    ]

    with _process_lock:
        _process_tasks[task_id] = {"episodes": [], "steps": steps,
                                    "started_at": time.time()}

    env_extra = {"VibeCut_PROJECT": project_name, "VibeCut_TASK": task_name}

    def _run(step_idx, script_name, args_list, timeout, env=None):
        pipeline_step(step_idx, script_name, args_list, timeout,
                      steps, task_id, _process_lock, _process_tasks, env)

    def _run_all():
        try:
            _run(0, "classify_transcript.py", [], timeout=600, env=env_extra)
            _run(1, "clean_interview_data.py", [], timeout=600, env=env_extra)
            _run(2, "segment_transcript.py", [], timeout=600, env=env_extra)
            _run(3, "build_index.py", ["--project", project_name], timeout=300)
        except Exception as e:
            print(f"[pipeline] 口播流水线异常: {e}")

    threading.Thread(target=_run_all, daemon=True).start()
