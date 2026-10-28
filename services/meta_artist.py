# -*- coding: utf-8 -*-
"""services/meta_artist.py —— 画师/社团的别名、关注清单与 key 迁移（3.6.84 从 meta_store 拆出）。

这一支线覆盖三类互相咬合的事实：
  * **别名**：笔名 / 社团 / 原作三张 alias→canonical 表，带模块级缓存；
  * **关注与档案**：follows 清单、某画师跨社团作品、画师作品计数、封面聚合；
  * **改名/合并/解散**：`works.key` 与各派生表的前缀迁移（2.x 时代改名丢关联，
    DB 化后改表即跟随），改完必须重建 FTS。

调用方式不变：`meta.author_aliases()` / `meta.rename_author()` 等由 meta_store 的
PEP 562 `__getattr__` 惰性转发到这里；连接与缓存本体仍在 meta_store（`meta._connect()`、
`meta._C_ALIASES`…），故 `monkeypatch.setattr(meta_store, "DB_PATH")` 依然生效。
"""
import sqlite3
import time

import meta_store as meta

_KEY_TABLES = ("work_authors", "work_tags", "reading", "ratings", "collection_items")


# ---------------------------------------------------------------
# key 迁移（改名/解散联动）
# ---------------------------------------------------------------
def rename_work_key(old_key, new_key):
    """单部作品 key 迁移（改名/归档落位）。幂等：old 不存在时静默。"""
    if not old_key or not new_key or old_key == new_key:
        return
    with meta._LOCK:
        c = meta._connect()
        grp, _, nm = new_key.partition("/")
        try:
            c.execute("UPDATE works SET key=?, group_name=?, name=? WHERE key=?",
                      (new_key, grp, nm, old_key))
        except sqlite3.IntegrityError:
            pass                                   # 目标 key 已存在：留待下轮扫描对账
        for t in _KEY_TABLES:
            try:
                c.execute("UPDATE OR IGNORE %s SET key=? WHERE key=?" % t, (new_key, old_key))
            except sqlite3.IntegrityError:
                c.execute("DELETE FROM %s WHERE key=?" % t, (old_key,))
        c.execute("DELETE FROM works WHERE key=?", (old_key,))
        c.commit()
        meta._fts_rebuild(c)
        c.commit()


def merge_circles(old, new):
    """社团合并：把 old 名下全部记录迁到 **已存在** 的 new 名下，old 档案本身抹掉。

    与 rename_circle 的区别：new 已存在（合并而非改名），所以不能 UPDATE circles.name
    （主键会撞），而是补目标档案 + 迁移数据 + 删除源档案。
    works 的 key 前缀、group_name、画师→社团映射都跟随；目标侧已有同名 key 的行会让路，
    （UPDATE OR IGNORE），被忽略的重复行随后删掉——不会出现两行同 key 的脏数据。
    """
    if not old or not new or old == new:
        return
    with meta._LOCK:
        c = meta._connect()
        c.execute("INSERT OR IGNORE INTO circles(name) VALUES(?)", (new,))
        _rename_key_prefix(c, "works", old, new)
        c.execute("UPDATE OR IGNORE works SET group_name=? WHERE group_name=?", (new, old))
        c.execute("DELETE FROM works WHERE group_name=?", (old,))
        for t in _KEY_TABLES:
            _rename_key_prefix(c, t, old, new)
            prefix = old + "/"
            c.execute("DELETE FROM %s WHERE substr(key, 1, ?) = ?" % t,
                      (len(prefix), prefix))
        c.execute("UPDATE OR IGNORE artist_circles SET circle=? WHERE circle=?", (new, old))
        c.execute("DELETE FROM artist_circles WHERE circle=?", (old,))
        c.execute("DELETE FROM circles WHERE name=?", (old,))
        c.commit()
        meta._fts_rebuild(c)
        c.commit()
        meta._invalidate()


def _rename_key_prefix(c, table, old, new):
    """table.key 的 'old/' 前缀整体迁移（社团改名）。不用 LIKE：词条名可含 %/_。"""
    prefix = old + "/"
    c.execute("UPDATE OR IGNORE %s SET key = ? || substr(key, ?) "
              "WHERE substr(key, 1, ?) = ?" % table,
              (new + "/", len(prefix) + 1, len(prefix), prefix))


def rename_circle(old, new):
    """社团改名：circles 档案 + 全部作品 key 前缀 + 画师→社团映射 联动跟随。"""
    if not old or not new or old == new:
        return
    with meta._LOCK:
        c = meta._connect()
        # 先改后补：circles.name 是主键，不能先 INSERT 新名再 UPDATE 旧名（自撞主键）
        cur = c.execute("UPDATE circles SET name=?, renamed_from=? WHERE name=?", (new, old, old))
        if cur.rowcount == 0:
            c.execute("INSERT OR IGNORE INTO circles(name, renamed_from) VALUES(?,?)", (new, old))
        _rename_key_prefix(c, "works", old, new)
        c.execute("UPDATE works SET group_name=? WHERE group_name=?", (new, old))
        for t in _KEY_TABLES:
            _rename_key_prefix(c, t, old, new)
        c.execute("UPDATE OR IGNORE artist_circles SET circle=? WHERE circle=?", (new, old))
        c.execute("DELETE FROM artist_circles WHERE circle=?", (old,))
        c.commit()
        meta._fts_rebuild(c)
        c.commit()
        meta._invalidate()


def dissolve_circle(name):
    with meta._LOCK:
        c = meta._connect()
        c.execute("INSERT OR IGNORE INTO circles(name) VALUES(?)", (name,))
        c.execute("UPDATE circles SET dissolved=1 WHERE name=?", (name,))
        c.commit()
        meta._invalidate()


def forget_work(key):
    """作品被删除（直接删除，不再进回收站）时清掉其全部 DB 痕迹（含用户附加事实——删除是显式意图）。"""
    with meta._LOCK:
        c = meta._connect()
        for t in ("works", "work_authors", "work_tags", "reading", "ratings"):
            c.execute("DELETE FROM %s WHERE key=?" % t, (key,))
        c.execute("DELETE FROM collection_items WHERE key=?", (key,))
        c.commit()
        meta._fts_rebuild(c)
        c.commit()


# ---------------------------------------------------------------
# 别名 / 画师→社团 / 解散清单（DB 权威 + 缓存；合并视图在 app.py）
# ---------------------------------------------------------------
def author_aliases():
    with meta._LOCK:
        if meta._C_ALIASES is None:
            try:
                c = meta._connect()
                meta._C_ALIASES = {str(a): str(cn) for a, cn in
                                   c.execute("SELECT alias, canonical FROM author_aliases")}
            except Exception:
                meta._C_ALIASES = {}
        return dict(meta._C_ALIASES)


def circle_aliases():
    """3.6.11 社团别名表（alias → canonical）。"""
    with meta._LOCK:
        if meta._C_CIRCLE_ALIASES is None:
            try:
                c = meta._connect()
                meta._C_CIRCLE_ALIASES = {str(a): str(cn) for a, cn in
                                          c.execute("SELECT alias, canonical FROM circle_aliases")}
            except Exception:
                meta._C_CIRCLE_ALIASES = {}
        return dict(meta._C_CIRCLE_ALIASES)


def original_aliases():
    """3.6.19 原作别名表（alias → canonical）：变体写法归并到规范原作名。"""
    with meta._LOCK:
        if meta._C_ORIGINAL_ALIASES is None:
            try:
                c = meta._connect()
                meta._C_ORIGINAL_ALIASES = {str(a): str(cn) for a, cn in
                                            c.execute("SELECT alias, canonical FROM original_aliases")}
            except Exception:
                meta._C_ORIGINAL_ALIASES = {}
        return dict(meta._C_ORIGINAL_ALIASES)


def _fold_original(name):
    """原作名沿别名链折叠到终点（3.6.41，visited 防环）。

    与 app._fold_alias_chain 同规则，但 meta_store 不能 import app（循环依赖），
    故在数据层留一份薄实现——**两处必须同步**（本项目反复踩过"同一规则只改一处"）。
    用途：扫描对账时把"改名残留的旧名标签"折成正名，而不是无条件放行。"""
    aliases = original_aliases()
    cur = str(name or "").strip()
    seen = set()
    while cur in aliases and cur not in seen:
        seen.add(cur)
        cur = aliases[cur]
    return cur


def upsert_alias(alias, canonical, kind="author"):
    """kind: 'author' 笔名别名 | 'circle' 社团别名 | 'original' 原作别名
    （3.6.11 起三类共用同一套语义；original 于 3.6.19 新增）。"""
    table = {"circle": "circle_aliases", "original": "original_aliases"}.get(
        kind, "author_aliases")
    with meta._LOCK:
        c = meta._connect()
        c.execute("INSERT OR REPLACE INTO %s(alias, canonical) VALUES(?,?)" % table,
                  (alias, canonical))
        c.commit()
        meta._invalidate()


def delete_alias(alias, kind="author"):
    table = {"circle": "circle_aliases", "original": "original_aliases"}.get(
        kind, "author_aliases")
    with meta._LOCK:
        c = meta._connect()
        cur = c.execute("DELETE FROM %s WHERE alias=?" % table, (alias,))
        c.commit()
        meta._invalidate()
        return cur.rowcount > 0


def artist_circles():
    with meta._LOCK:
        if meta._C_ARTIST is None:
            out = {}
            try:
                c = meta._connect()
                for a, cn in c.execute("SELECT author, circle FROM artist_circles"):
                    out.setdefault(str(a), set()).add(str(cn))
            except Exception:
                out = {}
            meta._C_ARTIST = out
        return {a: set(cs) for a, cs in meta._C_ARTIST.items()}


def learn_artist_circle(author, circle):
    with meta._LOCK:
        c = meta._connect()
        c.execute("INSERT OR IGNORE INTO artist_circles(author, circle) VALUES(?,?)",
                  (author, circle))
        c.commit()
        meta._invalidate()


def dissolved_circles():
    with meta._LOCK:
        if meta._C_DISSOLVED is None:
            try:
                c = meta._connect()
                meta._C_DISSOLVED = {str(r[0]) for r in
                                     c.execute("SELECT name FROM circles WHERE dissolved=1")}
            except Exception:
                meta._C_DISSOLVED = set()
        return set(meta._C_DISSOLVED)


# ---------------------------------------------------------------
# 关注与画师档案（M4）
# ---------------------------------------------------------------
def follows_list():
    with meta._LOCK:
        c = meta._connect()
        return [{"author": r[0], "created_at": r[1], "last_seen_at": r[2]}
                for r in c.execute("SELECT author, created_at, last_seen_at FROM follows"
                                   " ORDER BY created_at DESC")]


def follow_add(author):
    with meta._LOCK:
        c = meta._connect()
        cur = c.execute("INSERT OR IGNORE INTO follows(author, created_at, last_seen_at)"
                        " VALUES(?,?,0)", (author, int(time.time())))
        c.commit()
        return cur.rowcount > 0


def follow_remove(author):
    with meta._LOCK:
        c = meta._connect()
        cur = c.execute("DELETE FROM follows WHERE author=?", (author,))
        c.commit()
        return cur.rowcount > 0


def follow_touch(author, ts):
    with meta._LOCK:
        c = meta._connect()
        c.execute("UPDATE follows SET last_seen_at=? WHERE author=?", (int(ts), author))
        c.commit()


def works_by_author(author):
    """某画师（正名）跨社团全部作品，按入库时间倒序。

    3.6.151：多带一个 `size`（works 表早有该列，只是没下发）——画师页「按文件大小」
    排序要用它查重。"""
    with meta._LOCK:
        c = meta._connect()
        return [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]) for r in c.execute(
            "SELECT w.key, w.group_name, w.name, w.pages, w.kind, w.added_at, w.mtime,"
            " w.circle, w.size"
            " FROM work_authors a JOIN works w ON w.key = a.key"
            " WHERE a.author=? ORDER BY w.added_at DESC, w.key", (author,))]


def authors_of(key):
    """某作品的作者多值（按入库顺序，合作作品每位作者一个）。"""
    with meta._LOCK:
        c = meta._connect()
        return [r[0] for r in c.execute(
            "SELECT author FROM work_authors WHERE key=? ORDER BY rowid", (key,)).fetchall()]


def originals_of(key):
    """某作品的原作标签（3.7.51）：卡片/续读/画师页都要显示——原作标签此前只在
    原作分区页渲染，因为只有那边的数据带 tags。按名称升序，稳定。"""
    with meta._LOCK:
        c = meta._connect()
        return [r[0] for r in c.execute(
            "SELECT name FROM work_tags WHERE key=? AND type='original' ORDER BY name",
            (key,)).fetchall()]


def author_work_paths(author):
    """某画师（正名）名下全部作品的 (key, group_name, name, path) —— 改名搬文件用。"""
    with meta._LOCK:
        c = meta._connect()
        return [(r[0], r[1], r[2], r[3]) for r in c.execute(
            "SELECT w.key, w.group_name, w.name, w.path FROM work_authors a"
            " JOIN works w ON w.key = a.key WHERE a.author=?"
            " ORDER BY w.added_at DESC, w.key", (author,))]


def rename_author(old, new):
    """画师改名/合并：work_authors、别名链、画师→社团映射、喜爱清单、FTS 全联动。

    合并场景（new 已是库中画师）同样适用：work_authors 用 UPDATE OR IGNORE，
    目标侧已有 (key, new) 行时旧行被忽略后删除——不会出现同作品双作者脏行；
    旧名同时降级为指向 new 的别名，保留「按旧名检索/历史文件名」的入口。
    """
    if not old or not new or old == new:
        return 0
    with meta._LOCK:
        c = meta._connect()
        cur = c.execute("UPDATE OR IGNORE work_authors SET author=? WHERE author=?",
                        (new, old))
        moved = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        c.execute("DELETE FROM work_authors WHERE author=?", (old,))
        # 别名链：原先指向 old 的别名改指 new；old 自身挂成 new 的别名
        c.execute("UPDATE OR REPLACE author_aliases SET canonical=? WHERE canonical=?",
                  (new, old))
        c.execute("DELETE FROM author_aliases WHERE alias=?", (old,))
        c.execute("INSERT OR IGNORE INTO author_aliases(alias, canonical) VALUES(?,?)",
                  (old, new))
        # 画师→社团映射
        c.execute("UPDATE OR IGNORE artist_circles SET author=? WHERE author=?", (new, old))
        c.execute("DELETE FROM artist_circles WHERE author=?", (old,))
        # 喜爱清单：并入 new（保留较早的创建时间与较晚的查看时间）
        _merge_follow(c, old, new)
        c.commit()
        meta._fts_rebuild(c)
        c.commit()
        meta._invalidate()
    return moved


def _merge_follow(c, old, new):
    row = c.execute("SELECT created_at, last_seen_at FROM follows WHERE author=?",
                    (old,)).fetchone()
    if not row:
        return
    tgt = c.execute("SELECT created_at, last_seen_at FROM follows WHERE author=?",
                    (new,)).fetchone()
    c.execute("DELETE FROM follows WHERE author=?", (old,))
    if tgt:
        c.execute("UPDATE follows SET created_at=?, last_seen_at=? WHERE author=?",
                  (min(row[0], tgt[0]), max(row[1], tgt[1]), new))
    else:
        c.execute("INSERT OR REPLACE INTO follows(author, created_at, last_seen_at)"
                  " VALUES(?,?,?)", (new, row[0], row[1]))


def works_count_by_author(author, added_since=0):
    with meta._LOCK:
        c = meta._connect()
        row = c.execute(
            "SELECT COUNT(*), IFNULL(SUM(w.added_at > :since AND w.added_at > 0), 0)"
            " FROM work_authors a JOIN works w ON w.key = a.key WHERE a.author = :a",
            {"since": int(added_since), "a": author}).fetchone()
        return row[0], row[1]


def aliases_of(canonical):
    """指向某正名的全部别名。"""
    with meta._LOCK:
        c = meta._connect()
        return [r[0] for r in c.execute(
            "SELECT alias FROM author_aliases WHERE canonical=?", (canonical,))]


def artists_all():
    """全部画师（跨社团去重，按作品数降序）——画师分区/档案页一级入口的数据源。
    每位画师附「体积最大作品」的首页作封面（cover_*）与最新入库时间（latest）。"""
    with meta._LOCK:
        c = meta._connect()
        rows = c.execute(
            "SELECT a.author, w.key, w.size, w.group_name, w.name, w.mtime, w.pages"
            " FROM work_authors a JOIN works w ON w.key = a.key").fetchall()
        added_rows = c.execute(
            "SELECT a.author, MAX(w.added_at) FROM work_authors a"
            " JOIN works w ON w.key = a.key GROUP BY a.author").fetchall()
    counts = {}
    biggest = {}
    for author, _key, size, gname, wname, mtime, pages in rows:
        counts[author] = counts.get(author, 0) + 1
        sz = size if (size is not None and size > 0) else -1
        cur = biggest.get(author)
        if cur is None or sz > cur[0]:
            biggest[author] = (sz, gname, wname, mtime or 0, pages or 0)
    added = {r[0]: (r[1] or 0) for r in added_rows}
    out = []
    for author in sorted(counts, key=lambda a: (-counts[a], a)):
        b = biggest.get(author)
        out.append({"name": author, "works": counts[author],
                    "latest": added.get(author, 0),
                    "cover_group": b[1] if b else None,
                    "cover_work": b[2] if b else None,
                    "cover_mtime": b[3] if b else 0,
                    "cover_pages": b[4] if b else 0})
    return out
