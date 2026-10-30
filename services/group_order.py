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


def group_arrival(name, works, created, content_mtime, commit=True, real_dir=True):
    """「最近入库」时间 —— 只有**新增作品**才会把它推到现在。

    3.6.166：改成 **max(上一轮的值, DB 里该社团最新 added_at)**。

    原实现只在"作品数量增加"时推进，数量没涨就原样沿用——这条启发式有两个漏口：
      * 作品被**改名/替换**（key 变了、数量不变）时新时间进不来；
      * DB 里 added_at 明明更新了（用户报障实测：こけもも 库内最新入库 10-22，
        面板仍停在 09-06），只要数量没变就永远不推进。

    `added_at` 是 db_sync 首次见到该作品时盖的章，重写内容/洗版不推进，本身就是
    "作品什么时候进的库"的权威记录——直接拿它当下限，既准确又不违反"只改内容不该前进"。
    DB 里还没有记录时（首扫、或本轮的扫描结果尚未同步进 DB）退回作品内容 mtime。

    记录持久化在 library_index.json 的 "groups" 里（{社团: {"n": 作品数, "at": 入库时间}}）。

    `commit=False` = 只算出临时值、不记账：扫描阶段（build_group）用它，因为那时
    `sync_scan` 还没跑，本轮新入库的作品在 DB 里还没有 `added_at`，只能退回文件 mtime——
    而 mtime 说明不了"什么时候进的库"（从别处复制 / 下载工具保留服务器时间都会很旧）。
    真正的记账在 `_apply_arrivals`：DB 同步**之后**再算一次，那时 added_at 已经就位。

    `real_dir` = 这是不是一个**真实的归档目录**（不是根目录散包拼出来的虚拟社团）。
    只有真实目录才谈得上"分区成立时间"——散包的 `created_at` 取的是作品文件 ctime，
    拿它兜底等于又退回"内容时间"，正是 3.6.151 修掉的病。
    """
    with h().INDEX_LOCK:
        bucket = h().state.index.setdefault("groups", {})
        prev = bucket.get(name)
        n = len(works)
        seed, born_used = _arrival_seed(name, created, content_mtime, works, real_dir)
        if not isinstance(prev, dict) or "at" not in prev:
            at = seed                               # 首次见到该社团：DB 优先，退回内容时间
        elif n > int(prev.get("n") or 0):
            # 作品数涨了 = 确实多了作品。推进值取 DB 里的 `added_at`（首次入库的章），
            # 而不是 now()：既比 now() 准（能反映"这部其实是两天前下的、今天才扫描到"），
            # 也不会像 mtime 那样被洗版/重写带跑。
            at = max(float(prev.get("at") or 0.0), seed)
        else:
            # 数量没涨：改名 / 洗版 / 删除都不该让社团跑到上面去（用户 3.6.111 的明确要求）。
            at = float(prev.get("at") or 0.0) or seed
        # 3.6.169：**只有"分区成立时间"这一种更权威的证据**出现、且晚于记账时才纠正。
        # 记账一旦写下就没人再看它——首轮扫描把回填的文件时间当成入库时间记下来之后，
        # 数量不变就永远走上面那个 else，错值被永久冻住（实测「漫画喫茶瀬戸」停在 10-22，
        # 而分区是 10-29 才成立的）。限定 born_used 是为了不把洗版/改名再放进来。
        if born_used and seed > at:
            at = seed
        if commit:
            bucket[name] = {"n": n, "at": at}
        return at


def _arrival_seed(name, created, content_mtime, works=(), real_dir=True):
    """「最近入库」时间的下限（索引里还没有这个社团时就是全部依据）。

    **首选 DB 里该社团最新一部作品的 `added_at`**（首次入库时间，db_sync 盖的章，
    重写内容/洗版不推进）——全库唯一一处"作品什么时候进的库"的权威记录。

    3.6.166：查 DB 要用**真实归档名**（DB 的 works.group_name 是目录名），而 `name`
    是词条归一后的社团名——归并出来的虚拟社团两者不同，只用 name 查永远落空。
    所以把作品上记的 `_group` 一并拿来查，取最大值。

    3.6.169：`added_at == mtime` 时它**不可信**。首建库回填是把文件 mtime 直接抄进
    `added_at` 的（见 `services/db_sync._collect_group_works`），两个值相等就等于
    "这条时间没有独立见证"，只说明文件内容生成于何时。真实症状：用户 10-29 新建
    三个分区、把 10-22 下好的老作品移进去，`_adopt_work_path` 保留了 added_at，
    于是这三个分区停在 10-22、排在 10-25 的 WASABI 后面。此时改用
    **分区首次登记时间**（`circles.created_at`，首次扫描写入一次、复制文库不会改写）
    与它取较大者：分区今天才成立，就该记今天。

    返回 `(时间, born_used)`：`born_used=True` 表示这个值**被"分区首次登记时间"推后过**
    （即 `added_at` 只是回填抄写的文件时间，而分区其实是后来才成立的）。调用方靠它
    决定要不要纠正已经写下的历史记账——只有这一种证据足够权威，洗版/改名都不算。
    """
    names = {name}
    for w in works:
        g = w.get("_group")
        if g:
            names.add(g)
    best, best_mtime, born = 0, 0, 0
    for g in names:
        try:
            ev = h().meta.group_seed(g)
        except Exception:                       # DB 未建表/未同步：不阻断扫描
            h().log.exception("读取社团「最近入库」基准失败（DB）")
            continue
        if ev["added"] > best:
            best, best_mtime = ev["added"], ev["mtime"]
        if ev["born"] > born:
            born = ev["born"]
    if best:
        # added_at 与文件 mtime 不等 = 它是"首次见到的时刻"，照原样用（3.6.151 的修复）。
        if best != best_mtime:
            return float(best), False
        # 相等 = 回填抄写，没有独立见证 → 用分区成立时间兜底。**只对真实目录**：
        # 散包虚拟社团的 created 本身就是作品文件 ctime，拿它兜底等于退回内容时间。
        if real_dir and born > best:
            return float(born), True
        return float(best), False
    return float(content_mtime or created or 0.0), False


def groups_prune(names):
    """清理已消失社团的入库记录（目录被删/改名后不再占用状态）。"""
    with h().INDEX_LOCK:
        bucket = h().state.index.setdefault("groups", {})
        for k in [k for k in bucket if k not in names]:
            bucket.pop(k, None)


def sort_groups(groups, mode="updated", order="desc"):
    """社团排序：updated=最近**入库新作品**的时间（默认，只有作品数量增加才前进）/
    created=档案创建时间 / count=作品数量。
    默认由新到旧、由多到少（desc）；order="asc" 即倒序（由旧到新 / 由少到多）。

    3.6.151：**删掉 touched（最近更新）档**。它与 updated 只差"洗版算不算入库"，
    两档并排放在同一个排序条里，用户实际分不清哪个才是"我刚下载的排在前面"，
    明确要求彻底移除（前端档位、后端分支、文案一并吃掉；收到 touched 也按 updated 处理，
    旧前端缓存不会因此排错）。

    3.6.166：**删掉 size（文件大小）档**。用户明确要求"作品大小排序只需要在分区内部
    存在即可，社团排序不需要这个"——查重是逐部作品比体积，把整个社团按总字节排一遍
    没有任何使用场景。收到 size 也按 updated 处理（旧前端缓存不会因此排错）。

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
    else:
        key = lambda g: int(round(g.get("updated_at", g.get("cover_mtime", 0.0))))
    out = sorted(groups, key=lambda g: h().natural_key(g["name"]))
    out.sort(key=key, reverse=(str(order).lower() != "asc"))
    return out