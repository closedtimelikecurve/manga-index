# -*- coding: utf-8 -*-
"""增量扫描（library_index.json）回归测试。

覆盖：
  * 压缩包作品：二次扫描命中缓存（不再打开压缩包枚举页名），结果逐字段一致
  * 源文件变动（mtime/内容）：缓存失效，重新解析
  * 文件夹作品：树内新增图片 → 页数变化被正确感知
  * originals 词条库变化 → 整个索引作废（全量重扫）
  * 索引文件损坏 → 安全回退全量扫描
  * SCAN_STATE 进度统计
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
import panel.paths as _paths  # noqa: E402  路径/媒体工具已抽至 panel/paths.py


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    """隔离的文库根 + 独立索引文件（绝不触碰真实文库与真实索引）。

    3.6.152 修复顺序依赖：这份夹具是**本文件自带**的（没有复用 `_originals_helpers.lib_env`），
    原先只换了 root / INDEX_FILE，却没还原**词条归一的全局态**——于是本进程此前跑过的
    测试（以及真实 config.json 里用户自己的词条）会把 `社团A (画师甲)` 归一到 `社团A`，
    而 `get_library()` 在索引 hash 失效时会顺手重载一遍词条库：同一测试里的两拍就可能
    一拍"未归一"、一拍"已归一"，`test_corrupt_index_falls_back` 比快照时随机红。
    （表现：全量跑偶尔红、单文件跑绿；在未改动的 HEAD worktree 上全量跑同样红。）
    现在与共享夹具同口径：词条库固定为**内置名单**，全局映射一并还原。
    """
    root = tmp_path / "lib"
    root.mkdir()
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    # 词条库固定为内置名单（不读任何 config），归一映射可还原
    built = app._dp.load_originals(None)
    monkeypatch.setitem(app.CFG, "originals", [])
    monkeypatch.setattr(app.state, "originals", built[0])
    monkeypatch.setattr(app.state, "norm_to_canon", dict(built[1]))
    monkeypatch.setattr(app._dp, "NORM_TO_CANON", dict(built[1]))
    app.state.index_loaded = False
    app.state.index = {"v": 1, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    yield root
    app.state.index_keys.clear()


def _make_zip(path, pages=5, prefix=""):
    with zipfile.ZipFile(path, "w") as z:
        for i in range(1, pages + 1):
            z.writestr(f"{prefix}{i:03d}.jpg", b"\xff\xd8 fake-jpeg")


@pytest.fixture()
def sample_lib(lib_env):
    circ = lib_env / "社团A (画师甲)"
    circ.mkdir()
    _make_zip(str(circ / "[社团A (画师甲)] 作品一 (C102).zip"), pages=5)
    fd = circ / "作品二文件夹"
    fd.mkdir()
    (fd / "001.jpg").write_bytes(b"\xff\xd8 x")
    with zipfile.ZipFile(str(fd / "extra.zip"), "w") as z:
        z.writestr("a/01.jpg", b"\xff\xd8 y")
        z.writestr("a/02.jpg", b"\xff\xd8 y")
    return lib_env


def _snapshot(lib):
    """稳定的快照形态：**按社团名排序后**再取字段。

    3.6.152 修顺序依赖：同一棵树会因「括号词条 vs 目录名」产出**两个社团**
    （`[社团A (画师甲)] 作品一` 归 `社团A`、无括号的 `作品二文件夹` 归目录名
    `社团A (画师甲)`），两者的「最近入库时间」只差几毫秒（新社团首见时刻取 now()）。
    原来这里按返回顺序逐字比，两次扫描只要毫秒级抖动换序就红——药不对症：
    这里要钉的是"内容一致"，顺序另有 `sort_groups` 的测试管。
    """
    return [
        (g["name"], [
            (w["name"], w["kind"], w["pages"], w["cover"], w["page_files"],
             w["circle"], w["personal"], [tuple(t) for t in w["tags"]])
            for w in g["works"]
        ])
        for g in sorted(lib["groups"], key=lambda g: g["name"])
    ]


def _count_zip_opens(monkeypatch):
    counter = {"n": 0}
    # list_zip_images 已抽到 panel/paths.py：打桩须打到真正被扫描路径调用的模块
    orig = _paths.list_zip_images

    def counting(p):
        counter["n"] += 1
        return orig(p)

    monkeypatch.setattr(_paths, "list_zip_images", counting)
    return counter


def test_second_scan_hits_cache_and_matches(lib_env, sample_lib, monkeypatch):
    lib1 = app.get_library(force=True)
    snap1 = _snapshot(lib1)
    assert os.path.exists(app.INDEX_FILE)

    counter = _count_zip_opens(monkeypatch)
    lib2 = app.get_library(force=True)
    # 全部压缩包命中缓存：不再打开任何 zip 枚举页名
    assert counter["n"] == 0, "二次扫描应命中索引缓存，不应重开压缩包"
    assert _snapshot(lib2) == snap1, "缓存命中结果必须与实时扫描逐字段一致"


def test_archive_change_invalidates(lib_env, sample_lib, monkeypatch):
    app.get_library(force=True)
    zp = sample_lib / "社团A (画师甲)" / "[社团A (画师甲)] 作品一 (C102).zip"
    # 明确把 mtime 往后推 —— 不能用 os.utime(path, None)：Windows 文件时间戳按系统时钟 tick
    # （约 15.6ms）粒度更新，"刚建完就 utime 成现在"可能落进同一个 tick，mtime_ns 不变 →
    # 增量索引键不变 → 断言偶发失败（本用例曾 3 次里挂 1 次的真正原因）。
    st = os.stat(str(zp))
    os.utime(str(zp), (st.st_atime, st.st_mtime + 10))
    counter = _count_zip_opens(monkeypatch)
    app.get_library(force=True)
    assert counter["n"] == 1, "变动的压缩包必须重新解析"


def test_folder_tree_change_detected(lib_env, sample_lib):
    lib1 = app.get_library(force=True)
    pages_before = {w["name"]: w["pages"] for g in lib1["groups"] for w in g["works"]}
    assert pages_before["作品二文件夹"] == 3      # 1 散图 + 2 嵌套包内页

    fd = sample_lib / "社团A (画师甲)" / "作品二文件夹"
    (fd / "002.jpg").write_bytes(b"\xff\xd8 z")   # 树内新增一页
    st = os.stat(str(fd / "extra.zip"))           # 同前：显式推后 mtime，不依赖"现在"的 tick
    os.utime(str(fd / "extra.zip"), (st.st_atime, st.st_mtime + 10))
    lib2 = app.get_library(force=True)
    pages_after = {w["name"]: w["pages"] for g in lib2["groups"] for w in g["works"]}
    assert pages_after["作品二文件夹"] == 4, "文件夹树内新增图片必须被感知"


def test_originals_change_drops_index(lib_env, sample_lib, monkeypatch):
    app.get_library(force=True)
    counter = _count_zip_opens(monkeypatch)
    monkeypatch.setattr(app, "_originals_hash", lambda: "changed-hash")
    app.get_library(force=True)
    assert counter["n"] >= 1, "originals 变化应使整个索引作废（全量重扫）"


def test_corrupt_index_falls_back(lib_env, sample_lib):
    app.get_library(force=True)
    snap = _snapshot(app.get_library())
    with open(app.INDEX_FILE, "w", encoding="utf-8") as f:
        f.write("{corrupted!!!")
    app.state.index_loaded = False
    app.state.index = {"v": 1, "originals_hash": "", "works": {}}
    lib = app.get_library(force=True)
    assert _snapshot(lib) == snap, "索引损坏必须安全回退且结果一致：第一拍=%r 重扫后=%r" % (
        snap, _snapshot(lib))


def test_scan_state_progress(lib_env, sample_lib):
    app.get_library(force=True)
    assert app.state.scan_state["done"] == app.state.scan_state["total"]
    assert app.state.scan_state["done"] > 0
    assert app.state.scan_state["running"] is False


def test_nested_archive_pages_counted_and_readable(lib_env, sample_lib):
    """P2-7：文件夹作品的嵌套压缩包页计入 page_files 且可经 page_source 读取。"""
    lib = app.get_library(force=True)
    works = {w["name"]: w for g in lib["groups"] for w in g["works"]}
    wf = works["作品二文件夹"]
    wz = works["[社团A (画师甲)] 作品一 (C102)"]
    assert wf["pages"] == len(wf["page_files"]) == 3     # 1 散图 + 2 嵌套包内页
    assert wz["pages"] == len(wz["page_files"]) == 5
    # 第 0 页 = 散图 → 磁盘路径；第 1/2 页 = 嵌套包内页 → bytes 可读（此前不可达）
    k0, p0, _ = app.page_source(wf, 0)
    assert k0 == "file" and os.path.exists(p0)
    k1, p1, _ = app.page_source(wf, 1)
    assert k1 == "bytes" and p1
    k2, p2, _ = app.page_source(wf, 2)
    assert k2 == "bytes" and p2
    assert app.page_source(wf, 3) == (None, None, None)  # 越界
    # api_pages kinds 形状与 total 恒一致（安卓/前端契约）
    kinds = [app.media_kind(app.page_media_name(pg)) for pg in wf["page_files"]]
    assert len(kinds) == wf["pages"] and all(k == "image" for k in kinds)


def test_persisted_index_survives_reload(lib_env, sample_lib, monkeypatch):
    app.get_library(force=True)
    # 模拟进程重启：重置内存态后重新加载磁盘索引
    app.state.index_loaded = False
    app.state.index = {"v": 1, "originals_hash": "", "works": {}}
    counter = _count_zip_opens(monkeypatch)
    lib = app.get_library(force=True)
    assert counter["n"] == 0, "重启后应从磁盘索引恢复，不重开压缩包"
    names = {w["name"] for g in lib["groups"] for w in g["works"]}
    assert names == {"[社团A (画师甲)] 作品一 (C102)", "作品二文件夹"}


# ---------------------------------------------------------------
# 3.6.10 回归：后台重扫跨异步边界写穿防护
# 事故原型：测试 fixture teardown 撤销 monkeypatch 后，仍在跑的后台重扫线程
# 拿旧库的作品列表往已还原的真实 meta.db 落盘，sync_scan 的「不在本次扫描中的
# key 全删」语义把线上 works 2263 行删到 1 行（works/work_authors/work_tags
# 三张派生表被清空）。此后任何写盘都必须锚定扫描发起时的上下文。
# ---------------------------------------------------------------
def test_scan_ctx_reflects_current_paths(lib_env, tmp_path, monkeypatch):
    ctx = app._scan_ctx()
    assert ctx["root"] == str(lib_env)
    assert ctx["idx"] == str(tmp_path / "library_index.json")
    assert ctx["db"].endswith("meta.db")
    assert not app._ctx_stale(ctx)
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "other_index.json"))
    assert app._ctx_stale(ctx)


def test_rescan_abandons_write_when_ctx_changed(lib_env, sample_lib, tmp_path, monkeypatch):
    """上下文已变 → 只更新内存缓存，绝不往新路径落盘（索引 + 元数据库都不写）。"""
    app.get_library(force=True)
    ctx = app._scan_ctx()

    # 模拟 fixture 撤销：切到另一套路径（= 真实 meta.db / library_index.json 的角色）
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setattr(app, "INDEX_FILE", str(other / "library_index.json"))
    monkeypatch.setattr(app.meta, "DB_PATH", str(other / "meta.db"))

    calls = []
    monkeypatch.setattr(app.meta, "sync_scan", lambda groups: calls.append(len(groups)))

    with app.SCAN_LOCK:
        app._do_scan(ctx=ctx)

    assert calls == [], "上下文已变仍写了元数据库（会清空目标库真实记录）"
    assert not (other / "library_index.json").exists(), "上下文已变仍写了索引文件"
    # 内存缓存照常刷新，保证前端仍能读到刚扫出来的数据
    assert app.state.lib["data"] is not None


def test_rescan_writes_when_ctx_unchanged(lib_env, sample_lib, monkeypatch):
    """对照组：上下文没变就正常落盘（不能把护栏做成一律不写）。"""
    calls = []
    monkeypatch.setattr(app.meta, "sync_scan", lambda groups: calls.append(len(groups)))
    with app.SCAN_LOCK:
        app._do_scan(ctx=app._scan_ctx())
    assert calls and calls[0] > 0
