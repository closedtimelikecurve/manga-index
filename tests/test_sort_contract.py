# -*- coding: utf-8 -*-
"""排序契约（3.6.151）：删「最近更新」档 + 反序箭头不翻转 + 各分区可「按文件大小」查重。

用户原话（2026-10-27）：
  ① 社团页的「最近更新」排序**彻底删掉**；
  ② 「最近入库」的排序绝对出问题了（另见 test_group_arrival.py，基准改 DB added_at）；
  ③ 那个反序键的箭头**按理来说不应改变方向**——只有文字随正/倒序变；
  ④ 各个分区内也要加「按文件大小」排序，用于查重。

网页与 APP 是同一天改的两端（纪律 §4.6 双端对齐），这里把两端的**档位集合**与
**箭头口径**一起钉死：任一端残留 touched、或箭头跟着翻转，这条测试立刻红。
"""
import os
import re

PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(PROG_DIR, "static", "js")
KT_DIR = os.path.join(PROG_DIR, "android", "app", "src", "main", "java", "com",
                      "biblioteca", "reader")


def _read(*parts):
    with open(os.path.join(*parts), "r", encoding="utf-8") as f:
        return f.read()


def _strip_js_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)//[^\n]*", "", src)


def test_web_circle_sort_bar_has_no_size_and_no_touched():
    """网页社团排序条：updated / created / count —— 没有 touched，也没有 size。

    3.6.166 用户要求：「作品大小排序只需要在分区内部存在即可，社团排序不需要这个」。
    查重是逐部作品比体积，把整个社团按总字节排一遍没有使用场景。"""
    core = _strip_js_comments(_read(JS_DIR, "core.js"))
    body = core[core.index("function sortBarHtml()"):]
    body = body[:body.index("}")]
    assert "'size'" not in body, "社团排序条还留着「文件大小」档（3.6.166 已删）"
    assert "touched" not in body, "「最近更新」档没删干净（用户要求彻底移除）"
    for key in ("updated", "created", "count"):
        assert "'" + key + "'" in body, "社团排序条丢了 %s 档" % key


def test_web_sort_mode_folds_legacy_touched():
    """旧缓存/旧标签里的 touched（3.6.151 删）与 size（3.6.166 删）必须回落 updated，
    否则排序条没有高亮项、点了也看不出变化。"""
    core = _strip_js_comments(_read(JS_DIR, "core.js"))
    assert "'touched' || m === 'size'" in core, "sortMode() 没把 touched/size 折回 updated"


def test_web_arrows_never_flip():
    """反序箭头固定朝下（表示列表从上到下的方向），只有文字变。

    事故来源：旧实现 asc 时给「↑ 由旧到新」，看起来像排序维度变了；
    用户要求箭头一律 ↓，文字说明方向。
    """
    core = _strip_js_comments(_read(JS_DIR, "core.js"))
    for fn in ("function sortDirLabel()", "function workDirLabel()"):
        body = core[core.index(fn):]
        body = body[:body.index("\n}")]
        labels = re.findall(r"t\('([^']*)'\)", body)
        assert labels, fn
        for lab in labels:
            assert lab.startswith("↓"), "%s 出现会翻转方向的箭头：%r" % (fn, lab)


def test_web_work_sort_has_size_and_is_used_by_every_zone():
    """作品列表排序三档（时间/文件大小/名称），且社团页/分区页/画师页都接上了。"""
    core = _strip_js_comments(_read(JS_DIR, "core.js"))
    assert "function sortWorks(" in core and "'size'" in core, "缺 sortWorks 的大小档"
    assert "function workSortBarHtml()" in core
    for f in ("detail.js", "tag.js"):
        src = _strip_js_comments(_read(JS_DIR, f))
        assert "sortWorks(" in src, "%s 没走统一的作品排序（加不上按大小排）" % f
        assert "workSortBarHtml()" in src, "%s 没有排序条" % f
    menu = _strip_js_comments(_read(JS_DIR, "menu.js"))
    assert "[data-wsort]" in menu and "[data-wsortdir]" in menu, "排序条按钮没接线"


def test_app_sort_bars_match_web():
    """APP 两端：社团排序条无「最近更新」、有「文件大小」；作品排序条三档；箭头固定 ↓。"""
    bars = _read(KT_DIR, "AppBars.kt")
    circle = bars[bars.index("internal fun CircleSortBar("):]
    circle = circle[:circle.index("\n}")]
    assert '"size"' not in circle, "APP 社团排序条还留着「文件大小」档（3.6.166 已删）"
    assert '"touched"' not in circle, "APP 社团排序条还留着「最近更新」档"
    # 只查"方向文案"（以箭头开头的那些）：档位名（最近入库 / 文件大小…）本来就没有箭头
    for lab in re.findall(r'AppI18n\.s\("([↑↓][^"]*)"\)', circle):
        assert lab.startswith("↓"), "社团排序条出现会翻转的箭头：%r" % lab

    common = _read(KT_DIR, "FeaturesCommon.kt")
    wbar = common[common.index("fun WorksSortBar("):]
    wbar = wbar[:wbar.index("\n}")]
    assert '"size"' in wbar and '"name"' in wbar and '"time"' in wbar
    for lab in re.findall(r'AppI18n\.s\("([↑↓][^"]*)"\)', wbar):
        assert lab.startswith("↓"), "作品排序条出现会翻转的箭头：%r" % lab

def test_group_sorts_whitelist_matches_backend_modes():
    """路由白名单必须与 sort_groups 的分支一致。

    事故形态（3.6.151 自查发现）：`GROUP_SORTS` 里还留着已删的 touched、且没有 size，
    `/api/library?sort=size` 被**静默**回落成 updated —— 前端"文件大小"按钮点了没反应，
    但没有任何报错。白名单少一项就是一次静默的功能缺失。
    """
    import inspect

    import services.group_order as go
    import app

    src = inspect.getsource(go.sort_groups)
    modes = set(re.findall(r'mode == "(\w+)"', src))
    modes.add("updated")                       # else 分支 = updated
    assert set(app.GROUP_SORTS) == modes,         "GROUP_SORTS=%r 与 sort_groups 档位=%r 不一致" % (sorted(app.GROUP_SORTS), sorted(modes))
    assert "touched" not in app.GROUP_SORTS, "touched 档已删，白名单还留着"
    assert "size" not in app.GROUP_SORTS, "size 档已删（3.6.166），白名单还留着"


def test_work_size_mode_says_big_small_not_old_new():
    """**作品**排序的「文件大小」档，方向文案必须跟着维度走。

    3.6.166：社团排序的这一档已删（大小只在分区内部按作品排），所以这条只钉
    `workDirLabel`——它就是分区内作品列表用的那一个。

    事故形态（自查发现）：方向文案只认 count，size 档落到默认分支，
    「文件大小」被写成"由旧到新"——维度名和方向说明打架，用户会以为排序没生效。
    """
    core = _strip_js_comments(_read(JS_DIR, "core.js"))
    body = core[core.index("function workDirLabel()"):]
    body = body[:body.index(chr(10) + "}")]
    assert "'↓ 由小到大'" in body and "'↓ 由大到小'" in body, "作品大小档的方向文案缺失"
    assert "m === 'size'" in body, "workDirLabel 没有 size 分支"


# ---------------------------------------------------------------------------
# 3.6.152：方向键的**文本**必须等于**实际顺序**（用户报障「全部搞反了」）
# ---------------------------------------------------------------------------

def _kt_no_comments(name):
    src = _read(KT_DIR, name + ".kt")
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)//[^\n]*$", "", src)


def test_app_comparators_negate_only_for_descending():
    """APP 两处比较器的符号约定：`ka < kb → -1` 本身就是**升序**，只有要降序时才取反。

    3.6.152 实测事故：`Api.sortCircles()` 与 `sortWorksList()` 都写成 `if (asc) r = -r`，
    于是默认方向实际是升序（由旧到新 / 由少到多 / 由小到大），而排序条文案写的是
    "由新到旧 / 由多到少 / 由大到小"——用户看到的就是"逆序键文本和实际排序全部搞反"。
    """
    for name, fn in (("ApiLibrary", "internal fun Api.sortCircles("),
                     ("FeaturesCommon", "fun <T> sortWorksList(")):
        src = _kt_no_comments(name)
        body = src[src.index(fn):]
        body = body[:body.index("\n}")]
        assert "if (asc) r = -r" not in body, \
            "%s：又写成 if (asc) r = -r（默认会变升序，与文案相反）" % name
        assert "if (!asc) r = -r" in body, "%s：缺少降序取反（默认应是新→旧）" % name


def test_feed_bars_use_fixed_arrow_and_mode_aware_words():
    """画师/分区列表的排序条：箭头固定 ↓，文案分「作品数量」与「创建次序/最新入库」两套。

    事故形态：这一处长期是 ↑/↓ 翻转，且 created/latest 共用"由少到多"——维度名与方向
    说明对不上（点「最新入库」却看到"由少到多"）。
    """
    app = _kt_no_comments("AppBars")
    body = app[app.index("internal fun FeedSortBar("):]
    body = body[:body.index("\n}")]
    assert "↑" not in body, "APP 画师/分区排序条还在翻转箭头（应固定 ↓）"
    assert "↓ 由少到多" in body and "↓ 由多到少" in body, "APP 缺「作品数量」的方向文案"
    assert "↓ 由旧到新" in body and "↓ 由新到旧" in body, "APP 缺「创建次序/最新入库」的方向文案"
    assert "onSort(eff, !asc)" in body, "方向键拿 raw mode 去切换（会把维度一起换掉）"

    web = _strip_js_comments(_read(JS_DIR, "home.js"))
    js_body = web[web.index("function feedSortBarHtml("):]
    js_body = js_body[:js_body.index("\n}")]
    assert "↑" not in js_body, "网页画师/分区排序条还在翻转箭头（应固定 ↓）"
    assert "↓ 由少到多" in js_body and "↓ 由多到少" in js_body, "网页缺「作品数量」的方向文案"
    assert "↓ 由旧到新" in js_body and "↓ 由新到旧" in js_body, "网页缺「创建次序/最新入库」文案"


def test_web_work_name_key_handles_artist_page_shape():
    """画师页的作品对象没有 name 字段（作品名在 work 上）——「名称」档必须认得两种形态。

    事故形态：`String(w(x).name)` 对画师页恒为 "undefined"，比较结果恒 0，
    点「名称」文案变了、列表一动不动。
    """
    core = _strip_js_comments(_read(JS_DIR, "core.js"))
    body = core[core.index("function sortWorks("):]
    body = body[:body.index("\n}")]
    assert "w(x).name || w(x).work" in body, "名称键没有兜底到 work 字段（画师页名称档会失效）"
    assert "String(w(x).name)" not in body, "名称键又只认 name（画师页会恒等排序）"


def test_group_sort_ties_on_whole_seconds_then_name():
    """时间档按整秒比较：同一秒内的社团按名称升序，顺序不随扫描顺序抖（3.6.154）。

    事故形态：首扫同一批新社团的「最近入库」取 now()，彼此只差几微秒，于是"同值按名字"
    的补位永不生效——同一份文库两次全量扫描能给出两种顺序（`test_corrupt_index_falls_back`
    的顺序依赖就是这么暴露出来的）。
    """
    import sys
    sys.path.insert(0, PROG_DIR)
    import app  # noqa: E402

    def g(name, ts, n=1):
        return {"name": name, "updated_at": ts, "created_at": ts,
                "works": [{"name": "w%d" % i} for i in range(n)], "total_bytes": n}

    # 只差几毫秒 → 视为同一秒 → 按名称升序，与传入顺序无关
    a = [g("社团B", 1000.004), g("社团A", 1000.001)]
    b = list(reversed(a))
    assert [x["name"] for x in app.sort_groups(a, "updated", "desc")] == ["社团A", "社团B"]
    assert [x["name"] for x in app.sort_groups(b, "updated", "desc")] == ["社团A", "社团B"]
    # 倒序（由旧到新）同样按名称升序补位，不会把同秒的那对反过来
    assert [x["name"] for x in app.sort_groups(a, "updated", "asc")] == ["社团A", "社团B"]
    # 真的差一秒以上，时间优先
    c = [g("社团A", 1001.0), g("社团B", 999.0)]
    assert [x["name"] for x in app.sort_groups(c, "updated", "desc")] == ["社团A", "社团B"]
    assert [x["name"] for x in app.sort_groups(c, "updated", "asc")] == ["社团B", "社团A"]
    # 数量档仍按精确值（不能被取整）
    d = [g("社团A", 1.0, 3), g("社团B", 2.0, 1)]
    assert [x["name"] for x in app.sort_groups(d, "count", "desc")] == ["社团A", "社团B"]


def test_web_and_app_round_time_keys_too():
    """网页与 APP 的社团排序也要按整秒比较——三端口径必须一致，否则换个端顺序就变。"""
    core = _strip_js_comments(_read(JS_DIR, "core.js"))
    body = core[core.index("function sortGroups("):]
    body = body[:body.index("\n}")]
    assert "Math.round(g.updatedAt" in body and "Math.round(g.createdAt" in body, \
        "网页的社团排序没有把时间取整（同秒社团会随扫描顺序抖）"
    assert "g.workCount || 0" in body and "Math.round(g.workCount" not in body, \
        "数量档不该取整"
    api = _kt_no_comments("ApiLibrary")
    body = api[api.index("internal fun Api.sortCircles("):]
    body = body[:body.index("\n}")]
    assert "Math.round(g.updatedAt)" in body and "Math.round(g.createdAt)" in body, \
        "APP 的社团排序没有把时间取整"
    assert "g.workCount.toDouble()" in body, "APP 数量档不该取整"
