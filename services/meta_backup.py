# -*- coding: utf-8 -*-
"""services/meta_backup.py —— meta.db 的时间机器与全量导出（3.6.84 从 meta_store 拆出）。

为什么拆：`meta_store` 913 有效代码行 / 1235 物理行，已远超 400/800 预算（见
docs/engineering-discipline.md §3）。这一簇（快照/保留策略/列表/恢复/导出）在
`meta_store` 内部**只被外部调用**，是天然的搬移单元。

调用方式不变：`meta.snapshot()` / `meta.backup_list()` 等由 meta_store 的 PEP 562
`__getattr__` 惰性转发到这里；`monkeypatch.setattr(meta_store, "DB_PATH"/"BACKUP_DIR")`
仍然生效（连接与目录都由 `meta.*` 现读，不在导入期取值）。
"""
import logging
import os
import sqlite3
import time
import traceback

import meta_store as meta

log = logging.getLogger(__name__)

_SNAPSHOT_KEEP = 30          # 保留最近 30 份 + 每日首份
_SNAPSHOT_MIN_INTERVAL = 60  # 非强制快照节流（秒）：批量操作（一键归档等）不刷屏


def snapshot(note="", force=False):
    """meta.db 快照到 backups/（sqlite backup API 原子复制，WAL 内容一并落盘）。
    非强制快照 60 秒节流：批量操作（一键归档/导入流水线）不产生备份风暴。"""
    with meta._LOCK:
        c = meta._connect()
        try:
            if not force:
                last = float(meta._kv_get(c, "last_snapshot_at") or 0)
                if time.time() - last < _SNAPSHOT_MIN_INTERVAL:
                    return None
            os.makedirs(meta.BACKUP_DIR, exist_ok=True)
            stamp = time.strftime("%Y%m%d%H%M%S")
            fname = "meta_%s.db" % stamp
            dest = os.path.join(meta.BACKUP_DIR, fname)
            i = 0
            while os.path.exists(dest):
                i += 1
                fname = "meta_%s_%02d.db" % (stamp, i)
                dest = os.path.join(meta.BACKUP_DIR, fname)
            c.commit()
            dst = sqlite3.connect(dest)
            try:
                c.backup(dst)
            finally:
                dst.close()
            now = int(time.time())
            c.execute("INSERT INTO snapshots(at, file, note) VALUES(?,?,?)", (now, fname, note))
            meta._kv_set(c, "last_snapshot_at", repr(time.time()))
            c.commit()
            _retention(c)
            return fname
        except Exception:
            try:
                c.rollback()
            except Exception:
                pass
            return None


def _retention(c):
    """保留最近 N 份 + 每日首份，超量连文件带记录一起清。"""
    try:
        rows = c.execute("SELECT file FROM snapshots ORDER BY at DESC, id DESC").fetchall()
        files = [r[0] for r in rows]
        keep = set(files[:_SNAPSHOT_KEEP])
        first_of_day = {}
        for f in reversed(files):                 # 旧 → 新：同日最早的那份留下
            day = str(f)[5:13]                    # meta_YYYYMMDD…（文件名即时间戳）
            first_of_day[day] = f
        keep.update(first_of_day.values())
        for f in files:
            if f not in keep:
                c.execute("DELETE FROM snapshots WHERE file=?", (f,))
                try:
                    os.unlink(os.path.join(meta.BACKUP_DIR, f))
                except OSError:
                    pass
    except Exception:
        # 清理失败不该让本次快照失败，但"旧快照堆积"必须留痕
        log.warning("快照保留策略执行失败（旧快照可能无限堆积）：%s", traceback.format_exc())


def backup_list():
    """目录实况为准（含恢复后遗留的孤儿快照），note 从 snapshots 表尽力补全。"""
    with meta._LOCK:
        c = meta._connect()
        notes = {r[0]: (r[1], r[2]) for r in
                 c.execute("SELECT file, at, note FROM snapshots")}
        out = []
        try:
            names = os.listdir(meta.BACKUP_DIR)
        except OSError:
            names = []
        for n in sorted(names, reverse=True):
            if not (n.startswith("meta_") and n.endswith(".db")):
                continue
            p = os.path.join(meta.BACKUP_DIR, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            at, note = notes.get(n, (int(st.st_mtime), ""))
            out.append({"file": n, "at": at, "size": st.st_size, "note": note})
        return out


def backup_restore(fname):
    """恢复快照：先快照当前（可撤销），再原子替换 meta.db。返回 (ok, message)。"""
    fname = os.path.basename(str(fname or ""))
    if not fname.startswith("meta_") or not fname.endswith(".db"):
        return False, "非法快照文件名"
    src = os.path.join(meta.BACKUP_DIR, fname)
    if not os.path.isfile(src):
        return False, "快照不存在：" + fname
    with meta._LOCK:
        c = meta._connect()
        pre = snapshot("恢复前自动快照", force=True)
        c.close()
        meta.close()                  # 置空 _CONN/_OPEN_PATH 并清缓存，随后按新文件重开
        try:
            os.replace(src, os.path.abspath(meta.DB_PATH))
            for suf in ("-wal", "-shm"):
                try:
                    os.unlink(os.path.abspath(meta.DB_PATH) + suf)
                except OSError:
                    pass
        except OSError as e:
            return False, "恢复失败：" + str(e)
        c2 = meta._connect()
        # 恢复前那份快照的记录随旧库被替换掉了：在新库里补记，保证可再撤销
        if pre:
            c2.execute("INSERT INTO snapshots(at, file, note) VALUES(?,?,?)",
                       (int(time.time()), pre, f"恢复前自动快照（被恢复：{fname}）"))
            c2.commit()
        return True, "已恢复快照：" + fname + (f"（恢复前状态已存为 {pre}）" if pre else "")


def export_json():
    """全量元数据 JSON 导出（灾备兜底，可离开本系统）。"""
    with meta._LOCK:
        c = meta._connect()
        tables = {}
        for t in ("works", "work_authors", "work_tags", "author_aliases", "artist_circles",
                  "circles", "reading", "ratings", "collections", "collection_items", "meta_kv"):
            cols = [d[1] for d in c.execute("PRAGMA table_info(%s)" % t)]
            tables[t] = [dict(zip(cols, row)) for row in c.execute("SELECT * FROM %s" % t)]
        return {"exported_at": int(time.time()), "schema": 1, "tables": tables}
