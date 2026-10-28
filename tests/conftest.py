# -*- coding: utf-8 -*-
"""公共测试隔离：任何测试都不得写穿真实 config.json 与 _app/meta.db。

1) config.json：save_config(CFG) 按 common.CONFIG_FILE 定位写盘；解散社团、画师映射
   登记等接口会把整个 CFG 全量落盘——若不隔离，测试里 monkeypatch 进 CFG 的
   token=""/测试根目录会写进真实 config.json（2026-09-13 曾因此清空线上 token，
   远程令牌被迫轮换、手机端集体掉线）。
2) meta.db（3.0 元数据层）：扫描同步/评分/收藏/阅读状态等都会写 _app/meta.db——
   每个测试把 DB_PATH 指到自己的临时目录并重开连接，绝不触碰真实元数据库。
"""
import os
import sys

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import common  # noqa: E402
import meta_store  # noqa: E402

import time as _time


def wait_rescan_quiet(timeout=15):
    """3.3.0 SWR：等待后台重扫线程静默（pending 清零且 stale 清除）。
    断言"重扫完成后"的状态（删除已消失、旧 key 已迁移…）之前必须调用，
    否则读到的可能是尚未刷新的 stale 缓存。"""
    import app as _app
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        if not _app.state.rescan.get("pending") and not _app.state.lib.get("stale"):
            return True
        _time.sleep(0.02)
    return False


def _stub_crawler_paths(tmp_path, monkeypatch):
    """爬虫日志/state/收件箱路径桩：导入时绑定的真实绝对路径必须重定向，否则写穿真实文件。
    公开发行树没有 wnacg 栈（只带 crawl_jm_direct）→ 条件导入，两树通用。
    注意：本函数是普通函数，由 _isolate_config_file（autouse）调用——fixture 装饰器
    必须挂在 _isolate_config_file 上（2026-10-28 事故：装饰器被本函数截走，隔离失效，
    测试别名写穿了真实 meta.db）。"""
    monkeypatch.setattr(common, "CRAWL_LOG_FILE", str(tmp_path / "crawl_log.txt"))
    monkeypatch.setattr(common, "_crawl_log_fp", None)
    try:
        from crawlers import crawl_wnacg as _cw      # 3.6.46：脚本已收进 crawlers/ 包
        from crawlers import wnacg_base as _wb
    except ImportError:
        return
    monkeypatch.setattr(_wb, "LOG_FILE", str(tmp_path / "crawl_log.txt"))
    monkeypatch.setattr(_wb, "STATE_FILE", str(tmp_path / "crawl_state.json"))
    monkeypatch.setattr(_cw, "LOG_FILE", str(tmp_path / "crawl_log.txt"))
    monkeypatch.setattr(_cw, "STATE_FILE", str(tmp_path / "crawl_state.json"))
    monkeypatch.setattr(_cw, "STAGING_DIR", str(tmp_path / "_inbox"))


@pytest.fixture(autouse=True)
def _isolate_config_file(tmp_path, monkeypatch):
    """把 save_config 写盘目标与元数据库都重定向到本测试的临时目录。"""
    # 3.3.0 SWR：上一个测试可能留下仍在跑的后台重扫线程（扫的是上一个测试的
    # 临时根目录），先等它结束再换状态，否则它会把本测试刚扫好的 LIB 覆盖掉
    wait_rescan_quiet()
    monkeypatch.setattr(common, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(meta_store, "DB_PATH", str(tmp_path / "meta.db"))
    monkeypatch.setattr(meta_store, "BACKUP_DIR", str(tmp_path / "backups"))
    # 3.6.35：crawl_wnacg 的日志/state/收件箱路径是**导入时绑定**的真实绝对路径，
    # 任何调用其 log()/purge_parts()/download_one() 的测试都会写穿真实
    # crawl_log.txt 与 _inbox（用户报障"没启动任务日志也在跳"的根因：
    # test_crawl_resume 的 purge_parts 测试每轮往真实日志写"清理下载半成品"）。
    # 这里统一兜底打桩；_crawl_log_fp 必须一起清（模块级缓存的旧句柄会继续写旧文件）。
    # 3.6.156：log 实现已下沉 common.crawl_log（读 common 的全局）——打桩改打 common；
    # wnacg_base/crawl_wnacg 的同名再导出不再被 log() 读，但 STATE_FILE/STAGING_DIR
    # 等路径仍被各自代码直读，照旧打桩。
    # 公开发行树没有 wnacg 栈（只带 crawl_jm_direct）→ 条件导入，两树通用。
    _stub_crawler_paths(tmp_path, monkeypatch)
    # 3.6.3 收件箱目录 = APP_DIR/_inbox（程序目录内部）。不隔离的话，解散社团/无词条归档
    # 会把作品搬进真实的 _app/_inbox，_inbox_sync 也会去扫真实目录——必须重定向。
    # 只重定向 _inbox_dir()，**不动 APP_DIR**：APP_DIR 还承载着 VERSION/app.py 等
    # 关键文件的定位（面板自重启的 mtime 判据就靠它），改了会让 test_panel_restart 全红。
    import app as _app_mod
    monkeypatch.setattr(_app_mod, "_inbox_dir", lambda: str(tmp_path / "_app" / "_inbox"))
    _app_mod.state.unfiled_paths.clear()
    meta_store.close()          # 弃用上一测试的连接/缓存，路径变更后按新路径重开
    # 3.6.41：app 导入时 `_reload_originals()` 读的是**真实** config + meta.db 原作别名，
    # 会把用户自己登记的别名带进解析映射（用户在 10-17 晚集中登记 21 条别名后，
    # test_parsing / test_immediacy 立刻变红——不是它们回归，是测试吃了真实数据）。
    # 统一重置为**纯内置名单**；别名缓存刚被 close() 清空，测试要别名就自己登记。
    _built = _app_mod._dp.load_originals(None)
    monkeypatch.setattr(_app_mod.state, "originals", _built[0])
    monkeypatch.setattr(_app_mod.state, "norm_to_canon", dict(_built[1]))
    monkeypatch.setattr(_app_mod._dp, "NORM_TO_CANON", dict(_built[1]))
    yield
    # 3.6.10：monkeypatch 撤销发生在 fixture 返回之后，此前必须再等一次后台重扫
    # 收尾——否则线程会在路径已被改回真实 meta.db / library_index.json 时才落盘。
    # （_do_scan 的 ctx 校验是最后一道闸，这里只是把窗口缩到最小。）
    wait_rescan_quiet()
    meta_store.close()
