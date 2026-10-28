# -*- coding: utf-8 -*-
"""services/pair_target.py —— 配对二维码的「远程可达地址」探测（3.6.129）。

用户报障：二维码只吐本机回环（127.0.0.1），手机扫了等于连手机自己，永远连不上。
本模块只回答一个问题：**这台机器现在有没有手机真正能到达的地址；有就配二维码，没有就不配。**

判定顺序（先到先用，全部只读、不启动任何进程、不改配置）：

1. `config.json` 的 `pair_url`——用户自己写死的地址，最高优先（内网穿透的域名只能这么给）；
2. 当前页面用的 host 本身不是回环——说明用户就是从远程地址打开的面板；
3. 检测到远程访问/内网穿透**进程在跑**（Tailscale / ZeroTier / EasyTier / frp / ngrok /
   cloudflared / nps / rathole / cpolar / natapp / holer），并且能把进程与本机某块
   非回环网卡对上（Tailscale 固定走 100.64.0.0/10，ZeroTier/EasyTier 按网卡名匹配）；
4. 都不满足 → `ok=False`：前端不请求、不显示二维码，只给提醒。

`frp`/`ngrok`/`cloudflared` 这类进程的公网地址写在对端配置里，本机推不出来，
因此它们只用来提示「检测到了进程但拿不到地址，请设 pair_url」，绝不用局域网 IP 冒充。

**端口**：本项目双实例运行——本地 `8765` 只绑 `127.0.0.1`、远程 `8766` 绑 `0.0.0.0`。
所以二维码里的端口**不能**取当前页面的端口（从本地页打开时会编出连不上的 8765），
而是按 `config.port → 8766 → 页面端口` 逐个 **TCP 探测**，用第一个真的在监听的。

**协议（3.6.148）**：候选地址默认全是 `http://`；只有一条会变成 `https://`——用户
自己写的 `pair_url`（第 1 条判定，自带协议），或"页面本身就是 https"（第 2 条判定，
`scheme` 由 `routes/pair._scheme` 判出来）。隧道与局域网 IP 候选永远是 http：
它们没有 TLS 入口，编成 https 只会让手机连不上。
"""
import ipaddress
import locale
import os
import re
import socket
import subprocess
import sys

# 进程名（小写，去 .exe）→ 展示名。只认这些远程访问/穿透工具，普通进程不参与判定。
TUNNEL_PROCS = {
    "tailscaled": "Tailscale", "tailscale": "Tailscale",
    "zerotier-one": "ZeroTier", "zerotier": "ZeroTier",
    "easytier": "EasyTier", "easytier-cli": "EasyTier",
    "frpc": "frp", "frps": "frp",
    "ngrok": "ngrok",
    "cloudflared": "Cloudflare Tunnel",
    "nps": "nps", "rathole": "rathole",
    "cpolar": "cpolar", "natapp": "natapp", "holer": "holer",
}

# 隧道工具 → 网卡名关键字（小写子串）；Tailscale 不靠名字，靠 CGNAT 网段。
IFACE_HINTS = {
    "ZeroTier": ("zerotier",),
    "EasyTier": ("easytier",),
}

CGNAT = ipaddress.ip_network("100.64.0.0/10")   # Tailscale 固定用这个段
IPV4_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")

# 远程服务专用端口（与 launcher_core.REMOTE_PORT 一致）。
# 本项目是"双实例"运行：本地 8765 **只绑 127.0.0.1**、远程 8766 才绑 0.0.0.0。
# 因此**绝不能**把"当前页面的端口"直接编进二维码——从 127.0.0.1:8765 打开面板时，
# 那个端口手机根本连不上（3.6.129 第一版就踩了这个坑，用户看到码里写着 8765）。
DEFAULT_REMOTE_PORT = 8766
PROBE_TIMEOUT = 0.6


def port_open(host, port, timeout=PROBE_TIMEOUT):
    """TCP 连一下：确认这个「地址:端口」真的有进程在监听（本地 8765 连不上会返回 False）。"""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError, OverflowError):
        return False


def _ports(page_port, cfg_port):
    """候选端口：config 里的 port（= 远程实例实际端口）→ 约定的 8766 → 页面端口。"""
    out = []
    for raw in (cfg_port, DEFAULT_REMOTE_PORT, page_port):
        try:
            port = int(raw or 0)
        except (TypeError, ValueError):
            continue
        if 0 < port < 65536 and port not in out:
            out.append(port)
    return out


def _decode(raw):
    """系统命令输出解码：Windows 控制台是 OEM 代码页（中文机器上是 936），别用 UTF-8 硬解。

    解码错了也不影响判定（网卡名/进程名的英文部分仍是 ASCII），但用户界面上
    展示候选地址时会带出乱码网卡名，所以按 OEM → ANSI → UTF-8 依次尝试。"""
    encs = ("oem", "mbcs") if sys.platform == "win32" else ()
    for enc in encs + (locale.getpreferredencoding(False), "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", "replace")


def _run(cmd):
    """跑一条只读命令；失败/超时/没这个命令一律空串（探测不能拖垮配对页）。"""
    flags = 0x08000000 if sys.platform == "win32" else 0   # CREATE_NO_WINDOW
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=4, creationflags=flags)
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""
    return _decode(done.stdout or b"")


def list_processes():
    """[(pid, 进程名小写)]；拿不到返回空列表（POSIX 用 ps，Windows 用 tasklist）。"""
    if sys.platform == "win32":
        out = []
        for line in _run(["tasklist", "/fo", "csv", "/nh"]).splitlines():
            m = re.match(r'\s*"([^"]+)","(\d+)"', line)
            if m:
                out.append((int(m.group(2)), m.group(1).lower()))
        return out
    out = []
    for line in _run(["ps", "-eo", "pid=,comm="]).splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            out.append((int(parts[0]), os.path.basename(parts[1].strip()).lower()))
    return out


def detect_tunnels(procs=None):
    """在跑的远程访问进程：[{pid, proc, label}]（同一工具只留一条）。"""
    found, seen = [], set()
    for pid, name in (list_processes() if procs is None else procs):
        base = name[:-4] if name.endswith(".exe") else name
        label = TUNNEL_PROCS.get(base)
        if label and label not in seen:
            seen.add(label)
            found.append({"pid": pid, "proc": base, "label": label})
    return found


def _parse_ipconfig(text):
    """Windows `ipconfig`：网卡名在顶格以冒号结尾的行，IPv4 在其后缩进行。"""
    out, iface = [], ""
    for line in text.splitlines():
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")) and line.rstrip().endswith(":"):
            head = line.rstrip()[:-1]
            for sep in (" adapter ", "适配器 "):
                if sep in head:
                    head = head.split(sep)[-1]
            iface = head.strip()
            continue
        if "IPv4" not in line:
            continue
        m = IPV4_RE.search(line)
        if m:
            out.append({"iface": iface, "ip": m.group(1)})
    return out


def _parse_ip_addr(text):
    """Linux `ip -o -4 addr show`：`2: eth0    inet 192.168.1.5/24 brd ...`。"""
    out = []
    for line in text.splitlines():
        m = re.match(r"\d+:\s+(\S+)\s+inet\s+(\d{1,3}(?:\.\d{1,3}){3})", line)
        if m:
            out.append({"iface": m.group(1), "ip": m.group(2)})
    return out


def _from_hostname():
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    return [{"iface": "", "ip": info[4][0]} for info in infos]


def local_ipv4(interfaces=None):
    """本机非回环 IPv4：[{iface, ip}]。`interfaces` 仅供测试注入。"""
    if interfaces is not None:
        return interfaces
    if sys.platform == "win32":
        return _parse_ipconfig(_run(["ipconfig"]))
    return _parse_ip_addr(_run(["ip", "-o", "-4", "addr", "show"])) or _from_hostname()


def kind(ip):
    """地址分类：tailscale / public / lan；回环与本机链路地址返回空串（不可用）。"""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ""
    if addr.is_loopback or addr.is_link_local or addr.is_unspecified:
        return ""
    if addr in CGNAT:
        return "tailscale"
    if addr.is_private:
        return "lan"
    return "public"


def is_loopback_host(host):
    """页面 host（可能带端口/方括号）是否是回环。"""
    name = (host or "").strip()
    if not name:
        return True
    if name.startswith("["):
        return True                                  # IPv6 字面量，本机场景一律按回环处理
    name = name.rsplit(":", 1)[0] if ":" in name else name
    return name in ("localhost", "") or name.startswith("127.")


def _blank(port, ifaces, tunnels, ports=()):
    return {"ok": False, "url": "", "host": "", "port": port, "source": "", "reason": "",
            "tunnels": [t["label"] for t in tunnels],
            "candidates": [it["ip"] for it in ifaces],
            "ports": list(ports)}


def _pick(url, source):
    host = url.split("://", 1)[-1].rstrip("/")
    return {"ok": True, "url": url.rstrip("/"), "host": host, "source": source,
            "reason": "ok"}


def _by_override(override):
    url = (override or "").strip()
    if url.startswith(("http://", "https://")) and not is_loopback_host(
            url.split("://", 1)[-1]):
        return _pick(url, "config")
    return None


def _by_host(host_header, port, scheme="http"):
    """页面 host 本身不是回环 → 以它为地址（协议由调用方给，见 `routes/pair._scheme`）。

    3.6.148（HTTPS）：`scheme="https"` 时**不补端口**。TLS 终结层（Tailscale serve /
    nginx 反代）把外面的 :8766 收在 443 上，Host 头里没有端口——照着 http 的老逻辑
    补成 `https://域名:8766`，手机就连不上了。反代在非 443 端口时 Host 头自带 `:8443`，
    走"已经带端口"的分支，不会被误判。"""
    if is_loopback_host(host_header):
        return None
    host = (host_header or "").strip()
    if ":" not in host.rsplit("]", 1)[-1] and scheme != "https":
        host = "%s:%d" % (host, port)
    return _pick(scheme + "://" + host, "request")


def _match_iface(label, ifaces):
    """把隧道进程和某块网卡对上；对不上返回 None。"""
    if label == "Tailscale":
        return next((it for it in ifaces if kind(it["ip"]) == "tailscale"), None)
    hints = IFACE_HINTS.get(label, ())
    for it in ifaces:
        if any(h in (it.get("iface") or "").lower() for h in hints):
            return it
    return None


def _by_tunnel(tunnels, ifaces, ports, probe=None):
    """按优先级找「进程在跑 + 地址对得上 + 那个端口真的在监听」的那一对。

    返回 (状态, 结果)：状态 ok=选中；closed=能对上但端口都不通（远程实例没起）；
    unmatched=没有能落到本机网卡上的隧道（frp/ngrok 等，公网地址在对端配置里）。"""
    check = probe or port_open
    labels = [t["label"] for t in tunnels]
    for label in ("Tailscale", "ZeroTier", "EasyTier"):
        hit = _match_iface(label, ifaces) if label in labels else None
        if not hit:
            continue
        for port in ports:
            if check(hit["ip"], port):
                return "ok", _pick("http://%s:%d" % (hit["ip"], port), "tunnel:" + label)
        return "closed", None
    return "unmatched", None


def _decide(port, host_header, override, ifaces, tunnels, cfg_port=None, probe=None,
            scheme="http"):
    ports = _ports(port, cfg_port)
    result = _blank(port, ifaces, tunnels, ports)
    picked = _by_override(override) or _by_host(host_header, port, scheme)
    if picked:
        result.update(picked)
        return result
    if not tunnels:
        result["reason"] = "no_remote"
        return result
    state, pick = _by_tunnel(tunnels, ifaces, ports, probe)
    if state == "ok":
        result.update(pick)
    else:
        result["reason"] = "not_listening" if state == "closed" else "tunnel_no_url"
    return result


def detect(port, host_header="", override="", interfaces=None, procs=None,
           cfg_port=None, probe=None, scheme="http"):
    """决定二维码该编码哪个地址。`interfaces`/`procs`/`probe`/`scheme` 仅供测试注入。

    `scheme` 只影响经 `host_header` 得到的地址（"用户在 https 页面上开的配对"）；
    `pair_url` 覆盖项自带协议，隧道/局域网候选一律 http（它们本身没有 TLS 入口）。"""
    raw = [it for it in local_ipv4(interfaces) if kind(it["ip"])]
    ifaces = sorted(({"iface": it.get("iface") or "", "ip": it["ip"],
                      "kind": kind(it["ip"])} for it in raw),
                    key=lambda it: {"tailscale": 0, "public": 1, "lan": 2}[it["kind"]])
    tunnel_list = detect_tunnels(procs)
    return _decide(int(port or DEFAULT_REMOTE_PORT), host_header, override, ifaces,
                   tunnel_list, cfg_port, probe, scheme)
