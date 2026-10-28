# -*- coding: utf-8 -*-
"""扫码配对的地址探测（3.6.129）。

用户报障：二维码只吐本机回环，手机扫了等于连自己。这里守住三件事：
1) 从 127.0.0.1 打开、又没起远程进程 → **不出码**（reason=no_remote）；
2) 检测到 Tailscale 且能对上 100.64/10 地址 → 用该地址；
3) 只有 frp/ngrok 这类拿不到公网地址的进程 → 提示手填 pair_url，绝不用局域网 IP 冒充。

进程列表与网卡列表全部用参数注入，测试不依赖本机真实环境。
"""
import sys

import pytest

import services.pair_target as pt


def _detect(host="127.0.0.1:8766", interfaces=(), procs=(), override="",
            page_port=8766, cfg_port=8766, open_ports=(8766,), scheme="http"):
    """探测函数也注入：`open_ports` 里列出的端口视为"真有进程在监听"。"""
    return pt.detect(page_port, host, override, interfaces=list(interfaces),
                     procs=list(procs), cfg_port=cfg_port,
                     probe=lambda _host, port: port in open_ports, scheme=scheme)


def test_no_remote_process_means_no_qr():
    """本机回环 + 纯局域网网卡 + 没有任何远程进程 → 不出码，并说明原因。"""
    got = _detect(interfaces=[{"iface": "WLAN", "ip": "172.23.79.112"}],
                  procs=[(4, "chrome.exe"), (5, "python.exe")])
    assert got["ok"] is False and got["url"] == ""
    assert got["reason"] == "no_remote"
    assert got["candidates"] == ["172.23.79.112"]      # 候选地址仍然报给前端做提示


def test_tailscale_running_uses_cgnat_address():
    """Tailscale 在跑 → 地址取 100.64/10 那块网卡，端口沿用页面端口。"""
    got = _detect(interfaces=[{"iface": "WLAN", "ip": "172.23.79.112"},
                              {"iface": "Tailscale", "ip": "100.64.0.10"}],
                  procs=[(6936, "tailscaled.exe")], open_ports=(8766,))
    assert got["ok"] is True and got["url"] == "http://100.64.0.10:8766"
    assert got["source"] == "tunnel:Tailscale" and got["reason"] == "ok"


def test_zerotier_matches_by_interface_name():
    """ZeroTier 的地址不一定在 100.64/10，靠网卡名和进程配对。"""
    got = _detect(interfaces=[{"iface": "ZeroTier One [1234]", "ip": "10.147.20.9"}],
                  procs=[(88, "zerotier-one")], open_ports=(8766,))
    assert got["ok"] is True and got["url"] == "http://10.147.20.9:8766"
    assert got["source"] == "tunnel:ZeroTier"


def test_tunnel_without_local_url_asks_for_pair_url():
    """frp/ngrok 的公网地址在对端配置里，本机推不出 → 不出码，提示设 pair_url。"""
    got = _detect(interfaces=[{"iface": "WLAN", "ip": "172.23.79.112"}],
                  procs=[(7, "frpc.exe")])
    assert got["ok"] is False and got["reason"] == "tunnel_no_url"
    assert got["tunnels"] == ["frp"]


def test_config_pair_url_wins_over_detection():
    """显式配置优先于一切自动探测（穿透域名只能这么给）。"""
    got = _detect(interfaces=[{"iface": "Tailscale", "ip": "100.64.0.10"}],
                  procs=[(6936, "tailscaled")], open_ports=(8766,),
                  override="http://lib.example.com:8766/")
    assert got["ok"] is True and got["url"] == "http://lib.example.com:8766"
    assert got["source"] == "config"


def test_remote_page_host_is_used_as_is():
    """用户本来就从远程地址打开面板 → 页面 host 就是手机可达的地址。"""
    got = _detect(host="100.64.0.10:8766", interfaces=[], procs=[])
    assert got["ok"] is True and got["url"] == "http://100.64.0.10:8766"
    assert got["source"] == "request"


def test_local_page_port_is_never_encoded():
    """回归（用户实测：码里写着 8765）：本地实例 8765 只绑 127.0.0.1，
    从它的页面打开配对时，端口必须落到真正在监听的 8766 上。"""
    got = _detect(page_port=8765, cfg_port=8766, open_ports=(8766,),
                  interfaces=[{"iface": "WLAN", "ip": "172.23.79.112"},
                              {"iface": "Tailscale", "ip": "100.64.0.10"}],
                  procs=[(6936, "tailscaled")])
    assert got["ok"] is True
    assert got["url"].endswith(":8766"), "把只绑回环的页面端口（8765）编进了二维码"
    assert got["ports"][0] == 8766, "候选端口顺序不对：config.port 应排在最前"


def test_tunnel_running_but_panel_not_listening():
    """进程在跑、但那个地址上没有端口在听（远程服务没启动）→ 不出码并说明原因。"""
    got = _detect(open_ports=(),
                  interfaces=[{"iface": "Tailscale", "ip": "100.64.0.10"}],
                  procs=[(6936, "tailscaled")])
    assert got["ok"] is False and got["reason"] == "not_listening"
    assert "127.0.0.1" not in got["url"]


@pytest.mark.parametrize("host", ["127.0.0.1:8766", "localhost:8766", "", "[::1]:8766"])
def test_loopback_hosts_are_recognised(host):
    assert pt.is_loopback_host(host) is True


def test_address_kind_classification():
    assert pt.kind("100.64.0.10") == "tailscale"    # CGNAT 段 = Tailscale
    assert pt.kind("192.168.1.5") == "lan"
    assert pt.kind("8.8.8.8") == "public"
    assert pt.kind("127.0.0.1") == ""                  # 回环不可用
    assert pt.kind("169.254.1.2") == ""                # 链路本地不可用
    assert pt.kind("不是地址") == ""


def test_qr_endpoint_refuses_when_unreachable(monkeypatch):
    """/api/pair/qr 必须 409 —— 不能悄悄编进一个连不上的地址。"""
    import app as app_mod
    monkeypatch.setitem(app_mod.CFG, "token", "")
    monkeypatch.setattr(pt, "detect", lambda *a, **k: {
        "ok": False, "url": "", "host": "", "port": 8766, "source": "",
        "reason": "no_remote", "tunnels": [], "candidates": ["172.23.79.112"]})
    client = app_mod.app.test_client()
    r = client.get("/api/pair/qr")
    assert r.status_code == 409 and r.get_json()["reason"] == "no_remote"
    info = client.get("/api/pair/info").get_json()
    assert info["canPair"] is False and info["reason"] == "no_remote"


def test_info_reports_can_pair_and_address(monkeypatch):
    import app as app_mod
    monkeypatch.setitem(app_mod.CFG, "token", "")
    monkeypatch.setattr(pt, "detect", lambda *a, **k: {
        "ok": True, "url": "http://100.1.2.3:8766", "host": "100.1.2.3:8766",
        "port": 8766, "source": "tunnel:Tailscale", "reason": "ok",
        "tunnels": ["Tailscale"], "candidates": ["100.1.2.3"]})
    info = app_mod.app.test_client().get("/api/pair/info").get_json()
    assert info["canPair"] is True and info["url"] == "http://100.1.2.3:8766"
    assert info["source"] == "tunnel:Tailscale" and info["tunnels"] == ["Tailscale"]


def test_no_silent_fallback_to_loopback(monkeypatch):
    """回归点：绝不允许把 127.0.0.1 编进二维码（旧实现就是这么干的）。"""
    got = _detect(interfaces=[{"iface": "WLAN", "ip": "192.168.1.5"}], procs=[])
    assert "127.0.0.1" not in got["url"]
    assert got["ok"] is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ---------------------------------------------------------------
# HTTPS 入口（3.6.148）：Tailscale serve / 反代终结 TLS 后的地址推断
# ---------------------------------------------------------------

def test_https_page_host_drops_the_proxy_port():
    """反代终结 TLS 时 Host 头不带端口（443 是默认），**绝不能**再补 :8766。

    补了就是 `https://域名:8766` —— 那台机器 8766 上跑的是明文 HTTP，
    手机会握手失败（本项目实测：补端口后 APP 报 SSL 错误，扫码连不上）。"""
    got = _detect(host="index-node-abcde.ts.net", interfaces=[], procs=[],
                  scheme="https")
    assert got["ok"] is True
    assert got["url"] == "https://index-node-abcde.ts.net", got["url"]
    assert got["source"] == "request"


def test_https_page_host_keeps_non_default_port():
    """反代不在 443（如 :8443）时 Host 头自带端口，照抄即可。"""
    got = _detect(host="index-node-abcde.ts.net:8443", interfaces=[], procs=[],
                  scheme="https")
    assert got["url"] == "https://index-node-abcde.ts.net:8443"


def test_http_page_host_still_gets_the_probed_port():
    """回归：http 分支的补端口行为不能因为 https 改造而丢。"""
    got = _detect(host="100.64.0.10", interfaces=[], procs=[], scheme="http")
    assert got["url"] == "http://100.64.0.10:8766"


def test_https_pair_url_is_accepted():
    """pair_url 写 https 域名时原样采用（这正是 Tailscale serve 的推荐配法）。"""
    got = _detect(interfaces=[{"iface": "Tailscale", "ip": "100.64.0.10"}],
                  procs=[(6936, "tailscaled")], open_ports=(8766,),
                  override="https://index-node-abcde.ts.net/")
    assert got["ok"] is True
    assert got["url"] == "https://index-node-abcde.ts.net"
    assert got["source"] == "config"


def test_tunnel_ip_candidates_stay_http_even_on_https_page():
    """从 https 页面打开、但 host 是回环 → 回落到隧道候选，那些 IP 没有 TLS 入口，
    必须仍是 http（编成 https 只会让手机连不上）。"""
    got = _detect(host="127.0.0.1:8766", scheme="https",
                  interfaces=[{"iface": "Tailscale", "ip": "100.64.0.10"}],
                  procs=[(6936, "tailscaled")], open_ports=(8766,))
    assert got["url"] == "http://100.64.0.10:8766", got["url"]
