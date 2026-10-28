# -*- coding: utf-8 -*-
"""应急工具：从自动备份导回被误清空的派生表（works / work_authors / work_tags）。

背景（2026-10-13 事故）：后台重扫线程跨异步边界写穿，sync_scan 的「不在本次扫描中的
key 全部删除」语义把线上 works 2263 行删到 1 行。三张表都是**派生表**（内容可由扫描
重建），但重建要一轮全量重扫且会丢 added_at/seen_at 等历史字段——优先从自动备份导回。

用法：
    python scripts/restore_derived_tables.py                 # 用 backups/ 下最新备份
    python scripts/restore_derived_tables.py backups/xxx.db  # 指定备份

行为：
  * 只 INSERT OR IGNORE，冲突行以当前库为准；**绝不动** reading / circles / follows /
    inbox / artist_circles 等用户事实表（它们通常比备份更新）。
  * 先删掉 path 含 "pytest-of-" 的测试残留行。
  * 导回后重建 works_fts，并 PRAGMA quick_check。
  * 面板侧随后重启/强制重扫即可补齐备份之后新增的作品。
"""
import glob
import os
import sqlite3
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUR = os.path.join(APP_DIR, "meta.db")
BACKUP_DIR = os.path.join(APP_DIR, "backups")
COLS_W = ("key, group_name, name, path, size, mtime, pages, kind, circle, bare,"
          " added_at, seen_at, sha1")


def latest_backup():
    cands = sorted(glob.glob(os.path.join(BACKUP_DIR, "meta_*.db")))
    return cands[-1] if cands else None


def main(argv):
    """入口：定位备份 → 清测试残留 → 导回三张派生表 → 重建 FTS → 校验。

    3.7.43 结构：三个步骤各自独立（`_clean_pytest_junk` / `_import_rows` /
    `_rebuild_fts`），main 只做编排（原 56 行）。
    """
    bak = argv[1] if len(argv) > 1 else latest_backup()
    if not bak or not os.path.isfile(bak):
        print("找不到备份（backups/meta_*.db）", file=sys.stderr)
        return 2
    print("当前库:", CUR)
    print("备份库:", bak)

    con = sqlite3.connect(CUR, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    c = con.cursor()

    def cnt(t):
        return c.execute("SELECT count(*) FROM %s" % t).fetchone()[0]

    print("before: works=%d authors=%d tags=%d" %
          (cnt("works"), cnt("work_authors"), cnt("work_tags")))
    _clean_pytest_junk(c)
    _import_rows(con, c, bak, cnt)
    _rebuild_fts(con, c, cnt)
    print("integrity:", c.execute("PRAGMA quick_check").fetchone()[0])
    con.close()
    return 0


def _clean_pytest_junk(c):
    """1) 清测试残留：pytest basetemp 造的 works 行及其作者/标签从属。"""
    junk = c.execute("SELECT count(*) FROM works WHERE path LIKE '%pytest-of-%'").fetchone()[0]
    print("pytest 残留 works 行: %d" % junk)
    c.execute("DELETE FROM work_authors WHERE key IN "
              "(SELECT key FROM works WHERE path LIKE '%pytest-of-%')")
    c.execute("DELETE FROM work_tags WHERE key IN "
              "(SELECT key FROM works WHERE path LIKE '%pytest-of-%')")
    c.execute("DELETE FROM works WHERE path LIKE '%pytest-of-%'")


def _import_rows(con, c, bak, cnt):
    """2) 导回（跨库 ATTACH 在本机 WAL 下会被锁，改为读出后 executemany）；
    只 INSERT OR IGNORE，冲突行以当前库为准。"""
    src = sqlite3.connect("file:%s?mode=ro" % bak.replace("\\", "/"), uri=True)
    rows_w = src.execute("SELECT %s FROM works" % COLS_W).fetchall()
    rows_a = src.execute("SELECT key, author FROM work_authors").fetchall()
    rows_t = src.execute("SELECT key, type, name FROM work_tags").fetchall()
    src.close()

    c.executemany("INSERT OR IGNORE INTO works(%s) VALUES(%s)"
                  % (COLS_W, ",".join("?" * len(COLS_W.split(",")))), rows_w)
    c.executemany("INSERT OR IGNORE INTO work_authors(key, author) VALUES(?,?)", rows_a)
    c.executemany("INSERT OR IGNORE INTO work_tags(key, type, name) VALUES(?,?,?)", rows_t)
    con.commit()
    print("restored: works+%d authors+%d tags+%d" % (len(rows_w), len(rows_a), len(rows_t)))
    print("after:  works=%d authors=%d tags=%d" %
          (cnt("works"), cnt("work_authors"), cnt("work_tags")))


def _rebuild_fts(con, c, cnt):
    """3) FTS 重建：works_fts 由 works/作者/标签/社团拼接而成，导回后必须整体重打。"""
    c.execute("DELETE FROM works_fts")
    c.execute("INSERT INTO works_fts(key, title, authors, tags, circle)"
              " SELECT w.key, w.name,"
              " IFNULL((SELECT GROUP_CONCAT(a.author,' ') FROM work_authors a WHERE a.key=w.key),''),"
              " IFNULL((SELECT GROUP_CONCAT(t.name,' ') FROM work_tags t WHERE t.key=w.key),''),"
              " IFNULL(w.group_name,'')"
              " FROM works w")
    con.commit()
    print("fts: %d" % cnt("works_fts"))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
