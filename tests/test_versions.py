# -*- coding: utf-8 -*-
"""多版本作品检测(3.2.4)回归测试:一级子目录分组 / 阈值 / 页序索引。"""
import os
import sys
import zipfile
from urllib.parse import quote

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402

JPG = b"\xff\xd8\xff\xe0 fake-jpg"


def _make_zip_multi(path):
    """两个版本目录(各 6 页) + 根级 1 页 + 一个 2 页的小目录(不足阈值)。"""
    with zipfile.ZipFile(str(path), "w") as z:
        z.writestr("cover.jpg", JPG)                          # 根级:不参与版本
        z.writestr("日文原版/p1.png", JPG + b"1")
        z.writestr("日文原版/p2.png", JPG + b"2")
        z.writestr("日文原版/p3.png", JPG + b"3")
        z.writestr("日文原版/p4.png", JPG + b"4")
        z.writestr("日文原版/p5.png", JPG + b"5")
        z.writestr("日文原版/p6.png", JPG + b"6")
        z.writestr("汉化版/p1.png", JPG + b"a")
        z.writestr("汉化版/p2.png", JPG + b"b")
        z.writestr("汉化版/p3.png", JPG + b"c")
        z.writestr("汉化版/p4.png", JPG + b"d")
        z.writestr("汉化版/p5.png", JPG + b"e")
        z.writestr("汉化版/p6.png", JPG + b"f")
        z.writestr("杂项/x1.jpg", JPG)                        # 仅 2 页(含 cover? 不,杂项独立)
        z.writestr("杂项/x2.jpg", JPG)


def _make_zip_single(path):
    with zipfile.ZipFile(str(path), "w") as z:
        for i in range(1, 9):
            z.writestr("p%d.jpg" % i, JPG)


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    app.state.index_loaded = False
    app.state.index = {"v": 3, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    yield root
    app.state.index_keys.clear()


def test_versions_detected_with_indexes(lib_env):
    circ = lib_env / "社团A"
    circ.mkdir()
    _make_zip_multi(circ / "[社团A] 双版本作品.zip")
    app.get_library(force=True)
    client = app.app.test_client()
    j = client.get("/api/pages?group=" + quote("社团A") + "&work=" + quote("[社团A] 双版本作品")).get_json()
    assert j["ok"] and j["total"] == 15
    vers = j["versions"]
    assert len(vers) == 2
    names = {v["name"] for v in vers}
    assert names == {"日文原版", "汉化版"}                 # （png） 后缀被剥掉
    for v in vers:
        assert len(v["idx"]) == 6
        assert v["idx"] == sorted(v["idx"])              # 绝对页序升序
    # 两组的页序不重叠;并集 = 除根级 cover.jpg 与"杂项"(2 页,低于阈值,排除)外的全部页面
    # 自然排序:cover(0) → 日文原版(1-6) → 杂项(7-8) → 汉化版(9-14)
    all_idx = sorted(vers[0]["idx"] + vers[1]["idx"])
    assert all_idx == list(range(1, 7)) + list(range(9, 15))


def test_single_folder_no_versions(lib_env):
    circ = lib_env / "社团B"
    circ.mkdir()
    _make_zip_single(circ / "[社团B] 单版本.zip")
    app.get_library(force=True)
    client = app.app.test_client()
    j = client.get("/api/pages?group=" + quote("社团B") + "&work=" + quote("[社团B] 单版本")).get_json()
    assert j["ok"] and "versions" not in j


def test_artists_latest_field(lib_env):
    circ = lib_env / "社团C"
    circ.mkdir()
    with zipfile.ZipFile(str(circ / "[社团C] 作品.zip"), "w") as z:
        z.writestr("01.jpg", JPG)
    app.get_library(force=True)
    client = app.app.test_client()
    j = client.get("/api/artists").get_json()
    assert j["ok"]
    for a in j["artists"]:
        assert "latest" in a and a["latest"] > 0
