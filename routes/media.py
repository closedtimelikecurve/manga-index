# -*- coding: utf-8 -*-
"""routes/media.py —— media 域路由（3.6.53 Stage6 从 app.py 抽出）。

规矩：
  * **不在本模块 import app**（`python app.py` 会造成二次导入 / 双 Flask 实例）；
    一律 `h().xxx` 按名解析，保证 monkeypatch 仍然生效。
  * 端点函数保持模块级；ROUTES 与 register() 放在文件末尾。
"""
import hashlib
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import zipfile

from flask import g, jsonify, request, send_file, send_from_directory

import common
import djc_parse as _dp
import meta_store as meta

from common import APP_DIR, ensure_dir, display_name
from panel.http import mutating
from panel import safecover
from routes.host import h


def api_pages():
    """作品全部页面信息（阅读器用）：返回总页数等元信息。"""
    gname = request.args.get("group", "")
    wname = request.args.get("work", "")
    w = h().find_work(gname, wname)
    if not w:
        return jsonify({"ok": False, "message": "作品不存在"}), 404
    total = len(w.get("page_files") or [])
    if not total:
        return jsonify({"ok": False, "message": "该作品没有可浏览的页面"}), 404
    kinds = [h().media_kind(h().page_media_name(pg)) for pg in (w.get("page_files") or [])]
    return jsonify({
        "ok": True,
        "group": gname, "work": wname,
        "name": display_name(w["name"]), "personal": w["personal"],
        "total": total,
        "kinds": kinds,        # 每页媒体类型："image" | "gif" | "video"(webm)
        "ver": h()._work_ver(w),   # 页面 URL 的缓存键（删首页图片后页序变化也能让 APP 丢缓存）
        "low": h().client_wants_low(),   # 本客户端当前是否按"远程低带宽"发图（APP 可据此提示）
        "tags": [{"type": t, "name": n} for t, n in w["tags"]],
        # 音声作品（含 mp3 等音频轨）标记（仅存在时输出，纯新增字段，旧端忽略）
        **({"audio": True} if h()._work_audio_entries(w) else {}),
        # 多版本作品（3.2.4：如 RJ 包的 日文原版/汉化版 两个子目录）——仅存在时输出
        **({"versions": h()._page_versions(w)} if h()._page_versions(w) else {}),
    })


def api_audio_manifest():
    """音声清单：轨道（natural 序）+ 每轨同名 lrc 解析结果（毫秒时间轴）。无音声 → tracks 空。"""
    w = h().find_work(request.args.get("group", ""), request.args.get("work", ""))
    if not w:
        return jsonify({"ok": False, "message": "作品不存在"}), 404
    tracks = []
    for _loc, name, size in h()._work_audio_entries(w):
        tracks.append({"name": name, "size": size, "lrc": h()._audio_lrc_for(w, name)})
    return jsonify({"ok": True, "total": len(tracks), "tracks": tracks})


def api_audio():
    """音频轨流式播放（conditional=True 支持 Range 拖进度条）。
    压缩包作品先把整轨解压到临时缓存（同 webm 页机制，LRU 管理），文件夹作品直接发原文件。"""
    w = h().find_work(request.args.get("group", ""), request.args.get("work", ""))
    try:
        n = int(request.args.get("n", "0"))
    except ValueError:
        n = -1
    if not w:
        return jsonify({"ok": False, "message": "作品不存在"}), 404
    entries = h()._work_audio_entries(w)
    if not entries or n < 0 or n >= len(entries):
        return jsonify({"ok": False, "message": "音频轨不存在"}), 404
    loc, name, _size = entries[n]
    ext = os.path.splitext(name)[1].lower()
    mime = h()._AUDIO_MIME.get(ext, "application/octet-stream")
    if w.get("kind") == "archive":
        data = h()._archive_read(os.path.abspath(w["path"]), loc)
        if not data:
            return jsonify({"ok": False, "message": "音频读取失败"}), 500
        p = h()._video_tmp_file(os.path.abspath(w["path"]) + "|audio|" + name, data, ext=ext)
        if not p:
            return jsonify({"ok": False, "message": "音频缓存失败"}), 500
        return send_file(p, mimetype=mime, conditional=True)
    if not h()._path_in_root(loc):
        return jsonify({"ok": False, "message": "音频路径不在文库根内"}), 400
    return send_file(loc, mimetype=mime, conditional=True)


PLACEHOLDER_IMG = safecover.PLACEHOLDER_IMG


def _safe_image_response(mime_hint="image/png"):
    """3.6.118 测试模式（--safe-images）：一律回占位图（固定 ETag，可 304）。"""
    return send_file(PLACEHOLDER_IMG, mimetype="image/png",
                     etag="safe-placeholder", conditional=True)


def api_page():
    """作品第 n 页内容（0 起）：图片或 webm 视频。
    文件夹作品与视频临时缓存走 send_file(conditional=True)，支持 Range（视频可拖进度条）。

    3.6.70 结构：低带宽转码分支抽到 `_lowres_page_response`。
    """
    if getattr(h(), "SAFE_IMAGES", False):
        return _safe_image_response()
    w = h().find_work(request.args.get("group", ""), request.args.get("work", ""))
    try:
        n = int(request.args.get("n", "0"))
    except ValueError:
        n = -1
    if not w:
        return jsonify({"ok": False, "message": "作品不存在"}), 404
    kind, payload, mime = h().page_source(w, n)
    if not payload:
        return jsonify({"ok": False, "message": "页面不存在"}), 404
    # 远程低带宽：图片按需转码成小图（webm 视频保持原样，否则拖不动进度条）
    if mime != "video/webm" and h().client_wants_low():
        resp = _lowres_page_response(w, n, kind, payload, mime)
        if resp is not None:
            return resp
    if kind == "file":
        resp = send_file(payload, mimetype=mime, conditional=True)
    else:
        # 3.3.0 压缩包抽出的页图（BytesIO）同样补 ETag/304 —— 键 = 作品版本 + 页号，
        # 删页/换图后 _work_ver 变化自动失效；磁盘文件路径本就走 conditional=True
        resp = send_file(io.BytesIO(payload), mimetype=mime,
                         etag="pg-%s-%d" % (h()._work_ver(w), n), conditional=True)
    resp.headers["Cache-Control"] = "public, max-age=3600"
    resp.headers["X-Img-Mode"] = "orig"
    return resp


def _lowres_page_response(w, n, kind, payload, mime):
    """低带宽版页面；转码不可用时返回 None（调用方回退原图）。"""
    pg = (w.get("page_files") or [])[n]
    src = pg.get("p") or pg.get("z") or pg.get("r") or ""
    src_name = h().page_media_name(pg)
    data = payload if kind == "bytes" else _read_bytes(payload)
    if not data:
        return None
    low = h().lowres_image(data, src_name, _lowres_seed(src, src_name))
    if not low:
        return None
    # 3.3.0 字节响应补 ETag/304：此前低带宽转码图无协商缓存，
    # max-age 过期后即使内容没变也要经 Tailscale 全量重传
    resp = send_file(io.BytesIO(low[0]), mimetype=low[1],
                     etag="low-%s-%d" % (h()._work_ver(w), n), conditional=True)
    resp.headers["Cache-Control"] = "public, max-age=3600"
    resp.headers["X-Img-Mode"] = "low"
    return resp


def _read_bytes(path):
    """读磁盘上的页图；读不了返回 None（调用方回退原图，不 500）。"""
    try:
        with open(str(path), "rb") as f:
            return f.read()
    except OSError:
        return None


def _lowres_seed(src, src_name):
    """转码缓存键的种子：源路径 + mtime_ns + 页名（取不到 mtime 时退化为两段）。"""
    base = os.path.abspath(str(src))
    try:
        return "%s|%s|%s" % (base, os.stat(base).st_mtime_ns, src_name)
    except OSError:
        return "%s|%s" % (base, src_name)


def api_cover():
    # 3.6.161 内测模式优先：用户主动选的占位图比 --safe-images 的灰度图更贴近真实界面
    safe = safecover.response()
    if safe is not None:
        return safe
    if getattr(h(), "SAFE_IMAGES", False):
        return _safe_image_response()
    w = h().find_work(request.args.get("group", ""), request.args.get("work", ""))
    if not w or not w.get("cover"):
        return jsonify({"ok": False, "message": "封面不存在"}), 404
    kind, payload, mime = h().cover_payload(w)
    if not payload:
        return jsonify({"ok": False, "message": "封面读取失败"}), 404
    if kind == "file":
        resp = send_file(payload, mimetype=mime, conditional=True)
    else:
        # 3.3.0 封面字节响应补 ETag/304（键跟 _work_ver 走，与 coverVer 缓存键同源）
        resp = send_file(io.BytesIO(payload), mimetype=mime,
                         etag="cv-%s" % h()._work_ver(w), conditional=True)
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


def api_open():
    body = request.get_json(silent=True) or {}
    gname = str(body.get("group", ""))
    wname = str(body.get("work", ""))
    target = body.get("target", "image")
    w = h().find_work(gname, wname)
    if not w:
        return jsonify({"ok": False, "message": "未找到该作品，请先重新扫描"}), 404
    # 防御纵深：只允许打开文库根目录内的路径（路径虽来自本地扫描，仍显式校验）
    root_real = os.path.realpath(h().CFG.get("root", ""))
    target_real = os.path.realpath(str(w.get("path", "")))
    if not target_real.lower().startswith(root_real.lower() + os.sep):
        return jsonify({"ok": False, "message": "目标路径不在文库根目录内，已拒绝"}), 400
    if target == "folder":
        ok, msg = h().open_work_folder(w)
    else:
        ok, msg = h().open_work_image(w)
    return jsonify({"ok": ok, "message": msg})

ROUTES = [
    ('get', '/api/pages', api_pages, False),
    ('get', '/api/audio/manifest', api_audio_manifest, False),
    ('get', '/audio', api_audio, False),
    ('get', '/page', api_page, False),
    ('get', '/cover', api_cover, False),
    ('post', '/api/open', api_open, False),
]


def register(app):
    for method, rule, fn, is_mut in ROUTES:
        if is_mut:
            fn = mutating(fn)
        getattr(app, method)(rule)(fn)
