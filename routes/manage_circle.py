# -*- coding: utf-8 -*-
"""routes/manage_circle.py —— 社团维度的写操作（3.6.81 从 routes/manage.py 拆出）。

三个端点：删空社团目录 / 社团改名 / 解散社团。共同点是一条链路：
**改词条 → 搬目录 → DB key 跟随 → 入向别名改指向 → 索引缓存同步**。
与 manage.py 的"作品维度"操作（删作品、删/设封面）失败模式不同，故单独成文件。

所有跨域依赖走 `h().xxx`（改名会调 `_apply_rename` / `_merge_circle_into` / `_lib_touch`，
测试对它们有打桩）；**不要改成 import app**（会双 Flask 实例）。
"""
import json
import os
import shutil

import djc_parse as _dp
import meta_store as meta

from flask import jsonify, request

from panel.http import mutating
from routes.host import h

def api_delete_circle():
    """删除整个社团（右键菜单）：真实档案夹整目录直接删除（不进回收站，不可还原）；
    根目录散包构成的虚拟社团则逐部直接删除。"""
    body = request.get_json(silent=True) or {}
    gname = str(body.get("group", ""))
    if gname == h().INBOX_GROUP:
        return jsonify({"ok": False, "message": "「收件箱」不支持一键删除，请逐部处理或手动整理"}), 400
    g = h().find_group(gname)
    if not g:
        return jsonify({"ok": False, "message": "未找到该社团，请先重新扫描"}), 404
    root = h().CFG.get("root", "")
    dir_path = h()._group_physical_dir(gname)
    n = 0
    if (os.path.isdir(dir_path) and h()._path_in_root(dir_path)
            and os.path.realpath(dir_path) == os.path.realpath(os.path.abspath(dir_path))):
        if not h()._delete(dir_path):
            return jsonify({"ok": False, "message": "删除失败（目录可能被占用）"}), 500
        h()._invalidate_after_delete(dir_path)
        n = len(g["works"])
    else:
        # 虚拟社团（根目录散包按词条归组）或目录不在根内：逐部作品删除
        for w in g["works"]:
            if not h()._path_in_root(w["path"]):
                continue
            if h()._delete(w["path"]):
                h()._invalidate_after_delete(w["path"])
                n += 1
        if n == 0:
            return jsonify({"ok": False, "message": "没有可删除的作品文件"}), 500
    cleaned = h()._clean_empty_dirs()
    msg = f"已删除：{gname}（{n} 部作品）"
    if cleaned:
        msg += f"，自动清理 {len(cleaned)} 个空文件夹"
    return jsonify({"ok": True, "message": msg})


def api_rename_circle():
    """社团改名：真实档案夹目录整体重命名（作品文件不动）。
    虚拟社团（根目录散包按词条归组）不支持改名；改名后迁移入库时间记录。

    3.6.67 结构：目录校验 `_circle_rename_dirs`、索引记录迁移 `_rename_index_group`。
    """
    body = request.get_json(silent=True) or {}
    gname = str(body.get("group", ""))
    new_name = _dp.sanitize_windows_name(str(body.get("new_name", "")).strip())
    if gname == h().INBOX_GROUP:
        return jsonify({"ok": False, "message": "「收件箱」不支持改名"}), 400
    if not new_name:
        return jsonify({"ok": False, "message": "新名称为空"}), 400
    if new_name == gname:
        return jsonify({"ok": True, "message": "名称未变化"})
    if new_name == h().INBOX_GROUP:
        return jsonify({"ok": False, "message": "不能改名为「收件箱」"}), 400
    g = h().find_group(gname)
    if not g:
        return jsonify({"ok": False, "message": "未找到该社团，请先重新扫描"}), 404
    src, dst, bad = _circle_rename_dirs(gname, new_name)
    if bad:
        return bad
    works = [w["path"] for w in g["works"]]
    h()._archive_quiesce(works)
    try:
        meta.snapshot("社团改名前")           # 备份时间机器
    except Exception:
        h().log.exception("社团改名：快照失败，本次操作没有回滚点")
    if os.path.isdir(dst) and os.path.normcase(src) != os.path.normcase(dst):
        # 3.7.4：目标社团已存在 → 合并（作品逐部搬过去），不再报"目标目录已存在"
        return h()._merge_circle_into(g, gname, new_name, src, dst)
    # 3.6.31：社团改名 —— 作品换到新目录后 find_work(旧社团名, 作品) 会落空，
    # 封面坐标必须跟着重定向到新社团名（retarget），否则封面静默回退派生。
    h()._region_cover_migrate("circle", gname, new_name, retarget=True)
    # 纯大小写改名（heartbreak→HeartBreak）：Windows 上 dst "已存在"其实是**同一目录**
    # （NTFS 不允许两个仅大小写不同的目录共存）。早年这里会误入合并分支，把作品逐一
    # 搬成「xxx (1).zip」再删源目录；现在 normcase 相等直接落到下面的 rename 完成大小写更正
    bad = _circle_rename_commit(gname, new_name, src, dst)
    if bad:
        return bad
    return jsonify({"ok": True, "message": f"已改名：「{gname}」→「{new_name}」",
                    "new_name": new_name})


def _circle_rename_commit(gname, new_name, src, dst):
    """社团改名落库段：目录 rename → 索引记录迁移 → DB key 前缀迁移 → 缓存失效。

    3.7.43 结构：从 api_rename_circle 尾部抽出（原函数 51 行）。
    成功返回 None；失败返回 (响应, 状态码)。
    """
    try:
        os.rename(src, dst)
    except OSError as e:
        return jsonify({"ok": False, "message": "改名失败（目录可能被占用）：" + str(e)}), 500
    _rename_index_group(gname, new_name)      # 入库时间记录迁移（「最近入库」排序状态不丢）
    try:
        meta.rename_circle(gname, new_name)     # 3.0：元数据库 key 前缀/画师映射联动迁移
    except Exception:
        h().log.exception("社团改名落库失败")
    h()._invalidate_after_delete(src)
    h()._lib_touch()
    return None


def _circle_rename_dirs(gname, new_name):
    """校验并返回 (src, dst)；不合法时返回 (None, None, (响应, 状态码))。"""
    root = os.path.abspath(h().CFG.get("root", ""))
    src = h()._group_physical_dir(gname)
    if not src:
        return None, None, (jsonify({"ok": False,
                                     "message": "未找到该社团的真实目录（散包虚拟社团不支持改名）"}), 400)
    if not (os.path.isdir(src) and h()._path_in_root(src)):
        return None, None, (jsonify({"ok": False,
                                     "message": "散包构成的虚拟社团不支持改名（请先一键归档或增补信息建档）"}), 400)
    dst = os.path.join(root, new_name)
    if os.path.exists(dst) and not os.path.isdir(dst):
        return None, None, (jsonify({"ok": False, "message": f"目标位置已是文件：{new_name}"}), 400)
    return src, dst, None


def _rename_index_group(gname, new_name):
    """把 library_index.json 里的入库时间记录迁到新社团名（「最近入库」排序状态不丢）。"""
    try:
        with open(h().INDEX_FILE, "r", encoding="utf-8") as f:
            idx = json.load(f)
        grps = idx.get("groups") or {}
        if gname not in grps:
            return
        grps[new_name] = grps.pop(gname)
        h().ensure_dir(os.path.dirname(h().INDEX_FILE) or h().APP_DIR)   # _state/ 可能尚未建（本次未扫描）
        with open(h().INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False)
    except Exception:
        h().log.exception("更新索引中的社团名失败")


def api_dissolve_circle():
    """解散社团：社团内全部作品移动到 **收件箱目录 _app/_inbox**（文件名不变，绝不覆盖），
    随后把原社团目录整棵直接删除——不在文库根留下空文件夹。
    踢出来的作品回到「未入库」状态：会在收件箱里以待确认项出现（带归档提案），
    补好词条后可一键入库。适用于无法分辨汉化组与待定词条而误建的社团。

    3.6.67 结构：搬作品 `_dissolve_move_works`、原目录处理 `_dissolve_cleanup_dir`。
    """
    body = request.get_json(silent=True) or {}
    gname = str(body.get("group", ""))
    if gname == h().INBOX_GROUP:
        return jsonify({"ok": False, "message": "「收件箱」无需解散"}), 400
    g = h().find_group(gname)
    if not g:
        return jsonify({"ok": False, "message": "未找到该社团，请先重新扫描"}), 404
    inbox_dir = h()._inbox_dir()          # 作品目的地 = 程序目录内的 _inbox（不在文库根建任何目录）
    try:
        meta.snapshot("解散社团前")           # 备份时间机器
    except Exception:
        h().log.exception("解散社团：快照失败，本次操作没有回滚点")
    moved, failed = _dissolve_move_works(g["works"], inbox_dir)
    if moved == 0 and failed:
        return jsonify({"ok": False,
                        "message": "没有作品可移动（" + (failed[0][:80] if failed else "目录可能被占用") + "）"}), 500
    for w in g["works"]:                  # 失效句柄/页面缓存中可能残留的路径
        h()._invalidate_after_delete(w["path"])
    dir_cleared, dir_note = _dissolve_cleanup_dir(g, gname, failed)
    # 解散记忆：该社团名此后不再解析为社团/待定词条（归档时自动降级，防止同名社团复活）
    # 3.0 起记入元数据库 circles 表（config.json 对应键只读退役）
    try:
        meta.dissolve_circle(gname)
    except Exception:
        h().log.exception("解散社团落库失败")
    h()._lib_touch()
    cleaned = h()._clean_empty_dirs()
    msg = f"已解散「{gname}」：{moved} 部作品移入收件箱"
    if dir_cleared:
        msg += "，原目录已清除"
    if failed:
        msg += f"，{len(failed)} 部移动失败"
    if cleaned:
        msg += f"，自动清理 {len(cleaned)} 个空文件夹"
    msg += dir_note
    return jsonify({"ok": not failed and not dir_note, "moved": moved, "failed": failed,
                    "dir_cleared": dir_cleared, "cleaned_dirs": len(cleaned), "message": msg})


def _dissolve_move_works(works, inbox_dir):
    """把社团内作品逐个搬进收件箱（文件名不变、重名自动让位）。返回 (moved, failed)。"""
    moved, failed = 0, []
    for w in works:
        src = w["path"]
        if not h()._path_in_root(src) or not os.path.exists(src):
            failed.append(os.path.basename(src) + "（文件不存在）")
            continue
        h()._archive_quiesce([src])   # 关缓存句柄+等在读线程排空（手机正浏览该社团时也会撞 WinError 32）
        try:
            os.makedirs(inbox_dir, exist_ok=True)
            base = os.path.basename(src if w["kind"] == "archive" else src.rstrip("\\/"))
            dest = h().unique_path(os.path.join(inbox_dir, base))
            ok, err = h()._move_with_retry(src, dest)
            if not ok:
                failed.append(os.path.basename(src) + "（" + err[:60] + "）")
                continue
            moved += 1
        except Exception as e:
            failed.append(os.path.basename(src) + "（" + str(e)[:60] + "）")
    return moved, failed


def _dissolve_cleanup_dir(g, gname, failed):
    """原社团目录清除：作品全部搬出后整棵目录树直接删除（残留的非作品文件一并删掉，
    不可还原），根目录不留空文件夹；只要还有作品没搬走就绝不动目录。
    返回 (是否已清除, 附注文案)。"""
    dir_path = h()._group_physical_dir(gname)
    if not any(h()._path_same_or_under(w["path"], dir_path) for w in g["works"]):
        return False, ""                  # 虚拟社团（根目录散包归组）：本就没有目录
    if failed:
        return False, "；原目录保留（仍有作品未搬出）"
    if not h()._path_in_root(dir_path):
        return False, "；原目录不在文库根内，已跳过清除"
    if not h()._purge_circle_dir(dir_path):
        return False, "；原目录清除失败（可能被占用），请手动删除"
    h()._invalidate_after_delete(dir_path)
    return True, ""


ROUTES = [
    ('post', '/api/delete-circle', api_delete_circle, True),
    ('post', '/api/rename-circle', api_rename_circle, True),
    ('post', '/api/dissolve-circle', api_dissolve_circle, True),
]


def register(app):
    for method, rule, fn, is_mut in ROUTES:
        if is_mut:
            fn = mutating(fn)
        getattr(app, method)(rule)(fn)
