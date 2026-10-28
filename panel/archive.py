# -*- coding: utf-8 -*-
"""压缩包读取 + 页面字节缓存 + 视频页临时文件 —— 3.7 结构重构：从 app.py 抽出。

  * 句柄复用：每请求一页不再重开压缩包；LRU 容量有限，逐出仅移除引用（活跃
    读取线程仍持有引用，底层文件对象引用计数归零后自动关闭，避免读到一半被关）
  * zipfile/rarfile 句柄非线程安全 → 每路径一把锁串行化 read
  * 页面字节 LRU：已解压图片页驻留内存（键含 mtime_ns，源变动自动失效）；
    webm 页不入内存缓存（已落盘 %TEMP%/djc_video_cache，支持 Range）

状态均为**原地可变容器**（OrderedDict / dict / list / Lock），app.py 以同对象再导出，
测试清空 `app._page_cache` / 改 `app.PAGE_CACHE_MAX_BYTES` 仍生效——但
`PAGE_CACHE_MAX_BYTES` 是**可重绑定常量**，打桩须打到本模块（见 test_page_cover 注释）。
"""
import hashlib
import os
import shutil
import tempfile
import threading
import time
import zipfile
from collections import OrderedDict

from panel.deps import RAR_AVAILABLE, rarfile
from panel.paths import mime_for

ARCHIVE_OPEN_MAX = 8
PAGE_CACHE_MAX_ITEMS = 600
PAGE_CACHE_MAX_BYTES = 256 * 1024 * 1024
_archive_handles = OrderedDict()            # abspath -> (zf, mtime_ns)
_page_cache = OrderedDict()                 # (abspath, mtime_ns, name) -> (bytes, mime)
_page_cache_bytes = [0]
_archive_lock = threading.Lock()
_page_cache_lock = threading.Lock()
_path_locks = {}                            # abspath -> threading.Lock

# 阅读页读取：压缩包内 webm 视频页落系统临时目录（支持 Range，可拖进度条）
VIDEO_TMP_DIR = os.path.join(tempfile.gettempdir(), "djc_video_cache")
VIDEO_TMP_MAX = 512 * 1024 * 1024


def _path_lock(abspath):
    with _archive_lock:
        return _path_locks.setdefault(abspath, threading.Lock())


def _archive_handle(abspath, m_ns):
    """取（或打开）压缩包句柄。须在 _path_lock(abspath) 内调用。"""
    with _archive_lock:
        ent = _archive_handles.get(abspath)
        if ent is not None and ent[1] == m_ns:
            _archive_handles.move_to_end(abspath)
            return ent[0]
        if ent is not None:
            _archive_handles.pop(abspath, None)     # 源已变动：弃用旧句柄（不主动 close，见上）
        if os.path.splitext(abspath)[1].lower() in (".rar", ".cbr") and RAR_AVAILABLE:
            zf = rarfile.RarFile(abspath)
        else:
            zf = zipfile.ZipFile(abspath)
        _archive_handles[abspath] = (zf, m_ns)
        while len(_archive_handles) > ARCHIVE_OPEN_MAX:
            _archive_handles.popitem(last=False)    # 仅弃引用，GC 自动回收
        return zf


def _archive_forget(path):
    """关闭并驱逐某文件的缓存压缩包句柄。
    开着的句柄在 Windows 上会阻止该文件被重命名/删除（WinError 32），
    所有文件管理操作（改名/归档/删除）前必须先调用。"""
    abspath = os.path.abspath(path)
    with _archive_lock:
        ent = _archive_handles.pop(abspath, None)
    if ent is not None:
        try:
            ent[0].close()
        except Exception:
            pass


def _archive_forget_tree(dir_path):
    """关闭目录树内所有缓存压缩包句柄（路径 = 目录本身或其子项）。
    Windows 上开着的句柄会阻止整目录直接删除（WinError 32），
    解散社团清目录前必须先撒手。"""
    prefix = os.path.abspath(dir_path).lower().rstrip("\\/") + os.sep
    with _archive_lock:
        ents = [_archive_handles.pop(k) for k in [k for k in _archive_handles
                                                  if k.lower().startswith(prefix)]]
    for ent in ents:
        try:
            ent[0].close()
        except Exception:
            pass


def _archive_quiesce(paths, timeout=5.0):
    """文件管理操作前的彻底撒手：关闭缓存句柄 + 等待在读线程排空。
    _archive_forget 只关缓存句柄，正在读取中的线程（手机翻页/封面生成）仍握着
    文件对象引用，os.rename 立刻撞 WinError 32——这里按路径锁轮询等它读完，
    超时则放弃等待（由调用方的重试兜底）。"""
    locks = []
    for p in set(os.path.abspath(x) for x in paths):
        _archive_forget(p)
        locks.append(_path_lock(p))
    deadline = time.time() + timeout
    pending = list(locks)
    while pending and time.time() < deadline:
        still = []
        for lk in pending:
            if lk.acquire(blocking=False):
                lk.release()
            else:
                still.append(lk)
        pending = still
        if pending:
            time.sleep(0.05)


def _rename_with_retry(src, dst, tries=3):
    """os.rename 带共享冲突重试：WinError 32/33（被占用）时撒手重试，
    覆盖杀软/索引器扫描、迟到的读取释放等瞬态占用。"""
    last = ""
    for i in range(tries):
        try:
            os.rename(src, dst)
            return True, ""
        except OSError as e:
            last = str(e)
            if getattr(e, "winerror", None) in (32, 33) and i < tries - 1:
                _archive_forget(src)
                time.sleep(0.3 * (i + 1))
                continue
            return False, last
    return False, last


def _move_with_retry(src, dst, tries=3):
    """shutil.move 带共享冲突重试（WinError 32/33：在读线程/杀软/索引器瞬态占用）。
    每次重试前撒手缓存句柄。失败返回 (False, 原因)。"""
    last = ""
    for i in range(tries):
        try:
            shutil.move(src, dst)
            return True, ""
        except OSError as e:
            last = str(e)
            if getattr(e, "winerror", None) in (32, 33) and i < tries - 1:
                _archive_forget(src)
                time.sleep(0.3 * (i + 1))
                continue
            return False, last
        except Exception as e:
            return False, str(e)
    return False, last


def _path_size(p):
    """文件/目录占用字节数（目录递归求和，用于重复作品比对）。"""
    try:
        if os.path.isfile(p):
            return os.path.getsize(p)
        total = 0
        for dp, _dn, fns in os.walk(p):
            for fn in fns:
                try:
                    total += os.path.getsize(os.path.join(dp, fn))
                except OSError:
                    pass
        return total
    except OSError:
        return -1


def _archive_read(abspath, name):
    """读压缩包内一个文件的字节（句柄复用 + 路径锁串行化）。失败返回 None。"""
    try:
        m_ns = os.stat(abspath).st_mtime_ns
    except OSError:
        return None
    lock = _path_lock(abspath)
    with lock:
        try:
            zf = _archive_handle(abspath, m_ns)
            return zf.read(name)
        except Exception:
            try:                                    # 句柄可能损坏：强制重开一次
                with _archive_lock:
                    _archive_handles.pop(abspath, None)
                zf = _archive_handle(abspath, m_ns)
                return zf.read(name)
            except Exception:
                return None


def _page_cache_get(key):
    with _page_cache_lock:
        hit = _page_cache.get(key)
        if hit is not None:
            _page_cache.move_to_end(key)
        return hit


def _page_cache_put(key, val):
    with _page_cache_lock:
        if key in _page_cache:
            _page_cache_bytes[0] -= len(_page_cache.pop(key)[0])
        _page_cache[key] = val
        _page_cache_bytes[0] += len(val[0])
        while _page_cache and (len(_page_cache) > PAGE_CACHE_MAX_ITEMS
                               or _page_cache_bytes[0] > PAGE_CACHE_MAX_BYTES):
            _k, v = _page_cache.popitem(last=False)
            _page_cache_bytes[0] -= len(v[0])


def purge_video_tmp():
    """清理超过 24 小时的视频页临时缓存文件。"""
    try:
        now = time.time()
        for n in os.listdir(VIDEO_TMP_DIR):
            p = os.path.join(VIDEO_TMP_DIR, n)
            try:
                if now - os.path.getmtime(p) > 86400:
                    os.unlink(p)
            except OSError:
                continue
    except OSError:
        pass


def _video_tmp_file(key, data, ext=".webm"):
    """把压缩包内媒体页（webm 视频/音频轨）写入临时缓存文件（返回路径），
    供 send_file 支持 Range/拖进度条。缓存总量超上限时按最旧优先清理（跳过正在写入的 .part）。"""
    try:
        os.makedirs(VIDEO_TMP_DIR, exist_ok=True)
        entries, total = [], 0
        for n in os.listdir(VIDEO_TMP_DIR):
            if n.endswith(".part"):
                continue
            p = os.path.join(VIDEO_TMP_DIR, n)
            try:
                st = os.stat(p)
                entries.append((st.st_mtime, st.st_size, n))
                total += st.st_size
            except OSError:
                continue
        for _mt, sz, n in sorted(entries):
            if total + len(data) <= VIDEO_TMP_MAX:
                break
            try:
                os.unlink(os.path.join(VIDEO_TMP_DIR, n))
                total -= sz
            except OSError:
                pass
        path = os.path.join(VIDEO_TMP_DIR,
                            hashlib.sha1(key.encode("utf-8")).hexdigest() + ext)
        if not os.path.exists(path):
            fd, tmp = tempfile.mkstemp(dir=VIDEO_TMP_DIR, suffix=".part")
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        return path
    except OSError:
        return None


def page_source(work, n):
    """作品第 n 页（0 起）。返回 (kind, payload, mime)：
      kind="file"  → payload 为磁盘路径（send_file 支持 Range，视频可拖进度条）
      kind="bytes" → payload 为字节
    页面描述统一路由（P2-7）：{"p":...} 散图直读磁盘；{"z"/"r":...} 从压缩包读
    （文件夹作品的嵌套压缩包页自此可读）。失败返回 (None, None, None)。"""
    pages = work.get("page_files") or []
    if n < 0 or n >= len(pages):
        return None, None, None
    pg = pages[n]
    if "p" in pg:                                   # 散图（文件夹作品）
        return "file", pg["p"], mime_for(pg["p"])
    name = pg["n"]
    mime = mime_for(name)
    abspath = os.path.abspath(pg.get("z") or pg.get("r") or "")
    if not abspath:
        return None, None, None
    key = _page_cache_key(abspath, name, mime)
    if key is not None:
        hit = _page_cache_get(key)
        if hit is not None:
            return "bytes", hit[0], hit[1]
    data = _archive_read(abspath, name)
    if not data:
        return None, None, None
    if mime == "video/webm":
        p = _video_tmp_file(abspath + "|" + name, data)
        if p:
            return "file", p, mime
    if key is not None:
        _page_cache_put(key, (data, mime))
    return "bytes", data, mime


def _page_cache_key(abspath, name, mime):
    """页缓存键 = (包路径, mtime_ns, 页名)。webm 不缓存（体积大且要 Range），
    取不到 mtime 也不缓存——宁可多读一次，也不用可能过期的键。"""
    if mime == "video/webm":
        return None
    try:
        return (abspath, os.stat(abspath).st_mtime_ns, name)
    except OSError:
        return None
