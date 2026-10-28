# -*- coding: utf-8 -*-
"""3.6.13 find_work 按 key owner 兜底：修复画师页/续读/收藏打不开「目录名≠圈子名」的作品。

背景（用户实测反馈）：3.6.12 起分组按**圈子名**归组，但作品 key 仍锚**真实目录**（_group）。
于是作品的展示群组名（circle，如 TOZAN_BU）可能≠其 key 的 owner（真实目录，如「富士やま」）。
社团浏览页按圈子名寻址没问题；但**画师档案页 / 续读 / 收藏**是按作品 key 的 owner
（works.group_name = 目录名）寻址的，find_work(富士やま, 作品名) 因没有名为「富士やま」的
群组而落空 → 这批作品在移动端（及网页画师页）一律 404 打不开。

修复：find_work 展示群组查不到时，按「目录名/作品名」（即作品真实 key）跨群组反查兜底。

覆盖：
  * 目录名≠圈子名时，圈子名寻址（社团浏览）与目录名寻址（画师页/续读/收藏）都能打开
  * 兜底返回的是带 page_files 的扫描作品（阅读器可用）
  * 真正不存在的 (目录, 作品) 组合仍返回 None，兜底不滥认
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


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    monkeypatch.setitem(app.CFG, "dissolved_circles", [])
    monkeypatch.setitem(app.CFG, "artist_circles", {})
    app.state.index_loaded = False
    app.state.index = {"v": 3, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    app.state.terms.update({"at": 0.0, "circles": {}, "authors": {}, "ac": {}, "main": {}})
    # 3.6.13 新增的 owner 反查缓存：用例间必须清空，避免串味
    app.state.owner_index["src"] = None
    app.state.owner_index["map"] = {}
    yield root
    app.state.index_keys.clear()
    app.state.owner_index["src"] = None
    app.state.owner_index["map"] = {}


def _zip(path, pages=2):
    with zipfile.ZipFile(str(path), "w") as z:
        for i in range(1, pages + 1):
            z.writestr("%02d.jpg" % i, JPG)


def test_find_work_falls_back_to_key_owner(lib_env):
    """目录名（富士やま）≠ 圈子名（TOZAN_BU）时，圈子名与目录名两种寻址都要能打开。"""
    d = lib_env / "富士やま"
    d.mkdir()
    _zip(d / "[TOZAN_BU (富士やま)] 作品甲.zip")
    app.get_library(force=True)

    g = app.find_group("TOZAN_BU")
    assert g is not None, "作品应按圈子名归入 TOZAN_BU"
    wname = g["works"][0]["name"]
    owner = g["works"][0].get("_group")
    assert owner == "富士やま", "作品 key 的 owner 应锚真实目录"

    # 主路径：社团浏览按圈子名寻址（不变）
    assert app.find_work("TOZAN_BU", wname) is not None
    # 兜底（3.6.13 修复点）：画师页/续读/收藏按 key owner（目录名）寻址
    w = app.find_work(owner, wname)
    assert w is not None, "按目录名（key owner）也应解析到作品"
    assert w["name"] == wname
    assert w.get("page_files"), "兜底返回的必须是带页面的扫描作品（阅读器可用）"


def test_find_work_still_none_for_missing(lib_env):
    """真正不存在的 (目录, 作品) 组合仍返回 None，兜底不滥认。"""
    d = lib_env / "富士やま"
    d.mkdir()
    _zip(d / "[TOZAN_BU (富士やま)] 作品甲.zip")
    app.get_library(force=True)
    assert app.find_work("富士やま", "不存在的作品名") is None
    assert app.find_work("不存在的目录", "作品甲") is None
