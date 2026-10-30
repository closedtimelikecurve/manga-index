# -*- coding: utf-8 -*-
"""3.6.161 内测模式（`config.safe_covers`）：所有封面统一换成占位图。

这个开关只改**显示**、不动任何文件，出错方式很隐蔽，所以单列守卫：

* 开了还返回真实封面 → 截图就泄露了（最严重，必须挡住）；
* 关了还返回占位图 → 用户以为文库坏了；
* 图缺失直接 500 → 公开版不随这张图分发，必须退回灰度占位而不是崩。
"""
import os
import sys

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
import common  # noqa: E402
from panel import safecover  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    """干净客户端：开关默认关、免令牌（不受本机 config.json 影响）。"""
    monkeypatch.setitem(app.CFG, "safe_covers", False)
    monkeypatch.setitem(app.CFG, "token", "")
    monkeypatch.setattr(app, "SAFE_IMAGES", False, raising=False)
    return app.app.test_client()


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


def test_off_serves_real_cover(client):
    """关着的时候 /cover 走原逻辑（没有 group/work → 404，不是占位图）。"""
    r = client.get("/cover")
    assert r.status_code == 404
    assert "X-Img-Mode" not in r.headers


def test_on_serves_placeholder(client):
    """开着的时候即使参数缺失也直接给占位图——说明走在找作品之前。"""
    app.CFG["safe_covers"] = {"web": True, "app": False}   # 3.6.162 起分端
    r = client.get("/cover")
    assert r.status_code == 200
    assert r.headers["X-Img-Mode"] == "safe:web"
    assert r.headers["Cache-Control"] == "no-cache"      # 关掉开关要立刻看到真封面
    # 内容确实是那张占位图（不是碰巧 200 的真实封面）。
    # 公开树不随附 safe_cover.jpg，此时应回退 placeholder.png —— 两棵树都要过。
    expect = (safecover.SAFE_COVER_IMG if os.path.exists(safecover.SAFE_COVER_IMG)
              else safecover.PLACEHOLDER_IMG)
    assert r.data == _bytes(expect)


def test_on_falls_back_when_image_missing(client, monkeypatch):
    """公开版不随这张图分发：文件缺失要退回 placeholder.png，不能 500。"""
    app.CFG["safe_covers"] = {"web": True, "app": False}
    monkeypatch.setattr(safecover, "SAFE_COVER_IMG", os.path.join(PROG_DIR, "no", "such.jpg"))
    r = client.get("/cover")
    assert r.status_code == 200
    assert r.headers["X-Img-Mode"] == "safe:web"
    assert r.headers["Content-Type"].startswith("image/png")
    assert r.data == _bytes(safecover.PLACEHOLDER_IMG)


def test_probe_cover_also_masked(client):
    """搜索下载器的探针封面同样是封面，不能漏。"""
    app.CFG["safe_covers"] = {"web": True, "app": False}
    r = client.get("/api/crawl/probe/cover?u=https://example.com/a.jpg")
    assert r.status_code == 200
    assert r.headers["X-Img-Mode"] == "safe:web"


def test_toggle_via_config_post(client):
    """抽屉开关走 POST /api/config：返回体里带新状态，CFG 同步改。"""
    r = client.post("/api/config", json={"safe_covers": True})
    assert r.status_code == 200
    assert r.get_json()["safeCovers"] is True
    assert common.safe_covers_on(app.CFG, "web") is True

    r = client.post("/api/config", json={"safe_covers": False})
    assert r.get_json()["safeCovers"] is False
    assert common.safe_covers_on(app.CFG, "web") is False
    # 关了之后封面恢复原逻辑
    assert client.get("/cover").status_code == 404


def test_toggle_writes_config_file(client):
    """必须落盘：重启面板后开关位置要还在（用户预期）。

    注意读的是 `common.CONFIG_FILE`——conftest 的隔离夹具打到 common 上的这个全局，
    `app` 侧那份是导入时的字符串副本，读它会指回真实 config.json。
    """
    client.post("/api/config", json={"safe_covers": True})
    import json
    with open(common.CONFIG_FILE, encoding="utf-8") as f:
        saved = json.load(f).get("safe_covers")
    # 不带 scope 的旧调用仍按两端一起设（3.6.162 的分端语义见 test_safe_covers_scope.py）
    assert saved == {"web": True, "app": True}


def test_string_false_is_false(client):
    """手写 config.json 写成 "false" 字符串时不能当开（`bool("false")` 是 True 的经典坑）。"""
    for raw, want in (("false", False), ("true", True), ("0", False), ("on", True)):
        assert common._truthy(raw) is want
    assert common._truthy(False) is False and common._truthy(True) is True


def test_safe_images_flag_still_works(client):
    """旧的 --safe-images 行为不能被新开关取代（自动化截图脚本还在用它）。"""
    app.CFG["safe_covers"] = False
    app.SAFE_IMAGES = True
    r = client.get("/cover")
    assert r.status_code == 200
    assert r.headers["ETag"].strip('"') == "safe-placeholder"
