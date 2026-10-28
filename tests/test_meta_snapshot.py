# -*- coding: utf-8 -*-
"""sync_scan 的**输出快照**（3.6.76）。

拆分 `_scan_collect` / `_scan_sync_works` / `_scan_sync_derived` 之前，先钉死
"输入树 → DB 内容"的契约：只要这三张表的内容不变，重建结构就没有改语义。

只钉**稳定列**（键、分组、页数、类型、社团、待定词条、大小），不钉 mtime / added_at /
seen_at —— 它们随运行时刻变化，钉了只会换来无意义的红灯。
`works_fts` 单独钉"键集合"，用来发现"拆分时忘了重建全文索引"。
"""
import os
import sys
import zipfile

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
import meta_store  # noqa: E402

JPG = b"\xff\xd8\xff\xe0 fake-jpg"


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
    app.state.index_loaded = False
    app.state.index = {"v": 3, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    yield root
    app.state.index_keys.clear()


def _dump():
    """按固定顺序导出三张表 + FTS 键集合（只取稳定列）。"""
    c = meta_store._connect()
    works = sorted(c.execute(
        "SELECT key, group_name, name, pages, kind, circle, bare, size FROM works"))
    authors = sorted(c.execute("SELECT key, author FROM work_authors"))
    tags = sorted(c.execute("SELECT key, type, name FROM work_tags"))
    fts = sorted(r[0] for r in c.execute("SELECT key FROM works_fts"))
    return {"works": works, "authors": authors, "tags": tags, "fts": fts}


def _build(root):
    circ = root / "社团A (画师甲)"
    circ.mkdir()
    _make_zip(circ / "[社团A (画师甲)] 作品一 (C102).zip", pages=5)
    fd = circ / "作品二文件夹"
    fd.mkdir()
    (fd / "001.jpg").write_bytes(JPG)
    b = root / "社团B"
    b.mkdir()
    _make_zip(b / "[社团B] 作品三.zip", pages=2)
    _make_zip(root / "[社团C] 作品四.zip", pages=4)      # 根目录散包 → 虚拟社团


def test_scan_snapshot_shape(lib_env):
    _build(lib_env)
    app.get_library(force=True)
    got = _dump()

    assert [w[0] for w in got["works"]] == [
        "社团A (画师甲)/[社团A (画师甲)] 作品一 (C102)",
        "社团A (画师甲)/作品二文件夹",
        "社团B/[社团B] 作品三",
        "社团C/[社团C] 作品四",
    ]
    # (pages, kind, circle, bare) —— 目录名不当词条、未见证的 [词条] 只进 bare（现状契约，勿随手改）
    assert [(w[3], w[4], w[5], w[6]) for w in got["works"]] == [
        (5, "archive", "社团A", ""),
        (1, "folder", "", ""),
        (2, "archive", "", "社团B"),
        (4, "archive", "", "社团C"),
    ]
    # 只有文件名里解析出画师的作品才进 work_authors；裸 [词条] 也按该词条记一位作者
    assert got["authors"] == [
        ("社团A (画师甲)/[社团A (画师甲)] 作品一 (C102)", "画师甲"),
        ("社团B/[社团B] 作品三", "社团B"),
        ("社团C/[社团C] 作品四", "社团C"),
    ]
    # 标签按 (key, type, name) 排序：event/personal 两类都要落到 DB
    assert ("社团A (画师甲)/[社团A (画师甲)] 作品一 (C102)", "event", "C102") in got["tags"]
    assert ("社团A (画师甲)/[社团A (画师甲)] 作品一 (C102)", "personal", "画师甲") in got["tags"]
    assert got["fts"] == [w[0] for w in got["works"]], "FTS 键集合必须与 works 一致"


def test_scan_snapshot_idempotent(lib_env):
    """同一棵树扫两次，DB 内容必须逐字一致（修剪与 upsert 都不允许漂移）。"""
    _build(lib_env)
    app.get_library(force=True)
    first = _dump()
    app.get_library(force=True)
    second = _dump()
    assert first == second


def test_scan_snapshot_prunes_removed_work(lib_env):
    """删掉一部作品后重扫：works / work_authors / work_tags / FTS 四处都不能留残行。"""
    _build(lib_env)
    app.get_library(force=True)
    os.remove(str(lib_env / "社团B" / "[社团B] 作品三.zip"))
    app.get_library(force=True)
    got = _dump()
    gone = "社团B/[社团B] 作品三"
    assert all(w[0] != gone for w in got["works"])
    assert all(a[0] != gone for a in got["authors"])
    assert all(t[0] != gone for t in got["tags"])
    assert gone not in got["fts"]
