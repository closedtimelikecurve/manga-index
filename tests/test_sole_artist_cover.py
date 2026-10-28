# -*- coding: utf-8 -*-
"""3.6.114 社团封面跟随唯一画师：绑定 / 解绑定格 / 用户覆盖优先 回归测试。

场景（文库根为临时目录，meta.db 由 conftest 隔离）：
  社A：画师甲两部小作品；社B：画师甲一部大作品 + 画师乙一部作品。
  * 绑定：社A 单画师 → 封面跟随「画师页口径」= 甲名下体积最大作品（在社B，跨社团）
  * 解绑：社A 进驻画师乙后 → 封面定格为跟随期最后的坐标，follow_artist 移除
  * 用户给社团手设 circle 覆盖 → 永远优先，不跟随
"""
import os
import sys
import zipfile

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402

JPG = b"\xff\xd8\xff\xe0 fake-jpg"


def _make_lib(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    # region_covers.json 没有 conftest 隔离——真实文件里若恰好有同名社团的覆盖记录，
    # 会触发"用户优先"分支让跟随永不生效，必须指到临时文件
    monkeypatch.setattr(app, "REGION_COVERS_FILE", str(tmp_path / "region_covers.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    app.state.index_loaded = False
    app.state.region_covers = None                    # 强制重读（打桩后的新文件）
    app.state.index = {"v": 2, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    return root


def _zip(path, pad=1024):
    with zipfile.ZipFile(str(path), "w") as z:
        z.writestr("001.jpg", JPG + b"a" * pad)


def _group(lib, name):
    return next(g for g in lib["groups"] if g["name"] == name)


def test_sole_artist_binding_follows_artist_page(tmp_path, monkeypatch):
    """单画师社团封面 = 画师页口径（甲名下体积最大作品，跨社团）；双画师社团不绑定。"""
    root = _make_lib(tmp_path, monkeypatch)
    a = root / "社A"; a.mkdir(parents=True)
    b = root / "社B"; b.mkdir()
    _zip(a / "[社A (画师甲)] 作品A1.zip")
    _zip(a / "[社A (画师甲)] 作品A2.zip")
    _zip(b / "[社B (画师甲)] 作品B1.zip", pad=65536)   # 甲名下体积最大 → 跟随坐标
    _zip(b / "[社B (画师乙)] 作品B2.zip")
    lib = app.get_library(force=True)
    ga = _group(lib, "社A")
    print("DEBUG follow:", ga.get("follow_artist"), ga.get("follow_cover"))
    print("DEBUG cover:", ga.get("cover_group"), (ga.get("cover_work") or {}).get("name"))
    print("DEBUG region:", app._region_cover_get("circle", "社A"))
    assert ga.get("follow_artist") == "画师甲"
    assert ga["cover_work"]["name"] == "[社B (画师甲)] 作品B1"
    assert ga["cover_group"] == "社B"                  # 跨社团取画师口径封面
    gb = _group(lib, "社B")
    assert gb.get("follow_artist") is None             # 双画师：不绑定
    # 下发层（/api/library）也吃到跟随结果
    client = app.app.test_client()
    d = client.get("/api/library").get_json()
    pub = next(g for g in d["groups"] if g["name"] == "社A")
    assert pub["coverWork"] == "[社B (画师甲)] 作品B1" and pub["coverGroup"] == "社B"


def test_unbind_freezes_cover_snapshot(tmp_path, monkeypatch):
    """画师乙进驻社A → 静默解绑：封面定格为跟随期最后的坐标（不跳变）；
    此后回归常规派生（重扫派生值接管）。"""
    root = _make_lib(tmp_path, monkeypatch)
    a = root / "社A"; a.mkdir(parents=True)
    b = root / "社B"; b.mkdir()
    _zip(a / "[社A (画师甲)] 作品A1.zip")
    _zip(b / "[社B (画师甲)] 作品B1.zip", pad=65536)
    app.get_library(force=True)                        # 绑定期：cover = B1
    _zip(a / "[社A (画师乙)] 作品A3.zip", pad=2048)     # 画师乙进驻（mtime 最新）
    lib = app.get_library(force=True)
    ga = _group(lib, "社A")
    assert ga.get("follow_artist") is None             # 绑定已解
    assert ga["cover_work"]["name"] == "[社B (画师甲)] 作品B1"   # 定格快照，不跳变到 A3
    lib = app.get_library(force=True)                  # 此后回归常规派生（最新作品）
    ga = _group(lib, "社A")
    assert ga["cover_work"]["name"] == "[社A (画师乙)] 作品A3"


def test_user_circle_cover_beats_following(tmp_path, monkeypatch):
    """用户给社团手设的封面永远优先于跟随。"""
    root = _make_lib(tmp_path, monkeypatch)
    a = root / "社A"; a.mkdir(parents=True)
    b = root / "社B"; b.mkdir()
    _zip(a / "[社A (画师甲)] 作品A1.zip")
    _zip(a / "[社A (画师甲)] 作品A2.zip")
    _zip(b / "[社B (画师甲)] 作品B1.zip", pad=65536)
    app.get_library(force=True)                        # 先形成绑定
    client = app.app.test_client()
    r = client.post("/api/set-cover", json={
        "scope": "circle", "name": "社A",
        "group": "社A", "work": "[社A (画师甲)] 作品A2"})
    assert r.status_code == 200, r.get_json()
    lib = app.get_library(force=True)
    ga = _group(lib, "社A")
    assert ga["cover_work"]["name"] == "[社A (画师甲)] 作品A2"   # 用户覆盖优先
    assert ga.get("follow_artist") is None             # 不再跟随（用户接管）
