# -*- coding: utf-8 -*-
"""services/inbox_db.py —— 收件箱登记与内容哈希去重（3.6.77 从 meta_store 拆出）。

为什么拆：拆分时 `meta_store` 已顶到 1545 行的冻结上限（后续持续增长到 1626，
3.6.84 再拆三条支线后落到 516 行）；这一簇在 meta_store 内部**没有被调用**，是天然的搬移单元。

调用方式不变：`meta.inbox_list()` / `meta.works_by_size()` 由 meta_store 的
PEP 562 `__getattr__` 惰性转发到这里，`monkeypatch.setattr(meta_store, "DB_PATH", ...)`
仍然生效（连接仍由 `meta._connect()` 提供，读的是打桩后的路径）。
"""
import time

import meta_store as meta


def inbox_upsert(src, name, size, mtime, sha1, proposal):
    """按 src 路径登记/更新收件项（文件重新落盘 = 内容变化 = 重新提案、回到 pending）。"""
    with meta._LOCK:
        c = meta._connect()
        row = c.execute("SELECT id, mtime, state FROM inbox WHERE src=?", (src,)).fetchone()
        now = int(time.time())
        if row and row[1] == mtime:
            return row[0], False
        c.execute("INSERT OR REPLACE INTO inbox(src, name, size, mtime, sha1, proposal, state, at)"
                  " VALUES(?,?,?,?,?,?, 'pending', ?)", (src, name, size, mtime, sha1, proposal, now))
        c.commit()
        row2 = c.execute("SELECT id FROM inbox WHERE src=?", (src,)).fetchone()
        return row2[0], True


def inbox_list():
    with meta._LOCK:
        c = meta._connect()
        rows = c.execute("SELECT id, src, name, size, mtime, sha1, proposal, state, at"
                         " FROM inbox ORDER BY CASE state WHEN 'pending' THEN 0 ELSE 1 END, at DESC, id DESC").fetchall()
        return [{"id": r[0], "src": r[1], "name": r[2], "size": r[3], "mtime": r[4],
                 "sha1": r[5], "proposal": r[6], "state": r[7], "at": r[8]} for r in rows]


def inbox_get(iid):
    with meta._LOCK:
        c = meta._connect()
        r = c.execute("SELECT id, src, name, size, mtime, sha1, proposal, state, at"
                      " FROM inbox WHERE id=?", (iid,)).fetchone()
        if not r:
            return None
        return {"id": r[0], "src": r[1], "name": r[2], "size": r[3], "mtime": r[4],
                "sha1": r[5], "proposal": r[6], "state": r[7], "at": r[8]}


def inbox_set_state(iid, state):
    with meta._LOCK:
        c = meta._connect()
        cur = c.execute("UPDATE inbox SET state=? WHERE id=?", (state, iid))
        c.commit()
        return cur.rowcount > 0


def inbox_reset_state(old, new):
    """批量状态迁移（如 3.5.1 移除「忽略」→ ignored 变 pending）。返回影响行数。"""
    with meta._LOCK:
        c = meta._connect()
        cur = c.execute("UPDATE inbox SET state=? WHERE state=?", (new, old))
        c.commit()
        return cur.rowcount


def inbox_delete(iid):
    with meta._LOCK:
        c = meta._connect()
        cur = c.execute("DELETE FROM inbox WHERE id=?", (iid,))
        c.commit()
        return cur.rowcount > 0


def inbox_find_sha1(sha1, exclude_src=None):
    """队列内同内容项（跨改名重复的第一道防线）。"""
    with meta._LOCK:
        c = meta._connect()
        row = c.execute("SELECT id, name FROM inbox WHERE sha1=? AND src IS NOT ? AND state='pending'",
                        (sha1, exclude_src)).fetchone()
        return {"id": row[0], "name": row[1]} if row else None


def works_by_size(size):
    """同体积作品（内容哈希去重的候选集：改名副本体积必相同）。"""
    with meta._LOCK:
        c = meta._connect()
        return [(r[0], r[1], r[2], r[3], r[4]) for r in c.execute(
            "SELECT key, group_name, name, path, sha1 FROM works WHERE size=?", (size,))]


def work_sha1_set(key, sha1):
    with meta._LOCK:
        c = meta._connect()
        c.execute("UPDATE works SET sha1=? WHERE key=?", (sha1, key))
        c.commit()


def work_register_sha1(key, path, size, sha1):
    """导入即时登记哈希基准（works 行可能尚未随扫描建立，先占位最小行；
    扫描同步会补全其余字段；同 key 已存在时不覆盖）。"""
    with meta._LOCK:
        c = meta._connect()
        grp, _, nm = key.partition("/")
        c.execute("INSERT OR IGNORE INTO works(key, group_name, name, path, size, sha1)"
                  " VALUES(?,?,?,?,?,?)", (key, grp, nm, str(path), int(size), sha1))
        c.commit()
