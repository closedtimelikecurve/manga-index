# -*- coding: utf-8 -*-
"""routes/crawl.py —— crawl 域路由（3.6.53 结构重构 Stage6 从 app.py 抽出）。

规矩：
  * **不在本模块 import app**（`python app.py` 时会造成二次导入 / 双 Flask 实例）；
    一律 `h().xxx` 按名解析，保证 monkeypatch 仍然生效。
  * 端点函数保持模块级（静态检查与测试按名字定位）；注册集中在 `register(app)`。
"""
from flask import jsonify, request

from panel.http import mutating
from routes.host import h


def api_crawl_status():
    """爬虫状态（五个任务各自独立，可同时运行）。

    3.7.58 起进度来自任务快照（`_overlay_jobs`），不再是子进程 PID + 日志文本；
    这里保留 tasks 形状与日志字段，是为了让旧版 APP 仍能只读顶层字段。
    日志按 ?kind= 取对应任务的文件；`?since=<字节游标>` 走增量（只回传新行）。
    监控面板请用 `GET /api/crawl/job`（含逐条作品与封面）。"""
    kinds = ("wnacg", "jm", "jmdl", "nh", "nhdl", "eh")
    with h()._CRAWL_LOCK:
        tasks = [h()._crawl_task_snapshot(k) for k in kinds]
    _overlay_jobs(tasks)          # 3.7.58：进度以任务快照为准（不再是子进程/日志）
    primary = next((t for t in tasks if t["running"]), tasks[0])
    kind_arg = request.args.get("kind") or "wnacg"
    log_kind = kind_arg if kind_arg in h()._CRAWL_KINDS else "wnacg"
    try:
        since = int(request.args.get("since", "-1"))
    except (TypeError, ValueError):
        since = -1
    out = {"ok": True, "tasks": tasks,
           "running": primary["running"],
           "kind": primary["kind"] if primary["running"] else None,
           "pid": primary["pid"], "startedAt": primary["startedAt"],
           "total": primary["total"], "done": primary["done"], "failed": primary["failed"]}
    log_path = h()._crawl_log_file(log_kind)
    # 3.6.38 #35：日志区改为「单次任务实时监测」——只回传**本次运行**产生的行
    # （起点 = 该任务启动时记录的 log_cursor）；任务未在运行 → 不回传任何行
    # （前端据此清除）。历史日志仍全量在文件里，只是不再展示。
    cursor0 = h().crawl_log_cursor(log_kind)
    if cursor0 is None:
        out.update({"logLines": [], "logTail": [], "logCursor": 0,
                    "logSize": 0, "logKind": log_kind})
    elif since >= 0:
        lines, cursor, size = h()._crawl_log_since(max(since, cursor0), path=log_path)
        out.update({"logLines": lines, "logCursor": cursor, "logSize": size, "logKind": log_kind})
    else:
        # 首轮（since<0）：从本次起点读全部（内部按 _CRAWL_LOG_READ_MAX 截断保护）
        lines, cursor, size = h()._crawl_log_since(cursor0, path=log_path)
        out.update({"logTail": lines[-h()._CRAWL_LOG_TAIL_LINES:],
                    "logLines": lines[-h()._CRAWL_LOG_TAIL_LINES:],
                    "logCursor": cursor, "logSize": size, "logKind": log_kind})
    return jsonify(out)


def api_crawl_start():
    """启动一个爬虫任务（可选先把本次清单写盘）。"""
    body = request.get_json(silent=True) or {}
    kind = body.get("kind", "wnacg")
    if kind not in h()._CRAWL_KINDS:
        return jsonify({"ok": False, "message": "未知任务类型"}), 400
    if kind not in h().available_kinds():
        return jsonify({"ok": False,
                        "message": "此发行版未包含该内置站点适配（可用任务见胶囊；或配置外接下载器）"}), 400
    try:
        limit = max(0, int(body.get("limit") or 0))
    except (TypeError, ValueError):
        limit = 0
    _crawl_write_lists(kind, body)
    # 3.7.58：不再拉子进程。五个任务统一走 crawlers→services 的两段式引擎：
    # 先逐条锁定作品（带封面），再集中下载；进度写任务快照，面板/APP 直接读。
    # 3.6.155：ext 任务透传工具名（空 = 用配置里第一个外接下载器）。
    r = h().crawl_run_start(kind, limit, bool(body.get("strict")),
                            tool=str(body.get("tool") or ""))
    code = 200 if r.get("ok") else 400
    return jsonify(r), code


def _crawl_write_lists(kind, body):
    """把前端提交的清单写盘（jmdl 独占两份：词条→直连词条，车号→直连 id）。"""
    entries = body.get("entries")
    if kind == "jmdl":
        # 直连模式独占两份清单：词条→pending_jmdl_titles（JM 站内搜索），车号→pending_jmdl_ids（直下）
        if isinstance(entries, list):
            h()._crawl_write_list(h()._CRAWL_LIST_JMDL_T, entries)
        jm_entries = body.get("jmEntries")
        if isinstance(jm_entries, list):
            h()._crawl_write_list(h()._CRAWL_LIST_JMDL_I, jm_entries)
        return
    if kind not in ("wnacg", "jm", "nh", "nhdl", "eh", "ext") or not isinstance(entries, list):
        return
    list_path = {"wnacg": h()._CRAWL_LIST_WNACG, "jm": h()._CRAWL_LIST_JM,
                 "nh": h()._CRAWL_LIST_NH, "nhdl": h()._CRAWL_LIST_NHDL,
                 "eh": h()._CRAWL_LIST_EH, "ext": h()._CRAWL_LIST_EXT}[kind]
    h()._crawl_write_list(list_path, entries)


def api_crawl_stop():
    body = request.get_json(silent=True) or {}
    kind = body.get("kind") or "wnacg"
    if kind not in h()._CRAWL_KINDS:
        return jsonify({"ok": False, "message": "未知任务类型"}), 400
    r = h().crawl_run_cancel(kind)
    code = 200 if r.get("ok") else 400
    return jsonify(r), code


def api_crawl_job():
    """任务进度快照（3.7.58）。`?kind=` 给单任务（含 items 卡片数据）；
    `?all=1` 给五个任务的精简状态（状态条 / 全局浮标用，不带 items）。"""
    if request.args.get("all"):
        return jsonify(h().crawl_run_status_all())
    kind = request.args.get("kind") or "wnacg"
    if kind not in h()._CRAWL_KINDS:
        return jsonify({"ok": False, "message": "未知任务类型"}), 400
    return jsonify(h().crawl_run_status(kind))


def _overlay_jobs(tasks):
    """把任务引擎的实时状态盖到任务快照上（running/total/done/failed/phase）。

    为什么不让 `_crawl_task_snapshot` 自己读：`services/crawl.py` 是状态存储层，
    不认识任务引擎；叠在路由层既不起循环导入，也保住"快照只有一种形状"。
    """
    for t in tasks:
        j = h().crawl_run_status(t["kind"], False)
        if not j.get("running") and not j.get("total"):
            continue          # 本进程还没跑过这个任务 → 保留断点计数（done/failed）
        t.update({"running": bool(j.get("running")), "pid": None,
                  "startedAt": j.get("started") if j.get("running") else None,
                  "total": j.get("total", 0), "done": j.get("done", 0),
                  "failed": j.get("failed", 0), "phase": j.get("phase", "idle"),
                  "message": j.get("message", ""), "jobRev": j.get("rev", 0)})


def api_crawl_list_get():
    def _read(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""
    # 3.6.7：清单文件各自独立（wnacg / jmdl 词条 / jmdl 车号 / N站直连）；
    # 3.6.36：索引系整合为共享清单 index（jm/nh 同一文件），jm/nhIds 为兼容镜像
    return jsonify({"ok": True, "wnacg": _read(h()._CRAWL_LIST_WNACG),
                    "index": _read(h()._CRAWL_LIST_INDEX),
                    "jm": _read(h()._CRAWL_LIST_INDEX),
                    "jmdlTitles": _read(h()._CRAWL_LIST_JMDL_T),
                    "jmdlIds": _read(h()._CRAWL_LIST_JMDL_I),
                    "nhIds": _read(h()._CRAWL_LIST_NH), "nhdlIds": _read(h()._CRAWL_LIST_NHDL),
                    "ehIds": _read(h()._CRAWL_LIST_EH),
                    "ext": _read(h()._CRAWL_LIST_EXT)})


def api_crawl_ext_tools():
    """3.6.155：外接下载器工具表（config.json ext_downloaders 的 name 列表）。
    空表 = 未配置，前端显示引导文案。"""
    from services.crawl_fetch import ext_tools
    tools = ext_tools()
    return jsonify({"ok": True, "tools": [
        {"name": t["name"], "timeout": int(t.get("timeout") or 0)} for t in tools]})


def api_crawl_list_post():
    body = request.get_json(silent=True) or {}
    try:
        # 3.6.36：索引系共享清单——index/jm/nhIds 三个键等价，都写同一文件；
        # 3.6.110：E站直连清单 ehIds；3.6.155：外接下载器清单 ext
        paths = {"wnacg": h()._CRAWL_LIST_WNACG, "index": h()._CRAWL_LIST_INDEX,
                 "jm": h()._CRAWL_LIST_INDEX, "nhIds": h()._CRAWL_LIST_NH,
                 "jmdlTitles": h()._CRAWL_LIST_JMDL_T, "jmdlIds": h()._CRAWL_LIST_JMDL_I,
                 "nhdlIds": h()._CRAWL_LIST_NHDL, "ehIds": h()._CRAWL_LIST_EH,
                 "ext": h()._CRAWL_LIST_EXT}
        for key, path in paths.items():
            if key in body:
                h()._crawl_write_list(path, str(body.get(key) or "").splitlines())
        return jsonify({"ok": True, "message": "清单已保存"})
    except Exception as e:
        return jsonify({"ok": False, "message": "保存失败：" + str(e)}), 500


ROUTES = [
    ('get', '/api/crawl/status', api_crawl_status, False),
    ('get', '/api/crawl/job', api_crawl_job, False),
    ('post', '/api/crawl/start', api_crawl_start, False),
    ('post', '/api/crawl/stop', api_crawl_stop, False),
    ('get', '/api/crawl/list', api_crawl_list_get, False),
    ('post', '/api/crawl/list', api_crawl_list_post, False),
    ('get', '/api/crawl/ext/tools', api_crawl_ext_tools, False),
]


def register(app):
    """把本域端点挂到 Flask 实例上（幂等：重复调用会报重复 endpoint，便于发现重复注册）。"""
    for method, rule, fn, is_mut in ROUTES:
        if is_mut:
            fn = mutating(fn)
        getattr(app, method)(rule)(fn)
