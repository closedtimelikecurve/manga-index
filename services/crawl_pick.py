# -*- coding: utf-8 -*-
"""services/crawl_pick.py —— 勾选作品 → 下载 → 自动入库归区（3.7.54）。

每个 aid 走四步：
  1. `download_one` 把压缩包下到收件箱（复用既有直链候选 / 断点续传 / 三道校验）；
  2. `_inbox_sync()` 登记 → 取回该文件的收件项；
  3. `_inbox_confirm_one(it, circle_override=…)` 按提案入库——**社团检索时强制归到该社团**；
  4. 原作检索：`originals_add(term, [key])` 把作品挂到该原作分区（文件名没写原作也归得进去）。
全部结束后 force 重扫一次，两端 rev 一变就自动刷新。

为什么跑在**本进程的线程**而不是子进程：入库要动 `state` / 收件箱 / 元数据库，
子进程会带出第二份状态（与 `h()` 的前提冲突，见 `docs/architecture.md` §6）。
下载是 I/O 密集，GIL 在 I/O 期间释放，线程足够；且进度可直接回给接口。

取消只能"排到下一个之前"，正在传输的那一部会下完——不半途杀线程（会留下 .part 残包）。
"""
import json
import os
import threading
import time

import meta_store as meta

from common import crawl_log as log    # 3.6.156：services 层零 crawlers 顶层依赖
from panel.host import h
from services import crawl_probe_sites as sites
from services.crawl_probe import KINDS

_LOCK = threading.Lock()
# 3.7.56：进度版本号——前端/APP 据此判断"有没有状态变化"（状态流转才 +1，
# 字节进度不抬版本号：它每 0.5s 就变，抬了反而让"变了才重绘"失效）。
# 每次作品状态流转 +1（起任务/开始下载/入库/失败/取消/收尾）。
_REV = [0]


def _bump():
    """推进进度版本号（与快照读取共用 _LOCK，避免并发下丢计数）。"""
    with _LOCK:
        _REV[0] += 1


_JOB = {
    "id": 0, "running": False, "term": "", "kind": "", "site": "", "domain": "",
    "total": 0, "done": 0, "failed": 0, "started": 0, "finished": 0,
    "cancel": False, "message": "", "items": [],
}


def _new_job(term, kind, picks, site):
    """重置全局任务槽（单任务：同一时刻只允许一个勾选爬取在跑）。"""
    _JOB.update({
        "id": int(time.time()), "running": True, "term": term, "kind": kind,
        "site": site, "domain": "", "total": len(picks), "done": 0, "failed": 0,
        "started": time.time(), "finished": 0, "cancel": False, "message": "准备中…",
        "items": [{"aid": p["aid"], "title": p.get("title", ""), "state": "queued", "msg": "",
                   "bytes": 0, "bytes_total": 0, "token": p.get("token", ""),
                   "cover": p.get("cover", "")}     # 3.6.111：看板封面卡（picks 自带代理地址）
                  for p in picks],
    })
    _REV[0] += 1                  # 已在 _LOCK 内（pick_start 调用本函数时持锁）
    return _JOB


def _finish(msg=""):
    # 同一把锁内改三件事：快照不会看到"已停但 finished 还是 0"的中间态。
    with _LOCK:
        _JOB["running"] = False
        _JOB["finished"] = time.time()
        if msg:
            _JOB["message"] = msg
        _REV[0] += 1


def pick_start(term, kind, picks, site="wnacg"):
    """启动任务（立即返回）。picks = [{aid, title}]，至少一条。"""
    term = str(term or "").strip()
    kind = kind if kind in KINDS else "author"
    site = sites.site_of(site)
    picks = [p for p in (picks or []) if str(p.get("aid", "")).isdigit()]
    if not term:
        return {"ok": False, "message": "词条为空"}
    if not picks:
        return {"ok": False, "message": "没有勾选任何作品"}
    with _LOCK:
        if _JOB["running"]:
            return {"ok": False, "message": "已有一个勾选爬取任务在跑，请等它结束"}
        job = _new_job(term, kind, picks[:60], site)
        t = threading.Thread(target=_run, args=(job, list(job["items"])), daemon=True)
        t.start()
    log(f"==== 勾选爬取开始：{term}（{site}/{kind}），共 {len(picks)} 部 ====")
    return {"ok": True, "job": pick_status()}


def pick_status():
    """任务快照（dict 浅拷贝 + items 深一层），供轮询/监控面板。

    除原始字段外补几个**只读派生值**，让任何界面（网页浮标、爬虫页卡片、APP 顶栏）
    都能只凭这一次响应画出进度：
      * `elapsed` 已运行秒数（结束后冻结为总耗时，不再一直涨）；
      * `current` / `current_state` 正在处理的那一部及其阶段；
      * `queue` 还在排队的部数；`rev` 状态版本号（状态流转才变）。
    每一条 item 另带 `bytes` / `bytes_total`，下载阶段可直接画字节进度。"""
    with _LOCK:
        snap = {k: v for k, v in _JOB.items() if k != "items"}
        snap["items"] = [dict(it) for it in _JOB["items"]]
        rev = _REV[0]
    now = time.time()
    started = snap.get("started") or 0
    # 结束后用 finished 冻结耗时：否则监控面板会把"任务结束到此刻"也算进去。
    end = snap.get("finished") or (now if snap.get("running") else 0)
    snap["elapsed"] = max(0, int(end - started)) if started and end else 0
    cur = next((it for it in snap["items"] if it["state"] in ("downloading", "importing")), None)
    snap["current"] = cur["title"] if cur else ""
    snap["current_state"] = cur["state"] if cur else ""
    snap["queue"] = sum(1 for it in snap["items"] if it["state"] == "queued")
    snap["rev"] = rev
    return snap


def pick_cancel():
    with _LOCK:
        if not _JOB["running"]:
            return {"ok": False, "message": "没有正在运行的任务"}
        _JOB["cancel"] = True
        _JOB["message"] = "已请求取消（当前这一部会下完）"
        _REV[0] += 1
    return {"ok": True, "message": "已请求取消"}


def _find_domain(term):
    """用一次搜索确认当前可用域名（下载页与搜索同域）；失败返回空串。"""
    try:
        from crawlers.wnacg_search import search_works
        domain, _r, _t = search_works(term, pages=1)
        return domain
    except Exception as e:
        log("勾选爬取：解析下载域名失败（本次全部作品都会失败）：%s %s"
            % (type(e).__name__, str(e)[:80]))
        return ""


def _run(job, items):
    try:
        if job["site"] == "wnacg":
            job["domain"] = _find_domain(job["term"])
            job["message"] = "开始下载" if job["domain"] else "站点不可达"
        else:
            job["domain"] = sites.site_label(job["site"])
            job["message"] = "开始从 %s 下载" % sites.site_label(job["site"])
        for it in items:
            if job["cancel"]:
                it["state"] = "skip"
                it["msg"] = "已取消"
                _bump()
                continue
            _one(job, it)
        _after_all()
        _finish(f"完成：成功 {job['done']} / 失败 {job['failed']}")
    except Exception as e:
        log("勾选爬取异常终止（已下载的部分仍在收件箱/文库）：%s %s"
            % (type(e).__name__, str(e)[:100]))
        _finish("异常终止：" + str(e)[:120])
    finally:
        log(f"==== 勾选爬取结束：成功 {job['done']} / 失败 {job['failed']} ====")


def _one(job, it):
    it["state"] = "downloading"
    it["bytes"] = 0
    it["bytes_total"] = 0
    _bump()
    dest, err = _download(job["site"], job["domain"], it["aid"], it["title"],
                          token=it.get("token") or "",
                          on_progress=lambda got, total: _set_bytes(it, got, total))
    if not dest:
        it["state"] = "fail"
        it["msg"] = err or "下载失败"
        job["failed"] += 1
        _bump()
        return
    it["state"] = "importing"
    _bump()
    ok, msg, _key = _import_file(dest, job["kind"], job["term"])
    if ok:
        it["state"] = "ok"
        it["msg"] = msg
        job["done"] += 1
        _bump()
    else:
        it["state"] = "fail"
        it["msg"] = "已下载但入库未完成：" + msg
        job["failed"] += 1
        _bump()


def _set_bytes(it, got, total):
    """下载回调：只更新字节数，不动状态/版本号（0.5s 级别的变化不触发整块重绘）。"""
    it["bytes"] = max(0, int(got or 0))
    it["bytes_total"] = max(0, int(total or 0))


def _download(site, domain, aid, title, token="", on_progress=None):
    """按站点分派下载器。wnacg 走既有的直链/域名兜底与字节回调；
    JM/N站/E站走各自整本下载（3.6.112 起 N站/E站带字节进度，JM 库不支持回调）。"""
    if site == "jmcomic":
        return sites.download("jmcomic", aid, title, on_progress=on_progress)
    if site == "nhentai":
        return sites.download("nhentai", aid, title, on_progress=on_progress)
    if site == "ehentai":
        return sites.download("ehentai", aid, title, token=token, on_progress=on_progress)
    # wnacg：域名不可用时再试一次候选域名
    from crawlers.wnacg_download import download_one
    from crawlers.wnacg_search import _domain_candidates
    os.makedirs(h()._inbox_dir(), exist_ok=True)      # 首次使用时收件箱目录可能还没建
    d = domain or ""
    for cand in ([d] if d else []) + _domain_candidates(d):
        try:
            dest, err = download_one(cand, aid, h()._inbox_dir(), title or ("aid%s" % aid),
                                     on_progress=on_progress)
        except Exception as e:
            log("勾选爬取：aid=%s 下载异常 %s %s" % (aid, type(e).__name__, str(e)[:70]))
            dest, err = None, f"{type(e).__name__} {str(e)[:80]}"
        if dest:
            return dest, None
        if err and "下载页未解析出直链" not in err:
            return None, err          # 直链问题与域名无关，换域名无益
    return None, "全部域名均下载失败"


def _key_of(proposal, override, dest):
    """入库后的作品 key（社团/文件名），与 `_inbox_move_into` 的目标一致。"""
    circle = str(override or proposal.get("circle") or proposal.get("bare") or "").strip()
    name = proposal.get("new_name") or os.path.basename(dest or "")
    if not circle or not name:
        return ""
    return circle + "/" + os.path.splitext(name)[0]


def _import_file(dest, kind, term):
    """收件箱登记 → 确认入库 →（原作检索）补原作标签。返回 (ok, 文案, key)。

    **持 SCAN_LOCK**：`/api/inbox/confirm` 是变更型端点（整个请求期持锁），
    这条后台线程做的是同一件事（搬文件 + `_lib_touch`），不持锁就会与用户同时
    点"确认入库"/触发重扫的请求交错搬同一个文件。RLock 可重入，内部再取不冲突。"""
    with h().SCAN_LOCK:
        return _import_locked(dest, kind, term)


def _import_locked(dest, kind, term):
    h()._inbox_sync()
    ap = os.path.abspath(dest)
    it = next((x for x in h().meta.inbox_list()
               if os.path.abspath(x["src"]) == ap), None)
    if not it:
        return False, "收件箱里找不到刚下载的文件", ""
    try:
        proposal = json.loads(it["proposal"] or "{}")
    except Exception:
        proposal = {}
    override = term if kind == "circle" else None
    ok, msg = h()._inbox_confirm_one(it, circle_override=override)
    key = _key_of(proposal, override, dest)
    if ok and kind == "original" and key:
        meta.originals_add(term, [key])
    return ok, msg, key


def _after_all():
    """全部完成后重扫一次：新作品/新原作标签才会出现在分区里（两端 rev 变化即刷新）。"""
    try:
        h().get_library(force=True)
    except Exception as e:
        log("勾选爬取：收尾重扫失败（文件已入库，重启/手动重扫后可见）：%s" % str(e)[:80])
