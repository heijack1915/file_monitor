#!/bin/bash
# ================================================================
# file_monitor_v7 一键部署脚本
# 用法: chmod +x setup.sh && ./setup.sh
# ================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║         📁 macOS 文件监控 v7 — 一键部署                     ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── 1. 检查 macOS ──────────────────────────────────────────────
if [ "$(uname)" != "Darwin" ]; then
    echo "❌ 此程序仅支持 macOS"
    exit 1
fi
echo "✅ macOS 环境确认"

# ── 2. 检查 Python 3 ───────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "❌ 未找到 python3，请先安装 Python 3.8+"
    echo "   brew install python3  或访问 https://python.org"
    exit 1
fi
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "✅ Python $PY_VERSION"

# ── 3. 检查 fs_usage ───────────────────────────────────────────
FS_USAGE=""
for path in "/usr/bin/fs_usage" "/usr/sbin/fs_usage"; do
    if [ -f "$path" ]; then
        FS_USAGE="$path"
        break
    fi
done
if [ -z "$FS_USAGE" ]; then
    echo "❌ 未找到 fs_usage，请安装 Xcode Command Line Tools:"
    echo "   xcode-select --install"
    exit 1
fi
echo "✅ fs_usage: $FS_USAGE"

# ── 4. 创建虚拟环境 ────────────────────────────────────────────
if [ ! -d "venv" ]; then
    echo "📦 创建 Python 虚拟环境..."
    python3 -m venv venv
else
    echo "📦 虚拟环境已存在，跳过创建"
fi

source venv/bin/activate

# ── 5. 安装依赖 ────────────────────────────────────────────────
echo "📦 安装 Python 依赖 (flask, watchdog)..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo "✅ 依赖安装完成"

# ── 6. 配置 sudo 免密 ──────────────────────────────────────────
CURRENT_USER="$(whoami)"
SUDOERS_FILE="/etc/sudoers.d/file_monitor_v7"

echo ""
echo "🔐 配置 sudo 免密 (运行 fs_usage 需要 root 权限)..."

ALREADY_SET=false
if sudo -n "$FS_USAGE" -h &>/dev/null 2>&1; then
    ALREADY_SET=true
elif [ -f "$SUDOERS_FILE" ]; then
    ALREADY_SET=true
fi

if $ALREADY_SET; then
    echo "✅ sudo 免密已配置，跳过"
else
    echo "   需要输入一次 sudo 密码（仅此一次）..."
    echo "$CURRENT_USER ALL=(ALL) NOPASSWD: $FS_USAGE" | sudo tee "$SUDOERS_FILE" > /dev/null
    sudo chmod 440 "$SUDOERS_FILE"
    echo "✅ sudo 免密配置完成 → $SUDOERS_FILE"
fi

# ── 7. 赋予执行权限 ────────────────────────────────────────────
chmod +x "$SCRIPT_DIR/app.py"
chmod +x "$SCRIPT_DIR/run.sh"
chmod +x "$SCRIPT_DIR/uninstall.sh"
echo "✅ 脚本权限设置完成"

# ── 8. 清理旧端口 ──────────────────────────────────────────────
echo ""
echo "🔌 检查端口 5006..."
if lsof -ti:5006 2>/dev/null | xargs kill -9 2>/dev/null; then
    echo "✅ 已停止占用端口 5006 的旧进程"
else
    echo "✅ 端口 5006 空闲"
fi

# ── 9. 完成 ───────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                    ✅  部署完成!                             ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║                                                              ║"
echo "║  启动监控:  ./run.sh                                         ║"
echo "║  访问界面:  http://localhost:5006                            ║"
echo "║  彻底删除:  ./uninstall.sh                                   ║"
echo "║                                                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
