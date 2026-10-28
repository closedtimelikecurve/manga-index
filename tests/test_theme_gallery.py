# -*- coding: utf-8 -*-
"""主题背景图图库回归：列表 / 入库 / 选用 / 删除 / 公开端点 / 路径穿越。

隔离面（纪律 §4.1）：打桩点就是架构——本域的打桩面是 `routes.theme` 的**模块级路径常量**
（`_STATE_DIR` / `_GALLERY_DIR` / `_BUILTIN_DIR` / `_THEME_BG_DEFAULT`），全部指向 tmp_path，
绝不写真实 `_state/`；`APP_DIR` 不动（它承载 VERSION 等定位，见 conftest 的说明）。

3.6.122 起「选用」按端记录（`theme_bg_<client>.*` / `theme_active_<client>.txt`）；
本文件只验证**缺省端（app）**的既有行为，按端隔离与旧数据迁移在 `test_theme_slots.py`。
"""
import os
import re
import sys
from types import SimpleNamespace

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
import routes.theme as theme  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"unit-test-png-payload"
JPG = b"\xff\xd8\xff" + b"unit-test-jpg-payload"
DEFAULT_JPG = b"\xff\xd8\xff" + b"unit-test-default-bg"
NAME_RE = re.compile(r"^t_\d{8}_\d{6}_[0-9a-f]{4}\.(?:jpg|png|webp)$")
LOCAL = {"REMOTE_ADDR": "127.0.0.1"}
REMOTE = {"REMOTE_ADDR": "100.64.0.99"}       # 模拟 Tailscale/局域网远程设备
TRAVERSAL = ["..%2F..%2Fapp.py", "....//app.py", "sub/dir.png", "a.png/../../x.png"]


@pytest.fixture()
def theme_env(tmp_path, monkeypatch):
    """路径常量全部重定向到 tmp_path；顺带隔离真实 config.json 的 token。"""
    state = tmp_path / "_state"
    state.mkdir()
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    default = tmp_path / "default_bg.jpg"
    default.write_bytes(DEFAULT_JPG)
    monkeypatch.setattr(theme, "_STATE_DIR", str(state))
    monkeypatch.setattr(theme, "_GALLERY_DIR", str(state / "theme_gallery"))
    monkeypatch.setattr(theme, "_BUILTIN_DIR", str(builtin))
    monkeypatch.setattr(theme, "_THEME_BG_DEFAULT", str(default))
    # hero 槽位也是真实 _state 下的文件：不隔离的话，用户用过"首页横幅"就会污染空态断言
    monkeypatch.setattr(theme, "_THEME_HERO_BASE", str(state / "theme_hero"))
    monkeypatch.setattr(theme, "_HERO_ACTIVE_FILE", str(state / "hero_active.txt"))
    monkeypatch.setitem(app.CFG, "token", "")
    return SimpleNamespace(client=app.app.test_client(), state=state, default=default,
                           gallery=state / "theme_gallery", builtin=builtin)


def _items(env):
    """(active, items)，并顺带卡住列表响应的键集合（APP 与网页端依赖此形状）。"""
    j = env.client.get("/api/theme/gallery").get_json()
    assert j["ok"] is True
    assert set(j) == {"ok", "client", "active", "activeWeb", "activeApp",
                      "heroActive", "items"}
    return j["active"], j["items"]


def _names(env):
    return [it["name"] for it in _items(env)[1]]


def _upload(env, data, path="/api/theme/gallery"):
    return env.client.post(path, data=data, content_type="image/png")


def _bg_bytes(env):
    r = env.client.get("/api/theme/bg")
    assert r.status_code == 200
    return r.data


def test_gallery_empty_has_no_items_and_no_active(theme_env):
    assert theme_env.client.get("/api/theme/gallery").get_json() == {
        "ok": True, "client": "app", "active": "", "activeWeb": "", "activeApp": "",
        "heroActive": "", "items": []}


def test_gallery_upload_appears_and_keeps_current_bg(theme_env):
    r = _upload(theme_env, PNG)
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] is True and NAME_RE.match(j["name"]), j
    active, items = _items(theme_env)
    assert active == ""                                  # 只入库：active 不变
    assert [it["name"] for it in items] == [j["name"]]
    assert items[0]["size"] == len(PNG)
    assert isinstance(items[0]["mtime"], float) and items[0]["mtime"] > 0
    assert _bg_bytes(theme_env) == DEFAULT_JPG           # 当前背景仍是默认图
    assert not list(theme_env.state.glob("theme_bg_*.*"))  # 没写本端背景副本


def test_gallery_items_sorted_by_mtime_desc(theme_env):
    """mtime 用显式固定值（纪律 §4.8：绝不用"现在"）；非白名单条目不入列表。"""
    theme_env.gallery.mkdir()
    for name, mtime in (("t_20260101_000000_aaaa.png", 1000.0),
                        ("t_20260102_000000_bbbb.jpg", 2000.0),
                        ("t_20260103_000000_cccc.webp", 1500.0),
                        ("not-in-whitelist.txt", 3000.0)):
        p = theme_env.gallery / name
        p.write_bytes(PNG)
        os.utime(p, (mtime, mtime))
    assert _names(theme_env) == ["t_20260102_000000_bbbb.jpg",
                                 "t_20260103_000000_cccc.webp",
                                 "t_20260101_000000_aaaa.png"]
    _, items = _items(theme_env)
    assert items[0]["mtime"] == 2000.0 and items[0]["size"] == len(PNG)


def test_gallery_select_by_json_name(theme_env):
    png = _upload(theme_env, PNG).get_json()["name"]
    jpg = _upload(theme_env, JPG).get_json()["name"]
    r = theme_env.client.post("/api/theme/bg", json={"name": png})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert _bg_bytes(theme_env) == PNG
    assert _items(theme_env)[0] == png
    assert (theme_env.state / "theme_bg_app.png").read_bytes() == PNG
    # 改选 jpg：背景副本换成 .jpg，旧 .png 副本被清掉（既有语义不许丢）
    assert theme_env.client.post("/api/theme/bg", json={"name": jpg}).status_code == 200
    assert _bg_bytes(theme_env) == JPG and _items(theme_env)[0] == jpg
    assert not (theme_env.state / "theme_bg_app.png").exists()
    # 名字不在图库里 / 缺 name → 400，且当前背景不受影响
    assert theme_env.client.post("/api/theme/bg",
                                 json={"name": "nope.png"}).status_code == 400
    assert theme_env.client.post("/api/theme/bg", json={}).status_code == 400
    assert _bg_bytes(theme_env) == JPG


def test_bg_raw_upload_enables_and_enters_gallery(theme_env):
    """旧行为（原始字节 = 上传并启用）必须保持，同时入库并记为 active。"""
    r = _upload(theme_env, PNG, path="/api/theme/bg")
    assert r.status_code == 200
    name = r.get_json()["name"]
    assert NAME_RE.match(name), name
    assert _bg_bytes(theme_env) == PNG
    active, items = _items(theme_env)
    assert active == name and [it["name"] for it in items] == [name]


def test_gallery_rejects_non_image_and_oversize(theme_env):
    for bad in (b"hello", b""):
        assert _upload(theme_env, bad).status_code == 400
    oversize = PNG + b"\x00" * theme._THEME_BG_MAX            # 8MB + 头，必超上限
    assert _upload(theme_env, oversize).status_code == 400
    assert theme_env.client.post("/api/theme/bg", data=b"hello",
                                 content_type="image/png").status_code == 400
    assert _items(theme_env) == ("", [])                      # 失败不留痕
    assert not theme_env.gallery.exists()
    assert not list(theme_env.state.glob("theme_bg_*.*"))


def test_delete_active_restores_default(theme_env):
    name = _upload(theme_env, PNG, path="/api/theme/bg").get_json()["name"]
    assert _bg_bytes(theme_env) == PNG
    r = theme_env.client.delete("/api/theme/gallery/" + name)
    assert r.status_code == 200 and r.get_json() == {"ok": True, "message": "已从图库删除"}
    assert _items(theme_env) == ("", [])
    assert _bg_bytes(theme_env) == DEFAULT_JPG            # 回到默认图
    assert not list(theme_env.state.glob("theme_bg_*.*"))   # 背景副本已删


def test_delete_inactive_keeps_bg_and_bg_delete_keeps_gallery(theme_env):
    active = _upload(theme_env, PNG, path="/api/theme/bg").get_json()["name"]
    other = _upload(theme_env, JPG).get_json()["name"]
    assert theme_env.client.delete("/api/theme/gallery/" + other).status_code == 200
    assert _bg_bytes(theme_env) == PNG and _items(theme_env)[0] == active
    # DELETE /api/theme/bg：恢复默认，但图库文件不动
    assert theme_env.client.delete("/api/theme/bg").status_code == 200
    assert _bg_bytes(theme_env) == DEFAULT_JPG
    assert _items(theme_env)[0] == "" and _names(theme_env) == [active]


def test_gallery_path_traversal_is_404_and_touches_nothing(theme_env):
    app_py = os.path.join(PROG_DIR, "app.py")
    with open(app_py, "rb") as f:
        src_before = f.read()
    _upload(theme_env, PNG)                        # 图库里先留一张正常条目，便于比对
    before = sorted(os.listdir(theme_env.gallery))
    for bad in TRAVERSAL:
        url = "/api/theme/gallery/" + bad
        assert theme_env.client.get(url).status_code == 404, bad
        assert theme_env.client.delete(url).status_code == 404, bad
    assert sorted(os.listdir(theme_env.gallery)) == before      # 图库目录内容不变
    assert not list(theme_env.state.glob("theme_active_*.txt"))
    assert not list(theme_env.state.glob("theme_bg_*.*"))
    with open(app_py, "rb") as f:
        assert f.read() == src_before                           # 仓库文件没被删改


def test_gallery_image_is_public_like_bg(theme_env, monkeypatch):
    """图库图片端点公开（<img> 带不了 token）；列表/删除仍走全局闸门。"""
    name = _upload(theme_env, PNG).get_json()["name"]
    assert "api_theme_gallery_image" in app.PUBLIC_ENDPOINTS
    # 首页横幅是 <img>（带不了 X-Token）：也必须是公开端点，否则远程访问时横幅裂图
    assert "api_theme_hero_get" in app.PUBLIC_ENDPOINTS
    monkeypatch.setitem(app.CFG, "token", "bks-unittest-token")
    c = theme_env.client
    assert c.get("/api/theme/gallery", environ_base=LOCAL).status_code == 200
    assert c.get("/api/theme/gallery", environ_base=REMOTE).status_code == 401
    assert c.delete("/api/theme/gallery/" + name, environ_base=REMOTE).status_code == 401
    assert _names(theme_env) == [name]                     # 远程无令牌删不掉
    r = c.get("/api/theme/gallery/" + name, environ_base=REMOTE)
    assert r.status_code == 200 and r.data == PNG
    assert r.headers["Content-Type"].startswith("image/png")
    assert c.get("/api/theme/bg", environ_base=REMOTE).status_code == 200