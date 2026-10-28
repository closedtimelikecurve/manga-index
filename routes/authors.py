# -*- coding: utf-8 -*-
"""routes/authors.py —— authors 域路由（3.6.53 Stage6 从 app.py 抽出）。

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


def api_author_aliases_get():
    """返回 {alias: canonical} 与反向 {canonical: [alias...]}（标签云/别名管理用）。
    ?kind=circle 取社团别名，默认 kind=author 取笔名别名。"""
    kind = h()._alias_kind()
    aliases = h()._aliases_of(kind)
    rev = {}
    for a, c in aliases.items():
        rev.setdefault(c, []).append(a)
    return jsonify({"ok": True, "aliases": aliases, "canonicals": rev, "kind": kind})


def api_author_aliases_post():
    """登记一条别名：{alias: 别名, canonical: 正名, kind: author|circle}（3.0 起写元数据库）。
    写库后强制全量重扫——笔名：作者字段/标签归并；社团：作品并入正名社团。"""
    body = request.get_json(silent=True) or {}
    kind = h()._alias_kind(body)
    alias = str(body.get("alias", "")).strip()
    canonical = str(body.get("canonical", "")).strip()
    if not alias or not canonical:
        return jsonify({"ok": False, "message": "别名与正名都必须非空"}), 400
    if kind == "original":
        # 3.6.19 原作别名：词条原样（原作名不是社团/作者名，不过 _canon_circle 清洗）；
        # 正名沿原作别名链取终点，防 A→B→A 成环。
        # 3.6.20 #25：终点再宽松归一到词条库规范名（三位一体：词条库/DB 标签/
        # 别名表同存规范名，防「Fate Grand Order」与「FateGrand Order」分裂两分区）。
        # 注意：alias 侧不做宽松拒绝——下划线/大小写变体宽松串虽同，但 _norm 不
        # 去分隔符、解析器确实不归并，登记别名正是补这个缺口的（#20 核心场景）。
        if alias == canonical:
            return jsonify({"ok": False, "message": "别名与正名相同，无需登记"}), 400
        canonical = h()._canon_original(h()._canon_original_name(canonical))
        if canonical == alias:
            return jsonify({"ok": False, "message": "别名与正名相同，无需登记"}), 400
    else:
        alias = h()._canon_circle(alias)
        canonical = h()._canon_circle(canonical)
        if alias == canonical:
            return jsonify({"ok": False, "message": "别名与正名相同，无需登记"}), 400
        # 正名自身若已是别人的别名，沿链取终点（A→B 再把 B→C 登记为 B→C 而非制造环）
        canonical = h()._canon_circle_name(canonical) if kind == "circle" else h()._canon_author(canonical)
    try:
        meta.upsert_alias(alias, canonical, kind)
    except Exception as e:
        return jsonify({"ok": False, "message": "写入失败：" + str(e)}), 500
    extra = ""
    if kind == "original":
        # 3.6.20 #26：别名分区整体迁入正名分区。重扫只会保留 manual original 标签
        # （sync_scan 的 want_t 放行），不显式迁移的话别名分区永远单列——
        # 用户在别名页设置的合并就不落地。迁完再重扫，have_t 已是正名行。
        merged = meta.originals_merge(canonical, [alias])
        # 显式接住返回值（_reload_originals 自带 global 副作用，与裸调用等价）；
        # 别名必须先登记进解析映射，随后的 force 重扫才能把文件名里的别名写法
        # 折叠到正名，而不是产出旧名标签。
        h()._reload_originals()
        if merged:
            extra = f"；原「{alias}」分区 {merged} 部作品已并入"
    h().get_library(force=True)     # 别名生效需要重扫（作者字段归并 / 社团作品并入 / 原作标签归并）
    what = {"circle": "社团", "original": "同人"}.get(kind, "笔名")
    return jsonify({"ok": True,
                    "message": f"已登记{what}别名：{alias} → {canonical}（已重扫生效）{extra}"})


def api_author_aliases_delete():
    """删除一条别名：{alias, kind?}（元数据库删除；config 迁移遗留同款一并清掉，
    防止合并视图把它"复活"）。删除后重扫，作品恢复原笔名/社团重新单列。
    kind=original（3.6.19）：删后重载词条库，变体不再归并到该正名。"""
    body = request.get_json(silent=True) or {}
    kind = h()._alias_kind(body)
    alias = str(body.get("alias", "")).strip()
    cfg_key = {"circle": "circle_aliases", "original": "original_aliases"}.get(
        kind, "author_aliases")
    in_db = False
    try:
        in_db = meta.delete_alias(alias, kind)
    except Exception as e:
        return jsonify({"ok": False, "message": "删除失败：" + str(e)}), 500
    in_cfg = alias in (h().CFG.get(cfg_key) or {})
    if not in_db and not in_cfg:
        return jsonify({"ok": False, "message": "别名不存在"}), 404
    if in_cfg:                                  # 清掉 config 迁移遗留（只此一处清理性写回）
        cur = {k: v for k, v in (h().CFG.get(cfg_key) or {}).items() if k != alias}
        h().CFG[cfg_key] = cur
        h().save_config(h().CFG)
    if kind == "original":
        h()._reload_originals()
    h().get_library(force=True)
    return jsonify({"ok": True, "message": f"已删除别名：{alias}（已重扫生效）"})

ROUTES = [
    ('get', '/api/author-aliases', api_author_aliases_get, False),
    ('post', '/api/author-aliases', api_author_aliases_post, False),
    ('post', '/api/author-aliases/delete', api_author_aliases_delete, False),
]


def register(app):
    for method, rule, fn, is_mut in ROUTES:
        if is_mut:
            fn = mutating(fn)
        getattr(app, method)(rule)(fn)
