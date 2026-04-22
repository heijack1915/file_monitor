#!/usr/bin/env python3
"""
macOS 文件监控 Web 界面 v8
主引擎：watchdog FSEvents（零 sudo、CPU < 2%）
进程识别：lsof 异步补查（约 85% 准确率）
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
monitor_thread = None
watchdog_observer = None
events = []
events_lock = threading.Lock()
subscribers = []
watch_paths_raw: list = []

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
        logging.FileHandler(LOG_DIR / 'web_server_v8.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

OP_MAP = {
    "create":  "新建",
    "modify":  "写入",
    "delete":  "删除",
    "move":    "重命名",
    "trash":   "删除(移入废纸篓)",
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
    ("/Applications", "应用程序"),
]

# lsof 进程补查线程池（最多 8 个并发）
_lsof_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="lsof")

# ── 进程缓存 ─────────────────────────────────────────────────────────────────
# 目录级缓存：lsof 单文件查到进程后写入，5s 内同目录事件直接命中
# 查询顺序：目录缓存 → lsof 单文件 → 路径规则兜底
# （移除了 lsof +D 目录扫描层：它会把 Python/Flask 自身进程误判为事件来源）
# ─────────────────────────────────────────────────────────────────────────────
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


_LSOF_NOISE = {
    'mds', 'mds_stores', 'mdworker', 'mdworker_shared', 'fseventsd',
    'kernel_task', 'launchd', 'logd', 'opendirectoryd', 'nsurlsessiond',
    'diskarbitrationd', 'loginwindow', 'WindowServer', 'sharingd',
    'distnoted', 'UserEventAgent', 'caffeinate', 'cfprefsd',
}


def _parse_lsof_proc(stdout: str) -> str:
    """从 lsof -F cn 输出中提取第一个非噪音进程名。"""
    for line in stdout.splitlines():
        if line.startswith('c'):
            name = line[1:].strip()
            if name and name not in _LSOF_NOISE:
                return name
    return "unknown"


def _query_proc_lsof(path: str) -> str:
    """
    用 lsof 查询当前持有该路径的进程名。
    对目录路径额外查父目录 cwd（mkdir/rmdir 操作者的 cwd 在父目录）。
    有时间窗口限制：进程关闭文件后查不到，返回 unknown。
    """
    p = Path(path)
    try:
        r = subprocess.run(
            ["lsof", "-F", "cn", "--", path],
            capture_output=True, text=True, timeout=1.5
        )
        proc = _parse_lsof_proc(r.stdout)
        if proc != "unknown":
            return proc
    except Exception:
        pass

    # 对目录（或已删除路径）额外查父目录下 cwd 为该目录的进程
    parent = str(p.parent)
    try:
        r2 = subprocess.run(
            ["lsof", "-d", "cwd", "-a", "-F", "cn", "--", parent],
            capture_output=True, text=True, timeout=1.5
        )
        proc = _parse_lsof_proc(r2.stdout)
        if proc != "unknown":
            return proc
    except Exception:
        pass

    return "unknown"


# 路径特征 → 进程推断（lsof 未查到时兜底）
_PATH_PROC_RULES = [
    # Finder / macOS UI
    ('/.Trash/',              'Finder'),
    ('.DS_Store',             'Finder'),
    ('/Desktop/',             'Finder'),
    # Spotlight / 元数据
    ('/Spotlight-V100/',      'mds'),
    ('/.Spotlight-',          'mds'),
    ('/Library/Metadata/',    'mdworker'),
    # Time Machine
    ('/.MobileBackups/',      'backupd'),
    ('/Backups.backupdb/',    'backupd'),
    # Xcode / 编译
    ('/DerivedData/',         'Xcode'),
    ('/Build/Products/',      'xcodebuild'),
    # Homebrew
    ('/Cellar/',              'brew'),
    ('/homebrew/',            'brew'),
    ('/opt/homebrew/',        'brew'),
    # Python / pip
    ('/Library/Python/',      'python'),
    ('/site-packages/',       'pip'),
    ('__pycache__',           'python'),
    ('.pyc',                  'python'),
    # Node.js / npm
    ('/node_modules/',        'npm'),
    ('/tmp/npm-',             'npm'),
    ('/tmp/node-',            'node'),
    # Claude / AI
    ('/.claude',              'claude'),
    ('/claude/',              'claude'),
    ('/tmp/claude-',          'claude'),
    # Git
    ('.git/',                 'git'),
    ('.git_',                 'git'),
    # 编辑器
    ('/.vscode/',             'Code'),
    ('/Library/Application Support/Code/', 'Code'),
    # 系统 prefs / cfprefsd
    ('/Library/Preferences/', 'cfprefsd'),
    ('/Preferences/com.',     'cfprefsd'),
    # 日志
    ('/Library/Logs/',        'syslogd'),
    # iCloud
    ('/Mobile Documents/',    'bird'),
    ('/.icloud',              'bird'),
    # 通用临时
    ('/tmp/',                 'system'),
    ('/var/folders/',         'system'),
]


def _infer_proc_from_path(path: str) -> str:
    for fragment, name in _PATH_PROC_RULES:
        if fragment in path:
            return name
    return "unknown"


def _push_event(op_key: str, path: str, proc: str):
    """构造事件对象并入库推送"""
    if 'FileMonitor' in path:
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


def _resolve_proc(path: str, try_lsof: bool = True) -> str:
    """
    统一进程查询链：目录缓存 → lsof 单文件（可选）→ 路径规则兜底
    delete/rmdir 类事件文件已消失，传 try_lsof=False 跳过无效的 lsof 调用。
    """
    proc = _lookup_dir_cache(path)
    if proc != "unknown":
        return proc
    if try_lsof:
        proc = _query_proc_lsof(path)
        if proc != "unknown":
            _cache_proc(path, proc)
            return proc
    return _infer_proc_from_path(path)


def _handle_event_async(op_key: str, path: str):
    proc = _resolve_proc(path, try_lsof=True)
    _push_event(op_key, path, proc)



def _resolve_delete(path: str):
    """
    文件删除事件延迟 300ms 后判断是废纸篓还是真正删除。
    Finder 移入废纸篓底层是 rename(src→~/.Trash/)，watchdog 在监控目录侧看到的是 DELETED。
    文件已消失，lsof 无效，只用缓存和路径规则。
    """
    time.sleep(0.3)

    src = Path(path)
    trash_candidate = Path.home() / ".Trash" / src.name

    in_trash = False
    if trash_candidate.exists():
        try:
            ctime = trash_candidate.stat().st_ctime
            in_trash = ctime >= time.time() - 5.0
        except OSError:
            pass

    if in_trash:
        op_key = "trash"
        display_path = str(trash_candidate)
    else:
        op_key = "delete"
        display_path = path

    proc = _resolve_proc(path, try_lsof=False)
    _push_event(op_key, display_path, proc)


def _handle_moved(src_path: str, dest_path: str):
    """
    watchdog on_moved 事件：dest_path 已知，直接用，无需延迟扫描目录。
    """
    src = Path(src_path)
    proc = _resolve_proc(dest_path, try_lsof=True)

    event = {
        "id":         int(time.time() * 1000000),
        "timestamp":  datetime.now().strftime("%H:%M:%S"),
        "date":       datetime.now().strftime("%Y-%m-%d"),
        "op":         "move",
        "op_cn":      get_op_cn("move"),
        "path":       dest_path,
        "path_short": simplify_path(dest_path) + f"  (← {src.name})",
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
    启动 watchdog FSEvents 作为主监控引擎。
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
            p = path[len('/private'):] if path.startswith('/private') else path
            return any(p.startswith(str(wp)) or path.startswith(str(wp))
                       for wp in self._watch_paths)

        def on_created(self, ev):
            if not self._in_watch(ev.src_path):
                return
            op = "mkdir" if ev.is_directory else "create"
            _lsof_executor.submit(_handle_event_async, op, ev.src_path)

        def on_modified(self, ev):
            if ev.is_directory or not self._in_watch(ev.src_path):
                return
            _lsof_executor.submit(_handle_event_async, "modify", ev.src_path)

        def on_deleted(self, ev):
            if not self._in_watch(ev.src_path):
                return
            if ev.is_directory:
                _lsof_executor.submit(_handle_event_async, "rmdir", ev.src_path)
            else:
                # 延迟检测：可能是 Finder 移入废纸篓（底层是 rename→DELETED）
                threading.Thread(
                    target=_resolve_delete,
                    args=(ev.src_path,),
                    daemon=True
                ).start()

        def on_moved(self, ev):
            if not self._in_watch(ev.src_path):
                return
            _lsof_executor.submit(_handle_moved, ev.src_path, ev.dest_path)

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
        expanded = Path(p).expanduser().resolve()
        if expanded.exists():
            watch_paths.append(expanded)

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
    ("unknown",        "进程未识别",            "lsof 补查时进程已关闭文件，或为内核级操作、权限受限进程。属于正常的时序盲区。"),
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
║         📁 macOS 文件监控 Web 界面 v8                        ║
╠══════════════════════════════════════════════════════════════╣
║  打开浏览器访问: http://localhost:5006                       ║
║  按 Ctrl+C 停止服务                                         ║
╚══════════════════════════════════════════════════════════════╝
    """)

    if not check_and_install_dependencies():
        print("❌ 依赖安装失败")
        sys.exit(1)

    app.run(host="0.0.0.0", port=5006, debug=False, threaded=True)
