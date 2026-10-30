# -*- coding: utf-8 -*-
"""services/queries.py —— 库内查询与对外序列化（3.6.60 Stage7 拆出）。

按名/按 owner_key 查作品与社团、`public_*`（内部结构 → 前端字段）、标签索引、
画师检索与每日推荐。**只读**：不扫盘、不写缓存（缓存写入在 index_cache）。
"""
import os
import random

from common import ensure_dir
from panel.host import h

def find_group(name):
    for g in h().get_library()["groups"]:
        if g["name"] == name:
            return g
    return None

def _work_by_owner_key(gname, wname):
    data = h().get_library() or {}
    src = data.get("groups") or []
    if h().state.owner_index["src"] is not src:
        m = {}
        for g in src:
            for w in g.get("works") or []:
                owner = str(w.get("_group") or "")
                if owner:
                    m[owner + "/" + str(w.get("name") or "")] = w
        h().state.owner_index["src"] = src
        h().state.owner_index["map"] = m
    return h().state.owner_index["map"].get(str(gname or "") + "/" + str(wname or ""))

def find_work(gname, wname):
    if gname == h().INBOX_GROUP:
        # 「收件箱」不是一个文库社团，而是**待入库伪社团**：名字就是收件项 id，
        # 供阅读器「先读后入库」与「增补信息」补全词条用（文件实体在 _app/_inbox 里）。
        return h()._inbox_pseudo_work(wname)
    g = h().find_group(gname)
    if g:
        for w in g["works"]:
            if w["name"] == wname:
                return w
    # 3.6.13 兜底：按作品 key 的 owner（真实目录）反查——修复画师页/续读/收藏打开
    # 「目录名≠圈子名」的作品（如富士やま 目录归入 TOZAN_BU）时 404 的问题。
    return h()._work_by_owner_key(gname, wname)

def _work_key(gname, wname):
    """作品元数据 key（3.0 约定）："社团/作品名"。"""
    return str(gname or "") + "/" + str(wname or "")

def _group_physical_dir(gname):
    """圈子对应的真实磁盘目录（3.6.12：分组改按圈子名后，目录名不一定等于圈子名）。

    真实档案目录（目录名 == 圈子名）直接返回；虚拟圈子（由「circle (画师)」式目录、
    画师名目录、根目录散包归组而来，磁盘上没有以圈子名命名的目录）回退到其作品的共同父目录
    ——这样「整目录删除 / 改名 / 合并清除源目录」对虚拟圈子同样有效，不会因目录名≠圈子名而失效。"""
    root = os.path.abspath(h().CFG.get("root", ""))
    d = os.path.join(root, gname)
    if os.path.isdir(d) and h()._path_in_root(d):
        return d
    g = h().find_group(gname)
    if g:
        dirs = {os.path.dirname(os.path.abspath(w["path"])) for w in g["works"]}
        if len(dirs) == 1:
            d = dirs.pop()
            # 共同父目录若是文库根本身（根目录散包），不算「有目录」——否则解散会误删文库根
            if d != root and h()._path_in_root(d):
                return d
    return None

def _work_ver(w):
    """作品内容版本号（封面/页面 URL 的缓存键）：文件毫秒级 mtime + 页数。
    内容一变（改名/删首页图片/换图/重扫出新页数）键就变 ——
    网页 <img> 与安卓 Coil（内存 + 磁盘缓存均按 URL 索引）靠它丢掉旧图。"""
    if not w:
        return ""
    return "%d-%d" % (int(round(float(w.get("mtime") or 0) * 1000)), int(w.get("pages") or 0))

def public_work(w):
    return {
        "name": w["name"], "kind": w["kind"], "pages": w["pages"],
        "hasCover": bool(w.get("cover")), "personal": w["personal"],
        "personals": (w.get("personals") or
                      ([w["personal"]] if w.get("personal") else [])),
        "circle": w["circle"], "bare": w.get("bare", ""), "mtime": w["mtime"],
        # 3.6.151：文件大小（字节）——「按文件大小排序」查重用（同作品重复下载时体积接近）
        "size": int(w.get("size") or 0),
        # 3.6.111：首次入库时间（扫描后由 _stamp_added_at 盖入）——分区内排序键，修改不推进
        "added_at": int(w.get("added_at") or 0),
        # 合作社团：[A、B] 作品 → ["A","B"]；前端据此提示"合作作品"（单社团时为空数组）
        "circles": list(w.get("circles") or []),
        "ver": h()._work_ver(w),
        "file": os.path.basename(w["path"]),
        "tags": [{"type": t, "name": n} for t, n in w["tags"]],
    }

def public_group(g):
    name = g["name"]
    cover_group = g.get("cover_group") or name
    cover_work = g.get("cover_work")
    # 重新应用区域封面覆盖：set-cover 后立即可见，无需等后台重扫（无覆盖时只是一次廉价字典查找）
    ov = h()._resolve_region_cover("circle", name)
    if ov:
        # 3.6.166：覆盖坐标**可能悬空**（手设封面那部作品后来被删/改名/移出文库）。
        # 找不到就保持 g 里已有的派生封面——旧代码无条件覆盖，会把 cover_work 置空、
        # 卡片直接变成占位图标，看起来像整个社团的作品都没了。
        owk = h().find_work(ov["group"], ov["work"])
        if owk:
            cover_work, cover_group = owk, ov["group"]
    return {
        "name": name, "workCount": len(g["works"]),
        "hasCover": bool(cover_work),
        "coverWork": cover_work["name"] if cover_work else "",
        "coverGroup": cover_group,
        "coverMtime": g["cover_mtime"], "latestWork": g["latest_work"],
        # 封面图 URL 的缓存键：跟"封面那部作品"的内容版本走（不是最新作品的时间）
        "coverVer": h()._work_ver(cover_work),
        # 社团排序用（秒，与 coverMtime 同单位）：档案创建时间 / 最近入库新作品的时间
        "createdAt": g.get("created_at", 0.0),
        "updatedAt": g.get("updated_at", g.get("cover_mtime", 0.0)),
        # 3.6.151：社团占用空间（字节）——社团列表「按文件大小」排序用
        "totalBytes": int(g.get("total_bytes") or 0),
    }

def tags_index(groups):
    """所有标签及出现次数：{类型: [{name, count}, ...]}
    personal 桶按作者多值计数（合作作品每位作者各 +1）并过笔名别名归一——
    同一作者的多个笔名/合作作品在标签云里聚合到正名下。"""
    tags = {"original": {}, "event": {}, "personal": {}, "other": {}}
    for g in groups:
        for w in g["works"]:
            for t, n in w["tags"]:
                if t == "personal":
                    n = h()._canon_author(n)
                    if not n:
                        continue
                tags.setdefault(t, {}).setdefault(n, 0)
                tags[t][n] += 1
    return {k: sorted(({"name": n, "count": c} for n, c in v.items()),
                      key=lambda x: (-x["count"], x["name"]))
            for k, v in tags.items()}

def _work_authors(w):
    """作品的作者列表（归一）：personals 多值优先，旧数据回退 personal 单值。"""
    authors = [h()._canon_author(a) for a in (w.get("personals") or
                                          ([w["personal"]] if w.get("personal") else []))]
    return [a for a in authors if a]

def search_authors(groups, terms):
    """按关键词筛画师：命中即返回 {name, count, cover_group, cover_work, cover_mtime, cover_pages}
    （跨社团作品数，按作品数降序）。

    匹配画师名、作品里的待定词条所属作者，以及该画师参与作品的社团名
    —— 这样搜社团名也能顺带看到其主力画师。
    cover_* 取该画师名下「有封面页」的一部作品，供前端渲染画师封面卡片。"""
    tally = {}
    for g in groups:
        for w in g["works"]:
            for a in h()._work_authors(w):
                hay = " ".join([a, w["name"], g["name"],
                                " ".join(n for _t, n in w["tags"])]).lower()
                if all(t in hay for t in terms):
                    rec = tally.get(a)
                    if rec is None:
                        rec = {"paths": set(), "cover_group": None,
                               "cover_work": None, "cover_mtime": 0.0, "cover_pages": 0}
                        tally[a] = rec
                    rec["paths"].add(w["path"])            # 按作品去重（交叉引用不重复计数）
                    if rec["cover_group"] is None and w.get("cover"):
                        rec["cover_group"] = g["name"]
                        rec["cover_work"] = w["name"]
                        rec["cover_mtime"] = w.get("mtime", 0.0)
                        rec["cover_pages"] = w.get("pages", 0)
    out = []
    for n, d in sorted(tally.items(), key=lambda kv: (-len(kv[1]["paths"]), kv[0])):
        rec = {"name": n, "count": len(d["paths"]),
               "cover_group": d["cover_group"], "cover_work": d["cover_work"],
               "cover_mtime": d["cover_mtime"], "cover_pages": d["cover_pages"]}
        # 画师封面覆盖：用户在画师页把某作品首图设为该画师封面
        h()._apply_artist_cover(rec, n)
        out.append(rec)
    return out

def daily_recommendations(groups):
    """随机推荐：每次刷新（/api/library 请求）随机抓 3 个社团的各一部“代表作”。
    不再按日期固定——刷新页面或重新扫描即换一批。
    返回具体作品名，供前端点击后直接在阅读器中打开。"""
    rng = random.Random()
    cand = [g for g in groups if g["cover_work"]]
    rng.shuffle(cand)
    recs = []
    for g in cand[:3]:
        cover_works = [w for w in g["works"] if w.get("cover")]
        if not cover_works:
            continue
        w = rng.choice(cover_works)
        recs.append({
            "group": g["name"],
            "work": w["name"],
            "personal": w["personal"],
            "pages": w["pages"],
        })
    return recs
