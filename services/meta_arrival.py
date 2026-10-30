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


def group_seed(group_name):
    """「最近入库」初始化要用的三条证据：最新 `added_at` / 那一行的 `mtime` / 分区首次登记时间。

    为什么要单独给一条查询（3.6.169）：`added_at` 在**首建库回填**时是直接抄文件 mtime 的
    （`services/db_sync._collect_group_works` 的 `initial` 分支），这时它只说明"文件内容
    是什么时候生成的"，说明不了"什么时候进的库"。实测 2026-10-29 用户报障的三个新分区：

    | 分区 | 分区首次登记 | added_at | 文件 mtime |
    |---|---|---|---|
    | あるるも | 10-29 14:20 | 10-22 13:18 | 10-22 13:18 |
    | 漫画喫茶瀬戸 | 10-29 01:00 | 10-22 12:44 | 10-22 12:44 |
    | スミヅミ | 10-29 00:45 | 10-22 12:42 | 10-22 12:42 |

    前两列 `added_at == mtime`，正是回填的形状；这三个分区是那天新建目录、把老作品移进来
    （db_sync 的 `_adopt_work_path` 会保留 added_at），于是「最近入库」卡在 10-22，
    排到了 10-25 的 WASABI 后面——用户看到的"日期不太对"就是这里。

    对照可信样本 WASABI（added_at 10-25 11:35 ≠ mtime 10-25 12:49）可见：
    **`added_at == mtime` 就是"这条时间没有独立见证"的记号**，调用方据此决定要不要拿
    `circles.created_at`（分区第一次被扫描到的时间，`INSERT OR IGNORE` 只写一次、
    复制文库也不会被改写）来兜底。
    """
    with meta._LOCK:
        c = meta._connect()
        row = c.execute("SELECT added_at, mtime FROM works WHERE group_name=? "
                        "ORDER BY added_at DESC LIMIT 1", (group_name,)).fetchone()
        cir = c.execute("SELECT created_at FROM circles WHERE name=?", (group_name,)).fetchone()
    return {
        "added": int(row[0] or 0) if row else 0,
        "mtime": int(row[1] or 0) if row else 0,
        "born": int(cir[0] or 0) if cir else 0,
    }


def author_work_count(author):
    """某画师名下有**几部**作品（work_authors 实时计数，3.6.166）。

    用途是给"词条救援"降噪：孤词条回头认库内画师时，候选至少要有 2 部独立历史——
    只有一条记录的"画师"往往正是上一次误判的产物，认了它等于把错误复制一遍。
    不放进内存词条库：那是启动时的快照，误判写进 work_authors 后快照会把它当成
    真画师，形成闭环。
    """
    try:
        with meta._LOCK:
            c = meta._connect()
            return int(c.execute("SELECT COUNT(*) FROM work_authors WHERE author=?",
                                 (str(author or ""),)).fetchone()[0])
    except Exception:                                   # noqa: BLE001
        return 0
