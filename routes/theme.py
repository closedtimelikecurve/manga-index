# -*- coding: utf-8 -*-
"""routes/theme.py —— 主题域路由（3.6.115 抽屉「主题」；3.6.116 背景图图库；3.6.122 按端选用）。

本文件只做 HTTP 薄层：解析请求 → 调 `services.theme_store` 的纯原语 → 返回字节/JSON。
文件/路径规则（白名单、魔数、副本读写、active 记录、内置图注册表）在
`services/theme_store.py`；**本模块的模块级路径常量仍在**——它们是测试打桩面（纪律 §4.1）。

3.6.122 起「图库」与「当前选用」分开：
* 图库是**一份**（`_state/theme_gallery/` + `static/img/gallery/` 的内置图），双端共用；
* 「当前选用」**按端各记一份**：`_state/theme_active_<client>.txt` + `_state/theme_bg_<client>.<ext>`，
  `client` 取 `?client=web|app`（body 的 `client`、`X-Client` 头兜底），**缺省 app**
  （唯一会省略参数的是 ≤3.7.78 的旧 APK；默认 app 保证旧包不覆盖网页的选择）。

* GET    /api/theme/bg              当前端背景字节（本端副本优先，否则默认 static/img/bg.jpg）。
  **公开端点**（<img> 带不了 X-Token；背景图非敏感）。
* POST   /api/theme/bg              原始字节 = 上传并直接启用（同时入图库）；JSON {"name"} = 从图库选用。
* DELETE /api/theme/bg              只清本端副本与 active，恢复默认（图库文件不动）。
* GET    /api/theme/gallery         图库列表（内置图在前 + 用户图按 mtime 倒序）。
* POST   /api/theme/gallery         上传入库，**不改当前背景**（jpg/png/webp，≤8MB，魔数校验）。
* GET    /api/theme/gallery/<name>  图库图片字节。**公开端点**（与背景图同理）。
* DELETE /api/theme/gallery/<name>  删用户图；内置图一律 400。删的是某端 active 时该端恢复默认。
* hero 四端点（3.6.118）保持全局单份：首页横幅是网页专属（APP 首页用打包资源）。

规矩与其它 routes 一致：不 import app，一律 h()/common 按名解析；ROUTES + register()。
"""
import os

from flask import jsonify, request, send_file

import common
from services import theme_store as ts

_STATE_DIR = os.path.join(common.APP_DIR, "_state")
_GALLERY_DIR = os.path.join(_STATE_DIR, "theme_gallery")
_BUILTIN_DIR = os.path.join(common.APP_DIR, "static", "img", "gallery")
_THEME_BG_DEFAULT = os.path.join(common.APP_DIR, "static", "img", "bg.jpg")
_THEME_BG_MAX = ts.MAX_BYTES
# 3.6.121 及以前的「全局」槽位：只用于一次性迁移与迁移失败时的读取兜底，不再被写入。
_LEGACY_ACTIVE_FILE = os.path.join(_STATE_DIR, "theme_active.txt")
_LEGACY_BG_BASE = os.path.join(_STATE_DIR, "theme_bg")
# hero 槽位（3.6.118）：全局单份，机制与背景图同构
_THEME_HERO_BASE = os.path.join(_STATE_DIR, "theme_hero")
_THEME_HERO_DEFAULT = os.path.join(common.APP_DIR, "static", "img", "hero.jpg")
_HERO_ACTIVE_FILE = os.path.join(_STATE_DIR, "hero_active.txt")

_CLIENTS = ("web", "app")
DEFAULT_CLIENT = "app"


# ---------- 按端槽位 ----------

def _client():
    """当前请求属于哪一端：query → body → X-Client → 缺省 app；非法值静默归缺省。"""
    c = (request.args.get("client") or "").strip().lower()
    if not c:
        body = request.get_json(silent=True)
        if isinstance(body, dict):
            c = str(body.get("client") or "").strip().lower()
    if not c:
        c = (request.headers.get("X-Client") or "").strip().lower()
    return c if c in _CLIENTS else DEFAULT_CLIENT


def _migrate():
    ts.migrate_legacy(_STATE_DIR, _CLIENTS)


def _active_file(client):
    return os.path.join(_STATE_DIR, "theme_active_%s.txt" % client)


def _bg_base(client):
    return os.path.join(_STATE_DIR, "theme_bg_%s" % client)


def _bg_custom_path(client):
    """本端背景副本；没有时读旧全局副本（迁移未完成/失败时升级后背景不突变）。"""
    return ts.copy_path(_bg_base(client)) or ts.copy_path(_LEGACY_BG_BASE)


def _gallery_path(name):
    """图库中该文件的可读路径：用户目录优先，其次内置目录；不合法/不存在 → None。"""
    return ts.find_image(_GALLERY_DIR, _BUILTIN_DIR, name)


def _gallery_items():
    """内置图（注册表顺序在前）+ 用户图（mtime 倒序）。"""
    items = ts.builtin_items(_BUILTIN_DIR)
    for it in ts.list_items(_GALLERY_DIR):
        it["builtin"] = False
        it["title"] = ""
        items.append(it)
    return items


def _image_ext_or_error(data):
    """校验上传字节：合法返回 (扩展名, None)，否则 (None, (响应, 400))。"""
    if not data or len(data) > _THEME_BG_MAX:
        return None, (jsonify({"ok": False, "message": "图片为空或超过 8MB"}), 400)
    ext = ts.sniff_ext(data)
    if not ext:
        return None, (jsonify({"ok": False, "message": "仅支持 jpg / png / webp"}), 400)
    return ext, None


# ---------- 背景图（按端） ----------

def api_theme_bg_get():
    _migrate()
    path = _bg_custom_path(_client()) or _THEME_BG_DEFAULT
    if not os.path.exists(path):                       # 默认图缺失（异常部署）：退 204
        return "", 204
    return send_file(path, mimetype=ts.mime_of(path), conditional=True)


def api_theme_bg_post():
    """原始字节 = 上传并启用；JSON {"name": ...} = 选用图库中的一张。"""
    _migrate()
    client = _client()
    if request.is_json:
        return _bg_apply_gallery(request.get_json(silent=True), client)
    return _bg_apply_bytes(client)


def _bg_apply_bytes(client):
    """旧行为（旧客户端/网页兼容）：字节直接启用，同时入图库并记为本端 active。"""
    data = request.get_data()
    ext, err = _image_ext_or_error(data)
    if err:
        return err
    name = ts.save_image(_GALLERY_DIR, data, ext)
    ts.write_copy(_bg_base(client), data, ext)
    ts.write_active(_active_file(client), name)
    return jsonify({"ok": True, "client": client, "name": name, "message": "背景图已更新"})


def _bg_apply_gallery(body, client):
    """从图库选用：复制成本端背景副本并记 active；名字不在图库 → 400。"""
    name = body.get("name") if isinstance(body, dict) else None
    path = _gallery_path(name)
    if not path:
        return jsonify({"ok": False, "message": "图库中没有这张图片"}), 400
    with open(path, "rb") as f:
        data = f.read()
    ts.write_copy(_bg_base(client), data, ts.ext_of(name))
    ts.write_active(_active_file(client), name)
    return jsonify({"ok": True, "client": client, "name": name, "message": "已启用图库图片"})


def api_theme_bg_delete():
    _migrate()
    client = _client()
    ts.clear_copy(_bg_base(client))
    ts.clear_active(_active_file(client))
    return jsonify({"ok": True, "client": client, "message": "已恢复默认背景图"})


# ---------- 首页大横幅（hero，全局单份） ----------

def api_theme_hero_get():
    """当前首页横幅字节（自定义优先，否则默认 hero.jpg）。公开端点（<img> 同理）。"""
    path = ts.copy_path(_THEME_HERO_BASE) or _THEME_HERO_DEFAULT
    if not os.path.exists(path):
        return "", 204
    return send_file(path, mimetype=ts.mime_of(path), conditional=True)


def api_theme_hero_post():
    """字节 = 上传即启用（入图库并记 hero active）；JSON {"name"} = 从图库选用。"""
    if request.is_json:
        name = (request.get_json(silent=True) or {}).get("name")
        path = _gallery_path(name)
        if not path:
            return jsonify({"ok": False, "message": "图库中没有这张图片"}), 400
        with open(path, "rb") as f:
            data = f.read()
        ts.write_copy(_THEME_HERO_BASE, data, ts.ext_of(name))
        ts.write_active(_HERO_ACTIVE_FILE, name)
        return jsonify({"ok": True, "name": name, "message": "首页横幅已更新"})
    data = request.get_data()
    ext, err = _image_ext_or_error(data)
    if err:
        return err
    name = ts.save_image(_GALLERY_DIR, data, ext)
    ts.write_copy(_THEME_HERO_BASE, data, ext)
    ts.write_active(_HERO_ACTIVE_FILE, name)
    return jsonify({"ok": True, "name": name, "message": "首页横幅已更新"})


def api_theme_hero_delete():
    ts.clear_copy(_THEME_HERO_BASE)
    ts.clear_active(_HERO_ACTIVE_FILE)
    return jsonify({"ok": True, "message": "已恢复默认横幅"})


def api_theme_hero_active():
    """当前 hero 启用状态（图库页高亮用）：{"active": name}。"""
    return jsonify({"ok": True, "active": ts.read_active(_HERO_ACTIVE_FILE)})


# ---------- 图库 ----------

def api_theme_gallery_list():
    """图库列表：active 为本端选用（没有则空串），另给两端各自的值便于页面高亮。"""
    _migrate()
    client = _client()
    return jsonify({
        "ok": True,
        "client": client,
        "active": ts.read_active(_active_file(client)),
        "activeWeb": ts.read_active(_active_file("web")),
        "activeApp": ts.read_active(_active_file("app")),
        "heroActive": ts.read_active(_HERO_ACTIVE_FILE),
        "items": _gallery_items(),
    })


def api_theme_gallery_post():
    """上传入库，**不改当前背景**（想启用再 POST /api/theme/bg）。"""
    data = request.get_data()
    ext, err = _image_ext_or_error(data)
    if err:
        return err
    name = ts.save_image(_GALLERY_DIR, data, ext)
    return jsonify({"ok": True, "name": name, "message": "已加入图库"})


def api_theme_gallery_image(name):
    """图库图片字节（内置/用户统一）。**公开端点**（<img> 带不了 X-Token）。"""
    path = _gallery_path(name)
    if not path:
        return "", 404
    return send_file(path, mimetype=ts.mime_of(name), conditional=True)


def api_theme_gallery_delete(name):
    """删除用户图；内置图 400。删的是某端 active 时，该端恢复默认背景。"""
    if ts.is_builtin(name):
        return jsonify({"ok": False, "message": "内置图片不可删除"}), 400
    path = ts.path_in(_GALLERY_DIR, name)
    if not path:
        return jsonify({"ok": False, "message": "图库中没有这张图片"}), 404
    os.remove(path)
    _migrate()
    for client in _CLIENTS:
        if ts.read_active(_active_file(client)) == name:
            ts.clear_copy(_bg_base(client))
            ts.clear_active(_active_file(client))
    return jsonify({"ok": True, "message": "已从图库删除"})


ROUTES = [
    # POST/DELETE 只写 _state/ 下的主题文件（不碰文库、不调 _lib_touch）——
    # 不进 mutating 登记（SWR 守卫测试要求清单精确）；token 由全局闸门提供，
    # 只有 <img> 取字节的两个端点公开（api_theme_bg_get / api_theme_gallery_image）。
    ('get', '/api/theme/bg', api_theme_bg_get, False),
    ('post', '/api/theme/bg', api_theme_bg_post, False),
    ('delete', '/api/theme/bg', api_theme_bg_delete, False),
    ('get', '/api/theme/hero', api_theme_hero_get, False),
    ('post', '/api/theme/hero', api_theme_hero_post, False),
    ('delete', '/api/theme/hero', api_theme_hero_delete, False),
    ('get', '/api/theme/hero/active', api_theme_hero_active, False),
    ('get', '/api/theme/gallery', api_theme_gallery_list, False),
    ('post', '/api/theme/gallery', api_theme_gallery_post, False),
    ('get', '/api/theme/gallery/<name>', api_theme_gallery_image, False),
    ('delete', '/api/theme/gallery/<name>', api_theme_gallery_delete, False),
]


def register(app):
    for method, rule, fn, is_mut in ROUTES:
        getattr(app, method)(rule)(fn)
