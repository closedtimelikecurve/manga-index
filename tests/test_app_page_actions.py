# -*- coding: utf-8 -*-
"""APP 页面动作入口的契约（3.6.152）。

用户原话（2026-10-27 第 3、4 条）：
  ③「除了社团内部以外，将同人分区和画师页内的下载全部键都删掉，操作栏已经有这个了」；
  ④「将画师页和同人分区内的联网获取都移到界面右上角，其样式跟同人分区那个 +添加 相同」。

为什么钉死：
* 「下载全部」在页头出现过两处（分区页、画师页），但真正的批量下载入口是**长按操作栏**里的
  那一项（FeaturesCardMenu）。页头再摆一个，等于同一动作两个入口、还各有一套文案；
* 「联网获取」（⛏）原本挤在"N 部作品"那一行，跟页头右上角的「＋ 添加」不是一套规格——
  同为"页面级动作"却长得不一样，用户很难把它们看成同一层。
"""
import os
import re

PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KT_DIR = os.path.join(PROG_DIR, "android", "app", "src", "main", "java", "com",
                      "biblioteca", "reader")


def _kt(name, strip_comments=True):
    with open(os.path.join(KT_DIR, name + ".kt"), encoding="utf-8") as f:
        src = f.read()
    if not strip_comments:
        return src
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)//[^\n]*$", "", src)


def _composable(src, name):
    """截出单个 @Composable 函数体（到下一个顶层 } 为止，够测试用）。"""
    body = src[src.index("private fun %s(" % name):]
    return body[:body.index("\n}")]


def test_download_all_is_gone_from_tag_and_artist_pages():
    """分区页 / 画师页的页头不再有「⬇ 下载全部」；长按操作栏那项必须还在。"""
    for name in ("FeaturesWorks", "ArtistScreen"):
        src = _kt(name)
        assert "下载全部" not in src, count_hint(name)
    menu = _kt("FeaturesCardMenu")
    assert 'AppI18n.s("⬇ 下载全部")' in menu, "长按操作栏里的「下载全部」被一起删掉了（那是唯一的批量入口）"


def count_hint(name):
    return "%s 里还留着「下载全部」——页头按钮应下架，批量下载只走长按操作栏" % name


def test_probe_entry_moved_to_top_right_with_add_chip_style():
    """「⛏ 联网获取」在分区页与画师页都挪到右上角，且用的是「＋ 添加」同款胶囊（TopChip）。"""
    app = _kt("AppBars")
    assert "internal fun TopChip(" in app, "缺少共用的右上角胶囊 TopChip"
    assert "0x33 / 255f" in app and "horizontal = 10.dp, vertical = 4.dp" in app, \
        "TopChip 的规格不是「＋ 添加」那一套（0x33 底 / 10×4 内边距）"

    works = _kt("FeaturesWorks")
    top = _composable(works, "TagWorksTopRow")
    assert 'TopChip(AppI18n.s("＋ 添加")' in top, "分区页右上角「＋ 添加」没有改用 TopChip"
    assert 'TopChip("⛏ " + AppI18n.s("联网获取")' in top, "分区页右上角缺「⛏ 联网获取」"
    header = _composable(works, "TagWorksHeader")
    assert "联网获取" not in header and "ProbeEntryChip" not in header, \
        "分区页头的作品数行还留着联网获取（应已搬到右上角）"

    artist = _kt("ArtistScreen")
    page_header = _composable(artist, "ArtistPageHeader")
    assert 'TopChip("⛏ " + AppI18n.s("联网获取")' in page_header, "画师页右上角缺「⛏ 联网获取」"
    actions = _composable(artist, "ArtistWorkActions")
    assert "ProbeEntryChip" not in actions and "联网获取" not in actions, \
        "画师页作品数行还留着联网获取（应已搬到右上角）"


def test_circle_page_keeps_its_probe_entry():
    """社团内部页不动：⛏ 入口仍在（用户只要求搬画师页与分区页）。"""
    src = _kt("FeaturesCircle")
    assert "ProbeEntryChip" in src, "社团内部页的 ⛏ 入口被误删了"