# -*- coding: utf-8 -*-
"""社团封面坐标悬空时的回退（3.6.166）。

## 背景

社团封面**允许**取自别的社团：单画师社团会跟随"画师页口径"（画师名下体积最大的作品），
那部作品完全可能在别的社团。实测 746 个社团里 27 个如此，`cover_group ≠ name` 是正常的，
`find_work` 还有按真实归档目录反查的兜底（3.6.13）。

但坐标会**悬空**：那部作品被删、改名、或移出文库之后，`cover_group/cover_work` 还留着，
于是 `/cover` 恒定 404、卡片一片空白，而且**永远不会自愈**。

两个入口都要兜：

* `_verify_cover_coords`（每轮扫描末尾）：绑定后的坐标验一次，悬空就退回 `_derived_cover`；
* `public_group`（每次请求）：重新应用区域封面覆盖时，找不到作品就**不要**覆盖掉派生封面
  ——旧代码无条件覆盖，会把 `cover_work` 置空，卡片变成占位图标。
"""
import os
import sys

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
from services import index_cache, queries  # noqa: E402


def _fake_find(table):
    """table = {(group, work): work_dict}；表里没有 = 悬空。"""
    def _find(gname, wname):
        return table.get((gname, wname))
    return _find


def test_dangling_cover_falls_back_to_derived(monkeypatch):
    """绑定的封面作品没了 → 退回本社团自己的派生封面，并清掉失效的绑定状态。"""
    monkeypatch.setattr(app, "find_work", _fake_find({
        ("本社", "本社作品"): {"name": "本社作品"},
        # ("别社", "他社作品") 故意不放 → 悬空
    }))
    g = {"name": "本社", "cover_work": {"name": "他社作品"}, "cover_group": "别社",
         "_derived_cover": ("本社作品", "本社"),
         "follow_artist": "某画师", "follow_cover": ["别社", "他社作品"]}
    index_cache._verify_cover_coords([g])
    assert g["cover_work"]["name"] == "本社作品", "没退回派生封面"
    assert g["cover_group"] == "本社"
    assert "follow_artist" not in g and "follow_cover" not in g, "失效的绑定状态没清掉"


def test_valid_cross_circle_cover_is_kept(monkeypatch):
    """跨社团封面只要能找到，就不许动它——这是单画师社团的正常形态。"""
    monkeypatch.setattr(app, "find_work", _fake_find({
        ("别社", "他社作品"): {"name": "他社作品"},
        ("本社", "本社作品"): {"name": "本社作品"},
    }))
    g = {"name": "本社", "cover_work": {"name": "他社作品"}, "cover_group": "别社",
         "_derived_cover": ("本社作品", "本社"), "follow_artist": "某画师"}
    index_cache._verify_cover_coords([g])
    assert g["cover_work"]["name"] == "他社作品" and g["cover_group"] == "别社"
    assert g.get("follow_artist") == "某画师", "有效绑定被误清"


def test_derived_also_missing_then_no_cover(monkeypatch):
    """派生封面也找不回来（社团被清空等）→ 置空，前端走"无封面"分支而不是 404。"""
    monkeypatch.setattr(app, "find_work", _fake_find({}))
    g = {"name": "本社", "cover_work": {"name": "他社作品"}, "cover_group": "别社",
         "_derived_cover": ("本社作品", "本社")}
    index_cache._verify_cover_coords([g])
    assert g["cover_work"] is None and g["cover_group"] is None


def test_no_cover_work_is_untouched(monkeypatch):
    """本来就没封面的社团不该被这条校验碰（避免给空社团写进无意义的状态）。"""
    monkeypatch.setattr(app, "find_work", _fake_find({}))
    g = {"name": "本社", "cover_work": None, "_derived_cover": ("", "")}
    index_cache._verify_cover_coords([g])
    assert g == {"name": "本社", "cover_work": None, "_derived_cover": ("", "")}


def test_public_group_keeps_derived_when_region_override_dangles(monkeypatch):
    """`public_group` 重放区域封面覆盖时，坐标悬空就**不许**覆盖掉派生封面。

    旧代码无条件覆盖：`cover_work = find_work(...)`（可能是 None）→ hasCover=False →
    卡片变成占位图标，看起来像整个社团的作品都丢了。
    """
    monkeypatch.setattr(app, "_resolve_region_cover",
                        lambda scope, name: {"group": "别社", "work": "已删除的作品"})
    monkeypatch.setattr(app, "find_work", _fake_find({}))          # 覆盖坐标悬空
    monkeypatch.setattr(app, "_work_ver", lambda w: "")
    g = {"name": "本社", "works": [{"name": "本社作品"}],
         "cover_work": {"name": "本社作品"}, "cover_group": "本社",
         "cover_mtime": 0.0, "latest_work": "本社作品",
         "created_at": 0.0, "updated_at": 0.0, "total_bytes": 0}
    pub = queries.public_group(g)
    assert pub["hasCover"] is True, "悬空的区域覆盖把派生封面顶掉了"
    assert pub["coverWork"] == "本社作品" and pub["coverGroup"] == "本社"


def test_public_group_applies_valid_region_override(monkeypatch):
    """覆盖有效时仍要立即生效（set-cover 后不等重扫）。"""
    monkeypatch.setattr(app, "_resolve_region_cover",
                        lambda scope, name: {"group": "别社", "work": "他社作品"})
    monkeypatch.setattr(app, "find_work",
                        _fake_find({("别社", "他社作品"): {"name": "他社作品"}}))
    monkeypatch.setattr(app, "_work_ver", lambda w: "")
    g = {"name": "本社", "works": [{"name": "本社作品"}],
         "cover_work": {"name": "本社作品"}, "cover_group": "本社",
         "cover_mtime": 0.0, "latest_work": "本社作品",
         "created_at": 0.0, "updated_at": 0.0, "total_bytes": 0}
    pub = queries.public_group(g)
    assert pub["coverWork"] == "他社作品" and pub["coverGroup"] == "别社"
