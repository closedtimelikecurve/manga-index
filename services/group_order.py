# -*- coding: utf-8 -*-
"""services/group_order.py —— 社团「最近入库」记账与排序（3.6.151 从 scan.py 拆出）。

为什么单独成模块：`services/scan.py` 有效代码已顶到 400 行预算（拆出前 419 行），
而这里四件事彼此自洽、且与"扫描文件系统"不是一回事——它们只管**排序语义**：

  * `_group_arrival`  维护每个社团的"最近入库"时间（只有新增作品才前进）；
  * `_arrival_seed`   初始化基准：DB 里的 `works.added_at`，不是目录创建时间；
  * `_groups_prune`   社团消失后清掉它的记录，别留垃圾状态；
  * `sort_groups`     `/api/library?sort=&order=` 的服务端排序（与前端同一套语义）。

历史教训（2026-10-27 用户报障"最近入库的排序绝对出问题了"）：旧实现用**目录创建时间**
做初始化基准，而导入新作品根本不推进目录 ctime，结果 742/742 个社团的 updatedAt 恒等于
createdAt，「最近入库」与「创建时间」排出来一模一样。现在基准取 DB 的 added_at。
"""
import time

from panel.host import h


def group_arrival(name, works, created, content_mtime):
    """「最近入库」时间 —— 只有**新增作品**才会把它推到现在。

    判据是"该社团的作品数量有没有增加"，而不是作品内容的修改时间：
      * 只改作品文件内容 / 整包重写（如删首页图片的临时文件替换）/ 删作品 / 改名 →
        数量没涨 → 时间不动（用户明确要求：只改了作品文件不该让社团跑到上面去）；
      * 新增一部作品（导入、爬虫下载、复制、从别处移入，任何途径）→ 数量上涨 → 时间 = 现在。
    首次见到该社团（索引里没有记录）时用 `_arrival_seed`：DB 里最新作品的 added_at，
    而不是档案创建时间（见模块注释里的历史事故）。
    记录持久化在 library_index.json 的 "groups" 里（{社团: {"n": 作品数, "at": 入库时间}}）。
    """
    with h().INDEX_LOCK:
        bucket = h().state.index.setdefault("groups", {})
        prev = bucket.get(name)
        n = len(works)
        if not isinstance(prev, dict) or "at" not in prev:
            at = _arrival_seed(name, created, content_mtime)
        elif n > int(prev.get("n") or 0):
            at = time.time()
        else:
            at = float(prev.get("at") or 0.0) or _arrival_seed(name, created, content_mtime)
        bucket[name] = {"n": n, "at": at}
        return at


def _arrival_seed(name, created, content_mtime):
    """「最近入库」时间的初始化值（索引里还没有这个社团时）。

    **首选 DB 里该社团最新一部作品的 `added_at`**（首次入库时间，db_sync 盖的章，
    重写内容/洗版不推进）——全库唯一一处"作品什么时候进的库"的权威记录。
    DB 里没有记录时（首扫、或作品尚未同步进 DB）退回作品内容 mtime，最后才用档案创建时间。
    """
    try:
        v = h().meta.group_last_added(name)
    except Exception:                       # DB 未建表/未同步：不阻断扫描
        h().log.exception("读取社团「最近入库」基准失败（DB）")
        v = 0
    if v:
        return float(v)
    return float(content_mtime or created or 0.0)


def groups_prune(names):
    """清理已消失社团的入库记录（目录被删/改名后不再占用状态）。"""
    with h().INDEX_LOCK:
        bucket = h().state.index.setdefault("groups", {})
        for k in [k for k in bucket if k not in names]:
            bucket.pop(k, None)


def sort_groups(groups, mode="updated", order="desc"):
    """社团排序：updated=最近**入库新作品**的时间（默认，只有作品数量增加才前进）/
    created=档案创建时间 / count=作品数量 / size=占用空间。
    默认由新到旧、由多到少（desc）；order="asc" 即倒序（由旧到新 / 由少到多）。

    3.6.151：**删掉 touched（最近更新）档**。它与 updated 只差"洗版算不算入库"，
    两档并排放在同一个排序条里，用户实际分不清哪个才是"我刚下载的排在前面"，
    明确要求彻底移除（前端档位、后端分支、文案一并吃掉；收到 touched 也按 updated 处理，
    旧前端缓存不会因此排错）。

    名称升序作为补位：先按名称排一遍再稳定排序，所以同值时（含倒序）仍按名称升序，
    列表不会在刷新之间跳来跳去。

    3.6.154：时间档改为**按整秒比较**。原先补位只在时间戳完全相等时生效，可首扫同一批
    新社团的「最近入库」取 now()，彼此只差几微秒——等于永不相等，兜底形同虚设，
    顺序随扫描顺序抖（`test_corrupt_index_falls_back` 的顺序依赖就是这么暴露出来的）。
    取整后同一秒内按名称升序，同一份文库两次全量扫描得到同一个顺序。
    """
    if mode == "created":
        key = lambda g: int(round(g.get("created_at", 0.0)))
    elif mode == "count":
        key = lambda g: len(g["works"])
    elif mode == "size":
        key = lambda g: g.get("total_bytes", 0)
    else:
        key = lambda g: int(round(g.get("updated_at", g.get("cover_mtime", 0.0))))
    out = sorted(groups, key=lambda g: h().natural_key(g["name"]))
    out.sort(key=key, reverse=(str(order).lower() != "asc"))
    return out