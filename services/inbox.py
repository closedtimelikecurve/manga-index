# -*- coding: utf-8 -*-
"""services/inbox.py —— 收件箱与导入流水线（3.6.59 Stage7 从 app.py 抽出）。

收件箱是「扫描发现的无归属作品」与「入库」之间的中转站：
  扫描 → _unfiled_collect 收集未归档路径 → _inbox_sync 搬进 _inbox/ 并生成伪作品卡
  → 用户在面板里填信息 → `services/inbox_import.py::_import_process` 落盘归档。

本模块只管"收件箱目录 / 提案 / 确认"；落盘流水线已拆到 inbox_import（3.6.80）。
`_import_process` 仍由 app.py 再导出，调用面不变。

为什么所有调用（含组内互调）都走 `h()`：`_inbox_dir` 被 conftest 与 21 处测试打桩
（`monkeypatch.setattr(app, "_inbox_dir", ...)`），`_import_process` 也有 3 处直接调用；
组内直呼模块函数会绕过桩 → 测试会真的读写用户 `_inbox/` 目录。
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


def _inbox_pseudo_work(wname):
    """待入库作品 → 阅读器可用的伪作品描述（3.4.2 收件箱阅读：先读后入库）。
    复用压缩包/文件夹作品的页面模型（{"z"/"r": 包路径, "n": 条目名} / {"p": 磁盘路径}），
    /api/pages、/page、/cover 无需改动即可服务。文件已消失/无页面返回 None。

    3.6.66 结构：取项 `_inbox_item`、页面/封面 `_inbox_pages`、显示名 `_inbox_display_name`。
    """
    it = _inbox_item(wname)
    if not it:
        return None
    src = str(it["src"] or "")
    if not src or not os.path.isfile(src):
        return None
    built = _inbox_pages(src)
    if not built:
        return None
    pages, cover = built
    return {"name": _inbox_display_name(it, src), "path": src,
            "mtime": _safe_mtime(src), "pages": len(pages),
            "page_files": pages, "cover": cover,
            # 3.6.8：补 kind 字段（archive/folder，与扫描侧 make_work 同口径）——
            # /api/parse-info、/api/supplement-info 的 _split_work_name 读 w["kind"]，
            # 缺它整个增补信息链路对收件箱作品直接 KeyError 500（表单全空不预填）。
            "kind": "folder" if os.path.isdir(src) else "archive",
            "personal": None, "tags": []}


def _inbox_item(wname):
    """按收件项 id 取；id 不是整数时退回"按文件名匹配"（阅读器只拿得到文件名）。"""
    try:
        return h().meta.inbox_get(int(wname))
    except (TypeError, ValueError):
        target = str(wname or "")
        for row in h().meta.inbox_list():
            if os.path.basename(row["src"]) == target:
                return row
        return None


def _inbox_pages(src):
    """压缩包/文件夹 → (页面列表, 封面)；无页或不可读形态返回 None
    （与收件箱提案 kind=unsupported 一致：不提供阅读）。"""
    ext = os.path.splitext(src)[1].lower()
    if ext in (".zip", ".rar"):
        names = (h().list_zip_images if ext == ".zip" else h().list_rar_images)(src)
        key, kind = ("z", "zip") if ext == ".zip" else ("r", "rar")
        pages = [{key: src, "n": n} for n in names]
        return (pages, (kind, src, names[0]) if names else None) if pages else None
    if not os.path.isdir(src):
        return None
    pages = []
    for dirpath, _dirs, files in os.walk(src):
        for fn in files:
            if os.path.splitext(fn)[1].lower() in h().PAGE_EXTS:
                pages.append({"p": os.path.join(dirpath, fn)})
    pages.sort(key=lambda pg: h().natural_key(pg["p"]))
    return (pages, ("file", pages[0]["p"])) if pages else None


def _inbox_display_name(it, src):
    """显示名：提案里的规范名 > 记录名 > 文件名（提案 JSON 坏掉按空处理）。"""
    try:
        proposal = json.loads(it["proposal"]) if it["proposal"] else {}
    except Exception:
        proposal = {}
    return proposal.get("new_name") or it.get("name") or os.path.basename(src)


def _safe_mtime(path):
    """文件 mtime；取不到返回 0（收件箱阅读排序不能因为一个坏文件整页 500）。"""
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0

def _find_work_by_key(key):
    g, _, wname = str(key or "").partition("/")
    if not g or not wname:
        return None
    return h().find_work(g, wname)

def _inbox_dir():
    """收件箱目录 = 程序目录内的 _inbox（不在文库根，永不参与文库扫描）。"""
    return os.path.join(h().APP_DIR, "_inbox")

def _inbox_parts():
    """_inbox 里下载中断留下的半成品 [(绝对路径, 名称, 字节数, 小时龄)]。
    它们不是作品，收件箱不展示；但一直堆着会让爬虫误判"库里已有"，所以单独列出来可清。"""
    d = h()._inbox_dir()
    out = []
    if not os.path.isdir(d):
        return out
    now = time.time()
    try:
        for e in os.scandir(d):
            if not e.is_file(follow_symlinks=False) or not h()._is_part_name(e.name):
                continue
            st = e.stat()
            out.append((e.path, e.name, st.st_size, (now - st.st_mtime) / 3600.0))
    except OSError:
        return out
    return sorted(out, key=lambda x: -x[3])

def _find_content_dup(sha1, size, exclude_path=None):
    """同内容查找：先队列内（同 sha1 的待入库项），再库内同体积作品（惰性哈希并缓存）。
    改名副本体积必相同——按 size 圈候选、SHA1 终判，避免全库预哈希。"""
    if not sha1:
        return None
    hit = h().meta.inbox_find_sha1(sha1, exclude_src=os.path.abspath(str(exclude_path or "")) or None)
    if hit:
        return {"scope": "inbox", "name": hit["name"]}
    for key, gname, wname, path, cached in h().meta.works_by_size(size):
        p = os.path.abspath(str(path or ""))
        if p == os.path.abspath(str(exclude_path or "")):
            continue
        sha = cached or h()._sha1_file(p)
        if not sha:
            continue
        if not cached:
            h().meta.work_sha1_set(key, sha)
        if sha == sha1:
            return {"scope": "library", "name": f"{gname}/{wname}"}
    return None

def _inbox_propose(fname, size, sha1, exclude_path=None):
    """收件项入库提案：解析词条（与导入同规则）+ 归一化名 + 置信度 + 疑似重复标记。
    置信度：high = 社团词条明确；mid = 待定词条新建档案；low = 无词条（未分类）。"""
    base, ext = os.path.splitext(fname)
    if ext.lower() not in h().ARCHIVE_EXTS:
        return {"kind": "unsupported", "confidence": "-", "circle": "", "bare": "",
                "new_name": fname, "action": "", "dup": None}
    circle, note = h()._import_resolve_and_name(base, ext.lower(), embed=True)
    note = h()._sanitize_note(note)
    if circle:
        confidence = "high"
    elif note.get("action") == "new-archive":
        confidence = "mid"
    else:
        confidence = "low"
    dup = h()._find_content_dup(sha1, size, exclude_path=exclude_path)
    return {"kind": "archive", "circle": circle, "bare": note.get("term", ""),
            "new_name": note.get("new_name") or fname, "action": note.get("action", ""),
            "confidence": confidence,
            "dup": ({"scope": dup["scope"], "name": dup.get("name", "")} if dup else None)}

def _unfiled_collect():
    """把扫描发现的「无归属」作品搬进收件箱目录。

    扫描只登记 state.unfiled_paths（不在热路径里做 IO —— 避免在文库遍历时和用户正在放的文件抢句柄），
    真正的移动在这里做：打开收件箱 / 启动同步时触发，移动失败的原样留下，下次再试。
    搬进去后下面的常规同步会自然把它们登记成待确认项（带归档提案）。"""
    paths = [p for p in list(h().state.unfiled_paths) if p and os.path.exists(p)]
    if not paths:
        return
    d = h()._inbox_dir()
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return
    moved = 0
    for p in paths:
        h().state.unfiled_paths.discard(p)
        base = os.path.basename(p.rstrip("\\/"))
        dest = h().unique_path(os.path.join(d, base))
        h()._archive_quiesce([p])                  # 松手缓存句柄，避免撞 WinError 32
        ok, _err = h()._move_with_retry(p, dest)
        if ok:
            h()._invalidate_after_delete(p)        # 旧路径可能还留在页面缓存里
            moved += 1
        else:
            h().state.unfiled_paths.add(p)              # 被占用/冲突 → 留到下次再试
    if moved:
        h()._lib_touch()                           # 文库结构变了，让两端轮询 rev 后刷新

def _inbox_sync():
    """扫描 _inbox/：先把扫描到的无归属作品收进来，再登记新文件
    （同路径同 mtime 跳过；.part 半成品忽略；文件已消失的行自动清除）。"""
    h()._unfiled_collect()
    d = h()._inbox_dir()
    if not os.path.isdir(d):
        return
    try:
        files = []
        for e in os.scandir(d):
            if not e.is_file(follow_symlinks=False) or h()._is_part_name(e.name):
                continue
            st = e.stat()
            files.append((e.name, e.path, st.st_mtime, st.st_size))
    except OSError:
        return
    known = {it["src"]: it for it in h().meta.inbox_list()}
    for name, path, mtime, size in files:
        ap = os.path.abspath(path)
        if ap in known and known[ap]["mtime"] == int(mtime):
            continue
        sha1 = h()._sha1_file(ap)
        if not sha1:
            continue
        proposal = h()._inbox_propose(name, size, sha1, exclude_path=ap)
        h().meta.inbox_upsert(ap, name, size, int(mtime), sha1,
                          json.dumps(proposal, ensure_ascii=False))
    for src, it in list(known.items()):
        if not os.path.isfile(src):
            h().meta.inbox_delete(it["id"])
    h()._inbox_repair_states()      # 3.5.1：「忽略」已移除，历史 ignored 项一次性恢复为 pending

def _inbox_repair_states():
    """3.5.1 收件箱「忽略」已作废：历史上被标成 ignored 的收件项一次性恢复为 pending，
    否则它们会永远卡在一个没有入口、也没有意义的中间态上。"""
    # 一次性修复闩仍由 app 持有（模块级标量），读写都走 h() 避免两份状态
    if h()._INBOX_STATE_FIXED:
        return 0
    h()._INBOX_STATE_FIXED = True
    n = h().meta.inbox_reset_state("ignored", "pending")
    if n:
        print(f"[收件箱] 已把 {n} 个历史「已忽略」项恢复为待确认（忽略功能已移除）", flush=True)
    return n

def _inbox_confirm_one(it, circle_override=None, force=False):
    """单条确认入库：目标目录 = 覆盖社团 > 提案社团 > 待定词条档案。
    内容级终判：库内已存在同内容（任意名字）→ 默认跳过（force=True 放行人工意图）；
    同名同内容 = 无条件跳过（绝不造 "(2)" 副本），同名不同内容才让位。**解析不出任何社团词条的
    保持待确认**（没法给它一个文库目的地）—— 请先在「增补信息」里补全词条，或手动指定目标社团，
    不要把它搬到收件箱目录里硬算入库（那样会自己覆盖自己，等于删原件）。

    3.6.66 结构：前置校验 `_inbox_dup_blocked` / 目标社团 `_inbox_target_circle` /
    真正搬运 `_inbox_move_into`，本函数只做顺序编排（cc 22→3）。
    """
    src = it["src"]
    if not os.path.isfile(src):
        h().meta.inbox_set_state(it["id"], "confirmed")
        return False, "文件已消失（可能被手动移走）"
    proposal = _inbox_proposal_of(it)
    if proposal.get("kind") == "unsupported":
        return False, "不支持的文件类型（请在收件箱删除）"
    blocked = _inbox_dup_blocked(it, src, force)
    if blocked:
        return False, blocked
    circle = _inbox_target_circle(proposal, circle_override)
    if not circle:
        # 没有任何可用词条 → 无处可归（它会落到收件箱目录自己身上）。
        # 保持 pending，让用户补词条或指定社团，而不是把文件搬到自己身上再判重复删掉。
        return False, ("未识别出社团词条，保持待确认——"
                       "请在「增补信息」补全后重试，或在下方输入目标社团")
    dest_dir = h()._archive_dest_dir(circle)
    return _inbox_move_into(it, src, proposal, dest_dir, os.path.basename(dest_dir))


def _inbox_proposal_of(it):
    """收件项的提案 JSON；坏数据按空 dict（下游都有默认值）。"""
    try:
        return json.loads(it["proposal"] or "{}")
    except Exception:
        return {}


def _inbox_dup_blocked(it, src, force):
    """库内已有同内容 → 返回拒收文案；force=True 放行人工意图。"""
    if force or not it["sha1"]:
        return ""
    dup = h()._find_content_dup(it["sha1"], it["size"], exclude_path=src)
    if dup and dup.get("scope") == "library":
        return (f"库内已存在相同内容（{dup['name']}），已跳过；"
                f"若确需重复入库请使用「仍要入库」")
    return ""


def _inbox_target_circle(proposal, circle_override):
    """目标社团：手填 > 提案社团 > 待定词条（与导入规则一致）。"""
    circle = str(circle_override or "").strip() or proposal.get("circle") or ""
    if not circle and proposal.get("bare"):
        return proposal["bare"]           # 待定词条按其新建档案
    return circle


def _inbox_move_into(it, src, proposal, dest_dir, dest_name):
    """真正搬运：同名同内容 = 直接清掉收件原件（绝不造 "(2)"）；同名不同内容才让位。"""
    try:
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, proposal.get("new_name") or os.path.basename(src))
        if os.path.exists(dest):
            same = it["sha1"] and h()._sha1_file(dest) == it["sha1"]
            if same:
                return _inbox_drop_duplicate(it, src, dest_name)
            dest = h().unique_path(dest)       # 同名不同内容：才让位 "(2)"
        ok, err = h()._move_with_retry(src, dest)
        if not ok:
            return False, "移动失败：" + err
    except Exception as e:
        return False, "入库失败：" + str(e)
    h().meta.inbox_set_state(it["id"], "confirmed")
    h()._lib_touch()
    return True, f"已入库到「{dest_name}」"


def _inbox_drop_duplicate(it, src, dest_name):
    """同名同内容：删掉收件原件并标 confirmed；被占用时保持待确认。"""
    h()._archive_quiesce([src])
    if h()._delete(src):
        h().meta.inbox_set_state(it["id"], "confirmed")
        return True, f"库内已存在相同内容（{dest_name}），已跳过"
    return False, "发现重复但清理收件原件失败（被占用）"
