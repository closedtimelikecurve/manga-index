# -*- coding: utf-8 -*-
"""services/crawl_probe.py —— 「分区爬取」的探测层（3.7.54；3.7.57 多站点）。

两步，都很轻：
  1) `probe_search(term, kind, pages, start, site)`：站点搜索 → 标题 + 页数 + **压缩封面**；
     站点 = wnacg / jmcomic / nhentai，差异在 `services/crawl_probe_sites.py`；
  2) `probe_cover(url)`：把站点缩略图抓回来，重编码成小图并落盘缓存。

封面为什么要自己转一道：站点缩略图在第三方域名（`t4.wnimg2.cfd` / `t.nhentai.net`）上，
手机侧未必能直连；原始 webp 对流量也偏大。这里统一重编码成 **160px 宽的 WebP**
（Pillow 不支持时退回 JPEG），并按 URL 哈希落 `_cache/crawl_thumb/`，二次请求零网络。

3.7.55 两项提速（用户实测"封面加载太慢 / 只出 24 部"）：
  * **不再走爬虫限速**：`fetch(..., throttle=False)`——限速是给站点页面用的 1.2~2.5s/次，
    24 张封面排队就是 30 秒起步，这是"慢"的根因；
  * **搜索即预热**：结果一返回就用 4 线程把封面抓进缓存（`_warm_covers`），
    浏览器随后请求时基本都是磁盘命中；同一 URL 的在途请求会被合并（`_INFLIGHT`），
    不会两张线程各抓一遍。

安全：`probe_cover` 是唯一"按用户给的 URL 出站"的入口，必须限定在站点域名族
（wnimg / wnacg / www.wnNN）——否则就是一个可打内网的 SSRF 洞。
"""
import hashlib
import os
import queue
import re
import threading
import time
import urllib.parse

import common
from common import crawl_log as log    # 3.6.156：services 层零 crawlers 顶层依赖；
# BUILTIN_DOMAINS（wnacg 域名表）与 fetch（wnacg 网络层）只在封面代理的函数体内用，
# 改为函数内延迟 import——公开发行版不含 wnacg 适配时本模块照常导入。
from services import crawl_dup
from services import crawl_probe_sites as sites

from panel.deps import PIL_OK, PILImage

KINDS = ("author", "circle", "original")
KIND_HINTS = {
    "author": "按画师名搜索：站点标题里的 `[社团 (作者)]` 会被逐字匹配",
    "circle": "按社团名搜索：命中的作品入库时会归到同名社团目录",
    "original": "按同人名搜索：命中的作品入库后自动挂上该同人标签",
}
SITE_HINTS = sites.SITE_HINTS
SITE_PAGE = 24                # 站点每页条数（实测），用于按 total 推算还要几页
MAX_PAGES = 8                 # 单次最多抓 8 页（192 部）；再多让用户"继续加载"
THUMB_MAX_W = 160
THUMB_QUALITY = 46

# 缩略图域名会校验 Referer（实测：不带 Referer 直接被 reset / SSL EOF），
# 所以记住"上次搜索成功的站点域名"当 Referer 用，未搜索过则用内置域名的第一个。
_SITE = [""]
_HOST_OK_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$", re.I)
_FAMILY_RE = re.compile(r"^(?:t\d+\.)?(?:wnimg\d*|wnacg\d*|www\.wn\d+)\.[a-z]+$", re.I)
# 3.7.58：JM 图床（`cdn-msp*.jmapiproxy*.cc` / `jmapinodeudzn.net`）。直连爬取的
# 锁定期要显示封面，必须放行；仍按"已知图床"白名单，不是任意域名。
_JM_IMG_RE = re.compile(r"^cdn-msp\d*\.(?:jmapiproxy\d*\.cc|jmapinodeudzn\.net)$", re.I)

_LOCK = threading.Lock()
_INFLIGHT = set()             # 正在抓的封面 URL（预热与浏览器请求撞车时合并）
_FETCH_SEM = threading.BoundedSemaphore(6)   # 同时出站的封面数上限（图站会 reset 突发连接）
_WARM_GEN = [0]              # 预热代际：换词条后旧批次立即停手


def _thumb_dir():
    """封面缓存目录（`_cache/crawl_thumb/`，可删——删了下次重新抓）。"""
    d = os.path.join(common.CACHE_DIR, "crawl_thumb")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        log("[封面] 创建缓存目录失败（封面将不落盘，每次重新抓）")
    return d


def _cover_allowed(url):
    """只放行站点域名族的 http(s) 封面地址（防 SSRF）。"""
    try:
        sp = urllib.parse.urlsplit(url)
    except Exception:
        return False
    if sp.scheme not in ("http", "https"):
        return False
    host = (sp.hostname or "").lower()
    if not host or not _HOST_OK_RE.match(host) or "." not in host:
        return False
    from crawlers.wnacg_base import BUILTIN_DOMAINS    # 延迟：公开版无此模块时走下面白名单
    if host in {d.lower() for d in BUILTIN_DOMAINS}:
        return True
    if host == "nhentai.net" or host.endswith(".nhentai.net"):
        return True              # 3.7.57：N站封面（t/t3/i.nhentai.net）
    if _JM_IMG_RE.match(host):
        return True              # 3.7.58：JM 图床封面（cdn-msp*.jmapiproxy*.cc）
    if host == "ehgt.org" or host.endswith(".ehgt.org"):
        return True              # 3.6.110：E站缩略图域族（ehgt/ul.ehgt/s.ehgt）
    return bool(_FAMILY_RE.match(host))


def _referer():
    from crawlers.wnacg_base import BUILTIN_DOMAINS    # 延迟：公开版无此模块
    d = _SITE[0] or (BUILTIN_DOMAINS[0] if BUILTIN_DOMAINS else "")
    return ("https://%s/" % d) if d else None


def _fetch_cover(url):
    """抓封面字节：带站点 Referer 优先，失败再试无 Referer。

    不走 `_throttle`（那是站点页面的限速）：封面是小图、成批、与作品页无关，
    排队等待只会把"24 张图"变成"30 秒白板"。超时也压到 15s。"""
    last = None
    if "nhentai.net" in url:
        ref0 = "https://nhentai.net/"
    elif "ehgt.org" in url:
        ref0 = "https://e-hentai.org/"       # 3.6.110：E站缩略图
    else:
        ref0 = _referer()
    for ref in (ref0, None):
        for _round in (1, 2):
            try:
                from crawlers.wnacg_net import fetch    # 延迟：公开版无 wnacg 网络层
                # 不指定通道：沿用"上次走通的那条"（封面域名与站点不同，强制直连实测更慢）
                return fetch(url, referer=ref, timeout=12, binary=True, throttle=False)
            except Exception as e:
                last = e
                time.sleep(0.3)
    raise last


def _compress(raw):
    """原图 → 160px 小图。优先 WebP（同画质约省 30%），Pillow 缺失/解码失败则原样透传。"""
    if not PIL_OK or PILImage is None:
        return raw, "image/webp"
    try:
        from io import BytesIO
        im = PILImage.open(BytesIO(raw)).convert("RGB")
        im.thumbnail((THUMB_MAX_W, THUMB_MAX_W * 2))
        out = BytesIO()
        try:
            im.save(out, "WEBP", quality=THUMB_QUALITY, method=4)
            return out.getvalue(), "image/webp"
        except Exception:
            out = BytesIO()
            im.save(out, "JPEG", quality=THUMB_QUALITY, optimize=True)
            return out.getvalue(), "image/jpeg"
    except Exception as e:
        log("[封面] 重编码失败，按原始字节透传：%s %s" % (type(e).__name__, str(e)[:60]))
        return raw, "image/webp"


def _cache_paths(url):
    """同一 URL 的两个候选缓存文件（WebP 优先，JPEG 兜底）。"""
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    d = _thumb_dir()
    return os.path.join(d, key + ".webp"), os.path.join(d, key + ".jpg")


def _from_cache(url):
    """命中磁盘缓存 → (字节, mime)；未命中 → None。"""
    webp, jpg = _cache_paths(url)
    for path, mime in ((webp, "image/webp"), (jpg, "image/jpeg")):
        try:
            with open(path, "rb") as f:
                return f.read(), mime
        except OSError:
            continue
    return None


def _wait_cache(url, seconds=8.0):
    """别的线程正在抓同一张（预热撞车）：短等它落盘，避免重复出站。"""
    deadline = time.time() + seconds
    while time.time() < deadline:
        hit = _from_cache(url)
        if hit:
            return hit
        time.sleep(0.05)
    return None


def _fetch_and_cache(url):
    """出站抓 + 压缩 + 落盘。并发上限 6：图站对突发连接会 reset，压住反而更快。"""
    with _FETCH_SEM:
        raw = _fetch_cover(url)
    data, mime = _compress(raw)
    path = _cache_paths(url)[0 if mime == "image/webp" else 1]
    try:
        with open(path, "wb") as f:
            f.write(data)
    except OSError as e:
        log("[封面] 缓存写盘失败（不影响本次返回）：%s" % str(e)[:60])
    return data, mime


def probe_cover(url, refresh=False):
    """返回 (字节, mime)。带磁盘缓存 + 在途合并：同一 URL 只出站一次。

    在途撞车时**不会返回空**——先等对方落盘（最多 8 秒），等不到就自己抓。
    早先那版直接返回空字节，浏览器把 <img> 记成加载失败、不会重试，表现为
    "一页里有几张永远不显示"。"""
    url = str(url or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    if not url or not _cover_allowed(url):
        return b"", "image/jpeg"
    if not refresh:
        hit = _from_cache(url)
        if hit:
            return hit
    with _LOCK:
        mine = url not in _INFLIGHT
        if mine:
            _INFLIGHT.add(url)
    if not mine:
        hit = _wait_cache(url)
        if hit:
            return hit
        try:
            return _fetch_and_cache(url)
        except Exception as e:
            log("[封面] 抓取失败（卡片显示占位图）：%s %s %s"
                % (url[:80], type(e).__name__, str(e)[:60]))
            return b"", "image/jpeg"
    try:
        return _fetch_and_cache(url)
    except Exception as e:
        log("[封面] 抓取失败（卡片显示占位图）：%s %s %s"
            % (url[:80], type(e).__name__, str(e)[:60]))
        return b"", "image/jpeg"
    finally:
        with _LOCK:
            _INFLIGHT.discard(url)


def _warm_covers(thumbs):
    """后台预热：结果一出来就并发抓封面，浏览器随后基本都是缓存命中。

    两个约束：
      * 用**守护线程**（不是 ThreadPoolExecutor）：线程池 worker 是非守护线程，进程退出
        时会被 join，一批抓不到的封面能把关闭卡几分钟——预热是尽力而为，不该拖住退出；
      * **代际号**（`_WARM_GEN`）：用户连续换词条时，旧批次的预热立刻停手，
        否则每搜一次就多 4 条线程扒图站，越积越多。
    失败不抛：`probe_cover` 内部已记录并返回空字节。"""
    todo = [t for t in (thumbs or []) if t and not _from_cache(t)][:MAX_PAGES * SITE_PAGE]
    if not todo:
        return
    _WARM_GEN[0] += 1
    gen = _WARM_GEN[0]
    q = queue.Queue()
    for t in todo:
        q.put(t)

    def worker():
        while _WARM_GEN[0] == gen:
            try:
                u = q.get_nowait()
            except queue.Empty:
                return
            probe_cover(u)

    for _ in range(min(4, len(todo))):
        threading.Thread(target=worker, daemon=True).start()


def _kind_of(kind):
    return kind if kind in KINDS else "author"


def _cover_proxy_url(thumb):
    if not thumb:
        return ""
    return "/api/crawl/probe/cover?u=" + urllib.parse.quote(thumb, safe="")


def probe_search(term, kind="author", pages=0, start=1, site="wnacg"):
    """搜索并返回卡片数据。站点不可达时抛异常（路由转成 502 + 文案）。

    `site` 为 wnacg / jmcomic / nhentai。wnacg 保留多页兜底与两段式加载；
    另外两站每页条数不同（JM 80 / N站 25），一次只取一页，前端用「继续加载」
    按 `nextStart` 增量翻页。`pages=0` 在前两站等价于「只取第 1 页」，不会像
    wnacg 那样一次抓全（N站 616 页全抓会把请求拖死）。
    """
    from crawlers.wnacg_search import search_works
    term = str(term or "").strip()
    if not term:
        return {"ok": False, "message": "词条为空"}
    s = sites.site_of(site)
    start = max(1, int(start or 1))
    pages = int(pages or 0)
    if s != "wnacg":
        d = sites.search(s, term, start, kind)
        works = [{"aid": r["aid"], "title": r["title"], "pages": r["pages"],
                  "thumb": r["thumb"], "cover": _cover_proxy_url(r["thumb"]),
                  "token": r.get("token", "")}
                 for r in d["works"]]
        crawl_dup.annotate(works, _kind_of(kind), term)   # 3.7.61/62：只跟本分区比
        _warm_covers([w["thumb"] for w in works])
        return {"ok": True, "term": term, "kind": _kind_of(kind), "site": s,
                "siteLabel": sites.site_label(s), "domain": "",
                "total": d["total"], "works": works, "shown": len(works), "start": start,
                "nextStart": d["nextStart"], "pages": 1, "hasMore": d["hasMore"],
                "autoLoad": False, "hint": SITE_HINTS[s]}
    pages = (min(max(pages, 0), MAX_PAGES) or 0) if start == 1 else min(max(pages, 1), MAX_PAGES)
    domain, results, total = search_works(term, pages=pages, start=start)
    _SITE[0] = domain or _SITE[0]
    works = [{"aid": r["aid"], "title": r["title"], "pages": r["pages"],
              "thumb": r["thumb"], "cover": _cover_proxy_url(r["thumb"])}
             for r in results]
    crawl_dup.annotate(works, _kind_of(kind), term)   # 3.7.61/62：只跟本分区比
    _warm_covers([w["thumb"] for w in works])
    if start > 1:
        has_more = len(works) >= pages * SITE_PAGE      # 抓满一页 → 后面大概还有
    else:
        has_more = (total > len(works)) if total else False
    # nextStart：前端「继续加载」用它做**纯增量**抓取（按已拿到的条数折算页号，
    # 跨页重复的 aid 被去重后可能略偏小 → 顶多多抓一页，不会漏）
    next_start = start + max(0, (len(works) + SITE_PAGE - 1) // SITE_PAGE)
    return {"ok": True, "term": term, "kind": _kind_of(kind), "site": "wnacg",
            "siteLabel": sites.site_label("wnacg"), "domain": domain,
            "total": total, "works": works, "shown": len(works), "start": start,
            "nextStart": max(next_start, start + 1), "pages": pages,
            "hasMore": bool(has_more), "autoLoad": True,
            "hint": KIND_HINTS[_kind_of(kind)]}
