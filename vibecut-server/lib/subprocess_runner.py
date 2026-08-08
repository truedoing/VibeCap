"""子进程执行器 — 统一脚本调用，支持直接 import 或 subprocess fallback"""

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Callable

from config import project_name, PROJECT_DIR, PYTHON_BIN, SERVER_DIR, args


# ── 通用子进程执行器 ──

def run_script(
    script_name: str,
    args_list: list = None,
    timeout: int = 600,
    env_extra: dict = None,
    progress_parser: Callable = None,
    on_line: Callable = None,
) -> dict:
    """运行 Python 脚本子进程，可逐行解析进度

    Returns:
        {"ok": True, "log_lines": [...], "elapsed": float}
    """
    if args_list is None:
        args_list = []
    cmd = [PYTHON_BIN, "-u", str(SERVER_DIR / script_name)] + args_list
    env = {**os.environ, "PYTHONUNBUFFERED": "1",
           "VibeCut_PROJECT": project_name, "VibeCut_TASK": args.task}
    if env_extra:
        env.update(env_extra)

    log_lines = []
    t0 = time.time()

    try:
        p = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
        )
        for line in p.stdout:
            line = line.rstrip()
            if line:
                log_lines.append(line)
                if len(log_lines) > 8:
                    log_lines = log_lines[-8:]
                if on_line:
                    on_line(line)
        p.wait(timeout=timeout)
        elapsed = round(time.time() - t0, 1)
        if p.returncode == 0:
            return {"ok": True, "log_lines": log_lines, "elapsed": elapsed}
        else:
            return {"ok": False, "log_lines": log_lines, "elapsed": elapsed,
                    "error": f"Exit code {p.returncode}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "log_lines": log_lines,
                "elapsed": round(time.time() - t0, 1), "error": "Timeout"}
    except Exception as e:
        return {"ok": False, "log_lines": log_lines,
                "elapsed": round(time.time() - t0, 1), "error": str(e)}


# ── 便捷封装 — 带进度追踪的流水线步骤执行器 ──

def pipeline_step(
    step_idx: int,
    script_name: str,
    args_list: list,
    timeout: int,
    steps: list,
    task_id: str,
    process_lock,
    process_tasks: dict,
    env_extra: dict = None,
):
    """执行流水线单步，自动更新进度"""
    def _update(i, **kw):
        with process_lock:
            t = process_tasks.get(task_id)
            if t:
                t["steps"][i].update(kw)

    _update(step_idx, status="running", detail="启动中...")
    t0 = time.time()
    log_lines = []

    cmd = [PYTHON_BIN, "-u", str(SERVER_DIR / script_name)] + args_list
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    if env_extra:
        env.update(env_extra)

    try:
        p = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
        )
        for line in p.stdout:
            line = line.rstrip()
            if line:
                log_lines.append(line)
                if len(log_lines) > 8:
                    log_lines = log_lines[-8:]
                elapsed = round(time.time() - t0, 1)
                detail = line[:80]
                m = re.search(r'\[?\s*(\d+)\s*/\s*(\d+)\s*\]?', line)
                if m:
                    current, total = int(m.group(1)), int(m.group(2))
                    pct = min(99, round(current / max(total, 1) * 100))
                    _update(step_idx, progress=pct, detail=detail,
                            elapsed=elapsed, log_lines=list(log_lines))
                else:
                    _update(step_idx, detail=detail, elapsed=elapsed,
                            log_lines=list(log_lines))
        p.wait(timeout=timeout)
        elapsed = round(time.time() - t0, 1)
        if p.returncode == 0:
            _update(step_idx, status="done", progress=100, elapsed=elapsed,
                    detail="✓ 完成", log_lines=list(log_lines))
        else:
            _update(step_idx, status="failed", elapsed=elapsed,
                    detail=f"✗ 退出码 {p.returncode}", log_lines=list(log_lines))
    except subprocess.TimeoutExpired:
        _update(step_idx, status="failed", elapsed=round(time.time() - t0, 1),
                detail="✗ 超时", log_lines=list(log_lines))
    except Exception as e:
        _update(step_idx, status="failed", elapsed=round(time.time() - t0, 1),
                detail=f"✗ {e}", log_lines=list(log_lines))
