# -*- coding: utf-8 -*-
"""services/db_sync.py —— 扫描结果落库（3.6.77 从 meta_store 拆出）。

一条流水线，五个阶段（顺序即语义，改动前务必先读 tests/test_meta_snapshot.py）：
  收集 `_scan_collect` → works 差异 `_scan_sync_works` → 派生表差异 `_scan_sync_derived`
  → 修剪闸门 `_scan_prune` → FTS 增量 `_scan_fts`；`sync_scan` 只做编排与事务边界。

**三条不变量**
  1. 骤减闸门：库中 ≥50 行而本次 <10%（且 <20 条）时**只 upsert 不删**——2026-10-13
     曾把 works 2263 行删到 1 行，这条闸门就是那次事故的产物；
  2. 用户附加事实表（reading / ratings / collection_items）绝不被扫描删除；
  3. 同一物理 path 只落一行（works.path UNIQUE），key 变化时整行连同派生表迁移。

调用方式不变：`meta.sync_scan(groups)` 由 meta_store 的 PEP 562 `__getattr__` 转发；
`monkeypatch.setattr(meta_store, "DB_PATH", ...)` 仍生效（连接取 `meta._connect()`）。
"""
import logging
import os

import meta_store as meta


def _scan_collect(c, groups):
    """扫描阶段一：登记 circles，收集去重后的作品清单，返回 (seen, wanted)。

    同一物理 path 可能重复出现（合作社团作品被挂到多个子社团），works.path 唯一约束下
    只能落一行，去重保留首个（社团交叉引用由 library_index.json 的 groups 承担）；
    3.6.11 起同名作品跨社团撞 key（主键）时同理。
    """
    seen, wanted = [], []
    seen_paths, seen_keys = set(), set()
    for g in groups:
        gname = str(g.get("name") or "")
        if not gname:
            continue
        c.execute("INSERT OR IGNORE INTO circles(name, created_at) VALUES(?,?)",
                  (gname, int(g.get("created_at") or 0)))
        _collect_group_works(g, gname, seen, wanted, seen_paths, seen_keys)
    return seen, wanted


def _collect_group_works(g, gname, seen, wanted, seen_paths, seen_keys):
    """一个社团下的作品：按真实归档名算落库 key，去重后进 wanted。"""
    for w in g.get("works") or []:
        # 3.6.11 社团别名：并入正名社团展示的作品，仍按**真实所在社团**落 key/group_name
        # （w["_group"]，由 app._merge_alias_circles 打标）。否则别名一登记 key 就从
        # 「社团B/作品二」变成「社团A/作品二」，既撞 works.path 唯一约束，又把阅读进度/收藏甩在身后。
        owner = str(w.get("_group") or gname)
        key = owner + "/" + str(w.get("name") or "")
        if key.endswith("/"):
            continue
        path = str(w.get("path") or "")
        if path in seen_paths or key in seen_keys:
            continue
        seen_paths.add(path)
        seen_keys.add(key)
        seen.append(key)
        mtime0 = int(float(w.get("mtime") or 0))
        added0 = mtime0 or int(float(g.get("updated_at") or 0))
        wanted.append((key, owner, w, added0))


def _scan_sync_works(c, wanted, seen):
    """扫描阶段二：works 行只写差异（新行 INSERT；旧行逐字段比对后按需 UPDATE）。

    返回 fts_dirty（需要重建 FTS 行的 key 集合）。
    """
    existing = _existing_works(c, seen)
    fts_dirty = set()
    for key, gname, w, added in wanted:
        path = str(w.get("path") or "")
        mtime = int(float(w.get("mtime") or 0))
        fields = (gname, str(w.get("name") or ""), path, _archive_size(w, path), mtime,
                  int(w.get("pages") or 0), str(w.get("kind") or ""),
                  str(w.get("circle") or ""), str(w.get("bare") or ""))
        old, adopted = existing.get(key), False
        if old is None and path:
            old, adopted = _adopt_work_path(c, key, path, existing)
        if old is None:
            c.execute("INSERT INTO works(key, group_name, name, path, size, mtime,"
                      " pages, kind, circle, bare, added_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (key,) + fields + (added,))
            fts_dirty.add(key)
        elif old != fields:
            # mtime 变了 → 内容变了 → 作废已缓存的 sha1（与旧版全量 UPDATE 语义一致）
            c.execute("UPDATE works SET group_name=?, name=?, path=?, size=?, mtime=?, pages=?,"
                      " kind=?, circle=?, bare=?,"
                      " sha1=CASE WHEN works.mtime=? THEN works.sha1 ELSE NULL END WHERE key=?",
                      fields + (mtime, key))
            fts_dirty.add(key)
        if adopted:
            fts_dirty.add(key)      # key 变过 → FTS 行的 key 必须重建
    return fts_dirty


def _existing_works(c, seen):
    """批量取本轮仍有效的 works 行（去掉 key 列，便于与 fields 直接比较）。"""
    existing = {}
    if not seen:
        return existing
    for chunk in meta._in_chunks(seen):
        q = ",".join("?" * len(chunk))
        for r in c.execute("SELECT key, group_name, name, path, size, mtime, pages,"
                           " kind, circle, bare FROM works WHERE key IN (%s)" % q, chunk):
            existing[r[0]] = r[1:]
    return existing


def _archive_size(w, path):
    """压缩包作品取文件大小（读不到给 -1，与历史行为一致）；文件夹作品恒 -1。"""
    if w.get("kind") != "archive" or not path:
        return -1
    try:
        return os.path.getsize(path)
    except OSError:
        return -1


def _adopt_work_path(c, key, path, existing):
    """同一物理文件此前挂在别的 key 下（圈子归并导致 key 变化、path 不变）。

    直接 INSERT 会撞 works.path UNIQUE 令整轮事务回滚，故把整行连同派生事实表
    （阅读进度/收藏/评分/作者/标签/FTS）迁到新 key，保留用户附加数据。
    返回 (新行|None, 是否发生了迁移)。
    """
    other = c.execute("SELECT key FROM works WHERE path=?", (path,)).fetchone()
    if not other or other[0] == key:
        return None, False
    old_key = other[0]
    for table in ("works", "work_authors", "work_tags", "reading", "ratings",
                  "collection_items", "works_fts"):
        c.execute("UPDATE %s SET key=? WHERE key=?" % table, (key, old_key))
    existing.pop(old_key, None)
    row = c.execute("SELECT key, group_name, name, path, size, mtime, pages,"
                    " kind, circle, bare FROM works WHERE key=?", (key,)).fetchone()
    return (row[1:] if row else None), True


def _scan_sync_derived(c, wanted, seen, fts_dirty):
    """扫描阶段三：work_authors / work_tags 只写差异；fts_dirty 就地更新。"""
    have_authors, have_tags = _existing_derived(c, seen)
    for key, gname, w, added in wanted:
        _sync_authors(c, key, w, have_authors, fts_dirty)
        _sync_tags(c, key, w, have_tags, fts_dirty)


def _existing_derived(c, seen):
    """批量取既有作者/标签行（按 key 分组成 set）。"""
    have_authors, have_tags = {}, {}
    if not seen:
        return have_authors, have_tags
    for chunk in meta._in_chunks(seen):
        q = ",".join("?" * len(chunk))
        for k, a in c.execute("SELECT key, author FROM work_authors"
                              " WHERE key IN (%s)" % q, chunk):
            have_authors.setdefault(k, set()).add(a)
        for k, t, n in c.execute("SELECT key, type, name FROM work_tags"
                                 " WHERE key IN (%s)" % q, chunk):
            have_tags.setdefault(k, set()).add((t, n))
    return have_authors, have_tags


def _sync_authors(c, key, w, have_authors, fts_dirty):
    """作者行对账：删多、按列表序补缺（rowid 序即展示序）。"""
    authors = w.get("personals")
    if authors is None:
        authors = [w.get("personal")] if w.get("personal") else []
    authors_norm = list(dict.fromkeys(str(x) for x in authors if str(x)))
    want_a = set(authors_norm)
    have_a = have_authors.get(key, set())
    if want_a == have_a:
        return
    for a in have_a - want_a:
        c.execute("DELETE FROM work_authors WHERE key=? AND author=?", (key, a))
    for a in authors_norm:
        if a in want_a - have_a:
            c.execute("INSERT OR IGNORE INTO work_authors(key, author) VALUES(?,?)", (key, a))
    fts_dirty.add(key)


def _sync_tags(c, key, w, have_tags, fts_dirty):
    """标签行对账：解析产出 ∪ 用户手动 original（折叠到正名后），删多补缺。"""
    tags_norm = list(dict.fromkeys((str(t), str(n)) for t, n in (w.get("tags") or [])
                                   if str(t) and str(n)))
    # 3.6.19：手动「添加原作」写进的 original 标签是用户附加事实（见 originals_add），
    # 重扫不得删除；解析器产出的 original 本就在 tags_norm 内，殊路同归不冲突。
    #
    # 3.6.41 用户报障（"改名之后旧分区依旧复活"）：此前把**所有**既有 original 行
    # 无条件放行，于是分区改名留下的旧名标签永远不会消失；而 old 通常还在内置名单里，
    # 解析器继续产出旧名，旧分区就常驻列表。更糟的是同一作品同时挂新旧两行，
    # 两个分区各算一部（实测 95 + 94）。
    # 修法：既有 original 行先按**别名链折叠到正名**再对账——别名链外的 manual
    # 标签原样保留（用户附加事实语义不变），别名链上的旧行被折成正名并去重。
    have_t = have_tags.get(key, set())
    manual_orig = {(t, meta._fold_original(n)) for t, n in have_t if t == "original"}
    want_t = set(tags_norm) | manual_orig
    if want_t == have_t:
        return
    for row in have_t - want_t:
        c.execute("DELETE FROM work_tags WHERE key=? AND type=? AND name=?", (key,) + row)
    # 遍历 want_t - have_t（而不是 tags_norm）：折叠后的 manual 正名可能不在解析产出里，
    # 也要补插，否则作品会被"折掉旧标签却没写新标签"。
    for row in want_t - have_t:
        c.execute("INSERT OR IGNORE INTO work_tags(key, type, name) VALUES(?,?,?)", (key,) + row)
    fts_dirty.add(key)


def _scan_prune(c, seen):
    """扫描阶段四：删除兜底闸门 + 派生表修剪。返回 removed（被删除的 key 列表）。

    骤减闸门（3.6.10）：本次扫描相对库中现有记录骤减（库里 ≥50 条而本次不足其 10%、
    且少于 20 条）→ 判定为异常扫描（文库根临时不可见/外接盘掉线/扫描被中断/跨线程拿错库…），
    **只 upsert 不删**。正常删作品是逐步发生的，永远不会一轮掉九成；而「整表清空」一旦
    发生就是不可逆事故（2026-10-13 实测把 works 2263 行删到 1 行）。代价只是暂留若干
    幽灵行，下一轮正常扫描即清理。用户附加事实表绝不动。
    """
    existing_total = c.execute("SELECT count(*) FROM works").fetchone()[0]
    prune = not (existing_total >= 50 and len(seen) < max(20, existing_total // 10))
    if not prune:
        logging.getLogger("meta_store").warning(
            "sync_scan 拒绝派生表修剪：库中 %d 行，本次扫描仅 %d 行（疑似异常扫描，只更新不删）",
            existing_total, len(seen))

    # 派生表修剪：扫描里已消失的作品行删除（用户附加事实表绝不动）
    removed = []
    if prune:
        c.execute("CREATE TEMP TABLE IF NOT EXISTS _seen(key TEXT PRIMARY KEY)")
        c.execute("DELETE FROM _seen")
        c.executemany("INSERT OR IGNORE INTO _seen(key) VALUES(?)", [(k,) for k in seen])
        removed = [r[0] for r in c.execute(
            "SELECT key FROM works WHERE key NOT IN (SELECT key FROM _seen)")]
        c.execute("DELETE FROM works WHERE key NOT IN (SELECT key FROM _seen)")
        c.execute("DELETE FROM work_authors WHERE key NOT IN (SELECT key FROM _seen)")
        c.execute("DELETE FROM work_tags WHERE key NOT IN (SELECT key FROM _seen)")
        c.execute("DROP TABLE IF EXISTS _seen")
    return removed


def _scan_fts(c, seen, fts_dirty):
    """扫描阶段五：FTS 增量更新（3.3.0）。只重建变化 key；大比例变更（首填/词条库变化/
    清空）仍走全量重建，避免逐 key 扫 FTS 的 O(n²) 退化。"""
    if len(fts_dirty) > max(len(seen) // 2, 64):
        meta._fts_rebuild(c)
    elif fts_dirty:
        for k in fts_dirty:
            c.execute("DELETE FROM works_fts WHERE key=?", (k,))
        for chunk in meta._in_chunks(sorted(fts_dirty)):
            q = ",".join("?" * len(chunk))
            c.execute("INSERT INTO works_fts(key, title, authors, tags, circle)"
                      " SELECT w.key, w.name,"
                      " IFNULL((SELECT GROUP_CONCAT(a.author,' ') FROM work_authors a WHERE a.key=w.key),''),"
                      " IFNULL((SELECT GROUP_CONCAT(t.name,' ') FROM work_tags t WHERE t.key=w.key),''),"
                      " IFNULL(w.group_name,'')"
                      " FROM works w WHERE w.key IN (%s)" % q, chunk)


def sync_scan(groups):
    """groups = build_group 产物列表。每次扫描后调用：
    upsert works/work_authors/work_tags + circles 登记 + FTS 增量更新 + 派生表修剪。
    3.3.0 起增量化：与库中现状逐字段比对，只写有变化的行、只重建变化 key 的 FTS 行
    （此前每轮扫描全量 DELETE/INSERT 派生表并全量重建 FTS，任何一次改名/导入都伴随
    上万条无谓写入）。首次回填（meta_kv.backfill_done 未打标）时 added_at 取历史值：
    文件 mtime，缺失则退回社团「最近入库」时间；此后新作品 added_at = 首次见到时刻。

    3.6.26：原 183 行 / 圈复杂度 67 的单体（历史事故重灾区）拆成五个具名阶段，
    本函数只负责编排顺序与事务边界，各阶段逻辑逐行等价。
    """
    with meta._LOCK:
        c = meta._connect()
        initial = meta._kv_get(c, "backfill_done") != "1"
        seen, wanted = _scan_collect(c, groups)
        fts_dirty = _scan_sync_works(c, wanted, seen)
        _scan_sync_derived(c, wanted, seen, fts_dirty)
        fts_dirty.update(_scan_prune(c, seen))
        _scan_fts(c, seen, fts_dirty)
        c.commit()
        if initial:
            meta._kv_set(c, "backfill_done", "1")
            c.commit()
