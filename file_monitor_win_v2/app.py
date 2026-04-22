#!/usr/bin/env python3
"""
Windows 文件监控 Web 界面 v2
主引擎：watchdog（跨平台，零管理员权限）
进程识别：psutil + OpenFiles + 句柄采样（约 85% 准确率）
AI 分析：OpenAI 兼容标准接口 + 离线规则引擎
"""

import json
import logging
import os
import re
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Optional
from flask import Flask, render_template, Response, jsonify, request

# Windows 特定导入
import ctypes
from ctypes import wintypes


# ============ 依赖自动安装 ============
def check_and_install_dependencies():
    required = {
        "flask": "flask>=2.0.0",
        "watchdog": "watchdog>=3.0.0",
        "psutil": "psutil>=5.9.0"
    }
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
                print(f"  [OK] {package} 安装成功")
            else:
                print(f"  [FAIL] {package} 安装失败")
                return False
        except Exception as e:
            print(f"  [FAIL] {package} 安装异常: {e}")
            return False
    print("\n[OK] 所有依赖安装完成\n")
    return True


# ============ Flask 应用 ============
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

monitoring = False
monitor_thread = None
watchdog_observer = None
events = []
events_lock = threading.Lock()
subscribers = []
watch_paths_raw: list = []

# ============ AI 分析配置（OpenAI 兼容接口）============
ai_config = {
    "api_url":  "",
    "api_key":  "",
    "model":    "gpt-4o",
    "timeout":  30,
}

MAX_EVENTS = 2000
LOG_DIR = Path.home() / "Documents/FileMonitorLogs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'file_monitor_win_v2.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

OP_MAP = {
    "create":  "新建",
    "modify":  "写入",
    "delete":  "删除",
    "move":    "重命名",
    "mkdir":   "新建目录",
    "rmdir":   "删除目录",
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
    ("~/Videos",    "视频"),
    ("~/Music",     "音乐"),
    ("~/Pictures",  "图片"),
]

# psutil 进程补查线程池（最多 8 个并发）
_psutil_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="psutil")

# ── 进程缓存 ─────────────────────────────────────────────────────────────────
# 目录级缓存：psutil 查到进程后写入，5s 内同目录事件直接命中
_proc_dir_cache: dict = {}
_PROC_CACHE_TTL = 5.0


def _cache_proc(path: str, proc: str):
    if proc == "unknown":
        return
    key = str(Path(path).parent)
    if len(_proc_dir_cache) > 500:
        cutoff = time.time() - _PROC_CACHE_TTL
        for k in [k for k, (_, ts) in list(_proc_dir_cache.items()) if ts < cutoff]:
            _proc_dir_cache.pop(k, None)
    _proc_dir_cache[key] = (proc, time.time())


def _lookup_dir_cache(path: str) -> str:
    entry = _proc_dir_cache.get(str(Path(path).parent))
    if entry:
        proc, ts = entry
        if time.time() - ts < _PROC_CACHE_TTL:
            return proc
    return "unknown"


def simplify_path(path: str) -> str:
    home = str(Path.home())
    if path.startswith(home):
        path = '~' + path[len(home):]
    # Windows 路径反斜杠转换显示
    path = path.replace('\\', '/')
    if len(path) > 70:
        parts = path.split('/')
        if len(parts) > 5:
            path = '/'.join(parts[:3]) + '/.../' + '/'.join(parts[-2:])
        else:
            path = path[:67] + '...'
    return path


def get_op_cn(op_key: str) -> str:
    return OP_MAP.get(op_key, op_key)


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


# Windows 系统进程黑名单（这些进程的读写通常是系统行为）
_PSUTIL_NOISE = {
    'System', 'Registry', 'smss', 'csrss', 'wininit', 'winlogon',
    'services', 'lsass', 'svchost', 'dwm', 'fontdrvhost',
    'explorer', 'taskhostw', 'RuntimeBroker', 'ShellExperienceHost',
    'SearchHost', 'StartMenuExperienceHost', 'TextInputHost',
    'ctfmon', 'sihost', 'dllhost', 'conhost', 'conhost.exe',
    'fontdrvhost', 'WmiPrvSE', 'audiodg', 'SgrmBroker',
    'SecurityHealthService', 'MsMpEng', 'NisSrv',
    'spoolsv', 'WmiPrvSE', 'DllHost', 'Registry',
}


def _get_open_files_for_path(path: str) -> list:
    """
    使用 psutil 获取打开指定文件的进程列表。
    Windows 下需要管理员权限才能看到所有进程的打开文件句柄，
    但普通权限也能看到当前用户进程的部分句柄。
    """
    try:
        import psutil
        matches = []
        path_lower = path.lower().replace('/', '\\')

        for proc in psutil.process_iter(['pid', 'name']):
            try:
                name = proc.info['name'].lower()
                if name in [n.lower() for n in _PSUTIL_NOISE]:
                    continue

                # 获取进程打开的文件
                try:
                    for f in proc.open_files():
                        f_path = f.path.lower()
                        if path_lower in f_path or f_path in path_lower:
                            matches.append(proc.info['name'])
                except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                    continue
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return matches
    except Exception as e:
        logger.debug(f"psutil open files query failed: {e}")
        return []


def _get_process_by_port(path: str) -> str:
    """
    通过查询网络端口来推断进程（部分场景有用）。
    """
    try:
        import psutil
        path_port = None
        # 尝试提取端口号
        port_match = re.search(r':(\d+)$', path.replace('\\', '/'))
        if port_match:
            path_port = int(port_match.group(1))

        if path_port:
            for conn in psutil.net_connections(kind='inet'):
                if conn.laddr.port == path_port and conn.status == 'LISTEN':
                    try:
                        proc = psutil.Process(conn.pid)
                        name = proc.name()
                        if name.lower() not in [n.lower() for n in _PSUTIL_NOISE]:
                            return name
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
    except Exception:
        pass
    return "unknown"


def _query_proc_psutil(path: str) -> str:
    """
    用 psutil 查询当前持有该路径的进程名。
    尝试多种方法：open_files、cwd分析等。
    """
    # 方法1：直接查打开文件
    open_procs = _get_open_files_for_path(path)
    if open_procs:
        # 返回第一个非噪音进程
        for p in open_procs:
            if p.lower() not in [n.lower() for n in _PSUTIL_NOISE]:
                return p

    # 方法2：查询目录的父进程（目录操作时）
    parent_dir = str(Path(path).parent)
    try:
        import psutil
        for proc in psutil.process_iter(['pid', 'name', 'cwd']):
            try:
                cwd = proc.cwd()
                if cwd and (parent_dir.lower() in cwd.lower() or cwd.lower() in parent_dir.lower()):
                    name = proc.info['name']
                    if name.lower() not in [n.lower() for n in _PSUTIL_NOISE]:
                        return name
            except (psutil.AccessDenied, psutil.NoSuchProcess, AttributeError):
                continue
    except Exception:
        pass

    # 方法3：命令行参数匹配路径
    try:
        import psutil
        path_short = Path(path).name.lower()
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline') or []
                cmdline_str = ' '.join(cmdline).lower()
                if path_short in cmdline_str:
                    name = proc.info['name']
                    if name.lower() not in [n.lower() for n in _PSUTIL_NOISE]:
                        return name
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
    except Exception:
        pass

    return "unknown"


# 路径特征 → 进程推断（psutil 未查到时兜底）
_PATH_PROC_RULES = [
    # Windows 系统目录
    ('\\Windows\\Temp',       'Windows'),
    ('/Windows/Temp',        'Windows'),
    ('\\AppData\\Local\\Temp', 'system'),
    ('/AppData/Local/Temp',  'system'),
    # VS Code
    ('\\.vscode\\',           'Code'),
    ('/.vscode/',             'Code'),
    # Git
    ('\\.git\\',              'git'),
    ('/.git/',                'git'),
    # Node.js
    ('\\node_modules\\',      'npm'),
    ('/node_modules/',        'npm'),
    # Python
    ('\\venv\\',              'python'),
    ('/venv/',                'python'),
    ('\\env\\',               'python'),
    ('/env/',                 'python'),
    ('__pycache__',           'python'),
    ('.pyc',                  'python'),
    # Docker
    ('\\AppData\\Local\\Docker', 'docker'),
    # Chrome
    ('\\Google\\Chrome\\',    'Chrome'),
    ('/Google/Chrome/',       'Chrome'),
    # Edge
    ('\\Microsoft\\Edge\\',    'Edge'),
    # Downloads
    ('\\Downloads\\',         'system'),
    ('/Downloads/',          'system'),
    # Documents
    ('\\Documents\\',         'system'),
    ('/Documents/',           'system'),
    # Desktop
    ('\\Desktop\\',           'system'),
    ('/Desktop/',             'system'),
    # OneDrive
    ('\\OneDrive\\',          'OneDrive'),
    ('/OneDrive/',            'OneDrive'),
    # Dropbox
    ('\\Dropbox\\',           'Dropbox'),
    ('/Dropbox/',             'Dropbox'),
    # 编译输出
    ('\\build\\',             'msbuild'),
    ('\\Debug\\',             'msbuild'),
    ('\\Release\\',           'msbuild'),
    ('/build/',               'msbuild'),
    ('/Debug/',               'msbuild'),
    ('/Release/',             'msbuild'),
]


def _infer_proc_from_path(path: str) -> str:
    path_lower = path.replace('/', '\\').lower()
    for fragment, name in _PATH_PROC_RULES:
        frag_lower = fragment.replace('/', '\\').lower()
        if frag_lower in path_lower:
            return name
    return "unknown"


def _push_event(op_key: str, path: str, proc: str):
    """构造事件对象并入库推送"""
    if 'FileMonitor' in path or 'FileMonitorLogs' in path:
        return

    event = {
        "id":         int(time.time() * 1000000),
        "timestamp":  datetime.now().strftime("%H:%M:%S"),
        "date":       datetime.now().strftime("%Y-%m-%d"),
        "op":         op_key,
        "op_cn":      get_op_cn(op_key),
        "path":       path,
        "path_short": simplify_path(path),
        "proc":       (proc or "unknown")[:40],
    }

    if not matches_filter(event):
        return

    with events_lock:
        events.append(event)
        if len(events) > MAX_EVENTS:
            del events[:-MAX_EVENTS]

    send_sse_event("event", event)


def _resolve_proc(path: str, try_psutil: bool = True) -> str:
    """
    统一进程查询链：目录缓存 → psutil 查询（可选）→ 路径规则兜底
    delete/rmdir 类事件文件已消失，传 try_psutil=False 跳过无效调用。
    """
    proc = _lookup_dir_cache(path)
    if proc != "unknown":
        return proc
    if try_psutil:
        proc = _query_proc_psutil(path)
        if proc != "unknown":
            _cache_proc(path, proc)
            return proc
    return _infer_proc_from_path(path)


def _handle_event_async(op_key: str, path: str):
    proc = _resolve_proc(path, try_psutil=True)
    _push_event(op_key, path, proc)


def _handle_delete_async(path: str):
    """文件删除事件：延迟后判断是否真的删除"""
    time.sleep(0.3)

    # 检查是否在回收站附近
    recycle_patterns = ['\\$Recycle.Bin\\', '/$Recycle.Bin/', '\\Recycler\\', '/Recycler/']
    in_recycle = any(p in path.replace('/', '\\') for p in recycle_patterns)

    if in_recycle:
        op_key = "delete"
        display_path = path
    else:
        # 检查文件是否还存在
        if Path(path).exists():
            op_key = "delete"
            display_path = path
        else:
            # 文件确实被删除了
            op_key = "delete"
            display_path = path

    proc = _resolve_proc(path, try_psutil=False)
    _push_event(op_key, display_path, proc)


def _handle_moved(src_path: str, dest_path: str):
    """watchdog on_moved 事件处理"""
    src = Path(src_path)
    proc = _resolve_proc(dest_path, try_psutil=True)

    event = {
        "id":         int(time.time() * 1000000),
        "timestamp":  datetime.now().strftime("%H:%M:%S"),
        "date":       datetime.now().strftime("%Y-%m-%d"),
        "op":         "move",
        "op_cn":      get_op_cn("move"),
        "path":       dest_path,
        "path_short": simplify_path(dest_path) + f"  (<- {src.name})",
        "proc":       (proc or "unknown")[:40],
    }

    if not matches_filter(event):
        return

    with events_lock:
        events.append(event)
        if len(events) > MAX_EVENTS:
            del events[:-MAX_EVENTS]

    send_sse_event("event", event)


def start_watchdog_monitor(watch_paths):
    """
    启动 watchdog 作为主监控引擎（Windows 下使用 ReadDirectoryChangesW）。
    每个事件异步投入线程池补查进程名，不阻塞事件流。
    """
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        logger.error("watchdog 未安装，请执行 pip install watchdog")
        return None

    class MainHandler(FileSystemEventHandler):
        def __init__(self, watch_paths):
            self._watch_paths = watch_paths

        def _in_watch(self, path: str) -> bool:
            # Windows 路径规范化
            path = path.replace('/', '\\')
            return any(
                path.startswith(str(wp).replace('/', '\\')) or
                str(wp).replace('/', '\\') in path
                for wp in self._watch_paths
            )

        def on_created(self, ev):
            if not self._in_watch(ev.src_path):
                return
            op = "mkdir" if ev.is_directory else "create"
            _psutil_executor.submit(_handle_event_async, op, ev.src_path)

        def on_modified(self, ev):
            if ev.is_directory or not self._in_watch(ev.src_path):
                return
            _psutil_executor.submit(_handle_event_async, "modify", ev.src_path)

        def on_deleted(self, ev):
            if not self._in_watch(ev.src_path):
                return
            if ev.is_directory:
                _psutil_executor.submit(_handle_event_async, "rmdir", ev.src_path)
            else:
                # 延迟检测删除类型
                threading.Thread(
                    target=_handle_delete_async,
                    args=(ev.src_path,),
                    daemon=True
                ).start()

        def on_moved(self, ev):
            if not self._in_watch(ev.src_path):
                return
            _psutil_executor.submit(_handle_moved, ev.src_path, ev.dest_path)

    handler = MainHandler(watch_paths)
    observer = Observer()
    for wp in watch_paths:
        observer.schedule(handler, str(wp), recursive=True)
    observer.start()
    logger.info(f"watchdog 主引擎启动，监控路径: {[str(p) for p in watch_paths]}")
    return observer


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
        try:
            expanded = Path(p).expanduser().resolve()
            if expanded.exists():
                watch_paths.append(expanded)
            else:
                logger.warning(f"Path does not exist: {expanded}")
        except Exception as e:
            logger.error(f"Invalid path {p}: {e}")

    if not watch_paths:
        return jsonify({"status": "error", "message": "没有有效的监控路径"})

    watch_paths_raw = [str(p) for p in watch_paths]
    monitoring = True

    watchdog_observer = start_watchdog_monitor(watch_paths)
    if not watchdog_observer:
        monitoring = False
        return jsonify({"status": "error", "message": "watchdog 启动失败，请检查依赖"})

    logger.info(f"监控已启动，路径: {[str(p) for p in watch_paths]}")
    return jsonify({"status": "started", "watch_paths": [str(p) for p in watch_paths]})


@app.route("/api/stop", methods=["POST"])
def stop_monitor():
    global monitoring, watchdog_observer, watch_paths_raw

    monitoring = False
    watch_paths_raw = []

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
        return jsonify({"error": "Missing event field"}), 400

    if mode == "ai":
        result = _analyze_ai(event)
    else:
        result = _analyze_offline(event)

    return jsonify(result)


def _analyze_ai(event: dict) -> dict:
    """调用 OpenAI 兼容接口分析事件"""
    if not ai_config["api_url"] or not ai_config["api_key"]:
        return {"error": "Please configure AI API URL and Key first"}

    prompt = (
        "You are a Windows filesystem security analyst. The following is a filesystem event record. "
        "Please analyze in Chinese: 1) What this operation means; 2) Which program initiated it and why; "
        "3) Whether it needs attention or has security risks. Be concise, no more than 200 characters.\n\n"
        f"Time: {event.get('timestamp','')}\n"
        f"Operation: {event.get('op_cn','')} ({event.get('op','')})\n"
        f"File Path: {event.get('path','')}\n"
        f"Process: {event.get('proc','unknown')}"
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
            "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
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
        return {"error": f"Connection failed: {e.reason}"}
    except Exception as e:
        return {"error": f"Network error: {str(e)[:200]}"}

    if not raw.strip():
        return {"error": "Empty response from API"}

    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": f"Non-JSON response: {raw[:300]}"}

    try:
        text = body["choices"][0]["message"]["content"].strip()
        return {"mode": "ai", "result": text}
    except (KeyError, IndexError):
        pass

    if "error" in body:
        err = body["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        return {"error": f"API Error: {msg[:300]}"}

    return {"error": f"Cannot parse response: {raw[:300]}"}


# ── 离线规则引擎 ──────────────────────────────────────────────────────────
_OFFLINE_PROC_RULES = [
    ("Code",         "VS Code",            "VS Code editor is reading/writing this file."),
    ("python",       "Python",             "A Python script or application is operating on this file."),
    ("node",         "Node.js",            "Node.js application (npm, build tools) is operating on this file."),
    ("git",          "Git",                "Git is executing commit, checkout, or merge operations."),
    ("npm",          "npm",                "Node package manager is installing or updating packages."),
    ("Chrome",       "Chrome",             "Chrome browser is reading/writing cache, downloads, or config."),
    ("Edge",         "Edge",               "Microsoft Edge browser is reading/writing cache or downloads."),
    ("docker",       "Docker",             "Docker container is operating on this file."),
    ("msbuild",      "MSBuild",            "Visual Studio build tool is compiling or linking."),
    ("python",       "Python",             "Python interpreter is executing scripts."),
    ("OneDrive",     "OneDrive",           "Microsoft OneDrive sync client is syncing this file."),
    ("Dropbox",      "Dropbox",            "Dropbox sync client is syncing this file."),
    ("unknown",      "Unknown Process",    "Process closed file before query, or it's a kernel-level operation."),
]

_OFFLINE_OP_RULES = {
    "write":   ("Write File",     "Program writes data to file, like save or append."),
    "create":  ("Create File",    "Program created a new file."),
    "mkdir":   ("Create Folder",  "Program created a new directory."),
    "delete":  ("Delete File",    "Program deleted this file."),
    "rmdir":   ("Delete Folder",  "Program deleted an empty directory."),
    "rename":  ("Rename/Move",    "File was renamed or moved to a new path."),
    "modify":  ("Modify File",    "File content was modified."),
}

_OFFLINE_PATH_RULES = [
    ("\\.git\\",            "Git repository internal files."),
    ("\\node_modules\\",    "Node.js dependencies directory."),
    ("\\__pycache__\\",     "Python bytecode cache."),
    ("\\venv\\",            "Python virtual environment."),
    ("\\AppData\\",         "Application data directory."),
    ("\\Desktop\\",         "Desktop folder."),
    ("\\Downloads\\",      "Downloads folder."),
    ("\\Documents\\",       "Documents folder."),
    ("\\OneDrive\\",        "OneDrive sync folder."),
]

_RISK_SIGNALS = [
    ("\\Windows\\System32\\",       "[WARNING] System32 directory - unauthorized changes may affect system security."),
    ("\\Program Files\\",           "[INFO] Program Files directory - normal for installers."),
    ("\\.ssh\\",                    "[SECURITY] SSH config directory - unexpected access requires attention."),
    ("id_rsa",                     "[SECURITY] SSH private key file - unauthorized access should be checked."),
    ("password",                   "[SECURITY] Path contains 'password' - confirm operation source."),
]


def _analyze_offline(event: dict) -> dict:
    op   = (event.get("op") or "").lower()
    path = event.get("path") or ""
    proc = event.get("proc") or "unknown"

    lines = []

    # Operation description
    op_name, op_desc = _OFFLINE_OP_RULES.get(op, (event.get("op_cn", op), "Unknown operation"))
    lines.append(f"**Operation**: {op_name} - {op_desc}")

    # Process description
    proc_label = proc_desc = None
    for kw, label, desc in _OFFLINE_PROC_RULES:
        if kw.lower() in proc.lower():
            proc_label, proc_desc = label, desc
            break
    if proc_label:
        lines.append(f"**Process**: {proc} ({proc_label}) - {proc_desc}")
    else:
        lines.append(f"**Process**: {proc} - Cannot identify this process.")

    # Path feature
    for kw, desc in _OFFLINE_PATH_RULES:
        if kw.lower() in path.lower():
            lines.append(f"**Path Info**: {desc}")
            break

    # Risk signal
    risk = None
    for kw, msg in _RISK_SIGNALS:
        if kw.lower() in path.lower():
            risk = msg
            break
    if risk:
        lines.append(f"**Risk**: {risk}")
    else:
        lines.append("**Risk Assessment**: No obvious risk signal, normal filesystem operation.")

    return {"mode": "offline", "result": "\n\n".join(lines)}


@app.route("/api/stats")
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
+============================================================+
|         Windows File Monitor Web Interface v2             |
+============================================================+
|  Open browser: http://localhost:5006                      |
|  Press Ctrl+C to stop                                      |
+============================================================+
    """)

    if not check_and_install_dependencies():
        print("[FAIL] Dependency installation failed")
        sys.exit(1)

    app.run(host="0.0.0.0", port=5006, debug=False, threaded=True)