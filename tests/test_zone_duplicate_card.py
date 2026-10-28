# -*- coding: utf-8 -*-
"""3.6.31「原作分区内同一作品出现两张卡片」回归测试。

报障：原作分区内会看到同一部作品有两张作品卡。

根因：3.7.4 的 `_build_coop_groups` 让**合作社团**（文件名 [A、B] / [A,B] 拆出
circles≥2）的作品**同时挂进 A 与 B 两个社团**做交叉引用。而 `/api/works`（标签/原作
分区页数据源）的实现是"遍历所有社团 → 命中标签就 append 一条"，于是同一部作品被
计两次 → 界面上两张一模一样的卡。`/api/search` 同款问题。

覆盖：
  * 合作作品挂原作标签 → /api/works 只出现一条
  * authorCircles 计数与卡片数一致（不能"1 张卡、分布显示 2"）
  * /api/search 同样不重复
  * 非合作作品行为不变（防回归）
"""
import itertools
import os
import sys
import zipfile

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402

JPG = b"\xff\xd8\xff\xe0 fake-jpg"
ZONE = "FateGrand Order"      # 内置原作名，文件名括号字面命中即产标签


def _make_zip(path, pages=3):
    with zipfile.ZipFile(str(path), "w") as z:
        for i in range(1, pages + 1):
            z.writestr(zipfile.ZipInfo("%03d.jpg" % i, date_time=(2020, 1, 1, 0, 0, 0)),
                       JPG + bytes([i]))


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    built = app._dp.load_originals(None)
    monkeypatch.setitem(app.CFG, "originals", [])
    monkeypatch.setattr(app.state, "originals", built[0])
    monkeypatch.setattr(app.state, "norm_to_canon", dict(built[1]))
    monkeypatch.setattr(app._dp, "NORM_TO_CANON", dict(built[1]))
    app.state.index_loaded = False
    app.state.index = {"v": 3, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    yield root


def test_coop_work_appears_once_in_tag_works(lib_env):
    """核心：合作作品在原作分区里只能有一张卡。"""
    circ = lib_env / "[社团A、社团B]"
    circ.mkdir()
    _make_zip(circ / ("[社团A、社团B] 合作本 (%s).zip" % ZONE))
    lib = app.get_library(force=True)
    # 前置校验：确实被交叉引用到了两个社团下（否则这测试没测到点子上）
    hosts = [g["name"] for g in lib["groups"]
             if any(n == ZONE for _t, n in
                    itertools.chain.from_iterable(w["tags"] for w in g["works"]))]
    assert len(hosts) >= 2, ("未能构造出交叉引用场景（合作社团解析未生效），"
                             "实际挂载社团：%s" % hosts)

    client = app.app.test_client()
    data = client.get("/api/works?type=original&tag=" + ZONE.replace(" ", "%20")).get_json()
    works = data["works"]
    names = [it["work"]["name"] for it in works]
    assert len(works) == 1, "同一部合作作品出现了 %d 次：%s" % (len(works), names)
    # 且 authorCircles 的计数总和必须与卡片数一致
    assert sum(c["count"] for c in data["authorCircles"]) == 1


def test_coop_work_appears_once_in_search(lib_env):
    circ = lib_env / "[社团A、社团B]"
    circ.mkdir()
    _make_zip(circ / ("[社团A、社团B] 唯一关键词合作本 (%s).zip" % ZONE))
    app.get_library(force=True)
    client = app.app.test_client()
    data = client.get("/api/search?q=唯一关键词合作本").get_json()
    names = [it["work"]["name"] for it in data["works"]]
    assert names.count(names[0]) == 1, "搜索结果里同一作品重复：%s" % names


def test_plain_work_unchanged(lib_env):
    """非合作作品：行为不变，别把正常的跨社团浏览去重坏了。"""
    d1 = lib_env / "社团X"
    d1.mkdir()
    _make_zip(d1 / ("[社团X] 作品一 (%s).zip" % ZONE))
    d2 = lib_env / "社团Y"
    d2.mkdir()
    _make_zip(d2 / ("[社团Y] 作品二 (%s).zip" % ZONE))
    app.get_library(force=True)
    client = app.app.test_client()
    data = client.get("/api/works?type=original&tag=" + ZONE.replace(" ", "%20")).get_json()
    names = sorted(it["work"]["name"] for it in data["works"])
    assert len(names) == 2, names
    assert sum(c["count"] for c in data["authorCircles"]) == 2
