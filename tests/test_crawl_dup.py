# -*- coding: utf-8 -*-
"""分区爬取的「疑似重复」预判（3.7.61；3.7.62 收窄到分区）。

用户规则：
  * **只跟当前分区内的作品比**（画师分区比该作者、社团分区比该社团、同人分区比该同人），
    不扫全库 —— 同一部作品同时出现在社团/同人分区是正常的，拿全库比会误判；
  * 裸名称相近（剥掉社团/作者/汉化组等括号块后比）；
  * **系列新作不算重复**（作品名 / 作品名2）；
  * 页数相近（汉化组会塞自己的图，允许 ±28% 或 ±3 页）；
  * 标记方式与收件箱一致（结果里带 dup 字段，前端画「⚠ 疑似重复」）。

不碰真实文库：`crawl_dup.h` 换成假的 `get_library()`。
"""
import os
import sys

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

from services import crawl_dup  # noqa: E402


def _work(group, name, pages, personals=(), originals=()):
    tags = [("personal", p) for p in personals] + [("original", o) for o in originals]
    return {"name": name, "pages": pages, "path": group + "/" + name,
            "circles": [group], "tags": tags}


def _with_lib(monkeypatch, works):
    """works = [(group, work_dict), ...]"""
    groups = {}
    for g, w in works:
        groups.setdefault(g, []).append(w)
    lib = {"groups": [{"name": g, "works": ws} for g, ws in groups.items()]}

    class _H:
        @staticmethod
        def get_library():
            return lib

    monkeypatch.setattr(crawl_dup, "h", lambda: _H)
    crawl_dup.invalidate()


def test_bare_name_ignores_brackets_and_noise():
    """裸名：社团/作者/汉化组/无修/DL版 都剥掉后再比。"""
    a = crawl_dup._norm("[社团A (画师B)] 作品名 [中国翻訳] [DL版]")
    b = crawl_dup._norm("作品名")
    assert a == b, (a, b)
    assert crawl_dup._norm("【汉化组】作品名（無修正）") == crawl_dup._norm("作品名")


def test_only_compares_inside_partition(monkeypatch):
    """3.7.62 核心：同一部作品在**别的**分区里不算重复，只认当前分区。"""
    _with_lib(monkeypatch, [
        ("社团A", _work("社团A", "[社团A] 作品名", 40, personals=["画师甲"], originals=["同人X"])),
        ("社团B", _work("社团B", "[社团B] 作品名", 40, personals=["画师乙"], originals=["同人Y"])),
    ])
    # 社团 A 分区里搜：命中社团 A 那份
    assert crawl_dup.find("作品名", 40, "circle", "社团A") is not None
    # 社团 B 分区里搜：命中的是社团 B 自己那份，而不是 A 的
    hit = crawl_dup.find("作品名", 40, "circle", "社团B")
    assert hit and hit["group"] == "社团B", hit
    # 画师分区：只比这位画师名下的
    assert crawl_dup.find("作品名", 40, "author", "画师甲") is not None
    assert crawl_dup.find("作品名", 40, "author", "画师乙") is not None
    assert crawl_dup.find("作品名", 40, "author", "画师丙") is None       # 不在任何分区
    # 同人分区同理
    assert crawl_dup.find("作品名", 40, "original", "同人X") is not None
    assert crawl_dup.find("作品名", 40, "original", "同人Z") is None


def test_no_partition_context_never_marks(monkeypatch):
    """从抽屉直接进来（没有分区 / 词条为空）时不判定，避免误标。"""
    _with_lib(monkeypatch, [("社团A", _work("社团A", "[社团A] 作品名", 40))])
    assert crawl_dup.find("作品名", 40, "", "") is None
    assert crawl_dup.find("作品名", 40, "circle", "") is None
    works = [{"aid": 1, "title": "作品名", "pages": 40}]
    crawl_dup.annotate(works)
    assert works[0]["dup"] is None


def test_sequel_is_not_duplicate(monkeypatch):
    """作品名 / 作品名2 是系列新作，不算重复（用户明确要求）。"""
    _with_lib(monkeypatch, [("社团A", _work("社团A", "[社团A] 作品名 [中国翻訳]", 40))])
    assert crawl_dup.find("作品名", 40, "circle", "社团A") is not None
    assert crawl_dup.find("作品名2", 40, "circle", "社团A") is None
    assert crawl_dup.find("[社团A] 作品名 3", 40, "circle", "社团A") is None


def test_pages_guard_blocks_short_vs_long(monkeypatch):
    """页数差太多不放行（短篇 vs 长篇合集）；汉化组多塞几页要放行。"""
    _with_lib(monkeypatch, [("社团A", _work("社团A", "[社团A] 作品名", 40))])
    assert crawl_dup.find("作品名", 43, "circle", "社团A") is not None      # +3 页
    assert crawl_dup.find("作品名", 200, "circle", "社团A") is None          # 长篇合集
    assert crawl_dup.find("作品名", 0, "circle", "社团A") is not None        # 页数未知


def test_different_name_is_not_duplicate(monkeypatch):
    """名字不同就不算重复（宁漏不误）。"""
    _with_lib(monkeypatch, [("社团A", _work("社团A", "[社团A] 完全不同的作品", 40))])
    assert crawl_dup.find("作品名", 40, "circle", "社团A") is None


def test_annotate_marks_each_work(monkeypatch):
    """搜索结果逐条打 dup（前端据此画徽标），命中时带库内作品名与理由。"""
    _with_lib(monkeypatch, [("社团A", _work("社团A", "[社团A] 作品名 [中国翻訳]", 40))])
    works = [{"aid": 1, "title": "[别家 (某人)] 作品名 [机翻]", "pages": 41},
             {"aid": 2, "title": "[别家] 另一部作品", "pages": 40}]
    crawl_dup.annotate(works, "circle", "社团A")
    assert works[0]["dup"] and "作品名" in works[0]["dup"]["name"]
    assert works[0]["dup"]["why"]
    assert works[1]["dup"] is None


def test_partition_index_is_cached(monkeypatch):
    """一次搜索要判上百条：分区索引必须缓存，不能每条都遍历。"""
    calls = {"n": 0}

    class _H:
        @staticmethod
        def get_library():
            calls["n"] += 1
            return {"groups": [{"name": "社团A",
                                "works": [_work("社团A", "[社团A] 作品名", 40)]}]}

    monkeypatch.setattr(crawl_dup, "h", lambda: _H)
    crawl_dup.invalidate()
    for _ in range(5):
        crawl_dup.find("作品名", 40, "circle", "社团A")
    assert calls["n"] == 1, calls
    crawl_dup.find("作品名", 40, "circle", "别的社团")     # 另一个分区 → 另建索引
    assert calls["n"] == 2, calls
