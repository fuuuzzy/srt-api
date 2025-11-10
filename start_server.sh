#!/bin/bash
# SRT翻译API服务启动脚本

# 获取端口参数，默认为8000
PORT=${1:-8000}
HOST=${2:-0.0.0.0}

echo "启动SRT翻译API服务..."
echo "主机: $HOST"
echo "端口: $PORT"

# 使用uv启动FastAPI服务
uv run python api_server.py --host "$HOST" --port "$PORT"