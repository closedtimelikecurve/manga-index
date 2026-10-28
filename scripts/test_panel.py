#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""AI 实测专用：一键起/停「测试模式」面板实例（工程纪律 §4.8b 的配套工具）。

测试模式 = app.py `--safe-images`（3.6.118）：/cover /page /api/crawl/probe/cover
三个端点对任意参数一律回 static/img/placeholder.png——浏览器截图只含占位图，
不暴露文库内容，不会触发多模态审查截断会话。

用法（agent 与人通用）：
    python scripts/test_panel.py start    # 起 127.0.0.1:8767（已跑则直接复用并自检）
    python scripts/test_panel.py status   # 看在不在跑 / 版本 / 占位图探针
    python scripts/test_panel.py stop     # 测完即停（纪律要求，不留常驻）
    python scripts/test_panel.py restart

启动参数固定 --host 127.0.0.1 --no-browser --safe-images，端口固定 8767
（--port 只覆写本进程内存，不落 config.json，见 server.py _apply_cli）。
回环访问免 token（app.py _token_gate），内部浏览器直接开 http://127.0.0.1:8767/ 即可。

本脚本起停只依赖 stdlib；探针「封面字节 == 占位图字节」是测试模式是否生效的
唯一机器判据，不靠自觉。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = APP_DIR / "_state"
PID_FILE = STATE_DIR / "test_panel.pid"
LOG_FILE = STATE_DIR / "test_panel.log"
PLACEHOLDER = APP_DIR / "static" / "img" / "placeholder.png"
PORT = 8767
BASE = "http://127.0.0.1:%d" % PORT


def _get(path, timeout=3):
    """GET 一下返回 bytes；连不上/非 200 返回 None。"""
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


def _version():
    """/api/config 的 panelVersion；不在跑返回 None。"""
    raw = _get("/api/config")
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8")).get("panelVersion")
    except Exception:
        return None


def _safe_verified():
    """占位图探针：任意参数 /cover 必须逐字节等于 placeholder.png。
    完整模式下该请求 404（作品不存在），因此探针通过 = 测试模式确实生效。"""
    body = _get("/cover?group=__safe_probe__&work=__safe_probe__")
    return bool(body) and body == PLACEHOLDER.read_bytes()


def _pid_on_port():
    """端口被谁占着（Windows 走 netstat -ano；POSIX 无依赖实现省略，够用即可）。"""
    if os.name != "nt":
        return None
    # 中文 Windows 的 netstat/tasklist 输出是 GBK，encoding+errors 防解码炸线程
    out = subprocess.run(["netstat", "-ano"], capture_output=True,
                         encoding="utf-8", errors="replace").stdout or ""
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(":%d" % PORT) and parts[3] == "LISTENING":
            return int(parts[4])
    return None


def _pid_alive(pid):
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid],
                             capture_output=True, encoding="utf-8", errors="replace").stdout or ""
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _spawn():
    """拉起分离进程：脱离本脚本生命周期，stdout/stderr 全量落 _state/test_panel.log。"""
    STATE_DIR.mkdir(exist_ok=True)
    cmd = [sys.executable, str(APP_DIR / "app.py"),
           "--host", "127.0.0.1", "--port", str(PORT),
           "--no-browser", "--safe-images"]
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    with open(LOG_FILE, "ab") as logf:
        proc = subprocess.Popen(cmd, cwd=str(APP_DIR), stdin=subprocess.DEVNULL,
                                stdout=logf, stderr=subprocess.STDOUT,
                                creationflags=flags)
    PID_FILE.write_text(str(proc.pid), encoding="ascii")


def cmd_start():
    ver = _version()
    if ver:
        if _safe_verified():
            print("已在跑：http://127.0.0.1:%d/  v%s（占位图探针通过，直接复用）" % (PORT, ver))
            return 0
        print("8767 上已有一个面板但**不是测试模式**（占位图探针不通过），拒绝在其上实测。")
        print("先 `python scripts/test_panel.py stop` 或人工确认该实例来路。")
        return 1
    print("启动测试模式实例（--safe-images 占位图）……")
    _spawn()
    for _ in range(60):                       # 最多 ~24s 等面板就绪
        ver = _version()
        if ver:
            break
        time.sleep(0.4)
    if not ver or not _safe_verified():
        print("启动失败或探针不通过，日志尾部：")
        if LOG_FILE.exists():
            print("\n".join(LOG_FILE.read_text(errors="replace").splitlines()[-15:]))
        cmd_stop_quiet()
        return 1
    print("就绪：http://127.0.0.1:%d/  v%s  SAFE-IMAGES=已验证（/cover 全占位图）" % (PORT, ver))
    print("内部浏览器打开上面地址即可实测；测完执行 `python scripts/test_panel.py stop`。")
    return 0


def cmd_stop_quiet():
    """内部兜底：探针失败/启动失败时回收本脚本拉起的进程，不与用户对话。"""
    _kill_by_pidfile() or _kill_by_port()
    for _ in range(20):
        if not _version():
            break
        time.sleep(0.4)
    if PID_FILE.exists():
        PID_FILE.unlink()


def cmd_stop():
    ver = _version()
    if not ver:
        if PID_FILE.exists():
            PID_FILE.unlink()
        print("8767 无实例在跑。")
        return 0
    if not _safe_verified():
        print("8767 上是 v%s 但占位图探针不通过（完整模式？），拒绝盲停，请人工确认。" % ver)
        return 1
    if not (_kill_by_pidfile() or _kill_by_port()):
        print("找不到进程 PID，请手工处理（netstat -ano | findstr :%d）。" % PORT)
        return 1
    for _ in range(25):
        if not _version():
            break
        time.sleep(0.4)
    if PID_FILE.exists():
        PID_FILE.unlink()
    print("已停止（8767 测试实例）。")
    return 0


def _kill_by_pidfile():
    """只认「pidfile 里的 PID 且正占着 8767」——PID 复用/陈旧 pidfile 都不误杀。"""
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text(encoding="ascii").strip() or 0)
    except ValueError:
        return False
    if pid and pid == _pid_on_port():
        return _kill(pid)
    return False


def _kill_by_port():
    pid = _pid_on_port()
    return _kill(pid) if pid else False


def _kill(pid):
    if os.name == "nt":
        r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return r.returncode == 0
    try:
        os.kill(pid, 15)
        return True
    except OSError:
        return False


def cmd_status():
    ver = _version()
    if not ver:
        print("8767 无实例。")
        return 1
    print("http://127.0.0.1:%d/  v%s  SAFE-IMAGES=%s"
          % (PORT, ver, "已验证" if _safe_verified() else "未通过（勿实测）"))
    return 0


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, OSError, AttributeError) as e:
        print("警告：stdout 切 UTF-8 失败（%s），中文输出可能乱码" % e, file=sys.stderr)
    acts = {"start": cmd_start, "stop": cmd_stop, "status": cmd_status,
            "restart": lambda: (cmd_stop(), cmd_start())[1]}
    fn = acts.get(argv[1] if len(argv) > 1 else "")
    if not fn:
        print(__doc__)
        return 2
    return fn()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
