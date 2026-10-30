# -*- coding: utf-8 -*-
"""内测模式各端独占（3.6.162）。

原先 `safe_covers` 是一个全局布尔：在电脑上打开了，手机上打开 APP 也全是占位图。
但实际用法往往是"我只在给别人截图的那一端遮挡"，另一端还要正常看——所以改成
`{"web": bool, "app": bool}`，两端各自记忆。

服务端靠请求头 `X-Client: app` 分辨端（APP 从 3.7.111 起发这个头），浏览器不发 → web。

要守住的四条：

* 网页开 / APP 关 —— 互不影响（本条最容易写错成"一起改"）；
* 旧格式 `true/false` 仍按两端同值读 —— 升级不该让已有用户突然只剩一端生效；
* 不带 scope 的旧调用仍按两端一起设 —— 老网页 / 老 APP 还能用；
* `/cover` 必须按端出口，否则"网页挡住了、手机漏着"等于没挡。
"""
import os
import sys

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
import common  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    """干净客户端：两端都关、免令牌。"""
    monkeypatch.setitem(app.CFG, "safe_covers", {"web": False, "app": False})
    monkeypatch.setitem(app.CFG, "token", "")
    monkeypatch.setattr(app, "SAFE_IMAGES", False, raising=False)
    return app.app.test_client()


def test_legacy_bool_means_both_sides():
    """3.6.162 之前存的是单个布尔，读进来要当成两端同值。"""
    assert common._norm_safe_covers(True) == {"web": True, "app": True}
    assert common._norm_safe_covers("false") == {"web": False, "app": False}


def test_partial_dict_fills_missing_side():
    """只写了一端也安全：另一端默认关，不会因为缺键抛 KeyError。"""
    assert common._norm_safe_covers({"web": True}) == {"web": True, "app": False}


def test_safe_covers_on_reads_one_side():
    cfg = {"safe_covers": {"web": True, "app": False}}
    assert common.safe_covers_on(cfg, "web") is True
    assert common.safe_covers_on(cfg, "app") is False


def test_web_toggle_leaves_app_untouched(client):
    d = client.post("/api/config",
                    json={"safe_covers": True, "safe_covers_scope": "web"}).get_json()
    assert d["safeCoversWeb"] is True
    assert d["safeCoversApp"] is False, "网页开开关不该连带手机"


def test_each_side_reads_its_own_value(client):
    client.post("/api/config", json={"safe_covers": True, "safe_covers_scope": "app"})
    web = client.get("/api/config").get_json()
    phone = client.get("/api/config", headers={"X-Client": "app"}).get_json()
    assert web["clientScope"] == "web" and web["safeCovers"] is False
    assert phone["clientScope"] == "app" and phone["safeCovers"] is True


def test_legacy_post_sets_both(client):
    """不带 scope 的调用（老网页 / 老 APP）仍按两端一起设。"""
    client.post("/api/config", json={"safe_covers": True})
    d = client.get("/api/config").get_json()
    assert d["safeCoversWeb"] is True and d["safeCoversApp"] is True


def test_cover_outlet_respects_scope(client):
    """网页开着、手机关着：同一个 /cover，两端必须拿到不同的东西。

    没带 group/work 时真实封面路径返回 404（封面不存在），所以这里用
    "200 + X-Img-Mode" 与"404"就能分辨，不必真有一部作品。
    """
    client.post("/api/config", json={"safe_covers": True, "safe_covers_scope": "web"})
    web = client.get("/cover")
    phone = client.get("/cover", headers={"X-Client": "app"})
    assert web.status_code == 200
    assert web.headers.get("X-Img-Mode") == "safe:web"
    assert phone.status_code == 404, "手机这一端关着，就不该被盖住"


def test_cover_not_masked_on_either_side(client):
    """两端都关：任何一端都不该拿到占位图。"""
    for headers in ({}, {"X-Client": "app"}):
        r = client.get("/cover", headers=headers)
        assert r.headers.get("X-Img-Mode") is None
