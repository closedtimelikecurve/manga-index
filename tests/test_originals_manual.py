# -*- coding: utf-8 -*-
"""原作分区的增删查与别名（3.6.83 从 test_originals_manual.py 拆出）。"""
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
import meta_store  # noqa: E402

from _originals_helpers import (  # noqa: E402
    JPG, TERM, KEY, KEY2, _has_original, _make_zip, _seed, _seed_builtin, _seed_fgo, lib_env,
)

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


# ---------- originals_search：子串 + 宽松变体 ----------

def test_originals_search_substring_and_loose(lib_env):
    _seed(lib_env)
    hits = meta_store.originals_search("Fate")
    assert {h["key"] for h in hits} == {KEY}
    # 宽松变体：下划线 vs 空格
    assert {h["key"] for h in meta_store.originals_search("fate grand order")} == {KEY}
    # 社团名参与匹配
    assert len(meta_store.originals_search("社团A")) == 1
    assert meta_store.originals_search("不存在的词条") == []


# ---------- originals_add：幂等 + 重扫保留 ----------

def test_originals_add_idempotent_and_survives_rescan(lib_env):
    _seed(lib_env)
    assert not _has_original(KEY, TERM)     # 词条库无该词 → 解析器不产 original
    keys = [h["key"] for h in meta_store.originals_search("Fate")]
    assert meta_store.originals_add(TERM, keys) == 1
    assert meta_store.originals_add(TERM, keys) == 0          # 幂等
    # 强制重扫：manual original 不被对账删除（3.6.19 核心不变量）
    app.get_library(force=True)
    assert _has_original(KEY, TERM)
    zones = {z["name"]: z["works"] for z in meta_store.originals_all()}
    assert zones.get(TERM) == 1


# ---------- 端点：add/search/remove ----------

def test_originals_endpoints_create_and_remove_zone(lib_env):
    _seed(lib_env)
    client = app.app.test_client()
    # add：落库 + 词条同步进 config 词条库 + zone 出现
    j = client.post("/api/originals/add", json={"term": "Grand Order"}).get_json()
    assert j["ok"] and j["hits"] == 1 and j["added"] == 1
    assert j["canon"] == "Grand Order"
    assert "Grand Order" in app.CFG["originals"]
    assert "Grand Order" in app.state.originals             # 词条库已重载
    zones = {z["name"] for z in client.get("/api/originals").get_json()["originals"]}
    assert "Grand Order" in zones
    # search：只读预览
    j3 = client.get("/api/originals/search?term=Fate").get_json()
    assert j3["ok"] and len(j3["works"]) == 1
    # remove：清标签 + 词条库删词条 + zone 消失
    j4 = client.post("/api/originals/remove", json={"term": "Grand Order"}).get_json()
    assert j4["ok"] and j4["removed"] == 1
    assert "Grand Order" not in app.CFG["originals"]
    assert "Grand Order" not in app.state.originals
    zones = {z["name"] for z in client.get("/api/originals").get_json()["originals"]}
    assert "Grand Order" not in zones
    # 空词条拒绝
    assert client.post("/api/originals/add", json={"term": "  "}).status_code == 400


def test_originals_add_keeps_user_input_verbatim(lib_env):
    """3.6.27 用户需求：创建分区**不做宽松归一**——用户输入什么就建什么分区名。

    （旧行为 3.6.19~3.6.26 会把 "fate grand order" 归一到内置规范名 "FateGrandOrder"。
    用户要求：宽松归一只能出现在"文件名 → 归入分区"的归档路径。）"""
    _seed(lib_env)
    client = app.app.test_client()
    j = client.post("/api/originals/add", json={"term": "fate grand order"}).get_json()
    assert j["ok"] and j["canon"] == "fate grand order"    # 原样落库，不归一
    assert _has_original(KEY, "fate grand order")
    zones = {z["name"] for z in client.get("/api/originals").get_json()["originals"]}
    assert zones == {"fate grand order"}
    # 移除端点仍是模糊操作：任意写法变体都能移除（宽松归一留在这里）
    j2 = client.post("/api/originals/remove", json={"term": "FATE_GRAND_ORDER"}).get_json()
    assert j2["ok"] and j2["removed"] == 1
    assert not _has_original(KEY, "fate grand order")


def test_config_post_clears_stale_original_tags(lib_env):
    """词条库经 /api/config 删词条 → stale manual 标签显式清库（3.6.19）。"""
    _seed(lib_env)
    client = app.app.test_client()
    client.post("/api/originals/add", json={"term": "Grand Order"})
    assert _has_original(KEY, "Grand Order")
    # 从词条库移除该词（清空列表）：manual 标签必须随之清掉
    client.post("/api/config", json={"originals": []})
    assert not _has_original(KEY, "Grand Order")
    assert "Grand Order" not in app.CFG["originals"]


def test_original_alias_registers_normalizes_and_deletes(lib_env):
    """原作别名（3.6.19 #20）：变体 → 规范名，解析器据此把变体括号归并同一分区；
    删除别名后回归 other。"""
    _seed(lib_env)
    client = app.app.test_client()
    j = client.post("/api/author-aliases",
                    json={"alias": "Fate_Grand_Order", "canonical": "FateGrand Order",
                          "kind": "original"}).get_json()
    assert j["ok"]
    # 词条库已叠加别名映射（别名优先于名单）
    assert app.state.norm_to_canon.get("Fate_Grand_Order") == "FateGrand Order"
    # GET 别名清单（kind=original）
    j2 = client.get("/api/author-aliases?kind=original").get_json()
    assert j2["aliases"] == {"Fate_Grand_Order": "FateGrand Order"}
    # 重扫后括号标签归并为 original 规范名
    app.get_library(force=True)
    c = meta_store._connect()
    tags = {(r[0], r[1]) for r in c.execute(
        "SELECT type, name FROM work_tags WHERE key=?", (KEY,))}
    assert ("original", "FateGrand Order") in tags
    assert ("other", "Fate_Grand_Order") not in tags
    # 删除别名 → 词条库重载 → 变体回归 other
    client.post("/api/author-aliases/delete",
                json={"alias": "Fate_Grand_Order", "kind": "original"})
    assert "Fate_Grand_Order" not in app.state.norm_to_canon
    app.get_library(force=True)
    c = meta_store._connect()
    tags = {(r[0], r[1]) for r in c.execute(
        "SELECT type, name FROM work_tags WHERE key=?", (KEY,))}
    assert ("other", "Fate_Grand_Order") in tags


# ---------- 3.6.20 #25：添加原作明示归并，不静默跳转 ----------

def test_originals_search_reports_similar_zones(lib_env):
    """预览返回宽松匹配的既有分区——前端据此提示"已有写法相近的分区"。
    3.6.27 起只提示、不自动并入（添加分区不归一）。"""
    _seed(lib_env)
    client = app.app.test_client()
    # 直接按精确名建分区（add 不再把变体归一到内置规范名）
    meta_store.originals_add("FateGrandOrder", [KEY])
    # 用带空格写法预览：similar 要指出既有分区，且 works 数对得上
    j = client.get("/api/originals/search?term=Fate Grand Order").get_json()
    assert j["ok"] and len(j["works"]) == 1
    assert j["similar"] == [{"name": "FateGrandOrder", "works": 1}]
    # 不相干的词条没有 similar
    j2 = client.get("/api/originals/search?term=社团A").get_json()
    assert j2["similar"] == []


def test_originals_add_reports_existed(lib_env):
    """add 返回 existed：与既有分区**字面**同名（3.6.27 起不再按宽松串判存在）。"""
    _seed(lib_env)
    client = app.app.test_client()
    j = client.post("/api/originals/add", json={"term": "Grand Order"}).get_json()
    assert j["ok"] and j["existed"] is False       # 首次：分区不存在
    # 同名再添加：canon 同名 → existed=True
    j2 = client.post("/api/originals/add", json={"term": "Grand Order"}).get_json()
    assert j2["ok"] and j2["canon"] == "Grand Order" and j2["existed"] is True
    # 仅写法不同的变体不再自动并入：各自成区（用户要的精确控制）
    j3 = client.post("/api/originals/add", json={"term": "grand_order"}).get_json()
    assert j3["ok"] and j3["canon"] == "grand_order" and j3["existed"] is False
    zones = {z["name"] for z in client.get("/api/originals").get_json()["originals"]}
    assert zones == {"Grand Order", "grand_order"}


def test_originals_merge_moves_tags_and_dedups(lib_env):
    """meta 层合并：别名分区标签迁到正名；同作品双标签撞键去重（#26）。"""
    _seed(lib_env)
    keys = [h["key"] for h in meta_store.originals_search("Fate")]
    # 同一作品挂两个原作标签（模拟 FGO 分区与 FateGrand Order 分区各有作品）
    assert meta_store.originals_add("FGO", keys) == 1
    assert meta_store.originals_add("FateGrand Order", keys) == 1
    assert _has_original(KEY, "FGO") and _has_original(KEY, "FateGrand Order")
    zones = {z["name"] for z in meta_store.originals_all()}
    assert zones == {"FGO", "FateGrand Order"}
    # 合并：FGO → FateGrand Order；双标签作品去重后只留正名一行
    moved = meta_store.originals_merge("FateGrand Order", ["FGO"])
    assert moved == 1
    assert not _has_original(KEY, "FGO")
    assert _has_original(KEY, "FateGrand Order")
    zones = {z["name"]: z["works"] for z in meta_store.originals_all()}
    assert zones == {"FateGrand Order": 1}        # FGO 分区消失，无重复计数
    # 重扫不撤销合并（manual original 保留正名行）
    app.get_library(force=True)
    assert _has_original(KEY, "FateGrand Order") and not _has_original(KEY, "FGO")


def test_original_alias_post_merges_zone(lib_env):
    """端点层用户场景（#26）：两个分区各自有作品，登记别名后整体并入正名、
    不再单列——用户在别名页设置的合并落地。"""
    _seed(lib_env)
    _seed_fgo(lib_env)
    client = app.app.test_client()
    # ① FateGrandOrder 分区（含 Fate_Grand_Order 作品）；② FGO 分区
    # （同前：meta 层直写需补词条库，避免 stale 清理误删；真实路径由 add 端点写库）
    app.CFG["originals"] = ["FGO"]     # 只补 FGO；正名走**内置**规范名 "FateGrand Order"
    app.save_config(app.CFG)           # 落盘到隔离的 tmp config.json（_reload_originals 读磁盘）
    app.state.originals, app.state.norm_to_canon = app._reload_originals()
    meta_store.originals_add("FateGrand Order", [KEY])
    meta_store.originals_add("FGO", [KEY2])
    zones = {z["name"]: z["works"]
             for z in client.get("/api/originals").get_json()["originals"]}
    assert zones == {"FateGrand Order": 1, "FGO": 1}
    # ③ 登记别名：FGO → Fate Grand Order（正名宽松归一到词条库规范名 FateGrand Order）
    j3 = client.post("/api/author-aliases",
                     json={"alias": "FGO", "canonical": "Fate Grand Order",
                           "kind": "original"}).get_json()
    assert j3["ok"] and "并入" in j3["message"]
    # ④ FGO 分区消失，其作品并入 FateGrand Order（共 2 部）
    assert not _has_original(KEY2, "FGO")
    assert _has_original(KEY2, "FateGrand Order")
    zones = {z["name"]: z["works"]
             for z in client.get("/api/originals").get_json()["originals"]}
    assert zones == {"FateGrand Order": 2}


def test_original_alias_post_normalizes_canonical_before_merge(lib_env):
    """正名宽松变体也归一到词条库规范名后再合并——防别名表与词条库分裂（#25）。"""
    _seed(lib_env)
    _seed_fgo(lib_env)
    client = app.app.test_client()
    client.post("/api/originals/add", json={"term": "FGO"})
    assert {z["name"] for z in client.get("/api/originals").get_json()["originals"]} == {"FGO"}
    # 正名输带空格变体：终点必须归一成 FateGrand Order，而不是把变体当新规范名
    j = client.post("/api/author-aliases",
                    json={"alias": "FGO", "canonical": "fate grand order",
                          "kind": "original"}).get_json()
    assert j["ok"]
    j2 = client.get("/api/author-aliases?kind=original").get_json()
    assert j2["aliases"] == {"FGO": "FateGrand Order"}
    assert _has_original(KEY2, "FateGrand Order") and not _has_original(KEY2, "FGO")
    # 字面相同仍拒绝
    j3 = client.post("/api/author-aliases",
                     json={"alias": "FGO", "canonical": "FGO", "kind": "original"})
    assert j3.status_code == 400


# ---------- 3.6.21：原作分区改名 / 合并（用户需求） ----------

def test_originals_rename_moves_tags_and_config(lib_env):
    """改名：只搬标签（零文件操作）+ 旧词条删、新词条加 + 旧分区消失 + 重扫不复活。"""
    _seed(lib_env)
    client = app.app.test_client()
    # 直接给作品挂 TERM 标签（manual original）；词条库此刻为空
    assert meta_store.originals_add(TERM, [KEY]) == 1
    assert _has_original(KEY, TERM)
    j = client.post("/api/originals/rename", json={"from": TERM, "to": "改名后ZZZ"}).get_json()
    assert j["ok"] and j["moved"] == 1 and j["merged"] is False
    assert j["to"] == "改名后ZZZ"
    assert _has_original(KEY, "改名后ZZZ") and not _has_original(KEY, TERM)
    # 词条库：旧的删、新的加（否则重扫把旧分区又长出来 / 新分区活不过重扫）
    assert "改名后ZZZ" in app.CFG["originals"] and TERM not in app.CFG["originals"]
    assert "改名后ZZZ" in app.state.originals
    zones = {z["name"]: z["works"]
             for z in client.get("/api/originals").get_json()["originals"]}
    assert zones == {"改名后ZZZ": 1}
    # 重扫不复活旧分区、也不丢新分区
    app.get_library(force=True)
    zones = {z["name"]: z["works"]
             for z in client.get("/api/originals").get_json()["originals"]}
    assert zones == {"改名后ZZZ": 1}
    # 空参数拒绝
    assert client.post("/api/originals/rename", json={"from": "", "to": "X"}).status_code == 400
    assert client.post("/api/originals/rename", json={"from": "X", "to": " "}).status_code == 400
    # 改成同名：不报错、不动数据
    j2 = client.post("/api/originals/rename",
                     json={"from": "改名后ZZZ", "to": "改名后ZZZ"}).get_json()
    assert j2["ok"] and j2["moved"] == 0 and "未变化" in j2["message"]


def test_originals_rename_keeps_variant_distinct(lib_env):
    """3.6.27 用户需求：改分区名**不做宽松归一**——改成宽松相近但不字面相同的名字时，
    就是一个**独立分区**，不再自动并入既有分区（旧行为会并入，用户无法改名）。"""
    _seed(lib_env)
    _seed_fgo(lib_env)
    client = app.app.test_client()
    # 真实路径里每个分区都由 /api/originals/add 创建、同步写进词条库；这里用 meta 层
    # 直写标签来构造场景，故显式补词条库——否则 _originals_config_set 的 stale 清理
    # 会把"不在词条库"的分区当废弃标签删掉（那是"删词条即删分区"的正常语义）。
    app.CFG["originals"] = [TERM, "Grand Order"]
    app.state.originals, app.state.norm_to_canon = app._reload_originals()
    meta_store.originals_add(TERM, [KEY])                 # TERM 分区（1 部）
    meta_store.originals_add("Grand Order", [KEY2])       # 既有 Grand Order 分区（1 部）
    assert {z["name"]: z["works"]
            for z in client.get("/api/originals").get_json()["originals"]} == {
        TERM: 1, "Grand Order": 1}
    j = client.post("/api/originals/rename",
                    json={"from": TERM, "to": "grand_order"}).get_json()
    assert j["ok"] and j["merged"] is False               # 不并入
    assert j["to"] == "grand_order"                       # 原样生效
    assert j["moved"] == 1
    zones = {z["name"]: z["works"]
             for z in client.get("/api/originals").get_json()["originals"]}
    assert zones == {"grand_order": 1, "Grand Order": 1}   # 两个独立分区
    assert not _has_original(KEY, TERM)
    assert _has_original(KEY, "grand_order")


def test_originals_rename_to_spaced_name_takes_effect(lib_env):
    """3.6.27 用户报障回归：把「FateGrandOrder」改成「Fate Grand Order」（只加空格）
    **必须真的改名**。旧实现按宽松归一判定"写法相同"→ 返回"名称未变化"，用户改不动分区名。

    同时：仅写法不同的改名会自动把旧名登记为别名，保证重扫后文件名里的旧写法
    （解析器按 _norm 精确匹配词条库）仍能归到本分区，作品不丢标签。"""
    _seed(lib_env)
    _seed_fgo(lib_env)
    client = app.app.test_client()
    meta_store.originals_add("FateGrandOrder", [KEY])
    j = client.post("/api/originals/rename",
                    json={"from": "FateGrandOrder", "to": "Fate Grand Order"}).get_json()
    assert j["ok"]
    assert j["to"] == "Fate Grand Order"        # 用户输入什么就是什么
    assert j["moved"] == 1
    assert j["keep_alias"] is True              # 仅写法不同 → 自动留别名
    zones = {z["name"]: z["works"]
             for z in client.get("/api/originals").get_json()["originals"]}
    assert zones == {"Fate Grand Order": 1}
    assert _has_original(KEY, "Fate Grand Order")


def test_originals_rename_keep_alias_blocks_revival(lib_env):
    """keep_alias：旧名登记为原作别名 → 将来文件名里再出现该写法也并回本分区。"""
    _seed(lib_env)
    client = app.app.test_client()
    meta_store.originals_add(TERM, [KEY])
    j = client.post("/api/originals/rename",
                    json={"from": TERM, "to": "Grand Order", "keep_alias": True}).get_json()
    assert j["ok"] and j["keep_alias"] is True and "别名" in j["message"]
    assert j["moved"] == 1
    assert meta_store.original_aliases().get(TERM) == "Grand Order"
    assert app.state.norm_to_canon.get(TERM) == "Grand Order"     # 词条库已叠加别名
    assert not _has_original(KEY, TERM) and _has_original(KEY, "Grand Order")
    # 旧写法的分区不复活
    app.get_library(force=True)
    zones = {z["name"] for z in client.get("/api/originals").get_json()["originals"]}
    assert zones == {"Grand Order"}


def test_originals_rename_empty_zone_just_removes_it(lib_env):
    """误建的空分区（词条库有词、但没有任何作品挂该标签）：改名 = 删掉它，
    且不该因此多出一个词条（用户场景：Fate Grand Ordee 这种误建分区）。"""
    _seed(lib_env)
    client = app.app.test_client()
    import common
    cfg = dict(app.CFG)
    cfg["originals"] = [TERM]
    common.save_config(cfg)                     # 词条库落盘（_reload_originals 读的是盘上文件）
    app.CFG["originals"] = [TERM]
    app.state.originals, app.state.norm_to_canon = app._reload_originals()
    assert TERM in app.state.originals
    # 3.6.36 #34：空分区（词条库有词、库内无作品）现在**可见**（0 部）——
    # 「允许添加空原作区，作品手动补齐」；旧语义"孤立词条不显示"已被 #34 刻意推翻。
    zones = {z["name"]: z["works"]
             for z in client.get("/api/originals").get_json()["originals"]}
    assert zones.get(TERM) == 0                    # 空分区可见（0 部）
    j = client.post("/api/originals/rename",
                    json={"from": TERM, "to": "不该出现的词条"}).get_json()
    assert j["ok"] and j["moved"] == 0 and j["merged"] is False
    assert "移除空分区" in j["message"]
    assert TERM not in app.CFG["originals"]
    assert "不该出现的词条" not in app.CFG["originals"]      # 没搬标签 → 不新增词条
    app.get_library(force=True)
    zones = {z["name"] for z in client.get("/api/originals").get_json()["originals"]}
    assert TERM not in zones


# ---------- 3.6.28：内置名单分区改名/归并后旧分区不得复活 ----------


def test_create_empty_zone_via_add_endpoint(lib_env):
    """网页端「新建分区」卡调的就是这个分支：只落词条，不搜作品、不写标签。

    用户 2026-10-30：同人分区视图没有建新分区的入口，要求做成一张作品卡片（置顶）。
    前端发 `POST /api/originals/add {term, empty:true}`，这里钉住后端那一半：
    分区立刻可见（0 部）、词条进 config（重扫/重启后仍在）、不误给任何作品打标签。
    """
    _seed(lib_env)
    client = app.app.test_client()
    before = {z["name"]: z["works"]
              for z in client.get("/api/originals").get_json()["originals"]}
    zone = "新建的空分区XYZ"
    j = client.post("/api/originals/add", json={"term": zone, "empty": True}).get_json()
    assert j["ok"] is True and j["empty"] is True and j["existed"] is False
    assert zone in app.CFG["originals"]          # 词条库落名：空分区靠它展示
    zones = {z["name"]: z for z in client.get("/api/originals").get_json()["originals"]}
    assert zones[zone]["works"] == 0             # 建好就可见，作品数是 0
    for name, n in before.items():               # 建空分区不该动其它分区
        assert zones[name]["works"] == n, name
    # 同名再建一次：幂等（existed=True），词条库里不重复
    j2 = client.post("/api/originals/add", json={"term": zone, "empty": True}).get_json()
    assert j2["existed"] is True
    assert [x for x in app.CFG["originals"] if x == zone] == [zone]
