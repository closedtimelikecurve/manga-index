# -*- coding: utf-8 -*-
"""services/crawl_probe_sites.py —— 「分区爬取」的多站点搜索/下载适配（3.7.57）。

为什么单独成模块：`crawl_probe.py` 只管封面代理与统一结果结构，站点差异
（JM 的 jmcomic 客户端 / N 站的 v2 JSON API / 各自的下载器）放这里，避免把
一个 400 行预算内的文件继续撑大。

统一结果：
  ```
  {"works": [{"aid": int, "title": str, "pages": int, "thumb": str}],
   "total": int, "per_page": int, "hasMore": bool, "nextStart": int}
  ```
  `thumb` 是原图站地址；服务层再包成 `/api/crawl/probe/cover?u=…` 代理。
"""
import queue
import threading
import urllib.parse

import common
from common import crawl_log as log    # 3.6.156：services 层零 crawlers 顶层依赖

SITES = ("wnacg", "jmcomic", "nhentai", "ehentai")
SITE_LABELS = {"wnacg": "wnacg", "jmcomic": "JM", "nhentai": "N站", "ehentai": "E站"}
SITE_HINTS = {
    "wnacg": "wnacg 站内搜索：按画师 / 社团 / 同人名找转载作品，封面与页数一次带出",
    "jmcomic": "JM 站内搜索：直接找禁漫原站作品，勾选后整本下载并还原图片分割",
    "nhentai": "N站搜索：v2 API 按日文/英文/罗马音找作品，勾选后下载整本 ZIP",
    "ehentai": "E站搜索：按画师/社团/原作 tag 找画廊（分区名自动映射 artist:/group:/parody:），"
               "种子优先（需 aria2c）逐页兜底；强制走代理，匿名可见范围有限",
}
DEFAULT_SITE = "wnacg"
SEARCH_TIMEOUT = 30.0        # 单次站点搜索上限：JM/NH 库的重试链在代理坏掉时可挂 1~2 分钟


def _run_with_timeout(fn, timeout, label):
    """在守护线程里跑搜索并限时返回。JM/NH 库自带多域重试，网络坏时不能让 HTTP 线程陪着挂死。
    超时后后台线程由 daemon 收尾（不再有人等它），主流程立即报错给用户。"""
    q = queue.Queue(maxsize=1)

    def run():
        try:
            q.put((True, fn()))
        except Exception as e:                         # noqa: BLE001
            q.put((False, e))

    t = threading.Thread(target=run, daemon=True, name="probe-site-search")
    t.start()
    try:
        ok, val = q.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError("%s超时（%.0fs，站点不可达或代理异常）" % (label, timeout))
    if not ok:
        raise val
    return val


def site_of(site):
    s = str(site or "").strip().lower()
    return s if s in SITES else DEFAULT_SITE


# 3.6.156：分区爬取的站点可用性（公开版只带 JM 直连 → 只有 jmcomic 站点可用）。
_SITE_MODULE = {"wnacg": "crawlers.crawl_wnacg", "jmcomic": "crawlers.crawl_jm_direct",
                "nhentai": "crawlers.crawl_nh_direct", "ehentai": "crawlers.crawl_ehentai"}


def site_available(site):
    """该站点的适配模块是否随发行版提供（wnacg 走 wnacg 网络栈，jm 底座即 crawl_jm_direct）。"""
    import importlib.util
    mod = _SITE_MODULE.get(site_of(site))
    if mod is None:
        return False
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def site_label(site):
    return SITE_LABELS[site_of(site)]


def _nh_thumb(thumbnail):
    """缩略图 → 绝对地址。字段形状有两种，都要认（3.7.66）：

      * v2 搜索 / 网页结果：`galleries/<media_id>/thumb.webp` 这类**字符串**；
      * v2 画廊详情（`/api/v2/galleries/<id>`）：**对象**
        `{"path": "galleries/4261212/thumb.webp", "width": …, "height": …}`。
        以前直接 `str(dict)`，拼出 `https://t.nhentai.net/{'path': …}` 这种废地址，
        清单爬虫的 N站直连作品因此永远没有封面。
    """
    if isinstance(thumbnail, dict):
        thumbnail = thumbnail.get("path") or ""
    t = str(thumbnail or "").strip()
    if not t:
        return ""
    if t.startswith("//"):
        return "https:" + t
    if t.startswith("/"):
        return "https://t.nhentai.net" + t
    if not t.startswith("http"):
        return "https://t.nhentai.net/" + t
    return t


def nh_api_search_url(term, page):
    return ("https://nhentai.net/api/v2/search?query="
            + urllib.parse.quote(str(term or "").strip()) + "&page=" + str(page))


# JM 封面图床（3.7.61 实测）：`cdn-msp*.jmapiproxy*.cc` 一族现在全部不可用
# （403/连接被断），`cdn-msp*.jmapinodeudzn.net` 是可用镜像、且同一车号在各镜像上都存在。
# 所以**不再**用 jmcomic 的 get_album_cover_url —— 它 random.choice 整个域名表，
# 等于一半概率抽到死域名，封面时有时无。
JM_COVER_HOSTS = ("cdn-msp.jmapinodeudzn.net", "cdn-msp3.jmapinodeudzn.net")


def jm_cover_url(aid):
    """JM 封面地址（按车号直接拼，零网络请求）。失败只可能是不合法车号 → 返回 ""。"""
    try:
        return "https://%s/media/albums/%d.jpg" % (JM_COVER_HOSTS[0], int(aid))
    except (TypeError, ValueError):
        return ""


def _search_jm_page(term, page):
    common.merge_pip_common()
    from jmcomic import JmOption
    client = JmOption.default().new_jm_client()
    return client.search_site(str(term or "").strip(), page=page)


def search_jm(term, page=1):
    """JM 站内搜索一页（80 条/页）。返回统一结果；失败/超时抛异常。"""
    page = max(1, int(page or 1))
    try:
        p = _run_with_timeout(lambda: _search_jm_page(term, page),
                              SEARCH_TIMEOUT, "JM 搜索")
    except Exception as e:
        log("[分区爬取-JM] 搜索失败：%s %s" % (type(e).__name__, str(e)[:80]))
        raise
    works, seen = [], set()
    for aid, info in (getattr(p, "content", None) or []):
        try:
            aid = int(aid)
        except (TypeError, ValueError):
            continue
        if aid in seen:
            continue
        seen.add(aid)
        title = str(info.get("name") or info.get("title") or "").strip()
        works.append({"aid": aid, "title": title or ("JM%s" % aid),
                      "pages": int(info.get("page_count") or 0),
                      "thumb": jm_cover_url(aid)})
    total = int(getattr(p, "total", 0) or 0)
    per_page = int(getattr(p, "page_size", 0) or 80)
    return {"works": works, "total": total, "per_page": per_page,
            "hasMore": bool(total and page * per_page < total),
            "nextStart": page + 1}


def _search_nh_page(url):
    from crawlers import nh_api
    return nh_api.nh_get_json(url)


def search_nh(term, page=1):
    """N站 v2 搜索一页（25 条/页）。返回统一结果；失败/超时抛异常。"""
    page = max(1, int(page or 1))
    url = nh_api_search_url(term, page)
    try:
        d = _run_with_timeout(lambda: _search_nh_page(url),
                              SEARCH_TIMEOUT, "N站搜索")
    except Exception as e:
        log("[分区爬取-NH] 搜索失败：%s %s" % (type(e).__name__, str(e)[:80]))
        raise
    works, seen = [], set()
    for it in (d.get("result") or []):
        try:
            gid = int(it.get("id"))
        except (TypeError, ValueError):
            continue
        if gid in seen:
            continue
        seen.add(gid)
        title = str(it.get("japanese_title") or it.get("english_title") or "").strip()
        works.append({"aid": gid, "title": title or ("NH%s" % gid),
                      "pages": int(it.get("num_pages") or 0),
                      "thumb": _nh_thumb(it.get("thumbnail"))})
    total = int(d.get("total") or 0)
    per_page = int(d.get("per_page") or 0 or 25)
    return {"works": works, "total": total, "per_page": per_page,
            "hasMore": bool(total and page * per_page < total),
            "nextStart": page + 1}


def search(site, term, page=1, kind=""):
    """非 wnacg 站点的搜索入口。kind 只 EH 用（画师/社团/原作 → artist:/group:/parody: 前缀）。"""
    s = site_of(site)
    if not site_available(s):
        raise TimeoutError("%s 适配未包含在此发行版中" % SITE_LABELS[s])
    if s == "jmcomic":
        return search_jm(term, page)
    if s == "nhentai":
        return search_nh(term, page)
    if s == "ehentai":
        return search_eh(term, page, kind)
    raise ValueError("search() 不处理 wnacg：它有自己的多页/域名兜底逻辑")


def download(site, aid, title, token="", on_progress=None):
    """非 wnacg 站点下载。返回 (落盘路径|None, 失败原因)。
    EH 的 aid 是 gid，token 必带；JM/N站/E站 3.6.112 起支持字节进度回调。"""
    s = site_of(site)
    if s == "jmcomic":
        return _download_jm(aid, title, on_progress=on_progress)
    if s == "nhentai":
        return _download_nh(aid, on_progress=on_progress)
    if s == "ehentai":
        return _download_eh(aid, token, title, on_progress=on_progress)
    return None, "未知站点"


_EH_KIND_PREFIX = {"author": "artist:", "circle": "group:", "original": "parody:"}


def search_eh(term, page=1, kind=""):
    """E站搜索一页（25 条/页）。kind → tag 前缀映射；强制走代理（eh_api 内实现）。"""
    page = max(1, int(page or 1)) - 1          # EH 搜索页码 0 基
    prefix = _EH_KIND_PREFIX.get(str(kind or ""), "")
    q = (prefix + str(term or "").strip()).strip()
    if not q:
        raise ValueError("E站搜索词条为空")
    d = _run_with_timeout(lambda: _search_eh_page(q, page), SEARCH_TIMEOUT, "E站搜索")
    works = [{"aid": w["gid"], "token": w["token"], "title": w["title"],
              "pages": w["pages"], "thumb": w["thumb"]} for w in d["works"]]
    return {"works": works, "total": 0, "per_page": 25,
            "hasMore": bool(d["hasMore"]), "nextStart": max(1, page + 1) + 1}


def _search_eh_page(query, page0):
    from crawlers import eh_api
    return eh_api.search_page(query, page0)


def _download_eh(aid, token="", title="", on_progress=None):
    """E站整本下载（种子优先/逐页兜底 → zip 落收件箱）。token 来自搜索结果（勾选透传）。"""
    try:
        import importlib
        EH = importlib.import_module("crawlers.crawl_ehentai")
        from crawlers import eh_api
        gid = int(str(aid))
        if not token:
            return None, "缺画廊 token（旧版客户端勾选的结果）——升级 APP 或重新搜索后再试"
        meta = eh_api.gdata(gid, token)
        t = EH.gallery_title(meta) or title or ("EH%s" % gid)
        zpath, _pages, reason = EH._fetch_zip(gid, token, meta, t, on_progress=on_progress)
        return zpath, (reason or None)
    except Exception as e:
        log("[分区爬取-EH] 下载失败：%s %s" % (type(e).__name__, str(e)[:100]))
        return None, "E站下载失败：%s %s" % (type(e).__name__, str(e)[:80])


def _download_jm(aid, title, on_progress=None):
    common.merge_pip_common()
    try:
        import importlib
        import jmcomic
        from jmcomic import JmOption
        JD = importlib.import_module("crawlers.crawl_jm_direct")
        zpath, pages = JD._download_album(jmcomic, JmOption, aid, title,
                                          on_progress=on_progress)
        return zpath, (None if zpath else "JM 下载失败")
    except Exception as e:
        log("[搜索下载器-JM] 下载失败：%s %s" % (type(e).__name__, str(e)[:100]))
        return None, "JM 下载失败：%s %s" % (type(e).__name__, str(e)[:80])


def _download_nh(aid, on_progress=None):
    try:
        import importlib
        ND = importlib.import_module("crawlers.crawl_nh_direct")
        auth = ND._nh_credential()
        gid, meta, _via = ND.resolve_entry(str(aid), 0.60)
        title = ND.gallery_title(meta)
        zpath, _pages, reason = ND._fetch_zip(gid, meta, title, auth,
                                              on_progress=on_progress)
        return zpath, (reason or None)
    except Exception as e:
        log("[分区爬取-NH] 下载失败：%s %s" % (type(e).__name__, str(e)[:100]))
        return None, "N站下载失败：%s %s" % (type(e).__name__, str(e)[:80])
