# -*- coding: utf-8 -*-
"""3.6.31 改名 / 合并时的「区域封面交接」回归测试。

用户需求：任何分区合并都要即时生效，且**合并后的新区，其封面继承自正名社团**。

改动前：三类改名/合并端点（社团 / 画师 / 原作分区）里，只有原作分区处理了封面覆盖；
社团改名与社团合并**完全没有**处理 circles 桶 —— 用户给社团设的封面在改名/合并后
凭空消失（旧名下的记录还留着，新的区域没有）。画师改名还会连作品文件名一起改，
封面坐标里的作品名也失效。

统一走 `_region_cover_migrate(scope, old, new, retarget=, work_renames=)`：
  * 正名优先：目标区域已有封面 → 保留目标那份（"继承正名"），旧的不抢；
  * 目标没封面 → 把旧的搬过去，坐标按需要重定向（retarget）/ 跟随作品改名；
  * 旧名记录一律清掉（避免同名重建时被意外继承）。
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


def _make_zip(path, tag=b"A", pages=3):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(path), "w") as z:
        for i in range(1, pages + 1):
            z.writestr(zipfile.ZipInfo("%03d.jpg" % i, date_time=(2020, 1, 1, 0, 0, 0)),
                       JPG + tag + bytes([i]))


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
    monkeypatch.setattr(app, "REGION_COVERS_FILE", str(tmp_path / "region_covers.json"))
    monkeypatch.setattr(app.state, "region_covers", None)
    yield root
    app.state.index_keys.clear()


# ---------- 纯函数层面：交接规则 ----------

def test_migrate_plain_rename_moves_cover(lib_env):
    """改名（目标无封面）→ 覆盖搬到新名，旧名清空。"""
    app._region_cover_set("circle", "旧社", "旧社", "作品A")
    app._region_cover_migrate("circle", "旧社", "新社")
    assert app._region_cover_get("circle", "旧社") is None
    assert app._region_cover_get("circle", "新社") == ("旧社", "作品A")


def test_migrate_keeps_target_cover_when_both_exist(lib_env):
    """正名优先：两边都有封面 → 保留目标那份，旧的被丢弃。"""
    app._region_cover_set("circle", "旧社", "旧社", "作品A")
    app._region_cover_set("circle", "正名社", "正名社", "作品B")
    app._region_cover_migrate("circle", "旧社", "正名社")
    assert app._region_cover_get("circle", "正名社") == ("正名社", "作品B")   # 未被抢
    assert app._region_cover_get("circle", "旧社") is None


def test_migrate_retargets_group(lib_env):
    """retarget：作品换到新区域 → 坐标里的 group 重定向到新名（否则 find_work 落空）。"""
    app._region_cover_set("circle", "旧社", "旧社", "作品A")
    app._region_cover_migrate("circle", "旧社", "新社", retarget=True)
    assert app._region_cover_get("circle", "新社") == ("新社", "作品A")


def test_migrate_follows_work_rename(lib_env):
    """work_renames：作品名随画师改名而变 → 坐标里的作品名跟着换。"""
    app._region_cover_set("artist", "旧名", "社团X", "[社团X (旧名)] 作品一")
    app._region_cover_migrate("artist", "旧名", "新名",
                              work_renames={"[社团X (旧名)] 作品一": "[社团X (新名)] 作品一"})
    assert app._region_cover_get("artist", "新名") == ("社团X", "[社团X (新名)] 作品一")
    assert app._region_cover_get("artist", "旧名") is None


def test_migrate_clears_old_even_without_cover(lib_env):
    """旧名没封面也要清记录（防同名重建时意外继承）。"""
    app._region_cover_set("circle", "旧社", "gc", "wc")
    app._region_cover_set("circle", "新社", "gn", "wn")
    app._region_cover_migrate("circle", "旧社", "新社")
    assert app._region_cover_get("circle", "旧社") is None


# ---------- 端点：社团改名 ----------

def test_circle_rename_moves_cover(lib_env):
    d = lib_env / "社团A"
    d.mkdir()
    _make_zip(d / "[社团A (画师甲)] 作品一.zip", tag=b"A")
    app.get_library(force=True)
    client = app.app.test_client()
    assert client.post("/api/set-cover", json={
        "scope": "circle", "name": "社团A", "group": "社团A",
        "work": "[社团A (画师甲)] 作品一"}).get_json()["ok"] is True

    r = client.post("/api/rename-circle", json={"group": "社团A", "new_name": "社团B"})
    assert r.get_json().get("ok") is True, r.get_json()

    app.state.region_covers = None
    assert app._region_cover_get("circle", "社团A") is None            # 旧名不留残骸
    cov = app._region_cover_get("circle", "社团B")
    assert cov is not None, "改名后社团封面丢了"
    assert cov[0] == "社团B", "封面坐标未重定向到新社团名：%s" % (cov,)
    # 坐标必须真的能查到（重定向不生效的话 find_work 会落空）。
    # 改名端点只 _lib_touch()，要 force 重扫后 LIB 里才是新社团名。
    app.get_library(force=True)
    assert app._resolve_region_cover("circle", "社团B") is not None


# ---------- 端点：社团合并（正名优先） ----------

def test_circle_merge_keeps_target_cover(lib_env):
    """A 合并进已存在的 B：B（正名）自己的封面要保住。"""
    da, db = lib_env / "社团A", lib_env / "社团B"
    da.mkdir(); db.mkdir()
    _make_zip(da / "[社团A (画师甲)] A作品.zip", tag=b"A")
    _make_zip(db / "[社团B (画师乙)] B作品.zip", tag=b"B")
    app.get_library(force=True)
    client = app.app.test_client()
    for g, w in (("社团A", "[社团A (画师甲)] A作品"),
                 ("社团B", "[社团B (画师乙)] B作品")):
        assert client.post("/api/set-cover", json={
            "scope": "circle", "name": g, "group": g, "work": w}).get_json()["ok"] is True

    r = client.post("/api/rename-circle", json={"group": "社团A", "new_name": "社团B"})
    j = r.get_json()
    assert j.get("merged") is True, j

    app.state.region_covers = None
    assert app._region_cover_get("circle", "社团A") is None
    cov = app._region_cover_get("circle", "社团B")
    assert cov == ("社团B", "[社团B (画师乙)] B作品"), "合并后未继承正名社团的封面：%s" % (cov,)


def test_circle_merge_inherits_source_cover_when_target_has_none(lib_env):
    """目标没设过封面 → 沿用源社团那份（坐标重定向到正名社团）。"""
    da, db = lib_env / "社团A", lib_env / "社团B"
    da.mkdir(); db.mkdir()
    _make_zip(da / "[社团A (画师甲)] A作品.zip", tag=b"A")
    _make_zip(db / "[社团B (画师乙)] B作品.zip", tag=b"B")
    app.get_library(force=True)
    client = app.app.test_client()
    assert client.post("/api/set-cover", json={
        "scope": "circle", "name": "社团A", "group": "社团A",
        "work": "[社团A (画师甲)] A作品"}).get_json()["ok"] is True

    r = client.post("/api/rename-circle", json={"group": "社团A", "new_name": "社团B"})
    assert r.get_json().get("merged") is True, r.get_json()

    app.state.region_covers = None
    cov = app._region_cover_get("circle", "社团B")
    assert cov == ("社团B", "[社团A (画师甲)] A作品"), "目标无封面时应沿用源封面：%s" % (cov,)
    app.get_library(force=True)      # 同上：重扫后坐标才生效
    assert app._resolve_region_cover("circle", "社团B") is not None


# ---------- 端点：画师改名（作品文件名跟着改） ----------

def test_artist_rename_follows_work_rename(lib_env):
    d = lib_env / "社团X"
    d.mkdir()
    _make_zip(d / "[社团X (旧名)] 作品一.zip", tag=b"A")
    app.get_library(force=True)
    client = app.app.test_client()
    assert client.post("/api/set-cover", json={
        "scope": "artist", "name": "旧名", "group": "社团X",
        "work": "[社团X (旧名)] 作品一"}).get_json()["ok"] is True

    r = client.post("/api/artist/rename", json={"from": "旧名", "to": "新名"})
    assert r.get_json().get("ok") is True, r.get_json()

    app.state.region_covers = None
    assert app._region_cover_get("artist", "旧名") is None
    cov = app._region_cover_get("artist", "新名")
    assert cov is not None, "画师改名后封面丢了"
    assert cov[1] == "[社团X (新名)] 作品一", "封面坐标未跟随作品改名：%s" % (cov,)
    app.get_library(force=True)      # 画师改名会改文件名，必须重扫才有新作品名
    assert app._resolve_region_cover("artist", "新名") is not None
