# -*- coding: utf-8 -*-
"""services/db_bootstrap.py —— 首启把 config 的三类旧配置搬进 DB（3.6.77 从 meta_store 拆出）。

一次性、幂等：`meta_kv.migrated_config_v1` 打标后不再执行；失败整轮回滚，下次 `_connect()` 重试。
为什么独立成文件：meta_store 已到行数上限（docs/architecture.md §8.1），
这块只被 `_connect()` 调用一次，是最安全的搬移单元。

`meta._migrate_config_once(c)` 仍是唯一入口（转发到 `migrate_config`）。
"""
import logging
import time

import common
import meta_store as meta

log = logging.getLogger("meta_store")   # 与 meta_store 同源，方便按模块筛日志


def _migrate_config_once(c):
    """首启把 config 三键搬进 DB（一次性、幂等；失败整轮回滚，下次重试）。"""
    try:
        row = c.execute("SELECT v FROM meta_kv WHERE k='migrated_config_v1'").fetchone()
        if row and row[0] == "1":
            return
        cfg = common.CFG or {}
        now = int(time.time())
        _migrate_aliases(c, cfg)
        _migrate_dissolved(c, cfg)
        _migrate_artist_circles(c, cfg)
        c.execute("INSERT OR REPLACE INTO meta_kv(k, v) VALUES('migrated_config_v1','1')")
        c.execute("INSERT OR REPLACE INTO meta_kv(k, v) VALUES('migrated_at',?)", (str(now),))
        c.commit()
        meta._invalidate()
    except Exception:
        _safe_rollback(c)


def _safe_rollback(c):
    """回滚失败不覆盖原始异常：只记 debug（否则真正的迁移错误会被吞掉）。"""
    try:
        c.rollback()
    except Exception:
        log.debug("config→DB 迁移回滚失败", exc_info=True)


def _migrate_aliases(c, cfg):
    """author_aliases：旧正名 → 新正名（INSERT OR REPLACE，DB 权威）。"""
    for alias, canon in (cfg.get("author_aliases") or {}).items():
        a, cn = str(alias).strip(), str(canon).strip()
        if a and cn:
            c.execute("INSERT OR REPLACE INTO author_aliases(alias, canonical) VALUES(?,?)", (a, cn))


def _migrate_dissolved(c, cfg):
    """dissolved_circles → circles.dissolved=1。"""
    for name in (cfg.get("dissolved_circles") or []):
        n = str(name).strip()
        if n:
            c.execute("INSERT OR IGNORE INTO circles(name, dissolved) VALUES(?,1)", (n,))


def _migrate_artist_circles(c, cfg):
    """artist_circles：画师 → 所属社团（列表形态才收，非 list 的直接跳过）。"""
    for artist, cs in (cfg.get("artist_circles") or {}).items():
        if not isinstance(cs, list):
            continue
        for cname in cs:
            a, cn = str(artist).strip(), str(cname).strip()
            if a and cn:
                c.execute("INSERT OR IGNORE INTO artist_circles(author, circle) VALUES(?,?)", (a, cn))


def migrate_config(c):
    """对外的唯一入口（meta_store 转发到这里）。"""
    return _migrate_config_once(c)
