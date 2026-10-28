# -*- coding: utf-8 -*-
"""services/crawl_lock.py —— 爬取任务的第一阶段「锁定」（3.7.58）。

把清单里的一条词条解析成**具体作品**：站点 id、标题、封面。只查不下载——
这样"哪些词条其实找不到作品"在下载开始前就暴露出来，面板也能先摆出一张张带封面的
卡片，而不是让人盯着滚动日志猜进度。

五个任务的差别只在这一步（wnacg 直接匹配 / JM 索引先取专辑名 / N站索引先解析 ID /
直连模式锁定专辑或画廊），下载统一在 `crawl_fetch.py`。
"""
from common import crawl_log as _clog    # 3.6.156：services 层零 crawlers 顶层依赖


class NoMatch(Exception):
    """没解析出作品（词条写法、站点没有、搜索无匹配…）。"""


class Skip(Exception):
    """该条目无需爬取（库内已有相似文件）。"""


class Ctx:
    """一次任务共享的上下文：域名、jmcomic 客户端（懒建）、N站凭证、档位阈值。"""

    def __init__(self, kind, strict):
        self.kind = kind
        self.strict = strict
        self.score = 0.80 if strict else 0.60
        self.domain = ""
        self.client = None
        self.jm_module = None
        self.jm_option = None
        self.nh_auth = None


def _crawler(name):
    import importlib
    return importlib.import_module("crawlers." + name)


def _domain(ctx):
    """当前可用站点域名（沿用脚本的发布页/缓存/内置候选），失败即整批锁定失败。"""
    if ctx.domain:
        return ctx.domain
    C = _crawler("crawl_wnacg")
    try:
        ctx.domain, _proxied = C.resolve_domain(C.load_state())
    except Exception as e:                              # noqa: BLE001
        raise NoMatch("站点域名不可用：%s" % str(e)[:60])
    return ctx.domain


def _jm_client(ctx):
    if ctx.client is None:
        import common
        common.merge_pip_common()
        import jmcomic
        from jmcomic import JmOption
        ctx.jm_module, ctx.jm_option = jmcomic, JmOption
        ctx.client = JmOption.default().new_jm_client()
    return ctx.client


def _jm_cover(ctx, aid):
    """JM 封面：固定可用镜像拼地址。

    不用 jmcomic 的 get_album_cover_url：它 random.choice 整个图床表，而
    `cdn-msp*.jmapiproxy*.cc` 一族已全部不可用（403/断连），等于一半概率抽到死域名——
    这正是"清单爬虫几乎从没成功抓到过封面"的根因之一。"""
    try:
        from services.crawl_probe_sites import jm_cover_url
        return jm_cover_url(aid)
    except Exception:                                   # noqa: BLE001 —— 没封面就占位图
        return ""


def _thumb(domain, aid):
    """封面：先用搜索阶段顺带记下的缩略图（零请求），没有再抓作品页。

    以前无条件抓作品页：多一次往返（实测 +17s/部），站点一抖就整批没封面——
    用户反馈"清单爬虫几乎从没成功抓到过封面"就是这个。"""
    try:
        from crawlers import wnacg_match
        t = wnacg_match.thumb_of(aid)
        if t:
            return t
    except Exception as e:                              # noqa: BLE001 —— 回落即可
        _clog("[锁定] 取搜索缩略图失败，回落作品页：%s %s"
              % (type(e).__name__, str(e)[:60]))
    try:
        from crawlers.wnacg_search import gallery_thumb
        return gallery_thumb(domain, aid)
    except Exception as e:                              # noqa: BLE001
        _clog("[锁定] 取封面失败 aid=%s：%s" % (aid, str(e)[:60]))
        return ""


def _match_title(title, ctx, entry, site="wnacg", rt=None, name=None):
    """标题 → wnacg 站内匹配（JM/N站索引模式都靠它落到具体转载作品）。"""
    C = _crawler("crawl_wnacg")
    p = C.parse_entry(title)
    if not p:
        raise NoMatch("标题无法解析出社团/标题：%s" % str(title)[:40])
    term, t, key = p
    try:
        hit = C.find_gallery(_domain(ctx), term, t, key,
                             min_score=ctx.score, strict=ctx.strict)
    except Exception as e:                              # noqa: BLE001
        raise NoMatch("站点搜索失败：%s %s" % (type(e).__name__, str(e)[:60]))
    if not hit:
        raise NoMatch("站点未找到匹配作品（下限 %.0f%%）" % (ctx.score * 100))
    aid, stitle, score = hit
    return {"title": stitle, "aid": aid, "site": site, "score": round(score, 3),
            "cover": _thumb(ctx.domain, aid), "name": name or stitle, "rt": rt or {}}


def lock_wnacg(entry, ctx):
    """wnacg 主爬：词条自带社团/标题，直接站内匹配。"""
    C = _crawler("crawl_wnacg")
    p = C.parse_entry(entry)
    if not p:
        raise NoMatch("词条无法解析（形如 [社团 (画师)] 标题）")
    term, title, key = p
    dup = C.existing_duplicate(C.STAGING_DIR, key)
    if dup:
        raise Skip(str(dup)[:80])
    try:
        hit = C.find_gallery(_domain(ctx), term, title, key,
                             min_score=ctx.score, strict=ctx.strict)
    except Exception as e:                              # noqa: BLE001
        raise NoMatch("站点搜索失败：%s %s" % (type(e).__name__, str(e)[:60]))
    if not hit:
        raise NoMatch("站点未找到匹配作品（下限 %.0f%%）" % (ctx.score * 100))
    aid, stitle, score = hit
    return {"title": stitle, "aid": aid, "site": "wnacg", "score": round(score, 3),
            "cover": _thumb(ctx.domain, aid), "name": entry}


def lock_jm(entry, ctx):
    """JM 索引：车号 → 专辑名 → wnacg 转载。"""
    return _match_title(_jm_title(_jm_client(ctx), entry), ctx, entry,
                        site="wnacg", rt={"jm_id": entry})


def lock_nh(entry, ctx):
    """N站索引：数字 ID 或词条 → gid → 日文名 → wnacg 转载。"""
    C = _crawler("crawl_wnacg")
    gid, name = str(entry).strip(), ""
    if not gid.isdigit():
        gid, name, _score = C.nh_resolve_gid(entry, min_score=ctx.score)
        if not gid:
            raise NoMatch("N站搜索无匹配（下限 %.0f%%）" % (ctx.score * 100))
    if not name:
        name = _nh_name(gid)
    return _match_title(name, ctx, entry, site="wnacg", rt={"gid": str(gid)})


def _nh_name(gid):
    try:
        ND = _crawler("crawl_nh_direct")
        return ND.gallery_title(ND.nh_get_json(gid))
    except Exception as e:                              # noqa: BLE001
        raise NoMatch("取不到 N站作品标题：%s %s" % (type(e).__name__, str(e)[:60]))


def _jm_title(client, jid):
    try:
        title = (client.get_album_detail(jid).name or "").strip()
    except Exception as e:                              # noqa: BLE001
        raise NoMatch("取不到 JM 专辑标题：%s %s" % (type(e).__name__, str(e)[:60]))
    if not title:
        raise NoMatch("JM 专辑标题为空")
    return title


def lock_jmdl(entry, ctx):
    """JM 直连：车号直接用，词条走 JM 站内搜索；锁定的是专辑本身（不经 wnacg）。"""
    JD = _crawler("crawl_jm_direct")
    client = _jm_client(ctx)
    aid, why = JD._resolve_aid(client, entry, ctx.score, "")
    if not aid:
        raise NoMatch(why or "JM 搜索无匹配")
    title = _jm_title(client, aid)
    return {"title": title, "aid": str(aid), "site": "jmcomic",
            "cover": _jm_cover(ctx, aid), "name": title}


def lock_nhdl(entry, ctx):
    """N站直连：ID/词条 → 画廊元数据；封面取 N站缩略图。"""
    ND = _crawler("crawl_nh_direct")
    gid, meta = ND.resolve_entry(entry, ctx.score)
    title = ND.gallery_title(meta) or ("NH%s" % gid)
    cover = ""
    try:
        from services.crawl_probe_sites import _nh_thumb
        cover = _nh_thumb(meta.get("thumbnail") or "")
    except Exception:                                   # noqa: BLE001 —— 没封面不影响下载
        cover = ""
    return {"title": title, "aid": str(gid), "site": "nhentai", "cover": cover,
            "name": title, "pages": int(meta.get("num_pages") or 0),
            "rt": {"gid": str(gid), "meta": meta}}


def lock_eh(entry, ctx):
    """E站直连：画廊 URL/gid 或词条 → (gid, token) + gdata 元数据；封面取 EH 缩略图。"""
    EH = _crawler("crawl_ehentai")
    gid, token, title_m, _score = EH.E.resolve_entry(str(entry), ctx.score)
    meta = EH.E.gdata(gid, token)
    title = EH.gallery_title(meta) or title_m or ("EH%s" % gid)
    return {"title": title, "aid": str(gid), "site": "ehentai",
            "cover": str(meta.get("thumb") or ""), "name": title,
            "pages": int(meta.get("pagecount") or 0),
            "rt": {"gid": str(gid), "token": str(token), "meta": meta}}


LOCKERS = {"wnacg": lock_wnacg, "jm": lock_jm, "nh": lock_nh,
           "jmdl": lock_jmdl, "nhdl": lock_nhdl, "eh": lock_eh}
