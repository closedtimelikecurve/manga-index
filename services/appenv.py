# -*- coding: utf-8 -*-
"""services/appenv.py —— 运行时环境：日志、配置载荷、启动行为开关（3.6.61 Stage7 从 app.py 抽出）。

`setup_logging`（panel.log 轮转）、`config_payload`（前端首屏要的全部环境信息）、
`_browser_open_suppressed`（三种入口的"启动即弹浏览器"抑制规则）。
"""
import logging
import os
from logging.handlers import RotatingFileHandler

from common import APP_DIR, ensure_dir, safe_covers_on
from panel.host import h


def client_scope():
    """当前请求来自哪一端：**APP 声明，浏览器默认**。

    APP 从 3.7.111 起在请求头带 `X-Client: app`（见 Api.kt 的 `request_base`）；
    浏览器不会发这个头，一律算 web。拿不到请求上下文时（启动日志里顺带调用）也不炸，
    按 web 处理——那是最保守的一侧，不会给 APP 误开遮挡。
    """
    try:
        from flask import request
        return "app" if (request.headers.get("X-Client") or "").strip().lower() == "app" else "web"
    except Exception:                                   # noqa: BLE001 —— 无请求上下文
        return "web"


def setup_logging():
    root = logging.getLogger()
    if getattr(root, "_index_configured", False):
        return
    ensure_dir(os.path.dirname(h().LOG_FILE) or APP_DIR)   # _logs/ 首次运行需先建
    handler = RotatingFileHandler(h().LOG_FILE, maxBytes=2 * 1024 * 1024,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    root._index_configured = True

def config_payload():
    return {
        "ok": True,
        "root": h().CFG.get("root", ""),
        "rootExists": bool(h().CFG.get("root")) and os.path.isdir(h().CFG.get("root", "")),
        "name": h().CFG.get("name", h().LIBRARY_NAME),
        "port": h().CFG_PORT_BIND or h().CFG.get("port", h().PORT),
        "rarAvailable": h().RAR_AVAILABLE,
        "pilAvailable": h().PIL_OK,
        "originals": h().state.originals,
        "importOnly": h().IMPORT_ONLY,
        "version": h().PANEL_VERSION,          # 兼容旧字段（= 面板版本）
        "panelVersion": h().PANEL_VERSION,     # 面板版本（APP 侧展示用）
        "apiLevel": h().SERVER_API_LEVEL,      # 面板当前支持的接口级别
        "minAppApi": h().MIN_APP_API,          # 面板要求 APP 至少达到的接口级别
        "authRequired": bool(h().CFG.get("token")),
        # 代码已更新但本进程还是旧代码？→ 网页据此提示并一键重启（Python 只在启动时加载代码）
        "needsRestart": h()._panel_needs_restart(),
        "diskVersion": h()._disk_panel_version(),
        # 3.6.156：本发行版可用的爬取任务（公开版无 wnacg/N站/E站适配 → 只剩 jmdl/ext，
        # 双端据此隐藏对应胶囊与站点入口；完整发行版恒为全部 7 个）
        "builtinKinds": h().available_kinds(),
        # 3.6.161：内测模式开关的当前状态——双端抽屉按它显示开关位置。
        # 3.6.162：改为**各端独占**。`safeCovers` 回的是当前请求端自己的值
        # （老 APP 只认这个字段，行为不变）；另两个字段给出两端的真实状态，供面板展示。
        "safeCovers": safe_covers_on(h().CFG, client_scope()),
        "safeCoversWeb": safe_covers_on(h().CFG, "web"),
        "safeCoversApp": safe_covers_on(h().CFG, "app"),
        "clientScope": client_scope(),
    }

def _browser_open_suppressed(args):
    """是否抑制"启动即弹系统浏览器"（3.6.21 恢复三入口）。

    正式进程（Index.exe 完整/仅导入/远程卡）不传任何东西 → 弹；
    测试/静默进程任一入口命中即不弹：
      * 命令行 --no-browser（启动壳「测试模式」卡就是它）
      * 环境变量 INDEX_NO_BROWSER=1（我的后台测试任务用这个兜底，忘带参数也不弹）
      * config.json 的 "no_browser": true（整机级抑制，日常不建议设）"""
    if getattr(args, "no_browser", False):
        return True
    if str(os.environ.get("INDEX_NO_BROWSER") or "").strip() not in ("", "0", "false", "False"):
        return True
    try:
        return bool(h().CFG.get("no_browser"))
    except Exception:
        return False
