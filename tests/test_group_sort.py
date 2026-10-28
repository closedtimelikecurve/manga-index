# -*- coding: utf-8 -*-
"""社团排序回归测试：三种维度（最近入库 / 创建时间 / 作品数量）+ 倒序。

网页与 APP 都按同一套语义在本地排序（切换即时生效，不重新请求），
服务端 /api/library?sort=&order= 走 sort_groups()，两边规则必须一致 ——
这里把服务端那半钉死（字段名、默认值、正倒序、同值补位、非法参数回退）。
"""
import os
import sys
import time
import zipfile

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402

# 都用过去的时间戳（1.6e9≈2020-09 / 1.7e9≈2023-11 / 1.75e9≈2025-06），避免造出"未来"时间干扰判断
T_OLD, T_MID, T_NEW = 1_600_000_000, 1_700_000_000, 1_750_000_000


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """三个社团：甲社 1 部（最旧）、乙社 3 部（中间）、丙社 2 部（最新）。"""
    root = tmp_path / "lib"
    root.mkdir()

    def mkgroup(name, n, mtime):
        d = root / name
        d.mkdir()
        for i in range(1, n + 1):
            p = d / f"[{name}] 作品{i}.zip"
            with zipfile.ZipFile(str(p), "w") as z:
                z.writestr("01.jpg", b"\xff\xd8 fake")
            os.utime(p, (mtime, mtime))       # 控制"最近入库"时间
        return d

    mkgroup("甲社", 1, T_OLD)
    mkgroup("乙社", 3, T_MID)
    mkgroup("丙社", 2, T_NEW)

    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    monkeypatch.setitem(app.CFG, "dissolved_circles", [])
    app.state.index_loaded = False
    app.state.index = {"v": 2, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    yield {"root": root}
    app.state.index_keys.clear()


def _names(payload):
    return [g["name"] for g in payload["groups"]]


def test_groups_expose_sort_fields(env):
    """排序依赖的三个字段必须真实可用：createdAt / updatedAt / workCount。
    注意 updatedAt 的语义是「最近**入库新作品**」，与作品内容的 coverMtime 是两码事：
    首次扫描时 DB 里还没有 added_at，初始化退回作品内容时间（不是档案创建时间——
    目录 ctime 只反映"这层文件夹什么时候建的"，导入新作品不会推进它，详见
    test_group_arrival.py 的 test_seed_uses_db_added_at_not_dir_created）。"""
    app.get_library(force=True)
    c = app.app.test_client()
    j = c.get("/api/library").get_json()
    gs = {g["name"]: g for g in j["groups"]}
    assert set(gs) == {"甲社", "乙社", "丙社"}
    for name, g in gs.items():
        assert g["createdAt"] > 0, name                       # 档案创建时间（目录 ctime）
        assert g["updatedAt"] == g["coverMtime"], name         # 首扫：退回作品内容时间
    assert gs["甲社"]["workCount"] == 1 and gs["乙社"]["workCount"] == 3
    # 内容最新时间是另一个字段（封面/"最新：X" 用），夹具里被显式设成了 T_OLD/T_NEW
    assert int(gs["甲社"]["coverMtime"]) == T_OLD
    assert int(gs["丙社"]["coverMtime"]) == T_NEW


def test_library_sort_modes_and_direction(env):
    """三种维度 × 正倒序的实际次序。入库时间显式种入状态，避免依赖"目录 ctime 的先后"。"""
    app.get_library(force=True)
    c = app.app.test_client()
    app.state.index["groups"] = {"甲社": {"n": 1, "at": T_OLD},
                            "乙社": {"n": 3, "at": T_MID},
                            "丙社": {"n": 2, "at": T_NEW}}
    app.get_library(force=True)

    # 默认：按最近入库新作品的时间，由新到旧
    assert _names(c.get("/api/library").get_json()) == ["丙社", "乙社", "甲社"]

    # 作品数量：由多到少 / 倒序由少到多
    assert _names(c.get("/api/library?sort=count&order=desc").get_json()) == ["乙社", "丙社", "甲社"]
    assert _names(c.get("/api/library?sort=count&order=asc").get_json()) == ["甲社", "丙社", "乙社"]

    # 最近入库：两向
    assert _names(c.get("/api/library?sort=updated&order=desc").get_json()) == ["丙社", "乙社", "甲社"]
    assert _names(c.get("/api/library?sort=updated&order=asc").get_json()) == ["甲社", "乙社", "丙社"]

    # 创建时间：两向的键必须各自单调。3.6.154 起时间档**按整秒比较**（同一秒内按名称升序），
    # 所以单调性要在整秒粒度上看——夹具的目录是同一次 mkdir 出来的，彼此只差几毫秒。
    asc = [g["createdAt"] for g in c.get("/api/library?sort=created&order=asc").get_json()["groups"]]
    desc = [g["createdAt"] for g in c.get("/api/library?sort=created&order=desc").get_json()["groups"]]
    asc_s = [round(v) for v in asc]
    desc_s = [round(v) for v in desc]
    assert asc_s == sorted(asc_s)
    assert desc_s == sorted(desc_s, reverse=True)


def test_sort_params_validation_and_echo(env):
    """非法 sort/order 回退到默认（updated desc），并把生效值回显出来。"""
    app.get_library(force=True)
    c = app.app.test_client()
    j = c.get("/api/library?sort=bogus&order=bogus").get_json()
    assert j["sort"] == "updated" and j["order"] == "desc"
    assert _names(j) == ["丙社", "乙社", "甲社"]
    j2 = c.get("/api/library?sort=count&order=ASC").get_json()      # 大小写不敏感
    assert j2["order"] == "asc"


def test_sort_groups_tiebreak_by_name():
    """同值（含倒序）时按名称升序补位 —— 列表不会在刷新之间跳动。"""
    groups = [
        {"name": "乙", "works": [1, 2], "cover_mtime": 5.0, "created_at": 1.0},
        {"name": "甲", "works": [1, 2], "cover_mtime": 5.0, "created_at": 1.0},
        {"name": "丙", "works": [1, 2], "cover_mtime": 5.0, "created_at": 1.0},
    ]
    # 三种维度、两个方向下，值全相同 → 一律退化为名称升序
    for order in ("desc", "asc"):
        for mode in ("updated", "created", "count"):
            got = [g["name"] for g in app.sort_groups(groups, mode, order)]
            assert got == sorted(got), (mode, order, got)


def test_virtual_group_created_at_from_works(env):
    """虚拟社团（根目录散包）没有目录，创建时间取作品文件的创建时间（不是文件 mtime）。"""
    root = env["root"]
    p = root / "[散包社] 单独作品.zip"
    with zipfile.ZipFile(str(p), "w") as z:
        z.writestr("01.jpg", b"\xff\xd8 fake")
    os.utime(p, (T_OLD, T_OLD))          # 只能改 mtime：Windows 上 st_ctime 即创建时间，不可改
    app.get_library(force=True)
    c = app.app.test_client()
    gs = {g["name"]: g for g in c.get("/api/library").get_json()["groups"]}
    assert "散包社" in gs
    # 内容最新 = 我们显式设的 T_OLD；首扫时 DB 还没有 added_at，初始化就退回内容时间
    assert int(gs["散包社"]["coverMtime"]) == T_OLD
    assert gs["散包社"]["updatedAt"] == T_OLD
    # 创建时间是文件落盘时间（刚建的）——和"最近入库"已经彻底分开了（3.6.151 修的就是这个）
    assert abs(gs["散包社"]["createdAt"] - time.time()) < 86_400
    assert int(gs["散包社"]["createdAt"]) != T_OLD
    assert gs["散包社"]["workCount"] == 1


def test_touched_mode_is_gone_and_falls_back_to_updated(env):
    """3.6.151：`touched`（最近更新）档已**彻底删除**。

    用户要求删掉：它与「最近入库」只差"洗版算不算"，两档并排反而分不清。
    但旧网页缓存 / 旧 APP 仍可能带上 sort=touched，所以服务端必须按 updated 处理
    （不能让参数非法回退成别的顺序，也不能崩）。
    """
    app.get_library(force=True)
    c = app.app.test_client()
    # 把甲社（1 部、mtime 最旧）的文件"洗版"成最新：数量不变，只有 mtime 变
    p = env["root"] / "甲社" / "[甲社] 作品1.zip"
    os.utime(p, (T_NEW + 100, T_NEW + 100))
    app.get_library(force=True)

    touched = _names(c.get("/api/library?sort=touched&order=desc").get_json())
    updated = _names(c.get("/api/library?sort=updated&order=desc").get_json())
    assert touched == updated, "touched 没有回退成 updated，旧缓存会排出别的顺序"
    # updated 不动（数量没增加）——甲社仍不在第一，两档语义确实不同
    assert _names(c.get("/api/library?sort=updated&order=desc").get_json())[0] != "甲社"
