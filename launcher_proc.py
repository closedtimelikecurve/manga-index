# -*- coding: utf-8 -*-
"""launcher_proc.py —— 服务进程的探测、启停与重启（3.6.84 从 index_launcher.py 拆出）。

只做"机器侧"的事，不碰 tkinter：netstat 解析、端口探测、Popen 拉起、taskkill、
Tailscale 状态。UI 通过 `core.ui()` 把结果送回主线程渲染。

两条硬约束（都是踩过坑写下来的）：
  * 本地端口固定 8765、远程固定 8766，**必须显式 --port**，否则 app.py 读 config 的
    漂移端口会撞上另一进程的监听地址；
  * 重启走 /api/panel/restart（带代码自检），且重启后 PID 已变，旧句柄必须作废。
"""
import json
import os
import re
import socket
import subprocess
import time
import traceback
import urllib.request
import webbrowser

import launcher_core as core


def run_cmd(args, timeout=10):
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout,
                           creationflags=core.CREATE_NO_WINDOW)
        out = (r.stdout or b"") + (r.stderr or b"")
        return r.returncode, out.decode("utf-8", errors="replace").strip()
    except Exception as e:
        return None, str(e)


def run_ts(args, timeout=15):
    if not core.TS_EXE:
        return None, "Tailscale 未安装（请先 winget install Tailscale.Tailscale）"
    return run_cmd([core.TS_EXE] + args, timeout=timeout)


def ts_state():
    """Tailscale 后端状态。返回 (state, ip, msg)。
    state: running / needs-login / stopped / missing / unknown
    ip: IPv4 或 ""。"""
    if not core.TS_EXE:
        return "missing", "", "Tailscale 未安装"
    code, out = run_ts(["status", "--json"], timeout=12)
    j, err = _ts_payload(code, out)
    if err:
        return err
    return _ts_verdict(j, out)


def _ts_payload(code, out):
    """tailscale status --json 的输出 → (dict, 错误三元组|None)。"""
    if code is None:
        return None, ("unknown", "", out or "tailscale 命令异常")
    if code != 0:
        return None, ("unknown", "", (out or "tailscale 不可用").splitlines()[0][:80])
    try:
        return json.loads(out), None
    except Exception:
        return None, ("unknown", "", "tailscale 输出解析失败")


def _ts_verdict(j, out):
    """BackendState → 面板用的三态。"""
    bs = str(j.get("BackendState", "")).lower()
    ip = _first_ipv4(j.get("Self") or {})
    if bs == "running":
        return "running", ip, ("Tailscale 已连接" if ip else "Tailscale 运行中（无 IPv4）")
    if bs in ("needslogin", "loggedout", "logged out", "stopped"):
        return "needs-login", "", "需要登录 Tailscale"
    return bs or "unknown", "", "状态：" + (bs or (out or "")[:60])


def _first_ipv4(self_):
    """Self.TailscaleIPs 里第一个不含 ':' 的地址（IPv4）；没有返回 ''。"""
    for x in (self_.get("TailscaleIPs") or []):
        if ":" not in str(x):
            return str(x)
    return ""


def open_ts_login():
    """尽量把登录页开给用户。"""
    # tailscale up 在未登录时会打印登录 URL（或启动 GUI 登录）
    try:
        _code, out = run_ts(["up", "--accept-dns=false"], timeout=15)
        m = re.search(r"https?://[^\s'\"]+", out or "")
        if m:
            webbrowser.open(m.group(0))
            return True
    except Exception:
        pass
    try:
        webbrowser.open("https://login.tailscale.com/")
        return True
    except Exception:
        return False


def _port_now(port=None):
    """端口即时解析：显式传入 > config.json（每次重读，P2-4 端口漂移不误判）。"""
    return port if port is not None else core.load_port()


def _netstat_local_addr(ln):
    """取 netstat 行的"本地地址"列（第 2 列）。非 TCP LISTENING 行返回 None。"""
    parts = ln.split()
    if len(parts) >= 4 and parts[0].upper() == "TCP" and "LISTENING" in parts[3].upper():
        return parts[1]
    return None


def listening_pids(port=None):
    port = _port_now(port)
    code, out = run_cmd(["netstat", "-ano"], timeout=15)
    pids = set()
    if code == 0:
        tag = ":%d" % port
        for ln in out.splitlines():
            local = _netstat_local_addr(ln)
            # 只认本地地址列（整行匹配会把外部地址 0.0.0.0:0 误算进来）
            if local and local.lower().endswith(tag):
                pids.add(ln.split()[-1])
    return pids


def server_listen_state(port=None):
    port = _port_now(port)
    code, out = run_cmd(["netstat", "-ano"], timeout=15)
    if code != 0:
        return None
    tag = ":%d" % port
    state = None
    for ln in out.splitlines():
        local = _netstat_local_addr(ln)
        if not local or not local.lower().endswith(tag):
            continue
        if local.startswith("0.0.0.0") or local.startswith("[::]"):
            return "remote"
        if local.startswith("127.0.0.1"):
            state = "local"
    return state


def port_open(port=None, host="127.0.0.1", timeout=0.4):
    port = _port_now(port)
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _stop_proc(key, port):
    """停掉一个服务进程：terminate 自己启动的句柄 + taskkill 该端口上的残留监听者。"""
    killed = False
    p = core.PROC[key]
    if p is not None and p.poll() is None:
        try:
            p.terminate()
            try:
                p.wait(timeout=3)
            except Exception:
                p.kill()
            killed = True
        except Exception:
            pass
    core.PROC[key] = None
    try:
        for pid in listening_pids(port=port):
            run_cmd(["taskkill", "/F", "/PID", pid], timeout=8)
            killed = True
    except Exception:
        pass
    for _ in range(10):
        if not port_open(port=port):
            break
        time.sleep(0.3)
    return killed


def stop_local():
    """只停本地服务（127.0.0.1:PORT）——不碰远程进程。"""
    return _stop_proc("local", core.PORT)


def stop_remote():
    """只停远程服务（0.0.0.0:REMOTE_PORT）——不碰本地进程。"""
    return _stop_proc("remote", core.REMOTE_PORT)


def _pids_from_cmd(args, timeout):
    """跑一条枚举命令 → (pid 集合, 命令是否成功)。失败/超时 → 空集 + False。"""
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {int(ln.strip()) for ln in (out.stdout or "").splitlines()
                if ln.strip().isdigit()}, True
    except Exception:
        return set(), False


def _scan_stray_pids():
    """枚举命令行带 app.py 的 python 进程：wmic 优先，Win11 精简版退回 PowerShell。

    两路都**跑不通**才记日志——"没有残留进程"和"查不到"必须分开：
    后者会让「停止服务」漏掉孤儿进程，用户只看到"服务未在运行"，却查不到原因。"""
    pids, ok = _pids_from_cmd(
        ["wmic", "process", "where",
         "name like 'py%' and commandline like '%app.py%'",
         "get", "processid"], 12)
    if pids or ok:
        return pids
    pids, ok = _pids_from_cmd(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'py*' "
         "-and $_.CommandLine -like '*app.py*' } | "
         "Select-Object -ExpandProperty ProcessId"], 20)
    if not ok:
        core.log_error("清扫残留进程失败：wmic 与 PowerShell 均不可用，"
                       "「停止服务」可能漏掉命令行带 app.py 的孤儿进程")
    return pids


def _kill_stray_panel_procs():
    """兜底清扫：结束所有命令行带 app.py 的 python/pythonw 进程——
    覆盖崩溃残留、面板自重启（os.execv）竞态孤儿等"不在端口监听表上"的漏网之鱼，
    保证「停止服务」卡无论何时都能把面板进程一网打尽。返回是否杀到东西。"""
    killed = False
    for pid in sorted(_scan_stray_pids()):
        try:
            run_cmd(["taskkill", "/F", "/PID", str(pid)], timeout=8)
            killed = True
        except Exception:
            pass
    return killed


def stop_service():
    """「停止服务」卡：两个进程全部结束——本地 + 远程**逐一执行不短路**，
    再按命令行兜底清扫 app.py 进程（修复"有时只能结束一个"的 or 短路 bug）。"""
    r1 = stop_local()
    r2 = stop_remote()
    stray = _kill_stray_panel_procs()
    return r1 or r2 or stray


def wait_port_ready(port, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(port=port):
            return True
        time.sleep(0.2)
    return False


def _spawn(key, port, args):
    """以指定端口启动一个独立服务进程；就绪后核验监听者确实是本进程。"""
    core.log_error("spawn[%s]: begin args=%s port=%s" % (key, args, port))
    if not core.PY:
        return False, "未检测到系统 Python（请安装 Python 3 并勾选 PATH）"
    if not os.path.exists(os.path.join(core.APP_DIR, "app.py")):
        return False, "找不到 app.py（需与 Index.exe 同目录）"
    _stop_proc(key, port)                    # 只清自己的端口，不碰另一进程
    try:
        core.PROC[key] = subprocess.Popen(
            [core.PY, os.path.join(core.APP_DIR, "app.py")] + args,
            cwd=core.APP_DIR, creationflags=core.CREATE_NO_WINDOW)
    except Exception as e:
        core.log_error("启动失败: %s\n%s" % (e, traceback.format_exc()))
        return False, "启动失败：" + str(e)
    if not wait_port_ready(port):
        return _spawn_failed(key, port)
    pids = listening_pids(port=port)
    if pids and str(core.PROC[key].pid) not in pids:
        try:
            core.PROC[key].kill()
        except Exception:
            pass
        core.PROC[key] = None
        return False, "端口 %d 被其他程序占用（可能有残留旧服务，请用任务管理器清理后重试）" % port
    return True, ""


def _spawn_failed(key, port):
    """拉起后端口没就绪：分清「进程立即退出」与「活着但没监听」。"""
    p = core.PROC[key]
    if p is not None and p.poll() is not None:
        core.PROC[key] = None
        return False, "服务启动后立即退出（退出码 %s，请查看 _logs/Index_error.log）" % p.returncode
    # 超时但进程还活着：多半在别的端口起来了（读 config 漂移端口）或被占用挂住，
    # 必须杀掉，否则留下孤儿进程持续监听、污染状态探测
    if p is not None:
        try:
            p.kill()
        except Exception:
            pass
        core.PROC[key] = None
    return False, ("服务启动超时（30 秒内端口 %d 未就绪）——"
                   "请检查 config.json 的 port 是否被端口冲突自增污染，"
                   "并在任务管理器确认无残留 python 进程" % port)


def local_launch(args):
    """启动本地服务进程（完整/仅导入模式）——不碰远程进程。
    本地端口固定让位：8766 是远程服务专用端口；config 里的本地端口若漂移到
    远程端口上（曾被端口冲突自增波及），此处强制指回 8765。
    必须显式传 --port：与远程进程同语义，app.py 不再读 config 漂移端口、
    不会撞上 0.0.0.0:8766 的远程进程，也不会把漂移端口写回 config.json。"""
    port = core.local_port()
    args = ["--port", str(port)] + list(args or [])
    return _spawn("local", port, args)


def remote_launch():
    """远程模式：Tailscale 就绪 → 0.0.0.0 起服务 → 报告 ts_url。
    未登录时打开授权页并等待用户完成（最长 90 秒）。"""
    state, ip, msg = ts_state()
    core.log_error("remote_launch: ts_state=%s ip=%s" % (state, ip))
    if state == "missing":
        return False, msg
    if state == "needs-login":
        state, ip, opened = _await_ts_login(state, ip)
        if state != "running" or not ip:
            return False, "Tailscale 登录未完成（已打开登录页：" + ("是" if opened else "否") + "）"
    if state != "running" or not ip:
        return False, "Tailscale 不可用：" + msg
    core.ST["tail_ip"] = ip
    core.ST["ts_url"] = "http://%s:%d/" % (ip, core.REMOTE_PORT)
    # 远程模式强制鉴权：token 为空则自动生成并提示（P1-1）
    token, generated = core.ensure_remote_token()
    if generated:
        core.ui(lambda t=token: core.set_note("已自动生成访问令牌：" + t + "（手机首次访问需输入）"))
    # 只启动/重启远程进程（0.0.0.0:REMOTE_PORT），本地进程不受影响
    # （3.6.21 恢复"正式进程默认弹浏览器"后，远程实例必须显式 --no-browser：
    #   它服务的是手机链路，在电脑前无端弹一个窗口只会打扰；要看远程页可手动开地址）
    ok, msg2 = _spawn("remote", core.REMOTE_PORT,
                      ["--host", "0.0.0.0", "--port", str(core.REMOTE_PORT), "--no-browser"])
    if not ok:
        return False, msg2
    return True, "远程服务已就绪：" + core.ST["ts_url"]


def _await_ts_login(state, ip):
    """打开授权页并等 backend 变 Running（最长 90 秒）。返回 (state, ip, 是否已开登录页)。"""
    opened = open_ts_login()
    deadline = time.time() + 90
    waited = False
    while time.time() < deadline:
        state2, ip2, _ = ts_state()
        if state2 == "running" and ip2:
            return state2, ip2, opened
        if not waited:
            core.ui(lambda: core.set_note("请在浏览器完成 Tailscale 登录授权…"))
            waited = True
        time.sleep(3)
    return state, ip, opened


def remote_off():
    """只关闭远程服务进程（0.0.0.0:REMOTE_PORT）——本地服务并行运行、不受影响。"""
    killed = stop_remote()
    core.ST["tail_ip"] = ""
    core.ST["ts_url"] = ""
    return True, ("远程服务已关闭" if killed else "远程服务未在运行")


def http_restart(port):
    """调面板自身的 /api/panel/restart：比起 kill 再拉起，它带一层代码自检
    （新代码 import 不过会被拒绝），不会把服务重启成一个起不来的进程。返回 (ok, msg)。"""
    url = "http://127.0.0.1:%d/api/panel/restart" % port
    req = urllib.request.Request(url, data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json"})
    tkn = core.load_token()
    if tkn:
        req.add_header("X-Token", tkn)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except Exception as e:
        return False, "调用重启接口失败：" + str(e)
    try:
        msg = json.loads(raw).get("message") or "已调度重启"
    except Exception:
        msg = (raw or "")[:80] or "已调度重启"
    return True, msg


def restart_service():
    """「重启服务」卡：服务在跑 → 走 /api/panel/restart 并等它重新就绪；
    服务没在跑 → 直接按完整模式拉起（此时重启卡等价于「启动」）。

    注意：面板自重启在 Windows 上是「新起进程 + 旧进程退出」，PID 会变，
    所以重启后必须丢弃本地句柄，否则「停止服务」会对着一个已死的 PID 下手。"""
    core.PORT = core.local_port()
    target = _running_target()
    if target is None:
        return local_launch([])
    ok, msg = http_restart(target)
    if not ok:
        return False, msg
    deadline = time.time() + 15                       # 先等旧进程让出端口
    while time.time() < deadline and port_open(port=target):
        time.sleep(0.3)
    if not wait_port_ready(target, timeout=40):       # 再等新进程接管
        return False, "重启已调度，但端口 %d 迟迟未恢复就绪（请查看 _logs/Index_error.log）" % target
    core.PROC["local"] = None                         # PID 已变：旧句柄一律作废
    core.PROC["remote"] = None
    return True, "服务已重启（http://127.0.0.1:%d/）" % target


def _running_target():
    """当前在跑的服务端口：优先本地，其次远程；都没跑返回 None。"""
    if port_open(port=core.PORT):
        return core.PORT
    if port_open(port=core.REMOTE_PORT):
        return core.REMOTE_PORT
    return None
