#!/bin/bash
# 启动 VIBECAP 后端
# 用法: ./start.sh [drama] [task]
DRAMA=${1:-都挺好}
TASK=${2:-Task7024}
PORT=${3:-8765}

cd "$(dirname "$0")"
export HF_ENDPOINT=https://hf-mirror.com

# 加载本地 .env（API Keys）
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

echo "启动: drama=$DRAMA task=$TASK port=$PORT"
/opt/anaconda3/bin/python3 server.py --drama "$DRAMA" --task "$TASK" --port "$PORT"
