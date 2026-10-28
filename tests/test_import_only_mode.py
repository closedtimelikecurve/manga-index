# -*- coding: utf-8 -*-
"""仅导入模式（--import-only）开放范围回归测试。

3.5.4：本机路径导入（/api/import-path + /api/import-commit，UI 上标称「移动模式」）
整体移除；同时仅导入模式除 首页/静态/配置/导入 外额外开放爬虫管理 —— 爬虫是入库的
上游来源（落盘 文库根/_inbox），把它挡在外面等于断掉这条路的入口。
"""
import os
import sys

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402


@pytest.fixture()
def only_mode(tmp_path, monkeypatch):
    """以仅导入模式起测试客户端（根目录指向临时目录，避免碰到真实文库）。"""
    monkeypatch.setitem(app.CFG, "root", str(tmp_path / "lib"))
    (tmp_path / "lib").mkdir()
    monkeypatch.setitem(app.CFG, "token", "")
    monkeypatch.setattr(app, "IMPORT_ONLY", True)
    return app.app.test_client()


def test_crawl_reachable_in_import_only(only_mode):
    """爬虫属于入库的上游链路，仅导入模式下必须可达（不能 403）。"""
    for path in ("/api/crawl/status", "/api/crawl/list"):
        r = only_mode.get(path)
        assert r.status_code != 403, f"{path} 在仅导入模式下被误拦"
        assert r.get_json()["ok"] is True


def test_browse_open_in_import_only(only_mode):
    """3.6.17 起仅导入模式仅前端隐藏功能键，不再于后端 403 拒绝浏览接口
    （完整模式已开的网页切到仅导入时，其他功能照常可用，只是界面不显示入口）。"""
    r = only_mode.get("/api/library")
    assert r.status_code != 403


def test_local_path_import_removed(tmp_path, monkeypatch):
    """「移动模式」的两个端点已彻底下线：路由不再注册（404）。

    注意要在完整模式下验 —— 仅导入模式的网关对任何未登记路由都回 403，
    那样分不出"已删除"和"被拦住"。"""
    monkeypatch.setitem(app.CFG, "root", str(tmp_path / "lib"))
    (tmp_path / "lib").mkdir()
    monkeypatch.setitem(app.CFG, "token", "")
    client = app.app.test_client()
    for path in ("/api/import-path", "/api/import-commit"):
        assert client.post(path, json={}).status_code == 404, f"{path} 应已不存在"
