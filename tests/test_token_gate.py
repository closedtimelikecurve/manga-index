# -*- coding: utf-8 -*-
"""鉴权门禁（3.6.147）：主令牌可以不存在，但**鉴权不能因此消失**。

这一条是这次改动里最危险的地方：

```python
token = CFG.get("token") or ""
if not token:
    return None          # ← 旧逻辑：主令牌为空 = 远程端口裸奔
```

用户想删掉主令牌（手机已经用设备令牌），如果只删 config 里的值而不动这段，
8766 就会对任何能访问该端口的人完全开放——比留着令牌更糟。

所以这里守住三件事：
1. 没有主令牌 + 没有设备令牌 → **401**（fail-closed）；
2. 没有主令牌 + 有设备令牌 → 放行；
3. `compare_digest("", "")` 不能变成"放行"（两边都空时会返回 True）。
"""
import json
from types import SimpleNamespace

import pytest

import app as main_app
import common
import routes.pair as pair
import services.server as server_mod
import services.pair_devices as pd
import services.pair_target  # noqa: F401  （确保包已注册）

REACHABLE = {
    "ok": True, "url": "http://100.68.1.2:8766", "host": "100.68.1.2", "port": 8766,
    "source": "tunnel:Tailscale", "reason": "", "tunnels": ["Tailscale"],
    "candidates": ["100.68.1.2"], "ports": [8766],
}
REMOTE = {"REMOTE_ADDR": "100.99.1.1"}          # 非回环，才会走门禁


@pytest.fixture()
def env(tmp_path, monkeypatch):
    state = tmp_path / "_state"
    state.mkdir()
    monkeypatch.setattr(common, "STATE_DIR", str(state))
    monkeypatch.setattr(common, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(pair.pair_target, "detect", lambda *a, **k: dict(REACHABLE))
    monkeypatch.setitem(main_app.CFG, "token", "")
    return SimpleNamespace(client=main_app.app.test_client(), state=state)


def _claim(env, name="测试机"):
    """造一张票据并 claim，拿到设备令牌。"""
    j = env.client.get("/api/pair/qr").get_json()
    assert j["ok"] is True
    store = json.loads((env.state / "pair_tickets.json").read_text(encoding="utf-8"))
    ticket = max(store, key=lambda k: store[k]["created"])
    body = env.client.post("/api/pair/claim", json={"p": ticket, "n": name}).get_json()
    assert body["ok"] is True
    return body["token"]


def test_no_token_does_not_open_everything(env):
    """核心：主令牌为空时，非回环访问必须 401（旧逻辑这里是放行）。"""
    assert main_app.CFG["token"] == ""
    r = env.client.get("/api/config", environ_base=REMOTE)
    assert r.status_code == 401, "主令牌为空时远程访问被放行了（等于裸奔）"


def test_no_token_still_accepts_paired_device(env):
    """主令牌删掉后，已配对的手机必须还能用。"""
    dev = _claim(env)
    assert main_app.CFG["token"] == ""
    assert env.client.get("/api/config", environ_base=REMOTE,
                          headers={"X-Token": dev}).status_code == 200


def test_empty_given_with_empty_token_is_rejected(env):
    """两边都空时 compare_digest("", "") 返回 True —— 必须靠 `token and` 挡住。"""
    main_app.CFG["token"] = ""
    for headers in ({}, {"X-Token": ""}, {}):
        r = env.client.get("/api/config", environ_base=REMOTE, headers=headers)
        assert r.status_code == 401


def test_loopback_still_free(env):
    """本机回环一直免鉴权——这是"本机可信"的既有设计，删主令牌不影响。"""
    assert env.client.get("/api/config").status_code == 200


def test_info_reports_missing_main_token(env):
    info = env.client.get("/api/pair/info").get_json()
    assert info["hasMainToken"] is False
    main_app.CFG["token"] = "bks-abc"
    assert env.client.get("/api/pair/info").get_json()["hasMainToken"] is True


def test_remote_boot_does_not_regenerate_token_when_devices_exist(env, monkeypatch):
    """有已配对设备时，远程启动不得"顺手补一个主令牌"——否则删了也会被悄悄恢复。"""
    _claim(env)
    main_app.CFG["token"] = ""
    args = SimpleNamespace(host="0.0.0.0", token=None)
    assert server_mod._ensure_remote_token(args) is None
    assert main_app.CFG["token"] == "", "启动时又把主令牌生成回来了"


def test_remote_boot_generates_token_when_nothing_else(env):
    """既无主令牌、又无设备时才兜底生成——避免真正的裸奔。"""
    main_app.CFG["token"] = ""
    args = SimpleNamespace(host="0.0.0.0", token=None)
    got = server_mod._ensure_remote_token(args)
    assert got and got.startswith("bks-")
    assert main_app.CFG["token"] == got
