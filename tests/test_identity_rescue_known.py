# -*- coding: utf-8 -*-
"""孤词条归并：回头认库里已有的社团/画师（3.6.166 重做）。

## 用户报障与用户给的流程

```
[無修正] [Wantan Meo] アトリエ 【大鸟可不敢乱转汉化】 [中国翻訳] [雲呑めお] [DL版] (COMIC 快楽天 2024年2月号)
```

被归进新建的 `Wantan Meo/` 目录，而 `雲呑めお` 库里**已有 8 部作品的档案**却没被认出来。
用户把该走的顺序说清楚了：

> 寻找有完整社团+画师的复合词条 → 没有，开始比对标题中的其他词条是否是在库中已存在的
> 社团/画师 → 发现是库内画师/社团，并入相应分区 → 如果画师存在相应的社团归属，
> 应当按照数量多数的那个归属并入其社团。

## 断链在哪

1. 解析层把第一个方括号当裸词条（`bare = "Wantan Meo"`），`[雲呑めお]` 落进 `other_brackets`；
2. `kind='bare'` 时它被当成**唯一作者**，写进了 `work_authors`；
3. 词条库（`_term_index`）正是从 `work_authors` 建的 → "这个名字存在"反过来证明"它是画师"；
4. 老的词条救援 `_rescue_personal` 只在**社团/画师/裸词条三样全空**时才跑，这里作者非空被跳过；
5. **3.6.165 踩过的坑**：只改 `personals` 不改 `circle`，作品仍按目录名分桶
   （`_bucket_by_circle` 看的是 circle），`Wantan Meo/` 分区原样存在——看起来"根本没归并"。

第 3 步是个**闭环**：一旦误判写进库，用"名字在不在库里"判断就永远改不回来。
所以判据是 `_author_has_circle`——孤词条凑不出社团归属，它是这条链上没被污染的一环。

## 需要钉住的行为

* 作者是孤词条、标题里有库内画师 → 认那位画师 **并把 circle 一起推出来**；
* 画师有多个社团时按作品数多数归属（`_main_circle_of`，作品实证优先）；
* 作者已是已知画师、裸词条是孤词条 → 也按该画师主社团归区（第二级，3.6.166 补）；
* 推不出社团就整条不动（不做半改）；
* 平台词（FANBOX/DLsite/DL版…）不许当候选——实测 `[FANBOX]` 会被认成社团 "Fanbox"。
"""
import os
import sys

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
from services import meta_arrival  # noqa: E402

NAME = ("[無修正] [Wantan Meo] アトリエ 【大鸟可不敢乱转汉化】 [中国翻訳] "
        "[雲呑めお] [DL版] (COMIC 快楽天 2024年2月号)")


def _identity(name=NAME, path_dir="某社团", parsed=None):
    p = parsed or app.parse_filename(name, set(), {})
    return app._normalize_identity(name, p, "/lib/" + path_dir + "/" + name + ".zip")


@pytest.fixture()
def registry(monkeypatch):
    """库里：雲呑めお 有 8 部作品、社团归属 una casita；Wantan Meo 是孤词条。

    判据查的是内存词条库（pc）与 DB 计数，两者都按真实口径打桩——
    内存词条库是启动快照，一旦被误判污染就会形成闭环，不能单独当判据。
    """
    monkeypatch.setattr(app.state, "known",
                        {"ready": True, "pc": {"雲呑めお": {"una casita"}},
                         "circles": {"una casita"}})
    monkeypatch.setattr(app, "_author_has_circle", lambda a: a == "雲呑めお")
    monkeypatch.setattr(meta_arrival, "author_work_count",
                        lambda a: 8 if a == "雲呑めお" else 1)
    # _resolve_bare 走词条库：雲呑めお 是画师（归 una casita），Wantan Meo 查不到
    monkeypatch.setattr(app, "_resolve_bare", lambda b: (
        {"as": "personal", "circle": "una casita"} if b == "雲呑めお" else None))
    monkeypatch.setattr(app, "_main_circle_of", lambda a: "una casita")
    return app.state.known


def test_lonely_author_falls_back_to_known_artist(registry):
    """核心：孤词条作者 → 认库内画师，**并且把 circle 一起推到该画师的主社团**。"""
    circle, personals, bare, _cs, _lg = _identity()
    assert personals == ["雲呑めお"], "没认出库里已有的画师"
    assert circle == "una casita", "只改了作者、没把作品归进画师的社团（3.6.165 就栽在这）"
    assert bare == "", "孤词条应该被丢掉，否则还会被当成归档名"


def test_bare_lonely_but_author_known_folds_to_main_circle(monkeypatch, registry):
    """第二级：作者已是已知画师、裸词条查不到 → 按该作者主社团归区。

    这一级补的是第一级的盲区：作者一旦被修成已知画师，`_author_has_circle` 立刻为真，
    第一级整段跳过，裸词条那个归档名就永远留着（Wantan Meo 那部后来的真实状态）。
    """
    parsed = app.parse_filename(NAME, set(), {})
    parsed["personals"] = ["雲呑めお"]
    parsed["personal"] = "雲呑めお"
    parsed["bare"] = "Some Lone Name"
    # 画师有多个社团时，由 `_main_circle_of` 按作品数多数决定（用户要求"多数归属"）
    monkeypatch.setattr(app, "_main_circle_of", lambda a: "多数社")
    circle, personals, bare, _cs, _lg = _identity(
        "[無修正] [Some Lone Name] 某作品 [雲呑めお] [DL版]", path_dir="Some Lone Name",
        parsed=parsed)
    assert personals == ["雲呑めお"]
    assert circle == "多数社", "裸词条是孤词条时没按作者主社团归区（且要按多数归属）"
    assert bare == ""


def test_no_rescue_when_author_has_circle(monkeypatch, registry):
    """作者本身就有社团归属 → 是货真价实的画师，不许被标题里的别人顶替。"""
    monkeypatch.setattr(app, "_author_has_circle", lambda a: True)
    _c, personals, _b, _cs, _lg = _identity()
    assert personals == ["Wantan Meo"]


def test_no_rescue_when_no_known_author_available(monkeypatch, registry):
    """候选都没有独立历史（都只有 1 部）时保持原状：不许瞎认一个陌生词当画师。"""
    monkeypatch.setattr(meta_arrival, "author_work_count", lambda a: 1)
    _c, personals, bare, _cs, _lg = _identity()
    assert personals == ["Wantan Meo"]
    assert bare == "Wantan Meo", "查不到就不许猜，原样留给人工确认"


def test_registry_not_ready_skips_rescue(monkeypatch, registry):
    """首扫期间词条库还没建好：不救援，避免重入扫描。"""
    monkeypatch.setattr(app.state, "known", {"ready": False, "pc": {}, "circles": set()})
    _c, personals, bare, _cs, _lg = _identity()
    assert personals == ["Wantan Meo"] and bare == "Wantan Meo"


def test_platform_terms_are_not_candidates(registry):
    """平台/版本标记（FANBOX、DLsite、DL版…）既不是社团也不是画师。

    实测误伤：`[Konnyaku] … [FANBOX]` 里 FANBOX 撞上库里一条叫 "Fanbox" 的记录，
    作品差点被归进一个平台名的分区。
    """
    assert app._dp.is_platform_term("FANBOX") is True
    assert app._dp.is_platform_term("DL版") is True
    assert app._dp.is_platform_term("digital") is True
    assert app._dp.is_platform_term("雲呑めお") is False
    cands = app._rescue_candidates("[Konnyaku] おねしょた和希先輩 【个人汉化】 [FANBOX]")
    assert "FANBOX" not in cands


def test_rescue_candidates_skip_noise(registry):
    """候选里不该出现汉化组/無修正/中国翻訳/刊号。"""
    cands = app._rescue_candidates(NAME)
    for bad in ("大鸟可不敢乱转汉化", "中国翻訳", "無修正", "DL版"):
        assert bad not in cands, bad
    assert "雲呑めお" in cands, "真正的画师词条没进候选"


def test_author_has_circle_reads_pc(monkeypatch):
    """判据是 pc（有社团归属的画师），不是 `artist_circles` 表。

    用 `artist_circles` 会把所有独立画师都当成孤词条（实测影响面 4 → 519 部）。
    """
    monkeypatch.setattr(app.state, "known",
                        {"ready": True, "pc": {"雲呑めお": {"una casita"}},
                         "circles": {"una casita"}})
    assert app._author_has_circle("雲呑めお") is True
    assert app._author_has_circle("Wantan Meo") is False


def test_prime_registry_builds_pc_from_index(monkeypatch):
    """`_prime_known_registry` 直接用已加载索引建 pc——首扫时 lib 还是 None，
    走 get_library() 会重入扫描、拿回空库，等于没建。"""
    from services import index_cache
    monkeypatch.setattr(app.state, "known", {"ready": False, "circles": set(), "pc": {}})
    monkeypatch.setattr(app.state, "index", {"works": {
        "k1": {"circle": "una casita", "personals": ["雲呑めお"]},
        "k2": {"circle": "", "personals": ["Wantan Meo"]},
    }})
    index_cache._prime_known_registry()
    assert app.state.known["ready"] is True
    assert app._author_has_circle("雲呑めお") is True
    assert app._author_has_circle("Wantan Meo") is False
