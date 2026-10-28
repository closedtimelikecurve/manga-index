# -*- coding: utf-8 -*-
"""routes/probe.py —— 「分区爬取」多站点搜索/勾选下载路由（3.7.54，10 号域）。

五个动作：选站点 → 搜索 → 看卡片 → 勾选 → 下载并自动归区。
  * `POST /api/crawl/probe`        词条 + site(wnacg/jmcomic/nhentai) → 站点命中
  * `GET  /api/crawl/probe/cover`  封面字节（服务端转码 + 磁盘缓存）
  * `POST /api/crawl/pick`         勾选的 aid 列表 + site → 起后台任务（立即返回）
  * `GET  /api/crawl/pick/status`  任务进度（前端 2s 轮询）
  * `POST /api/crawl/pick/cancel`  请求取消（当前那一部下完即停）

规矩同其它域：**不 import app**，一律 `h().xxx` 按名解析（见 docs/architecture.md §四）。
"""
import urllib.parse

from flask import Response, jsonify, request

from panel import safecover
from routes.host import h


def api_probe_search():
    """词条搜索。kind 只影响文案与入库归属策略，不影响搜索本身。"""
    body = request.get_json(silent=True) or {}
    term = str(body.get("term") or request.args.get("term") or "").strip()
    kind = str(body.get("kind") or request.args.get("kind") or "author")
    site = str(body.get("site") or request.args.get("site") or "wnacg")
    try:
        pages = int(body.get("pages") if body.get("pages") is not None
                    else request.args.get("pages", 0))
        start = int(body.get("start") or request.args.get("start") or 1)
    except (TypeError, ValueError):
        pages, start = 0, 1
    if not term:
        return jsonify({"ok": False, "message": "请输入搜索词"}), 400
    # 3.6.156：发行版可用性前门守卫——公开树没有对应适配时给出准确文案，
    # 而不是让深层惰性 import 报"站点不可达(No module named …)"。
    from services.crawl_probe_sites import site_available, site_label
    if not site_available(site):
        return jsonify({"ok": False,
                        "message": "%s 适配未包含在此发行版中" % site_label(site)}), 400
    try:
        # 页数/起始页由服务层兜（MAX_PAGES=8）：这里只挡非法值，不再把用户锁在 3 页
        return jsonify(h().probe_search(term, kind, max(pages, 0), max(start, 1), site))
    except Exception as e:
        return jsonify({"ok": False,
                        "message": "搜索失败：站点不可达（%s）" % str(e)[:90]}), 502


def api_probe_cover():
    """封面（高压缩）：命中缓存直接回，未命中才出站抓取。白名单在服务层。"""
    safe = safecover.response()             # 3.6.161 内测模式：探针封面同样盖住
    if safe is not None:
        return safe
    if getattr(h(), "SAFE_IMAGES", False):   # 3.6.118 测试模式：占位图
        from flask import send_file as _sf
        return _sf(safecover.PLACEHOLDER_IMG,
                   mimetype="image/png", etag="safe-placeholder", conditional=True)
    url = str(request.args.get("u") or "").strip()
    if not url:
        return jsonify({"ok": False, "message": "缺少 u"}), 400
    data, mime = h().probe_cover(urllib.parse.unquote(url))
    if not data:
        return Response(status=404)
    resp = Response(data, mimetype=mime)
    # 封面内容按 URL 固定（站点缩略图不复用路径），可以长缓存；手机端因此只抓一次
    resp.headers["Cache-Control"] = "public, max-age=604800"
    return resp


def api_pick_start():
    body = request.get_json(silent=True) or {}
    return jsonify(h().pick_start(body.get("term") or "", body.get("kind") or "author",
                                  body.get("picks") or [], body.get("site") or "wnacg"))


def api_pick_status():
    return jsonify({"ok": True, "job": h().pick_status()})


def api_pick_cancel():
    return jsonify(h().pick_cancel())


ROUTES = [
    ('post', '/api/crawl/probe', api_probe_search, False),
    ('get', '/api/crawl/probe/cover', api_probe_cover, False),
    ('post', '/api/crawl/pick', api_pick_start, False),
    ('get', '/api/crawl/pick/status', api_pick_status, False),
    ('post', '/api/crawl/pick/cancel', api_pick_cancel, False),
]


def register(app):
    for method, rule, fn, is_mut in ROUTES:
        if is_mut:
            from panel.http import mutating
            fn = mutating(fn)
        getattr(app, method)(rule)(fn)
