# -*- coding: utf-8 -*-
"""services/panel_admin.py —— 面板自重启与"代码已更新"检测（3.6.56 Stage7 从 app.py 抽出）。

背景：Python 只在启动时加载代码，改完 app.py 不重启就不生效（曾两次导致"改了没生效"）。
本模块负责：比较磁盘 VERSION / 关键文件 mtime → 判断是否需要重启 → 重启前在子进程里
试 import 一遍新代码（语法错挡住）→ 就地重启。
"""
import os
import subprocess
import sys
import tempfile
import threading
import time

from common import APP_DIR
from panel.host import h

def _disk_panel_version():
    """磁盘上 VERSION 文件里的面板版本（与本进程 PANEL_VERSION 不同 → 代码已更新但未重启）。"""
    try:
        with open(os.path.join(h().APP_DIR, "VERSION"), "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return h().PANEL_VERSION

def _panel_needs_restart():
    """本进程代码是否落后于磁盘：比较本进程启动时刻与关键文件 mtime（容忍 1 秒）。"""
    try:
        newest = max(os.path.getmtime(os.path.join(h().APP_DIR, f)) for f in h()._WATCH_FILES)
    except OSError:
        return False
    return newest > h()._PROC_START + 1

def _validate_fresh_code(timeout=120):
    """子进程里 import 一遍 app，确认新代码至少能加载 —— 语法/顶层错误挡在重启之前，
    免得"一键重启"把面板重启成一个起不来的进程。输出写临时文件（不用管道，沙箱下更稳）。"""
    fd, out = tempfile.mkstemp(prefix="panel_check_", dir=h().APP_DIR)
    os.close(fd)
    try:
        with open(out, "w", encoding="utf-8") as fout:
            r = subprocess.run([sys.executable, "-c", "import app"], cwd=h().APP_DIR,
                               stdout=fout, stderr=subprocess.STDOUT, timeout=timeout,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode == 0:
            return True, ""
        with open(out, "r", encoding="utf-8", errors="replace") as f:
            tail = [ln for ln in f.read().strip().splitlines() if ln.strip()][-3:]
        return False, (" / ".join(tail) or ("退出码 %d" % r.returncode))
    except Exception as e:
        return False, str(e)
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass

def _exec_self():
    """就地重启：用新代码重新拉起自己。

    **注意（2026-09-23 实测更正）**：Windows 上 os.execv 并不是 POSIX 那种"原地替换进程映像"，
    而是**新起一个进程、旧进程退出** —— PID 会变（实测 8432 → 16844），新进程也不再挂在
    启动器 Index.exe 名下。启动器的「停止服务」不受影响：它是先 terminate 自己的句柄、
    再按端口找监听者 `taskkill`（见 launcher_proc.py::_stop_proc），所以按端口照样能停。"""
    for s in (sys.stdout, sys.stderr):
        try:
            s.flush()
        except Exception:
            pass
    os.execv(sys.executable, [sys.executable] + sys.argv)

def _schedule_exec(delay=0.8):
    """延迟重启：先把 HTTP 响应发完，再换代码（线程不阻塞响应）。"""
    def _run():
        time.sleep(delay)
        _exec_self()
    threading.Thread(target=_run, daemon=True).start()
