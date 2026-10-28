# -*- coding: utf-8 -*-
"""services/meta_arrival.py —— 入库时间读取（3.6.151 从 meta_store 拆出）。

`meta_store.py` 有效代码已顶到 400 行预算（拆出前 405 行），而"作品什么时候进的库"
这一条支线自洽且被两处共用：

  * `works_added_at()`  全库 (key, added_at) —— 扫描后回填 state.lib 的作品字典，
    分区内"新→旧"排序用它（文件 mtime 会被删首页图之类的重写操作推进，added_at 不会）；
  * `group_last_added(group)` 某归档目录最新一部作品的入库时间 —— 社团「最近入库」
    排序的初始化基准（3.6.151 修的那个 bug 就靠它：目录创建时间不能代表入库时间）。

调用方式不变：`meta.works_added_at()` / `meta.group_last_added(...)` 由 meta_store 的
PEP 562 `__getattr__` 惰性转发到这里；连接仍由 `meta._connect()` 提供，
`monkeypatch.setattr(meta_store, "DB_PATH", ...)` 依然生效。
"""
import meta_store as meta


def works_added_at():
    """全部作品的首次入库时间 (key, added_at)（3.6.111：供 _do_scan 回填 state.lib）。

    分区内"新→旧"排序以此为准——文件 mtime 会被删首页图等重写操作推进（作品错误
    顶到"最新"），added_at 首次见到后不再变化（db_sync 的 UPDATE 不写 added_at）。"""
    with meta._LOCK:
        c = meta._connect()
        return c.execute("SELECT key, added_at FROM works WHERE added_at > 0").fetchall()


def group_last_added(group_name):
    """某个归档目录里**最新一部作品**的入库时间（秒，没有记录返回 0）。

    3.6.151：社团「最近入库」排序的初始化基准。之前的基准是目录创建时间，
    往里导入新作品并不会推进它，于是「最近入库」与「创建时间」排出来一模一样
    （实测 742/742 个社团两值相等）；added_at 是 db_sync 首次见到该作品时盖的章，
    重写内容/洗版都不推进，才是"作品什么时候进的库"的权威记录。
    单条查询在真库上约 0.07ms（742 个社团全量首扫约 55ms）。"""
    with meta._LOCK:
        c = meta._connect()
        row = c.execute("SELECT MAX(added_at) FROM works WHERE group_name=?",
                        (group_name,)).fetchone()
        return int(row[0] or 0) if row else 0