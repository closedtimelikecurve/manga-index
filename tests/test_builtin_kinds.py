# -*- coding: utf-8 -*-
"""发行版可用性探测（3.6.156）：公开版只带 JM 直连爬虫，其余站点适配被剔除。

守住三条契约：
  1. services 层**零 crawlers 顶层依赖**——把 crawlers 包从模块查找里藏掉后，
     available_kinds / site_available 照常工作（公开树只剩 jmdl/ext）；
  2. 完整发行版恒为 7 个任务，/api/config 下发 builtinKinds（双端过滤的唯一事实源）；
  3. 不可用任务的启动/搜索拿到**友好错误**（不崩、不进引擎）。
"""
import importlib.util
import os
import sys
import time

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import common  # noqa: E402
from services import crawl as crawl_svc  # noqa: E402
from services import crawl_probe_sites as sites  # noqa: E402


@pytest.fixture()
def client():
    import app as app_mod
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


@pytest.fixture()
def hide_crawlers(monkeypatch):
    """从 sys.modules 与模块查找两层把公开树剔除的爬虫模块藏掉。

    只在测试进程内模拟：available_kinds 走 find_spec（对已导入模块会直接回
    sys.modules 里的 spec），所以 sys.modules 必须一起清，钩子才拦得到。
    公开树**保留** crawlers 包本身与 crawl_jm_direct（JM 直连公开）。
    """
    _PUBLIC = {"crawlers", "crawlers.crawl_jm_direct"}
    for name in [n for n in list(sys.modules)
                 if (n == "crawlers" or n.startswith("crawlers.")) and n not in _PUBLIC]:
        monkeypatch.delitem(sys.modules, name)

    class _HideCrawlers:
        def find_spec(self, fullname, path=None, target=None):
            if fullname.startswith("crawlers") and fullname not in _PUBLIC:
                raise ImportError("simulated public distribution (module removed)")
            return None

    monkeypatch.setattr(sys, "meta_path", [_HideCrawlers()] + sys.meta_path)


def _expected_kinds():
    """按 find_spec 现算期望清单（两树通用：完整发行版 7 个，公开树只剩 jmdl/ext）。"""
    out = []
    for kind, mod in crawl_svc._KIND_CRAWLER_MODULE.items():
        try:
            if importlib.util.find_spec(mod) is not None:
                out.append(kind)
        except (ImportError, ValueError):
            pass
    return [k for k in crawl_svc._KIND_ORDER if k in out or k == "ext"]


def test_full_install_reports_all_seven_kinds():
    """主线发行版（本仓库带全套 crawlers）：available_kinds 与 find_spec 现算一致。"""
    assert crawl_svc.available_kinds() == _expected_kinds()


def test_kinds_narrow_without_crawlers(hide_crawlers):
    """公开树契约：crawlers 缺失 → available_kinds 只剩 jmdl + ext（ext 恒可用）。"""
    assert crawl_svc.available_kinds() == ["jmdl", "ext"]
    assert sites.site_available("jmcomic") is True
    assert sites.site_available("wnacg") is False
    assert sites.site_available("nhentai") is False
    assert sites.site_available("ehentai") is False


def test_unavailable_kind_start_is_friendly_error(client, monkeypatch):
    """不可用任务的启动：400 + 引导文案，绝不进引擎（即使前端被绕过）。"""
    import app as app_mod
    monkeypatch.setattr(app_mod, "available_kinds", lambda: ["ext"])
    r = client.post("/api/crawl/start", json={"kind": "wnacg", "entries": ["x"]})
    assert r.status_code == 400
    assert "未包含" in r.get_json()["message"]


def test_unavailable_probe_site_errors(client, monkeypatch):
    """分区爬取对不可用站点：路由前门直接 400 + 点名"适配未包含"（公开树深层
    惰性 import 也会炸，但守卫必须在前门拦住）。"""
    from services import crawl_probe_sites as s
    monkeypatch.setattr(s, "site_available", lambda site: site == "jmcomic")
    r = client.post("/api/crawl/probe",
                    json={"term": "x", "kind": "author", "site": "nhentai"})
    assert r.status_code == 400
    assert "未包含" in r.get_json()["message"]


def test_config_payload_carries_builtin_kinds(client):
    """/api/config 下发 builtinKinds（双端胶囊/站点 chip 过滤的唯一事实源）。"""
    d = client.get("/api/config").get_json()
    assert d["builtinKinds"] == crawl_svc.available_kinds()


def test_crawl_log_lands_in_common(tmp_path, monkeypatch):
    """log 实现下沉后：common.crawl_log 写 common.CRAWL_LOG_FILE，wnacg_base.log 同一实现。
    （公开树没有 wnacg_base——re-export 断言只对完整发行版有意义。）"""
    pytest.importorskip("crawlers.wnacg_base")
    from crawlers import wnacg_base as wb
    logfile = tmp_path / "cl.txt"
    monkeypatch.setattr(common, "CRAWL_LOG_FILE", str(logfile))
    monkeypatch.setattr(common, "_crawl_log_fp", None)
    common.crawl_log("下沉冒烟")
    time.sleep(0.05)
    assert "下沉冒烟" in logfile.read_text(encoding="utf-8")
    assert wb.log is common.crawl_log                   # re-export 是同一个函数对象
