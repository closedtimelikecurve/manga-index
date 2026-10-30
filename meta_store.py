# -*- coding: utf-8 -*-
"""
meta_store.py —— Index 3.0 元数据层（SQLite 唯一事实源）
==========================================================
设计要点（见《更新计划书-3.0元数据时代》M1）：
  * 文件系统退化为纯存储：扫描器（scan_groups）仍是发现引擎，每次扫描后把结果
    upsert 进本库（works/work_authors/work_tags 三张"扫描派生表"）；
  * 用户附加事实（评分/收藏/阅读状态/收藏集）只存本库，重扫永不丢失；
  * config.json 的 artist_circles / author_aliases / dissolved_circles 首次启动
    一次性迁入（meta_kv.migrated_config_v1 防重复），此后 config 对应键只读不再写回；
    读取侧 = DB(权威) ∪ config 旧值，合并视图由 app.py 完成（双轨兼容）；
  * FTS5 全文索引（works_fts，trigram 分词支持 CJK 子串）随每次扫描全量重建；
  * 备份时间机器：结构性变更前 snapshot() 到 _app/backups/，保留最近 30 份 + 每日首份；
  * 回滚：删 meta.db 即回到 2.15 行为（派生表随首扫重新回填）。

线程模型：单连接 + RLock 串行（Flask threaded；全部操作毫秒级，无长事务跨请求）。
连接惰性打开并跟随 DB_PATH —— tests/conftest.py 把 DB_PATH 指到临时目录即可整体隔离，
绝不写穿真实 _app/meta.db（与 config.json 同一纪律）。
"""
import json
import logging
import os
import re
import sqlite3
import threading
import unicodedata
import time

import common

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "meta.db")
BACKUP_DIR = os.path.join(APP_DIR, "backups")

_LOCK = threading.RLock()
_CONN = None
_OPEN_PATH = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta_kv(
  k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS works(
  key TEXT PRIMARY KEY,             -- "社团/作品名"（与 API workKey 一致）
  group_name TEXT, name TEXT,
  path TEXT UNIQUE, size INTEGER, mtime INTEGER, pages INTEGER, kind TEXT,
  circle TEXT, bare TEXT,
  added_at INTEGER DEFAULT 0,       -- 首次入库时间（回填自文件 mtime/社团入库时间）
  seen_at INTEGER DEFAULT 0,        -- mark-seen 的按作品基准
  sha1 TEXT);                       -- 内容哈希（惰性计算：收件箱/导入去重时才哈希并缓存）
CREATE TABLE IF NOT EXISTS work_authors(
  key TEXT, author TEXT, PRIMARY KEY(key, author));
CREATE TABLE IF NOT EXISTS work_tags(
  key TEXT, type TEXT, name TEXT, PRIMARY KEY(key, type, name));
CREATE TABLE IF NOT EXISTS author_aliases(
  alias TEXT PRIMARY KEY, canonical TEXT);
-- 3.6.11 社团别名：与笔名别名同构（别名 → 正名）。被登记为别名的社团不再单列，
-- 其作品并入正名社团展示（作品 path 仍在原目录，key 不变，阅读进度/收藏不受影响）。
CREATE TABLE IF NOT EXISTS circle_aliases(
  alias TEXT PRIMARY KEY, canonical TEXT);
-- 3.6.19 原作别名：与笔名/社团别名同构（别名 → 正名）。原作名写法多样
-- （Fate／Grand Order / FateGrand Order / FGO…），登记后 norm 归一映射
-- 指向正名，解析器据此把变体括号归入同一原作分区（load_originals 之后叠加）。
CREATE TABLE IF NOT EXISTS original_aliases(
  alias TEXT PRIMARY KEY, canonical TEXT);
CREATE TABLE IF NOT EXISTS artist_circles(
  author TEXT, circle TEXT, PRIMARY KEY(author, circle));
CREATE TABLE IF NOT EXISTS circles(
  name TEXT PRIMARY KEY, dissolved INTEGER DEFAULT 0,
  created_at INTEGER DEFAULT 0, renamed_from TEXT);
CREATE TABLE IF NOT EXISTS reading(
  key TEXT PRIMARY KEY, last_page INTEGER DEFAULT 0,
  finished INTEGER DEFAULT 0, last_read_at INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS ratings(
  key TEXT PRIMARY KEY, score INTEGER DEFAULT 0, favorite INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS collections(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE,
  created_at INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS collection_items(
  cid INTEGER, key TEXT, added_at INTEGER DEFAULT 0, PRIMARY KEY(cid, key));
CREATE VIRTUAL TABLE IF NOT EXISTS works_fts USING fts5(
  key UNINDEXED, title, authors, tags, circle, tokenize='trigram');
CREATE TABLE IF NOT EXISTS snapshots(
  id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER, file TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS inbox(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  src TEXT UNIQUE,                  -- 收件文件绝对路径（_inbox/ 内）
  name TEXT, size INTEGER, mtime INTEGER,
  sha1 TEXT,                        -- 内容哈希（登记时计算，提案去重与确认复用）
  proposal TEXT,                    -- 入库提案 JSON（词条/归一化名/置信度/疑似重复）
  state TEXT DEFAULT 'pending',     -- pending | confirmed（ignored 于 3.5.1 移除）
  at INTEGER);                      -- 登记时间
CREATE TABLE IF NOT EXISTS follows(
  author TEXT PRIMARY KEY,          -- 正名（笔名别名归一后）
  created_at INTEGER DEFAULT 0,
  last_seen_at INTEGER DEFAULT 0);  -- 上次查看该画师新作品的时间（新作品计数基准）
"""


# ---------------------------------------------------------------
# 连接与缓存
# ---------------------------------------------------------------
def close():
    """关闭连接并清空缓存（测试隔离 / 恢复快照后重开时用）。"""
    global _CONN, _OPEN_PATH
    with _LOCK:
        if _CONN is not None:
            try:
                _CONN.close()
            except Exception:
                pass
        _CONN = None
        _OPEN_PATH = None
        _invalidate()


def _invalidate():
    global _C_ALIASES, _C_ARTIST, _C_DISSOLVED, _C_CIRCLE_ALIASES, _C_ORIGINAL_ALIASES
    _C_ALIASES = None
    _C_ARTIST = None
    _C_DISSOLVED = None
    _C_CIRCLE_ALIASES = None       # 3.6.11 社团别名
    _C_ORIGINAL_ALIASES = None     # 3.6.19 原作别名


_C_ALIASES = None
_C_ARTIST = None
_C_DISSOLVED = None
_C_CIRCLE_ALIASES = None
_C_ORIGINAL_ALIASES = None


def _connect():
    """惰性打开/跟随 DB_PATH（路径变了 = 旧连接作废重开，测试零成本隔离）。"""
    global _CONN, _OPEN_PATH
    with _LOCK:
        path = os.path.abspath(DB_PATH)
        if _CONN is not None and _OPEN_PATH == path:
            return _CONN
        if _CONN is not None:
            try:
                _CONN.close()
            except Exception:
                pass
            _CONN = None
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        c = sqlite3.connect(path, check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.executescript(_SCHEMA)
        _ensure_columns(c)
        c.commit()
        _CONN = c
        _OPEN_PATH = path
        _invalidate()
        _migrate_config_once(c)
        return c


# ---------------------------------------------------------------
# 一次性迁移：config.json 三键 → DB（幂等，meta_kv 打标防重复）
# ---------------------------------------------------------------
def _migrate_config_once(c):
    """首启 config→DB 迁移（实现见 services/db_bootstrap.py；失败整轮回滚，下次重连重试）。"""
    from services.db_bootstrap import migrate_config
    return migrate_config(c)


# ---------------------------------------------------------------
# 扫描同步（双轨核心）：已迁至 services/db_sync.py（3.6.77）
# meta.sync_scan() 经 __getattr__ 惰性转发；_fts_rebuild 留在这里（改名/合并/解散也要用）
# ---------------------------------------------------------------
def _in_chunks(seq, n=400):
    """SQL IN 参数分块（SQLite 变量上限 999，400 留足余量）。"""
    for i in range(0, len(seq), n):
        yield seq[i:i + n]

def _like_pat(term):
    """LIKE 模式串：转义反斜杠与 `%` `_`，再包成 `%term%`（originals_search 与 services/search 共用）。"""
    esc = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + esc + "%"


def _fts_rebuild(c):
    c.execute("DELETE FROM works_fts")
    c.execute("INSERT INTO works_fts(key, title, authors, tags, circle)"
              " SELECT w.key, w.name,"
              " IFNULL((SELECT GROUP_CONCAT(a.author,' ') FROM work_authors a WHERE a.key=w.key),''),"
              " IFNULL((SELECT GROUP_CONCAT(t.name,' ') FROM work_tags t WHERE t.key=w.key),''),"
              " IFNULL(w.group_name,'')"
              " FROM works w")

# ---------------------------------------------------------------
# 用户附加事实：评分/收藏/阅读状态/收藏集
# ---------------------------------------------------------------
def set_rating(key, score=None, favorite=None):
    with _LOCK:
        c = _connect()
        c.execute("INSERT OR IGNORE INTO ratings(key) VALUES(?)", (key,))
        if score is not None:
            c.execute("UPDATE ratings SET score=? WHERE key=?", (int(score), key))
        if favorite is not None:
            c.execute("UPDATE ratings SET favorite=? WHERE key=?", (1 if favorite else 0, key))
        c.commit()
        row = c.execute("SELECT score, favorite FROM ratings WHERE key=?", (key,)).fetchone()
        return {"score": row[0], "favorite": bool(row[1])} if row else {"score": 0, "favorite": 0}


def reading_get(key):
    with _LOCK:
        c = _connect()
        row = c.execute("SELECT last_page, finished, last_read_at FROM reading WHERE key=?",
                        (key,)).fetchone()
        return {"key": key, "last_page": row[0] if row else 0,
                "finished": bool(row[1]) if row else False,
                "last_read_at": row[2] if row else 0}


def reading_set(key, last_page, finished=None):
    with _LOCK:
        c = _connect()
        c.execute("INSERT OR IGNORE INTO reading(key) VALUES(?)", (key,))
        if finished is None:
            c.execute("UPDATE reading SET last_page=?, last_read_at=? WHERE key=?",
                      (int(last_page), int(time.time()), key))
        else:
            c.execute("UPDATE reading SET last_page=?, finished=?, last_read_at=? WHERE key=?",
                      (int(last_page), 1 if finished else 0, int(time.time()), key))
        c.commit()
        return reading_get(key)


def reading_resume(limit=10):
    """最近在 读 的作品（继续阅读列表）——已读完的不再出现（3.2.1 用户要求）。
    附 personals（合作画师列表，按入库顺序）与 circle（所属社团/圈子名），
    供前端/APP 续读卡片渲染「可点击的社团 + 画师标签」（2026-10-15 需求1）。"""
    with _LOCK:
        c = _connect()
        rows = c.execute("SELECT r.key, r.last_page, r.finished, r.last_read_at,"
                         " w.group_name, w.name, w.pages, w.circle"
                         " FROM reading r LEFT JOIN works w ON w.key = r.key"
                         " WHERE r.last_read_at > 0 AND r.finished = 0"
                         " ORDER BY r.last_read_at DESC LIMIT ?",
                         (int(limit),)).fetchall()
        out = []
        for r in rows:
            key = r[0]
            authors = [a[0] for a in c.execute(
                "SELECT author FROM work_authors WHERE key=? ORDER BY rowid", (key,)).fetchall()]
            originals = [o[0] for o in c.execute(
                "SELECT name FROM work_tags WHERE key=? AND type='original' ORDER BY name",
                (key,)).fetchall()]
            out.append({"key": key, "last_page": r[1], "finished": bool(r[2]), "last_read_at": r[3],
                        "group": r[4], "work": r[5], "pages": r[6], "circle": r[7] or "",
                        "personals": authors, "originals": originals})
        return out


def mark_seen(key=None):
    """记录「最后访问时间」（新作品标亮基准）；带 key 时同时盖该作品的 seen_at。"""
    with _LOCK:
        c = _connect()
        prev = float(_kv_get(c, "last_visit_at") or 0)
        now = time.time()
        _kv_set(c, "last_visit_at", repr(now))
        if key:
            c.execute("UPDATE works SET seen_at=? WHERE key=?", (int(now), key))
        c.commit()
        return prev


def stats_overview():
    with _LOCK:
        c = _connect()
        total, pages = c.execute("SELECT COUNT(*), IFNULL(SUM(pages),0) FROM works").fetchone()
        finished = c.execute("SELECT COUNT(*) FROM reading WHERE finished=1").fetchone()[0]
        started = c.execute("SELECT COUNT(*) FROM reading WHERE last_read_at>0").fetchone()[0]
        favorites = c.execute("SELECT COUNT(*) FROM ratings WHERE favorite=1").fetchone()[0]
        rated = c.execute("SELECT COUNT(*) FROM ratings WHERE score>0").fetchone()[0]
        circles_n = c.execute("SELECT COUNT(*) FROM circles WHERE dissolved=0").fetchone()[0]
        by_day = [{"day": r[0], "count": r[1]} for r in c.execute(
            "SELECT date(added_at,'unixepoch','localtime') d, COUNT(*) c FROM works"
            " WHERE added_at>0 GROUP BY d ORDER BY d DESC LIMIT 90")]
        by_day.reverse()
        top_authors = [{"name": r[0], "count": r[1]} for r in c.execute(
            "SELECT author, COUNT(DISTINCT key) c FROM work_authors"
            " GROUP BY author ORDER BY c DESC, author LIMIT 10")]
        return {"works": total, "pages": pages, "finished": finished, "started": started,
                "favorites": favorites, "rated": rated, "circles": circles_n,
                "by_day": by_day, "top_authors": top_authors,
                "last_visit_at": float(_kv_get(c, "last_visit_at") or 0)}


def work_meta(key):
    """作品全部元数据（含用户附加事实）。DB 无此 key 返回 None（调用方回退扫描结果）。"""
    with _LOCK:
        c = _connect()
        w = c.execute("SELECT key, group_name, name, path, size, mtime, pages, kind,"
                      " circle, bare, added_at FROM works WHERE key=?", (key,)).fetchone()
        if not w:
            return None
        authors = [r[0] for r in c.execute(
            "SELECT author FROM work_authors WHERE key=? ORDER BY rowid", (key,))]
        tags = [{"type": r[0], "name": r[1]} for r in c.execute(
            "SELECT type, name FROM work_tags WHERE key=? ORDER BY rowid", (key,))]
        rating = c.execute("SELECT score, favorite FROM ratings WHERE key=?", (key,)).fetchone()
        reading = c.execute("SELECT last_page, finished, last_read_at FROM reading WHERE key=?",
                            (key,)).fetchone()
        cols = [{"id": r[0], "name": r[1]} for r in c.execute(
            "SELECT ci.cid, cl.name FROM collection_items ci JOIN collections cl ON cl.id=ci.cid"
            " WHERE ci.key=? ORDER BY cl.name", (key,))]
        return {"key": w[0], "group": w[1], "work": w[2], "path": w[3], "size": w[4],
                "mtime": w[5], "pages": w[6], "kind": w[7], "circle": w[8], "bare": w[9],
                "added_at": w[10], "authors": authors, "tags": tags,
                "rating": {"score": rating[0] if rating else 0,
                           "favorite": bool(rating[1]) if rating else False},
                "reading": {"last_page": reading[0] if reading else 0,
                            "finished": bool(reading[1]) if reading else False,
                            "last_read_at": reading[2] if reading else 0},
                "collections": cols}


# ---------------- 收藏集 ----------------
def collections_list():
    with _LOCK:
        c = _connect()
        return [{"id": r[0], "name": r[1], "count": r[2]} for r in c.execute(
            "SELECT cl.id, cl.name, (SELECT COUNT(*) FROM collection_items ci WHERE ci.cid=cl.id)"
            " FROM collections cl ORDER BY cl.id")]


def collection_create(name):
    with _LOCK:
        c = _connect()
        cur = c.execute("INSERT INTO collections(name, created_at) VALUES(?,?)",
                        (name, int(time.time())))
        c.commit()
        return cur.lastrowid


def collection_rename(cid, name):
    with _LOCK:
        c = _connect()
        cur = c.execute("UPDATE collections SET name=? WHERE id=?", (name, cid))
        c.commit()
        return cur.rowcount > 0


def collection_delete(cid):
    with _LOCK:
        c = _connect()
        c.execute("DELETE FROM collection_items WHERE cid=?", (cid,))
        cur = c.execute("DELETE FROM collections WHERE id=?", (cid,))
        c.commit()
        return cur.rowcount > 0


def collection_add(cid, key):
    with _LOCK:
        c = _connect()
        c.execute("INSERT OR IGNORE INTO collection_items(cid, key, added_at) VALUES(?,?,?)",
                  (cid, key, int(time.time())))
        c.commit()


def collection_remove(cid, key):
    with _LOCK:
        c = _connect()
        cur = c.execute("DELETE FROM collection_items WHERE cid=? AND key=?", (cid, key))
        c.commit()
        return cur.rowcount > 0


def collection_get(cid):
    with _LOCK:
        c = _connect()
        row = c.execute("SELECT id, name FROM collections WHERE id=?", (cid,)).fetchone()
        if not row:
            return None
        items = []
        for r in c.execute("SELECT ci.key, ci.added_at, w.group_name, w.name, w.pages, w.kind"
                           " FROM collection_items ci LEFT JOIN works w ON w.key=ci.key"
                           " WHERE ci.cid=? ORDER BY ci.added_at DESC, ci.rowid DESC", (cid,)):
            items.append({"key": r[0], "added_at": r[1], "group": r[2], "work": r[3],
                          "pages": r[4], "kind": r[5], "missing": r[2] is None})
        return {"id": row[0], "name": row[1], "items": items}


def _kv_get(c, k):
    row = c.execute("SELECT v FROM meta_kv WHERE k=?", (k,)).fetchone()
    return row[0] if row else None


def _kv_set(c, k, v):
    c.execute("INSERT OR REPLACE INTO meta_kv(k, v) VALUES(?,?)", (k, str(v)))


def _ensure_columns(c):
    """既有 meta.db 的列迁移（CREATE TABLE IF NOT EXISTS 不会补旧表的列）。"""
    try:
        cols = {r[1] for r in c.execute("PRAGMA table_info(works)")}
        if "sha1" not in cols:
            c.execute("ALTER TABLE works ADD COLUMN sha1 TEXT")
            c.commit()
    except Exception:
        pass


# ---------------------------------------------------------------
# 收件箱（M3 提案式入库）：已迁至 services/inbox_db.py（3.6.77）
# meta.inbox_* 经 __getattr__ 惰性转发；连接仍由本模块 _connect() 提供
# ---------------------------------------------------------------


def reading_all():
    with _LOCK:
        c = _connect()
        return [(r[0], r[1], r[2]) for r in c.execute(
            "SELECT key, last_page, finished FROM reading")]


def works_keys_added_since(ts):
    """某时间点之后入库的作品 key（ts<=0 恒空：首次访问没有"新"基线）。"""
    if not ts or int(ts) <= 0:
        return []
    with _LOCK:
        c = _connect()
        return [r[0] for r in c.execute(
            "SELECT key FROM works WHERE added_at > ? AND added_at > 0", (int(ts),))]


# ---------------------------------------------------------------
# 检索簇（3.6.76 拆至 services/search.py）
# ---------------------------------------------------------------
_LAZY_MODULES = {
    # 检索簇（3.6.76）
    # 入库时间读取（3.6.151：文件顶到 400 行预算，搬去 services/meta_arrival.py）
    "works_added_at": "services.meta_arrival",
    "group_last_added": "services.meta_arrival",
    "group_seed": "services.meta_arrival",
    "author_work_count": "services.meta_arrival",
    "search2": "services.search",
    "_fw_variant": "services.search",
    # 扫描落库流水线（3.6.77）
    "sync_scan": "services.db_sync",
    "_scan_collect": "services.db_sync",
    "_scan_sync_works": "services.db_sync",
    "_scan_sync_derived": "services.db_sync",
    "_scan_prune": "services.db_sync",
    "_scan_fts": "services.db_sync",
    # 收件箱 / 内容哈希簇（3.6.77）
    "inbox_upsert": "services.inbox_db",
    "inbox_list": "services.inbox_db",
    "inbox_get": "services.inbox_db",
    "inbox_set_state": "services.inbox_db",
    "inbox_reset_state": "services.inbox_db",
    "inbox_delete": "services.inbox_db",
    "inbox_find_sha1": "services.inbox_db",
    "works_by_size": "services.inbox_db",
    "work_sha1_set": "services.inbox_db",
    "work_register_sha1": "services.inbox_db",
    # 备份时间机器 / 全量导出（3.6.84）
    "snapshot": "services.meta_backup",
    "_retention": "services.meta_backup",
    "backup_list": "services.meta_backup",
    "backup_restore": "services.meta_backup",
    "export_json": "services.meta_backup",
    # 原作分区读取与手动维护（3.6.84）
    "originals_all": "services.meta_originals",
    "_original_zone_rows": "services.meta_originals",
    "_zone_stats": "services.meta_originals",
    "_zone_payload": "services.meta_originals",
    "_loose": "services.meta_originals",
    "originals_search": "services.meta_originals",
    "resolve_work_key": "services.meta_originals",
    "originals_add": "services.meta_originals",
    "originals_remove": "services.meta_originals",
    "work_tags_rename": "services.meta_originals",
    "originals_stale_names": "services.meta_originals",
    "original_tags_all": "services.meta_originals",
    "originals_merge": "services.meta_originals",
    # 画师/社团别名、关注清单与 key 迁移（3.6.84）
    "rename_work_key": "services.meta_artist",
    "merge_circles": "services.meta_artist",
    "_rename_key_prefix": "services.meta_artist",
    "rename_circle": "services.meta_artist",
    "dissolve_circle": "services.meta_artist",
    "forget_work": "services.meta_artist",
    "originals_of": "services.meta_artist",   # 3.7.51：卡片/续读/画师页显示原作标签
    "author_aliases": "services.meta_artist",
    "circle_aliases": "services.meta_artist",
    "original_aliases": "services.meta_artist",
    "_fold_original": "services.meta_artist",
    "upsert_alias": "services.meta_artist",
    "delete_alias": "services.meta_artist",
    "artist_circles": "services.meta_artist",
    "learn_artist_circle": "services.meta_artist",
    "dissolved_circles": "services.meta_artist",
    "follows_list": "services.meta_artist",
    "follow_add": "services.meta_artist",
    "follow_remove": "services.meta_artist",
    "follow_touch": "services.meta_artist",
    "works_by_author": "services.meta_artist",
    "authors_of": "services.meta_artist",
    "author_work_paths": "services.meta_artist",
    "rename_author": "services.meta_artist",
    "_merge_follow": "services.meta_artist",
    "works_count_by_author": "services.meta_artist",
    "aliases_of": "services.meta_artist",
    "artists_all": "services.meta_artist",
}


def __getattr__(name):
    """惰性再导出已迁出的函数（`meta.inbox_list` / `from meta_store import search2` 照旧可用）。

    用 PEP 562 而不是模块级 import —— 被迁模块导入期就要取 `_LOCK/_connect/_in_chunks`，
    两边都写模块级 import 会撞上"半初始化模块"的 ImportError。
    """
    mod = _LAZY_MODULES.get(name)
    if mod:
        from importlib import import_module
        return getattr(import_module(mod), name)
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
