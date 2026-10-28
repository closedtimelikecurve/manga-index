# -*- coding: utf-8 -*-
"""清理空文件夹、归档重复守卫、作者歧义多数表决 回归测试。"""
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
    app.state.index_loaded = False
    app.state.index = {"v": 2, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    saved_known = dict(app.state.known)
    yield root
    app.state.known.clear()
    app.state.known.update(saved_known)          # 就地恢复，保住 "ready" 键且不污染其他测试
    app.state.index_keys.clear()


# ---------- 清理空文件夹 ----------

def test_clean_empty_dirs_removes_empty_chains(lib_env):
    root = lib_env
    (root / "社团A" / "空作品" / "更深").mkdir(parents=True)          # 空目录链
    (root / "空社团").mkdir()
    keep = root / "社团B"
    keep.mkdir()
    (keep / "[社团B] 作品.zip").write_bytes(JPG)                      # 有作品，必须保留
    inbox = app._inbox_dir()                                          # 3.6.3：收件箱在程序目录内
    os.makedirs(inbox, exist_ok=True)
    removed = app._clean_empty_dirs()
    assert len(removed) == 4                                          # 空链3 + 空社团
    assert not (root / "社团A").exists()
    assert not (root / "空社团").exists()
    assert os.path.isdir(inbox), "收件箱不在文库根内，清扫文库绝不能碰到它"
    assert (keep / "[社团B] 作品.zip").exists()


def test_clean_empty_dirs_second_run_reports_zero(lib_env):
    root = lib_env
    (root / "空社团").mkdir()
    assert len(app._clean_empty_dirs()) == 1
    assert app._clean_empty_dirs() == []            # 第二次清扫无东西可清


# ---------- 归档重复守卫 ----------

def _make_uncat_zip(root, name):
    d = root / "待整理"
    d.mkdir(exist_ok=True)
    p = d / name
    with zipfile.ZipFile(str(p), "w") as z:
        z.writestr("01.jpg", JPG)
        z.writestr("02.jpg", JPG)
    return p


def test_archive_dup_guard_deletes_same_size(lib_env):
    root = lib_env
    src = _make_uncat_zip(root, "[社团D] 作品D.zip")
    circle = root / "社团D"
    circle.mkdir()
    with zipfile.ZipFile(str(circle / "[社团D] 作品D.zip"), "w") as z:   # 社团里已有同名同大小
        z.writestr("01.jpg", JPG)
        z.writestr("02.jpg", JPG)
    lib = app.get_library(force=True)
    g = next(g for g in lib["groups"] if g["name"] == "待整理")
    w = next(w for w in g["works"] if w["name"] == "[社团D] 作品D")
    print("DBG pre:", app._path_size(str(circle / "[社团D] 作品D.zip")),
          "src:", app._path_size(str(src)), "pre_exists:", (circle / "[社团D] 作品D.zip").exists())
    ok, msg = app._apply_rename(w, "[社团D] 作品D.zip")
    print("DBG msg:", msg)
    assert ok and "重复项" in msg
    assert not src.exists()                                       # 待整理原件已清理
    assert not (circle / "[社团D] 作品D (2).zip").exists()        # 绝不造第二份
    assert (circle / "[社团D] 作品D.zip").exists()


def test_archive_diff_size_keeps_both_with_suffix(lib_env):
    root = lib_env
    src = _make_uncat_zip(root, "[社团D] 作品D.zip")
    circle = root / "社团D"
    circle.mkdir()
    with zipfile.ZipFile(str(circle / "[社团D] 作品D.zip"), "w") as z:   # 同名不同内容(数据足够大,压缩后大小必不同)
        z.writestr("01.jpg", JPG * 300 + b"x")
        z.writestr("99.jpg", JPG * 137)
    lib = app.get_library(force=True)
    g = next(g for g in lib["groups"] if g["name"] == "待整理")
    w = next(w for w in g["works"] if w["name"] == "[社团D] 作品D")
    ok, msg = app._apply_rename(w, "[社团D] 作品D.zip")
    assert ok and "归档到" in msg
    assert (circle / "[社团D] 作品D.zip").exists()
    assert (circle / "[社团D] 作品D (2).zip").exists()            # 大小不同才并存
    assert not src.exists()


# ---------- 作者歧义多数表决 ----------

def test_resolve_bare_term_majority_vote(lib_env, monkeypatch):
    monkeypatch.setitem(app.CFG, "dissolved_circles", [])
    app.state.known.clear()
    app.state.known.update({"ready": True, "circles": set(), "pc": {"作者X": {"社团甲", "社团乙"}}})
    # 文库中 作者X 在 社团甲 有 2 部、社团乙 有 1 部 → 多数表决归 社团甲
    app.state.lib["data"] = {"groups": [
        {"name": "社团甲", "works": [{"personal": "作者X", "bare": ""},
                                     {"personal": "作者X", "bare": ""}]},
        {"name": "社团乙", "works": [{"personal": "作者X", "bare": ""}]},
    ], "scan_ms": 0, "scanned_at": 0}
    r = app.resolve_bare_term("作者X")
    assert r == ("personal", "社团甲")


def test_resolve_bare_term_tie_stays_none(lib_env, monkeypatch):
    monkeypatch.setitem(app.CFG, "dissolved_circles", [])
    app.state.known.clear()
    app.state.known.update({"ready": True, "circles": set(), "pc": {"作者Y": {"社团甲", "社团乙"}}})
    app.state.lib["data"] = {"groups": [
        {"name": "社团甲", "works": [{"personal": "作者Y", "bare": ""}]},
        {"name": "社团乙", "works": [{"personal": "作者Y", "bare": ""}]},
    ], "scan_ms": 0, "scanned_at": 0}
    assert app.resolve_bare_term("作者Y") is None                 # 平票不猜


def test_resolve_bare_term_single_owner_unchanged(lib_env, monkeypatch):
    monkeypatch.setitem(app.CFG, "dissolved_circles", [])
    app.state.known.clear()
    app.state.known.update({"ready": True, "circles": {"社团丙"}, "pc": {"作者Z": {"社团丙"}}})
    assert app.resolve_bare_term("作者Z") == ("personal", "社团丙")
    assert app.resolve_bare_term("社团丙") == ("circle",)
