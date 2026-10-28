# -*- coding: utf-8 -*-
"""配对链路的 HTTPS 判定（3.6.148）。

背景：远程访问改由 **Tailscale serve** 终结 TLS —— tailscaled 在 443 上持有
Let's Encrypt 证书（公共信任链，Android 系统默认认可），再把请求反代到
`127.0.0.1:8766`。于是有两件事必须判对：

1. **协议**：反代后面 `request.is_secure` 恒为 False（wsgi.url_scheme 仍是 http），
   只能看 `X-Forwarded-Proto`；但这个头谁都能塞，所以**只认回环来源**，
   否则同网段的直连者可以让页面谎报"已加密"。
2. **地址**：https 时 443 是默认端口，Host 头不带端口就不能补 `:8766`
   ——那个端口跑的是明文 HTTP，补上会让手机握手失败。

`_link()` 另外守一条：警告必须针对**二维码里那个地址**，而不是当前页面。
本机 8765（回环、免鉴权、http）页面打开配对、`pair_url` 却是 https 域名时，
按 `request.is_secure` 判会误报"明文"。
"""
import pytest

import app as main_app
import routes.pair as pair


def _ctx(remote="127.0.0.1", proto=None, scheme="http"):
    """造一个请求上下文：`remote` 是 TCP 对端地址，`proto` 是反代塞的头。"""
    headers = {"X-Forwarded-Proto": proto} if proto else {}
    return main_app.app.test_request_context(
        "/api/pair/info", headers=headers, base_url="%s://test.local/" % scheme,
        environ_overrides={"REMOTE_ADDR": remote})


# ---------------------------------------------------------------
# _scheme()：外部协议
# ---------------------------------------------------------------

def test_local_proxy_forwarded_proto_is_trusted():
    """本机反代（tailscaled 从 127.0.0.1 转发）声明 https → 采信。"""
    with _ctx(remote="127.0.0.1", proto="https"):
        assert pair._scheme() == "https"


def test_ipv6_loopback_proxy_is_trusted():
    with _ctx(remote="::1", proto="https"):
        assert pair._scheme() == "https"


def test_forwarded_proto_from_lan_is_rejected():
    """同网段直连者伪造 X-Forwarded-Proto: https —— 必须当没看见。

    这不是权限问题（该头只影响文案和二维码地址），但**谎报安全状态**比明文更危险：
    用户会以为自己被加密了，从而愿意在这条链路上输令牌。"""
    with _ctx(remote="192.168.1.50", proto="https"):
        assert pair._scheme() == "http"


def test_multiple_forwarded_proto_takes_the_first():
    """`X-Forwarded-Proto: https, http` —— 最左是客户端侧真实协议。"""
    with _ctx(remote="127.0.0.1", proto="https, http"):
        assert pair._scheme() == "https"


def test_direct_tls_is_recognised():
    """没有反代、Flask 自己起 TLS（wsgi.url_scheme=https）时也要认。"""
    with _ctx(remote="127.0.0.1", scheme="https"):
        assert pair._scheme() == "https"


def test_garbage_forwarded_proto_falls_back_to_scheme():
    with _ctx(remote="127.0.0.1", proto="ftp"):
        assert pair._scheme() == "http"


# ---------------------------------------------------------------
# _link()：给前端的加密级别
# ---------------------------------------------------------------

def test_link_https_when_target_url_is_https():
    """本机 http 页面 + pair_url 给 https → 必须报 https（不能按当前页面判）。"""
    with _ctx(remote="127.0.0.1", scheme="http"):
        got = pair._link({"url": "https://index-node-abcde.ts.net",
                          "source": "config"})
    assert got == "https"


def test_link_tunnel_wins_when_url_is_plain_http():
    with _ctx(remote="127.0.0.1", scheme="http"):
        got = pair._link({"url": "http://100.64.0.10:8766",
                          "source": "tunnel:Tailscale"})
    assert got == "tunnel:Tailscale"


def test_link_http_warns_when_nothing_encrypts():
    with _ctx(remote="127.0.0.1", scheme="http"):
        got = pair._link({"url": "http://192.168.1.5:8766", "source": "request"})
    assert got == "http"


def test_link_follows_page_scheme_behind_proxy():
    """反代 + Host 头地址（source=request）时，按反代声明的协议判。"""
    with _ctx(remote="127.0.0.1", proto="https"):
        got = pair._link({"url": "https://index-node-abcde.ts.net",
                          "source": "request"})
    assert got == "https"


# ---------------------------------------------------------------
# /api/pair/info 整体契约
# ---------------------------------------------------------------

@pytest.fixture()
def https_env(tmp_path, monkeypatch):
    """反代场景：本机回环代理 + 声明 https + pair_url 指向 ts.net 域名。"""
    import common
    state = tmp_path / "_state"
    state.mkdir()
    monkeypatch.setattr(common, "STATE_DIR", str(state))
    monkeypatch.setattr(common, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setitem(common.CFG, "pair_url", "https://index-node-abcde.ts.net")
    monkeypatch.setitem(common.CFG, "token", "")


def test_pair_info_reports_https_through_proxy(https_env):
    """端到端：反代（http 到后端、https 对外）+ pair_url=https 域名 →
    info 里的 url / secure / link 三者一致，前端才会显 🔒 而不是 ⚠。"""
    client = main_app.app.test_client()
    resp = client.get("/api/pair/info",
                      headers={"X-Forwarded-Proto": "https"},
                      base_url="http://index-node-abcde.ts.net/",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["url"] == "https://index-node-abcde.ts.net", body["url"]
    assert body["secure"] is True
    assert body["link"] == "https"
    assert body["canPair"] is True


def test_forwarded_proto_cannot_bypass_auth(https_env):
    """伪造 `X-Forwarded-Proto: https` 的远程直连者，连 info 都读不到（401）。

    这条同时锁住两件事：`X-Forwarded-Proto` 只在回环反代时才被采信，
    且它不是绕过鉴权的后门——加密头的存在与否跟能不能进是两个问题。"""
    client = main_app.app.test_client()
    resp = client.get("/api/pair/info",
                      headers={"X-Forwarded-Proto": "https"},
                      base_url="http://192.168.1.50:8766/",
                      environ_overrides={"REMOTE_ADDR": "192.168.1.50"})
    assert resp.status_code == 401


# ---------------------------------------------------------------
# 配置白名单（3.6.148 顺带发现的既有缺陷）
# ---------------------------------------------------------------

def test_pair_config_keys_survive_load(tmp_path, monkeypatch):
    """守纪律：`routes/pair.py` 读的配置键必须能真的从 config.json 读回内存。

    背景：`pair_url` 与 `pair_ticket_ttl` 双双漏在 `common._apply_scalars` 的
    白名单外，于是"config.json 里写了等于没写"——而前端还一直提示"请设置 pair_url"，
    用户照做了也无效，且**没有任何报错**。这类配置静默失效只能靠测试锁住。
    """
    import common
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        '{"root": "%s", "pair_url": "https://x.ts.net", "pair_ticket_ttl": 300}'
        % str(tmp_path).replace("\\", "\\\\"),
        encoding="utf-8")
    monkeypatch.setattr(common, "CONFIG_FILE", str(cfg_file))
    got = common.load_config()
    assert got["pair_url"] == "https://x.ts.net"
    assert got["pair_ticket_ttl"] == 300


def test_pair_config_keys_default_to_none(tmp_path, monkeypatch):
    """没配时必须是 None 而不是空串/0：save_config 会跳过 None，配置里就不会
    凭空多出 `"pair_url": ""` 这种噪声行。"""
    import common
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"root": "%s"}' % str(tmp_path).replace("\\", "\\\\"),
                        encoding="utf-8")
    monkeypatch.setattr(common, "CONFIG_FILE", str(cfg_file))
    got = common.load_config()
    assert got["pair_url"] is None
    assert got["pair_ticket_ttl"] is None
