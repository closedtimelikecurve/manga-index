# -*- coding: utf-8 -*-
"""3.6.11 社团别名（笔名别名的同构扩展）回归测试。

覆盖：
  * 别名社团不再单列，其作品并入正名社团
  * 并入的作品仍带**真实 path**（作品 key 不变 → 阅读进度/收藏不受影响）
  * 两边目录都存在时按 path 去重，不会重复计数
  * 删除别名即撤销（社团重新各自单列）
  * /api/author-aliases 的 kind=circle 与 kind=author 互不串台
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


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    monkeypatch.setitem(app.CFG, "circle_aliases", {})
    app.state.index_loaded = False
    app.state.index = {"v": 3, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    yield root
    app.state.index_keys.clear()


def _zip(path, pages=2):
    with zipfile.ZipFile(str(path), "w") as z:
        for i in range(1, pages + 1):
            z.writestr("%02d.jpg" % i, JPG)


def _names(lib):
    return sorted(g["name"] for g in lib["groups"])


def test_circle_alias_absorbs_works(lib_env):
    (lib_env / "社团A").mkdir()
    _zip(lib_env / "社团A" / "[社团A] 作品一.zip")
    (lib_env / "社团B").mkdir()
    _zip(lib_env / "社团B" / "[社团B] 作品二.zip")
    assert _names(app.get_library(force=True)) == ["社团A", "社团B"]

    app.get_library(force=True)
    meta_store.upsert_alias("社团B", "社团A", "circle")
    lib = app.get_library(force=True)
    assert _names(lib) == ["社团A"], "别名社团不该再单列"
    ga = lib["groups"][0]
    assert len(ga["works"]) == 2
    # 并入的作品仍指向真实所在目录 → 打开/删除/续读照旧（key 不变）
    paths = {w["path"] for w in ga["works"]}
    assert any("社团B" in p for p in paths), paths
    assert any("社团A" in p for p in paths), paths
    # 元数据库里作品二仍归属**真实**社团：key 不随展示归并而变（阅读进度不丢）
    # 注意：_connect() 返回的是模块级共享连接，**不要 close**（关了后面全部操作都会炸）
    con = meta_store._connect()
    keys = sorted(r[0] for r in con.execute("SELECT key FROM works"))
    assert keys == ["社团A/[社团A] 作品一", "社团B/[社团B] 作品二"], keys

    # 撤销：删除别名后两个社团各自恢复
    meta_store.delete_alias("社团B", "circle")
    assert _names(app.get_library(force=True)) == ["社团A", "社团B"]


def test_circle_alias_dedups_when_both_exist(lib_env):
    """正名目录里已有同名作品时不重复计数（按 path 去重）。"""
    (lib_env / "社团A").mkdir()
    _zip(lib_env / "社团A" / "[社团A] 作品一.zip")
    (lib_env / "社团B").mkdir()
    _zip(lib_env / "社团B" / "[社团B] 作品二.zip")
    app.get_library(force=True)
    meta_store.upsert_alias("社团B", "社团A", "circle")
    lib = app.get_library(force=True)
    ga = lib["groups"][0]
    assert len(ga["works"]) == 2
    # 再扫一轮不该越加越多
    lib2 = app.get_library(force=True)
    assert len(lib2["groups"][0]["works"]) == 2
    meta_store.delete_alias("社团B", "circle")


def test_alias_api_kinds_dont_mix(lib_env):
    c = app.app.test_client()
    r = c.post("/api/author-aliases", json={"alias": "别名社团", "canonical": "正名社团",
                                            "kind": "circle"}).get_json()
    assert r["ok"] is True, r
    j = c.get("/api/author-aliases?kind=circle").get_json()
    assert j["aliases"].get("别名社团") == "正名社团"
    assert j["kind"] == "circle"
    # 笔名别名里不该出现这条
    j2 = c.get("/api/author-aliases?kind=author").get_json()
    assert "别名社团" not in j2["aliases"]
    # 反向：笔名登记不进社团表
    c.post("/api/author-aliases", json={"alias": "旧笔名", "canonical": "正名画师",
                                        "kind": "author"})
    assert "旧笔名" not in c.get("/api/author-aliases?kind=circle").get_json()["aliases"]
    # 删除按 kind 分流
    r = c.post("/api/author-aliases/delete", json={"alias": "别名社团", "kind": "circle"}).get_json()
    assert r["ok"] is True, r
    assert "别名社团" not in c.get("/api/author-aliases?kind=circle").get_json()["aliases"]
