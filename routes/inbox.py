# -*- coding: utf-8 -*-
"""routes/inbox.py —— inbox 域路由（3.6.53 Stage6 从 app.py 抽出）。

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

from common import APP_DIR, ensure_dir
from panel.http import mutating
from routes.host import h


def api_inbox_list():
    h()._inbox_sync()
    items = []
    for it in meta.inbox_list():
        try:
            proposal = json.loads(it["proposal"]) if it["proposal"] else {}
        except Exception:
            proposal = {}
        items.append({**it, "proposal": proposal, "exists": os.path.isfile(it["src"])})
    pending = sum(1 for it in items if it["state"] == "pending" and it["exists"])
    return jsonify({"ok": True, "total": len(items), "pending": pending, "items": items,
                    "parts": [{"name": n, "size": s, "age_h": round(a, 1)}
                              for _p, n, s, a in h()._inbox_parts()]})


def api_inbox_confirm():
    """确认入库：{id, circle?}（circle 可覆盖提案的社团；画师可在入库后用增补信息改）。"""
    body = request.get_json(silent=True) or {}
    try:
        iid = int(body.get("id") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "缺少 id"}), 400
    it = meta.inbox_get(iid)
    if not it:
        return jsonify({"ok": False, "message": "收件项不存在"}), 404
    if it["state"] == "confirmed":
        return jsonify({"ok": False, "message": "该项已入库"}), 400
    ok, msg = h()._inbox_confirm_one(it, body.get("circle"), force=bool(body.get("force")))
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)


def api_inbox_purge_parts():
    """清掉 _inbox 里的下载半成品（crawl_wnacg 断点续传留下的 .part/.part.src）。
    这些文件不是作品、收件箱不展示，留着只会让重爬误判「库里已有」——
    这里给一个显式出口，直接删除（不进回收站，不可还原）。"""
    body = request.get_json(silent=True) or {}
    try:
        max_age = float(body.get("max_age_h") or 0)
    except (TypeError, ValueError):
        max_age = 0
    removed, kept, failed = 0, 0, []
    for path, name, _size, age in h()._inbox_parts():
        if max_age > 0 and age < max_age:
            kept += 1
            continue
        if h()._delete(path):
            removed += 1
        else:
            failed.append(name)
    msg = f"已清理 {removed} 个下载半成品（已直接删除）" + (f"，保留 {kept} 个较新的" if kept else "")
    if failed:
        msg += f"，{len(failed)} 个被占用清理失败"
    return jsonify({"ok": not failed, "removed": removed, "kept": kept,
                    "failed": failed[:10], "message": msg})


def api_inbox_delete():
    """删除：文件直接删除（不进回收站，不可还原）+ 移除登记。"""
    body = request.get_json(silent=True) or {}
    try:
        iid = int(body.get("id") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "缺少 id"}), 400
    it = meta.inbox_get(iid)
    if not it:
        return jsonify({"ok": False, "message": "收件项不存在"}), 404
    if os.path.isfile(it["src"]):
        h()._archive_quiesce([it["src"]])
        if not h()._delete(it["src"]):
            return jsonify({"ok": False, "message": "删除失败（文件可能被占用）"}), 500
    meta.inbox_delete(iid)
    return jsonify({"ok": True, "message": "已删除：" + it["name"]})


def api_inbox_confirm_all():
    """一键入库：全部 pending 提案按预案归档；疑似重复项跳过（留给人工裁决）。"""
    h()._inbox_sync()
    confirmed = skipped = 0
    failed = []
    for it in meta.inbox_list():
        if it["state"] != "pending" or not os.path.isfile(it["src"]):
            continue
        try:
            proposal = json.loads(it["proposal"] or "{}")
        except Exception:
            proposal = {}
        if proposal.get("kind") == "unsupported":
            continue
        if proposal.get("dup"):
            skipped += 1
            continue
        ok, msg = h()._inbox_confirm_one(it, None)
        if ok:
            confirmed += 1
        else:
            failed.append(f"{it['name']}：{msg}")
    h()._lib_touch()
    msg = f"已入库 {confirmed} 项"
    if skipped:
        msg += f"，跳过疑似重复 {skipped} 项（请逐条裁决）"
    if failed:
        msg += f"，失败 {len(failed)} 项（{failed[0][:60]}）"
    return jsonify({"ok": not failed, "confirmed": confirmed, "skipped": skipped,
                    "failed": failed[:10], "message": msg})

ROUTES = [
    ('get', '/api/inbox/list', api_inbox_list, True),
    ('post', '/api/inbox/confirm', api_inbox_confirm, True),
    ('post', '/api/inbox/purge-parts', api_inbox_purge_parts, False),
    ('post', '/api/inbox/delete', api_inbox_delete, False),
    ('post', '/api/inbox/confirm-all', api_inbox_confirm_all, True),
]


def register(app):
    for method, rule, fn, is_mut in ROUTES:
        if is_mut:
            fn = mutating(fn)
        getattr(app, method)(rule)(fn)
