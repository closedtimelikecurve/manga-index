# -*- coding: utf-8 -*-
"""3.6.122 图库「按端选用」+ 内置图回归。

用户需求：图库是**共用的**一份（两端看到同一批图），但**选中的图可以不同**
（电脑挑 A、手机挑 B，互不覆盖）；默认图与基础图要出现在图库里，且内置图不可删。

打桩面（纪律 §4.1）：`routes.theme` 的 `_STATE_DIR` / `_GALLERY_DIR` / `_BUILTIN_DIR` /
`_THEME_BG_DEFAULT` 四个模块级路径常量，全部指向 tmp_path。
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
import routes.theme as theme  # noqa: E402
from services import theme_store as ts  # noqa: E402

PNG_A = b"\x89PNG\r\n\x1a\n" + b"slot-a"
PNG_B = b"\x89PNG\r\n\x1a\n" + b"slot-b"
DEFAULT_JPG = b"\xff\xd8\xff" + b"slot-default"


@pytest.fixture()
def env(tmp_path, monkeypatch):
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
    monkeypatch.setitem(app.CFG, "token", "")
    return SimpleNamespace(client=app.app.test_client(), state=state,
                           gallery=state / "theme_gallery", builtin=builtin)


def _upload(env, data):
    r = env.client.post("/api/theme/gallery", data=data, content_type="image/png")
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()["name"]


def _list(env, client=None):
    url = "/api/theme/gallery" + ("?client=" + client if client else "")
    return env.client.get(url).get_json()


def _bg(env, client=None):
    url = "/api/theme/bg" + ("?client=" + client if client else "")
    r = env.client.get(url)
    assert r.status_code == 200
    return r.data


def _select(env, name, client=None):
    url = "/api/theme/bg" + ("?client=" + client if client else "")
    return env.client.post(url, json={"name": name})


def test_two_clients_keep_different_selections(env):
    a = _upload(env, PNG_A)
    b = _upload(env, PNG_B)
    assert _select(env, a, "web").status_code == 200
    assert _select(env, b, "app").status_code == 200
    assert _list(env, "web")["active"] == a
    assert _list(env, "app")["active"] == b
    assert _bg(env, "web") == PNG_A and _bg(env, "app") == PNG_B
    # 图库本身只有一份（两端都看到 A 与 B）
    assert set(env.client.get("/api/theme/gallery?client=web").get_json()["items"][0]) >= {
        "name", "size", "mtime", "builtin", "title"}
    names_web = [it["name"] for it in _list(env, "web")["items"]]
    names_app = [it["name"] for it in _list(env, "app")["items"]]
    assert names_web == names_app


def test_missing_client_defaults_to_app(env):
    """≤3.7.78 的旧 APK 不带 client：必须落 app 槽位，永不覆盖网页的选择。"""
    name = _upload(env, PNG_A)
    assert _select(env, name).status_code == 200          # 不带 client
    j = _list(env)
    assert j["client"] == "app" and j["active"] == name
    assert j["activeWeb"] == ""


def test_legacy_global_selection_migrates_to_both_clients(env):
    """升级前只有一份全局选用：升级后两端都应继续显示那张图，旧文件随后清掉。"""
    name = "t_20260101_000000_aaaa.png"
    (env.state / "theme_gallery").mkdir()
    (env.state / "theme_gallery" / name).write_bytes(PNG_A)
    (env.state / "theme_active.txt").write_text(name + "\n", encoding="utf-8")
    (env.state / "theme_bg.png").write_bytes(PNG_A)

    j = _list(env, "web")
    assert j["activeWeb"] == name and j["activeApp"] == name
    assert _bg(env, "web") == PNG_A and _bg(env, "app") == PNG_A
    assert (env.state / "theme_bg_web.png").exists()
    assert (env.state / "theme_bg_app.png").exists()
    assert not (env.state / "theme_active.txt").exists()
    assert not (env.state / "theme_bg.png").exists()


def test_delete_one_client_selection_leaves_the_other(env):
    a = _upload(env, PNG_A)
    b = _upload(env, PNG_B)
    _select(env, a, "web")
    _select(env, b, "app")
    assert env.client.delete("/api/theme/gallery/" + a).status_code == 200
    assert _list(env, "web")["active"] == ""               # 删的那张正是 web 的选用
    assert _list(env, "app")["active"] == b                # app 不受影响
    assert _bg(env, "web") == DEFAULT_JPG and _bg(env, "app") == PNG_B


def _seed_builtins(env):
    for name, _title in ts.BUILTIN_ITEMS[:3]:
        (env.builtin / name).write_bytes(PNG_A)


def test_builtin_items_listed_first(env):
    _seed_builtins(env)
    user = _upload(env, PNG_B)
    j = _list(env, "web")
    names = [it["name"] for it in j["items"]]
    assert names[:3] == [n for n, _t in ts.BUILTIN_ITEMS[:3]]   # 内置固定顺序在前
    assert names[-1] == user
    first = j["items"][0]
    assert first["builtin"] is True and first["title"] == ts.BUILTIN_ITEMS[0][1]
    assert j["items"][-1]["builtin"] is False


def test_builtin_can_be_selected_but_not_deleted(env):
    _seed_builtins(env)
    name = ts.BUILTIN_ITEMS[0][0]
    assert _select(env, name, "web").status_code == 200
    assert _bg(env, "web") == PNG_A
    r = env.client.get("/api/theme/gallery/" + name)
    assert r.status_code == 200 and r.data == PNG_A
    d = env.client.delete("/api/theme/gallery/" + name)
    assert d.status_code == 400 and d.get_json()["message"] == "内置图片不可删除"
    assert (env.builtin / name).exists()


def test_builtin_registry_files_exist_in_repo():
    """注册表里每一张都必须真实提交（防"注册表写了、二进制漏了"→ 图库 404）。"""
    folder = os.path.join(PROG_DIR, "static", "img", "gallery")
    missing = [n for n, _t in ts.BUILTIN_ITEMS if not os.path.isfile(os.path.join(folder, n))]
    assert not missing, "内置图缺失：%s" % missing
