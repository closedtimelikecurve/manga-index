# -*- coding: utf-8 -*-
"""汉字字形折叠（3.6.173）：JM 台湾繁体 vs 日文原名，不该把同一人劈成两档。

## 事故

用户 2026-10-30 报障：JM 是台湾站，作品名里的汉字会变成繁体，于是同一作者的作品
因为字形不同而"档案分立"。收件箱里三个新作正是这种情况：

| 来源 | 写法 |
|---|---|
| 库里已有（日文原名） | 南**浜**屋 (南浜よりこ) |
| 收件箱新作（JM 繁体） | 南**濱**屋 (南濱よりこ) |

`_term_key` 当时只折叠分隔符（TOZAN_BU / TOZAN-BU …），对字形毫无感知；
`_norm_key` 里的 `_VARIANT_MAP` 只有 20 组、且不含 浜/濱/滨 这一组。

## 修法

* `panel/variants.fold()`：繁/日文新字体 → 简体的**比对用**折叠；
* `identity._term_key` 走它 → 三种字形同键；
* `_canon_circle_resolved` / 新增的 `_canon_author_resolved` 把同键的新写法
  **回填成库里已有的那个写法**，展示名不变、作品并进原档案。

## 本文件守什么

1. 三种字形折叠成同一键；
2. 回填成库内写法（而不是反过来把库里的改名）；
3. **不误伤**：不相干的社团不会被合并；
4. `_VARIANT_MAP`（简→日，wnacg 搜索变体用）与本折叠方向相反，两者都必须在岗。
"""
import os
import sys

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
import djc_parse  # noqa: E402
import meta_store  # noqa: E402
from panel.variants import fold  # noqa: E402


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    """空库；`state.terms` 必须清空，否则词条索引会拿上一条测试的缓存。"""
    root = tmp_path / "lib"
    root.mkdir()
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    monkeypatch.setitem(app.CFG, "dissolved_circles", [])
    monkeypatch.setitem(app.CFG, "artist_circles", {})
    app.state.terms.update({"at": 0.0, "circles": {}, "authors": {}, "ac": {}, "main": {}})
    app.state.known.update({"ready": False, "circles": set(), "pc": {}})
    yield root
    app.state.terms.update({"at": 0.0, "circles": {}, "authors": {}, "ac": {}, "main": {}})


def _seed_old_work():
    """库里先有一条「南浜屋 / 南浜よりこ」的旧记录（作者在 work_authors，不在 works 里）。"""
    with meta_store._LOCK:
        con = meta_store._connect()
        con.execute("INSERT OR REPLACE INTO works(key, group_name, name, path, circle)"
                    " VALUES(?,?,?,?,?)", ("南浜屋/旧作", "南浜屋", "旧作", "", "南浜屋"))
        con.execute("INSERT OR REPLACE INTO work_authors(key, author) VALUES(?,?)",
                    ("南浜屋/旧作", "南浜よりこ"))
        con.commit()
    app.state.terms.update({"at": 0.0, "circles": {}, "authors": {}, "ac": {}, "main": {}})


def test_fold_collapses_three_scripts():
    """繁体 / 日文新字体 / 简体 三种写法折叠到同一个字。"""
    assert fold("南濱屋") == fold("南浜屋") == fold("南滨屋") == "南滨屋"
    # 日文新字体那一批（wnacg/match 里常见）
    assert fold("調査") == fold("调查") == "调查"
    assert fold("時間") == fold("时间") == "时间"
    # 非汉字原样保留：英文、假名、数字都不许被动
    assert fold("Hisasi よりこ 2024") == "Hisasi よりこ 2024"


def test_norm_key_and_term_key_agree_across_scripts():
    """两个比对键（解析层 / 身份层）都必须把三种字形认成同一个。"""
    for name in ("南濱屋", "南浜屋", "南滨屋"):
        assert djc_parse._norm_key(name) == djc_parse._norm_key("南浜屋")
        assert app._term_key(name) == app._term_key("南浜屋")
    assert app._term_key("南濱よりこ") == app._term_key("南浜よりこ")


def test_variant_map_keeps_its_opposite_direction():
    """`_VARIANT_MAP` 是**简→日**（wnacg 搜索变体用），不能跟着折叠表一起改方向。"""
    assert "调查".translate(djc_parse._VARIANT_MAP) == "調査"
    assert "时间".translate(djc_parse._VARIANT_MAP) == "時間"


def test_circle_and_author_resolve_to_library_spelling(lib_env):
    """库里有「南浜屋 / 南浜よりこ」时，繁体写法必须回填成库内写法。"""
    _seed_old_work()
    app.state.terms.update({"at": 0.0, "circles": {}, "authors": {}, "ac": {}, "main": {}})

    assert app._canon_circle_resolved("南濱屋") == "南浜屋"
    assert app._canon_author_resolved("南濱よりこ") == "南浜よりこ"
    # 书里没有的写法原样保留（首见者即规范名）
    assert app._canon_author_resolved("まったく新しい画师") == "まったく新しい画师"


def test_parsed_identity_merges_into_existing_circle(lib_env):
    """端到端：JM 繁体文件名解析出来的 circle/personal 直接落在库内档案上。"""
    _seed_old_work()
    app.state.terms.update({"at": 0.0, "circles": {}, "authors": {}, "ac": {}, "main": {}})

    name = "[angle345個人漢化][南濱屋 (南濱よりこ)] 種付ライセンス〜女上司わからせ編〜[中國翻譯]"
    parsed = app.parse_filename(name, app.state.originals, app.state.norm_to_canon)
    circle, personals, _bare, _circles, _loose = app._normalize_identity(name, parsed, "")
    assert circle == "南浜屋"
    assert personals == ["南浜よりこ"]


def test_unrelated_circles_are_not_merged(lib_env):
    """不误伤：写法完全不同、只是长度相同的社团不会被折叠到一起。"""
    assert app._term_key("南浜屋") != app._term_key("北浜屋")
    assert app._term_key("南浜屋") != app._term_key("南浜")
    assert app._canon_circle_resolved("北浜屋") == "北浜屋"
