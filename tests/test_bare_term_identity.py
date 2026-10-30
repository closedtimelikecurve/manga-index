# -*- coding: utf-8 -*-
"""3.6.12 待定词条印证（裸 [a] 到底是谁）回归测试。

背景（TOZAN-BU / 富士やま 实例）：
  * 解析层把裸词条 bare 一律塞进 personals（"先待定后印证"），但**全链路从没印证过**：
    扫描期不查词条库、导入期 2026-09-25 起作废了"自动补社团名"。
  * `_canon_circle` 只剥结尾下划线，对 TOZANBU / TOZAN_BU / TOZAN：BU / TOZAN BU /
    TOZAN-BU 这类分隔符变体毫无感知 → 词条库碎成一地，新写法永远"不认识"。
  后果：社团名 TOZAN-BU 被当成画师，画师名 富士やま 永远停在"未定"。

覆盖：
  * 归一比较键折叠分隔符变体（只用于查表，不改展示名）
  * 裸词条命中已知社团 → 认作社团，且**不再**被当成画师
  * 裸词条命中已知画师 → 认作画师并补上其主社团
  * 谁都不命中 → 完全维持原样（不改动既有行为）
  * 印证后作品 key 仍按**真实归档名**落库（_group）——阅读进度/收藏不丢
  * _known_learn 拒绝"画师→自己"的脏学习
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


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    monkeypatch.setitem(app.CFG, "dissolved_circles", [])
    monkeypatch.setitem(app.CFG, "artist_circles", {})
    app.state.index_loaded = False
    app.state.index = {"v": 3, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    app.state.terms.update({"at": 0.0, "circles": {}, "authors": {}, "ac": {}, "main": {}})
    # 3.6.165：`_do_scan` 现在会在扫描前预建词条库（`_prime_known_registry`），
    # 于是 `state.known` 会跨测试残留。这里是"新建一个空库"的语义，词条库必须一起清空，
    # 否则 `_known_learn` 看到内存里已有映射就直接 return、不写 DB（它的去重逻辑）。
    app.state.known.update({"ready": False, "circles": set(), "pc": {}})
    yield root
    app.state.index_keys.clear()
    app.state.terms.update({"at": 0.0, "circles": {}, "authors": {}, "ac": {}, "main": {}})


def _zip(path, pages=2):
    with zipfile.ZipFile(str(path), "w") as z:
        for i in range(1, pages + 1):
            z.writestr("%02d.jpg" % i, JPG)


def _work(lib, name_hint):
    for g in lib["groups"]:
        for w in g["works"]:
            if name_hint in w["name"]:
                return g, w
    return None, None


def test_term_key_folds_separator_variants():
    """同一社团的六种写法（爬虫/站点/各汉化组各异）必须归一到同一个比较键。"""
    variants = ["TOZANBU", "TOZAN_BU", "TOZAN：BU", "TOZAN BU", "TOZAN-BU", "TOZAN:BU"]
    keys = {app._term_key(v) for v in variants}
    assert len(keys) == 1, keys
    # 归一只用于查表，绝不改写原名
    assert app._term_key("TOZAN-BU") == "tozanbu"
    # 不同词条不能误并
    assert app._term_key("TOZAN-BU") != app._term_key("富士やま")


def test_bare_matching_known_circle_is_not_an_artist(lib_env):
    """[TOZAN-BU] 与已入库的 [TOZAN_BU (…)] 同源 → 认作社团，不再进画师名单。"""
    d = lib_env / "富士やま"
    d.mkdir()
    _zip(d / "[TOZAN_BU (富士やま)] 作品甲.zip")
    app.get_library(force=True)                       # 学会社团 TOZAN_BU
    _zip(d / "[TOZAN-BU] 作品乙.zip")                 # 同一社团的另一种写法（裸词条）
    lib = app.get_library(force=True)

    g, w = _work(lib, "作品乙")
    assert w is not None, "作品乙应在库里"
    assert w["circle"] == "TOZAN_BU", w
    assert w["bare"] == "", "印证后不该再是待定词条"
    assert "TOZAN-BU" not in (w.get("personals") or []), "社团名不该被当成画师"
    # 归档跟随：作品乙进社团档案，而不是留在画师目录
    assert g["name"] == "TOZAN_BU", g["name"]


def test_resolved_work_keeps_real_group_key(lib_env):
    """印证改了展示归属，但作品 key 仍按**真实所在目录**落库 → 阅读进度不丢。"""
    d = lib_env / "富士やま"
    d.mkdir()
    _zip(d / "[TOZAN_BU (富士やま)] 作品甲.zip")
    app.get_library(force=True)
    _zip(d / "[TOZAN-BU] 作品乙.zip")
    app.get_library(force=True)
    con = meta_store._connect()      # 共享连接，**不要 close**
    keys = {r[0] for r in con.execute("SELECT key FROM works")}
    assert "富士やま/[TOZAN-BU] 作品乙" in keys, keys


def test_bare_matching_known_artist_gets_its_circle(lib_env):
    """[富士やま]（画师名的裸写法）→ 认作画师，并补上其主社团。"""
    d = lib_env / "富士やま"
    d.mkdir()
    _zip(d / "[TOZAN_BU (富士やま)] 作品甲.zip")
    _zip(d / "[TOZAN_BU (富士やま)] 作品乙.zip")
    app.get_library(force=True)                       # 学会：画师 富士やま 属于 TOZAN_BU
    _zip(d / "[富士やま] 作品丙.zip")
    lib = app.get_library(force=True)

    g, w = _work(lib, "作品丙")
    assert w is not None
    assert "富士やま" in (w.get("personals") or []), w
    assert w["circle"] == "TOZAN_BU", "画师名应补上其主社团"
    assert w["bare"] == "", "不再停在'未定'"


def test_unknown_bare_keeps_legacy_behaviour(lib_env):
    """谁都不命中 → 完全维持原样（bare 保留 + 仍作 personals），禁止扩大改动面。"""
    d = lib_env / "陌生词条社"
    d.mkdir()
    _zip(d / "[从未见过的词条] 作品丁.zip")
    lib = app.get_library(force=True)
    g, w = _work(lib, "作品丁")
    assert w is not None
    assert w["bare"] == "从未见过的词条", w
    assert w.get("personals") == ["从未见过的词条"], w


def test_known_learn_refuses_self_mapping(lib_env):
    """拒绝『画师 → 自己』的脏学习（曾让 artist_circles 堆满自我映射）。"""
    app._known_learn("広乃あずま", "広乃あずま")
    app._known_learn("TOZAN_BU", "TOZANBU")     # 归一后同名，同样拒绝
    try:
        learned = meta_store.artist_circles()
    except Exception:
        learned = {}
    assert not [k for k in learned if "広乃あずま" in k or "TOZAN" in k.upper()], learned
    # 正常映射照旧学习
    app._known_learn("TOZAN_BU", "富士やま")
    assert "TOZAN_BU" in meta_store.artist_circles().get("富士やま", set())
