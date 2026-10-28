# -*- coding: utf-8 -*-
"""配对端点（3.6.144）：一次性票据 + 设备令牌。

守本次安全改造的四条承诺：

1. `/api/pair/info` **不再吐主令牌**（原先 `token` 字段直接给前端，等于白改）；
2. `/api/pair/qr` 返回的是 `{ok, svg, expiresIn}`，码里放票据而不是长期令牌；
3. `/api/pair/claim` 一次性：同一票据第二次必失败，过期返回 410；
4. 设备令牌能通过 `_token_gate`（与主令牌并列），乱写的令牌仍然 401。

打桩面：`common.STATE_DIR` 指向 tmp_path（**必须是这一处**——鉴权中间件与路由都读它，
两边不一致就会出现"claim 写到 A、鉴权查 B"，设备令牌永远过不了）；
`pair_target.detect` 固定返回可达，避免测试去真探测本机端口。
"""
import json
import os
from types import SimpleNamespace

import pytest

import app as main_app
import common
import routes.pair as pair

REACHABLE = {
    "ok": True, "url": "http://100.68.1.2:8766", "host": "100.68.1.2", "port": 8766,
    "source": "tunnel:Tailscale", "reason": "", "tunnels": ["Tailscale"],
    "candidates": ["100.68.1.2"], "ports": [8766],
}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    state = tmp_path / "_state"
    state.mkdir()
    monkeypatch.setattr(common, "STATE_DIR", str(state))
    # 轮换令牌会写 config.json —— 必须指到 tmp，否则动到真实配置
    monkeypatch.setattr(common, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(pair.pair_target, "detect", lambda *a, **k: dict(REACHABLE))
    monkeypatch.setitem(main_app.CFG, "token", "")
    return SimpleNamespace(client=main_app.app.test_client(), state=state,
                           tickets=state / "pair_tickets.json",
                           devices=state / "pair_devices.json")


def _ticket(env):
    """走一次 /api/pair/qr，从落盘表里取回**刚签发**的票据（表里可能已有旧票据）。"""
    j = env.client.get("/api/pair/qr").get_json()
    assert j["ok"] is True and "svg" in j
    with open(env.tickets, encoding="utf-8") as f:
        store = json.load(f)
    assert store, "签发后应落盘票据"
    return max(store, key=lambda k: store[k]["created"]), j


def test_info_no_longer_leaks_main_token(env):
    j = env.client.get("/api/pair/info").get_json()
    assert "token" not in j, "info 还在吐主令牌（改了票据也白搭）"
    assert j["canPair"] is True and j["url"].endswith(":8766")
    assert j["ticketTtl"] == 120, "默认票据有效期应为 120 秒"


def test_qr_returns_ticket_with_expiry(env):
    ticket, j = _ticket(env)
    assert j["expiresIn"] == 120
    assert "<svg" in j["svg"], "前端仍需要内联 SVG"
    assert len(ticket) == 32, "票据应是 128 bit 的十六进制"


def test_claim_is_single_use(env):
    ticket, _ = _ticket(env)
    first = env.client.post("/api/pair/claim", json={"p": ticket, "n": "小米 14"})
    assert first.status_code == 200
    body = first.get_json()
    assert body["ok"] is True and body["token"].startswith("dev-")
    assert body["deviceName"] == "小米 14"
    second = env.client.post("/api/pair/claim", json={"p": ticket, "n": "小米 14"})
    assert second.status_code == 409 and second.get_json()["reason"] == "used"


def test_claim_expired_and_unknown(env):
    env.tickets.write_text(json.dumps({"a" * 32: {"exp": 1, "created": 1, "ip": ""}}),
                           encoding="utf-8")
    expired = env.client.post("/api/pair/claim", json={"p": "a" * 32})
    assert expired.status_code == 410 and expired.get_json()["reason"] == "expired"
    unknown = env.client.post("/api/pair/claim", json={"p": "b" * 32})
    assert unknown.status_code == 400 and unknown.get_json()["reason"] == "unknown"


def test_device_token_passes_token_gate(env):
    """设备令牌与主令牌并列有效；乱写的仍然是 401。"""
    ticket, _ = _ticket(env)
    dev = env.client.post("/api/pair/claim", json={"p": ticket}).get_json()["token"]
    main_app.CFG["token"] = "bks-mainsecret"
    remote = {"REMOTE_ADDR": "100.99.1.1"}          # 非回环，才会走门禁

    assert env.client.get("/api/config", environ_base=remote).status_code == 401
    assert env.client.get("/api/config", environ_base=remote,
                          headers={"X-Token": "bks-mainsecret"}).status_code == 200
    assert env.client.get("/api/config", environ_base=remote,
                          headers={"X-Token": dev}).status_code == 200
    assert env.client.get("/api/config", environ_base=remote,
                          headers={"X-Token": "dev-deadbeef"}).status_code == 401


def test_claim_endpoint_is_public():
    """新手机没有任何令牌，claim 必须是公开端点，否则第一次绑定永远调不通。"""
    assert "api_pair_claim" in main_app.PUBLIC_ENDPOINTS
    assert "api_pair_qr" not in main_app.PUBLIC_ENDPOINTS, "取码仍然需要令牌"


def test_device_token_file_has_no_plaintext(env):
    ticket, _ = _ticket(env)
    dev = env.client.post("/api/pair/claim", json={"p": ticket}).get_json()["token"]
    assert dev not in env.devices.read_text(encoding="utf-8")


# ---------- 3.6.145：设备列表 / 吊销 / 轮换主令牌 ----------

def test_devices_list_and_revoke(env):
    """设备列表不含哈希；吊销后该设备令牌立刻失效（其它设备不受影响）。"""
    ticket, _ = _ticket(env)
    first = env.client.post("/api/pair/claim", json={"p": ticket, "n": "旧手机"}).get_json()
    ticket2, _ = _ticket(env)
    second = env.client.post("/api/pair/claim", json={"p": ticket2, "n": "新手机"}).get_json()

    items = env.client.get("/api/pair/devices").get_json()["devices"]
    assert {it["name"] for it in items} == {"旧手机", "新手机"}
    assert all("h" not in it for it in items), "列表把令牌哈希带出去了"

    main_app.CFG["token"] = "bks-mainsecret"
    remote = {"REMOTE_ADDR": "100.99.1.1"}
    assert env.client.get("/api/config", environ_base=remote,
                          headers={"X-Token": first["token"]}).status_code == 200

    r = env.client.delete("/api/pair/devices/" + first["deviceId"])
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert env.client.get("/api/config", environ_base=remote,
                          headers={"X-Token": first["token"]}).status_code == 401, \
        "吊销后旧令牌还能用"
    assert env.client.get("/api/config", environ_base=remote,
                          headers={"X-Token": second["token"]}).status_code == 200, \
        "吊销一台把另一台也踢了"
    assert env.client.delete("/api/pair/devices/" + first["deviceId"]).status_code == 404


def test_rotate_token_replaces_main_but_keeps_devices(env):
    """轮换主令牌：旧主令牌立刻失效、设备令牌继续有效（这正是分两套凭据的意义）。"""
    ticket, _ = _ticket(env)
    dev = env.client.post("/api/pair/claim", json={"p": ticket, "n": "手机"}).get_json()["token"]
    main_app.CFG["token"] = "bks-oldtoken"

    r = env.client.post("/api/config/rotate-token")
    assert r.status_code == 200
    new_token = r.get_json()["token"]
    assert new_token.startswith("bks-") and len(new_token) == 28
    assert new_token != "bks-oldtoken"
    assert main_app.CFG["token"] == new_token, "内存里的令牌没换（当前进程还会认旧令牌）"

    remote = {"REMOTE_ADDR": "100.99.1.1"}
    assert env.client.get("/api/config", environ_base=remote,
                          headers={"X-Token": "bks-oldtoken"}).status_code == 401
    assert env.client.get("/api/config", environ_base=remote,
                          headers={"X-Token": new_token}).status_code == 200
    assert env.client.get("/api/config", environ_base=remote,
                          headers={"X-Token": dev}).status_code == 200, \
        "轮换主令牌把已配对设备也踢了"


def test_credential_endpoints_are_not_public():
    """设备列表/吊销、轮换令牌都必须带令牌（只有 claim 靠票据本身鉴权）。"""
    for name in ("api_pair_devices", "api_pair_device_revoke", "api_rotate_token"):
        assert name not in main_app.PUBLIC_ENDPOINTS, name


# ---------- 3.6.146：挑战-响应与链路状态 ----------

def test_attest_endpoint_proves_identity(env):
    """APP 在 claim 之前就能验证"是不是上次那台"：发 nonce 拿 proof。"""
    import services.server_identity as si
    nonce = "a1b2c3d4e5f60718"
    j = env.client.post("/api/pair/attest", json={"n": nonce}).get_json()
    assert j["ok"] is True
    assert j["proof"] == si.attest(str(env.state), nonce), "proof 不是用本地 secret 算的"
    assert si.verify(str(env.state), nonce, j["proof"]) is True
    assert si.secret(str(env.state)) not in j["proof"], "proof 里带出了 secret"


def test_attest_rejects_bad_nonce(env):
    for bad in ("", "short", "x" * 200):
        r = env.client.post("/api/pair/attest", json={"n": bad})
        assert r.status_code == 400 and r.get_json()["reason"] == "bad_nonce"


def test_claim_returns_secret_and_info_shows_link(env):
    import services.server_identity as si
    ticket, _ = _ticket(env)
    body = env.client.post("/api/pair/claim", json={"p": ticket, "n": "手机"}).get_json()
    assert body["sk"] == si.secret(str(env.state)), "claim 没有下发服务器 secret"

    info = env.client.get("/api/pair/info").get_json()
    assert info["fingerprint"] == si.fingerprint(str(env.state))
    assert info["link"].startswith("tunnel:") or info["link"] in ("http", "https")
    assert "sk" not in info and si.secret(str(env.state)) not in str(info), \
        "info 把 secret 泄露出去了"


def test_attest_endpoint_is_public():
    """APP 调它时还没有任何令牌，必须是公开端点。"""
    assert "api_pair_attest" in main_app.PUBLIC_ENDPOINTS
