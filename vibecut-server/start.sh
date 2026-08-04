#!/bin/bash
# VibeCut 一键启动（后端 + 前端生产构建）
# 用法: ./start.sh [drama] [task] [port]
# 访问 http://localhost:8766 即可使用完整应用
DRAMA=${1:-都挺好}
TASK=${2:-Task7024}
PORT=${3:-8766}

cd "$(dirname "$0")"
export HF_ENDPOINT=https://hf-mirror.com

# 加载本地 .env（API Keys）
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

# 前端构建（如未构建）
if [ ! -d "../vibecut-web/dist" ]; then
  echo ">>> 构建前端..."
  cd ../vibecut-web && npm run build && cd - > /dev/null
fi

echo "VibeCut 生产模式: http://localhost:$PORT"
echo "  drama=$DRAMA  task=$TASK"
/opt/anaconda3/bin/python3 server.py --drama "$DRAMA" --task "$TASK" --port "$PORT"
