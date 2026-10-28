# -*- coding: utf-8 -*-
"""services/crawl_dup.py —— 分区爬取里的「疑似重复」预判（3.7.61；3.7.62 收窄到分区）。

**只跟当前分区内的作品比**（用户 2026-10-22 明确）：在画师分区搜就只比这位画师的，
社团分区只比这个社团的，同人分区只比这个同人的——不扫全库。理由：
  * 同一个作品在不同分区本来就该各有一份（比如既在某社团名下、又挂某个同人），
    拿全库比会把"同人分区里那个正常条目"误判成重复；
  * 2400 部的全库扫描没必要，一个分区的作品数通常几十到几百，判起来也更准。

三条判据（用户定的）：
  1. **作品裸名称相近**：剥掉 `[社团]`/`(作者)`/`（汉化组）`/`(C102)` 等括号块与
     汉化/无修/DL版 之类标记后比较，全等或相似度 ≥ 0.90；
  2. **系列新作不算重复**：`作品名` 与 `作品名2` / `作品名 3` 视为不同作品
     （尾部数字被剥掉后相同 → 判为续作，直接放行）；
  3. **页数相近**：汉化组会塞自己的图片，所以允许 ±28% 或 ±3 页的偏差；
     任一方页数未知（JM 搜索不给页数）则不参与判定。

只做提示，不拦下载：结果里带 `dup` 字段，前端按收件箱同款「⚠ 疑似重复」标记。
没有分区上下文（从抽屉直接进来、词条为空）时不判定。
"""
import time

from common import crawl_log as log    # 3.6.156：services 层零 crawlers 顶层依赖
from djc_parse import _norm_key    # 3.6.156：实现下沉 djc_parse

from panel.host import h

# 名称里没有信息量的标记：去掉后再比
_NOISE = (
    "中国翻訳", "中国翻译", "中文翻译", "漢化", "汉化", "個人漢化", "个人汉化",
    "機翻", "机翻", "無修正", "无修正", "無碼", "无码", "dl版", "DL版", "中文版",
    "中国語", "中国语", "全彩", "彩色", "完全版", "修正版",
)
_SEP = "[]()（）【】「」『』・·。.，,～~〜!！?？♡♥♪☆★×+:：;；|｜／/\\—_-'\"“”‘’　 "

SCOPES = ("author", "circle", "original")
_CACHE = {}          # (kind, norm_term) -> {"at": ts, "rows": [...]}
TTL = 60.0


def _norm(name):
    """裸名称归一：去括号块 → 去噪音标记 → 去标点空白 → 折叠简繁（复用解析器同一套）。"""
    import re
    s = str(name or "")
    s = re.sub(r"\[[^\[\]]*\]|【[^【】]*】|（[^（）]*）|\([^()]*\)", " ", s)
    low = s.lower()
    for w in _NOISE:
        if w.lower() in low:
            low = low.replace(w.lower(), " ")
    return _norm_key(low).strip(_SEP)


def _is_sequel(a, b):
    """a、b 归一后只差尾部数字 → 系列新作，不算重复。"""
    import re
    if a == b:
        return False
    return re.sub(r"\d+$", "", a) == re.sub(r"\d+$", "", b)


def _pages_close(pa, pb):
    """页数相近：任一方未知则放行；汉化组会多塞几张，所以允许 28%。"""
    try:
        a, b = int(pa or 0), int(pb or 0)
    except (TypeError, ValueError):
        return True
    if a <= 0 or b <= 0:
        return True
    if abs(a - b) <= 3:
        return True
    return min(a, b) / float(max(a, b)) >= 0.72


def _in_scope(kind, term_key, group, work):
    """该作品是否属于这个分区（社团 / 画师 / 同人）。"""
    if kind == "circle":
        names = [group.get("name")] + list(work.get("circles") or [])
        return any(n and _norm_key(str(n)) == term_key for n in names)
    tag_type = "personal" if kind == "author" else "original"
    for t, v in work.get("tags") or []:
        if t == tag_type and v and _norm_key(str(v)) == term_key:
            return True
    return False


def _collect_rows(kind, term_key):
    """遍历文库，挑出属于该分区的作品（`_rows` 的实体部分）。"""
    rows = []
    try:
        lib = h().get_library()
    except Exception as e:                              # noqa: BLE001 —— 没索引就不提示
        log("[去重] 读文库失败，本次不判重复：%s" % str(e)[:60])
        return rows
    for g in lib.get("groups") or []:
        for w in g.get("works") or []:
            if not _in_scope(kind, term_key, g, w):
                continue
            name = w.get("name") or ""
            rows.append({"norm": _norm(name), "name": name,
                         "key": str(w.get("path") or name),
                         "pages": w.get("pages") or 0,
                         "group": g.get("name") or ""})
    return rows


def _rows(kind, term):
    """该分区内作品的扁平索引（按分区缓存 60s：一次搜索要判上百条）。"""
    if kind not in SCOPES:
        return []
    key = (kind, _norm_key(str(term or "")))
    if not key[1]:
        return []                       # 没有分区上下文 → 不判
    hit = _CACHE.get(key)
    if hit and time.time() - hit["at"] < TTL:
        return hit["rows"]
    rows = _collect_rows(kind, key[1])
    _CACHE[key] = {"at": time.time(), "rows": rows}
    return rows


def _similar(a, b):
    """归一后相似度：全等 1.0，否则编辑距离比。"""
    import difflib
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def find(title, pages=0, kind="", term=""):
    """返回**该分区内**与之疑似重复的作品；没有则 None。

    返回 `{"name", "group", "pages", "score", "why"}`，前端只用到 name/why。
    """
    n = _norm(title)
    if not n:
        return None
    best, best_score = None, 0.0
    for row in _rows(kind, term):
        if not row["norm"]:
            continue
        sc = _similar(n, row["norm"])
        if sc < 0.90 or sc <= best_score:
            continue
        if _is_sequel(n, row["norm"]):
            continue                      # 作品名 / 作品名2 → 系列新作
        if not _pages_close(pages, row["pages"]):
            continue                      # 页数差太多（如短篇 vs 长篇合集）
        best, best_score = row, sc
    if not best:
        return None
    why = "名称一致" if best_score >= 0.999 else "名称相近 %d%%" % round(best_score * 100)
    if pages and best["pages"]:
        why += " · 页数 %s/%s" % (pages, best["pages"])
    return {"name": best["name"], "group": best["group"], "key": best["key"],
            "pages": best["pages"], "score": round(best_score, 3), "why": why}


def annotate(works, kind="", term=""):
    """给搜索结果逐条打 `dup`（原地修改并返回列表）。

    没有 `kind`/`term`（不在任何分区上下文里）时一律置 None：宁可不错标。
    """
    for w in works or []:
        try:
            w["dup"] = find(w.get("title") or "", w.get("pages") or 0, kind, term)
        except Exception as e:                          # noqa: BLE001 —— 判定失败不影响搜索
            log("[去重] 判定失败：%s %s" % (type(e).__name__, str(e)[:60]))
            w["dup"] = None
    return works


def invalidate():
    """库内变动（入库/删除/重扫）后调用，下一次判定重新索引。"""
    _CACHE.clear()
