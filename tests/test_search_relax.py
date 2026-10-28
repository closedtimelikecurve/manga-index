# -*- coding: utf-8 -*-
"""搜索宽松档回归（3.6.108）。

用户报障：把「[社团 (画师)] 标题」整条粘进搜索栏返回 0 条，但只输裸标题就正常。
根因不是长度、也不是限流：多关键词是 AND，**只要有一个词在库里一次都没出现就整体 0 条**，
而整条作品名里经常带着库里没有的尾巴（`.zip`、写法不同的汉化组标记），或者复合词条在
入库时已被规范化挪走。

修法：严格档 0 条时，把"全库都没有"的词丢掉再试一次（`.zip` 先剥后缀），
响应里的 `dropped` 回报丢了哪些词，前端在条数后面说明。
"""
import os
import sys
import zipfile

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    circ = root / "社团R"
    circ.mkdir(parents=True)
    with zipfile.ZipFile(str(circ / "[社团R (画师R)] 标题R.zip"), "w") as z:
        z.writestr("01.jpg", b"\xff\xd8 fake")
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    app.state.index_loaded = False
    app.state.index = {"v": 2, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    app.get_library(force=True)
    yield root
    app.state.index_keys.clear()


def _search(q):
    return app.app.test_client().get("/api/search?q=" + q).get_json()


def test_full_name_with_archive_tail_still_hits(lib_env):
    """整条作品名后面多一个 .zip —— 用户从文件名/收件箱复制时最常见。"""
    j = _search("[社团R (画师R)] 标题R .zip")
    assert len(j["works"]) == 1, j.get("works")
    assert j["dropped"] == [".zip"]


def test_attached_archive_suffix_is_stripped(lib_env):
    """`.zip` 粘在最后一个词上（`标题R.zip`）也要能剥出前半段。"""
    j = _search("[社团R (画师R)] 标题R.zip")
    assert len(j["works"]) == 1, j.get("works")
    assert j["dropped"] == ["标题r.zip"]


def test_unknown_extra_word_is_dropped(lib_env):
    """多打了一个库里没有的词（汉化组写法不同等）也不该整条归零。"""
    j = _search("标题R 完全不存在の词")
    assert len(j["works"]) == 1
    assert j["dropped"] == ["完全不存在の词"]


def test_strict_hit_reports_no_dropped(lib_env):
    """严格命中时不进宽松档，dropped 必须为空（否则前端会误报"已忽略"）。"""
    j = _search("[社团R (画师R)] 标题R")
    assert len(j["works"]) == 1
    assert j["dropped"] == []


def test_all_terms_unknown_still_empty(lib_env):
    """全都没有的词 → 照旧 0 条（不能因为宽松档就乱给结果）。"""
    j = _search("完全不存在的词甲 完全不存在的词乙")
    assert j["works"] == []
    assert j["dropped"] == []


def test_bare_title_still_works(lib_env):
    assert len(_search("标题R")["works"]) == 1


# ---------- 3.6.109：忽略空白 ----------

def test_name_without_spaces_matches_spaced_library_name(lib_env):
    """用户原例：`[ずり屋(おやずり)]育ち盛りに…`（无空格）搜不到，删掉复合词条才行。

    库里这条的实际名字是 `[ずり屋 (おやずり)] 育ち盛りに…` —— 社团、画师、标题之间
    各有空格。整串只有**一个**词（没有空格可分），要求连续出现 → 差一个空格就 0 条。
    现在两边都抹掉空白再比。
    """
    j = _search("[社团R(画师R)]标题R")
    assert len(j["works"]) == 1, j.get("works")
    assert j["dropped"] == []


def test_spaced_query_matches_too(lib_env):
    """反过来（输入带空格、库里没有）也一样命中。"""
    j = _search("[社团R (画师R)] 标题R")
    assert len(j["works"]) == 1


def test_blank_only_query_never_matches_everything(lib_env):
    """纯空白/零宽字符：词全部被滤空，必须 0 条（`"" in hay` 恒为真，不能漏这个洞）。"""
    j = _search("\u200b\u200d")
    assert j["works"] == [] and j["groups"] == []


# ---------- 3.6.109：忽略空白 ----------

def test_name_without_spaces_matches_spaced_library_name(lib_env):
    """用户原例：`[ずり屋(おやずり)]育ち盛りに…`（无空格）搜不到，删掉复合词条才行。

    库里这条的实际名字是 `[ずり屋 (おやずり)] 育ち盛りに…` —— 社团、画师、标题之间
    各有空格。整串只有**一个**词（没有空格可分），要求连续出现 → 差一个空格就 0 条。
    现在两边都抹掉空白再比。
    """
    j = _search("[社团R(画师R)]标题R")
    assert len(j["works"]) == 1, j.get("works")
    assert j["dropped"] == []


def test_spaced_query_matches_too(lib_env):
    """反过来（输入带空格、库里没有）也一样命中。"""
    j = _search("[社团R (画师R)] 标题R")
    assert len(j["works"]) == 1


def test_blank_only_query_never_matches_everything(lib_env):
    """纯空白/零宽字符：词全部被滤空，必须 0 条（`"" in hay` 恒为真，不能漏这个洞）。"""
    j = _search("\u200b\u200d")
    assert j["works"] == [] and j["groups"] == []
