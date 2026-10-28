# -*- coding: utf-8 -*-
"""删除作品首页图片（压缩包层面）回归测试。"""
import io
import os
import sys
import zipfile

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402

JPG = b"\xff\xd8\xff\xe0 fake-jpg-bytes"


def _make_lib(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    circ = root / "社团D"
    circ.mkdir(parents=True)
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    app.state.index_loaded = False
    app.state.index = {"v": 2, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    return root, circ


@pytest.fixture()
def zip_work(tmp_path, monkeypatch):
    root, circ = _make_lib(tmp_path, monkeypatch)
    zpath = circ / "[社团D] 作品D.zip"
    with zipfile.ZipFile(str(zpath), "w") as z:
        z.writestr("cover.jpg", JPG)
        z.writestr("p2.jpg", JPG)
        z.writestr("p3.jpg", JPG)
    yield zpath
    app.state.index_keys.clear()


def test_delete_cover_removes_first_page(zip_work):
    client = app.app.test_client()
    r = client.post("/api/delete-cover", json={"group": "社团D", "work": "[社团D] 作品D"})
    assert r.status_code == 200, r.get_json()
    with zipfile.ZipFile(str(zip_work)) as z:
        names = z.namelist()
    assert "cover.jpg" not in names
    assert "p2.jpg" in names and "p3.jpg" in names
    # 重扫后封面自动变为原第二页、页数 -1
    lib = app.get_library(force=True)
    g = next(g for g in lib["groups"] if g["name"] == "社团D")
    w = next(w for w in g["works"] if w["name"] == "[社团D] 作品D")
    assert w["pages"] == 2
    assert w["cover"][0] == "zip" and w["cover"][2] == "p2.jpg"


def test_delete_cover_added_at_stable(zip_work):
    """3.6.111 回归钉：删首图推进 works.mtime，但 added_at（首次入库时间）不动——
    分区内"新→旧"排序键（APP 3.7.69 起）改用 added_at，修改过的作品不得顶到"最新"。"""
    lib0 = app.get_library(force=True)
    w0 = next(w for g in lib0["groups"] if g["name"] == "社团D"
              for w in g["works"] if w["name"] == "[社团D] 作品D")
    assert w0["added_at"] > 0                          # 首扫回填自 mtime
    client = app.app.test_client()
    r = client.post("/api/delete-cover", json={"group": "社团D", "work": "[社团D] 作品D"})
    assert r.status_code == 200
    lib = app.get_library(force=True)
    w = next(w for g in lib["groups"] if g["name"] == "社团D"
             for w in g["works"] if w["name"] == "[社团D] 作品D")
    assert w["mtime"] >= w0["mtime"]                   # 文件被重写 → mtime 推进
    assert w["added_at"] == w0["added_at"]             # 入库时间不变（排序不被顶）


def test_public_work_payload_has_added_at(zip_work):
    client = app.app.test_client()
    app.get_library(force=True)
    d = client.get("/api/circle/社团D").get_json()
    ws = d.get("works") or []
    assert ws and all("added_at" in w for w in ws)


def test_delete_cover_rejects_single_page_work(tmp_path, monkeypatch):
    root, circ = _make_lib(tmp_path, monkeypatch)
    with zipfile.ZipFile(str(circ / "[社团D] 单页.zip"), "w") as z:
        z.writestr("only.jpg", JPG)
    client = app.app.test_client()
    r = client.post("/api/delete-cover", json={"group": "社团D", "work": "[社团D] 单页"})
    assert r.status_code == 400
    assert "仅剩 1 页" in r.get_json()["message"]


def test_delete_cover_rejects_folder_work(tmp_path, monkeypatch):
    root, circ = _make_lib(tmp_path, monkeypatch)
    folder = circ / "散图作品"
    folder.mkdir()
    (folder / "cover.jpg").write_bytes(JPG)
    (folder / "p2.jpg").write_bytes(JPG)
    client = app.app.test_client()
    r = client.post("/api/delete-cover", json={"group": "社团D", "work": "散图作品"})
    assert r.status_code == 400
    assert "仅支持压缩包作品" in r.get_json()["message"]
    assert (folder / "cover.jpg").exists()


def test_delete_cover_rejects_unknown_work(tmp_path, monkeypatch):
    _make_lib(tmp_path, monkeypatch)
    client = app.app.test_client()
    r = client.post("/api/delete-cover", json={"group": "社团D", "work": "不存在"})
    assert r.status_code == 404


def test_delete_cover_preserves_other_entries(zip_work):
    """非图片条目（info.txt）与压缩包注释必须原样保留。"""
    with zipfile.ZipFile(str(zip_work), "a") as z:
        z.writestr("sub/info.txt", "hello")
        z.comment = "lib-comment".encode("utf-8")
    app.state.lib["data"] = None                       # 让重扫感知新条目
    client = app.app.test_client()
    r = client.post("/api/delete-cover", json={"group": "社团D", "work": "[社团D] 作品D"})
    assert r.status_code == 200
    with zipfile.ZipFile(str(zip_work)) as z:
        assert z.read("sub/info.txt") == b"hello"
        assert z.comment == "lib-comment".encode("utf-8")
        assert z.read("p3.jpg") == JPG
