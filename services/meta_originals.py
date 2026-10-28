# -*- coding: utf-8 -*-
"""services/meta_originals.py —— 原作分区的读取与手动维护（3.6.84 从 meta_store 拆出）。

两段职责，同属"原作"这一条支线：
  * 读取：`originals_all` 把 work_tags(type=original) 聚合成前端卡片（作品数/封面/latest）；
  * 维护：搜索命中 → 写标签（`originals_add`）、改名/合并（`work_tags_rename`、
    `originals_merge`）、删分区（`originals_remove`）、清残留（`originals_stale_names`）。

解析器只认"整括号规范化匹配"词条库；用户要的是"含有该词条"的子串语义，
故 originals_search 命中的作品直接写 original 标签（用户附加事实，重扫不删，
见 services/db_sync 内 want_t 合并）；词条同时进 config 词条库，让后续重扫/新作品
由解析器产出同一标签，两边殊途同归。

调用方式不变：`meta.originals_add()` 等由 meta_store 的 PEP 562 `__getattr__`
惰性转发到这里；连接仍由 `meta._connect()` 提供，`monkeypatch.setattr(meta_store,
"DB_PATH", ...)` 依然生效。
"""
import re
import unicodedata

import meta_store as meta

_LOOSE_JUNK_RE = re.compile(r"[\s_\-/]+")


# ---------------------------------------------------------------
# 读取：分区卡片
# ---------------------------------------------------------------
def originals_all():
    """全部原作分区（type=original 标签去重，按作品数降序），附最大作品封面与 latest。"""
    with meta._LOCK:
        c = meta._connect()
        rows, added_rows, first_rows = _original_zone_rows(c)
    counts, biggest = _zone_stats(rows)
    added = {r[0]: (r[1] or 0) for r in added_rows}
    first = {r[0]: (r[1] or 0) for r in first_rows}
    return [_zone_payload(t, counts, added, first, biggest)
            for t in sorted(counts, key=lambda t: (-counts[t], t))]


def _original_zone_rows(c):
    """三条聚合查询：分区作品行、最新入库、首次入库（全文见 3.6.42 的排序说明）。"""
    rows = c.execute(
        "SELECT t.name, w.key, w.size, w.group_name, w.name, w.mtime, w.pages"
        " FROM work_tags t JOIN works w ON w.key = t.key"
        " WHERE t.type = 'original'").fetchall()
    added_rows = c.execute(
        "SELECT t.name, MAX(w.added_at) FROM work_tags t"
        " JOIN works w ON w.key = t.key WHERE t.type = 'original' GROUP BY t.name").fetchall()
    # 3.6.42：分区"首次出现时间" = 该分区最早一部作品的入库时刻。
    # 排序里的「创建次序」用它，而不是 config 词条库位置——解析器产出的分区
    # （東方Project 81 部、五等分の花嫁…）根本不在词条库里，按位置排会集体沉底。
    first_rows = c.execute(
        "SELECT t.name, MIN(w.added_at) FROM work_tags t"
        " JOIN works w ON w.key = t.key WHERE t.type = 'original' GROUP BY t.name").fetchall()
    return rows, added_rows, first_rows


def _zone_stats(rows):
    """每个分区的作品数 + 封面取"体积最大的那部"（体积相同取先出现者）。"""
    counts, biggest = {}, {}
    for tname, _key, size, gname, wname, mtime, pages in rows:
        counts[tname] = counts.get(tname, 0) + 1
        sz = size if (size is not None and size > 0) else -1
        cur = biggest.get(tname)
        if cur is None or sz > cur[0]:
            biggest[tname] = (sz, gname, wname, mtime or 0, pages or 0)
    return counts, biggest


def _zone_payload(tname, counts, added, first, biggest):
    """单个分区的对外结构（前端卡片直接消费）。"""
    b = biggest.get(tname)
    return {"name": tname, "works": counts[tname],
            "latest": added.get(tname, 0),
            "first_added": first.get(tname, 0),
            "cover_group": b[1] if b else None,
            "cover_work": b[2] if b else None,
            "cover_mtime": b[3] if b else 0,
            "cover_pages": b[4] if b else 0}


# ---------------------------------------------------------------
# 手动维护
# ---------------------------------------------------------------
def _loose(s):
    """宽松归一：NFKC（全半角统一，3.6.38 #38）→ 去空白/下划线/连字符/斜杠
    + 小写——原作名变体互认（Fate Grand Order / Fate_Grand_Order /
    Fate/GrandOrder → 同串；ぼっち・ざ・ろっく！/ぼっち・ざ・ろっく! → 同串）。"""
    s = unicodedata.normalize("NFKC", str(s or ""))
    return _LOOSE_JUNK_RE.sub("", s).lower()


def originals_search(term, limit=2000):
    """预览「添加原作」命中：作品名/社团名/既有标签名内大小写不敏感子串匹配，
    再按宽松归一补一轮（容忍 _/空格/斜杠变体）。按入库时间倒序。"""
    term = str(term or "").strip()
    if not term:
        return []
    with meta._LOCK:
        c = meta._connect()
        pat = meta._like_pat(term)
        rows = c.execute(
            "SELECT w.key, w.name, w.group_name, w.size, w.pages, w.mtime, w.added_at"
            " FROM works w"
            " WHERE w.name LIKE ? ESCAPE '\\' OR w.group_name LIKE ? ESCAPE '\\'",
            (pat, pat)).fetchall()
        rows += c.execute(
            "SELECT w.key, w.name, w.group_name, w.size, w.pages, w.mtime, w.added_at"
            " FROM works w JOIN work_tags t ON t.key = w.key"
            " WHERE t.name LIKE ? ESCAPE '\\'", (pat,)).fetchall()
        merged = {}
        for r in rows:
            merged.setdefault(r[0], r)
        lt = _loose(term)
        if lt:
            for r in c.execute(
                    "SELECT key, name, group_name, size, pages, mtime, added_at FROM works"):
                if r[0] in merged:
                    continue
                if lt in _loose(r[1]) or lt in _loose(r[2]):
                    merged[r[0]] = r
    out = [{"key": k, "name": r[1], "group": r[2], "size": r[3],
            "pages": r[4], "mtime": r[5] or 0, "added_at": r[6] or 0}
           for k, r in merged.items()]
    out.sort(key=lambda x: -x["added_at"])
    return out[:limit]


def resolve_work_key(gname, wname):
    """把「展示群组名/作品名」解析成 works 表里的**真实 key**（3.6.41）。

    搜索/分区接口回传的 group 是 LIB 的展示群组名（可能是归一后的圈子名、或
    合作社团的交叉引用组），而 works.key 的 group 段是**归档目录名**——两者不总是
    相等。手动添加作品若直接拼 `group + "/" + name` 落库，会写出一条指向不存在
    作品的悬空标签：接口返回 ok、分区里却永远看不到卡片（用户报障"添加失败"）。
    返回 None 表示库里没有对应作品（调用方应跳过并如实告知，而不是静默写悬空行）。"""
    gname = str(gname or "").strip()
    wname = str(wname or "").strip()
    if not gname or not wname:
        return None
    with meta._LOCK:
        c = meta._connect()
        r = c.execute("SELECT key FROM works WHERE group_name=? AND name=?",
                      (gname, wname)).fetchone()
        if r:
            return r[0]
        r = c.execute("SELECT key FROM works WHERE key=?", (gname + "/" + wname,)).fetchone()
        if r:
            return r[0]
        # 最后兜底：同名作品在库里唯一时采用（合作社团交叉引用的组名对不上，
        # 但作品本身只有一个物理副本）。多个同名则宁可返回 None，让用户看清再选。
        rows = c.execute("SELECT key FROM works WHERE name=?", (wname,)).fetchall()
        return rows[0][0] if len(rows) == 1 else None


def originals_add(term, keys):
    """把词条作为原作标签写进指定作品（3.6.19 添加原作）。幂等，返回新写入行数。"""
    term = str(term or "").strip()
    keys = [str(k) for k in (keys or []) if str(k)]
    if not term or not keys:
        return 0
    with meta._LOCK:
        c = meta._connect()
        before = c.execute("SELECT count(*) FROM work_tags").fetchone()[0]
        for chunk in meta._in_chunks(keys):
            c.executemany("INSERT OR IGNORE INTO work_tags(key, type, name) VALUES(?,?,?)",
                          [(k, "original", term) for k in chunk])
        after = c.execute("SELECT count(*) FROM work_tags").fetchone()[0]
        c.commit()
    return after - before


def originals_remove(term):
    """移除某原作分区的全部标签行（3.6.19）。返回删除行数。"""
    term = str(term or "").strip()
    if not term:
        return 0
    with meta._LOCK:
        c = meta._connect()
        before = c.execute("SELECT count(*) FROM work_tags").fetchone()[0]
        c.execute("DELETE FROM work_tags WHERE type='original' AND name=?", (term,))
        after = c.execute("SELECT count(*) FROM work_tags").fetchone()[0]
        c.commit()
    return before - after


def work_tags_rename(old, new, type_="original"):
    """把某类标签整体改名（3.6.21 原作分区改名/合并）。

    原作名不在文件名里、只活在 DB 标签 + config 词条库（与画师名相反：画师名编码在
    文件名括号里，改 DB 不改文件名会被下一轮扫描解析回来）——所以这里**只搬标签**，
    不碰任何作品文件、不碰 works/reading/follows。

    目标名已有标签时（同作品撞 (key,type,name) 主键）用 UPDATE OR REPLACE 自动去重：
    该作品最终只留目标名一行——即"改名"自然退化成"合并"。返回受影响的标签行数。

    注意：`old` 必须与 DB 里的名字**逐字相等**（分区名 = 规范名，见界面上的 zone 名）。"""
    old = str(old or "").strip()
    new = str(new or "").strip()
    if not old or not new or old == new:
        return 0
    with meta._LOCK:
        c = meta._connect()
        n = c.execute("SELECT count(*) FROM work_tags WHERE type=? AND name=?",
                      (type_, old)).fetchone()[0]
        if n:
            # OR REPLACE：同作品已带新名 → 直接删掉旧行（主键冲突即替换），避免残留双标签
            c.execute("UPDATE OR REPLACE work_tags SET name=? WHERE type=? AND name=?",
                      (new, type_, old))
            c.commit()
    return n


def originals_stale_names(keep):
    """不在 keep 集合内的 original 标签名——词条库删词条后需显式清库
    （manual original 不再被 sync_scan 自动清理，见该函数内注释）。"""
    keep = {str(x) for x in (keep or [])}
    with meta._LOCK:
        c = meta._connect()
        names = [r[0] for r in c.execute(
            "SELECT DISTINCT name FROM work_tags WHERE type='original'")]
    return [n for n in names if n not in keep]


def original_tags_all():
    """全部 (key, name) original 标签对（3.6.38 #36：供 _do_scan 回填 LIB 用）。
    手动「添加作品」写的标签只落 DB，LIB 的 work.tags 只有解析产出——
    不回填的话 /api/works?type=original 永远过滤不到手动添加的作品。"""
    with meta._LOCK:
        c = meta._connect()
        return c.execute(
            "SELECT key, name FROM work_tags WHERE type='original'").fetchall()


def originals_merge(canonical, aliases):
    """把别名分区的作品整体迁入正名分区（3.6.20 #26 别名合并）：
    work_tags 的 original 标签批量改名。同一作品已带正名标签时
    （key,type,name 主键撞键）UPDATE OR REPLACE 删旧行去重，
    该作品最终只保留正名标签一行。返回处理的标签行数。
    注意：仅搬标签，不碰 works/reading/follows——作品位置、进度、收藏不变。"""
    canonical = str(canonical or "").strip()
    aliases = [str(a).strip() for a in (aliases or []) if str(a).strip()]
    aliases = [a for a in aliases if a and a != canonical]
    if not canonical or not aliases:
        return 0
    moved = 0
    with meta._LOCK:
        c = meta._connect()
        for a in aliases:
            cur = c.execute(
                "SELECT count(*) FROM work_tags WHERE type='original' AND name=?",
                (a,)).fetchone()[0]
            if cur <= 0:
                continue
            c.execute(
                "UPDATE OR REPLACE work_tags SET name=? WHERE type='original' AND name=?",
                (canonical, a))
            moved += cur
        c.commit()
    return moved
