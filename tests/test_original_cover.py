# -*- coding: utf-8 -*-
"""3.6.19「原作分区设为封面」回归测试。

背景：区域封面分三桶（circles / artists / originals）落盘在 region_covers.json，
但 _region_covers_load() 只解析了 circles 与 artists 两个桶 —— originals 桶虽然能被
写进去（APP 端长按作品「设为分区封面」走的是 scope=original），面板一重启就读不
回来，用户看到的就是"设了封面但没生效 / 过一会儿又变回去了"。

覆盖：
  * /api/set-cover scope=original 写入后，/api/originals 立即可见覆盖
  * 覆盖能从**磁盘**恢复（模拟面板重启：清空进程内缓存后仍能读到）
  * /api/clear-cover scope=original 能清除覆盖并回退派生封面
  * 三个桶互不串扰（社团/画师/原作同名互不覆盖）
"""
import os
import sys
import zipfile

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
import meta_store  # noqa: E402

JPG = b"\xff\xd8\xff\xe0 fake-jpg"
# 内置原作名（djc_parse.DEFAULT_ORIGINALS 有 FateGrand Order），文件名括号字面命中
# 即产出 original 标签 —— 无需依赖 config 词条库，测试不受真实词条库影响。
ZONE = "FateGrand Order"
G1, G2 = "社团A (画师甲)", "社团B"
# 作品名 = 文件名去扩展名（含社团前缀），与 find_work 的口径一致
W1 = "[社团A (画师甲)] 作品一 (FateGrand Order)"
W2 = "[社团B] 作品二 (FateGrand Order)"


def _make_zip(path, pages=3):
    with zipfile.ZipFile(str(path), "w") as z:
        for i in range(1, pages + 1):
            z.writestr("%03d.jpg" % i, JPG)


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    # 词条库全局态：用纯内置名单重建，不复制进程启动态（避免真实 config 词条污染）
    built = app._dp.load_originals(None)
    monkeypatch.setitem(app.CFG, "originals", [])
    monkeypatch.setattr(app.state, "originals", built[0])
    monkeypatch.setattr(app.state, "norm_to_canon", dict(built[1]))
    monkeypatch.setattr(app._dp, "NORM_TO_CANON", dict(built[1]))
    app.state.index_loaded = False
    app.state.index = {"v": 3, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    # 区域封面：重定向到临时目录 + 清空进程内缓存（每个测试都从"冷启动"开始）
    monkeypatch.setattr(app, "REGION_COVERS_FILE", str(tmp_path / "region_covers.json"))
    monkeypatch.setattr(app.state, "region_covers", None)
    yield root


def _seed(lib_env):
    """两个社团各一部作品，同挂在 ZONE 原作分区下（用于验证覆盖切换）。"""
    c1 = lib_env / G1
    c1.mkdir()
    _make_zip(c1 / (W1 + ".zip"))
    c2 = lib_env / G2
    c2.mkdir()
    _make_zip(c2 / (W2 + ".zip"))
    app.get_library(force=True)


def _zone(covers, name=ZONE):
    return next((z for z in covers if z["name"] == name), None)


# ---------- 覆盖写入后立即可见 ----------

def test_original_set_cover_applies(lib_env):
    _seed(lib_env)
    client = app.app.test_client()
    r = client.post("/api/set-cover", json={"scope": "original", "name": ZONE,
                                            "group": G1, "work": W1})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["ok"] is True
    # 派生封面取「体积最大」，两部一样大时不定；显式覆盖后必须稳定指向 W1
    data = client.get("/api/originals").get_json()
    z = _zone(data["originals"])
    assert z is not None
    assert (z["cover_group"], z["cover_work"]) == (G1, W1)


# ---------- 覆盖能从磁盘恢复（模拟面板重启）—— 本次修复的核心 ----------

def test_original_cover_survives_reload(lib_env):
    _seed(lib_env)
    client = app.app.test_client()
    assert client.post("/api/set-cover", json={"scope": "original", "name": ZONE,
                                               "group": G1, "work": W1}).get_json()["ok"] is True
    # 清空进程内缓存：下一次读取只能从 region_covers.json 恢复（等价面板重启）
    app.state.region_covers = None

    assert app._region_cover_get("original", ZONE) == (G1, W1)
    # 且渲染路径仍然生效（_apply_original_cover 依赖 _resolve_region_cover）
    data = client.get("/api/originals").get_json()
    z = _zone(data["originals"])
    assert (z["cover_group"], z["cover_work"]) == (G1, W1)


# ---------- 磁盘上三个桶都要解析，不能只认 circles/artists ----------

def test_all_buckets_load_from_disk(lib_env, tmp_path):
    cov = tmp_path / "region_covers.json"
    cov.write_text(
        '{"circles": {"C": ["gc", "wc"]},'
        ' "artists": {"A": ["ga", "wa"]},'
        ' "originals": {"O": ["go", "wo"]}}',
        encoding="utf-8")
    app.state.region_covers = None
    assert app._region_cover_get("circle", "C") == ("gc", "wc")
    assert app._region_cover_get("artist", "A") == ("ga", "wa")
    assert app._region_cover_get("original", "O") == ("go", "wo")


def test_invalid_entries_dropped_on_load(lib_env, tmp_path):
    """脏数据防御：非 list / 长度非 2 / 非字符串一律丢弃，不污染运行时。"""
    cov = tmp_path / "region_covers.json"
    cov.write_text(
        '{"originals": {"ok": ["g", "w"], "bad1": "gw",'
        ' "bad2": ["g"], "bad3": ["g", "w", "x"], "bad4": [1, 2]}}',
        encoding="utf-8")
    app.state.region_covers = None
    assert app._region_cover_get("original", "ok") == ("g", "w")
    for bad in ("bad1", "bad2", "bad3", "bad4"):
        assert app._region_cover_get("original", bad) is None


# ---------- 清除覆盖，回退派生封面 ----------

def test_original_clear_cover_reverts(lib_env):
    _seed(lib_env)
    client = app.app.test_client()
    # 先覆盖到 W1，再清除 → 回到派生封面（这里两部作品一样大，取其中之一即可）
    assert client.post("/api/set-cover", json={"scope": "original", "name": ZONE,
                                               "group": G1, "work": W1}).get_json()["ok"] is True
    assert client.get("/api/originals").get_json()["originals"][0]["cover_work"] == W1
    r = client.post("/api/clear-cover", json={"scope": "original", "name": ZONE})
    assert r.get_json()["ok"] is True
    app.state.region_covers = None
    assert app._region_cover_get("original", ZONE) is None


# ---------- 同名不同桶互不串扰 ----------

def test_buckets_do_not_leak(lib_env):
    _seed(lib_env)
    client = app.app.test_client()
    # 同一个名字 "同名" 在三个桶里各存一份，取的时候必须各回各家
    app._region_cover_set("circle", "同名", "gc", "wc")
    app._region_cover_set("artist", "同名", "ga", "wa")
    app._region_cover_set("original", "同名", "go", "wo")
    app.state.region_covers = None
    assert app._region_cover_get("circle", "同名") == ("gc", "wc")
    assert app._region_cover_get("artist", "同名") == ("ga", "wa")
    assert app._region_cover_get("original", "同名") == ("go", "wo")


# ---------- 覆盖只在作品仍存在且有首图时生效 ----------

def test_original_cover_falls_back_when_work_gone(lib_env):
    """覆盖指向的作品已不存在 → 自动回退派生封面（不显示空图）。"""
    _seed(lib_env)
    app._region_cover_set("original", ZONE, "不存在的社团", "不存在的作品")
    app.state.region_covers = None
    assert app._resolve_region_cover("original", ZONE) is None
    client = app.app.test_client()
    z = _zone(client.get("/api/originals").get_json()["originals"])
    assert z["cover_work"]          # 仍是派生封面，非空


# ---------- 覆盖随分区改名 / 移除一起走（不留残骸） ----------

def test_original_cover_follows_zone_rename(lib_env):
    """分区改名后，用户设的封面必须跟着到新名；旧名记录清掉。"""
    _seed(lib_env)
    client = app.app.test_client()
    assert client.post("/api/set-cover", json={"scope": "original", "name": ZONE,
                                               "group": G1, "work": W1}).get_json()["ok"] is True
    r = client.post("/api/originals/rename", json={"from": ZONE, "to": "新分区名XYZ"})
    assert r.get_json()["ok"] is True, r.get_json()

    app.state.region_covers = None
    assert app._region_cover_get("original", ZONE) is None                # 旧名无残留
    assert app._region_cover_get("original", "新分区名XYZ") == (G1, W1)     # 新名继承

    z = _zone(client.get("/api/originals").get_json()["originals"], "新分区名XYZ")
    assert z is not None                                                  # 新分区确实存在
    assert (z["cover_group"], z["cover_work"]) == (G1, W1)                  # 且封面已继承


def test_original_cover_cleared_on_zone_remove(lib_env):
    """移除分区 → 它的封面覆盖记录一并清除（否则同名分区重建时会意外继承旧封面）。"""
    _seed(lib_env)
    client = app.app.test_client()
    assert client.post("/api/set-cover", json={"scope": "original", "name": ZONE,
                                               "group": G2, "work": W2}).get_json()["ok"] is True
    r = client.post("/api/originals/remove", json={"term": ZONE})
    assert r.get_json()["ok"] is True, r.get_json()

    app.state.region_covers = None
    assert app._region_cover_get("original", ZONE) is None
