# -*- coding: utf-8 -*-
"""services/index_cache.py —— 扫描缓存与重扫调度（3.6.60 Stage7 拆出）。

`library_index.json` 缓存（含 `norm_v` 归一逻辑版本失效）、作品级局部读写、
SWR 缓存（`state.lib` + `state.rescan` single-flight）与 `_lib_touch`（变更登记：
凡搬改删文件后调用它，令下一个请求同步重扫）。
"""
import hashlib
import json
import os
import tempfile
import threading
import time

from common import ensure_dir
from panel.host import h

def _lib_touch():
    """文库数据变动（改名/归档/删除/导入/配置变更…）后调用：
    标记缓存为脏并递增修订号 rev —— 安卓端轮询 /api/library/meta 发现 rev 变了
    就自动刷新首页/社团页，从而把「面板侧改动要手动下拉才同步」的延迟压到秒级。
    3.3.0 起作废方式改为 stale-while-revalidate：旧数据继续服务，重扫在后台跑；
    （此前置 data=None，写操作后的下一个读请求要同步扛完整轮扫描才能响应。）"""
    if h().state.lib["data"] is not None:
        h().state.lib["stale"] = True          # 只在确有旧数据可服务时置脏；首扫前无数据无需 kick
        h()._kick_rescan()
    h().state.lib["rev"] = int(h().state.lib.get("rev") or 0) + 1
    return h().state.lib["rev"]

def _scan_ctx():
    """扫描上下文快照：文库根 + 元数据库路径 + 索引文件路径。
    后台重扫线程启动时会跨异步边界（线程可以随时被调度器挂起），**写盘目标必须锚定
    到扫描发起时的这套路径**：否则线程醒来时若路径已被改回（典型场景 = 测试 fixture
    teardown 撤销 monkeypatch），它手里仍是旧库的作品列表，却会往新路径写盘——
    sync_scan 的「不在本次扫描中的 key 全部删除」语义会把目标库的真实记录清空。
    3.6.10：曾因此把线上 meta.db 的 works 2263 行删到 1 行（见 2026-10-13 条目）。"""
    try:
        db = str(getattr(h().meta, "DB_PATH", "") or "")
    except Exception:
        db = ""
    return {"root": str(h().CFG.get("root") or ""), "db": db, "idx": str(h().INDEX_FILE or "")}

def _ctx_stale(ctx):
    """上下文已变 → 本次扫描的数据与当前写盘目标不匹配，必须放弃写盘。"""
    return isinstance(ctx, dict) and h()._scan_ctx() != ctx

def _kick_rescan():
    """后台静默重扫（single-flight）：文库已有数据且被标记为脏时启动一次；
    首扫未完成时不启动（由 get_library 的阻塞路径负责）。"""
    with h().LIB_LOCK:
        if h().state.rescan["pending"] or h().state.lib["data"] is None:
            return
        h().state.rescan["pending"] = True
    ctx = h()._scan_ctx()          # 3.6.10：锚定发起时的路径，线程内凭它判定能否写盘

    def _run():
        try:
            with h().SCAN_LOCK:
                try:
                    h()._do_scan(ctx=ctx)
                except Exception:
                    h().log.exception("后台重扫失败（保留旧缓存继续服务）")
        finally:
            with h().LIB_LOCK:
                h().state.rescan["pending"] = False

    threading.Thread(target=_run, daemon=True, name="rescan").start()

def _originals_hash():
    # 掺入词条黑名单：黑名单变化 → 解析结果可能变化 → 索引整体作废全量重扫
    try:
        payload = json.dumps([sorted(h().state.originals),
                              sorted((str(k), v) for k, v in h().state.norm_to_canon.items()),
                              sorted(h()._term_blacklist()), sorted(h()._term_whitelist())],
                             ensure_ascii=False)
    except Exception:
        payload = str(len(h().state.originals))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()

def _index_load():
    with h().INDEX_LOCK:
        if h().state.index_loaded:
            return
        h().state.index_loaded = True
        h().state.reset_index()
        try:
            with open(h().INDEX_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if (isinstance(data, dict) and data.get("v") == 3
                    and isinstance(data.get("works"), dict)
                    and data.get("originals_hash") == h()._originals_hash()):
                h().state.index = data
                # 身份归一逻辑版本不符（如 3.6.12 修了 TOZAN-BU/富士やま 归一）→ 旧缓存里的
                # circle/bare 不可信，整表作废重算；版本一致才沿用缓存（省去重开压缩包的代价）。
                if h().state.index.get("norm_v") != h().NORM_LOGIC_VERSION:
                    h().state.index["works"] = {}
                h().state.index["norm_v"] = h().NORM_LOGIC_VERSION
                # 3.6.151：入库时间的初始化基准换了（created_at → 作品文件最新 ctime）。
                # 旧记录是用旧基准算的（实测 742/742 个 at 恒等于 created_at），留着就永远不生效。
                if h().state.index.get("arrival_v") != h().ARRIVAL_VERSION:
                    h().state.index["groups"] = {}
                h().state.index["arrival_v"] = h().ARRIVAL_VERSION
        except Exception:
            h().log.exception("读取索引缓存失败（将触发全量重扫）")

def _index_save():
    fd = tmp = None
    try:
        with h().INDEX_LOCK:
            alive = {k: v for k, v in h().state.index["works"].items() if k in h().state.index_keys}
            h().state.index["works"] = alive
            h().state.index["originals_hash"] = h()._originals_hash()
            payload = h().state.index
        # 原子写：临时文件必须与目标同目录（同盘符 os.replace 才有效）
        idx_dir = h().ensure_dir(os.path.dirname(h().INDEX_FILE) or h().APP_DIR)   # 目录可能在 _state/，首次写前建好
        fd, tmp = tempfile.mkstemp(prefix="library_index_", suffix=".json", dir=idx_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        fd = None
        os.replace(tmp, h().INDEX_FILE)
        tmp = None
    except Exception:
        h().log.exception("写入索引缓存失败（重启后需要重新扫描）")
    finally:
        for fh in (fd, tmp):        # 变量名不能叫 h：会遮蔽 panel.host.h
            if fh is None:
                continue
            try:
                if isinstance(fh, int):
                    os.close(fh)
                else:
                    os.unlink(fh)
            except Exception:
                pass

def _work_to_cache(w):
    c = {k: w[k] for k in ("name", "path", "kind", "pages", "page_files", "mtime",
                           "circle", "circles", "personal", "personals", "bare", "tags")}
    c["cover"] = list(w["cover"]) if w.get("cover") else None
    c["tags"] = [list(t) for t in w["tags"]]
    return c

def _work_from_cache(c):
    try:
        w = dict(c)
        w["cover"] = tuple(c["cover"]) if c.get("cover") else None
        w["tags"] = [tuple(t) for t in c.get("tags", [])]
        # v2 旧缓存无 personals → 由 personal 单值回退（v3 索引版本会强制全量重扫补齐）
        if not w.get("personals"):
            w["personals"] = [w["personal"]] if w.get("personal") else []
        if not w.get("circles"):
            w["circles"] = [w["circle"]] if w.get("circle") else []
        return w
    except Exception:
        return None

def _index_get_work(key):
    with h().INDEX_LOCK:
        c = h().state.index["works"].get(key)
    h().state.index_keys.add(key)
    return h()._work_from_cache(c) if c is not None else None

def _index_put_work(key, work):
    with h().INDEX_LOCK:
        h().state.index["works"][key] = h()._work_to_cache(work)
    h().state.index_keys.add(key)

def _stamp_added_at(groups):
    """3.6.111：把 DB 的 works.added_at（首次入库时间）盖进 state.lib 的作品字典。

    分区内"新→旧"排序（APP 画师/社团/原作/标签页）以此为准——文件 mtime 会被
    删首页图等重写操作推进（作品错误顶到"最新"，用户明确不要）；added_at 首次
    见到后不再变化（db_sync 的 UPDATE 不写 added_at）。DB 没有的 key 保持缺省，
    APP 端回落 mtime。key 拼法与 _backfill_work_originals 相同（works.key = 真实
    归档目录名 + "/" + 作品名）。"""
    try:
        rows = h().meta.works_added_at()
    except Exception:
        h().log.exception("回填 added_at 失败（读取 DB）")
        return
    if not rows:
        return
    by_key = dict(rows)
    for g in groups:
        for w in g.get("works") or []:
            v = by_key.get((w.get("_group") or g.get("name") or "") + "/" + (w.get("name") or ""))
            if v:
                w["added_at"] = int(v)


def _merge_manual_originals(groups):
    """3.6.38 #36：把 DB 里的 original 标签回填进 state.lib 的 work.tags。

    「分区内手动添加作品」（/api/originals/add-works）写的标签只落 DB
    （用户附加事实，sync_scan 的 want_t 放行不删），但 state.lib 的 work.tags
    只含**解析器从文件名产出**的标签——/api/works?type=original 过滤的是
    state.lib 内存 tags。不回填的后果（已复现）：add-works 返回 ok、DB 标签在、
    force 重扫后分区内依然 0 部卡片。
    解析产出与 manual 行主键不同可共存（同作品可挂多个 original 标签）。

    3.6.70 结构：单部作品的回填抽到 `_backfill_work_originals`，本函数只做汇总。
    """
    try:
        rows = h().meta.original_tags_all()
    except Exception:
        h().log.exception("回填 manual original 标签失败（读取 DB）")
        return
    if not rows:
        return
    by_key = {}
    for key, name in rows:
        by_key.setdefault(key, set()).add(name)
    n_fill = 0
    for g in groups:
        for w in g.get("works") or []:
            if _backfill_work_originals(g, w, by_key):
                n_fill += 1
    if n_fill:
        h().log.info("manual original 标签回填 state.lib：%d 部作品", n_fill)


def _artist_page_cover(artist, recs):
    """3.6.114 画师页口径封面坐标：画师区域覆盖优先，否则名下体积最大作品
    （artists_all 的 biggest 语义，跨社团取）。无可用封面返回 None。"""
    ov = h()._resolve_region_cover("artist", artist)
    if ov:
        return ov["group"], ov["work"]
    rec = recs.get(artist)
    if rec and rec.get("cover_work"):
        return rec["cover_group"], rec["cover_work"]
    return None


def _unbind_circle_cover(g, old):
    """解绑：封面定格为跟随期最后的坐标快照（静默，不跳变）。"""
    if not (old.get("follow_artist") and old.get("follow_cover")):
        return
    fg, fw = old["follow_cover"]
    obj = h().find_work(fg, fw)
    if obj:
        g["cover_work"], g["cover_group"] = obj, fg


def _bind_circle_cover(g, artist, recs):
    """绑定：社团封面取画师页口径（用户给社团手设的覆盖优先，画师侧无封面则不绑）。"""
    if h()._region_cover_get("circle", g["name"]):
        return
    coord = _artist_page_cover(artist, recs)
    obj = h().find_work(*coord) if coord else None
    if not obj:
        return
    g["follow_artist"] = artist
    g["follow_cover"] = [coord[0], coord[1]]
    g["cover_work"], g["cover_group"] = obj, coord[0]


def _apply_sole_artist_covers(groups, old_data=None):
    """3.6.114：社团内只有一位画师时，封面跟随「画师页口径」（_bind_circle_cover）；
    画师集合 >1（新画师进驻 / 合作作品引入第二作者）时**静默解绑**
    （_unbind_circle_cover 定格快照，此后回归常规派生）。状态存 group 字典
    （follow_artist / follow_cover，随 library_index.json 持久化），跨轮状态从
    old_data（上一轮 LIB）恢复——force 重扫的 groups 是全新 dict。"""
    prev_state = {}
    for og in (old_data or {}).get("groups") or []:
        if og.get("follow_artist") or og.get("follow_cover"):
            prev_state[og["name"]] = og
    from services import meta_artist
    try:
        recs = {r["name"]: r for r in meta_artist.artists_all()}
    except Exception:
        h().log.exception("sole-artist 封面跟随失败（读取画师聚合）")
        return
    for g in groups:
        old = prev_state.get(g["name"]) or {}
        authors = set()
        for w in g.get("works") or []:
            authors.update(h()._work_authors(w))
        if len(authors) == 1:
            _bind_circle_cover(g, next(iter(authors)), recs)
        else:
            _unbind_circle_cover(g, old)


def _backfill_work_originals(g, w, by_key):
    """把该作品在 DB 里的 manual original 标签并进 w["tags"]；有变化返回 True。

    `_group` = 真实归档目录名（DB works.key 的 group 段，见 _normalize_identity）；
    g["name"] 是词条归一后的社团名（如「社团A (画师甲)」→「社团A」），不能拿来拼 key。
    """
    gname = w.get("_group") or g.get("name") or ""
    names = by_key.get(gname + "/" + (w.get("name") or ""))
    if not names:
        return False
    tags = list(w.get("tags") or [])
    add = names - {n for t, n in tags if t == "original"}
    if not add:
        return False
    tags.extend(("original", n) for n in sorted(add))
    w["tags"] = tags
    return True

# 3.7.51：扫描重入守卫。SCAN_LOCK 是**可重入锁**，挡不住同一线程的递归：
# build_group → _cover_for_group → _resolve_region_cover → find_work → find_group
# → get_library()（首扫时 state.lib["data"] 还是 None）→ _do_scan() → … 直到 RecursionError。
# 实际事故：扫描永久卡在 73/733，网页与 APP 都停在"正在加载中"。
# 重入时返回空库（封面覆盖查不到就退回派生封面），绝不二次进入扫描。
_SCAN_TLS = threading.local()


def _do_scan(ctx=None):
    """执行一轮全量扫描并替换 state.lib["data"]（调用方必须已持有 SCAN_LOCK）。
    get_library（阻塞路径）与 _kick_rescan（后台路径）共用。
    ctx=None → 同步路径，正常写盘；ctx=快照 → 后台路径，先校验上下文未变再写盘，
    变了就只更新内存缓存、放弃落盘（避免跨异步边界写穿到另一套库，见 _scan_ctx）。"""
    h()._index_load()
    h()._term_index(force=True)     # 3.6.12：每轮扫描刷新一次待定词条印证索引
    with h().INDEX_LOCK:
        # 词条库（originals）变化 → 解析结果可能变化 → 作废全部缓存（含本次进程内存态）
        if h().state.index.get("originals_hash") != h()._originals_hash():
            h().state.index["works"] = {}
        h().state.index_keys.clear()
    if getattr(_SCAN_TLS, "active", False):
        cur = h().state.lib["data"]
        return cur if cur is not None else {"groups": [], "scan_ms": 0, "scanned_at": 0.0}
    _SCAN_TLS.active = True
    t0 = time.time()
    h().state.scan_state["running"] = True
    try:
        groups = h().scan_groups(h().CFG.get("root", ""))
        data = {
            "groups": groups,
            "scan_ms": int((time.time() - t0) * 1000),
            "scanned_at": time.time(),
        }
        if h()._ctx_stale(ctx):
            # 3.6.10：扫描用的还是旧路径的库，写盘目标却已换成另一套 → 一律不落盘。
            # 只更新内存缓存（对生产无害：配置变更本身会触发新的 _lib_touch/_kick_rescan）。
            h().log.warning(
                "重扫上下文已变，放弃落盘以免写穿：%s -> %s", ctx, h()._scan_ctx())
        else:
            h()._index_save()
            try:
                h().meta.sync_scan(groups)   # 3.0 双轨：扫描结果 upsert 进元数据库（用户附加事实只存 DB）
                h()._merge_manual_originals(groups)   # 3.6.38 #36：manual 标签回填 state.lib
                _stamp_added_at(groups)      # 3.6.111：added_at（首次入库时间）回填 state.lib
            except Exception:
                h().log.exception("meta.sync_scan 失败（评分/进度同步可能中断）")
        old_data = h().state.lib["data"]        # 上一轮 LIB（跨轮恢复绑定状态用）
        with h().LIB_LOCK:
            h().state.lib["data"] = data
            h().state.lib["stale"] = False
        # 3.6.114：必须在 LIB 赋值**之后**——find_work 依赖 state.lib["data"]，
        # _do_scan 期间 LIB 为空，sole-artist 跟随的 find_work 会全部落空。
        # old_data = 上一轮 LIB：跨轮恢复绑定状态（force 重扫的 groups 是全新 dict）。
        _apply_sole_artist_covers(groups, old_data)
        return data
    finally:
        _SCAN_TLS.active = False
        h().state.scan_state["running"] = False

def get_library(force=False):
    """获取文库缓存。扫描在锁外执行：重扫期间旧数据仍可服务，
    同一时刻只允许一次扫描（其余请求等它完成后直接取结果）。
    force=False 且缓存已有数据（即使被 _lib_touch 标脏）→ 立即返回；
    后台重扫由 _kick_rescan 负责，读请求不再同步等待。"""
    arrived = time.time()
    with h().LIB_LOCK:
        if h().state.lib["data"] is not None and not force:
            return h().state.lib["data"]
    with h().SCAN_LOCK:
        with h().LIB_LOCK:
            data = h().state.lib["data"]
            if data is not None and (not force or data.get("scanned_at", 0) >= arrived):
                return data
        return h()._do_scan()
