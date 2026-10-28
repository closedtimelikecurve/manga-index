# -*- coding: utf-8 -*-
"""routes/admin.py —— admin 域路由（3.6.53 Stage6 从 app.py 抽出）。

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
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import zipfile

from flask import g, jsonify, request, send_file, send_from_directory
from werkzeug.datastructures import FileStorage

import common
import djc_parse as _dp
import meta_store as meta

from common import APP_DIR, ensure_dir
from panel.http import mutating
from routes.host import h


def api_panel_restart():
    """一键重启面板（网页顶部提示条的按钮调用）。新代码自检不过则拒绝重启。"""
    if not h()._panel_needs_restart():
        return jsonify({"ok": True, "message": "当前运行的就是最新代码，无需重启"})
    ok, err = h()._validate_fresh_code()
    if not ok:
        return jsonify({"ok": False, "message": "新代码自检失败，已拒绝重启：" + err}), 500
    h()._schedule_exec(0.8)
    return jsonify({"ok": True, "message": "面板正在重启，约 2~3 秒后自动恢复"})


def api_import():
    """导入文件（multipart 上传）：文件先落盘临时目录，与分块上传共用同一条处理管线。"""
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "message": "未收到文件"}), 400
    paths = request.form.getlist("paths")
    if len(paths) != len(files):                    # 兼容旧前端：无 paths 时按单文件处理
        paths = [(f.filename or "") for f in files]
    entries, tmps = [], []
    try:
        os.makedirs(h().UPLOAD_TMP, exist_ok=True)   # 启动清理后目录可能不存在，multipart 必须先建
        for f, rel in zip(files, paths):
            fd, tmp = tempfile.mkstemp(prefix="import_", dir=h().UPLOAD_TMP)
            os.close(fd)
            f.save(tmp)
            tmps.append(tmp)
            entries.append((FileStorage(open(tmp, "rb"), filename=f.filename), str(rel or ""), tmp))
        return h()._import_process(entries)
    finally:
        for e in entries:
            try:
                e[0].close()                       # Windows 上句柄开着会阻止 tmp 落盘清理
            except Exception:
                pass
        for t in tmps:
            try:
                os.unlink(t)
            except OSError:
                pass


def api_upload_chunk():
    """分块上传的单块（救不可靠中继链路）：原始字节 body 落为 part 文件。
    query: upload_id / fid（文件序号）/ idx（块序号）；失败重传同名 part 即覆盖。"""
    uid = request.args.get("upload_id", "")
    fid, idx = request.args.get("fid", ""), request.args.get("idx", "")
    if (not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", uid or "")
            or not fid.isdigit() or not idx.isdigit()):
        return jsonify({"ok": False, "message": "参数非法"}), 400
    d = os.path.join(h().UPLOAD_TMP, uid)
    os.makedirs(d, exist_ok=True)
    data = request.get_data()
    part = os.path.join(d, "%04d_%06d.part" % (int(fid), int(idx)))
    with open(part, "wb") as f:
        f.write(data)
    return jsonify({"ok": True, "received": len(data)})


def api_upload_commit():
    """分块上传收尾：按序拼接各文件的 part → 共用导入管线 → 清理会话分块。

    3.6.70 结构：拼接在 `_merge_upload_parts`（缺块时返回错误响应），本函数只管会话校验与清理。
    """
    body = request.get_json(silent=True) or {}
    uid = str(body.get("upload_id", ""))
    files = body.get("files") or []
    if (not uid or not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", uid)
            or not os.path.isdir(os.path.join(h().UPLOAD_TMP, uid)) or not isinstance(files, list)):
        return jsonify({"ok": False, "message": "上传会话不存在或无文件"}), 400
    d = os.path.join(h().UPLOAD_TMP, uid)
    entries = []
    try:
        merged_entries, bad = _merge_upload_parts(d, files)
        if bad:
            return bad
        entries = merged_entries
        return h()._import_process(entries)
    finally:
        for e in entries:
            try:
                e[0].close()
            except Exception:
                pass
        shutil.rmtree(d, ignore_errors=True)       # 导入完成/失败都清理本会话分块


def _merge_upload_parts(d, files):
    """按序拼接会话分块 → [(FileStorage, rel, merged_path)]。
    缺块等输入问题返回 (None, (响应, 状态码))，由调用方原样回包。"""
    entries, merged = [], []
    for i, meta in enumerate(files):
        if not isinstance(meta, dict) or not meta.get("name"):
            return None, (jsonify({"ok": False, "message": "files 元素须含 name/chunks"}), 400)
        merged_path = os.path.join(d, "final_%04d" % i)
        err = _append_parts(meta, d, i, merged_path)
        if err:
            return None, err
        merged.append(merged_path)
        entries.append((FileStorage(open(merged_path, "rb"), filename=meta["name"]),
                        str(meta.get("rel") or meta["name"]), merged_path))
    return entries, None


def _append_parts(meta, d, i, merged_path):
    """把一个文件的所有分块按序追加到 merged_path；缺块返回错误响应，否则 None。"""
    with open(merged_path, "wb") as out:
        for idx in range(int(meta.get("chunks") or 0)):
            part = os.path.join(d, "%04d_%06d.part" % (i, idx))
            if not os.path.exists(part):
                return (jsonify({"ok": False,
                                 "message": meta["name"] + " 缺少第 " + str(idx + 1) + " 块，请重传"}), 400)
            with open(part, "rb") as pf:
                shutil.copyfileobj(pf, out)
    return None


def api_backup_list():
    return jsonify({"ok": True, "backups": meta.backup_list()})


def api_backup_restore():
    """恢复快照：恢复前自动快照当前（可撤销），随后强制全量重扫。"""
    body = request.get_json(silent=True) or {}
    ok, msg = meta.backup_restore(str(body.get("file", "")))
    if not ok:
        return jsonify({"ok": False, "message": msg}), 400
    h().state.known["ready"] = False                     # 别名/解散/映射可能随快照回退
    rescanned = True
    try:
        h().get_library(force=True)
    except Exception:
        rescanned = False
        h().log.exception("备份恢复后重扫失败（库内容可能仍是旧的）")
    h()._lib_touch()
    if not rescanned:
        # 不得把失败说成成功：重扫没跑起来，库内容仍是恢复前的旧数据
        return jsonify({"ok": True,
                        "message": msg + "（但重扫失败，库内容可能未刷新，请手动重新扫描）"})
    return jsonify({"ok": True, "message": msg + "（已强制重扫）"})


def api_backup_export():
    """全量元数据 JSON 导出（灾备兜底，可离开本系统）。"""
    data = meta.export_json()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    resp = h().app.response_class(
        json.dumps(data, ensure_ascii=False, indent=1),
        mimetype="application/json")
    resp.headers["Content-Disposition"] = f"attachment; filename=meta_export_{stamp}.json"
    return resp


def api_export_manifest():
    """导出清单：{name, group, work, size, mtime, pages, circle, personals, bare, tags, kind}。"""
    w = h().find_work(request.args.get("group", ""), request.args.get("work", ""))
    if not w:
        return jsonify({"ok": False, "message": "作品不存在"}), 404
    size = None
    if w["kind"] == "archive":
        try:
            size = os.path.getsize(w["path"])
        except OSError:
            size = None
    return jsonify({"ok": True,
                    "name": w["name"], "group": request.args.get("group", ""),
                    "work": request.args.get("work", ""),
                    "file": os.path.basename(w["path"]),
                    "size": size, "mtime": w.get("mtime"), "pages": w.get("pages"),
                    "kind": w.get("kind"), "circle": w.get("circle"),
                    "personals": h()._work_authors(w), "bare": w.get("bare", ""),
                    "tags": [{"type": t, "name": n} for t, n in w["tags"]],
                    "downloadable": w["kind"] == "archive"})


def api_export_file():
    """作品原包下载（保原图，不走低带宽压缩；send_file conditional=True 支持断点续传）。
    文件夹作品 v1 不支持导出。须过 token 闸门（与 /api/page 一致）。"""
    w = h().find_work(request.args.get("group", ""), request.args.get("work", ""))
    if not w:
        return jsonify({"ok": False, "message": "作品不存在"}), 404
    if w["kind"] != "archive":
        return jsonify({"ok": False, "message": "文件夹作品暂不支持导出"}), 400
    ext = os.path.splitext(w["path"])[1].lower()
    resp = send_file(w["path"], mimetype=h()._EXPORT_MIME.get(ext, "application/octet-stream"),
                     conditional=True, as_attachment=True,
                     download_name=os.path.basename(w["path"]))
    return resp


def api_app_version():
    """返回 app_releases/ 内最新 APK 信息（versionCode 取文件名末段数字或默认 0）。"""
    best = None
    try:
        for n in os.listdir(h().APP_RELEASES_DIR):
            m = h()._APK_VER_RE.match(n)
            if not m:
                continue
            code = int(m.group(4) or 0)
            ver = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
            if best is None or code > best["versionCode"]:
                best = {"versionName": ver, "versionCode": code,
                        "apkUrl": "/app-releases/" + n, "file": n,
                        "size": os.path.getsize(os.path.join(h().APP_RELEASES_DIR, n))}
    except OSError:
        pass
    return jsonify({"ok": True, "latest": best})


def api_app_release_download(name):
    """下载 APK（受 token 闸门保护；文件名白名单校验，仅允许 app_releases 内的 .apk）。"""
    if "/" in name or ".." in name or not name.lower().endswith(".apk"):
        return jsonify({"ok": False, "message": "非法文件名"}), 400
    return send_from_directory(h().APP_RELEASES_DIR, name, as_attachment=True)


def _apply_safe_covers(body):
    """3.6.161 内测模式开关。返回 True = 本次**只**切了这一个开关。

    调用方据此提前返回：这个开关不碰文库数据，不该顺带触发 _lib_touch 的全库重扫。
    必须用 `in body` 判——关掉时值是 False，`if body.get(...)` 会让"关"永远不生效。
    """
    if "safe_covers" not in body:
        return False
    h().CFG["safe_covers"] = bool(body["safe_covers"])
    return not any(k in body for k in ("root", "name", "port", "originals"))


def api_config_post():
    body = request.get_json(silent=True) or {}
    if _apply_safe_covers(body):
        h().save_config(h().CFG)
        return jsonify(h().config_payload())
    if body.get("root"):
        r = os.path.abspath(os.path.expanduser(str(body["root"]).strip().strip('"').strip("'")))
        if not os.path.isdir(r):
            return jsonify({"ok": False, "message": "目录不存在：" + r}), 400
        h().CFG["root"] = r
    if body.get("name"):
        name = str(body["name"]).strip()
        if name:
            h().CFG["name"] = name
    if isinstance(body.get("port"), int) and 0 < body["port"] < 65536:
        h().CFG["port"] = body["port"]
    if "originals" in body and isinstance(body["originals"], list):
        h().CFG["originals"] = [str(x).strip() for x in body["originals"] if str(x).strip()]
        h().save_config(h().CFG)
        h()._reload_originals()
        # 3.6.19：manual original 标签不再被 sync_scan 自动清理 → 词条库删词条
        # 必须显式清库，否则分区永不消失（词条库与 zone 脱节）。
        for stale in meta.originals_stale_names(h().state.originals):
            meta.originals_remove(stale)
    else:
        h().save_config(h().CFG)      # CFG 含从 config.json 读回的 originals/ignore_files，不会被抹掉
    h()._lib_touch()                             # 强制重新扫描
    return jsonify(h().config_payload())

def api_rotate_token():
    """轮换主访问令牌（3.6.145）。

    用途：怀疑令牌泄露时**当场止损**，不必手改 `config.json` 再重启面板。

    **设备令牌不受影响**——已扫码的 APP 用的是 `dev-` 令牌（存在 pair_devices 表里），
    这正是"主令牌 / 设备令牌"分开的价值：换主令牌只影响"仍在用主令牌的客户端"（远程网页）。

    新令牌只在响应里出现一次（之后只存在于 `config.json`，要本地才看得到），
    前端必须提示用户保存。
    """
    new_token = "bks-" + secrets.token_hex(12)
    h().CFG["token"] = new_token
    h().save_config(h().CFG)
    return jsonify({"ok": True, "token": new_token})


ROUTES = [
    ('post', '/api/panel/restart', api_panel_restart, False),
    ('post', '/api/import', api_import, True),
    ('post', '/api/upload-chunk', api_upload_chunk, False),
    ('post', '/api/upload-commit', api_upload_commit, True),
    ('get', '/api/backup/list', api_backup_list, False),
    ('post', '/api/backup/restore', api_backup_restore, True),
    ('get', '/api/backup/export', api_backup_export, False),
    ('get', '/api/export/manifest', api_export_manifest, False),
    ('get', '/api/export/file', api_export_file, False),
    ('get', '/api/app-version', api_app_version, False),
    ('get', '/app-releases/<path:name>', api_app_release_download, False),
    ('post', '/api/config', api_config_post, True),
    ('post', '/api/config/rotate-token', api_rotate_token, False),
]


def register(app):
    for method, rule, fn, is_mut in ROUTES:
        if is_mut:
            fn = mutating(fn)
        getattr(app, method)(rule)(fn)
