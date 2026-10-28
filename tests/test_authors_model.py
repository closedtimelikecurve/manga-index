# -*- coding: utf-8 -*-
"""作者多值模型（合作作品拆分 + 笔名别名归一 + 双向交叉引用）回归测试。"""
import os
import sys
import zipfile
from urllib.parse import quote

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
import djc_parse  # noqa: E402

JPG = b"\xff\xd8\xff\xe0 fake-jpg"


# ---------- 解析层：合作拆分 ----------

def test_split_authors_separators():
    assert djc_parse.split_authors("A & B") == ["A", "B"]
    assert djc_parse.split_authors("A&B") == ["A", "B"]
    assert djc_parse.split_authors("A ＆ B") == ["A", "B"]
    assert djc_parse.split_authors("A × B") == ["A", "B"]
    assert djc_parse.split_authors("A×B") == ["A", "B"]
    assert djc_parse.split_authors("A x B") == ["A", "B"]
    assert djc_parse.split_authors("A、B") == ["A", "B"]
    assert djc_parse.split_authors("A & B & C") == ["A", "B", "C"]


def test_split_authors_no_false_positive():
    # 含 x 的罗马字名（无空格）不拆；单人名单元素
    assert djc_parse.split_authors("Rex") == ["Rex"]
    assert djc_parse.split_authors("xenon") == ["xenon"]
    assert djc_parse.split_authors("hiten") == ["hiten"]
    assert djc_parse.split_authors("") == []


def test_parse_filename_collab():
    r = djc_parse.parse_filename("[社团C (A & B)] 标题.zip")
    assert r["circle"] == "社团C"
    assert r["personals"] == ["A", "B"]
    assert r["personal"] == "A"                      # 兼容字段 = 首位
    ptags = [n for t, n in r["tags"] if t == "personal"]
    assert ptags == ["A", "B"]                       # 合作作品每人都进标签


def test_parse_filename_single_unchanged():
    r = djc_parse.parse_filename("[社团C (羊羽忍)] 标题.zip")
    assert r["personals"] == ["羊羽忍"] and r["personal"] == "羊羽忍"
    r2 = djc_parse.parse_filename("[待定词条] 标题.zip")
    assert r2["bare"] == "待定词条" and r2["personal"] == ""   # bare 兼容语义不变


# ---------- 别名归一 ----------

@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    monkeypatch.setitem(app.CFG, "author_aliases", {})
    app.state.index_loaded = False
    app.state.index = {"v": 3, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    saved = dict(app.state.known)
    yield root
    app.state.known.clear()
    app.state.known.update(saved)
    app.state.index_keys.clear()


def test_canon_author_alias_chain(lib_env, monkeypatch):
    monkeypatch.setitem(app.CFG, "author_aliases", {"飞天御姐流": "hiten", "Hiten_": "hiten"})
    assert app._canon_author("飞天御姐流") == "hiten"
    assert app._canon_author("Hiten_") == "hiten"       # 尾下划线 + 别名叠加
    assert app._canon_author("别人") == "别人"


def test_canon_author_no_infinite_loop(lib_env, monkeypatch):
    monkeypatch.setitem(app.CFG, "author_aliases", {"A": "B", "B": "A"})
    assert app._canon_author("A") in ("A", "B")          # 环不炸


def test_alias_crud_and_rescan(lib_env):
    root = lib_env
    circ = root / "社团H"
    circ.mkdir()
    zpath = circ / "[社团H (hiten)] 作品H.zip"
    with zipfile.ZipFile(str(zpath), "w") as z:
        z.writestr("01.jpg", JPG)
    client = app.app.test_client()
    # 登记别名：飞天御姐流 → hiten
    r = client.post("/api/author-aliases", json={"alias": "飞天御姐流", "canonical": "hiten"})
    assert r.status_code == 200, r.get_json()
    # 重扫后作品的 personal 归一到正名
    lib = app.get_library(force=True)
    g = next(g for g in lib["groups"] if g["name"] == "社团H")
    w = next(w for w in g["works"])
    assert w["personals"] == ["hiten"]
    # 列表接口
    r2 = client.get("/api/author-aliases").get_json()
    assert r2["aliases"] == {"飞天御姐流": "hiten"}
    assert r2["canonicals"] == {"hiten": ["飞天御姐流"]}
    # 删除
    r3 = client.post("/api/author-aliases/delete", json={"alias": "飞天御姐流"})
    assert r3.status_code == 200


# ---------- 聚合与交叉引用 ----------

def test_works_personal_aggregates_collab_and_cross_circle(lib_env):
    root = lib_env
    for gname in ("社团甲", "社团乙"):
        (root / gname).mkdir()
    with zipfile.ZipFile(str(root / "社团甲" / "[社团甲 (hiten)] W1.zip"), "w") as z:
        z.writestr("01.jpg", JPG)
    with zipfile.ZipFile(str(root / "社团甲" / "[社团甲 (hiten & 搭档)] W2.zip"), "w") as z:
        z.writestr("01.jpg", JPG)
    with zipfile.ZipFile(str(root / "社团乙" / "[社团乙 (飞天御姐流)] W3.zip"), "w") as z:
        z.writestr("01.jpg", JPG)
    client = app.app.test_client()
    # 先登记笔名别名：飞天御姐流 → hiten（重扫后 W3 的作者归一为 hiten）
    ra = client.post("/api/author-aliases", json={"alias": "飞天御姐流", "canonical": "hiten"})
    assert ra.status_code == 200
    r = client.get("/api/works?type=personal&tag=hiten").get_json()
    assert len(r["works"]) == 3, "别名飞天御姐流未生效或合作作品未按位匹配"
    names = [c["name"] for c in r["authorCircles"]]
    assert names == ["社团甲", "社团乙"]                 # 双向交叉引用：作者→社团分布
    # 合作作品搜"搭档"也能命中
    r2 = client.get("/api/works?type=personal&tag=搭档").get_json()
    assert len(r2["works"]) == 1 and r2["works"][0]["work"]["personals"] == ["hiten", "搭档"]


def test_circle_authors_aggregate(lib_env):
    root = lib_env
    (root / "社团甲").mkdir()
    with zipfile.ZipFile(str(root / "社团甲" / "[社团甲 (hiten)] W1.zip"), "w") as z:
        z.writestr("01.jpg", JPG)
    with zipfile.ZipFile(str(root / "社团甲" / "[社团甲 (hiten & 搭档)] W2.zip"), "w") as z:
        z.writestr("01.jpg", JPG)
    client = app.app.test_client()
    r = client.get("/api/circle/" + quote("社团甲")).get_json()
    authors = {a["name"]: a["count"] for a in r["authors"]}
    assert authors == {"hiten": 2, "搭档": 1}            # 合作作品每位作者各计 1


def test_public_work_personals_compat(lib_env):
    root = lib_env
    (root / "社团K").mkdir()
    with zipfile.ZipFile(str(root / "社团K" / "[社团K (A & B)] W.zip"), "w") as z:
        z.writestr("01.jpg", JPG)
    app.get_library(force=True)
    g = next(g for g in app.get_library()["groups"] if g["name"] == "社团K")
    w = g["works"][0]
    pw = app.public_work(w)
    assert pw["personals"] == ["A", "B"] and pw["personal"] == "A"
