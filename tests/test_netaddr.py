# -*- coding: utf-8 -*-
"""真实客户端地址判定（3.6.148）——**安全回归，别再退化**。

## 这次差点造成的洞

远程访问改由 Tailscale serve 终结 TLS，tailscaled 恒从 `127.0.0.1` 反代，
于是 `request.remote_addr` 对**任何**进入 443 的请求都是回环。而 `_token_gate`
正是拿回环当"本机免鉴权"的依据，实测：

```
GET https://<节点>.ts.net/api/library   （不带任何令牌）
→ 200，554 KB 全量库
```

tailnet 内每台设备（含手机丢失后仍在 tailnet 的、含被 ACL 分享给他人的机器）
都能读整个文库。**加 HTTPS 反而把鉴权弄没了**，这是本轮最该记住的教训：
换传输层时，任何"按来源地址判身份"的地方都要重新审一遍。

## 信任规则

`remote_addr` 不是回环 → 直接用它，**不信** `X-Forwarded-For`（局域网可伪造）；
`remote_addr` 是回环 → 取 XFF 里第一个非回环地址（跳过代理自身）。
"""
import pytest

import app as main_app
import common
from services import netaddr

AUTHED_ENDPOINT = "/api/pair/devices"     # 不在 PUBLIC_ENDPOINTS 里，最轻的受保护接口


# ---------------------------------------------------------------
# netaddr 纯函数
# ---------------------------------------------------------------

@pytest.mark.parametrize("addr", ["127.0.0.1", "::1", "::ffff:127.0.0.1",
                                  "127.0.0.5", "::ffff:127.1.2.3"])
def test_loopback_forms_are_recognised(addr):
    assert netaddr.is_loopback(addr) is True


@pytest.mark.parametrize("addr", ["192.168.1.5", "100.64.0.10", "", None,
                                  "0.0.0.0", "8.8.8.8", "not-an-ip"])
def test_non_loopback_and_garbage_are_not_loopback(addr):
    """解析不出来的地址**绝不**当回环——宁可多要一次令牌，也不能把看不懂的东西放行。"""
    assert netaddr.is_loopback(addr) is False


def test_direct_client_ignores_forwarded_header():
    """直连（remote_addr 非回环）时不看 XFF：局域网设备伪造 `127.0.0.1` 也无效。"""
    got = netaddr.real_client("192.168.1.50", "127.0.0.1")
    assert got == "192.168.1.50"


def test_proxied_client_comes_from_forwarded_header():
    """经本机反代（remote_addr 是回环）时取 XFF 里的真实客户端。"""
    got = netaddr.real_client("127.0.0.1", "100.64.0.10")
    assert got == "100.64.0.10"


def test_proxy_chain_skips_intermediate_loopback():
    """`127.0.0.1, 100.x`——链里出现的回环都是代理自身，跳过它们取真实客户端。"""
    got = netaddr.real_client("127.0.0.1", "127.0.0.1, 100.64.0.10")
    assert got == "100.64.0.10"


def test_local_browser_has_no_forwarded_header():
    """本机浏览器直连：没有 XFF → 仍是回环 → 免鉴权行为不变。"""
    assert netaddr.is_local("127.0.0.1", "") is True
    assert netaddr.real_client("127.0.0.1", "") == "127.0.0.1"


def test_all_loopback_forwarded_chain_stays_local():
    """客户端本身就在本机（经反代访问自己的面板）→ 仍算本机。"""
    assert netaddr.is_local("127.0.0.1", "127.0.0.1") is True


def test_zone_id_suffix_is_stripped():
    """IPv6 链路本地地址常带 `%eth0` 后缀，判回环前要剥掉。"""
    assert netaddr.is_loopback("::1%lo0") is True


# ---------------------------------------------------------------
# _token_gate 端到端：这才是真正会漏数据的那道门
# ---------------------------------------------------------------

@pytest.fixture()
def env(tmp_path, monkeypatch):
    state = tmp_path / "_state"
    state.mkdir()
    monkeypatch.setattr(common, "STATE_DIR", str(state))
    monkeypatch.setattr(common, "CONFIG_FILE", str(tmp_path / "config.json"))
    # 主令牌为空：此时"回环免鉴权"就是唯一的门，误判直接等于全库泄露
    monkeypatch.setitem(main_app.CFG, "token", "")
    return state


def _request(remote="127.0.0.1", xff=None, path=AUTHED_ENDPOINT):
    headers = {"X-Forwarded-For": xff} if xff else {}
    return main_app.app.test_client().get(
        path, headers=headers, environ_overrides={"REMOTE_ADDR": remote})


def test_proxied_remote_client_gets_401(env):
    """回归主案：经 Tailscale serve 的远程设备**必须**要令牌。

    未修前这里返回 200 与全量数据（remote_addr=127.0.0.1 被当成"本机"）。"""
    resp = _request(remote="127.0.0.1", xff="100.64.0.10")
    assert resp.status_code == 401, "反代后面的远程客户端被当成了本机，整库裸奔"


def test_local_browser_still_passes(env):
    """本机浏览器：remote_addr 回环、无 XFF → 照旧免鉴权（不能把用户自己关在门外）。"""
    resp = _request(remote="127.0.0.1")
    assert resp.status_code == 200


def test_lan_client_cannot_forge_loopback_forwarded_header(env):
    """局域网直连者伪造 `X-Forwarded-For: 127.0.0.1` —— 仍然 401。

    因为 remote_addr 已经是非回环，规则 1 生效：根本不看这个头。"""
    resp = _request(remote="192.168.1.50", xff="127.0.0.1")
    assert resp.status_code == 401


def test_proxied_client_with_valid_device_token_passes(env):
    """真实手机的场景：经反代 + 带设备令牌 → 放行。"""
    from services import pair_devices
    dev = pair_devices.issue(str(env), name="V2405A")
    resp = main_app.app.test_client().get(
        AUTHED_ENDPOINT,
        headers={"X-Forwarded-For": "100.64.0.10", "X-Token": dev["token"]},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200


# ---------------------------------------------------------------
# waitress 代理头配置（根因所在，删掉这几行就等于重新打开那个洞）
# ---------------------------------------------------------------

def test_waitress_trusts_only_loopback_proxy(monkeypatch):
    """waitress 必须信任**回环来源**的 `X-Forwarded-*`，否则远程鉴权整体失效。

    未配 `trusted_proxy` 时 waitress 的 `clear_untrusted_proxy_headers`（默认 True）
    会把转发头全部清掉，后端 `remote_addr` 恒为 127.0.0.1，被当成本机放行。

    只配 `"127.0.0.1"` 而**不是** `"*"`：前者意味着只有本机进程（tailscaled、本机
    nginx）能注入转发头，局域网直连者的伪造头照旧被清除。
    `x-forwarded-for` 必须显式列入可信头——waitress 默认只保留 `x-forwarded-proto`。
    """
    import services.server as srv
    captured = {}

    def fake_create(app, **kw):
        captured.update(kw)
        return "SRV"

    monkeypatch.setattr(main_app, "_waitress_create", fake_create)
    assert srv._make_server(8766, "0.0.0.0") == "SRV"
    assert captured["trusted_proxy"] == "127.0.0.1", "waitress 不信任本机反代 → 转发头被清空"
    trusted = set(captured["trusted_proxy_headers"])
    assert "x-forwarded-for" in trusted, "XFF 被清掉就判不出真实客户端"
    assert "x-forwarded-proto" in trusted, "XFP 被清掉就判不出 https"


def test_make_server_falls_back_without_waitress(monkeypatch):
    """没装 waitress 时回退 werkzeug（该路径不清理转发头，由 netaddr 兜底判定）。"""
    import services.server as srv
    monkeypatch.setattr(main_app, "_waitress_create", None)
    calls = {}

    def fake_make_server(host, port, app, threaded=False):
        calls.update({"host": host, "port": port, "threaded": threaded})
        return "WERKZEUG"

    monkeypatch.setattr(srv, "make_server", fake_make_server)
    assert srv._make_server(9000, "127.0.0.1") == "WERKZEUG"
    assert calls == {"host": "127.0.0.1", "port": 9000, "threaded": True}
