# -*- coding: utf-8 -*-
"""tests/_originals_helpers.py —— 原作分区测试的共用夹具与常量（3.6.83 从测试文件抽出）。

拆出的原因：拆分时 `test_originals_manual.py` 有 902 行（有效代码 597），已超「物理 800 / 代码 400」；
两个测试文件若各自复制 `lib_env` / `_seed`，夹具就会漂移。
**这里的 `lib_env` 是 pytest fixture**：测试文件按名字导入即可生效（`from _originals_helpers import lib_env`）。
"""
import json
import os
import sys
import zipfile

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
import common  # noqa: E402
import meta_store  # noqa: E402


JPG = b"\xff\xd8\xff\xe0 fake-jpg"
# 刻意避开 djc_parse.DEFAULT_ORIGINALS 内置名单（Fate/東方/ブルアカ…），
# 否则 canon 撞内置、断言恒真恒假，测不到手动维护路径本身。
TERM = "テスト原作XYZ"
KEY = "社团A (画师甲)/[社团A (画师甲)] 某作品 (Fate_Grand_Order)"
# FGO 分区宿主：文件名真的含 "FGO"（用户场景里 FGO 分区能存在，就有这样的作品）
KEY2 = "社团B/[社团B] FGO 同人志"


def _make_zip(path, pages=3):
    with zipfile.ZipFile(str(path), "w") as z:
        for i in range(1, pages + 1):
            z.writestr("%03d.jpg" % i, JPG)


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    # 词条库全局态：端点内会整体重载，必须可还原（否则污染后续测试的解析结果）。
    # 3.6.28 起用**纯内置名单**重建映射（load_originals(None) 不读任何 config）——
    # 此前复制"进程启动态"，会把真实 config.json 里用户新加的词条带进来
    # （用户把分区归一成 'Fate Grand Order' 后 4 个测试连红，测试对用户数据敏感）。
    # 宽松归一要能命中内置名单才能测到变体归一，内置名单保持完整。
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


def _seed(lib_env):
    circ = lib_env / "社团A (画师甲)"
    circ.mkdir()
    _make_zip(circ / "[社团A (画师甲)] 某作品 (Fate_Grand_Order).zip")
    app.get_library(force=True)


def _seed_fgo(lib_env):
    """追加一个文件名含 FGO 的作品——FGO 分区的宿主（搜 FGO 能命中它）。"""
    circ = lib_env / "社团B"
    circ.mkdir()
    _make_zip(circ / "[社团B] FGO 同人志.zip")
    app.get_library(force=True)


def _seed_builtin(lib_env):
    """文件名括号**字面等于内置原作名**的作品 → 解析产出内置 original 标签。
    分区靠 djc_parse 内置名单存活（config 词条库为空）——真实库里这类分区最常见，
    也是 3.6.28「归一后旧分区复活」报障的宿主：内置词条不随词条库删除。"""
    circ = lib_env / "社团C"
    circ.mkdir()
    _make_zip(circ / "[社团C] 内置原作测试 (FateGrand Order).zip")
    app.get_library(force=True)


def _has_original(key, name):
    c = meta_store._connect()
    return (c.execute("SELECT count(*) FROM work_tags WHERE key=? AND type='original' AND name=?",
                      (key, name)).fetchone()[0]) > 0
