# -*- coding: utf-8 -*-
"""services/inbox_import.py —— 收件箱的「入库流水线」（3.6.80 从 services/inbox.py 拆出）。

职责：把用户提交的一批文件**落盘归档**——分拣（压缩包/单文件/文件夹/不支持）、
按魔数补类型、同批与库内去重、三类各自的落盘 + 登记，最后返回逐条结果。

**与收件箱的分工**：`services/inbox.py` 管"收件箱目录/提案/确认"，本模块管"确认之后怎么落盘"。
所有跨模块调用仍走 `h().xxx`（`_inbox_dir` 等被 conftest 与 20+ 处测试打桩，直呼会绕过桩）。
"""
import json
import os
import re
import shutil
import tempfile
import time
import zipfile

import djc_parse as _dp
import meta_store as meta

from common import ensure_dir
from panel.host import h
from services.import_notes import dup_name_hint as _dup_name_hint


def _circle_authors(g, limit=30):
    """社团内作者聚合：[{name, count}] 按作品数降序（合作作品每位作者各计 1）。"""
    tally = {}
    for w in g["works"]:
        for a in set(h()._work_authors(w)):
            tally[a] = tally.get(a, 0) + 1
    return [{"name": n, "count": c} for n, c in
            sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


def _other_info_of(a):
    """「其他信息」栏的初始值 = 整标题里**除**展会/社团/画师/名称/原作/汉化组之外的
    **全部**有效内容，裸词条、空格分隔（保存时按原形态回写成 [词条] 或 (词条)）。

    3.6.11 前这一栏只有 bare（待定词条），语言标记 [中国翻訳]、其余 [] 段、其余 () 段
    都既看不见也改不了——等于整标题的一部分内容在逐字段模式里凭空消失。
    顺序：语言标记 → 其他方括号 → 待定词条 → 其他圆括号（贴合原文件名里的层次）。"""
    out = []
    for key in ("cn_lang", "other_brackets"):
        out.extend(x for x in (a.get(key) or []) if x)
    if a.get("bare"):
        out.append(a["bare"])
    out.extend(x for x in (a.get("other_parens") or []) if x)
    return " ".join(dict.fromkeys(out))


def _sanitize_note(note):
    """导入落盘名兜底清洗：Windows 非法字符 → 空格（保留扩展名）。"""
    if note.get("new_name"):
        b, e = os.path.splitext(note["new_name"])
        sb = h()._dp.sanitize_windows_name(b)
        if sb:
            note["new_name"] = sb + e
    if note.get("new_base"):
        sb = h()._dp.sanitize_windows_name(note["new_base"])
        if sb:
            note["new_base"] = sb
    return note


def _safe_subpaths(segs):
    """导入相对子路径清洗：拒绝空段与非法字符，返回安全段列表或 None。"""
    out = []
    for s in segs:
        s = h()._dp.sanitize_windows_name(str(s))
        if not s:
            return None
        out.append(s)
    return out or None


def _import_status(note, dest_name, circle):
    st = "已导入" + (f"（社团「{dest_name}」）" if circle else "（收件箱）")
    if note.get("action") == "personal":
        st += "；待定词条已印证为个人名，自动补全社团"
    elif note.get("action") == "circle":
        st += "；待定词条已印证为社团名"
    elif note.get("action") == "new-archive":
        st += f"；待定词条无法匹配社团/个人，已按其归档到「{dest_name}」档案"
    return st


def _import_resolve_and_name(base, ext, embed):
    """导入文件名规范化 + 待定词条解析（规则2/3/4）。
    返回 (circle, note)；note.new_name / new_base 为最终落盘名。
    待定词条无法匹配到已知社团/个人时 → 直接以其本身新建档（不再进未分类）。"""
    parsed = h().parse_filename(base, h().state.originals, h().state.norm_to_canon)
    if parsed["circle"]:                       # [C (P)]：社团明确
        h()._known_learn(parsed["circle"], parsed["personal"])   # 即时学习，同批后续文件可用
        return parsed["circle"], {"new_name": h().normalize_filename(base, ext) or base + ext, "new_base": h().normalize_filename(base, "") or base}
    if parsed["bare"]:                         # 裸 [a]：待定词条 → 与词条库比对
        # （2026-09-25 作废"自动补社团名"）待定词条一律按词条本身新建个人目录
        term = h()._clean_term(parsed["bare"])
        if embed:
            return term, {"new_name": h().normalize_filename(base, ext) or base + ext,
                          "action": "new-archive", "term": term}
        return term, {"new_base": h().normalize_filename(base, "") or base,
                      "action": "new-archive", "term": term}
    return "", {"new_name": h().normalize_filename(base, ext) or base + ext,
                "new_base": h().normalize_filename(base, "") or base}


def _import_process(entries):
    """导入处理管线：entries = [(FileStorage, rel, src_path)]，
    由 /api/import（multipart 落盘）与 /api/upload-commit（分块拼接）共用。

    3.6.66 结构：分拣在 `_import_sort`，三类落盘各自成函数，本函数只做编排与汇总（cc 33→4）。
    单条失败一律折成一条"失败"结果，不打断整批。
    """
    files = [e[0] for e in entries]
    paths = [e[1] for e in entries]
    root = h().CFG.get("root", "")
    if not os.path.isdir(root):
        return h().jsonify({"ok": False, "message": "根目录不存在，请先设置"}), 400
    try:
        h().meta.snapshot("导入前")               # 备份时间机器（60s 节流，批量导入不刷屏）
    except Exception:
        h().log.exception("导入：快照失败，本次操作没有回滚点")
    archives, singles, grouped, skipped = _import_sort(files, paths)
    results = [{"file": o, "status": "跳过", "message": "不支持的文件类型", "rel": o}
               for o in skipped]
    batch_sha = {}                 # 本批已入库内容的 sha1 → 文件名（批内重复去重）
    imported = 0
    for item in archives:
        res, delta = _import_archive(item, batch_sha)
        results.extend(res)
        imported += delta
    for item in singles:
        res, delta = _import_single(item)
        results.extend(res)
        imported += delta
    for top, items in grouped.items():
        res, delta = _import_group(top, items)
        results.extend(res)
        imported += delta
    h()._lib_touch()
    return h().jsonify({"ok": True, "imported": imported, "results": results})


def _import_sort(files, paths):
    """把上传项分成 压缩包 / 单文件媒体 / 顶层文件夹媒体（按首段分组）/ 不支持 四类。"""
    archives, singles, skipped = [], [], []
    grouped = h().OrderedDict()
    for f, rel in zip(files, paths):
        rel = str(rel or "").replace("\\", "/").strip("/")
        orig = os.path.basename(rel) or os.path.basename(str(f.filename or "").replace("\\", "/"))
        orig, ext = _import_sniff_ext(f, orig)
        if ext in h().ARCHIVE_EXTS:
            archives.append((f, orig, rel))
        elif ext in h().PAGE_EXTS:
            segs = [s for s in rel.split("/") if s]
            if len(segs) >= 2:                      # 顶层文件夹/子路径/文件名
                grouped.setdefault(segs[0], []).append((f, segs[1:], rel))
            else:
                singles.append((f, orig, rel))
        else:
            skipped.append(orig)
    return archives, singles, grouped, skipped


def _import_sniff_ext(f, orig):
    """返回 (文件名, 小写扩展名)。无扩展名/未知扩展名时按魔数补类型——
    爬虫下载常不带扩展名，不嗅探就会被当"不支持的类型"跳过。"""
    ext = os.path.splitext(orig)[1].lower()
    if ext in h().ARCHIVE_EXTS or ext in h().PAGE_EXTS:
        return orig, ext
    head = b""
    try:
        f.stream.seek(0)
        head = f.stream.read(16)
        f.stream.seek(0)
    except Exception:
        head = b""
    sniffed = h()._sniff_ext(head)
    if sniffed:
        return orig + sniffed, sniffed
    return orig, ext


def _find_batch_dup(sha, dest, batch_sha):
    """同内容判定：先看本批（批内重复），再看库内（跨批/历史上传）。"""
    if not sha:
        return None
    if sha in batch_sha:
        return {"scope": "batch", "name": batch_sha[sha]}
    return h()._find_content_dup(sha, os.path.getsize(dest), exclude_path=dest)


def _import_archive(item, batch_sha):
    """一个压缩包：解析命名 → 落盘 → 内容去重（重复即删）→ 登记 sha1。
    返回 (results, imported_delta)。"""
    f, orig, rel = item
    try:
        base, e = os.path.splitext(orig)
        circle, note = h()._import_resolve_and_name(base, e, embed=True)
        note = h()._sanitize_note(note)
        dest_dir = h()._archive_dest_dir(circle)
        dest_name = os.path.basename(dest_dir)
        os.makedirs(dest_dir, exist_ok=True)
        base_dest = os.path.join(dest_dir, note["new_name"])
        same_name = os.path.exists(base_dest)   # 3.7.39：同名→洗版候选（同内容走重复分支）
        dest = h().unique_path(base_dest)
        f.save(dest)
        # 3.1 内容哈希去重：同内容不同名的包不再产生 "(2)" 副本——保存后哈希比对，重复即直接删除
        sha = h()._sha1_file(dest)
        dup = _find_batch_dup(sha, dest, batch_sha)
        if dup:
            h()._archive_quiesce([dest])
            h()._delete(dest)
            return ([{"file": orig, "status": "重复内容",
                      "message": f"与「{dup.get('name', '')}」内容相同，已跳过（未入库）",
                      "rel": rel}], 0)
        if sha:
            batch_sha[sha] = orig
            # 即时登记：连续两批同内容也拦得住
            h().meta.work_register_sha1(
                dest_name + "/" + os.path.splitext(note["new_name"])[0],
                dest, os.path.getsize(dest), sha)
        status = h()._import_status(note, dest_name, circle)
        row = {"file": orig, "status": status + ("（替换洗版）" if same_name else ""), "rel": rel}
        if same_name: row["message"] = _dup_name_hint(dest, exact=True)
        return ([row], 1)
    except Exception as e:
        return ([{"file": orig, "status": "失败", "message": str(e), "rel": rel}], 0)


def _import_single(item):
    """一个散图媒体：在目标社团下按作品名建目录，把这一张放进去。
    返回 (results, imported_delta)。"""
    f, orig, rel = item
    try:
        base, _e = os.path.splitext(orig)
        circle, note = h()._import_resolve_and_name(base, "", embed=False)
        note = h()._sanitize_note(note)
        dest_dir = h()._archive_dest_dir(circle)
        dest_name = os.path.basename(dest_dir)
        base_dir = os.path.join(dest_dir, note["new_base"])
        same_name = os.path.exists(base_dir)       # 3.7.39：同名作品目录 → 洗版候选
        work_dir = h().unique_path(base_dir)
        os.makedirs(work_dir, exist_ok=True)
        f.save(os.path.join(work_dir, orig))
        status = h()._import_status(note, dest_name, circle)
        row = {"file": orig, "status": status + ("（替换洗版）" if same_name else ""), "rel": rel}
        if same_name: row["message"] = _dup_name_hint(work_dir, exact=False)
        return ([row], 1)
    except Exception as e:
        return ([{"file": orig, "status": "失败", "message": str(e), "rel": rel}], 0)


def _import_resolve_folder(top_clean):
    """文件夹名作为词条参与印证：解析不出圈子且未给出动作时，
    把整个名字当待定词条再解析一次（作品目录名仍用文件夹原名，不加 []）。"""
    circle, note = h()._import_resolve_and_name(top_clean, "", embed=False)
    if not circle and "action" not in note:
        circle, note = h()._import_resolve_and_name("[" + top_clean + "]", "", embed=False)
        note["new_base"] = top_clean
    return circle, note


def _import_group(top, items):
    """顶层文件夹归并的媒体：整个文件夹算一部作品。
    返回 (results, imported_delta)；组级异常保留已收结果并追加一条"失败"（与原实现一致）。"""
    results, imported = [], 0
    try:
        top_clean = h()._dp.sanitize_windows_name(top)
        circle, note = _import_resolve_folder(top_clean)
        note = h()._sanitize_note(note)
        dest_name = os.path.basename(h()._archive_dest_dir(circle))
        base_dir = os.path.join(h()._archive_dest_dir(circle), note["new_base"])
        same_name = os.path.exists(base_dir)       # 3.7.39：同名作品目录 → 洗版候选
        work_dir = h().unique_path(base_dir)
        os.makedirs(work_dir, exist_ok=True)
        status = h()._import_status(note, dest_name, circle)
        hint = _dup_name_hint(work_dir, exact=False) if same_name else ""
        for f, sub, rel in items:
            rel_name = top + "/" + "/".join(sub)
            segs = h()._safe_subpaths(sub)
            if not segs:
                results.append({"file": rel_name, "status": "失败", "message": "非法路径",
                                "rel": rel_name})
                continue
            target = os.path.join(work_dir, *segs)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            f.save(target)
            imported += 1
            row = {"file": rel_name, "status": status, "rel": rel}
            if hint and not results:           # 只挂本组第一条，避免整组每行重复同一句
                row["status"] = status + "（替换洗版）"
                row["message"] = hint
            results.append(row)
    except Exception as e:
        results.append({"file": top + "/…", "status": "失败", "message": str(e), "rel": top + "/…"})
    return results, imported
