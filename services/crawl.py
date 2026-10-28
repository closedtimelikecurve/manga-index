# -*- coding: utf-8 -*-
"""爬虫任务状态 / 清单 / 日志（3.6.25 从 app.py 拆出）。

为什么拆：app.py 原本 6233 行、264 个函数混在一起，改一处要通读全文。
本模块只负责"爬虫任务的进程句柄、清单文件、断点 state、日志读写"，
与文库扫描/HTTP 端点正交。

状态共享约定（重要）：_CRAWL_TASKS / _CRAWL_LOCK 定义在本模块，app.py 以
"from services.crawl import _CRAWL_TASKS" 引用**同一个对象**。两边都不要再
重新赋值（那样会分叉成两份状态）。
"""
import json
import logging
import os
import tempfile
import threading
import time

from common import APP_DIR, LOG_DIR, STATE_DIR, ensure_dir

log = logging.getLogger(__name__)


_CRAWL_LIST_WNACG = os.path.join(APP_DIR, "pending_wnacg.txt")
# 3.6.36：索引系（JM 索引 / N站索引）整合为一个模式、两份目标共享同一份清单
_CRAWL_LIST_INDEX = os.path.join(APP_DIR, "pending_index.txt")
_CRAWL_LIST_JM = _CRAWL_LIST_INDEX      # 兼容别名（crawl_jm_ids.py 的 --list 默认值同文件）
_CRAWL_LIST_NH = _CRAWL_LIST_INDEX      # 兼容别名（crawl_nh_ids.py 的 --list 默认值同文件）
_CRAWL_LIST_JMDL_T = os.path.join(APP_DIR, "pending_jmdl_titles.txt")   # 3.6.7：jmdl 独占两份清单
_CRAWL_LIST_JMDL_I = os.path.join(APP_DIR, "pending_jmdl_ids.txt")
_CRAWL_LIST_NHDL = os.path.join(APP_DIR, "pending_nhdl.txt")   # 3.6.36：N站直连（ID 或词条）
_CRAWL_LIST_EH = os.path.join(APP_DIR, "pending_ehdl.txt")     # 3.6.110：E站直连（URL/词条）
_CRAWL_LIST_EXT = os.path.join(APP_DIR, "pending_ext.txt")     # 3.6.155：外接下载器（每行一条 URL/参数）
_CRAWL_STATE_FILE = os.path.join(STATE_DIR, "crawl_state.json")
_CRAWL_STATE_FILE_JMDL = os.path.join(STATE_DIR, "crawl_state_jmdl.json")
_CRAWL_STATE_FILE_EH = os.path.join(STATE_DIR, "crawl_state_eh.json")
_CRAWL_STATE_FILE_EXT = os.path.join(STATE_DIR, "crawl_state_ext.json")
_CRAWL_LOG_FILE = os.path.join(LOG_DIR, "crawl_log.txt")
_CRAWL_LOG_FILE_JM = os.path.join(LOG_DIR, "crawl_log_jm.txt")
_CRAWL_LOG_FILE_JMDL = os.path.join(LOG_DIR, "crawl_log_jmdl.txt")
_CRAWL_LOG_FILE_NH = os.path.join(LOG_DIR, "crawl_log_nh.txt")
_CRAWL_LOG_FILE_NHDL = os.path.join(LOG_DIR, "crawl_log_nhdl.txt")
_CRAWL_LOG_FILE_EH = os.path.join(LOG_DIR, "crawl_log_eh.txt")
_CRAWL_LOG_FILE_EXT = os.path.join(LOG_DIR, "crawl_log_ext.txt")

_CRAWL_TASKS = {"wnacg": {"proc": None, "startedAt": None},
                "jm": {"proc": None, "startedAt": None},
                "jmdl": {"proc": None, "startedAt": None},
                "nh": {"proc": None, "startedAt": None},
                "nhdl": {"proc": None, "startedAt": None},
                "eh": {"proc": None, "startedAt": None}}
# 3.6.46：爬虫脚本收进 `crawlers/` 包（域名即目录）。_CRAWL_KINDS 里仍记**裸文件名**，
# 真实路径一律经 crawl_script_path() 解析 —— 这样测试的"脚本文件存在"断言只需改一处。
_CRAWL_DIR = os.path.join(APP_DIR, "crawlers")


def crawl_script_path(script):
    """裸文件名 → 爬虫脚本绝对路径（`_app/crawlers/<script>`）。"""
    return os.path.join(_CRAWL_DIR, script)


# 3.6.156：按任务探测内置站点适配是否随发行版提供。
# 公开发行版只带 JM 直连（crawl_jm_direct，底层是公开的 jmcomic 库），其余站点适配
# 被剔除——此时 importlib 找不到对应模块，任务从「可用清单」里消失，前端据此隐藏胶囊。
_KIND_CRAWLER_MODULE = {
    "wnacg": "crawlers.crawl_wnacg", "jm": "crawlers.crawl_jm_ids",
    "jmdl": "crawlers.crawl_jm_direct", "nh": "crawlers.crawl_nh_ids",
    "nhdl": "crawlers.crawl_nh_direct", "eh": "crawlers.crawl_ehentai",
}
_KIND_ORDER = ("wnacg", "jm", "jmdl", "nh", "nhdl", "eh", "ext")


def available_kinds():
    """当前发行版可用的任务 kind（保持 _KIND_ORDER 顺序；ext 恒可用）。"""
    import importlib.util
    out = []
    for kind in _KIND_ORDER:
        mod = _KIND_CRAWLER_MODULE.get(kind)
        if mod is None:                                 # ext：外接下载器，不依赖 crawlers 包
            out.append(kind)
            continue
        try:
            if importlib.util.find_spec(mod) is not None:
                out.append(kind)
        except (ImportError, ValueError):
            pass                                        # 命名空间异常按不可用处理
    return out

# 3.6.38 #35：每个任务的"本次运行日志起点"（启动时记录日志文件字节位置）。
# 日志区只展示本次任务的实时输出；任务结束后前端自动清除，历史只进文件存档。
# None = 无进行中的任务（status 不回传任何日志行）。
_CRAWL_LOCK = threading.Lock()
_CRAWL_KINDS = {
    "wnacg": ("crawl_wnacg.py", ["--list", _CRAWL_LIST_WNACG]),
    "jm": ("crawl_jm_ids.py", ["--list", _CRAWL_LIST_JM]),
    # 3.6.7：直连不再复用 wnacg/jm 的清单，独占「pending_jmdl_titles / pending_jmdl_ids」两份
    "jmdl": ("crawl_jm_direct.py",
             ["--list", _CRAWL_LIST_JMDL_I, "--titles", _CRAWL_LIST_JMDL_T]),
    # 3.6.30：N站两模式——索引（同 jm：ID/词条→标题→wnacg）与直连（ID/词条→ZIP 整本）
    "nh": ("crawl_nh_ids.py", ["--list", _CRAWL_LIST_NH]),
    "nhdl": ("crawl_nh_direct.py", ["--list", _CRAWL_LIST_NHDL]),
    # 3.6.110：E站直连（画廊 URL / 标题词条 → 种子优先/逐页兜底 → ZIP 整本）
    "eh": ("crawl_ehentai.py", ["--list", _CRAWL_LIST_EH]),
    # 3.6.155：外接下载器——没有独立脚本，条目即命令参数；两段式引擎里走专用路径
    # （跳过锁定/封面阶段，直接由 crawl_fetch.dl_ext 起子进程）。
    "ext": ("ext", []),
}   # 失败词条无需专门重试：留在清单里，再跑一轮即自动按当前档位重爬

def _crawl_state_file(kind):
    """各任务的断点 state 文件（wnacg 保持可打桩的 _CRAWL_STATE_FILE）。"""
    if kind == "jmdl":
        return _CRAWL_STATE_FILE_JMDL
    if kind == "nhdl":
        return os.path.join(STATE_DIR, "crawl_state_nhdl.json")
    if kind == "eh":
        return _CRAWL_STATE_FILE_EH
    if kind == "ext":
        return _CRAWL_STATE_FILE_EXT   # 3.6.155：外接下载器独立断点，不与 wnacg 混写
    return _CRAWL_STATE_FILE          # wnacg 与 jm 索引（jm 只读 domain 缓存，不写 done）

def _crawl_log_file(kind):
    """各任务的日志文件（wnacg/默认保持可打桩的 _CRAWL_LOG_FILE）。"""
    if kind == "jm":
        return _CRAWL_LOG_FILE_JM
    if kind == "jmdl":
        return _CRAWL_LOG_FILE_JMDL
    if kind == "nh":
        return _CRAWL_LOG_FILE_NH
    if kind == "nhdl":
        return _CRAWL_LOG_FILE_NHDL
    if kind == "eh":
        return _CRAWL_LOG_FILE_EH
    if kind == "ext":
        return _CRAWL_LOG_FILE_EXT    # 3.6.155：外接下载器（工具 stdout 节流进这里）
    return _CRAWL_LOG_FILE

def _crawl_proc(kind="wnacg"):
    """返回该 kind 仍在运行的子进程句柄；已退出的自动清位（不留僵尸状态）。"""
    t = _CRAWL_TASKS.get(kind)
    if t is None:
        return None
    p = t.get("proc")
    if p is not None and p.poll() is not None:
        t["proc"] = None
        t["startedAt"] = None
        return None
    return p

_CRAWL_LOG_TAIL_LINES = 200
_CRAWL_LOG_READ_MAX = 256 * 1024      # 单次最多读取的字节（防止一次性把 5MB 日志读进来）

def _crawl_log_append(text, path=None):
    """往爬虫日志追加一行（启动任务时先写一行标记：手机端一按启动立刻就有反馈）。"""
    line = time.strftime("[%H:%M:%S] ") + text + "\n"
    path = path or _CRAWL_LOG_FILE
    try:
        ensure_dir(os.path.dirname(path) or APP_DIR)   # _logs/ 首次运行需先建
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        log.exception("写入爬虫日志失败")
    return line

def _crawl_log_tail(n=_CRAWL_LOG_TAIL_LINES, max_bytes=_CRAWL_LOG_READ_MAX, path=None):
    """末 n 行 + 文件字节数。从尾部按块读，不再把整个日志读进来
    （日志上限 5MB，手机端高频轮询时这个差别很大）。"""
    path = path or _CRAWL_LOG_FILE
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()                      # 丢掉可能被截断的首行
            data = f.read()
        return data.decode("utf-8", "replace").splitlines()[-n:], size
    except FileNotFoundError:
        return [], 0
    except Exception as e:
        return ["（日志读取失败：%s）" % e], 0

def _crawl_log_since(cursor, max_bytes=_CRAWL_LOG_READ_MAX, path=None):
    """自 cursor 字节位置起的新日志。返回 (lines, 新 cursor, size)。
    只回传**完整行**：末尾半行不计入新游标，留到下次读（避免把一行切成两半）。
    日志被轮转/截断（size < cursor）时自动从头重来。"""
    path = path or _CRAWL_LOG_FILE
    try:
        size = os.path.getsize(path)
    except OSError:
        return [], 0, 0
    if cursor < 0 or cursor > size:
        cursor = 0
    try:
        with open(path, "rb") as f:
            f.seek(cursor)
            data = f.read(max_bytes)
    except OSError as e:
        return ["（日志读取失败：%s）" % e], cursor, size
    cut = data.rfind(b"\n")
    if cut < 0:
        return [], cursor, size                   # 一行都没写完：游标不动
    complete = data[:cut + 1]
    return (complete.decode("utf-8", "replace").splitlines(),
            cursor + len(complete), size)

def _crawl_state_counts(kind=None):
    """断点进度计数：wnacg 用 crawl_state.json，jmdl 用独立的 crawl_state_jmdl.json，
    nhdl 用 crawl_state_nhdl.json，jm/nh 索引用 *_ids.json（3.6.9 起的轻量计数 state，
    每轮全量重跑），五个任务互不污染。"""
    if kind == "jm":
        path = os.path.join(STATE_DIR, "crawl_state_jm_ids.json")
    elif kind == "nh":
        path = os.path.join(STATE_DIR, "crawl_state_nh_ids.json")
    else:
        path = _crawl_state_file(kind)
    try:
        with open(path, "r", encoding="utf-8") as f:
            st = json.load(f)
        return len(st.get("done", {})), len(st.get("failed", {}))
    except Exception:
        return 0, 0

def _crawl_list_count(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return sum(1 for ln in f if ln.strip() and not ln.lstrip().startswith("#"))
    except Exception:
        return 0

def _crawl_write_list(path, entries):
    text = "\n".join(str(x).strip() for x in entries if str(x).strip())
    # 临时文件必须落在目标同目录：os.replace 跨盘符（设备）会直接失败
    fd, tmp = tempfile.mkstemp(prefix="crawl_list_", dir=os.path.dirname(path) or APP_DIR)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(text + ("\n" if text else ""))
    os.replace(tmp, path)

def _crawl_task_snapshot(kind):
    """单个任务的对外状态快照（3.6.7：多任务独立后的 status 基本单元）。"""
    proc = _crawl_proc(kind)
    running = proc is not None
    t = _CRAWL_TASKS[kind]
    done, failed = _crawl_state_counts(kind)
    if kind == "jmdl":
        total = _crawl_list_count(_CRAWL_LIST_JMDL_T) + _crawl_list_count(_CRAWL_LIST_JMDL_I)
    elif kind == "jm":
        total = _crawl_list_count(_CRAWL_LIST_JM)
    elif kind == "nh":
        total = _crawl_list_count(_CRAWL_LIST_NH)
    elif kind == "nhdl":
        total = _crawl_list_count(_CRAWL_LIST_NHDL)
    elif kind == "eh":
        total = _crawl_list_count(_CRAWL_LIST_EH)
    else:
        total = _crawl_list_count(_CRAWL_LIST_WNACG)
    return {"kind": kind, "running": running,
            "pid": proc.pid if running else None,
            "startedAt": t.get("startedAt") if running else None,
            "total": total, "done": done, "failed": failed,
            # 3.6.38 #35：本次任务的日志起点游标（仅运行中有值；None=不展示日志）
            "logCursor": t.get("log_cursor") if running else None}


def crawl_log_cursor(kind):
    """本次任务的日志起点游标（3.7.58：不再要求子进程在跑）。

    任务改为本进程线程执行后 `_crawl_proc()` 永远是 None，若还拿它当判据，
    日志区会永远空白——"启动后什么都没看到"。现在只认启动时记下的游标；
    下次启动会覆盖成新的起点。"""
    t = _CRAWL_TASKS.get(kind)
    return t.get("log_cursor") if t is not None else None


def crawl_mark_log_start(kind, path):
    """任务启动时记录日志文件当前位置作为本次运行起点（3.6.38 #35）。
    调用必须在 Popen 之前/同时：先落一个"启动标记"再让脚本自己写。"""
    try:
        size = os.path.getsize(path) if os.path.exists(path) else 0
    except OSError:
        size = 0
    if kind in _CRAWL_TASKS:
        _CRAWL_TASKS[kind]["log_cursor"] = size
    return size


def crawl_clear_log_cursor(kind):
    """任务停止/退出时清掉本次起点（日志区随之停止展示）。"""
    if kind in _CRAWL_TASKS:
        _CRAWL_TASKS[kind]["log_cursor"] = None
