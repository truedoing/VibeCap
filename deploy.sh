#!/bin/bash
# VIBECAP 一键部署（git pull → build → restart）
# 用法: ./deploy.sh
set -e

cd "$(dirname "$0")"
DRAMA=${1:-都挺好}
TASK=${2:-Task7029}
PORT=${3:-8766}

echo ">>> git pull..."
git pull origin main

echo ">>> 构建前端..."
cd vibecap-web
npm run build
cd ..

echo ">>> 加载环境变量..."
if [ -f vibecap-server/.env ]; then
  export $(grep -v '^#' vibecap-server/.env | xargs)
fi

echo ">>> 重启服务..."
lsof -ti :$PORT | xargs kill -9 2>/dev/null || true
sleep 1
nohup /opt/anaconda3/bin/python3 vibecap-server/server.py \
  --drama "$DRAMA" --task "$TASK" --port "$PORT" \
  > /tmp/vibecap.log 2>&1 &
sleep 2

# 验证
if curl -sf http://localhost:$PORT/status > /dev/null 2>&1; then
  echo "✅ 部署完成 → http://localhost:$PORT"
else
  echo "❌ 启动失败，查看日志: tail /tmp/vibecap.log"
  exit 1
fi
