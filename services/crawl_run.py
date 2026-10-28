# -*- coding: utf-8 -*-
"""services/crawl_run.py —— 全爬虫域的两段式任务引擎（3.7.58）。

背景：分区爬取（`crawl_pick`）证明"先锁定作品 → 再集中下载 → 面板看进度"这条路
比"一边搜一边下、进度只能靠日志文本反推"好用得多。这里把它推广到五个爬取任务
（wnacg 主爬 / JM 索引 / JM 直连 / N站索引 / N站直连）：

  * 第一阶段「锁定」（`crawl_lock`）：逐条把词条解析成**具体作品**（站点 id / 标题 /
    封面），只查不下载。解析不出作品的条目当场标成「未匹配」，不拖到下载阶段才发现；
  * 第二阶段「爬取」（`crawl_fetch`）：对已锁定的作品逐个下载，带字节进度；
  * 全程写进任务快照（`status()`），网页与 APP 都靠它画监控面板，日志退居次要。

为什么跑在**本进程线程**而不是子进程：面板要实时读进度，子进程只能靠日志文本反推。
执行的都是 I/O 密集操作，GIL 在 I/O 期间释放，线程足够。五个任务各自一个槽位、可同时运行。

取消语义与分区爬取一致：只挡"下一个"，正在传输的那一部会下完——不半途杀线程，
否则会留下 `.part` 残包。
"""
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout

import common

from common import crawl_log as _clog    # 3.6.156：services 层零 crawlers 顶层依赖
from services import crawl as _state
from services.crawl_fetch import DOWNLOADERS
from services.crawl_lock import LOCKERS, Ctx, NoMatch, Skip

KINDS = ("wnacg", "jm", "jmdl", "nh", "nhdl", "eh", "ext")   # 3.6.155 +外接下载器
KIND_LABELS = {"wnacg": "wnacg 主下载", "jm": "JM 索引获取", "jmdl": "JM 直连获取",
               "nh": "N站索引获取", "nhdl": "N站直连获取", "eh": "E站直连获取",
               "ext": "外接下载器"}
MAX_ITEMS = 500           # 单任务上限：再长的清单分批跑，免得面板与内存一起爆
COVER_WORKERS = 5         # 封面准备阶段的并发（图站对突发连接会 reset，压住反而更快）
COVER_BUDGET = 90.0       # 封面准备的总预算（秒）：到点用占位图，绝不无限等

_LOCK = threading.RLock()
_REVS = {k: 0 for k in KINDS}
_RUNTIME = {k: {} for k in KINDS}     # kind -> {idx: 运行时对象}（meta 等，不进快照）


def _blank(kind):
    return {"kind": kind, "id": 0, "running": False, "phase": "idle",
            "total": 0, "done": 0, "failed": 0, "unmatched": 0, "skipped": 0,
            "started": 0, "finished": 0, "cancel": False, "message": "",
            "strict": False, "covers": 0, "covers_ready": 0, "items": []}


_JOBS = {k: _blank(k) for k in KINDS}


def _bump(kind):
    """状态版本号 +1（只在状态流转时调；字节进度不抬，否则"变了才重绘"失效）。"""
    with _LOCK:
        _REVS[kind] += 1


def _log(kind, text):
    """写进该任务自己的日志文件（面板里是可折叠的"运行日志"）。"""
    try:
        _state._crawl_log_append(text, path=_state._crawl_log_file(kind))
    except Exception as e:                              # noqa: BLE001 —— 日志失败不影响爬取
        _clog("[爬取] 写日志失败：%s" % str(e)[:60])


# ---------------------------------------------------------------
# 任务快照
# ---------------------------------------------------------------
def status(kind, with_items=True):
    """单个任务的进度快照（面板画卡片用）。含派生值，前端不必自己算。

    `with_items=False` 只给状态条 / 全局浮标用：清单几百条时，5 个任务一起拉
    没必要把 items 也各复制一遍。"""
    if kind not in _JOBS:
        return {"ok": False, "message": "未知任务类型"}
    snap = _copy_job(kind, with_items)
    _derive(snap)
    return snap


def _copy_job(kind, with_items):
    with _LOCK:
        job = _JOBS[kind]
        snap = {k: v for k, v in job.items() if k != "items"}
        snap["items"] = [dict(it) for it in job["items"]] if with_items else []
        snap["rev"] = _REVS[kind]
    return snap


def _derive(snap):
    """补齐派生值：耗时、已锁定/排队数、当前条目、任务名。"""
    now = time.time()
    started = snap.get("started") or 0
    end = snap.get("finished") or (now if snap.get("running") else 0)
    snap["elapsed"] = max(0, int(end - started)) if started and end else 0
    items = snap["items"]
    snap["locked"] = _count(items, ("locked", "downloading", "ok"))
    snap["queued"] = _count(items, ("queued", "locking"))
    cur = next((it for it in items if it["state"] in ("locking", "downloading")), None)
    snap["current"] = cur["title"] if cur else ""
    snap["current_state"] = cur["state"] if cur else ""
    snap["label"] = KIND_LABELS.get(snap["kind"], snap["kind"])
    snap["ok"] = True


def _count(items, states):
    return sum(1 for it in items if it["state"] in states)


def status_summary(kind):
    """精简快照（不含 items）：状态条 / 全局浮标用，5 个任务一起拉也不重。"""
    s = status(kind, with_items=False)
    s.pop("items", None)
    return s


def status_all():
    return {"ok": True, "jobs": [status_summary(k) for k in KINDS]}


# ---------------------------------------------------------------
# 清单 / 断点
# ---------------------------------------------------------------
def _list_paths(kind):
    """该任务的清单文件（jmdl 两份：车号在前——精确匹配优先，与脚本口径一致）。"""
    if kind == "wnacg":
        return [_state._CRAWL_LIST_WNACG]
    if kind in ("jm", "nh"):
        return [_state._CRAWL_LIST_INDEX]
    if kind == "jmdl":
        return [_state._CRAWL_LIST_JMDL_I, _state._CRAWL_LIST_JMDL_T]
    if kind == "eh":
        return [_state._CRAWL_LIST_EH]
    if kind == "ext":
        return [_state._CRAWL_LIST_EXT]
    return [_state._CRAWL_LIST_NHDL]


def _read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except OSError:
        return []


def _write_lines(path, lines):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines).rstrip("\n") + ("\n" if lines else ""))
    os.replace(tmp, path)


def _state_path(kind):
    if kind in ("jm", "nh"):
        # 走 services.crawl 的 STATE_DIR（与其它任务的 state 同源，测试里可整体重定向）
        return os.path.join(_state.STATE_DIR, "crawl_state_%s_ids.json" % kind)
    return _state._crawl_state_file(kind)


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                   # noqa: BLE001 —— 缺失/损坏都按空处理
        return None


def _write_json(path, data):
    common.ensure_dir(os.path.dirname(path) or common.APP_DIR)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _done_entries(kind):
    """已完成条目（断点）：同一词条不再重复锁定/下载。"""
    st = _read_json(_state_path(kind)) or {}
    out = set()
    for key, rec in (st.get("done") or {}).items():
        # 断点有两种历史形状：老 CLI 脚本写的是**字符串**（直接是词条），
        # 3.7.58 起写的是 dict（含 entry/aid/title/file）。只认 dict 会
        # AttributeError → read_entries 抛出 → 清单爬虫点「启动」直接失败。
        if isinstance(rec, dict):
            out.add(str(rec.get("entry") or key).strip())
        else:
            out.add(str(rec or key).strip())
    return out


def read_entries(kind):
    """读清单 → 待处理条目（去注释、去重、去已完成，保留原始顺序）。"""
    done = _done_entries(kind)
    out, seen = [], set()
    for p in _list_paths(kind):
        for line in _read_lines(p):
            e = line.strip()
            if not e or e.startswith("#") or e in seen or e in done:
                continue
            seen.add(e)
            out.append(e)
    return out


def _record(kind, entry, ok, info):
    """写断点（与各脚本同一份 state 文件，CLI 与面板互相接得住）。"""
    try:
        path = _state_path(kind)
        st = _read_json(path) or {}
        if not isinstance(st.get("done"), dict):
            st["done"] = {}
        if not isinstance(st.get("failed"), dict):
            st["failed"] = {}
        if ok:
            st["done"][entry] = info
            st["failed"].pop(entry, None)
        else:
            st["failed"][entry] = info
        _write_json(path, st)
    except Exception as e:                              # noqa: BLE001 —— 记账失败不影响已下载文件
        _log(kind, "断点写入失败（不影响已下载文件）：%s" % str(e)[:80])


# ---------------------------------------------------------------
# 启动 / 取消
# ---------------------------------------------------------------
def start(kind, limit=0, strict=False, tool=""):
    """启动一个两段式任务（立即返回）。清单由调用方（路由）先写盘。
    tool 仅 ext 任务用：外接下载器的工具名（空 = 用配置里第一个）。"""
    if kind not in KINDS:
        return {"ok": False, "message": "未知任务类型"}
    with _LOCK:
        if _JOBS[kind]["running"]:
            return {"ok": False, "message": "该任务已在运行中"}
    entries = read_entries(kind)
    if limit and limit > 0:
        entries = entries[:limit]
    if not entries:
        return {"ok": False, "message": "清单里没有待爬词条（已完成或为空）"}
    entries = entries[:MAX_ITEMS]
    with _LOCK:
        job = _blank(kind)
        job.update({
            "id": int(time.time()), "running": True, "phase": "lock",
            "total": len(entries), "started": time.time(), "strict": bool(strict),
            "tool": str(tool or ""),
            "message": "正在锁定作品…",
            "items": [{"idx": i, "entry": e, "title": e, "name": e, "site": "",
                       "aid": "", "cover": "", "state": "queued", "msg": "",
                       "bytes": 0, "bytes_total": 0, "pages": 0}
                      for i, e in enumerate(entries)],
        })
        _JOBS[kind] = job
        _RUNTIME[kind] = {}
        _REVS[kind] += 1
    _state.crawl_mark_log_start(kind, _state._crawl_log_file(kind))
    _log(kind, "==== 启动：%d 个词条（%s）｜先锁定作品，再集中获取 ===="
         % (len(entries), "严格档" if strict else "常规档"))
    # 把 job 对象直接交给线程：不要再让它按 kind 回查全局槽——测试里槽位会被
    # 下一个用例重置，晚调度的线程会抓到别人的任务（表现为"刚启动就说已在运行"）。
    threading.Thread(target=_run, args=(job,), daemon=True,
                     name="crawl-run-" + kind).start()
    return {"ok": True, "message": "已启动：%d 个词条（先锁定，再爬取）" % len(entries)}


def cancel(kind):
    if kind not in KINDS:
        return {"ok": False, "message": "未知任务类型"}
    with _LOCK:
        job = _JOBS[kind]
        if not job["running"]:
            return {"ok": False, "message": "该任务没有在运行"}
        job["cancel"] = True
        job["message"] = "已请求取消（当前这一部会下完）"
        _REVS[kind] += 1
    return {"ok": True, "message": "已请求取消"}


# ---------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------
def _run(job):
    kind = job["kind"]
    ctx = Ctx(kind, job["strict"])
    try:
        if kind == "ext":
            _ext_prepare(job)                  # 3.6.155：条目即 URL，无锁定/封面阶段
        else:
            _lock_all(job, ctx)
            if not job["cancel"]:
                _prepare_covers(job, ctx)      # 3.7.64：封面必须在下载前备好（阻塞）
        if not job["cancel"]:
            _download_all(job, ctx)
        _finish(job, "完成：成功 %d · 失败 %d%s"
                % (job["done"], job["failed"],
                   (" · 跳过 %d" % job["skipped"]) if job["skipped"] else ""))
    except Exception as e:                              # noqa: BLE001 —— 线程顶层必须兜住
        _clog("[爬取] %s 异常终止：%s %s" % (kind, type(e).__name__, str(e)[:100]))
        _finish(job, "异常终止：%s %s" % (type(e).__name__, str(e)[:100]))


def _ext_prepare(job):
    """外接下载器的前置：条目已是命令参数，全部直接标记为「已锁定」进下载阶段；
    同时给每条挂上 rt（工具名 + 取消回调），dl_ext 从 rt 里取。"""
    kind = job["kind"]
    _log(kind, "外接下载器：%s" % (job.get("tool") or "默认工具"))
    for it in job["items"]:
        it["title"] = it["entry"]
        _RUNTIME[kind][it["idx"]] = {"tool": job.get("tool") or "",
                                     "cancelled": (lambda j=job: j["cancel"])}
        _mark(job, it, "locked", "待下载")


def _finish(job, msg):
    """收尾：**先重写清单，再宣布结束**——这个顺序就是契约。

    事故来源（2026-10-26 查一个偶发失败）：原来先 `running = False` 再 `_rewrite_lists()`，
    于是任何"看到任务结束就去读清单"的一方（监控面板提示、测试、用户手动复制清单）
    都可能读到**还没删掉已完成条目**的旧内容，`test_successful_entries_leave_the_list`
    因此偶发失败。把重写提到前面后，`running=False` 才真正等于"跑完了，清单也更新好了"。
    """
    _rewrite_lists(job)
    with _LOCK:
        job["running"] = False
        job["phase"] = "done"
        job["finished"] = time.time()
        job["message"] = msg
    _bump(job["kind"])
    _log(job["kind"], "==== " + msg + " ====")
    # 任务结束 → 撤销本次日志起点：/api/crawl/status 不再回传本次日志
    # （与 3.6.38 的约定一致；监控面板是主视图，日志只在运行时有用）
    _state.crawl_clear_log_cursor(job["kind"])


def _rewrite_lists(job):
    """成功后从清单移除条目（失败/未匹配留在清单里，下次重试）。"""
    done = {it["entry"] for it in job["items"]
            if it["state"] == "ok" or (it["state"] == "skip" and it["msg"].startswith("库内已有"))}
    if not done:
        return
    for path in _list_paths(job["kind"]):
        try:
            lines = _read_lines(path)
            kept = [ln for ln in lines if not (ln.strip() and ln.strip() in done)]
            if kept == lines:
                continue
            _write_lines(path, kept)
            _log(job["kind"], "清单回写 %s：移除 %d 行，剩余 %d 行"
                 % (os.path.basename(path), len(lines) - len(kept), len(kept)))
        except OSError as e:
            _log(job["kind"], "清单回写失败 %s：%s" % (path, str(e)[:60]))


def _lock_all(job, ctx):
    job["phase"] = "lock"
    job["message"] = "正在锁定作品…"
    _bump(job["kind"])
    for it in job["items"]:
        if job["cancel"]:
            _mark(job, it, "skip", "已取消")
            job["skipped"] += 1
            continue
        _lock_item(job, it, ctx)
    covers = [it["cover"] for it in job["items"] if it["cover"]]
    if covers:
        _warm(covers)


def _lock_item(job, it, ctx):
    _mark(job, it, "locking", "解析中…")
    try:
        rec = LOCKERS[job["kind"]](it["entry"], ctx)
    except Skip as e:
        _skip_item(job, it, e)
        return
    except NoMatch as e:
        _fail_item(job, it, str(e), "未匹配")
        return
    except Exception as e:                              # noqa: BLE001 —— 单条失败不毁整批
        _fail_item(job, it, "%s %s" % (type(e).__name__, str(e)[:100]), "锁定异常")
        return
    _RUNTIME[job["kind"]][it["idx"]] = rec.get("rt") or {}
    for k in ("title", "site", "aid", "cover", "pages", "name"):
        if rec.get(k) not in (None, ""):
            it[k] = rec[k]
    _mark(job, it, "locked", "已锁定")
    _log(job["kind"], "  ✓ 锁定：%s → %s%s" % (it["entry"][:50], str(it["title"])[:50],
                                            (" (aid=%s)" % it["aid"]) if it["aid"] else ""))


def _skip_item(job, it, err):
    """库内已有相似文件：按"已完成"处理（从清单移除、记断点），不计下载成功。"""
    _mark(job, it, "skip", "库内已有：%s" % str(err)[:80])
    job["done"] += 1
    job["skipped"] += 1
    _record(job["kind"], it["entry"], True,
            {"entry": it["entry"], "skip": "duplicate", "file": str(err)[:120]})
    _log(job["kind"], "  = 跳过：%s（%s）" % (it["entry"][:50], str(err)[:60]))


def _fail_item(job, it, msg, label):
    _mark(job, it, "unmatched", msg[:120])
    job["failed"] += 1
    job["unmatched"] += 1
    _record(job["kind"], it["entry"], False, msg[:160])
    _log(job["kind"], "  ✗ %s：%s ｜ %s" % (label, it["entry"][:50], msg[:70]))


def _download_all(job, ctx):
    job["phase"] = "download"
    job["message"] = "开始集中获取"
    _bump(job["kind"])
    for it in job["items"]:
        if it["state"] != "locked":
            continue
        if job["cancel"]:
            _mark(job, it, "skip", "已取消")
            job["skipped"] += 1
            continue
        _download_item(job, it, ctx)


def _download_item(job, it, ctx):
    _mark(job, it, "downloading", "下载中…")
    it["bytes"] = 0
    it["bytes_total"] = 0
    rt = _RUNTIME[job["kind"]].get(it["idx"]) or {}
    try:
        fn = DOWNLOADERS[job["kind"]]
        ok, msg = fn(it, ctx, rt, on_progress=lambda got, total: _bytes(it, got, total))
    except Exception as e:                              # noqa: BLE001 —— 单条失败不毁整批
        ok, msg = False, "%s %s" % (type(e).__name__, str(e)[:100])
    if ok:
        _mark(job, it, "ok", msg)
        job["done"] += 1
        _record(job["kind"], it["entry"], True,
                {"entry": it["entry"], "aid": str(it["aid"]), "title": it["title"]})
        _log(job["kind"], "  ⬇ 完成：%s" % str(it["title"])[:60])
        return
    _mark(job, it, "fail", msg)
    job["failed"] += 1
    _record(job["kind"], it["entry"], False, msg)
    _log(job["kind"], "  ✗ 下载失败：%s ｜ %s" % (str(it["title"])[:50], msg[:70]))


def _mark(job, it, state, msg):
    with _LOCK:
        it["state"] = state
        it["msg"] = msg
    _bump(job["kind"])


def _bytes(it, got, total):
    """下载回调：只更新字节数，不动状态（0.5s 级频率，抬版本号会让重绘判据失效）。"""
    it["bytes"] = max(0, int(got or 0))
    it["bytes_total"] = max(0, int(total or 0))


def _prepare_covers(job, ctx):
    """下载前把封面**抓进缓存并等它们就绪**（3.7.64）。

    用户要求：集中爬取开始时封面必须已经加载好。此前是异步预热（`_warm_covers`）：
    下载一开始浏览器就来取图，撞上还没落盘的 URL 会拿到 404，`<img>` 随即被
    `onerror` 隐藏——看起来就是"任务里没有封面"。更糟的是分区爬虫一搜索就会推进
    预热代际（`_WARM_GEN`），把这里的预热直接掐停。

    现在这一阶段是阻塞的：并发抓完（或到预算上限）才进入下载阶段。已经预热过的会走
    磁盘缓存，几乎零耗时；真的抓不到的条目用占位图，不拖住任务。
    """
    urls = [it["cover"] for it in job["items"] if it.get("cover")]
    if not urls:
        return
    _use_site_referer(ctx)
    with _LOCK:
        job["phase"] = "cover"
        job["covers"] = len(urls)
        job["covers_ready"] = 0
        job["message"] = "正在准备封面 0/%d…" % len(urls)
    _bump(job["kind"])
    ready = _run_cover_pool(job, urls)
    _log(job["kind"], "封面就绪 %d/%d" % (ready, len(urls)))


def _use_site_referer(ctx):
    """让封面代理用爬虫当前的真实站点域名做 Referer（图床会校验）。"""
    if not getattr(ctx, "domain", ""):
        return
    try:
        from services import crawl_probe
        crawl_probe._SITE[0] = ctx.domain
    except Exception as e:                              # noqa: BLE001 —— 只影响 Referer
        _clog("[爬取] 设置封面 Referer 失败：%s" % str(e)[:60])


def _run_cover_pool(job, urls):
    """并发抓封面；返回成功张数。到预算就停手（余下的用占位图）。"""
    ready = 0
    ex = ThreadPoolExecutor(max_workers=COVER_WORKERS, thread_name_prefix="cover")
    try:
        futs = {ex.submit(_cover_one, u): u for u in urls}
        deadline = time.time() + COVER_BUDGET
        for fut in as_completed(futs, timeout=max(1.0, deadline - time.time())):
            if not fut.result():
                continue
            ready += 1
            with _LOCK:
                job["covers_ready"] = ready
                job["message"] = "正在准备封面 %d/%d…" % (ready, len(urls))
            _bump(job["kind"])
    except FuturesTimeout:
        _log(job["kind"], "封面准备超时（预算 %.0fs），余下用占位图" % COVER_BUDGET)
    finally:
        # wait=False：别为了几张抓不到的图把任务卡在超时预算之外
        ex.shutdown(wait=False, cancel_futures=True)
    return ready


def _cover_one(url):
    try:
        from services import crawl_probe
        return bool(crawl_probe.probe_cover(url)[0])
    except Exception as e:                              # noqa: BLE001 —— 单张失败不影响整批
        _clog("[爬取] 封面抓取失败 %s：%s %s" % (str(url)[:60], type(e).__name__, str(e)[:50]))
        return False


def _warm(covers):
    try:
        from services import crawl_probe
        crawl_probe._warm_covers(covers)
    except Exception as e:                              # noqa: BLE001 —— 预热失败只是慢一点
        _clog("[爬取] 封面预热失败：%s" % str(e)[:60])
