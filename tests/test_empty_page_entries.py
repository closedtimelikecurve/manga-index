# -*- coding: utf-8 -*-
"""3.6.31「空条目不是有效页」回归测试。

报障：作品「[アオヒモファミリア (あおひも)] クラスメイトにノリで中出しすなーっ! 2
【白杨汉化组】 [DL版]」出现部分页加载失效。

实测该包：44 个条目里有 **13 个是 0 字节**（0005/0006/0008/0014/0015/0019/0022/
0027/0028/0030/0031/0035/0043.webp）——源文件转录时缺页，被写成了同名空条目。
此前 list_zip_images 只按扩展名过滤，这些空条目被当成有效页计入页数 →
阅读器翻到它们读不出内容；若首页是空条目，封面也会取到一张读不出来的图。

覆盖：
  * zip / rar：0 字节条目不计入页数
  * 首页为 0 字节时封面自动落到下一个非空页（此前封面会失效）
  * 全部为空 → 无封面、0 页
  * 文件夹型作品：磁盘上的 0 字节图片同样排除（与压缩包同口径）
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


def _make_zip_with_holes(path, pages=6, holes=()):
    """造一个压缩包：holes 里的页号写成 0 字节条目。"""
    with zipfile.ZipFile(str(path), "w") as z:
        for i in range(1, pages + 1):
            name = "%03d.jpg" % i
            zi = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            # 目录条目（'/'）混在里面是不相干的干扰项，必须被忽略
            z.writestr(zi, b"" if i in holes else JPG + bytes([i]))


# ---------- list_zip_images：0 字节不算页 ----------

def test_zip_zero_byte_entries_excluded(tmp_path):
    p = tmp_path / "w.zip"
    _make_zip_with_holes(p, pages=6, holes=(2, 4, 5))
    names = app.list_zip_images(str(p))
    assert names == ["001.jpg", "003.jpg", "006.jpg"]


def test_zip_all_pages_valid_unchanged(tmp_path):
    """无空条目时行为不变（防回归：别把正常包也过滤坏了）。"""
    p = tmp_path / "w.zip"
    _make_zip_with_holes(p, pages=4, holes=())
    assert app.list_zip_images(str(p)) == ["001.jpg", "002.jpg", "003.jpg", "004.jpg"]


def test_zip_empty_file_is_noop(tmp_path):
    """坏包 / 不存在的文件 → 空列表，不抛异常。"""
    assert app.list_zip_images(str(tmp_path / "missing.zip")) == []


# ---------- 页数与封面：端到端走 make_work ----------

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


def test_work_page_count_skips_empty_entries(lib_env):
    circ = lib_env / "社团A"
    circ.mkdir()
    _make_zip_with_holes(circ / "[社团A] 缺页作品.zip", pages=6, holes=(2, 4, 5))
    lib = app.get_library(force=True)
    g = next(g for g in lib["groups"] if g["name"] == "社团A")
    w = g["works"][0]
    assert w["pages"] == 3, "0 字节条目不应计入页数"
    assert [pg["n"] for pg in w["page_files"]] == ["001.jpg", "003.jpg", "006.jpg"]


def test_cover_skips_empty_first_page(lib_env):
    """首页是 0 字节 → 封面必须落到下一个非空页（此前会取到读不出来的图）。"""
    circ = lib_env / "社团A"
    circ.mkdir()
    _make_zip_with_holes(circ / "[社团A] 首页为空.zip", pages=4, holes=(1, 2))
    lib = app.get_library(force=True)
    g = next(g for g in lib["groups"] if g["name"] == "社团A")
    w = g["works"][0]
    assert w["pages"] == 2
    assert w["cover"] is not None and w["cover"][2] == "003.jpg"


def test_all_pages_empty_no_cover(lib_env):
    circ = lib_env / "社团A"
    circ.mkdir()
    _make_zip_with_holes(circ / "[社团A] 全空.zip", pages=3, holes=(1, 2, 3))
    lib = app.get_library(force=True)
    g = next(g for g in lib["groups"] if g["name"] == "社团A")
    w = g["works"][0]
    assert w["pages"] == 0
    assert w["cover"] is None


# ---------- 文件夹型作品：同口径 ----------

def test_folder_work_skips_empty_image_files(lib_env):
    circ = lib_env / "社团A"
    work = circ / "[社团A] 散页作品"
    work.mkdir(parents=True)
    (work / "001.jpg").write_bytes(JPG + b"1")
    (work / "002.jpg").write_bytes(b"")          # 0 字节：不是有效页
    (work / "003.jpg").write_bytes(JPG + b"3")
    lib = app.get_library(force=True)
    g = next(g for g in lib["groups"] if g["name"] == "社团A")
    w = g["works"][0]
    assert w["pages"] == 2
    assert os.path.basename(w["cover"][1]) == "001.jpg"
