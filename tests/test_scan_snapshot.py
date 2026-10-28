# -*- coding: utf-8 -*-
"""扫描快照测试（纪律 §4.9：拆事故重灾区前先补"输入→输出"快照）。

`scan_groups`（cc 46）与后续要拆的 `sync_scan` 都属事故重灾区：它们把
「文件名 → 分组 → 归档路径」这条链路一次算完，中间任何顺序变化都可能让
作品换社团、封面错位、或者收件箱重复入项。

本测试只钉**结构契约**，不钉时间戳（时间来自文件系统，天然不稳定）：
给一棵固定的小树，断言最终分组结果（社团名、作品名、排序）。
搬家/拆分前后跑它，输出必须逐字一致。
"""
import os
import sys
import zipfile

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402

T_FIXED = 1_700_000_000        # 固定 mtime：不依赖"现在"


def _mkzip(path):
    with zipfile.ZipFile(str(path), "w") as z:
        z.writestr("01.jpg", b"\xff\xd8 fake")
    os.utime(str(path), (T_FIXED, T_FIXED))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()

    # 真实档案目录：两部作品（裸词条 + 社团(画师)）
    d = root / "甲社"
    d.mkdir()
    _mkzip(d / "[甲社] 作品A.zip")
    _mkzip(d / "[甲社 (作者一)] 作品B.zip")

    # 根目录散包：只带词条，没有档案目录 → 归出虚拟社团
    _mkzip(root / "[乙社] 作品C.zip")

    # 合作社团：同时归入两个社团（不造合成组）
    _mkzip(root / "[丙社、丁社 (作者二)] 合作D.zip")

    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    monkeypatch.setitem(app.CFG, "dissolved_circles", [])
    monkeypatch.setitem(app.CFG, "ignore_files", [])
    app.state.index_loaded = False
    app.state.index = {"v": 2, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    yield {"root": root}
    app.state.index_keys.clear()


def _dump(groups):
    """稳定快照形态：[(社团名, (作品名…))]，按社团名排序，剔除时间字段。"""
    return [(g["name"], tuple(w["name"] for w in g["works"]))
            for g in sorted(groups, key=lambda g: g["name"])]


def test_scan_groups_snapshot(env):
    groups = app.scan_groups(str(env["root"]))
    # 作品名 = 去掉扩展名的**原始文件名**（不改写、不重排括号）；分组只看词条解析结果
    assert _dump(groups) == [
        ("丁社", ("[丙社、丁社 (作者二)] 合作D",)),
        ("丙社", ("[丙社、丁社 (作者二)] 合作D",)),
        ("乙社", ("[乙社] 作品C",)),
        ("甲社", ("[甲社 (作者一)] 作品B", "[甲社] 作品A")),
    ]


def test_scan_groups_snapshot_survives_rescan(env):
    """第二次扫描（走索引缓存）必须与首次逐个一致——缓存键/命中语义不能漂。"""
    first = _dump(app.scan_groups(str(env["root"])))
    second = _dump(app.scan_groups(str(env["root"])))
    assert first == second


def test_scan_groups_ignores_unknown_dirs(env):
    """程序目录、点目录、config 里的忽略名单都不算社团。

    程序目录名**不能写死 `_app`**：`IGNORE_DIRS` 收的是 `basename(APP_DIR)`，而 CI 上
    仓库叫 `manga-index`、检出目录就是 `manga-index`，写死会让这条只在本地绿、CI 红
    （3.6.161 实际踩到：公开树首跑 CI 挂在这条）。
    """
    app_dir_name = os.path.basename(app.APP_DIR)
    root = env["root"]
    (root / app_dir_name).mkdir()
    _mkzip(root / app_dir_name / "[噪声] 不该出现.zip")
    (root / ".hidden").mkdir()
    _mkzip(root / ".hidden" / "[噪声] 也不该出现.zip")
    groups = app.scan_groups(str(root))
    names = {g["name"] for g in groups}
    assert "噪声" not in names
    assert names == {"甲社", "乙社", "丙社", "丁社"}


def test_scan_groups_empty_root_returns_empty(tmp_path):
    """不存在 / 空根目录都返回空列表，不抛异常（首启动即这个状态）。"""
    assert app.scan_groups(str(tmp_path / "nope")) == []
    empty = tmp_path / "empty"
    empty.mkdir()
    assert app.scan_groups(str(empty)) == []
