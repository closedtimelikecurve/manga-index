# -*- coding: utf-8 -*-
"""扫描重入回归（3.7.51）：首扫期间任何"顺手查库"的调用不得递归重扫。

事故现象：网页与 APP 都停在"正在加载中"，`/api/library` 永远返回
`{"status":"scanning","done":73,"total":733}`。

根因：`SCAN_LOCK` 是 `threading.RLock`（可重入），挡不住同一线程的递归——
`build_group → _cover_for_group → _resolve_region_cover → find_work → find_group
→ get_library()`（首扫时 `state.lib["data"]` 还是 None）`→ _do_scan() → …`
无限递归到 `RecursionError`，扫描线程直接死掉，`running` 永远是 True。
"""
import os
import sys
import zipfile

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    d = root / "社团A"
    d.mkdir(parents=True)
    p = d / "[社团A (画师甲)] 作品1 (FateGrand Order).zip"
    with zipfile.ZipFile(str(p), "w") as z:
        z.writestr("01.jpg", b"\xff\xd8 fake")
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    monkeypatch.setitem(app.CFG, "dissolved_circles", [])
    app.state.index_loaded = False
    app.state.index = {"v": 3, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    app.state.lib["stale"] = False
    yield root
    app.state.index_keys.clear()


def test_scan_survives_reentrant_get_library(lib_env, monkeypatch):
    """扫描进行中调用 get_library 必须返回空库，而不是再进一次 _do_scan。"""
    orig = app.scan_groups

    def spy(root):
        app.get_library()          # 模拟 _cover_for_group → find_work → find_group 的查库
        return orig(root)

    monkeypatch.setattr(app, "scan_groups", spy)
    lib = app.get_library(force=True)          # 修复前：RecursionError
    assert lib["groups"], lib


def test_scan_survives_cover_override_lookup(lib_env, monkeypatch):
    """真实触发路径：区域封面覆盖存在时，_cover_for_group 会走到 find_work → get_library。"""
    app.state.lib["data"] = None
    monkeypatch.setattr(app, "_resolve_region_cover",
                        lambda region, name: {"group": "社团A", "work": "作品1"})
    lib = app.get_library(force=True)
    assert lib["groups"], lib
