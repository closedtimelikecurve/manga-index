# -*- coding: utf-8 -*-
"""routes/meta.py —— meta 域路由（3.6.53 Stage6 从 app.py 抽出）。

规矩：
  * **不在本模块 import app**（`python app.py` 会造成二次导入 / 双 Flask 实例）；
    一律 `h().xxx` 按名解析，保证 monkeypatch 仍然生效。
  * 端点函数保持模块级；ROUTES 与 register() 放在文件末尾。
"""
import json
import os
import subprocess
import sys
import time

from flask import g, jsonify, request, send_file, send_from_directory

import common
import djc_parse as _dp
import meta_store as meta

from common import APP_DIR, ensure_dir
from panel.http import mutating
from routes.host import h


def api_meta_work():
    """作品全部元数据（扫描派生字段 + 评分/收藏/阅读状态/收藏集）。"""
    key = str(request.args.get("key", "")).strip()
    if not key:
        return jsonify({"ok": False, "message": "缺少 key"}), 400
    data = meta.work_meta(key)
    if data is None:
        w = h()._find_work_by_key(key)
        if not w:
            return jsonify({"ok": False, "message": "作品不存在"}), 404
        # 元数据库尚未同步（刚改名/落位未重扫）：用扫描结果 + 默认附加事实兜底
        data = {"key": key, "group": key.partition("/")[0], "work": w["name"],
                "path": w.get("path"), "size": None, "mtime": w.get("mtime"),
                "pages": w.get("pages"), "kind": w.get("kind"),
                "circle": w.get("circle"), "bare": w.get("bare"),
                "added_at": 0, "authors": h()._work_authors(w),
                "tags": [{"type": t, "name": n} for t, n in w["tags"]],
                "rating": {"score": 0, "favorite": False},
                "reading": {"last_page": 0, "finished": False, "last_read_at": 0},
                "collections": []}
    return jsonify({"ok": True, **data})


def api_meta_rating():
    """评分/收藏：{key, score?, favorite?}（score 整数，favorite 布尔；字段可选）。"""
    body = request.get_json(silent=True) or {}
    key = str(body.get("key", "")).strip()
    if not key:
        return jsonify({"ok": False, "message": "缺少 key"}), 400
    score = body.get("score")
    favorite = body.get("favorite")
    if score is not None:
        try:
            score = max(0, min(10, int(score)))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "message": "score 须为整数"}), 400
    if favorite is not None:
        favorite = bool(favorite)
    try:
        rating = meta.set_rating(key, score, favorite)
    except Exception as e:
        return jsonify({"ok": False, "message": "写入失败：" + str(e)}), 500
    return jsonify({"ok": True, "key": key,
                    "rating": {"score": rating["score"], "favorite": bool(rating["favorite"])}})


def api_meta_collections_list():
    return jsonify({"ok": True, "collections": meta.collections_list()})


def api_meta_collections_post():
    """收藏集 CRUD：action ∈ create/rename/delete/add/remove。
    create{name} → {id}; rename{id,name}; delete{id}; add{id,key}; remove{id,key}。

    3.6.70 结构：create 走 `_collection_create`，其余动作走 `_collection_by_id`。
    """
    body = request.get_json(silent=True) or {}
    action = str(body.get("action") or ("create" if body.get("name") else "")).strip()
    if not action:
        return jsonify({"ok": False, "message": "缺少 action"}), 400
    try:
        meta.snapshot("收藏变更前", force=True)   # 备份时间机器：用户数据变更前必快照
        if action == "create":
            return _collection_create(body)
        cid = _collection_id(body)
        if cid is None:
            return jsonify({"ok": False, "message": "缺少收藏集 id"}), 400
        return _collection_by_id(action, cid, body)
    except Exception as e:
        return jsonify({"ok": False, "message": "操作失败：" + str(e)}), 500


def _collection_create(body):
    """新建收藏集；同名已存在 → 400（meta 层抛异常表示重名）。"""
    name = str(body.get("name", "")).strip()
    if not name:
        return jsonify({"ok": False, "message": "收藏集名称不能为空"}), 400
    try:
        cid = meta.collection_create(name)
    except Exception:
        return jsonify({"ok": False, "message": f"收藏集「{name}」已存在"}), 400
    return jsonify({"ok": True, "id": cid, "message": f"已创建收藏集「{name}」"})


def _collection_id(body):
    """收藏集 id（整数）；缺失或非法返回 None。"""
    try:
        return int(body.get("id"))
    except (TypeError, ValueError):
        return None


def _collection_by_id(action, cid, body):
    """rename / delete / add / remove 四个动作（都要 id）。"""
    if action == "rename":
        return _collection_rename(cid, body)
    if action == "delete":
        if not meta.collection_delete(cid):
            return jsonify({"ok": False, "message": "收藏集不存在"}), 404
        return jsonify({"ok": True, "message": "已删除收藏集"})
    if action in ("add", "remove"):
        return _collection_membership(action, cid, body)
    return jsonify({"ok": False, "message": "未知 action：" + action}), 400


def _collection_rename(cid, body):
    """改名；空名 400，不存在 404。"""
    name = str(body.get("name", "")).strip()
    if not name:
        return jsonify({"ok": False, "message": "收藏集名称不能为空"}), 400
    if not meta.collection_rename(cid, name):
        return jsonify({"ok": False, "message": "收藏集不存在"}), 404
    return jsonify({"ok": True, "message": f"已改名为「{name}」"})


def _collection_membership(action, cid, body):
    """加入/移出收藏集（按作品 key）。"""
    key = str(body.get("key", "")).strip()
    if not key:
        return jsonify({"ok": False, "message": "缺少作品 key"}), 400
    if action == "add":
        meta.collection_add(cid, key)
        return jsonify({"ok": True, "message": "已加入收藏集"})
    if not meta.collection_remove(cid, key):
        return jsonify({"ok": False, "message": "该作品不在此收藏集中"}), 404
    return jsonify({"ok": True, "message": "已移出收藏集"})


def api_meta_collection_get():
    """收藏集内容（封面墙数据；来源已失效的条目 missing=true）。"""
    try:
        cid = int(request.args.get("id", ""))
    except ValueError:
        return jsonify({"ok": False, "message": "缺少 id"}), 400
    data = meta.collection_get(cid)
    if not data:
        return jsonify({"ok": False, "message": "收藏集不存在"}), 404
    return jsonify({"ok": True, **data})


def api_search2():
    """FTS5 检索（标题/画师/标签/社团；trigram 子串 + LIKE 兜底），与旧 /api/search 并存。
    词项先过笔名别名归一——按别名搜画师也能命中正名下的作品。"""
    q = str(request.args.get("q", "")).strip()
    try:
        limit = max(1, min(500, int(request.args.get("limit", "200"))))
    except ValueError:
        limit = 200
    if q:
        q = " ".join((h()._canon_author(t) or t) for t in q.split())
    try:
        works = meta.search2(q, limit)
    except Exception as e:
        return jsonify({"ok": False, "message": "检索失败：" + str(e)}), 500
    return jsonify({"ok": True, "q": q, "works": works})


def api_reading_state_get():
    key = str(request.args.get("key", "")).strip()
    if not key:
        return jsonify({"ok": False, "message": "缺少 key"}), 400
    return jsonify({"ok": True, **meta.reading_get(key)})


def api_reading_state_post():
    """上报阅读进度：{key, last_page, finished?}（APP 翻页/网页阅读时调用）。"""
    body = request.get_json(silent=True) or {}
    key = str(body.get("key", "")).strip()
    if not key:
        return jsonify({"ok": False, "message": "缺少 key"}), 400
    try:
        last_page = max(0, int(body.get("last_page") or 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "last_page 须为整数"}), 400
    finished = body.get("finished")
    finished = bool(finished) if finished is not None else None
    try:
        st = meta.reading_set(key, last_page, finished)
    except Exception as e:
        return jsonify({"ok": False, "message": "写入失败：" + str(e)}), 500
    return jsonify({"ok": True, **st})


def api_reading_resume():
    """最近阅读的 N 部（继续阅读列表）。"""
    try:
        limit = max(1, min(100, int(request.args.get("limit", "10"))))
    except ValueError:
        limit = 10
    return jsonify({"ok": True, "items": meta.reading_resume(limit)})


def api_reading_mark_seen():
    """记录「最后访问时间」（新作品标亮基准）；body {key?} 可选盖作品级 seen_at。"""
    body = request.get_json(silent=True) or {}
    key = str(body.get("key") or "").strip() or None
    prev = meta.mark_seen(key)
    return jsonify({"ok": True, "previous": prev})


def api_stats_overview():
    """个人统计：总量/已读/页数/收藏数/入库增长曲线/最常看画师。"""
    return jsonify({"ok": True, **meta.stats_overview()})


def api_reading_summary():
    """阅读状态汇总（网页消费端）：全部已读/在读状态 + 自 since 以来新入库的作品 key。
    since<=0 恒返回空 new_keys（首次访问没有"新"基线，不把全库标亮）。"""
    try:
        since = float(request.args.get("since") or 0)
    except (TypeError, ValueError):
        since = 0.0
    states = {r[0]: {"p": r[1], "f": bool(r[2])} for r in meta.reading_all()}
    return jsonify({"ok": True, "states": states,
                    "new_keys": meta.works_keys_added_since(since)})


def api_artists():
    """全部画师（跨社团去重，按作品数降序）——APP 首页「全部画师」分区数据源。
    附最大作品封面（cover_*）与喜爱状态（followed）。cover_* 已并入区域封面覆盖。"""
    loved = {f["author"] for f in meta.follows_list()}
    artists = meta.artists_all()
    for a in artists:
        a["followed"] = a["name"] in loved
        h()._apply_artist_cover(a, a["name"])
    return jsonify({"ok": True, "artists": artists})


def api_artist(name):
    """画师档案：跨社团全部作品（按入库时间倒序）+ 别名 + 合作社团聚合 + 关注状态。
    已关注的画师访问档案页即盖 last_seen_at（新作品计数清零基准）。"""
    canon = h()._canon_author(str(name).strip())
    rows = meta.works_by_author(canon)
    circles = {}
    works = []
    for key, gname, wname, pages, kind, added_at, mtime, circle, size in rows:
        # 3.6.14：社团聚合改用归一的 circle——目录名≠圈子名时（如目录「富士やま」归入
        # 圈子「TOZAN_BU」）展示圈子名，与社团浏览/圈子页寻址一致；circle 为空
        # （未归类/待定词条）才回退目录名 gname。
        cname = str(circle or "") or gname
        circles[cname] = circles.get(cname, 0) + 1
        works.append({"key": key, "group": gname, "work": wname, "pages": pages,
                      "kind": kind, "added_at": added_at, "mtime": mtime, "circle": circle,
                      # 3.6.151：文件大小（字节）——画师页「按文件大小」排序查重用
                      "size": int(size or 0),
                      # 2026-10-15 需求3：透传该作品全部作者（合作作品多人），
                      # 前端据 d.author 滤掉本画师、仅渲染合作者标签
                      "personals": meta.authors_of(key),
                      # 3.7.51：原作标签随画师作品一起下发，卡片任何区域都能显示
                      "originals": meta.originals_of(key)})
    following = any(f["author"] == canon for f in meta.follows_list())
    if following:
        meta.follow_touch(canon, time.time())
    # 画师封面：派生（名下最大有封面作品）+ 区域封面覆盖
    art = next((a for a in meta.artists_all() if a["name"] == canon), None)
    cover = {"cover_group": art.get("cover_group") if art else None,
             "cover_work": art.get("cover_work") if art else None,
             "cover_mtime": art.get("cover_mtime", 0.0) if art else 0.0,
             "cover_pages": art.get("cover_pages", 0) if art else 0}
    h()._apply_artist_cover(cover, canon)
    return jsonify({
        "ok": True, "author": canon, "queried": name,
        "is_following": following,
        "cover_group": cover["cover_group"], "cover_work": cover["cover_work"],
        "cover_mtime": cover["cover_mtime"], "cover_pages": cover["cover_pages"],
        "aliases": meta.aliases_of(canon),
        "circles": [{"name": n, "count": c} for n, c in
                    sorted(circles.items(), key=lambda kv: (-kv[1], kv[0]))],
        "works": works, "total": len(works),
    })


def api_follows():
    """喜爱清单：每位画师的作品总数 + 自上次查看以来的新作品数（新作品多在前）+ 封面。"""
    cover_by = {a["name"]: a for a in meta.artists_all()}
    out = []
    for f in meta.follows_list():
        total, new_n = meta.works_count_by_author(f["author"], f["last_seen_at"])
        cov = cover_by.get(f["author"]) or {}
        rec = {"author": f["author"], "works": total, "new": new_n,
               "created_at": f["created_at"], "last_seen_at": f["last_seen_at"],
               "cover_group": cov.get("cover_group"),
               "cover_work": cov.get("cover_work"),
               "cover_mtime": cov.get("cover_mtime", 0),
               "cover_pages": cov.get("cover_pages", 0)}
        h()._apply_artist_cover(rec, f["author"])
        out.append(rec)
    out.sort(key=lambda x: (-x["new"], -x["works"], x["author"]))
    return jsonify({"ok": True, "follows": out, "total": len(out)})


def api_follow_add():
    """喜爱画师：{author}（笔名别名归一后入库）。"""
    body = request.get_json(silent=True) or {}
    author = h()._canon_author(str(body.get("author", "")).strip())
    if not author:
        return jsonify({"ok": False, "message": "缺少 author"}), 400
    if meta.follow_add(author):
        return jsonify({"ok": True, "message": f"已喜爱：{author}", "author": author})
    return jsonify({"ok": True, "message": f"已在喜爱列表：{author}", "author": author})


def api_follow_remove():
    """取消喜爱：{author}。"""
    body = request.get_json(silent=True) or {}
    author = h()._canon_author(str(body.get("author", "")).strip())
    if not author:
        return jsonify({"ok": False, "message": "缺少 author"}), 400
    if not meta.follow_remove(author):
        return jsonify({"ok": False, "message": f"未在喜爱列表：{author}"}), 404
    return jsonify({"ok": True, "message": f"已取消喜爱：{author}", "author": author})

ROUTES = [
    ('get', '/api/meta/work', api_meta_work, False),
    ('post', '/api/meta/rating', api_meta_rating, False),
    ('get', '/api/meta/collections', api_meta_collections_list, False),
    ('post', '/api/meta/collections', api_meta_collections_post, False),
    ('get', '/api/meta/collection', api_meta_collection_get, False),
    ('get', '/api/search2', api_search2, False),
    ('get', '/api/reading/state', api_reading_state_get, False),
    ('post', '/api/reading/state', api_reading_state_post, False),
    ('get', '/api/reading/resume', api_reading_resume, False),
    ('post', '/api/reading/mark-seen', api_reading_mark_seen, False),
    ('get', '/api/stats/overview', api_stats_overview, False),
    ('get', '/api/reading/summary', api_reading_summary, False),
    ('get', '/api/artists', api_artists, False),
    ('get', '/api/artist/<path:name>', api_artist, False),
    ('get', '/api/follows', api_follows, False),
    ('post', '/api/follow', api_follow_add, False),
    ('post', '/api/follow/unfollow', api_follow_remove, False),
]


def register(app):
    for method, rule, fn, is_mut in ROUTES:
        if is_mut:
            fn = mutating(fn)
        getattr(app, method)(rule)(fn)
