#!/bin/bash
# ================================================================
# file_monitor_v7 一键启动脚本
# ================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 杀掉占用端口的旧进程
if lsof -ti:5006 2>/dev/null | xargs kill -9 2>/dev/null; then
    echo "🔌 已停止旧进程"
    sleep 0.5
fi

# 激活虚拟环境并启动
source venv/bin/activate
echo "🚀 启动文件监控 v7..."
python3 app.py
