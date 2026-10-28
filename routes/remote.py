# -*- coding: utf-8 -*-
"""routes/remote.py —— 远程服务（8766）启停（3.6.151）。

## 为什么要这个端点

用户希望不必每次都跑回电脑点启动器，直接在**网页端的二维码配对页**里关掉/打开
电脑那边跑着的远程服务。

## 入口只有一个：网页端（APP 端不放）

3.6.151 一开始把这个开关做进了 APP 的扫码页，被用户否掉并要求移除——理由是第 2 条
事实：关掉之后就再也没法在手机上打开它，放在手机上等于只能"关"不能"开"。
现在开关只在 `static/index.html#pairModal`（二维码页）里，APP 侧不提供。

## 两个必须讲清楚的事实

1. **停止是"先回包、后动手"**：本进程可能就是远程服务本身（8766）。在请求线程里直接
   杀掉自己会让响应发不出去，客户端只看到连接被重置、误以为失败。所以先返回 200，
   再延迟 1.5 秒起一个脱离的子进程去 `launcher_proc.stop_remote()`。

2. **"在远程页面上关掉、再在远程页面上打开"物理上不可能**：远程服务停了，8766 不再监听，
   手机没有任何通路能到达它（HTTPS 的 443 也只是 `tailscale serve` 转发到 8766）。
   所以 `start` 实际只能在**本机实例 8765** 上调通，且本页若正是远程实例
   （`isSelf`），停止 = 当场断开本页——前端必须把这两点写在按钮下面。

## 实现

起子进程跑 `launcher_proc`（与启动器同一个入口，避免出现第二套启停逻辑）。
用 `Popen` 且**不 wait**——`subprocess.run` 会等结果，把响应拖住。
"""
import socket
import subprocess
import sys
import threading

from flask import jsonify

import common
from routes.host import h

REMOTE_PORT = 8766
STOP_DELAY = 1.5          # 秒：先把响应发出去，再动手杀进程


def _self_port():
    """本进程绑的端口（显式 --port 记在 CFG_PORT_BIND；否则读 config.port）。"""
    try:
        return int(h().CFG_PORT_BIND or common.CFG.get("port") or 0)
    except (TypeError, ValueError):
        return 0


def _listening(port, host="127.0.0.1"):
    try:
        with socket.create_connection((host, int(port)), timeout=0.4):
            return True
    except (OSError, ValueError):
        return False


def _spawn_detached(code):
    """起一个脱离本进程的 Python 子进程执行启动器逻辑（不等结果、不继承窗口）。"""
    flags = 0x08000000 if sys.platform == "win32" else 0    # CREATE_NO_WINDOW
    try:
        subprocess.Popen([sys.executable, "-c", code], cwd=common.APP_DIR,
                         creationflags=flags, close_fds=True,
                         stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def api_remote_state():
    """远程服务状态：有没有在监听、当前进程是不是它自己。"""
    return jsonify({
        "ok": True,
        "port": REMOTE_PORT,
        "running": _listening(REMOTE_PORT),
        "selfPort": _self_port(),
        # 本进程就是远程实例时，停止等于自杀——前端据此给更强的确认
        "isSelf": _self_port() == REMOTE_PORT,
    })


def api_remote_stop():
    """停止远程服务（延迟执行，先让本次响应发出去）。"""
    if not _listening(REMOTE_PORT):
        return jsonify({"ok": True, "code": "already_stopped",
                        "message": "远程服务本来就没在运行"})
    threading.Timer(STOP_DELAY, lambda: _spawn_detached(
        "import launcher_proc as lp; lp.stop_remote()")).start()
    return jsonify({"ok": True, "code": "stopping", "delay": int(STOP_DELAY),
                    "message": "远程服务将在 %d 秒后停止" % int(STOP_DELAY)})


def api_remote_start():
    """启动远程服务。**只能在 8765（本机实例）调通**——8766 停着时手机到不了这里。"""
    if _self_port() == REMOTE_PORT:
        return jsonify({"ok": False, "code": "self",
                        "message": "当前就是远程服务进程，无法自启动；请在电脑的面板页操作"}), 400
    if _listening(REMOTE_PORT):
        return jsonify({"ok": True, "code": "already_running",
                        "message": "远程服务已在运行"})
    ok = _spawn_detached(
        "import launcher_proc as lp; lp._spawn('remote', %d, "
        "['--host','0.0.0.0','--port','%d','--no-browser'])" % (REMOTE_PORT, REMOTE_PORT))
    if not ok:
        return jsonify({"ok": False, "code": "spawn_failed",
                        "message": "启动失败（无法创建子进程）"}), 500
    return jsonify({"ok": True, "code": "starting",
                    "message": "远程服务正在启动，几秒后可用"})


ROUTES = [
    ('get', '/api/remote/state', api_remote_state, False),
    ('post', '/api/remote/stop', api_remote_stop, False),
    ('post', '/api/remote/start', api_remote_start, False),
]


def register(app):
    for method, rule, fn, is_mut in ROUTES:
        if is_mut:
            fn = h().mutating(fn)
        getattr(app, method)(rule)(fn)
