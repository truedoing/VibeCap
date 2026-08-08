"""统一 .env 加载，消除多文件重复"""

import os
from pathlib import Path


def load_env(env_file: Path = None):
    """从 .env 文件加载环境变量（仅设置未定义或为空的变量）"""
    if env_file is None:
        env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                if not os.environ.get(key):
                    os.environ[key] = val.strip().strip('"').strip("'")
