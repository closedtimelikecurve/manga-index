# -*- coding: utf-8 -*-
"""合作社团识别（[A、B] / [A,B] → 各社团交叉引用，不单列合成社团）回归测试。"""
import os
import sys
import zipfile

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
import common  # noqa: E402
import djc_parse  # noqa: E402

JPG = b"\xff\xd8\xff\xe0 fake-jpg"


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    monkeypatch.setitem(app.CFG, "term_blacklist", [])
    monkeypatch.setitem(app.CFG, "dissolved_circles", [])
    app.state.index_loaded = False
    app.state.index = {"v": 3, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    saved_known = dict(app.state.known)
    app.state.known.clear()
    app.state.known.update({"ready": True, "circles": set(), "pc": {}})
    yield root
    app.state.known.clear()
    app.state.known.update(saved_known)
    app.state.index_keys.clear()


def _mk(root, circle_dir, fname):
    d = root / circle_dir
    d.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(d / fname), "w") as z:
        z.writestr("01.jpg", JPG)


def _groups(lib):
    return {g["name"]: [w["name"] for w in g["works"]] for g in lib["groups"]}


# ---------- 解析层 ----------

@pytest.mark.parametrize("text,expect", [
    ("社团A、社团B", ["社团A", "社团B"]),
    ("社团A,社团B", ["社团A", "社团B"]),
    ("社团A，社团B", ["社团A", "社团B"]),
    ("社团A 、 社团B", ["社团A", "社团B"]),
    ("社团A", ["社团A"]),                       # 单社团不拆
    ("", []),
    ("たまかけ屋（如月みゆ，たまかけ）", ["たまかけ屋（如月みゆ，たまかけ）"]),  # 全角括号内逗号不是分隔符
    ("社团A (画师A，助手B)", ["社团A (画师A，助手B)"]),                      # 半角括号同理
    ("milkberry，たまかけ屋（如月みゆ，たまかけ）",
     ["milkberry", "たまかけ屋（如月みゆ，たまかけ）"]),                     # 括号段整体保留
])
def test_split_circles(text, expect):
    assert djc_parse.split_circles(text) == expect


def test_parse_filename_exposes_circles():
    # 裸 [A、B]（无 (画师) 括号）→ 走待定词条通道，词条本身仍要按合作社团拆开。
    # 词条已做符号归一：顿号写作半角逗号（与 [A,B] 同归一种写法，不再分裂成两个档案）
    p = djc_parse.parse_filename("[社团A、社团B] 作品名.zip")
    assert p["bare"] == "社团A,社团B"
    assert p["circles"] == ["社团A", "社团B"]
    # [C (P)] 形态：社团区域含分隔符同样拆开
    p2 = djc_parse.parse_filename("[社团A、社团B (画师X)] 作品名.zip")
    assert p2["circle"] == "社团A,社团B"      # 同样归一为半角逗号
    assert p2["circles"] == ["社团A", "社团B"]
    # 单社团不拆
    single = djc_parse.parse_filename("[社团A] 作品名.zip")
    assert single["circles"] == ["社团A"]


# ---------- 命名符号归一 ----------

def test_normalize_symbols():
    assert djc_parse.normalize_symbols("社团（画师）") == "社团(画师)"
    assert djc_parse.normalize_symbols("社团A、社团B") == "社团A,社团B"
    assert djc_parse.normalize_symbols("社团A，社团B") == "社团A,社团B"
    assert djc_parse.normalize_symbols("【绅士仓库汉化】") == "【绅士仓库汉化】"   # 汉化组方括号不动
    assert djc_parse.normalize_symbols("") == ""


def test_fullwidth_paren_recognized_as_circle_personal():
    """全角括号 [社团（画师）] 归一后正确识别为 社团+画师，不再退化成待定词条。"""
    p = djc_parse.parse_filename("[社团A（画师X）] 作品名.zip")
    assert p["circle"] == "社团A"
    assert p["personal"] == "画师X"
    assert p["bare"] == ""


def test_milkberry_fullwidth_case():
    """真实库样本：[milkberry，たまかけ屋（如月みゆ，たまかけ）]
    全角逗号/顿号→半角逗号、全角括号→半角后，两社与两画师各自拆开。"""
    p = djc_parse.parse_filename(
        "[milkberry，たまかけ屋（如月みゆ，たまかけ）] （COMIC1☆15） JC催眠.zip")
    assert p["circle"] == "milkberry,たまかけ屋"
    assert p["circles"] == ["milkberry", "たまかけ屋"]
    assert p["personals"] == ["如月みゆ", "たまかけ"]


def test_separator_variants_parse_identically():
    """「、」「，」「,」三种写法归一后解析结果完全一致——不再因符号分裂成两个档案。"""
    outs = [djc_parse.parse_filename(f"[きのこのみ{s}brand nyu (konomi{s}nyu)] 作品.zip")
            for s in ("、", "，", ",")]
    keys = [(o["circle"], tuple(o["circles"]), tuple(o["personals"])) for o in outs]
    assert len(set(keys)) == 1, keys
    assert keys[0] == ("きのこのみ,brand nyu", ("きのこのみ", "brand nyu"), ("konomi", "nyu"))


def test_existing_archive_dir_hits_symbol_variant(lib_env, monkeypatch):
    """磁盘上已有「A、B」目录时，待落位名「A,B」沿用前者，不再另建符号变体目录。"""
    root = lib_env
    (root / "甲社、乙社").mkdir()
    monkeypatch.setitem(common.CFG, "root", str(root))
    assert common.existing_archive_dir("甲社,乙社", str(root)) == "甲社、乙社"
    assert common.existing_archive_dir("甲社、乙社", str(root)) == "甲社、乙社"
    # 都不存在时才返回规范名（归一后的写法）
    assert common.existing_archive_dir("丙社、丁社", str(root)) == "丙社,丁社"


# ---------- 呈现层：交叉引用 ----------

def test_coop_work_appears_in_every_circle(lib_env):
    """合作作品同时出现在两个社团下；两个社团都能读到它。"""
    root = lib_env
    _mk(root, "甲社", "[甲社、乙社] 合作本.zip")
    lib = app.get_library(force=True)
    g = _groups(lib)
    assert "甲社" in g and "乙社" in g
    assert "甲社、乙社" not in g           # 合成名不再单列一个社团
    assert g["甲社"] == ["[甲社、乙社] 合作本"]
    assert g["乙社"] == ["[甲社、乙社] 合作本"]


def test_coop_ref_merges_into_existing_circle(lib_env):
    """合作社团若已有自己的真实目录，合作作品并入其中而不是新建虚拟社团。"""
    root = lib_env
    _mk(root, "甲社", "[甲社、乙社] 合作本.zip")
    _mk(root, "乙社", "[乙社] 单行本.zip")
    lib = app.get_library(force=True)
    g = _groups(lib)
    assert "甲社、乙社" not in g
    assert g["乙社"] == ["[乙社] 单行本", "[甲社、乙社] 合作本"]
    assert g["甲社"] == ["[甲社、乙社] 合作本"]


def test_coop_work_readable_from_ref_circle(lib_env):
    """从引用社团（乙社）也能按 社团/作品 定位到该作品——删除/下载不会失灵。"""
    root = lib_env
    _mk(root, "甲社", "[甲社、乙社] 合作本.zip")
    app.get_library(force=True)
    w = app.find_work("乙社", "[甲社、乙社] 合作本")
    assert w is not None and os.path.exists(w["path"])
    assert os.path.basename(os.path.dirname(w["path"])) == "甲社"   # 实体仍在主社团目录下


def test_single_circle_untouched(lib_env):
    """普通单社团作品不受影响（含名字里恰巧没有分隔符的情况）。"""
    root = lib_env
    _mk(root, "単独社", "[単独社] 作品.zip")
    lib = app.get_library(force=True)
    assert _groups(lib) == {"単独社": ["[単独社] 作品"]}


def test_coop_group_kept_when_work_cannot_place(lib_env):
    """历史遗留的「A、B」目录里若有无词条作品（归不了位），该社团保留兜底，作品不丢。"""
    root = lib_env
    _mk(root, "甲社、乙社", "[甲社、乙社] 合作本.zip")
    _mk(root, "甲社、乙社", "没词条的作品.zip")
    lib = app.get_library(force=True)
    g = _groups(lib)
    assert g["甲社"] == ["[甲社、乙社] 合作本"]
    assert g["乙社"] == ["[甲社、乙社] 合作本"]
    assert g["甲社、乙社"] == ["没词条的作品"]   # 无处可去的作品留在原处


def test_loose_coop_archive_splits(lib_env):
    """根目录散落的合作作品归档按子社团各自成立（不落进「A、B」合成组）。"""
    root = lib_env
    with zipfile.ZipFile(str(root / "[甲社、乙社] 散的合作本.zip"), "w") as z:
        z.writestr("01.jpg", JPG)
    lib = app.get_library(force=True)
    g = _groups(lib)
    assert g == {"甲社": ["[甲社、乙社] 散的合作本"],
                 "乙社": ["[甲社、乙社] 散的合作本"]}


# ---------- 归档落位 ----------

def test_archive_lands_in_primary_circle(lib_env):
    """合作社团作品归档时落到主社团（第一个），不再生成「A、B」目录。"""
    root = lib_env
    d = root / "待整理"
    d.mkdir()
    src = d / "[甲社、乙社] 未归档本.zip"
    with zipfile.ZipFile(str(src), "w") as z:
        z.writestr("01.jpg", JPG)
    app.get_library(force=True)
    w = app.find_work("待整理", "[甲社、乙社] 未归档本")
    ok, _msg = app._apply_rename(w, "[甲社、乙社] 未归档本.zip")
    assert ok, _msg
    lib = app.get_library(force=True)
    g = _groups(lib)
    assert "甲社、乙社" not in g
    assert g["甲社"] == ["[甲社、乙社] 未归档本"]
    assert g["乙社"] == ["[甲社、乙社] 未归档本"]
