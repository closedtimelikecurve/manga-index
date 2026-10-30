# -*- coding: utf-8 -*-
"""设备按机器码识别（3.6.162）。

## 要解决的问题

原先每扫一次码就 `issue()` 一条新设备记录：同一台手机重扫三次，面板里就冒出三台
"V2405A"，而且旧的两条令牌**仍然有效**——既看不清设备，也留下了多余的长期凭据。

现在 claim 会带上 `m`（机器码，APP 用 ANDROID_ID）与 `t`（本机已有令牌）：

* 机器码登记过 + 令牌对得上 → **原样返回**：不加设备、不换 token（真正意义上的"复用"）；
* 机器码登记过 + 令牌对不上（APP 重装 / 清了数据）→ 复用同一个 deviceId，**轮换** token。
  设备数不增加，符合"不生成新设备"；旧令牌立即失效，避免留下可用的僵尸凭据；
* 机器码没登记（换机 / 首次）→ 新建，与旧版一致；
* 调用方没给机器码（老版本 APP）→ 也新建，**不能被这次改动弄坏**。

为什么不存明文 token 换来"永久复用"：那等于把长期凭据明文写进 `_state`，
文件一泄露所有设备一起失守。只存哈希是 3.6.144 立的底线。
"""
import os
import sys

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

from services import pair_devices as pd  # noqa: E402


def test_new_machine_creates_device(tmp_path):
    d = str(tmp_path)
    r = pd.issue(d, name="Pixel", machine="machine-a")
    assert r["reused"] is False
    assert len(pd.list_devices(d)) == 1
    assert pd.verify(d, r["token"]) == r["deviceId"]


def test_same_machine_with_valid_token_reuses_everything(tmp_path):
    """已登记设备带着有效令牌重扫：设备不加、token 不换。"""
    d = str(tmp_path)
    first = pd.issue(d, name="Pixel", machine="machine-a")
    again = pd.issue(d, name="Pixel", machine="machine-a", known_token=first["token"])
    assert again["reused"] is True
    assert again["deviceId"] == first["deviceId"]
    assert again["token"] == first["token"]
    assert len(pd.list_devices(d)) == 1


def test_same_machine_without_token_rotates_only(tmp_path):
    """APP 重装（本地令牌丢了）：deviceId 不变，只轮换 token，设备数不增加。"""
    d = str(tmp_path)
    first = pd.issue(d, name="Pixel", machine="machine-a")
    again = pd.issue(d, name="Pixel", machine="machine-a")
    assert again["reused"] is False
    assert again["deviceId"] == first["deviceId"]
    assert again["token"] != first["token"]
    assert len(pd.list_devices(d)) == 1
    assert pd.verify(d, first["token"]) is None, "旧令牌必须立刻失效"
    assert pd.verify(d, again["token"]) == first["deviceId"]


def test_other_devices_token_is_not_hijacked(tmp_path):
    """机器码对、但带来的是**别的设备**的令牌：不能拿它当复用凭据。"""
    d = str(tmp_path)
    a = pd.issue(d, name="A", machine="machine-a")
    b = pd.issue(d, name="B", machine="machine-b")
    again = pd.issue(d, name="A", machine="machine-a", known_token=b["token"])
    assert again["deviceId"] == a["deviceId"]
    assert again["token"] != b["token"]
    assert pd.verify(d, b["token"]) == b["deviceId"], "B 的令牌不该受牵连"


def test_different_machines_stay_separate(tmp_path):
    """两台不同的手机各自一条记录，互不覆盖。"""
    d = str(tmp_path)
    a = pd.issue(d, name="A", machine="machine-a")
    b = pd.issue(d, name="B", machine="machine-b")
    assert a["deviceId"] != b["deviceId"]
    assert len(pd.list_devices(d)) == 2


def test_no_machine_keeps_old_behavior(tmp_path):
    """老 APP 不带机器码 → 仍按旧逻辑每次新建，兼容性不能被这次改动破坏。"""
    d = str(tmp_path)
    pd.issue(d, name="legacy")
    pd.issue(d, name="legacy")
    assert len(pd.list_devices(d)) == 2


def test_machine_is_stored_as_hash_only(tmp_path):
    """机器码不能明文落盘（state 文件被看到也不该泄出设备指纹）。"""
    d = str(tmp_path)
    pd.issue(d, name="Pixel", machine="very-secret-machine-id")
    raw = open(os.path.join(d, "pair_devices.json"), encoding="utf-8").read()
    assert "very-secret-machine-id" not in raw
    assert '"m"' in raw


def test_bound_flag_marks_machine_devices(tmp_path):
    """面板靠 bound 区分"会复用"的新记录与"每次新建"的旧记录。"""
    d = str(tmp_path)
    pd.issue(d, name="bound", machine="machine-a")
    pd.issue(d, name="loose")
    flags = {it["name"]: it["bound"] for it in pd.list_devices(d)}
    assert flags == {"bound": True, "loose": False}


def test_upgrade_claims_matching_legacy_record(tmp_path):
    """迁移：升级前的老记录没有机器码，同名且唯一时应该被认领，而不是凭空多一台。

    这是用户实际会走到的路径——他现在名下就有一条 3.6.162 之前签发的记录。
    """
    d = str(tmp_path)
    old = pd.issue(d, name="V2405A")                 # 旧格式：无机器码
    new = pd.issue(d, name="V2405A", machine="machine-a")
    assert new["deviceId"] == old["deviceId"], "应该认领旧记录，而不是新建"
    assert len(pd.list_devices(d)) == 1
    assert pd.list_devices(d)[0]["bound"] is True
    assert pd.verify(d, old["token"]) is None        # 认领时轮换了令牌
    assert pd.verify(d, new["token"]) == old["deviceId"]


def test_upgrade_claims_only_when_unambiguous(tmp_path):
    """两条同名旧记录时不能猜——猜错就把别人的令牌给了这台设备。"""
    d = str(tmp_path)
    a = pd.issue(d, name="同型号")
    b = pd.issue(d, name="同型号")
    new = pd.issue(d, name="同型号", machine="machine-a")
    assert new["deviceId"] not in (a["deviceId"], b["deviceId"]), "应新建而非乱认领"
    assert len(pd.list_devices(d)) == 3


def test_upgrade_does_not_claim_different_name(tmp_path):
    """名称不同就不是同一台（用户可能是新增设备），不能认领。"""
    d = str(tmp_path)
    old = pd.issue(d, name="旧手机")
    new = pd.issue(d, name="新手机", machine="machine-a")
    assert new["deviceId"] != old["deviceId"]
    assert len(pd.list_devices(d)) == 2
