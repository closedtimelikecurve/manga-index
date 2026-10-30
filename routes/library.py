# -*- coding: utf-8 -*-
"""routes/library.py —— library 域路由（3.6.53 Stage6 从 app.py 抽出）。

规矩：
  * **不在本模块 import app**（`python app.py` 会造成二次导入 / 双 Flask 实例）；
    一律 `h().xxx` 按名解析，保证 monkeypatch 仍然生效。
  * 端点函数保持模块级；ROUTES 与 register() 放在文件末尾。
"""
import json
import os
import re
import subprocess
import sys
import time
import unicodedata

from flask import g, jsonify, request, send_file, send_from_directory

import common
import djc_parse as _dp
import meta_store as meta

from common import APP_DIR, ensure_dir
from panel.http import mutating
from routes.host import h


def index():
    """页面壳：**显式声明不缓存**（3.6.22）。

    壳是静态文件，浏览器按启发式规则可能一直用本地副本 → 它引用的 `/static/js/*.js?v=x`
    也就永不更新，"磁盘代码已修好、页面还是旧行为"。壳不缓存、静态资源带版本串，
    两条一起才真正堵住这类"缓存掩盖真相"（2026-10-15 的「无限加载中」被缓存掩盖了两天）。"""
    resp = send_from_directory(h().app.static_folder, "index.html")
    resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


def api_config():
    return jsonify(h().config_payload())


def api_library():
    # 首次扫描进行中 → 立即返回进度（HTTP 200），前端轮询显示"x/y"，不再同步阻塞 10~60s。
    # 注意仅在"文库尚无数据且正被后台扫描"时走此快速路径；force 手动重扫保持原阻塞语义。
    if h().state.lib["data"] is None and h().state.scan_state["running"]:
        return jsonify({"ok": True, "status": "scanning",
                        "done": h().state.scan_state["done"], "total": h().state.scan_state["total"]})
    lib = h().get_library(force=request.args.get("refresh") == "1")
    mode = request.args.get("sort", "updated")
    if mode not in h().GROUP_SORTS:
        mode = "updated"
    order = "asc" if request.args.get("order", "desc").lower() == "asc" else "desc"
    groups = h().sort_groups(lib["groups"], mode, order)
    return jsonify({
        "ok": True,
        "groups": [h().public_group(g) for g in groups],
        "sort": mode, "order": order,
        "tags": h().tags_index(lib["groups"]),
        "recommendations": h().daily_recommendations(lib["groups"]),
        "scan_ms": lib["scan_ms"],
        "scanned_at": lib["scanned_at"],
        "rev": int(h().state.lib.get("rev") or 0),
    })


def api_library_meta():
    """极轻量探针：安卓端轮询它来判断"面板侧是否改过文库"——rev 一变就自动刷新
    首页/社团页，不必等用户手动下拉。不触发扫描、不返回社团数据，可高频调用。"""
    with h().LIB_LOCK:
        scanning = bool(h().state.scan_state["running"])
    return jsonify({"ok": True, "rev": int(h().state.lib.get("rev") or 0),
                    "scanned_at": (h().state.lib.get("data") or {}).get("scanned_at", 0),
                    "scanning": scanning,
                    "needsRestart": h()._panel_needs_restart(),
                    # 3.1 收件箱待确认数（仅查库不触发同步；纯新增字段，旧端忽略）
                    "inboxPending": sum(1 for it in meta.inbox_list() if it["state"] == "pending")})


def api_circle(name):
    # ?refresh=1 → 后台静默重扫（single-flight），立即用缓存返回当前数据，不再阻塞全量重扫。
    # 2026-10-15 需求6：此前 refresh 调 get_library(force=True) 会同步阻塞 10~60s，
    # 导致移动端「除首页外界面」下拉刷新极慢；改为 _kick_rescan() 后台跑，响应秒回，
    # 重扫完成后由 /api/library/meta 的 rev 变化驱动端上自动刷新拿到新数据。
    if request.args.get("refresh") in ("1", "true"):
        h()._kick_rescan()
    # 注：3.6.3 起「未分类/收件箱」都不再是社团（无归属作品统一收进 _app/_inbox 待整理），
    # 这里不再做任何别名重定向——那个名字找不到就是找不到。
    g = h().find_group(name)
    if not g:
        return jsonify({"ok": False, "message": "社团不存在：" + name}), 404
    return jsonify({
        "ok": True,
        "group": h().public_group(g),
        "works": [h().public_work(w) for w in g["works"]],
        # 双向交叉引用：社团 → 作者聚合（按作品数排），网页社团页头部作者链用
        "authors": h()._circle_authors(g),
    })


def api_works():
    """全局作品检索：?type=original&tag=原神 等（跨所有社团）。
    personal 类型按作者多值匹配（personals 归一后包含 tag）——
    合作作品搜任一位作者都能命中，同一作者跨社团/多笔名聚合浏览；
    响应带 authorCircles（该作者作品分布的社团+计数，双向交叉引用）。"""
    tag = request.args.get("tag", "")
    ttype = request.args.get("type", "")
    tag_canon = h()._canon_author(tag) if ttype == "personal" else tag
    out = []
    author_circles = {}
    # 同一作品的去重（3.6.31）：3.7.4 起合作作品（[A、B] 拆出 circles≥2）会被
    # **同时挂进 A 与 B 两个社团**做交叉引用，于是按"遍历所有社团"累加时，
    # 同一部作品会被计两次 → 原作分区/标签页里出现两张一模一样的作品卡。
    # 按作品的**物理路径**去重（同一文件的两个视图是同一部作品）；若同一路径
    # 出现多次，group 优先取作品的主社团（circle），保证打开时用最合理的归属。
    _seen_path = {}
    for g in h().get_library()["groups"]:
        for w in g["works"]:
            hit = False
            if ttype == "personal":
                hit = tag_canon in h()._work_authors(w) or \
                      h()._canon_circle(w.get("bare") or "") == tag_canon
            else:
                hit = any(t == ttype and n == tag for t, n in w["tags"])
            if not hit:
                continue
            key = os.path.abspath(str(w.get("path") or "")) or (g["name"] + "\0" + w["name"])
            prev = _seen_path.get(key)
            if prev is not None:
                # 第二次出现 = 合作社团的交叉引用；主社团那条优先替换进来，
                # 卡片数与 authorCircles 计数都只算一次（避免两者对不上）。
                if g["name"] == w.get("circle"):
                    out[prev] = {"group": g["name"], "work": h().public_work(w)}
                continue
            _seen_path[key] = len(out)
            out.append({"group": g["name"], "work": h().public_work(w)})
            author_circles[g["name"]] = author_circles.get(g["name"], 0) + 1
    circles = [{"name": n, "count": c} for n, c in
               sorted(author_circles.items(), key=lambda kv: (-kv[1], kv[0]))]
    return jsonify({"ok": True, "works": out, "authorCircles": circles})


def api_parse_info():
    """读取作品当前文件名解析结果，供“增补信息”表单预填。"""
    gname = request.args.get("group", h().INBOX_GROUP)
    wname = request.args.get("work", "")
    w = h().find_work(gname, wname)
    if not w:
        return jsonify({"ok": False, "message": "作品不存在"}), 404
    base, _ext = h()._split_work_name(w)
    a = h().analyze_filename(base)
    return jsonify({
        "ok": True,
        "file": os.path.basename(w["path"]),
        "base": base,              # 不含扩展名：「整标题」模式用它预填输入框
        "event": a["events"][0] if a["events"] else "",
        "circle": a["circle"] or "",
        # 待定词条不再预填个人名（易与汉化组混淆）—— 改填「其他信息」一栏；
        # personal 多作者以 & 连写，各段过笔名别名归一（APP 复制作者/增补预填一致）
        "personal": (" & ".join(h()._canon_author(x) for x in _dp.split_authors(a["personal"]))
                     if a["personal"] else ""),
        "bare": a["bare"] or "",
        # 3.6.11 汉化组独立成栏（【…】词条），位置在「其他信息」之前
        "translator": " ".join(a["groups"] or []),
        "other_info": h()._other_info_of(a),
        "title": a["title"],
        "original": a["originals"][0] if a["originals"] else "",
        "uncensored": a["uncensored"],
        "groups": a["groups"],
        "cn_lang": a["cn_lang"],
        "other_brackets": a["other_brackets"],
        "other_parens": a["other_parens"],
    })


def api_supplement_info():
    """增补信息 → 按规范格式生成文件名并建档。
    body: {group, work, fields: {event, circle, personal, title, original}}
    """
    body = request.get_json(silent=True) or {}
    gname = str(body.get("group", h().INBOX_GROUP))
    wname = str(body.get("work", ""))
    fields = body.get("fields") or {}
    w = h().find_work(gname, wname)
    if not w:
        return jsonify({"ok": False, "message": "作品不存在"}), 404
    base, ext = h()._split_work_name(w)
    a = h().analyze_filename(base)

    # 命名规则本体已下沉到 panel/naming.py（3.6.45 Stage4）：端点只负责 HTTP 与落盘。
    # 那块逻辑是「用户可见的命名契约」（README「文件名规范格式」），原先 70 余行顺序代码
    # 与请求解析/改名/快照搅在一起、圈复杂度 90；现在纯函数化后可脱离 Flask 单测。
    new_name = h()._naming.canonical_from_fields(fields, a, h()._canon_author)
    if not new_name:
        return jsonify({"ok": False, "message": "无法生成文件名，请至少填写“名称”"}), 400
    ok, msg = h()._apply_rename(w, new_name + ext)
    if ok:
        h()._lib_touch()      # 归档改变磁盘结构，失效缓存让首页/社团页立即反映新归档
    return jsonify({"ok": ok, "message": msg, "newName": new_name})


def api_supplement_title():
    """「整标题」模式：只输完整标题（可粘贴与原文件名完全不同的一整串），
    程序自动判定各部分词条（社团/个人/汉化组/展会/原作/待定词条）→ 规范化命名
    → **按解析出的社团归档**（与导入同一套规则，待定词条会走词条库反查补全社团）。
    未识别出社团时**只规范化文件名、不移动**：作品留在原目录（原本在收件箱的仍在收件箱），
    返回文案会明确写出它到底留在哪儿（3.6.174 修：从前一律说"保留在收件箱"，而实现从不移动）。"""
    body = request.get_json(silent=True) or {}
    gname = str(body.get("group", h().INBOX_GROUP))
    wname = str(body.get("work", ""))
    w = h().find_work(gname, wname)
    if not w:
        return jsonify({"ok": False, "message": "作品不存在"}), 404
    base, ext = h()._split_work_name(w)
    raw = str(body.get("title", "")).strip() or base
    if ext and raw.lower().endswith(ext.lower()):        # 允许直接粘贴带扩展名的完整文件名
        raw = raw[: -len(ext)]
    raw = _dp.clean_spaces(raw)
    if not raw:
        return jsonify({"ok": False, "message": "请输入完整标题"}), 400
    # 注意：整串标题**不做** strip_wrappers（否则 "[社团 (个人)] 标题" 这类会被剥壳丢词条）
    norm_base = h().normalize_filename(raw, "")
    if not norm_base:
        return jsonify({"ok": False, "message": "无法从该标题生成规范名，请检查输入"}), 400
    a = h().analyze_filename(norm_base)
    ok, msg = h()._apply_rename(w, norm_base + ext)
    return jsonify({"ok": ok, "message": f"「{norm_base}」— {msg}", "newName": norm_base + ext,
                    "preview": norm_base, "circle": a["circle"] or a["bare"] or "",
                    "personal": a["personal"] or "", "title": a["title"]})


def api_search():
    """全文检索：社团 / 作品 / 画师（全半角宽松 + **忽略空白**，NFKC 后再比）。"""
    q = str(request.args.get("q", "")).strip()
    if not q:
        return jsonify({"ok": True, "q": q, "groups": [], "works": [], "authors": [],
                        "dropped": []})
    lib = h().get_library()
    # 3.6.109：词也做"平铺"（NFKC + 小写 + 去全部空白/零宽字符），与 haystack 同口径。
    # 空串必须滤掉——`"" in hay` 恒为真，留着就等于匹配一切。
    terms = [t for t in (_flat_norm(x) for x in q.split()) if t]
    if not terms:
        return jsonify({"ok": True, "q": q, "groups": [], "works": [], "authors": [],
                        "dropped": []})
    groups = _search_groups(lib["groups"], terms)
    works, dropped = _search_works(lib["groups"], terms)
    # 3.7.4：搜索也返回画师（原先只有社团 + 作品，搜人名时只能从作品里挑）
    authors = h().search_authors(lib["groups"], terms)[:30]
    return jsonify({"ok": True, "q": q, "groups": groups[:50], "works": works,
                    "authors": authors,
                    # 3.6.108：宽松档丢掉了哪些"库里一次都没出现"的词（空 = 严格命中）
                    "dropped": dropped})


def _nf_lower(s):
    """全半角宽松归一（3.6.38 #38）：NFKC + 小写，两端口径一致。"""
    return unicodedata.normalize("NFKC", str(s or "")).lower()


# 空白 + 零宽字符：搜索时一律抹掉再比（CJK 标题里空格位置纯属排版，用户不会照抄）
_WS_RE = re.compile(r"[\s\u200b\u200c\u200d\u2060\ufeff]+")


def _flat_norm(s):
    """NFKC + 小写 + **去掉所有空白**。

    3.6.109 用户报障：`[ずり屋(おやずり)]育ち盛りにギャルの母娘丼` 搜不到，删掉
    `[ずり屋(おやずり)]` 就正常。库里这条的实际名字是
    `[ずり屋 (おやずり)] 育ち盛りにギャルの母娘丼 …`——**社团名、画师、标题之间各有一个空格**。
    用户输入没有空格、整串当一个词（`q.split()` 按空白切，没空格就只有一个词），
    于是要求整串连续出现 → 差一个空格就 0 条。站点文件名本来就常不带空格，所以
    "从文件名复制"必然踩雷。现在两边都抹掉空白再比，"有空格/没空格"不再影响结果。
    """
    return _WS_RE.sub("", _nf_lower(s))


def _search_groups(groups, terms):
    """社团名命中（所有词都要出现；同样忽略空白）。"""
    out = []
    for g in groups:
        name = _flat_norm(g["name"])
        if all(t in name for t in terms):
            out.append(h().public_group(g))
    return out


def _search_works(groups, terms, limit=200):
    """作品命中（名/作者/裸词条/社团/标签一起当 haystack），返回 `(works, dropped)`。

    与标签检索同款去重（3.6.31）：合作社团交叉引用会让同一作品出现在多个社团，
    按物理路径去重、group 优先取主社团（详见 api_works 处注释）。

    **3.6.108 宽松档**（用户报障："整条作品名粘进搜索栏搜不到，裸标题却可以"）：
    多词是 AND，只要有一个词库里一次都没出现就是 0 条 —— 而整条作品名里常带着
    `.zip`、`[DL版]` 这类库里没有的尾巴，或者社团/画师复合词条在入库时已被
    规范化挪走。严格档 0 条时，把这些"全库都没有"的词丢掉再试一次（`.zip` 这种
    后缀先剥掉、保留前面那半），并把丢掉的词回报给前端说明。
    """
    works = _scan_works(groups, terms, limit)
    if works or len(terms) < 2:
        return works, []
    keep, dropped = _relax_terms(groups, terms)
    if not dropped or not keep:
        return [], []
    return _scan_works(groups, keep, limit), dropped


def _work_hay(gname_nf, w):
    """单部作品的检索 haystack：名 / 作者 / 裸词条 / 社团 / 标签拼一起，NFKC + 小写 + 去空白。

    3.6.109：末尾必须走 `_flat_norm`——用户从站点文件名粘来的串通常**没有空格**，
    而库里的名字在社团/画师/标题之间是有空格的（见 `_flat_norm` 注释）。
    """
    hay = " ".join([w["name"], w["personal"] or "", w.get("bare") or "", gname_nf,
                    " ".join(h()._work_authors(w)),
                    " ".join(n for _t, n in w["tags"])])
    return _flat_norm(hay)


def _scan_works(groups, terms, limit):
    """严格 AND 扫描 + 按物理路径去重。"""
    works, seen_path = [], {}
    for g in groups:
        gname_nf = _nf_lower(g["name"])
        for w in g["works"]:
            if not all(t in _work_hay(gname_nf, w) for t in terms):
                continue
            key = os.path.abspath(str(w.get("path") or "")) or (g["name"] + "\0" + w["name"])
            prev = seen_path.get(key)
            if prev is not None:
                if g["name"] == w.get("circle"):
                    works[prev] = {"group": g["name"], "work": h().public_work(w)}
                continue
            seen_path[key] = len(works)
            works.append({"group": g["name"], "work": h().public_work(w)})
            if len(works) >= limit:
                return works
    return works


_ARCHIVE_TAIL = (".zip", ".cbz", ".rar", ".cbr", ".7z")


def _relax_terms(groups, terms):
    """把"全库一个作品都不含"的词判为噪声。返回 `(保留的词, 丢掉的词)`。

    一次遍历就能给出所有词的答案（不必每个词各扫一遍库）。
    带压缩包后缀的词（`xxx.zip`、`[DL版].zip`）先剥后缀再留前半段。
    """
    missing = set(terms)
    for g in groups:
        if not missing:
            break
        gname_nf = _nf_lower(g["name"])
        for w in g["works"]:
            hay = _work_hay(gname_nf, w)
            for t in [t for t in missing if t in hay]:
                missing.discard(t)
            if not missing:
                break
    keep, dropped = [], []
    for t in terms:
        if t not in missing:
            keep.append(t)
            continue
        dropped.append(t)
        stem = t
        for suf in _ARCHIVE_TAIL:
            if stem.endswith(suf):
                stem = stem[:-len(suf)].rstrip(" ._-")
                break
        if stem and stem != t:
            keep.append(stem)
    return keep, dropped

ROUTES = [
    ('get', '/', index, False),
    ('get', '/api/config', api_config, False),
    ('get', '/api/library', api_library, False),
    ('get', '/api/library/meta', api_library_meta, False),
    ('get', '/api/circle/<path:name>', api_circle, False),
    ('get', '/api/works', api_works, False),
    ('get', '/api/parse-info', api_parse_info, False),
    ('post', '/api/supplement-info', api_supplement_info, True),
    ('post', '/api/supplement-title', api_supplement_title, True),
    ('get', '/api/search', api_search, False),
]


def register(app):
    for method, rule, fn, is_mut in ROUTES:
        if is_mut:
            fn = mutating(fn)
        getattr(app, method)(rule)(fn)
