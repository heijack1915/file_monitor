#!/usr/bin/env python3
"""
macOS 文件监控 Web 界面 v7.3
双引擎监控：fs_usage（写入/重命名/废纸篓）+ watchdog FSEvents（rm 删除）
新增：AI 分析功能（OpenAI 兼容标准接口 + 离线规则引擎）
"""

import fcntl
import json
import logging
import os
import pty
import ssl
import re
import select
import struct
import subprocess
import sys
import termios
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional
from flask import Flask, render_template, Response, jsonify, request


# ============ 依赖自动安装 ============
def check_and_install_dependencies():
    required = {"flask": "flask>=2.0.0", "watchdog": "watchdog>=3.0.0"}
    missing = []
    for package, spec in required.items():
        try:
            __import__(package)
        except ImportError:
            missing.append((package, spec))
    if not missing:
        return True
    print("\n" + "=" * 60)
    print("  正在安装依赖库...")
    print("=" * 60)
    for package, spec in missing:
        print(f"\n  安装 {spec} ...")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", spec],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                print(f"  ✅ {package} 安装成功")
            else:
                print(f"  ❌ {package} 安装失败")
                return False
        except Exception as e:
            print(f"  ❌ {package} 安装异常: {e}")
            return False
    print("\n✅ 所有依赖安装完成\n")
    return True


# ============ Flask 应用 ============
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

monitoring = False
fs_process = None
monitor_thread = None
watchdog_observer = None
events = []
events_lock = threading.Lock()
subscribers = []
watch_paths_raw: list = []   # 保存原始路径字符串，供前端刷新后恢复

# ============ AI 分析配置（OpenAI 兼容接口）============
ai_config = {
    "api_url":  "",       # 如 https://api.openai.com/v1/chat/completions
    "api_key":  "",
    "model":    "gpt-4o",
    "timeout":  30,
}

MAX_EVENTS = 2000
LOG_DIR = Path.home() / "Library/Logs/FileMonitor"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'web_server_v7.3.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

OP_MAP = {
    "open":           "打开",
    "write":          "写入",
    "wrdata":         "写入",
    "pwrite":         "写入",
    "guarded_pwrite": "写入",
    "guarded_write":  "写入",
    "creat":          "新建",   # macOS 真实 syscall（create 是别名）
    "create":         "新建",
    "unlink":         "删除",
    "rename":         "重命名",
    "trash":          "删除(移入废纸篓)",
    "mkdir":          "新建目录",
    "rmdir":          "删除目录",
    "truncate":       "截断",
    "link":           "硬链接",
    "symlink":        "软链接",
    "chmod":          "权限变更",
    "chown":          "所有者变更",
    "utimes":         "时间变更",
}

WRITE_OP_KEYWORDS = {
    "write", "wrdata", "pwrite", "guarded_pwrite", "guarded_write",
    "creat", "create", "unlink", "rename",
    "mkdir", "rmdir",
    "truncate", "link", "symlink",
}

filters = {
    "keyword": "",
    "path": "",
    "process": "",
    "app": "",
    "types": []
}

COMMON_PATHS = [
    ("~/Desktop",   "桌面"),
    ("~/Documents", "文档"),
    ("~/Downloads", "下载"),
    ("/Applications", "应用程序"),
]

# 行首跳过前缀
SKIP_PREFIXES = (
    'WARNING', 'FILE', '-', 'Timestamp', 'PAGE_OUT', 'PAGE',
    'PgOut', 'CPU', 'TH_', 'IOP', 'ktrace', 'MACH', 'MSC', 'BSC',
)

# 跳过的块设备前缀（不是用户文件）
DEVICE_PATH_PREFIXES = ('/dev/', '/proc/')

# macOS fs_usage 有时省略路径开头的 /，这些前缀可直接补上
IMPLICIT_PATH_STARTERS = (
    'private/', 'Users/', 'var/', 'tmp/', 'System/',
    'Library/', 'Applications/', 'Volumes/', 'home/',
)


def is_write_op(op: str) -> bool:
    op_l = op.lower()
    return any(op_l == kw or op_l.startswith(kw) for kw in WRITE_OP_KEYWORDS)


def normalize_path(token: str) -> Optional[str]:
    """把 fs_usage 输出的路径 token 规范化为绝对路径，无法识别返回 None"""
    if token.startswith('/'):
        if any(token.startswith(d) for d in DEVICE_PATH_PREFIXES):
            return None  # 块设备，跳过
        return token
    if any(token.startswith(s) for s in IMPLICIT_PATH_STARTERS):
        return '/' + token
    return None


def parse_fs_line(line: str):
    """
    解析 fs_usage 输出行，返回 (ts, op, path, proc) 或 None。

    fs_usage -w 格式（512列PTY）：
      时间  syscall  [F=N/D=N/B=N ...]  [/dev/diskXsY]  path  elapsed  FLAGS  process
    rename 格式较短：
      时间  rename  path  elapsed  [FLAGS]  process
    """
    if not line:
        return None

    for prefix in SKIP_PREFIXES:
        if line.startswith(prefix):
            return None

    parts = line.split()
    if len(parts) < 3:
        return None

    ts = parts[0]
    op = parts[1]

    # 从右向左找第一个合法用户空间路径（跳过设备路径）
    path = None
    path_idx = -1
    for i in range(len(parts) - 1, 1, -1):
        normalized = normalize_path(parts[i])
        if normalized is not None:
            path = normalized
            path_idx = i
            break

    if not path:
        return None

    # 进程名：在路径之后的 token 里，取最后一个不像数字/标志的 token
    proc = "unknown"
    for j in range(len(parts) - 1, path_idx, -1):
        p = parts[j]
        if (len(p) > 1
                and '/' not in p
                and not p.startswith('0x')
                and not p.startswith(('B=', 'D=', 'F=', 'O=', '<'))
                and not re.match(r'^\d+\.\d+$', p)   # 单点小数（elapsed，如 0.000009）
                and not re.match(r'^[A-Z]{1,4}$', p) # 全大写标志（W/RW/CF等）
        ):
            proc = p
            break

    # fs_usage 对某些进程输出 "version.bignum" 格式（如 Claude Code: 2.1.114.29220321）
    # 尝试用路径推断可读进程名
    if proc == "unknown" or re.match(r'^[\d.]+$', proc):
        inferred = _infer_proc_from_path(path, proc)
        if inferred:
            proc = inferred

    return ts, op, path, proc


# 路径特征 → 进程名推断表（顺序匹配，先匹配先得）
_PATH_PROC_RULES = [
    ('/tmp/claude-',     'claude'),
    ('/.claude',         'claude'),   # 匹配 /.claude 目录本身及其子路径
    ('/claude/',         'claude'),
    ('/tmp/node-',       'node'),
    ('/tmp/npm-',        'npm'),
    ('/Library/Python/', 'python'),
    ('/site-packages/',  'pip'),
]


def _infer_proc_from_path(path: str, raw_proc: str) -> str:
    """根据路径特征推断进程名；无法推断时返回 raw_proc（可能是 version.id 字符串）"""
    for fragment, name in _PATH_PROC_RULES:
        if fragment in path:
            return name
    # Claude Code 的 proc token 格式为 "主版本.次版本.补丁.PID"（四段纯数字），如 2.1.114.29220248
    if re.match(r'^\d+\.\d+\.\d+\.\d+$', raw_proc):
        return 'claude'
    # 保留原始 token（至少比 unknown 有信息量）
    return raw_proc if raw_proc != "unknown" else ""


def simplify_path(path: str) -> str:
    home = str(Path.home())
    if path.startswith('/private'):
        path = path[len('/private'):]
    if path.startswith(home):
        path = '~' + path[len(home):]
    if len(path) > 70:
        parts = path.split('/')
        if len(parts) > 5:
            path = '/'.join(parts[:3]) + '/.../' + '/'.join(parts[-2:])
        else:
            path = path[:67] + '...'
    return path


def get_op_cn(op_key: str) -> str:
    for key, cn in OP_MAP.items():
        if op_key == key or op_key.startswith(key):
            return cn
    return op_key


def matches_filter(event) -> bool:
    if not any([filters["keyword"], filters["path"],
                filters["process"], filters["app"], filters["types"]]):
        return True
    if filters["types"] and event.get("op") not in filters["types"]:
        return False
    if filters["keyword"] and filters["keyword"].lower() not in event.get("path", "").lower():
        return False
    if filters["path"] and not event.get("path", "").startswith(filters["path"]):
        return False
    if filters["process"] and filters["process"].lower() not in event.get("proc", "").lower():
        return False
    if filters["app"] and filters["app"].lower() not in event.get("proc", "").lower():
        return False
    return True


def send_sse_event(event_type, data):
    for q in list(subscribers):
        try:
            q.put_nowait({"type": event_type, "data": data})
        except Exception:
            try:
                subscribers.remove(q)
            except Exception:
                pass


def resolve_rename(src_path: str, proc: str, watch_paths, trigger_time: float = 0):
    """
    rename 事件延迟 300ms 后检测文件命运，再入库推送。
    fs_usage 只给 source 路径，通过检查文件系统状态反推结果。
    trigger_time: process_line 处理该行时的 time.time()，用于计算 event_time。
    """
    time.sleep(0.3)

    src = Path(src_path)
    trash = Path.home() / ".Trash"

    # 用 trigger_time 而非 now-0.3：避免洪流积压导致时间基准漂移
    # 回溯 5 秒窗口，覆盖高负载下的延迟处理情况
    if trigger_time > 0:
        event_time = trigger_time - 0.3
    else:
        event_time = time.time() - 0.3
    lookback = 5.0   # 向前回溯 5 秒

    src_exists = src.exists()

    # ── 废纸篓判断 ───────────────────────────────────────────────
    trash_candidate = trash / src.name
    in_trash = False
    if not src_exists and trash_candidate.exists():
        try:
            ctime = trash_candidate.stat().st_ctime
            in_trash = ctime >= event_time - lookback
        except OSError:
            pass

    if in_trash:
        op_key = "trash"
        display_path = str(trash_candidate)
        path_short = "~/.Trash/" + src.name
    else:
        # ── 重命名目标扫描 ────────────────────────────────────────
        # 跳过隐藏文件，取 ctime 最接近 event_time 的文件
        new_name = None
        try:
            best_delta = 999.0
            for sibling in src.parent.iterdir():
                if sibling == src:
                    continue
                if sibling.name.startswith('.'):
                    continue
                try:
                    st = sibling.stat()
                except OSError:
                    continue
                if st.st_ctime >= event_time - lookback:
                    delta = abs(st.st_ctime - event_time)
                    if delta < best_delta:
                        best_delta = delta
                        new_name = sibling
        except Exception:
            pass

        if new_name:
            op_key = "rename"
            display_path = str(new_name)
            path_short = simplify_path(str(new_name)) + f"  (← {src.name})"
        else:
            op_key = "rename"
            display_path = src_path
            path_short = simplify_path(src_path) + " (→ ?)"

    event = {
        "id":         int(time.time() * 1000000),
        "timestamp":  datetime.now().strftime("%H:%M:%S"),
        "date":       datetime.now().strftime("%Y-%m-%d"),
        "op":         op_key,
        "op_cn":      get_op_cn(op_key),
        "path":       display_path,
        "path_short": path_short,
        "proc":       proc[:40] if proc else "unknown",
    }

    if not matches_filter(event):
        return

    with events_lock:
        events.append(event)
        if len(events) > MAX_EVENTS:
            del events[:-MAX_EVENTS]

    send_sse_event("event", event)


def process_line(line: str, watch_paths):
    """解析单行 fs_usage 输出并入库/推送"""
    global events

    parsed = parse_fs_line(line)
    if not parsed:
        return

    ts, op, path, proc = parsed

    if not is_write_op(op):
        return

    # 路径过滤
    if watch_paths:
        norm_path = path[len('/private'):] if path.startswith('/private') else path
        if not any(norm_path.startswith(str(p)) or path.startswith(str(p))
                   for p in watch_paths):
            return

    if 'FileMonitor' in path or 'fs_usage' in proc:
        return

    op_lower = op.lower()

    # rename：交给后台线程延迟检测，立即返回
    if op_lower.startswith('rename'):
        trigger_time = time.time()   # 记录行被处理的时刻，用于 resolve_rename 时间基准
        t = threading.Thread(
            target=resolve_rename, args=(path, proc, watch_paths, trigger_time), daemon=True
        )
        t.start()
        return

    op_key = op_lower
    path_short = simplify_path(path)

    event = {
        "id":         int(time.time() * 1000000),
        "timestamp":  datetime.now().strftime("%H:%M:%S"),
        "date":       datetime.now().strftime("%Y-%m-%d"),
        "op":         op_key,
        "op_cn":      get_op_cn(op_key),
        "path":       path,
        "path_short": path_short,
        "proc":       proc[:40] if proc else "unknown",
    }

    if not matches_filter(event):
        return

    with events_lock:
        events.append(event)
        if len(events) > MAX_EVENTS:
            del events[:-MAX_EVENTS]

    send_sse_event("event", event)


def push_delete_event(path: str, proc: str = "rm"):
    """由 watchdog 回调调用，直接推送删除事件"""
    event = {
        "id":         int(time.time() * 1000000),
        "timestamp":  datetime.now().strftime("%H:%M:%S"),
        "date":       datetime.now().strftime("%Y-%m-%d"),
        "op":         "unlink",
        "op_cn":      "删除",
        "path":       path,
        "path_short": simplify_path(path),
        "proc":       proc,
    }

    if not matches_filter(event):
        return

    with events_lock:
        events.append(event)
        if len(events) > MAX_EVENTS:
            del events[:-MAX_EVENTS]

    send_sse_event("event", event)
    logger.info(f"[watchdog] 删除事件: {path}")


def start_watchdog(watch_paths):
    """启动 watchdog FSEvents 观察者，专门补充 rm 删除事件"""
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler, FileDeletedEvent, DirDeletedEvent
    except ImportError:
        logger.warning("watchdog 未安装，rm -rf 删除事件不会显示")
        return None

    class DeleteHandler(FileSystemEventHandler):
        def on_deleted(self, event):
            push_delete_event(event.src_path, proc="rm")

    observer = Observer()
    for wp in watch_paths:
        observer.schedule(DeleteHandler(), str(wp), recursive=True)
    observer.start()
    logger.info(f"watchdog 观察者启动，监控路径: {[str(p) for p in watch_paths]}")
    return observer


def monitor_thread_func(watch_paths):
    """
    监控线程：用 pty.openpty() 给 fs_usage 一个 512 列伪 TTY。
    - 512 列：防止长路径截断，进程名不再丢失
    - select 非阻塞读：毫秒级延迟，不再积压缓冲区
    - ANSI 先剥离再做路径过滤，避免转义码截断路径匹配
    - fd→path 缓存：open/creat 记录 fd，write/wrdata 无路径时从缓存补全
    """
    global fs_process, monitoring

    logger.info(f"监控线程启动，监控路径: {watch_paths}")

    master_fd, slave_fd = pty.openpty()
    winsize = struct.pack('HHHH', 50, 512, 0, 0)
    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

    fs_cmd = ["sudo", "/usr/bin/fs_usage", "-w", "-f", "filesys"]

    # 监控路径字符串集合，用于解码后过滤（比字节匹配更可靠）
    watch_strs = [str(p) for p in watch_paths] if watch_paths else []
    watch_strs_private = ['/private' + s for s in watch_strs if s.startswith('/Users')]
    all_watch_strs = watch_strs + watch_strs_private

    # fd → path 缓存：open/creat 写入，write/wrdata 读取
    # 格式：{ "fd_N": path }，容量上限 2000 防止泄漏
    _fd_cache: dict = {}
    _FD_CACHE_MAX = 2000

    def _cache_fd(fd_token: str, path: str):
        if len(_fd_cache) >= _FD_CACHE_MAX:
            # 清掉最老的一半
            keys = list(_fd_cache.keys())
            for k in keys[:_FD_CACHE_MAX // 2]:
                del _fd_cache[k]
        _fd_cache[fd_token] = path

    def _lookup_fd(line: str) -> Optional[str]:
        """从行中提取 F=N token，查缓存返回 path"""
        for token in line.split():
            if token.startswith('F=') and token[2:].isdigit():
                return _fd_cache.get(token)
        return None

    ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')

    try:
        logger.info("启动 fs_usage 进程（pty 512列）")
        fs_process = subprocess.Popen(
            fs_cmd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True
        )
        os.close(slave_fd)

        buf = b""

        while monitoring:
            try:
                r, _, _ = select.select([master_fd], [], [], 0.5)
            except (ValueError, OSError):
                break

            if not r:
                if fs_process.poll() is not None:
                    logger.warning("fs_usage 进程已退出")
                    break
                continue

            try:
                chunk = os.read(master_fd, 65536)
            except OSError:
                break

            if not chunk:
                break

            buf += chunk
            raw_lines = buf.split(b'\n')
            buf = raw_lines[-1]

            for raw in raw_lines[:-1]:
                # 先解码并剥离 ANSI，再做路径过滤（修复：ANSI 码可截断路径字符串）
                line = raw.decode('utf-8', errors='replace')
                line = ANSI_RE.sub('', line).replace('\r', '').strip()
                if not line:
                    continue

                parts = line.split()
                if len(parts) < 2:
                    continue
                op_raw = parts[1].lower()

                # open/creat 行：记录 fd→path 缓存
                if op_raw in ('open', 'creat', 'create'):
                    path_in_line = None
                    for tok in reversed(parts[2:]):
                        n = normalize_path(tok)
                        if n:
                            path_in_line = n
                            break
                    if path_in_line:
                        # 提取 F=N
                        for tok in parts:
                            if tok.startswith('F=') and tok[2:].isdigit():
                                _cache_fd(tok, path_in_line)
                                break

                # write/wrdata/pwrite 可能无路径，尝试从 fd 缓存补全
                if op_raw in ('write', 'wrdata', 'pwrite', 'guarded_write', 'guarded_pwrite'):
                    has_path = any(normalize_path(tok) for tok in parts[2:])
                    if not has_path:
                        cached = _lookup_fd(line)
                        if cached:
                            # 补一个 path token，让 process_line 能解析
                            line = line + '  ' + cached

                # 路径过滤（解码后做，避免 ANSI 截断问题）
                if all_watch_strs and not any(ws in line for ws in all_watch_strs):
                    op_lower = op_raw
                    if not any(kw in op_lower for kw in
                               ('rename', 'unlink', 'creat', 'create', 'mkdir', 'rmdir', 'write', 'link')):
                        continue

                try:
                    process_line(line, watch_paths)
                except Exception as e:
                    logger.debug(f"process_line 异常: {e}  行: {line[:80]}")

    except Exception as e:
        logger.error(f"监控线程异常: {e}")
        import traceback
        traceback.print_exc()
        send_sse_event("error", str(e))
    finally:
        try:
            os.close(master_fd)
        except Exception:
            pass
        if fs_process:
            try:
                fs_process.terminate()
            except Exception:
                pass
            fs_process = None
        logger.info("监控线程结束")


# ============ 路由 ============
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def status():
    with events_lock:
        return jsonify({
            "monitoring":   monitoring,
            "event_count":  len(events),
            "events":       events[-200:] if events else [],
            "watch_paths":  watch_paths_raw,
        })


@app.route("/api/events")
def get_events():
    with events_lock:
        limit  = request.args.get("limit", 200, type=int)
        offset = request.args.get("offset", 0, type=int)
        return jsonify({
            "events": events[offset:offset + limit],
            "total":  len(events)
        })


@app.route("/api/start", methods=["POST"])
def start_monitor():
    global monitoring, monitor_thread, watchdog_observer, watch_paths_raw

    if monitoring:
        return jsonify({"status": "already_running"})

    data = request.get_json() or {}
    paths = data.get("paths", [])

    watch_paths = []
    for p in paths:
        expanded = Path(p).expanduser().resolve()
        if expanded.exists():
            watch_paths.append(expanded)

    watch_paths_raw = [str(p) for p in watch_paths]

    # 清理可能残留的 fs_usage，防止 ktrace_start: Resource busy
    try:
        subprocess.run(["sudo", "pkill", "-9", "-f", "fs_usage"],
                       capture_output=True, timeout=3)
        time.sleep(0.5)
    except Exception:
        pass

    monitoring = True
    monitor_thread = threading.Thread(
        target=monitor_thread_func, args=(watch_paths,), daemon=True
    )
    monitor_thread.start()

    # 启动 watchdog 补充 rm -rf 删除事件（fs_usage unlinkat 无绝对路径）
    if watch_paths:
        watchdog_observer = start_watchdog(watch_paths)

    logger.info(f"监控已启动，路径: {[str(p) for p in watch_paths]}")
    return jsonify({"status": "started", "watch_paths": [str(p) for p in watch_paths]})


@app.route("/api/stop", methods=["POST"])
def stop_monitor():
    global monitoring, fs_process, watchdog_observer, watch_paths_raw

    monitoring = False
    watch_paths_raw = []
    if fs_process:
        try:
            fs_process.terminate()
        except Exception:
            pass
        fs_process = None

    # fs_usage 以 root 运行，terminate() 只杀 sudo 外壳，需要显式清理
    # 否则 ktrace 资源不释放，下次启动报 "ktrace_start: Resource busy"
    try:
        subprocess.run(["sudo", "pkill", "-9", "-f", "fs_usage"],
                       capture_output=True, timeout=3)
    except Exception:
        pass

    if watchdog_observer:
        try:
            watchdog_observer.stop()
            watchdog_observer.join(timeout=2)
        except Exception:
            pass
        watchdog_observer = None

    logger.info("监控已停止")
    return jsonify({"status": "stopped"})


@app.route("/api/clear", methods=["POST"])
def clear_events():
    global events
    with events_lock:
        events = []
    return jsonify({"status": "cleared"})


@app.route("/api/filter", methods=["POST"])
def set_event_filter():
    data = request.get_json() or {}
    filters["keyword"] = data.get("keyword", "")
    filters["path"]    = data.get("path", "")
    filters["process"] = data.get("process", "")
    filters["app"]     = data.get("app", "")
    filters["types"]   = data.get("types", [])
    return jsonify({"status": "ok"})


@app.route("/api/filter/clear", methods=["POST"])
def clear_event_filter():
    filters.update({"keyword": "", "path": "", "process": "", "app": "", "types": []})
    return jsonify({"status": "cleared"})


@app.route("/api/common-paths")
def get_common_paths():
    expanded = []
    for path, name in COMMON_PATHS:
        p = Path(path).expanduser().resolve()
        expanded.append({"path": str(p), "name": name, "exists": p.exists()})
    return jsonify(expanded)


@app.route("/api/export", methods=["GET"])
def export_events():
    with events_lock:
        return jsonify({
            "export_time": datetime.now().isoformat(),
            "count":       len(events),
            "events":      events
        })


# ============ AI 分析接口 ============

@app.route("/api/ai-config", methods=["GET"])
def get_ai_config():
    return jsonify({
        "api_url": ai_config["api_url"],
        "api_key": "***" if ai_config["api_key"] else "",
        "model":   ai_config["model"],
        "timeout": ai_config["timeout"],
    })


@app.route("/api/ai-config", methods=["POST"])
def set_ai_config():
    data = request.get_json() or {}
    if "api_url" in data:
        ai_config["api_url"] = data["api_url"].strip()
    if "api_key" in data and data["api_key"] != "***":
        ai_config["api_key"] = data["api_key"].strip()
    if "model" in data:
        ai_config["model"] = data["model"].strip()
    if "timeout" in data:
        ai_config["timeout"] = max(5, min(120, int(data["timeout"])))
    return jsonify({"status": "ok"})


@app.route("/api/analyze", methods=["POST"])
def analyze_event():
    """
    分析单条事件：
      mode=ai     → 调用外部 OpenAI 兼容接口
      mode=offline → 本地规则引擎
    """
    data  = request.get_json() or {}
    event = data.get("event", {})
    mode  = data.get("mode", "offline")

    if not event:
        return jsonify({"error": "缺少 event 字段"}), 400

    if mode == "ai":
        result = _analyze_ai(event)
    else:
        result = _analyze_offline(event)

    return jsonify(result)


def _analyze_ai(event: dict) -> dict:
    """调用 OpenAI 兼容接口分析事件"""
    if not ai_config["api_url"] or not ai_config["api_key"]:
        return {"error": "未配置 AI 接口地址或 API Key，请先在「AI 设置」中填写"}

    prompt = (
        "你是 macOS 文件系统安全分析专家。以下是一条文件系统事件记录，"
        "请用中文分析：1）这个操作是什么含义；2）是哪个程序发起的，为什么；"
        "3）是否需要关注或有安全风险。请简明扼要，不超过 200 字。\n\n"
        f"时间：{event.get('timestamp','')}\n"
        f"操作类型：{event.get('op_cn','')}（{event.get('op','')}）\n"
        f"文件路径：{event.get('path','')}\n"
        f"发起进程：{event.get('proc','unknown')}"
    )

    payload = json.dumps({
        "model":    ai_config["model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 400,
    }).encode("utf-8")

    req = urllib.request.Request(
        ai_config["api_url"],
        data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {ai_config['api_key']}",
            "User-Agent":    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        },
        method="POST",
    )

    try:
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=ai_config["timeout"], context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {e.code}: {raw[:300]}"}
    except urllib.error.URLError as e:
        return {"error": f"连接失败: {e.reason}"}
    except Exception as e:
        return {"error": f"网络异常: {str(e)[:200]}"}

    if not raw.strip():
        return {"error": "接口返回空响应，请检查接口地址和 Key 是否正确"}

    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": f"接口返回非 JSON 内容: {raw[:300]}"}

    # 兼容标准 OpenAI 格式
    try:
        text = body["choices"][0]["message"]["content"].strip()
        return {"mode": "ai", "result": text}
    except (KeyError, IndexError):
        pass

    # 有些接口直接返回 {"error": ...}
    if "error" in body:
        err = body["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        return {"error": f"接口错误: {msg[:300]}"}

    return {"error": f"无法解析响应结构: {raw[:300]}"}


# ── 离线规则引擎 ──────────────────────────────────────────────────────────

_OFFLINE_PROC_RULES = [
    ("mdworker",       "Spotlight 索引进程",    "macOS 在后台对新文件或新目录建立搜索索引，属于正常系统行为。"),
    ("mds",            "Spotlight 元数据服务",  "macOS Spotlight 的核心守护进程，统筹文件元数据更新，正常系统行为。"),
    ("backupd",        "Time Machine 备份",    "Time Machine 正在备份该文件，属于正常备份行为。"),
    ("Finder",         "Finder 文件管理器",     "用户通过 Finder 进行了此操作，或 Finder 在更新 .DS_Store 图标布局文件。"),
    ("python",         "Python 程序",          "Python 脚本或应用正在读写此文件，可结合路径判断具体用途。"),
    ("node",           "Node.js 程序",         "Node.js 应用（如 npm、前端构建工具）正在操作此文件。"),
    ("claude",         "Claude Code",          "Claude Code AI 助手正在读写此路径，通常是代码生成或编辑操作。"),
    ("vim",            "Vim 编辑器",            "Vim 在保存文件时会先写临时文件再重命名，这是正常的保存机制。"),
    ("Code",           "VS Code 编辑器",        "VS Code 或其扩展正在读写此文件。"),
    ("Xcode",          "Xcode",                "Xcode IDE 或编译工具链正在操作此文件。"),
    ("git",            "Git 版本控制",           "Git 在执行提交、检出或合并操作，属于正常版本控制行为。"),
    ("Chrome",         "Google Chrome",        "Chrome 浏览器正在读写缓存、下载目录或配置文件。"),
    ("Safari",         "Safari 浏览器",         "Safari 在读写缓存或下载内容。"),
    ("unknown",        "进程未识别",            "fs_usage 未能解析进程名，可能是内核级操作、权限受限进程，或 fd 缓存未命中导致。"),
    ("rm",             "命令行 rm 删除",        "通过 rm 命令（可能是 rm -rf）删除了此文件，由 watchdog 捕获。"),
]

_OFFLINE_OP_RULES = {
    "write":   ("写入文件内容",   "程序向文件写入数据，如保存、追加日志等。"),
    "wrdata":  ("写入文件内容",   "同 write，fs_usage 对部分写入操作使用此名称。"),
    "pwrite":  ("定位写入",       "程序在指定偏移量处写入数据，常见于数据库或大文件编辑。"),
    "creat":   ("新建文件",       "程序通过 creat() 系统调用创建了新文件。"),
    "create":  ("新建文件",       "程序创建了新文件。"),
    "mkdir":   ("新建目录",       "程序创建了一个新目录。"),
    "unlink":  ("删除文件",       "程序通过 unlink() 删除了此文件（文件从目录中移除）。"),
    "rmdir":   ("删除目录",       "程序删除了一个空目录。"),
    "rename":  ("重命名/移动",    "文件被重命名或移动到新路径。Vim 等编辑器保存时会先写临时文件再 rename。"),
    "trash":   ("移入废纸篓",     "Finder 将文件移入 ~/.Trash，底层是一次 rename 操作。"),
    "truncate":("截断文件",       "文件被清空或截短，常见于日志轮转或文件覆盖写场景。"),
    "link":    ("创建硬链接",     "为文件创建了一个硬链接。"),
    "symlink": ("创建软链接",     "创建了一个符号链接（快捷方式）。"),
    "chmod":   ("修改权限",       "文件的读写执行权限被修改。"),
}

_OFFLINE_PATH_RULES = [
    (".DS_Store",        "这是 Finder 的目录视图元数据文件，记录图标位置、视图模式等，属于正常系统文件。"),
    ("/.Trash/",         "文件已被移入废纸篓，尚未彻底删除，可从废纸篓还原。"),
    ("/tmp/",            "系统临时目录，程序运行时的中间文件，系统重启后自动清理。"),
    ("/Library/Caches/", "应用缓存目录，存放临时加速数据，可安全清理。"),
    ("/.claude",         "Claude Code 的配置/缓存目录，AI 工具的正常读写。"),
    ("/site-packages/",  "Python 第三方库目录，可能是 pip 安装或更新包。"),
    ("/node_modules/",   "Node.js 依赖包目录，npm install 等操作产生。"),
    (".git/",            "Git 仓库内部文件，git 操作的正常产物。"),
    ("__pycache__",      "Python 字节码缓存目录，Python 解释器自动生成，无需关注。"),
]

_RISK_SIGNALS = [
    ("/etc/",         "⚠️ 系统配置目录，非系统进程修改此处需特别关注。"),
    ("/usr/bin/",     "⚠️ 系统可执行文件目录，被修改可能影响系统安全。"),
    ("/usr/local/bin/","ℹ️ 用户级可执行文件目录，包管理器（如 brew）的正常写入路径。"),
    ("id_rsa",        "🔐 SSH 私钥文件，若被非 ssh 进程读写请立即检查。"),
    (".ssh/",         "🔐 SSH 配置目录，非预期修改有安全风险。"),
    ("keychain",      "🔐 钥匙串相关文件，请确认操作进程可信。"),
    ("password",      "🔐 路径含 password 字样，请确认操作来源。"),
    ("wallet",        "🔐 路径含 wallet 字样，请确认操作来源。"),
]


def _analyze_offline(event: dict) -> dict:
    op   = (event.get("op") or "").lower()
    path = event.get("path") or ""
    proc = event.get("proc") or "unknown"

    lines = []

    # 操作说明
    op_name, op_desc = _OFFLINE_OP_RULES.get(op, (event.get("op_cn", op), "未知操作类型。"))
    lines.append(f"**操作含义**：{op_name} — {op_desc}")

    # 进程说明（模糊匹配）
    proc_label = proc_desc = None
    for kw, label, desc in _OFFLINE_PROC_RULES:
        if kw.lower() in proc.lower():
            proc_label, proc_desc = label, desc
            break
    if proc_label:
        lines.append(f"**发起进程**：{proc}（{proc_label}）— {proc_desc}")
    else:
        lines.append(f"**发起进程**：{proc} — 未能识别此进程，建议结合路径和操作类型综合判断。")

    # 路径特征说明
    for kw, desc in _OFFLINE_PATH_RULES:
        if kw in path:
            lines.append(f"**路径说明**：{desc}")
            break

    # 风险信号
    risk = None
    for kw, msg in _RISK_SIGNALS:
        if kw in path:
            risk = msg
            break
    if risk:
        lines.append(f"**风险提示**：{risk}")
    else:
        lines.append("**风险评估**：未发现明显风险信号，属于常规文件系统操作。")

    return {"mode": "offline", "result": "\n\n".join(lines)}

def get_stats():
    with events_lock:
        stats = {"total": len(events), "by_type": {}, "top_processes": {}}
        for e in events:
            op   = e["op"]
            proc = e["proc"]
            stats["by_type"][op]         = stats["by_type"].get(op, 0) + 1
            stats["top_processes"][proc] = stats["top_processes"].get(proc, 0) + 1
        stats["top_processes"] = dict(
            sorted(stats["top_processes"].items(), key=lambda x: x[1], reverse=True)[:15]
        )
        stats["by_type"] = dict(
            sorted(stats["by_type"].items(), key=lambda x: x[1], reverse=True)
        )
        return jsonify(stats)


@app.route("/stream")
def stream():
    def generate():
        import queue
        q = queue.Queue(maxsize=100)
        subscribers.append(q)
        try:
            while True:
                try:
                    event = q.get(timeout=30)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"
        finally:
            try:
                subscribers.remove(q)
            except Exception:
                pass

    return Response(generate(), mimetype='text/event-stream')


# ============ 主入口 ============
if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════╗
║         📁 macOS 文件监控 Web 界面 v7.3                      ║
╠══════════════════════════════════════════════════════════════╣
║  打开浏览器访问: http://localhost:5006                       ║
║  按 Ctrl+C 停止服务                                         ║
╚══════════════════════════════════════════════════════════════╝
    """)

    if not check_and_install_dependencies():
        print("❌ 依赖安装失败")
        sys.exit(1)

    try:
        subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=2)
    except Exception:
        print("\n⚠️  提示: 建议配置 sudo 免密运行 fs_usage:")
        print("   sudo visudo")
        print(f"   添加: {os.getenv('USER', 'zzc')} ALL=(ALL) NOPASSWD: /usr/bin/fs_usage\n")

    app.run(host="0.0.0.0", port=5006, debug=False, threaded=True)
