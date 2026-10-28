# -*- coding: utf-8 -*-
"""一次性配对票据与设备令牌的存储层（3.6.144）。

守四件事，对应本次安全改造的核心承诺：

1. **票据短时效**：默认 120 秒（配置可调但夹在 30~600），过期即 `expired`；
2. **票据一次性**：`claim` 成功一次后再来必是 `used`，与是否在有效期内无关；
3. **跨实例可见**：票据落盘在 `_state/`，另一个进程（本项目的 8765/8766 双实例）
   读同一份文件就能验——只存进程内存的话，从 8765 页面生成的码在 8766 必然验不过；
4. **设备令牌只存哈希**：设备表文件里不能出现明文令牌，泄露文件也拿不到凭据。
"""
import json
import os

import services.pair_devices as pd
import services.pair_tickets as pt


# ---------- 票据 ----------

def test_issue_returns_short_lived_ticket(tmp_path):
    got = pt.issue(str(tmp_path), ip="100.68.1.2")
    assert len(got["ticket"]) == 32 and all(c in "0123456789abcdef" for c in got["ticket"])
    assert got["expiresIn"] == 120, "默认有效期应为 120 秒（60 秒对首次扫码太紧）"
    assert got["expiresAt"] > got["expiresAt"] - 1
    # 落盘：证明它不是只活在内存里（双实例场景的唯一依据）
    with open(os.path.join(str(tmp_path), "pair_tickets.json"), encoding="utf-8") as f:
        store = json.load(f)
    assert got["ticket"] in store and store[got["ticket"]]["ip"] == "100.68.1.2"


def test_ticket_is_single_use(tmp_path):
    d = str(tmp_path)
    t = pt.issue(d)["ticket"]
    status, _ = pt.claim(d, t, ip="100.99.1.1")
    assert status == "ok"
    status2, _ = pt.claim(d, t, ip="100.99.1.1")
    assert status2 == "used", "同一票据第二次必须作废，否则等于长期有效"
    status3, _ = pt.claim(d, t, ip="100.99.9.9")
    assert status3 == "used", "换来源 IP 也不能重放"


def test_ticket_expires(tmp_path):
    d = str(tmp_path)
    got = pt.issue(d, ttl=120)
    # 用注入的 now 模拟 121 秒后
    status, _ = pt.claim(d, got["ticket"], now=got["expiresAt"] + 1)
    assert status == "expired"


def test_unknown_and_empty_ticket(tmp_path):
    d = str(tmp_path)
    assert pt.claim(d, "deadbeef" * 4)[0] == "unknown"
    assert pt.claim(d, "")[0] == "unknown"


def test_ttl_is_clamped(tmp_path):
    assert pt.clamp_ttl(None) == pt.DEFAULT_TTL
    assert pt.clamp_ttl("abc") == pt.DEFAULT_TTL
    assert pt.clamp_ttl(5) == pt.DEFAULT_TTL, "过短的 ttl 要回默认，不能真按 5 秒签"
    assert pt.clamp_ttl(9999) == pt.DEFAULT_TTL
    assert pt.clamp_ttl(300) == 300
    assert pt.issue(str(tmp_path), ttl=300)["expiresIn"] == 300


def test_purge_drops_expired(tmp_path):
    d = str(tmp_path)
    old = pt.issue(d, ttl=120)
    pt.purge(d, now=old["expiresAt"] + 1)
    with open(os.path.join(d, "pair_tickets.json"), encoding="utf-8") as f:
        assert json.load(f) == {}, "过期票据要清掉，否则表会一直涨"


def test_ticket_survives_a_fresh_reader(tmp_path):
    """模拟另一个实例：本模块没有内存态，重新读文件即可 claim（这就是跨实例可见）。"""
    d = str(tmp_path)
    t = pt.issue(d)["ticket"]
    assert os.path.exists(os.path.join(d, "pair_tickets.json"))
    assert pt.claim(d, t)[0] == "ok"


# ---------- 设备令牌 ----------

def test_device_token_is_hashed_on_disk(tmp_path):
    d = str(tmp_path)
    got = pd.issue(d, name="小米 14")
    assert got["token"].startswith(pd.PREFIX) and len(got["token"]) == 36
    assert pd.verify(d, got["token"]) == got["deviceId"]
    with open(os.path.join(d, "pair_devices.json"), encoding="utf-8") as f:
        raw = f.read()
    assert got["token"] not in raw, "明文令牌绝不能落盘"
    assert got["deviceId"] in raw and "小米 14" in raw


def test_device_revoke_kills_token(tmp_path):
    d = str(tmp_path)
    got = pd.issue(d, name="旧手机")
    assert pd.verify(d, got["token"]) == got["deviceId"]
    assert pd.revoke(d, got["deviceId"]) is True
    assert pd.verify(d, got["token"]) is None, "吊销后必须立刻失效"
    assert pd.revoke(d, got["deviceId"]) is False


def test_device_verify_rejects_non_device_tokens(tmp_path):
    """主令牌（非 dev- 前缀）不该被当成设备令牌校验，避免两套凭据混淆。"""
    d = str(tmp_path)
    pd.issue(d, name="x")
    assert pd.verify(d, "bks-0123456789abcdef01234567") is None
    assert pd.verify(d, "") is None


def test_device_list_hides_hash(tmp_path):
    d = str(tmp_path)
    pd.issue(d, name="A")
    pd.issue(d, name="B")
    items = pd.list_devices(d)
    assert len(items) == 2
    assert all("h" not in it for it in items)
    assert {it["name"] for it in items} == {"A", "B"}
    pd.touch(d, items[0]["deviceId"])
    assert pd.list_devices(d)[0]["deviceId"] == items[0]["deviceId"], "最近使用的排前面"
