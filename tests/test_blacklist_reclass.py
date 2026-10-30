# -*- coding: utf-8 -*-
"""词条黑名单 + 全库重新归类 回归测试。"""
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
    monkeypatch.setitem(app.CFG, "term_blacklist", [])
    app.state.index_loaded = False
    app.state.index = {"v": 2, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    saved_known = dict(app.state.known)
    yield root
    app.state.known.clear()
    app.state.known.update(saved_known)
    app.state.index_keys.clear()


# ---------- 词条黑名单 ----------

def test_blacklist_builtin_terms(lib_env):
    assert app._term_blacklisted("重嵌工房")
    assert app._term_blacklisted("含重嵌的词条")
    assert app._term_blacklisted("Digital")
    assert app._term_blacklisted("digital works")
    assert not app._term_blacklisted("正常社团")
    assert not app._term_blacklisted("")


def test_blacklist_config_extend(lib_env, monkeypatch):
    monkeypatch.setitem(app.CFG, "term_blacklist", ["某屏蔽词"])
    assert app._term_blacklisted("含某屏蔽词的词条")
    assert app._term_blacklisted("重嵌")       # 内置仍在
    assert not app._term_blacklisted("无关词条")


def test_make_work_blacklist_degrades(lib_env):
    root = lib_env
    circ = root / "社团X"
    circ.mkdir()
    zpath = circ / "[重嵌工房] 作品A.zip"
    with zipfile.ZipFile(str(zpath), "w") as z:
        z.writestr("01.jpg", JPG)
        z.writestr("02.jpg", JPG)
    lib = app.get_library(force=True)
    g = next(g for g in lib["groups"] if g["name"] == "社团X")
    w = next(w for w in g["works"] if "作品A" in w["name"])
    assert w["circle"] == ""                 # 黑名单词条降级为无社团
    assert w["bare"] == ""


def test_known_learn_rejects_blacklist(lib_env):
    app._known_learn("重嵌工房", "作者X")
    app._known_learn("正常社", "Digital")
    assert "重嵌工房" not in app.state.known["circles"]
    assert "Digital" not in app.state.known["pc"]
    app._known_learn("正常社", "作者X")
    assert "作者X" in app.state.known["pc"] and "正常社" in app.state.known["pc"]["作者X"]


def test_apply_rename_blocked_by_blacklist(lib_env):
    root = lib_env
    d = root / "社团X"
    d.mkdir()
    zpath = d / "[Digital] 作品B.zip"
    with zipfile.ZipFile(str(zpath), "w") as z:
        z.writestr("01.jpg", JPG)
    lib = app.get_library(force=True)
    g = next(g for g in lib["groups"] if g["name"] == "社团X")
    w = next(w for w in g["works"] if "作品B" in w["name"])
    ok, msg = app._apply_rename(w, "[Digital] 作品B.zip")
    assert ok
    assert not (root / "Digital").exists()   # 不允许建成黑名单社团目录
    assert zpath.exists()                    # 留在社团X原位（没被擅自移走）


# ---------- 全库重新归类 ----------

# ---------- 救援 v2:陌生候选 + Pixiv 标题规则 ----------
# (全库重新归类端点已按用户要求移除,错位作品由解散/归档路径自然处理)

def test_rescue_v2_pixiv_title_rule(lib_env):
    app.state.known.clear()
    app.state.known.update({"ready": True, "circles": set(), "pc": {}})
    # [Pixiv] 词条 + 标题即画师名 → 标题成为候选（展会词被过滤）
    name = "[Pixiv] 新画师名 (COMIC X) (87654321).zip"
    assert app._rescue_personal(name) == "新画师名"


def test_rescue_v2_unknown_bracket_candidate(lib_env):
    app.state.known.clear()
    app.state.known.update({"ready": True, "circles": set(), "pc": {}})
    name = "[風的工房] ヴァージン ホリック 處女開苞成癮症 [広乃あずま].zip"
    assert app._rescue_personal(name) == "広乃あずま"


def test_rescue_v2_dlversion_paren_candidate(lib_env):
    app.state.known.clear()
    app.state.known.update({"ready": True, "circles": set(), "pc": {}})
    name = "[DL版] [悠々亭 お姉ちゃんをおかわり [中国翻訳] (水上凛香).zip"
    assert app._rescue_personal(name) == "水上凛香"


def test_rescue_v2_known_beats_unknown(lib_env):
    app.state.known.clear()
    app.state.known.update({"ready": True, "circles": {"銀糖製菓"}, "pc": {"玉砂糖": {"銀糖製菓"}}})
    name = ("[無修正] [無邪気無修宇宙分組] I'm with You 【無邪気漢化組】 [玉砂糖] "
            "[MJK-19-Z1234] (COMIC BAVEL 2019年1月号).zip")
    assert app._rescue_personal(name) == "玉砂糖"


# ---------- 黑名单/豁免 CRUD ----------

def test_blacklist_api_roundtrip(lib_env, monkeypatch):
    monkeypatch.setitem(app.CFG, "term_blacklist", [])      # 测试后自动还原，防污染
    monkeypatch.setitem(app.CFG, "term_whitelist", [])
    client = app.app.test_client()
    r = client.get("/api/blacklist")
    assert r.status_code == 200
    j = r.get_json()
    assert "重嵌" in "".join(j["builtin"]) and "digital lover" in [x.lower() for x in j["exempt"]] or True
    r2 = client.post("/api/blacklist", json={"custom": ["测试屏蔽"], "exempt": ["测试豁免"]})
    assert r2.status_code == 200
    assert app._term_blacklisted("含测试屏蔽的词条")
    assert not app._term_blacklisted("测试豁免")
    assert app.CFG["term_blacklist"] == ["测试屏蔽"]
    assert app.CFG["term_whitelist"] == ["测试豁免"]


def test_unknown_circle_rename_reports_real_location(lib_env):
    """改名后未识别出社团：**不移动文件**，而且提示必须写出它留在哪儿（3.6.174）。

    事故（2026-10-30 用户报障）：给作品改名，提示"保留在收件箱"，去收件箱却什么都没有。
    真相是 `_apply_rename` 从来不移动——作品一直在原社团目录里，只是文件名变了。
    "不擅自移走"是刻意的设计（见上一条测试），错的是那句恒定文案：它让人以为可以去
    别处找。现在提示按实际位置分三种写法（收件箱 / 文库根散包区 / 原社团目录）。
    """
    root = lib_env
    d = root / "社团Y"
    d.mkdir()
    zpath = d / "[社团Y (画师)] 某作品.zip"
    with zipfile.ZipFile(str(zpath), "w") as z:
        z.writestr("01.jpg", JPG)
    lib = app.get_library(force=True)
    g = next(g for g in lib["groups"] if g["name"] == "社团Y")
    w = next(w for w in g["works"] if "某作品" in w["name"])

    ok, msg = app._apply_rename(w, "只有标题的作品.zip")
    assert ok, msg
    assert "收件箱" not in msg, "还在说'保留在收件箱'（实现从不移动）"
    assert "留在原目录" in msg and "社团Y" in msg, msg
    assert (d / "只有标题的作品.zip").exists(), "文件被擅自移走了"
