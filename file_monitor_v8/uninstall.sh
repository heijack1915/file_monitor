#!/bin/bash
# ================================================================
# file_monitor_v7 一键彻底删除脚本
# 删除内容：虚拟环境、sudo 免密配置、日志、整个项目目录
# ================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CURRENT_USER="$(whoami)"
SUDOERS_FILE="/etc/sudoers.d/file_monitor_v7"
LOG_DIR="$HOME/Library/Logs/FileMonitor"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║         🗑️  file_monitor_v7 彻底删除                         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "⚠️  此操作将删除以下内容："
echo "   • 运行中的监控进程"
echo "   • Python 虚拟环境 (venv/)"
echo "   • sudo 免密配置 ($SUDOERS_FILE)"
echo "   • 运行日志 ($LOG_DIR)"
echo "   • 项目目录 ($SCRIPT_DIR)"
echo ""
read -p "确认彻底删除? 输入 yes 继续: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "已取消。"
    exit 0
fi

echo ""

# ── 1. 停止运行中的进程 ────────────────────────────────────────
echo "📴 停止监控进程..."
pkill -f "python.*app.py" 2>/dev/null && echo "   ✅ 进程已停止" || echo "   ✅ 无运行中进程"
lsof -ti:5006 2>/dev/null | xargs kill -9 2>/dev/null || true

# ── 2. 删除 sudo 免密配置 ──────────────────────────────────────
echo "🔐 删除 sudo 免密配置..."
if [ -f "$SUDOERS_FILE" ]; then
    sudo rm -f "$SUDOERS_FILE"
    echo "   ✅ 已删除 $SUDOERS_FILE"
else
    echo "   ✅ 无 sudo 免密配置"
fi

# ── 3. 删除日志 ────────────────────────────────────────────────
echo "📋 删除运行日志..."
if [ -d "$LOG_DIR" ]; then
    rm -rf "$LOG_DIR"
    echo "   ✅ 已删除 $LOG_DIR"
else
    echo "   ✅ 无日志目录"
fi

# ── 4. 删除项目目录 ────────────────────────────────────────────
echo "📁 删除项目目录..."
# 先退出目录再删除
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PARENT_DIR"
rm -rf "$SCRIPT_DIR"
echo "   ✅ 已删除 $SCRIPT_DIR"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              ✅  彻底删除完成，干干净净！                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
