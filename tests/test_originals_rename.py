# -*- coding: utf-8 -*-
"""原作分区的改名/合并/别名链与全半角互通（3.6.83 从 test_originals_manual.py 拆出）。"""
import json
import os
import sys
import time
import zipfile
from urllib.parse import quote

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
import common  # noqa: E402
import meta_store  # noqa: E402

from _originals_helpers import (  # noqa: E402
    JPG, TERM, KEY, KEY2, _has_original, _make_zip, _seed, _seed_builtin, _seed_fgo, lib_env,
)

KEYC = "社团C/[社团C] 内置原作测试 (FateGrand Order)"


def test_rename_builtin_zone_keeps_alias_and_does_not_revive(lib_env):
    """3.6.28 报障回归：内置名单分区（config 词条库里没有、靠 djc_parse 内置
    词条解析产出）**真改名**（宽松串不同的新名）后，旧分区不得因内置词条
    重新产出而复活。修复 = 旧名会被解析器产出时自动留别名（DB 别名优先于名单）。"""
    _seed(lib_env)
    _seed_builtin(lib_env)
    client = app.app.test_client()
    # sanity：分区由内置名单解析产出；config 词条库为空（内置词条删不掉）
    assert _has_original(KEYC, "FateGrand Order")
    assert "FateGrand Order" not in (app.CFG.get("originals") or [])
    assert app.state.norm_to_canon.get(app._dp._norm("FateGrand Order")) == "FateGrand Order"
    j = client.post("/api/originals/rename",
                    json={"from": "FateGrand Order", "to": "FGO合集"}).get_json()
    assert j["ok"] and j["moved"] == 1 and j["merged"] is False
    assert j["keep_alias"] is True          # 旧名会被内置名单重新产出 → 强制留别名
    zones = {z["name"]: z["works"]
             for z in client.get("/api/originals").get_json()["originals"]}
    assert zones == {"FGO合集": 1}           # 旧分区当场消失
    # 重扫不复活：文件名里的 (FateGrand Order) 经别名折叠到新名
    app.get_library(force=True)
    zones = {z["name"]: z["works"]
             for z in client.get("/api/originals").get_json()["originals"]}
    assert zones == {"FGO合集": 1}
    assert _has_original(KEYC, "FGO合集") and not _has_original(KEYC, "FateGrand Order")


def test_merge_builtin_zone_into_existing_does_not_revive(lib_env):
    """3.6.28 报障回归（归并形态）：内置名分区改名到**既有分区**（宽松串不同）
    → merged；重扫后旧分区不得复活、作品不丢标签。"""
    _seed(lib_env)
    _seed_fgo(lib_env)
    _seed_builtin(lib_env)
    client = app.app.test_client()
    j = client.post("/api/originals/add", json={"term": "FGO"}).get_json()
    assert j["ok"] and j["hits"] == 1       # FGO 分区：KEY2（manual original）
    j2 = client.post("/api/originals/rename",
                     json={"from": "FateGrand Order", "to": "FGO"}).get_json()
    assert j2["ok"] and j2["merged"] is True and j2["moved"] == 1
    assert j2["keep_alias"] is True         # 内置名旧分区 → 强制留别名压制复活
    zones = {z["name"]: z["works"]
             for z in client.get("/api/originals").get_json()["originals"]}
    assert zones == {"FGO": 2}
    app.get_library(force=True)
    zones = {z["name"]: z["works"]
             for z in client.get("/api/originals").get_json()["originals"]}
    assert zones == {"FGO": 2}              # FateGrand Order 分区不复活
    assert _has_original(KEYC, "FGO") and not _has_original(KEYC, "FateGrand Order")


# ---------- 3.6.36 #34：空原作分区 ----------

def test_api_originals_includes_empty_zones_from_config(lib_env):
    """config 词条库里用户显式添加、但库内暂无作品的分区也展示（0 部）；
    内置名单（DEFAULT_ORIGINALS）不合并——否则首页会冒出几十个空分区。"""
    _seed(lib_env)
    client = app.app.test_client()
    zones = {z["name"]: z["works"]
             for z in client.get("/api/originals").get_json()["originals"]}
    # 内置名单（DEFAULT_ORIGINALS）不合并——否则首页会冒出几十个空分区
    assert "\u6771\u65b9Project" not in zones
    # 用户显式加进 config 词条库、但库内暂无作品 → 空分区入列（0 部）
    app.CFG["originals"] = ["空测试区"]
    zones = {z["name"]: z["works"]
             for z in client.get("/api/originals").get_json()["originals"]}
    assert zones.get("空测试区") == 0


def test_originals_add_empty_mode_creates_no_tags(lib_env):
    """empty=true：只建空分区（词条库落名、不搜作品、不写标签）。"""
    _seed(lib_env)
    client = app.app.test_client()
    r = client.post("/api/originals/add", json={"term": "手动分区", "empty": True})
    assert r.get_json()["ok"] and r.get_json()["empty"] is True
    assert r.get_json()["hits"] == 0
    assert "手动分区" in app.CFG["originals"]
    c = meta_store._connect()
    assert c.execute("SELECT count(*) FROM work_tags WHERE type='original' AND name='手动分区'"
                     ).fetchone()[0] == 0             # 不写任何标签
    zones = {z["name"]: z["works"]
             for z in client.get("/api/originals").get_json()["originals"]}
    assert zones.get("手动分区") == 0                 # 列表可见（0 部）


def test_originals_add_rejects_empty_name(lib_env):
    client = app.app.test_client()
    r = client.post("/api/originals/add", json={"term": "  ", "empty": True})
    assert r.status_code == 400


# ---------- 3.6.36 #33：分区内手动添加作品 ----------

def test_originals_add_works_endpoint(lib_env):
    """add-works：把指定作品写进分区的 original 标签（分区不在词条库时顺带落名）。"""
    _seed(lib_env)
    client = app.app.test_client()
    keys = [r[0] for r in meta_store._connect().execute(
        "SELECT key FROM works").fetchall()]
    assert keys
    r = client.post("/api/originals/add-works",
                    json={"zone": "手动归类", "keys": keys})
    j = r.get_json()
    assert j["ok"] and j["added"] == len(keys)
    for k in keys:
        assert _has_original(k, "手动归类")
    assert "手动归类" in app.CFG["originals"]          # 词条库顺带落名


def test_originals_add_works_rejects_bad_input(lib_env):
    client = app.app.test_client()
    assert client.post("/api/originals/add-works",
                       json={"zone": "", "keys": ["a/b"]}).status_code == 400
    assert client.post("/api/originals/add-works",
                       json={"zone": "X", "keys": []}).status_code == 400


# ---------- 3.6.36 #33：分区内手动添加作品 ----------


def test_add_works_shows_up_in_zone_after_rescan(lib_env):
    """3.6.38 #36：add-works 写的标签必须能在分区内看见。
    复现过的真 bug：标签只落 DB，LIB 的 work.tags 只有解析产出，
    /api/works?type=original 过滤 LIB → force 重扫后分区仍 0 部。
    修法：_do_scan 里 _merge_manual_originals 把 DB 标签回填 LIB。"""
    _seed(lib_env)
    client = app.app.test_client()
    client.post("/api/originals/add", json={"term": "回填测试区", "empty": True})
    c = meta_store._connect()
    keys = [r[0] for r in c.execute("SELECT key FROM works").fetchall()]
    assert keys
    r = client.post("/api/originals/add-works", json={"zone": "回填测试区", "keys": keys})
    assert r.get_json()["ok"]
    # 避开 get_library 的"同 tick 不重扫"优化（scanned_at>=arrived 直接返旧缓存），
    # 确保本次真的走一轮 _do_scan（_merge_manual_originals 在其中）
    # 避开 get_library 的"同 tick 不重扫"优化，确保真的走一轮 _do_scan
    time.sleep(0.05)
    app.get_library(force=True)
    import urllib.parse
    d = client.get("/api/works?type=original&tag="
                   + urllib.parse.quote("回填测试区")).get_json()
    assert len(d.get("works") or []) == len(keys)   # 分区内全部可见
    # LIB 内存里也能看到标签（面板分区计数/首页都走这条）
    zmap = {z["name"]: z["works"]
            for z in client.get("/api/originals").get_json()["originals"]}
    assert zmap.get("回填测试区") == len(keys)


# ---------- 3.6.38 #38：全半角宽松归一与检索 ----------

def test_norm_and_loose_fullwidth_halfwidth():
    """全角 ！/半角 ! 在 _norm/_loose 下必须相等（ぼっち・ざ・ろっく！ 报障根因）。"""
    import djc_parse as dp
    a, b = "ぼっち・ざ・ろっく！", "ぼっち・ざ・ろっく!"
    assert dp._norm(a) == dp._norm(b)
    assert meta_store._loose(a) == meta_store._loose(b)
    # 原有宽松变体不回归
    assert meta_store._loose("Fate Grand Order") == meta_store._loose("Fate_Grand_Order")


def test_search_fullwidth_halfwidth(lib_env):
    """搜索域全半角宽松：半角 query 命中全角内容、全角 query 命中半角内容。
    seed 两个作品：文件名全角（ぼっち・ざ・ろっく！）与半角（ぼっち・ざ・ろっく!）各一。"""
    circ = lib_env / "社团D"
    circ.mkdir()
    _make_zip(circ / "[社团D] 全角感叹号作品 (ぼっち・ざ・ろっく！).zip")
    _make_zip(circ / "[社团D] 半角感叹号作品 (ぼっち・ざ・ろっく!).zip")
    app.get_library(force=True)
    client = app.app.test_client()
    import urllib.parse
    for q in ("ぼっち・ざ・ろっく！", "ぼっち・ざ・ろっく!"):
        d = client.get("/api/search?q=" + urllib.parse.quote(q)).get_json()
        assert len(d.get("works") or []) >= 2, f"/api/search 未全半角互通: {q} -> {len(d.get('works') or [])}"
        d2 = client.get("/api/search2?q=" + urllib.parse.quote(q)).get_json()
        assert len(d2.get("works") or []) >= 2, f"/api/search2 未全半角互通: {q} -> {len(d2.get('works') or [])}"


def test_originals_add_fullwidth_halfwidth_zone(lib_env):
    """分区识别全半角宽松：词条库记半角写法，文件名里全角感叹号也应归入。"""
    # 文件名含全角 ！ 的作品 + 词条库记半角 ! 写法
    circ = lib_env / "社团D"
    circ.mkdir()
    _make_zip(circ / "[社团D] 孤独摇滚同人 (ぼっち・ざ・ろっく！).zip")
    app.CFG["originals"] = ["ぼっち・ざ・ろっく!"]
    app.save_config(app.CFG)          # _reload_originals 读的是盘上 config.json
    app.state.originals, app.state.norm_to_canon = app._reload_originals()
    app._dp.NORM_TO_CANON = app.state.norm_to_canon
    app.get_library(force=True)
    c = meta_store._connect()
    rows = c.execute("SELECT name FROM work_tags WHERE type='original' AND key LIKE '社团D/%'"
                     ).fetchall()
    names = {r[0] for r in rows}
    assert "ぼっち・ざ・ろっく!" in names, f"全半角未归一，产出: {names}"


# ---------- 3.6.38 收尾：_loose_term 同步 NFKC + 分区排序 ----------

def test_app_loose_term_matches_meta_loose():
    """app._loose_term 必须与 meta_store._loose **同规则**（含 NFKC）。

    3.6.38 踩过：只给 meta_store._loose 加了 NFKC，漏了 app._loose_term ——
    识别（解析器走 _norm）能过，但 canon 归并与别名判定仍把全角/半角当两个分区。"""
    a, b = "ぼっち・ざ・ろっく！", "ぼっち・ざ・ろっく!"
    assert app._loose_term(a) == app._loose_term(b)
    assert app._loose_term(a) == meta_store._loose(a)      # 两处规则一致
    # 原有宽松变体不回归
    assert app._loose_term("Fate Grand Order") == app._loose_term("Fate_Grand_Order")


def test_originals_sorted_newest_created_first(lib_env):
    """3.6.38 #37：新建的分区置顶（按 config 词条库次序倒序）。

    用户报障：新创建的分区跑到列表底部——因为前端按 latest(最近入库)/作品数排序，
    而新建空分区 latest=0、works=0，怎么排都在最后。"""
    _seed(lib_env)
    client = app.app.test_client()
    app.CFG["originals"] = ["先建的分区", "后建的分区"]
    app.save_config(app.CFG)
    app.state.originals, app.state.norm_to_canon = app._reload_originals()
    names = [z["name"] for z in client.get("/api/originals").get_json()["originals"]]
    # 两个都是空分区（config 里有、库内无作品）也要出现，且后建的排最前
    assert names[:2] == ["后建的分区", "先建的分区"], names


def test_canon_original_prefers_existing_zone(lib_env, monkeypatch):
    """3.6.39 #38：多个候选宽松相等时，优先归到**库里已存在的实际分区**。

    用户原话："Fate／Grand Order 和 FateGrand Order 本身就是一个类别"。
    归一判断本来就是通的（全角/空格/斜杠一律相等），但"目标名"该选哪个很关键：
    选一个只有写法规范、却没作品的幽灵名，等于把作品从既有分区里拽出来另立门户——
    归一反而制造分裂。所以优先级：有作品的既有分区 > 空分区 > 规范形态 > 名单首位。
    """
    _seed(lib_env)
    # 两个候选宽松相等：全角写法 NFKC 后与半角相同；用假名单隔离内置项干扰
    fake = {"a": "Ｆａｔｅ试验", "b": "Fate试验", "c": "另一个原作"}
    monkeypatch.setattr(app.state, "norm_to_canon", fake)
    # 库里只有半角那个分区有作品
    meta_store.originals_add("Fate试验", [KEY])
    assert app._canon_original("fate试验") == "Fate试验"
    assert app._canon_original("Fate试验") == "Fate试验"
    # 两个都不存在时，退回"本身已是规范形态"的那个（不落到全角写法）
    monkeypatch.setattr(app.state, "norm_to_canon", {"a": "Ｆａｔｅ空试验", "b": "Fate空试验"})
    assert app._canon_original("fate空试验") == "Fate空试验"


def test_alias_chain_survives_zone_rename(lib_env):
    """3.6.39 报障预演：别名链 + 分区改名叠加，旧词条写法必须落进改名后的分区。

    用户场景：`ブルーアーカイブ → Blue Archive` 已登记；随后把 Blue Archive 分区
    改名为「蔚蓝档案」，再登记 `Blue Archive → 蔚蓝档案`。此时导入含
    ブルーアーカイブ 的作品——别名链是 A→B→C，解析映射若只折叠**一层**（A→B），
    标签会落回旧名 B，作品既进不了 C，还会把 B 分区复活。
    """
    circ = lib_env / "社团BA"
    circ.mkdir()
    _make_zip(circ / "[社团BA] 蔚蓝本1 (ブルーアーカイブ).zip")
    app.get_library(force=True)
    client = app.app.test_client()
    names = {z["name"] for z in client.get("/api/originals").get_json()["originals"]}
    assert "ブルーアーカイブ" in names, names        # 内置名单里它是独立分区名

    j = client.post("/api/author-aliases", json={
        "alias": "ブルーアーカイブ", "canonical": "Blue Archive", "kind": "original"}).get_json()
    assert j["ok"], j
    j = client.post("/api/originals/rename",
                    json={"from": "Blue Archive", "to": "蔚蓝档案"}).get_json()
    assert j["ok"], j
    j = client.post("/api/author-aliases", json={
        "alias": "Blue Archive", "canonical": "蔚蓝档案", "kind": "original"}).get_json()
    assert j["ok"], j

    # 新导入一份含旧词条写法（ブルーアーカイブ）的作品
    _make_zip(circ / "[社团BA] 蔚蓝本2 (ブルーアーカイブ).zip")
    app.get_library(force=True)
    zones = {z["name"]: z["works"]
             for z in client.get("/api/originals").get_json()["originals"]}
    assert "Blue Archive" not in zones, f"旧名分区被复活：{zones}"
    assert zones.get("蔚蓝档案") == 2, f"新作品没进改名后的分区：{zones}"
    # 改名同时要把"指向旧名"的别名改指向新名（A→B 变 A→C），
    # 否则旧写法还得靠链式折叠兜底；这是同一隐患的另一半。
    assert app.meta.original_aliases().get("ブルーアーカイブ") == "蔚蓝档案"


def test_rescan_folds_stale_old_zone_tags(lib_env):
    """3.6.41：改名残留的旧名 original 标签，重扫时必须折叠到正名。

    用户报障"改名之后旧分区依旧复活"。真因不是复活，而是**旧标签从未被清**：
    sync_scan 此前把所有既有 original 行当 manual 无条件放行（3.6.19 的保守做法），
    于是 old 名（通常还在内置名单里）永远挂在列表里。真实库里实测
    Blue Archive 94 部 + 碧藍檔案 95 部并存——同一批作品挂了新旧两行。
    """
    _seed(lib_env)                     # 作品文件名含 (Fate_Grand_Order)
    key = KEY
    meta_store.originals_add("Fate Grand Order", [key])      # 旧名标签（改名残留）
    meta_store.upsert_alias("Fate Grand Order", "Fate新名", "original")
    app.state.originals, app.state.norm_to_canon = app._reload_originals()
    app._dp.NORM_TO_CANON = app.state.norm_to_canon

    app.get_library(force=True)        # 重扫 → 折叠
    rows = {n for k, n in meta_store.original_tags_all() if k == key}
    assert rows == {"Fate新名"}, f"旧名标签未折叠/未清理：{rows}"
    zones = {z["name"] for z in meta_store.originals_all()}
    assert "Fate Grand Order" not in zones, zones
    # manual 标签语义不变：别名链以外的标签不被删
    meta_store.originals_add("用户手加的原作", [key])
    app.get_library(force=True)
    rows = {n for k, n in meta_store.original_tags_all() if k == key}
    assert "用户手加的原作" in rows and "Fate新名" in rows, rows


def test_add_works_reports_unmatched_and_is_visible_immediately(lib_env):
    """3.6.41：手动添加作品——key 解析失败要如实报错（不写悬空标签），
    且返回时立刻可查（改为同步 force 重扫；原来只 _lib_touch 异步，
    前端 onAdded 立刻刷新拿到旧缓存 → 用户以为"添加失败"）。"""
    _seed(lib_env)
    client = app.app.test_client()
    j = client.post("/api/originals/add-works",
                    json={"zone": "测试手动区", "keys": [KEY]}).get_json()
    assert j["ok"] and j["added"] == 1, j
    # 不下拉刷新、不等后台重扫，立刻查分区作品
    ws = client.get("/api/works?type=original&tag=测试手动区").get_json()["works"]
    assert len(ws) == 1, ws
    # 重复添加：新增 0 部（前端据此提示"已在本区"）
    j2 = client.post("/api/originals/add-works",
                     json={"zone": "测试手动区", "keys": [KEY]}).get_json()
    assert j2["ok"] and j2["added"] == 0, j2
    # 库里没有的 key：404 + 不写悬空行
    j3 = client.post("/api/originals/add-works",
                     json={"zone": "测试手动区", "keys": ["不存在的社团/不存在的作品"]})
    assert j3.status_code == 404
    rows = [n for k, n in meta_store.original_tags_all()
            if k == "不存在的社团/不存在的作品"]
    assert rows == []


def test_rename_defaults_to_keeping_alias(lib_env):
    """3.6.41：改名默认登记旧名为别名（旧写法重扫时不会复活旧分区）。"""
    _seed(lib_env)
    # 显式挂旧名标签（_seed 文件名里的下划线写法不一定解析成内置的带空格规范名）
    meta_store.originals_add("Fate Grand Order", [KEY])
    client = app.app.test_client()
    j = client.post("/api/originals/rename",
                    json={"from": "Fate Grand Order", "to": "命运冠位指定"}).get_json()
    assert j["ok"], j
    assert j["keep_alias"] is True, j
    assert app.meta.original_aliases().get("Fate Grand Order") == "命运冠位指定"
    zones = {z["name"] for z in client.get("/api/originals").get_json()["originals"]}
    assert "命运冠位指定" in zones and "Fate Grand Order" not in zones, zones
    # 空分区改名（moved=0）未显式要求时不硬留别名
    client.post("/api/originals/add", json={"term": "空区甲乙", "empty": True})
    j2 = client.post("/api/originals/rename",
                     json={"from": "空区甲乙", "to": "空区甲乙改名"}).get_json()
    assert j2["ok"] and j2["keep_alias"] is False, j2


def test_originals_created_order_uses_first_seen(lib_env, monkeypatch):
    """3.6.42 #45：创建次序按「分区首次出现时间」，不按 config 词条库位置。

    用户报障"创建次序逻辑明显有错误"：旧实现按 config 顺序倒序排，而**解析器产出的
    分区根本不在词条库里**（東方Project 81 部、五等分の花嫁…），cfg_index 一律 -1
    → 集体沉底；反过来最近才加进词条的 1~2 部分区顶在最前。
    """
    a = lib_env / "社团老"
    b = lib_env / "社团新"
    a.mkdir()
    b.mkdir()
    _make_zip(a / "[社团老] 老作品 (FateGrand Order).zip")
    _make_zip(b / "[社团新] 新作品 (ブルーアーカイブ).zip")
    app.get_library(force=True)
    # 把两个分区的作品入库时间拉开（added_at 是"分区首次出现时间"的判据）
    import sqlite3
    c2 = sqlite3.connect(meta_store.DB_PATH)
    c2.execute("UPDATE works SET added_at=1000 WHERE key LIKE '社团老/%'")
    c2.execute("UPDATE works SET added_at=2000 WHERE key LIKE '社团新/%'")
    c2.commit()
    c2.close()
    # 只把"老分区"登记进词条库：旧实现会因此把老分区顶到最前
    monkeypatch.setitem(app.CFG, "originals", ["FateGrand Order"])
    client = app.app.test_client()
    names = [z["name"] for z in client.get("/api/originals").get_json()["originals"]]
    assert names[:2] == ["ブルーアーカイブ", "FateGrand Order"], names
    # 新建的空分区视为最新，排最前
    monkeypatch.setitem(app.CFG, "originals", ["FateGrand Order", "刚建的空区"])
    names = [z["name"] for z in client.get("/api/originals").get_json()["originals"]]
    assert names[0] == "刚建的空区", names


def test_alias_page_canon_rename_keeps_old_canon_as_alias(lib_env):
    """3.7.53 别名栏「✏ 改区名」的服务端契约：原作正名 = 原作分区名。

    APP 别名页改名固定带 keep_alias=true 调 /api/originals/rename。期望：
    ① 分区名真的改掉、作品跟着走；② 旧正名立刻变成别名指向新正名；
    ③ 旧正名下已有的别名改指向新正名（别名树不会指向一个已不存在的根）；
    ④ 重扫后旧写法不把旧分区长回来。
    """
    _seed(lib_env)
    meta_store.originals_add(TERM, [KEY])          # 建分区（TERM 不在内置名单，只能手动维护）
    app.state.originals, app.state.norm_to_canon = app._reload_originals()
    app._dp.NORM_TO_CANON = app.state.norm_to_canon
    client = app.app.test_client()
    assert {z["name"]: z["works"] for z in client.get("/api/originals").get_json()["originals"]} == {TERM: 1}

    j = client.post("/api/author-aliases", json={
        "alias": "FGO", "canonical": TERM, "kind": "original"}).get_json()
    assert j["ok"], j                            # 树里已有一支：TERM ← FGO

    j = client.post("/api/originals/rename",
                    json={"from": TERM, "to": "命运冠位指定", "keep_alias": True}).get_json()
    assert j["ok"] and j["moved"] == 1 and j["keep_alias"] is True, j

    zones = {z["name"]: z["works"] for z in client.get("/api/originals").get_json()["originals"]}
    assert zones == {"命运冠位指定": 1}, zones      # 区名真的改了，作品跟着走
    aliases = client.get("/api/author-aliases?kind=original").get_json()["aliases"]
    assert aliases.get(TERM) == "命运冠位指定", aliases   # 旧正名自动并入别名
    assert aliases.get("FGO") == "命运冠位指定", aliases  # 既有别名改指向新正名

    app.get_library(force=True)                    # 重扫：旧写法不得把旧分区长回来
    zones = {z["name"]: z["works"] for z in client.get("/api/originals").get_json()["originals"]}
    assert zones == {"命运冠位指定": 1}, zones
