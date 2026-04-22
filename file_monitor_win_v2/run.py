#!/usr/bin/env python3
"""
Windows File Monitor v2 - Launcher
跨平台启动脚本，支持自动安装 Python 依赖
"""

import subprocess
import sys
import os
import shutil
from pathlib import Path


def find_python():
    """查找可用的 Python 解释器"""
    # 尝试常见的 Python 命令
    commands = ['python', 'python3', 'py']
    for cmd in commands:
        try:
            result = subprocess.run([cmd, '--version'],
                                 capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return cmd
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    # 尝试常见安装路径 (Windows)
    if os.name == 'nt':
        # winget 安装的 Python
        localappdata = os.environ.get('LOCALAPPDATA', '')
        paths_to_check = [
            Path(localappdata) / 'Programs' / 'Python',
        ]

        # 也检查 Python 安装后可能的新路径
        for base in paths_to_check:
            if not base.exists():
                continue
            for p in sorted(base.glob('Python*')):
                if p.is_dir():
                    exe = p / 'python.exe'
                    if exe.exists():
                        try:
                            result = subprocess.run([str(exe), '--version'],
                                                 capture_output=True, text=True, timeout=5)
                            if result.returncode == 0:
                                return str(exe)
                        except:
                            continue

    return None


def install_python_winget():
    """通过 winget 安装 Python"""
    print("\n[INFO] Python not found.")
    print("\n" + "=" * 50)
    print("   Install Python")
    print("=" * 50)
    print()
    print("   1 - Install automatically via winget (recommended)")
    print("   2 - Download from website")
    print("   3 - Cancel")
    print("=" * 50)
    print()

    choice = input("Choose (1/2/3): ").strip()

    if choice == '1':
        print("\n[INFO] Installing Python via winget...")
        print("[INFO] Please wait a few minutes...")
        try:
            result = subprocess.run(
                ['winget', 'install', 'Python.Python.3.11',
                 '--accept-package-agreements', '--accept-source-agreements'],
                capture_output=False
            )
            if result.returncode == 0:
                print("\n[OK] Python installed successfully!")
                return True
            else:
                print("\n[ERROR] winget install failed.")
                return False
        except Exception as e:
            print(f"\n[ERROR] {e}")
            return False

    elif choice == '2':
        print("\n[INFO] Opening download page...")
        subprocess.run(['start', 'https://www.python.org/downloads/'], shell=True)
        return False

    else:
        print("\n[CANCELLED]")
        return False


def install_dependencies(python_cmd):
    """安装依赖"""
    print("\n[INFO] Installing dependencies (flask, watchdog, psutil)...")

    deps = ['flask', 'watchdog', 'psutil']
    for dep in deps:
        print(f"  Installing {dep}...")
        try:
            subprocess.run([python_cmd, '-m', 'pip', 'install', dep, '-q'],
                         check=True, timeout=120)
        except Exception as e:
            print(f"  [WARN] Failed to install {dep}: {e}")

    print("[OK] Dependencies ready.")


def main():
    # 获取脚本所在目录
    script_dir = Path(__file__).parent.resolve()

    print("=" * 50)
    print("   Windows File Monitor v2")
    print("=" * 50)
    print(f"\n[INFO] Working directory: {script_dir}")

    # 切换到脚本目录
    os.chdir(script_dir)

    # 查找 Python
    python_cmd = find_python()

    # 如果没找到，尝试安装
    if not python_cmd:
        success = install_python_winget()
        if not success:
            input("\nPress Enter to exit...")
            sys.exit(1)

        # 安装完成后，重新查找 Python
        print("\n[INFO] Refreshing Python location...")
        python_cmd = find_python()

        if not python_cmd:
            # 可能安装在非标准路径，再试一次
            python_cmd = find_python()
            if not python_cmd:
                print("\n[ERROR] Could not find Python after installation.")
                print("[INFO] Please run this script again.")
                input("\nPress Enter to exit...")
                sys.exit(1)

    # 验证 Python
    try:
        result = subprocess.run([python_cmd, '--version'],
                              capture_output=True, text=True)
        print(f"[OK] Found: {result.stdout.strip()}")
    except Exception as e:
        print(f"[ERROR] Cannot verify Python: {e}")
        sys.exit(1)

    # 检查 app.py
    app_py = script_dir / 'app.py'
    if not app_py.exists():
        print(f"\n[ERROR] app.py not found in {script_dir}")
        sys.exit(1)

    # 安装依赖
    install_dependencies(python_cmd)

    # 启动应用
    print("\n" + "=" * 50)
    print("[INFO] Starting File Monitor...")
    print("[INFO] Open http://localhost:5006")
    print("=" * 50)
    print("\nPress Ctrl+C to stop.\n")

    try:
        subprocess.run([python_cmd, 'app.py'])
    except KeyboardInterrupt:
        print("\n\n[INFO] File Monitor stopped.")
    except Exception as e:
        print(f"\n[ERROR] {e}")


if __name__ == '__main__':
    main()
