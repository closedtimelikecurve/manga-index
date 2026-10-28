# -*- coding: utf-8 -*-
"""收件箱（_app/_inbox）与「未分类已取消」的回归测试。

3.6.3 起「未分类」正式取消：
  * 收件箱是**功能性目录**（程序目录内的 _app/_inbox），不是社团 —— /api/circle/收件箱 必须 404，
    它也不能在文库根留下任何中文目录。
  * 文库里无法归属的作品（遗留「未分类」目录里的、根目录无词条散包）**不进文库**，
    由 _inbox_sync 搬进 _app/_inbox 变成待确认项，与爬虫落盘共用同一套提案式入库流程。
  * 别的社团名找不到时仍然 404（不能把真实错误一起吞掉）。
  * /api/pages 的 kinds 要标出动图（gif）：APP 靠它决定不预读、并限制解码尺寸。
"""
import os
import sys
from urllib.parse import quote

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402

UNCAT = "/api/circle/" + quote("收件箱")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """一个社团（3 页：jpg + gif + webm），收件箱目录按用例决定是否创建。"""
    root = tmp_path / "lib"
    root.mkdir()
    pages = root / "社团G" / "作品G"
    pages.mkdir(parents=True)
    (pages / "01.jpg").write_bytes(b"\xff\xd8 fake")
    (pages / "02.gif").write_bytes(b"GIF89a fake")
    (pages / "03.webm").write_bytes(b"\x1a\x45\xdf\xa3 fake")

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


def test_inbox_is_not_a_circle(env):
    """收件箱是功能性目录（_app/_inbox）而不是社团 → /api/circle/收件箱 必须 404。"""
    app.get_library(force=True)
    c = app.app.test_client()
    r = c.get(UNCAT)
    assert r.status_code == 404, r.status_code
    assert "社团不存在" in r.get_json()["message"]
    # 文库根不允许出现任何收件箱/未分类的中文目录
    assert not (env["root"] / "收件箱").exists()
    assert not (env["root"] / "未分类").exists()


def test_legacy_uncat_dir_goes_to_inbox(env):
    """遗留「未分类」目录不再算社团：作品不进文库，同步后搬进 _app/_inbox 成为待确认项。"""
    root = env["root"]
    d = root / "未分类"
    d.mkdir()
    (d / "乱名作品.zip").write_bytes(b"PK\x03\x04 fake")
    app.get_library(force=True)
    # 1) 不进文库（既不是「未分类」社团，也不是「收件箱」社团）
    names = {g["name"] for g in app.get_library()["groups"]}
    assert "未分类" not in names and "收件箱" not in names
    # 2) 被登记成「无归属」
    assert any(os.path.basename(p) == "乱名作品.zip" for p in app.state.unfiled_paths)
    # 3) 同步后搬进收件箱目录（不在文库根建任何中文目录）
    app._inbox_sync()
    assert (os.path.join(app._inbox_dir(), "乱名作品.zip"))
    assert os.path.isfile(os.path.join(app._inbox_dir(), "乱名作品.zip"))
    assert not (d / "乱名作品.zip").exists()
    # 4) 成为待确认项，走同一套提案式入库
    assert any(it["name"].startswith("乱名作品") for it in app.meta.inbox_list())


def test_root_loose_unfiled_goes_to_inbox(env):
    """文库根的无词条散包同样不进文库，同步后收进 _app/_inbox。"""
    root = env["root"]
    (root / "毫无词条的作品.zip").write_bytes(b"PK\x03\x04 fake")
    app.get_library(force=True)
    names = {g["name"] for g in app.get_library()["groups"]}
    assert "毫无词条的作品" not in names
    app._inbox_sync()
    assert os.path.isfile(os.path.join(app._inbox_dir(), "毫无词条的作品.zip"))


def test_other_missing_circle_still_404(env):
    """别的社团名找不到必须仍然 404（不能把真实错误一起吞掉）。"""
    app.get_library(force=True)
    c = app.app.test_client()
    r = c.get("/api/circle/" + quote("不存在的社团"))
    assert r.status_code == 404
    assert "社团不存在" in r.get_json()["message"]


def test_pages_kinds_marks_gif(env):
    """kinds 要区分 image / gif / video —— APP 靠 gif 标记决定不预读 + 限制解码尺寸。"""
    app.get_library(force=True)
    c = app.app.test_client()
    j = c.get("/api/pages?group=" + quote("社团G") + "&work=" + quote("作品G")).get_json()
    assert j["ok"] is True and j["total"] == 3
    assert j["kinds"] == ["image", "gif", "video"], j["kinds"]
    assert j["ver"]                                  # 页面缓存键仍然在
