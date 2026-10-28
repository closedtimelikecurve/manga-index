# -*- coding: utf-8 -*-
"""routes/manage.py —— manage 域路由（3.6.53 Stage6 从 app.py 抽出）。

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


def api_delete():
    """删除单部作品（右键菜单）：直接删除（不进回收站，不可还原）。"""
    body = request.get_json(silent=True) or {}
    w = h().find_work(str(body.get("group", "")), str(body.get("work", "")))
    if not w:
        return jsonify({"ok": False, "message": "未找到该作品，请先重新扫描"}), 404
    path = w["path"]
    if not h()._path_in_root(path):
        return jsonify({"ok": False, "message": "目标路径不在文库根目录内，已拒绝"}), 400
    if not h()._delete(path):
        return jsonify({"ok": False, "message": "删除失败（文件可能被占用）"}), 500
    h()._invalidate_after_delete(path)
    try:
        # 重分组后显示 group 名（圈子名）可能与作品落库 key 的归档名（真实目录）不同，
        # 用作品自身的 _group 锚定回真实目录，避免 forget 删错记录（3.6.12）。
        meta.forget_work(h()._work_key(w.get("_group") or body.get("group", ""),
                                   str(body.get("work", ""))))
    except Exception:
        h().log.exception("清理作品元数据失败（可能残留阅读/评分记录）")
    return jsonify({"ok": True, "message": "已删除：" + os.path.basename(path)})


def api_delete_cover():
    """删除作品首页图片（压缩包层面）：把封面页条目从 .zip/.cbz 内物理移除。
    重扫后封面与首页自动变为原第二页。文件夹作品与 .rar/.cbr 无压缩包重写能力
    （rarfile 只读），一律拒绝并说明；仅剩 1 页时拒绝（删完变空包）。

    3.6.67 结构：zip 重写在 `_rewrite_zip_without_entry`，本函数只做校验与回包。
    """
    body = request.get_json(silent=True) or {}
    w = h().find_work(str(body.get("group", "")), str(body.get("work", "")))
    if not w:
        return jsonify({"ok": False, "message": "未找到该作品，请先重新扫描"}), 404
    path = w["path"]
    if not h()._path_in_root(path):
        return jsonify({"ok": False, "message": "目标路径不在文库根目录内，已拒绝"}), 400
    ext = os.path.splitext(path)[1].lower()
    if w["kind"] != "archive" or ext not in (".zip", ".cbz"):
        return jsonify({"ok": False,
                        "message": "仅支持压缩包作品（.zip/.cbz）：文件夹作品与 .rar/.cbr 无法在压缩包层面删除首页图片"}), 400
    if len(w.get("page_files") or []) <= 1:
        return jsonify({"ok": False, "message": "作品仅剩 1 页，删除后将为空包，已拒绝"}), 400
    cover = w.get("cover")
    if not cover or cover[0] != "zip":
        return jsonify({"ok": False, "message": "未找到可删除的封面图片（封面缺失或为视频页）"}), 400
    entry = cover[2]
    err, status = _rewrite_zip_without_entry(path, entry)
    if err:
        return jsonify({"ok": False, "message": err}), status
    h()._invalidate_after_delete(path)
    return jsonify({"ok": True, "message": "已删除首页图片：" + entry})


def _rewrite_zip_without_entry(path, entry):
    """把 entry 从 zip 里物理移除（同目录临时文件 + os.replace 原子替换）。
    返回 (错误文案, HTTP 状态)；成功返回 ("", 0)，原包在失败时保持完好。"""
    abspath = os.path.abspath(path)
    with h()._archive_lock:                      # 先弃用本进程已打开的压缩包句柄
        for k in [k for k in h()._archive_handles if k.lower() == abspath.lower()]:
            h()._archive_handles.pop(k, None)
    try:
        fd, tmp = tempfile.mkstemp(prefix="cover_del_", suffix=".zip.tmp",
                                   dir=os.path.dirname(abspath))
        os.close(fd)
        try:
            with zipfile.ZipFile(path, "r") as zin:
                infos = zin.infolist()
                if entry not in {i.filename for i in infos}:
                    return "封面条目不存在（请重新扫描后重试）", 400
                with zipfile.ZipFile(tmp, "w") as zout:
                    for i in infos:
                        if i.filename == entry:
                            continue
                        zout.writestr(_zip_info(i), zin.read(i.filename))
                    if zin.comment:
                        zout.comment = zin.comment
            # 读句柄已关闭，同目录 os.replace 原子替换；失败时原包完好
            os.replace(tmp, path)
            tmp = None
        finally:
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
    except PermissionError:
        return "压缩包被占用（阅读器/其他程序正打开它），请关闭后重试", 500
    except OSError as e:
        return "压缩包重写失败：" + str(e), 500
    return "", 0


def _zip_info(i):
    """复制一个 ZipInfo 的属性（时间/压缩方式/属性/注释），重写后条目不丢元数据。"""
    zi = zipfile.ZipInfo(i.filename, date_time=i.date_time)
    zi.compress_type = i.compress_type
    zi.external_attr = i.external_attr
    zi.internal_attr = i.internal_attr
    zi.create_system = i.create_system
    zi.comment = i.comment
    return zi


def api_artist_rename():
    """画师改名/合并：名下全部作品的**文件名作者词条、文件本体、DB 记录**联动迁移。

    作者名编码在作品文件名的词条括号里（[社团(作者)] / [作者]），只改数据库的话
    下一轮扫描就会从文件名把旧名解析回来——所以必须连文件一起改名（与社团改名
    「改目录、文件不动」相反）。目标名已是库中画师 → 合并：作品并入该画师，
    旧名降级为别名保留检索入口。

    3.6.67 结构：逐部改名在 `_rename_artist_works`，本函数只做校验/快照/收尾。
    """
    body = request.get_json(silent=True) or {}
    old = h()._canon_author(str(body.get("from", "")).strip())
    new = _dp.sanitize_windows_name(str(body.get("to", "")).strip())
    if not old:
        return jsonify({"ok": False, "message": "缺少原画师名"}), 400
    if not new:
        return jsonify({"ok": False, "message": "新名称为空"}), 400
    if new == h().INBOX_GROUP:
        return jsonify({"ok": False, "message": "不能改名为「收件箱」"}), 400
    if new == old:
        return jsonify({"ok": True, "message": "名称未变化", "renamed": 0, "merged": False})
    rows = meta.author_work_paths(old)
    if not rows:
        return jsonify({"ok": False, "message": "未找到该画师的作品，请先重新扫描"}), 404
    merged = bool(meta.author_work_paths(h()._canon_author(new)))
    try:
        meta.snapshot(f"画师改名 {old}→{new}")   # 备份时间机器
    except Exception:
        h().log.exception("画师改名：快照失败，本次操作没有回滚点")
    h()._archive_quiesce([r[3] for r in rows])       # 关句柄 + 等读线程排空，免 WinError 32
    moved, skipped, errors, work_renames = _rename_artist_works(rows, old, new)
    meta.rename_author(old, new)
    # 3.6.31：画师封面是按 (社团, 作品名) 存的坐标，作品文件名改了坐标就失效 →
    # 跟随改名；目标画师自己设过封面时保留那份（正名优先）。
    h()._region_cover_migrate("artist", old, new, work_renames=work_renames)
    msg = _artist_rename_finish(moved, skipped, errors, merged, old, new)
    return jsonify({"ok": True, "message": msg, "renamed": moved,
                    "merged": merged, "new_name": new})


def _artist_rename_finish(moved, skipped, errors, merged, old, new):
    """画师改名收尾：作废扫描索引（文件名批量变化 → path 缓存全过期）+ 组装结果消息。

    3.7.43 结构：从 api_artist_rename 尾部抽出（原函数 53 行）。
    """
    try:
        os.remove(h().INDEX_FILE)
    except OSError:
        pass
    with h().INDEX_LOCK:
        h().state.index_loaded = False
        h().state.reset_index()
    h()._lib_touch()
    msg = f"已完成：「{old}」→「{new}」，{moved} 部作品跟随改名"
    if merged:
        msg += "（目标画师已存在，已合并）"
    if skipped:
        msg += f"，{skipped} 部无需改动"
    if errors:
        msg += "；失败：" + "；".join(errors[:3])
    return msg


def _new_work_name(path, old, new):
    """算出该作品改名后的文件名；无需改动返回 ""（作者词条不在其中 / 换成同名）。"""
    fname = os.path.basename(path)
    info = _dp.parse_filename(fname)
    if old not in (info.get("personals") or []):
        return ""                           # 该作者不在此作品词条里（历史脏数据）
    new_fname = _dp.rename_personal_in_name(fname, old, new)
    return "" if new_fname == fname else new_fname


def _rename_verdict(path, new_path, wname, errors):
    """改名可行性：'ok' 可改；'same' 路径没变（跳过）；'blocked' 已被别的文件占用（记错误）。

    Windows 大小写不敏感：纯大小写改名（someartist→SomeArtist）时 new_path "已存在"
    其实是**同一文件**，必须放行，否则 DB 改了名、文件原地不动。
    """
    if os.path.abspath(new_path) == os.path.abspath(path):
        return "same"
    same_case = os.path.normcase(new_path) == os.path.normcase(path)
    if os.path.exists(new_path) and not same_case:
        errors.append(f"{wname}：目标文件名已存在")
        return "blocked"
    return "ok"


def _rename_artist_works(rows, old, new):
    """逐部作品改名并让 DB key 跟随。返回 (moved, skipped, errors, work_renames)。"""
    moved = skipped = 0
    errors, work_renames = [], {}      # 旧作品名 → 新作品名（封面坐标跟随文件名改名）
    for key, gname, wname, path in rows:
        new_fname = _new_work_name(path, old, new)
        if not new_fname:
            skipped += 1
            continue
        new_path = os.path.join(os.path.dirname(path), new_fname)
        verdict = _rename_verdict(path, new_path, wname, errors)
        if verdict == "same":
            skipped += 1
            continue
        if verdict == "blocked":
            continue
        try:
            os.rename(path, new_path)
        except OSError as e:
            errors.append(f"{wname}：{e}")
            continue
        moved += 1
        # key 跟随：DB 侧作品名口径**不含扩展名**（扫描时 splitext(f.name)[0]），
        # 必须去掉扩展名再拼 key，否则 works 行匹配不上、进度/评分会留在旧 key 上
        ext = os.path.splitext(os.path.basename(path))[1]
        old_stem = os.path.basename(path)[:-len(ext)] if ext else os.path.basename(path)
        new_stem = new_fname[:-len(ext)] if ext else new_fname
        work_renames[old_stem] = new_stem
        new_key = h()._work_key(gname, new_stem)
        if new_key != key:
            meta.rename_work_key(key, new_key)  # reading/ratings/收藏等按 key 跟随
    return moved, skipped, errors, work_renames


def api_blacklist_get():
    """词条黑名单（含内置项与用户自定义项）与豁免名单。"""
    custom = [x for x in (h().CFG.get("term_blacklist") or []) if str(x).strip()]
    exempt = [x for x in (h().CFG.get("term_whitelist") or []) if str(x).strip()]
    return jsonify({"ok": True, "builtin": h()._TERM_BLACKLIST_BUILTIN,
                    "custom": custom, "exempt": exempt,
                    "note": "内置项不可删；自定义/豁免项可编辑（子串命中、不区分大小写）"})


def api_blacklist_post():
    """编辑词条黑名单（term_blacklist）与豁免名单（term_whitelist）：
    body {"custom": [词条...], "exempt": [词条...]} 全量替换。
    任一名单变化都会使扫描索引失效，下次访问自动全量重扫。"""
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("custom", []), list) or not isinstance(body.get("exempt", []), list):
        return jsonify({"ok": False, "message": "格式错误：custom/exempt 须为数组"}), 400
    custom = [str(x).strip() for x in body.get("custom", []) if str(x).strip()]
    exempt = [str(x).strip() for x in body.get("exempt", []) if str(x).strip()]
    try:
        meta.snapshot("黑名单保存前")         # 备份时间机器（黑名单变化会使解析结果重算）
    except Exception:
        h().log.exception("黑名单变更：快照失败，本次操作没有回滚点")
    h().CFG["term_blacklist"] = custom
    h().CFG["term_whitelist"] = exempt
    h().save_config(h().CFG)
    h()._lib_touch()
    return jsonify({"ok": True,
                    "message": f"黑名单已保存（自定义 {len(custom)} 条，豁免 {len(exempt)} 条），将自动重扫生效"})


def api_set_cover():
    """把某作品首图设为某个区域的封面。
    scope ∈ {circle, artist, original}；name = 区域名（社团名 / 画师名 / 原作分区名）；
    group = 作品物理所在社团（或交叉引用所在的视图社团，二者同属该作品的归属社团列表，
            find_work 都能命中）；work = 作品名。
    覆盖按 (group, work) 存，渲染时按该作品物理社团取首图 → 自动跟随首图删除/作品删除。"""
    body = request.get_json(silent=True) or {}
    scope = body.get("scope")
    name = str(body.get("name", "")).strip()
    group = str(body.get("group", "")).strip()
    work = str(body.get("work", "")).strip()
    if scope not in ("circle", "artist", "original") or not name or not group or not work:
        return jsonify({"ok": False, "message": "参数缺失或 scope 非法"}), 400
    wk = h().find_work(group, work)
    if not wk:
        return jsonify({"ok": False, "message": "作品不存在或不在该社团下"}), 404
    if not wk.get("cover"):
        return jsonify({"ok": False, "message": "该作品没有可用封面（首图缺失）"}), 400
    h()._region_cover_set(scope, name, group, work)
    h()._lib_touch()        # 让安卓端轮询 rev 感知封面变动并刷新
    return jsonify({"ok": True, "message": "已设为封面"})


def api_clear_cover():
    """清除某区域的封面覆盖，回退到派生的「最新有封面作品首图」。"""
    body = request.get_json(silent=True) or {}
    scope = body.get("scope")
    name = str(body.get("name", "")).strip()
    if scope not in ("circle", "artist", "original") or not name:
        return jsonify({"ok": False, "message": "参数缺失或 scope 非法"}), 400
    h()._region_cover_set(scope, name, "", "")
    h()._lib_touch()
    return jsonify({"ok": True, "message": "已清除封面覆盖"})

ROUTES = [
    ('post', '/api/delete', api_delete, True),
    ('post', '/api/delete-cover', api_delete_cover, True),
    ('post', '/api/artist/rename', api_artist_rename, True),
    ('get', '/api/blacklist', api_blacklist_get, False),
    ('post', '/api/blacklist', api_blacklist_post, True),
    ('post', '/api/set-cover', api_set_cover, True),
    ('post', '/api/clear-cover', api_clear_cover, True),
]


def register(app):
    for method, rule, fn, is_mut in ROUTES:
        if is_mut:
            fn = mutating(fn)
        getattr(app, method)(rule)(fn)
