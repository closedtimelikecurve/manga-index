# -*- coding: utf-8 -*-
"""Index 3.0 元数据层（M1）回归测试。

覆盖《更新计划书》验收标准：
  * 首启迁移：config 三键 → DB，一次性、幂等、不写穿 config
  * 扫描后 DB 与扫描结果一致（works/work_authors/work_tags 对账 + 修剪）
  * 评分/收藏/阅读状态跨重启保留、重扫不丢
  * FTS 检索：画师别名、社团名、标题子串、标签均命中
  * 收藏集 CRUD、阅读状态端点、统计、备份 list/restore/export、导出端点
  * 改名/解散联动（key 迁移不丢用户数据）
  * 回滚：删 meta.db → 系统回到 2.15 行为
"""
import json
import os
import sys
import zipfile
from urllib.parse import quote

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
import common  # noqa: E402
from conftest import wait_rescan_quiet  # noqa: E402
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
    saved_known = dict(app.state.known)
    yield root
    app.state.known.clear()
    app.state.known.update(saved_known)
    app.state.index_keys.clear()


# ---------- 首启迁移：config 三键 → DB，幂等，不写穿 config ----------

def test_migration_from_config_idempotent(monkeypatch):
    monkeypatch.setitem(app.CFG, "author_aliases", {"飞天御姐流": "hiten"})
    monkeypatch.setitem(app.CFG, "dissolved_circles", ["已解散社"])
    monkeypatch.setitem(app.CFG, "artist_circles", {"画师X": ["社团X"]})
    assert meta_store.author_aliases() == {"飞天御姐流": "hiten"}
    assert meta_store.dissolved_circles() == {"已解散社"}
    assert meta_store.artist_circles() == {"画师X": {"社团X"}}
    # 幂等：关连接重开（等价重启）后再读一致，且不重复堆积
    meta_store.close()
    assert meta_store.author_aliases() == {"飞天御姐流": "hiten"}
    assert meta_store.dissolved_circles() == {"已解散社"}
    assert meta_store.artist_circles() == {"画师X": {"社团X"}}
    # 不写穿 config：迁移全程不落 config.json
    assert not os.path.exists(common.CONFIG_FILE)


def test_db_wins_over_legacy_config(monkeypatch):
    """合并视图 DB 权威：同别名冲突时以 DB 为准。"""
    monkeypatch.setitem(app.CFG, "author_aliases", {"A": "旧正名"})
    meta_store.upsert_alias("A", "新正名")
    assert app._author_aliases()["A"] == "新正名"


# ---------- 扫描同步对账 ----------

def test_sync_scan_reconciliation(lib_env):
    circ = lib_env / "社团A (画师甲)"
    circ.mkdir()
    _make_zip(circ / "[社团A (画师甲)] 作品一 (C102).zip", pages=5)
    fd = circ / "作品二文件夹"
    fd.mkdir()
    (fd / "001.jpg").write_bytes(JPG)
    app.get_library(force=True)
    c = meta_store._connect()
    keys = {r[0] for r in c.execute("SELECT key FROM works")}
    assert keys == {"社团A (画师甲)/[社团A (画师甲)] 作品一 (C102)",
                    "社团A (画师甲)/作品二文件夹"}
    w = c.execute("SELECT pages, kind, size, circle, group_name FROM works WHERE key=?",
                  ("社团A (画师甲)/[社团A (画师甲)] 作品一 (C102)",)).fetchone()
    assert w[0] == 5 and w[1] == "archive" and w[2] == os.path.getsize(str(circ / "[社团A (画师甲)] 作品一 (C102).zip"))
    assert w[3] == "社团A" and w[4] == "社团A (画师甲)"
    authors = {r[0] for r in c.execute("SELECT author FROM work_authors WHERE key=?",
                                       ("社团A (画师甲)/[社团A (画师甲)] 作品一 (C102)",))}
    assert authors == {"画师甲"}
    tags = {(r[0], r[1]) for r in c.execute("SELECT type, name FROM work_tags WHERE key=?",
                                            ("社团A (画师甲)/[社团A (画师甲)] 作品一 (C102)",))}
    assert ("event", "C102") in tags and ("personal", "画师甲") in tags
    # 修剪：作品删除后派生行消失
    os.remove(str(circ / "[社团A (画师甲)] 作品一 (C102).zip"))
    app.get_library(force=True)
    keys2 = {r[0] for r in c.execute("SELECT key FROM works")}
    assert keys2 == {"社团A (画师甲)/作品二文件夹"}


def test_user_facts_survive_rescan_and_restart(lib_env):
    circ = lib_env / "社团A"
    circ.mkdir()
    _make_zip(circ / "[社团A] 作品.zip")
    app.get_library(force=True)
    client = app.app.test_client()
    key = "社团A/[社团A] 作品"
    assert client.post("/api/meta/rating", json={"key": key, "score": 5, "favorite": True}
                       ).status_code == 200
    assert client.post("/api/reading/state",
                       json={"key": key, "last_page": 2}).status_code == 200
    for _ in range(2):
        app.get_library(force=True)             # 重扫不丢
    meta_store.close()                          # 模拟重启（连接重开）
    j = client.get("/api/meta/work?key=" + quote(key)).get_json()
    assert j["ok"] and j["rating"]["score"] == 5 and j["rating"]["favorite"] is True
    assert j["reading"]["last_page"] == 2 and not j["reading"]["finished"]


# ---------- FTS / 检索 ----------

def test_search2_hits_alias_circle_title_tag(lib_env):
    circ = lib_env / "社团H"
    circ.mkdir()
    _make_zip(circ / "[社团H (hiten)] 星空下的旅行记 (C102).zip")
    client = app.app.test_client()
    client.post("/api/author-aliases", json={"alias": "飞天御姐流", "canonical": "hiten"})
    app.get_library(force=True)
    # 画师别名命中（归一到正名 hiten）
    r1 = client.get("/api/search2?q=" + quote("飞天御姐流")).get_json()
    assert len(r1["works"]) == 1 and r1["works"][0]["authors"] == ["hiten"]
    # 画师正名命中
    assert len(client.get("/api/search2?q=hiten").get_json()["works"]) == 1
    # 社团名命中
    assert len(client.get("/api/search2?q=" + quote("社团H")).get_json()["works"]) == 1
    # 标题子串命中（≥3 字走 FTS trigram，2 字走 LIKE 兜底，两条路都要通）
    assert len(client.get("/api/search2?q=" + quote("星空下的旅行")).get_json()["works"]) == 1
    assert len(client.get("/api/search2?q=" + quote("星空")).get_json()["works"]) == 1
    # 标签命中（展会词条 C102）
    assert len(client.get("/api/search2?q=C102").get_json()["works"]) == 1
    # 多词 AND + 无命中
    assert len(client.get("/api/search2?q=" + quote("星空 社团H")).get_json()["works"]) == 1
    assert client.get("/api/search2?q=" + quote("不存在的词")).get_json()["works"] == []


# ---------- 收藏集 CRUD ----------

def test_collections_crud(lib_env):
    circ = lib_env / "社团A"
    circ.mkdir()
    _make_zip(circ / "[社团A] 作品.zip")
    app.get_library(force=True)
    client = app.app.test_client()
    key = "社团A/[社团A] 作品"
    r = client.post("/api/meta/collections", json={"action": "create", "name": "最爱"})
    assert r.status_code == 200, r.get_json()
    cid = r.get_json()["id"]
    assert client.post("/api/meta/collections", json={"action": "create", "name": "最爱"}
                       ).status_code == 400     # 重名拒绝
    assert client.post("/api/meta/collections",
                       json={"action": "add", "id": cid, "key": key}).status_code == 200
    lst = client.get("/api/meta/collections").get_json()["collections"]
    assert lst == [{"id": cid, "name": "最爱", "count": 1}]
    got = client.get("/api/meta/collection?id=%d" % cid).get_json()
    assert got["name"] == "最爱" and got["items"][0]["key"] == key
    assert got["items"][0]["group"] == "社团A" and got["items"][0]["pages"] == 3
    # 收藏集元数据可查（与 /api/meta/work 交叉一致）
    wm = client.get("/api/meta/work?key=" + quote(key)).get_json()
    assert wm["collections"] == [{"id": cid, "name": "最爱"}]
    assert client.post("/api/meta/collections",
                       json={"action": "rename", "id": cid, "name": "精挑"}).status_code == 200
    assert client.post("/api/meta/collections",
                       json={"action": "remove", "id": cid, "key": key}).status_code == 200
    assert client.get("/api/meta/collection?id=%d" % cid).get_json()["items"] == []
    # 收藏变更触发备份快照（时间机器）
    assert any(b["file"].startswith("meta_") for b in
               client.get("/api/backup/list").get_json()["backups"])
    assert client.post("/api/meta/collections",
                       json={"action": "delete", "id": cid}).status_code == 200
    assert client.get("/api/meta/collection?id=%d" % cid).status_code == 404


# ---------- 阅读状态 / 统计 / mark-seen ----------

def test_reading_stats_and_mark_seen(lib_env, monkeypatch):
    for i in (1, 2):
        circ = lib_env / ("社团%d" % i)
        circ.mkdir()
        _make_zip(circ / ("作品%d.zip" % i), pages=4)   # 目录=社团，文件名=作品名 → key 社团N/作品N
    app.get_library(force=True)
    # 可控时钟：两次上报拉开时间差（真实秒级时间戳同秒并列会让次序不稳）
    clock = {"t": 1_000_000.0}

    def _fake_time():
        clock["t"] += 10
        return clock["t"]

    monkeypatch.setattr(meta_store.time, "time", _fake_time)
    client = app.app.test_client()
    assert client.post("/api/reading/state",
                       json={"key": "社团1/作品1", "last_page": 4, "finished": True}
                       ).status_code == 200
    assert client.post("/api/reading/state",
                       json={"key": "社团2/作品2", "last_page": 1}).status_code == 200
    j = client.get("/api/reading/state?key=" + quote("社团1/作品1")).get_json()
    assert j["finished"] is True and j["last_page"] == 4
    # 3.2.1:已读完(社团1)不再出现在继续阅读里
    resume = client.get("/api/reading/resume").get_json()["items"]
    assert [x["key"] for x in resume] == ["社团2/作品2"]
    assert resume[0]["pages"] == 4 and resume[0]["group"] == "社团2"
    st = client.get("/api/stats/overview").get_json()
    assert st["works"] == 2 and st["pages"] == 8 and st["finished"] == 1 and st["started"] == 2
    assert st["circles"] == 2
    p1 = client.post("/api/reading/mark-seen", json={}).get_json()["previous"]
    p2 = client.post("/api/reading/mark-seen", json={}).get_json()["previous"]
    assert p2 >= p1 and p2 > 0
    st2 = client.get("/api/stats/overview").get_json()
    assert st2["last_visit_at"] > p2          # 库里存的是最新一次访问时间


# ---------- 备份时间机器 ----------

def test_backup_snapshot_and_restore(lib_env):
    circ = lib_env / "社团A"
    circ.mkdir()
    _make_zip(circ / "[社团A] 作品.zip")
    app.get_library(force=True)
    client = app.app.test_client()
    key = "社团A/[社团A] 作品"
    client.post("/api/meta/rating", json={"key": key, "score": 5})
    snap = meta_store.snapshot("手动快照")
    assert snap and os.path.exists(os.path.join(str(meta_store.BACKUP_DIR), snap))
    client.post("/api/meta/rating", json={"key": key, "score": 1})   # 破坏现场
    lst = client.get("/api/backup/list").get_json()["backups"]
    assert any(b["file"] == snap and b["note"] == "手动快照" for b in lst)
    r = client.post("/api/backup/restore", json={"file": snap})
    assert r.status_code == 200, r.get_json()
    j = client.get("/api/meta/work?key=" + quote(key)).get_json()
    assert j["rating"]["score"] == 5                      # 恢复成功
    # 恢复前自动快照存在（恢复本身可撤销）
    lst2 = client.get("/api/backup/list").get_json()["backups"]
    assert any("恢复前" in (b["note"] or "") for b in lst2)
    # 非法文件名拒绝
    assert client.post("/api/backup/restore", json={"file": "../evil.db"}).status_code == 400


def test_backup_export_json(lib_env):
    client = app.app.test_client()
    r = client.get("/api/backup/export")
    assert r.status_code == 200
    data = json.loads(r.data.decode("utf-8"))
    assert data["schema"] == 1 and "works" in data["tables"] and "ratings" in data["tables"]
    assert "attachment" in r.headers.get("Content-Disposition", "")


# ---------- 改名 / 解散联动 ----------

def test_rename_circle_moves_keys_and_facts(lib_env):
    circ = lib_env / "社团A"
    circ.mkdir()
    _make_zip(circ / "[社团A] 作品.zip")
    app.get_library(force=True)
    client = app.app.test_client()
    client.post("/api/meta/rating", json={"key": "社团A/[社团A] 作品", "score": 4})
    client.post("/api/reading/state", json={"key": "社团A/[社团A] 作品", "last_page": 1})
    r = client.post("/api/rename-circle", json={"group": "社团A", "new_name": "社团B"})
    assert r.status_code == 200, r.get_json()
    app.get_library(force=True)                 # 重扫后 DB 与新目录对账
    c = meta_store._connect()
    keys = {row[0] for row in c.execute("SELECT key FROM works")}
    assert keys == {"社团B/[社团A] 作品"}
    j = client.get("/api/meta/work?key=" + quote("社团B/[社团A] 作品")).get_json()
    assert j["rating"]["score"] == 4 and j["reading"]["last_page"] == 1   # 关联跟随
    assert client.get("/api/meta/work?key=" + quote("社团A/[社团A] 作品")).status_code == 404


def test_dissolve_marks_circle_in_db(lib_env):
    circ = lib_env / "社团甲"
    circ.mkdir()
    _make_zip(circ / "[社团甲] 作品.zip")
    app.get_library(force=True)
    client = app.app.test_client()
    r = client.post("/api/dissolve-circle", json={"group": "社团甲"})
    assert r.status_code == 200, r.get_json()
    assert "社团甲" in meta_store.dissolved_circles()
    # 重启不失忆
    meta_store.close()
    assert "社团甲" in meta_store.dissolved_circles()


def test_apply_rename_migrates_work_key(lib_env):
    d = lib_env / "待整理"
    d.mkdir()
    _make_zip(d / "[社团R] 待归档作品 (C99).zip")
    app.get_library(force=True)
    client = app.app.test_client()
    old_key = "待整理/[社团R] 待归档作品 (C99)"
    client.post("/api/meta/rating", json={"key": old_key, "score": 3})
    lib = app.get_library()
    g = next(g for g in lib["groups"] if g["name"] == "待整理")
    w = next(w for w in g["works"] if "待归档作品" in w["name"])
    ok, msg = app._apply_rename(w, "[社团R] 待归档作品 (C99).zip")
    assert ok and "归档到" in msg, msg
    new_key = "社团R/[社团R] 待归档作品 (C99)"
    j = client.get("/api/meta/work?key=" + quote(new_key)).get_json()
    assert j["ok"] and j["rating"]["score"] == 3, j   # 用户数据随 key 迁移
    assert wait_rescan_quiet(), "SWR 后台重扫应静默完成"   # 3.3.0：stale 窗口内旧 key 仍可经扫描回退命中
    assert client.get("/api/meta/work?key=" + quote(old_key)).status_code == 404


# ---------- 导出端点 ----------

def test_export_manifest_and_file(lib_env):
    circ = lib_env / "社团A"
    circ.mkdir()
    zpath = circ / "[社团A (画师乙)] 作品.zip"
    _make_zip(zpath, pages=4)
    fdir = lib_env / "社团A" / "文件夹作品"
    fdir.mkdir()
    (fdir / "001.jpg").write_bytes(JPG)
    app.get_library(force=True)
    client = app.app.test_client()
    m = client.get("/api/export/manifest?group=" + quote("社团A") + "&work=" + quote("[社团A (画师乙)] 作品")).get_json()
    assert m["ok"] and m["downloadable"] is True
    assert m["size"] == os.path.getsize(str(zpath)) and m["pages"] == 4
    assert m["file"] == "[社团A (画师乙)] 作品.zip"      # 原始文件名（APP 本地落盘用）
    assert m["personals"] == ["画师乙"] and m["circle"] == "社团A"
    r = client.get("/api/export/file?group=" + quote("社团A") + "&work=" + quote("[社团A (画师乙)] 作品"))
    assert r.status_code == 200 and r.data == zpath.read_bytes()   # 保原图
    # Range 断点续传（send_file conditional）
    rr = client.get("/api/export/file?group=" + quote("社团A") + "&work=" + quote("[社团A (画师乙)] 作品"),
                    headers={"Range": "bytes=0-9"})
    assert rr.status_code == 206 and len(rr.data) == 10
    # 文件夹作品：manifest 不可下载标志 + file 400
    mf = client.get("/api/export/manifest?group=" + quote("社团A") + "&work=" + quote("文件夹作品")).get_json()
    assert mf["ok"] and mf["downloadable"] is False and mf["kind"] == "folder"
    assert client.get("/api/export/file?group=" + quote("社团A") + "&work=" + quote("文件夹作品")
                      ).status_code == 400
    assert client.get("/api/export/manifest?group=无&work=无").status_code == 404


# ---------- 回滚：删 meta.db → 回到 2.15 行为 ----------

def test_rollback_delete_metadb(lib_env):
    circ = lib_env / "社团A"
    circ.mkdir()
    _make_zip(circ / "[社团A] 作品.zip")
    app.get_library(force=True)
    client = app.app.test_client()
    client.post("/api/meta/rating", json={"key": "社团A/[社团A] 作品", "score": 2})
    meta_store.close()
    for suf in ("", "-wal", "-shm"):
        p = str(meta_store.DB_PATH) + suf
        if os.path.exists(p):
            os.unlink(p)
    # 库没了：扫描照常（2.15 行为），派生表随首扫重新回填，用户附加数据随库消失（快照可恢复）
    lib = app.get_library(force=True)
    names = {w["name"] for g in lib["groups"] for w in g["works"]}
    assert names == {"[社团A] 作品"}
    j = client.get("/api/meta/work?key=" + quote("社团A/[社团A] 作品")).get_json()
    assert j["ok"] and j["rating"]["score"] == 0 and j["rating"]["favorite"] is False
    assert client.get("/api/backup/list").status_code == 200


# ---------- API 1 兼容：/api/library 结构不变 ----------

def test_api_library_shape_unchanged(lib_env):
    circ = lib_env / "社团A"
    circ.mkdir()
    _make_zip(circ / "[社团A] 作品.zip")
    client = app.app.test_client()
    j = client.get("/api/library").get_json()
    assert j["ok"] and j["groups"][0]["name"] == "社团A"
    assert set(j.keys()) >= {"ok", "groups", "tags", "recommendations", "scan_ms",
                             "scanned_at", "rev", "sort", "order"}
    assert app.SERVER_API_LEVEL == 1


# ---------- 3.6.10 删除兜底闸门：扫描结果骤减时不得整表清空 ----------

def _seed_works(c, n):
    c.executemany("INSERT OR IGNORE INTO works(key, group_name, name, path, mtime, kind)"
                  " VALUES(?,?,?,?,?,?)",
                  [("社团S/作品%d" % i, "社团S", "作品%d" % i, "/x/%d" % i, 1000 + i, "archive")
                   for i in range(n)])


def test_sync_scan_refuses_mass_prune(lib_env):
    """库中 60 行、本次只扫到 1 部作品 → 判定异常扫描，只 upsert 不删（防整表清空）。"""
    con = meta_store._connect()
    c = con.cursor()
    _seed_works(c, 60)
    con.commit()
    before = c.execute("SELECT count(*) FROM works").fetchone()[0]
    assert before == 60

    circ = lib_env / "社团A"
    circ.mkdir()
    _make_zip(circ / "[社团A] 作品.zip")
    meta_store.sync_scan(app.scan_groups(str(lib_env)))

    after = c.execute("SELECT count(*) FROM works").fetchone()[0]
    assert after == 61, "异常扫描不该删旧行（新增 1 部，原有 60 部保留）"
    con.close()


def test_sync_scan_still_prunes_normal_deletes(lib_env):
    """对照组：正常规模（库中 5 行、扫到 1 行）仍照常修剪，不能把闸门做成一律不删。"""
    con = meta_store._connect()
    c = con.cursor()
    _seed_works(c, 5)
    con.commit()

    circ = lib_env / "社团A"
    circ.mkdir()
    _make_zip(circ / "[社团A] 作品.zip")
    meta_store.sync_scan(app.scan_groups(str(lib_env)))

    left = set(r[0] for r in c.execute("SELECT key FROM works"))
    assert left == {"社团A/[社团A] 作品"}
    con.close()


# ---------- 3.6.10 删除兜底闸门：扫描结果骤减时不得整表清空 ----------

def _seed_works(c, n):
    c.executemany("INSERT OR IGNORE INTO works(key, group_name, name, path, mtime, kind)"
                  " VALUES(?,?,?,?,?,?)",
                  [("社团S/作品%d" % i, "社团S", "作品%d" % i, "/x/%d" % i, 1000 + i, "archive")
                   for i in range(n)])


def test_sync_scan_refuses_mass_prune(lib_env):
    """库中 60 行、本次只扫到 1 部作品 → 判定异常扫描，只 upsert 不删（防整表清空）。"""
    con = meta_store._connect()
    c = con.cursor()
    _seed_works(c, 60)
    con.commit()
    before = c.execute("SELECT count(*) FROM works").fetchone()[0]
    assert before == 60

    circ = lib_env / "社团A"
    circ.mkdir()
    _make_zip(circ / "[社团A] 作品.zip")
    meta_store.sync_scan(app.scan_groups(str(lib_env)))

    after = c.execute("SELECT count(*) FROM works").fetchone()[0]
    assert after == 61, "异常扫描不该删旧行（新增 1 部，原有 60 部保留）"
    con.close()


def test_sync_scan_still_prunes_normal_deletes(lib_env):
    """对照组：正常规模（库中 5 行、扫到 1 行）仍照常修剪，不能把闸门做成一律不删。"""
    con = meta_store._connect()
    c = con.cursor()
    _seed_works(c, 5)
    con.commit()

    circ = lib_env / "社团A"
    circ.mkdir()
    _make_zip(circ / "[社团A] 作品.zip")
    meta_store.sync_scan(app.scan_groups(str(lib_env)))

    left = set(r[0] for r in c.execute("SELECT key FROM works"))
    assert left == {"社团A/[社团A] 作品"}
    con.close()
