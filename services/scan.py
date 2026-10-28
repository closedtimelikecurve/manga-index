# -*- coding: utf-8 -*-
"""services/scan.py —— 文件系统扫描与社团分组（3.6.60 Stage7 从 app.py 抽出，再由
services/library.py 拆出）。

链路：`collect_works_in_dir`（遍历目录、枚举压缩包/文件夹）→ `make_work`
（文件名 → 作品：词条/画师/页码/封面）→ `scan_groups`（社团归并、合作社团交叉引用、
别名合并、排序）。**纯读取**：不改文件、不写 DB（收件箱搬运由 services/inbox.py 负责）。
"""
import hashlib
import json
import os
import time

from common import ensure_dir
from panel.host import h

def _normalize_identity(name, parsed, path):
    """3.6.12：从解析结果算出作品的身份字段 (circle, personals, bare, circles, loose_group)。

    抽出来是因为它必须**每次都执行**——不仅新作品，增量缓存命中的旧作品也要用最新逻辑重算，
    否则 3.6.12 的词条归一/待定印证结果会被 library_index.json 缓存住、长期不收敛
    （TOZAN-BU 被识别成画师、富士やま 沦为未定社团，根因就在这）。

    3.6.69 结构：作者/社团清洗与裸词条印证各自成函数，本函数只表顺序（cc 29→8）。
    """
    personals = _identity_personals(parsed)
    circle = "" if h()._term_blacklisted(parsed["circle"]) else parsed["circle"]
    bare = "" if h()._term_blacklisted(parsed.get("bare", "")) else parsed.get("bare", "")
    circles = _identity_circles(parsed)
    if not circle and not personals and not bare:
        rescued = h()._rescue_personal(name)
        if rescued:
            personals = [rescued]           # 词条救援：后续括号里的已知个人名顶上
    circle, personals, bare, loose_group = _resolve_bare_identity(circle, personals, bare, path)
    if circle:
        # 3.6.12：圈子名折叠分隔符变体（TOZAN_BU / TOZAN：BU / TOZANBU / TOZAN-BU …），
        # 归一到同一规范名——否则同一社团会被碎成多个"社团"、画师目录被反判成"未定社团"。
        circle = h()._canon_circle_resolved(circle)
    return circle, personals, bare, circles, loose_group


def _identity_personals(parsed):
    """作者列表：逐位笔名归一，丢掉空串与黑名单词条（`A & B` 已在解析层拆开）。"""
    raw = parsed.get("personals") or ([parsed["personal"]] if parsed["personal"] else [])
    canon = [h()._canon_author(a) for a in raw]
    return [a for a in canon if a and not h()._term_blacklisted(a)]


def _identity_circles(parsed):
    """合作社团列表：去空、去重、去黑名单，保序（顺序影响后续归档的"第一社团"）。"""
    out = []
    for c in (parsed.get("circles") or []):
        c = str(c).strip()
        if c and c not in out and not h()._term_blacklisted(c):
            out.append(c)
    return out


def _resolve_bare_identity(circle, personals, bare, path):
    """待定词条印证：命中的社团/画师决定作品归到哪，并记下需要锚定的归档名。

    只有**根目录散包**才需要锚定原归档名：目录内作品的归档名本来就是目录名
    （印证只改身份、不动归档）；散包的归档名来自词条本身，印证改了 circle 就会改 key。
    """
    if not bare or circle:
        return circle, personals, bare, ""
    r = h()._resolve_bare(bare)
    loose_group = bare if h()._is_root_loose(path) else ""
    if r and r["as"] == "circle":
        return r["name"], [], "", loose_group
    if r and r["as"] == "personal" and r["circle"]:
        return r["circle"], personals, "", loose_group
    return circle, personals, bare, ""

def _reresolve_cached_work(hit, name):
    """增量缓存命中：页枚举/封面很贵（要开压缩包/遍历目录），复用缓存里的 page_files/cover；
    但 circle/bare/personals/tags 这些**身份字段必须按当前逻辑重算**——否则 library_index.json
    里 3.6.12 修复前的旧值会原样返回，绕过词条归一/待定印证（TOZAN-BU 等归一失效就是这么来的）。"""
    path = str(hit.get("path") or "")
    kind = hit.get("kind") or "archive"
    parsed = h().parse_filename(os.path.basename(path), h().state.originals, h().state.norm_to_canon)
    circle, personals, bare, circles, _loose_group = h()._normalize_identity(name, parsed, path)
    work = {
        "name": name, "path": path, "kind": kind,
        "pages": hit.get("pages", 0), "cover": hit.get("cover"),
        "page_files": hit.get("page_files") or [],
        "mtime": hit.get("mtime", 0),
        "circle": circle, "circles": circles, "personal": (personals[0] if personals else ""),
        "personals": personals, "bare": bare,
        "tags": parsed["tags"],
    }
    if _loose_group:
        work["_group"] = _loose_group
    return work

def make_work(name, path, kind):
    """
    生成一部作品的元数据。
    kind: "folder" | "archive"
    封面规则：文件名排序后的第一张图片；若在压缩包内则取包内第一张。
    cover: ("file", 路径) | ("zip", 包, 内部名) | ("rar", 包, 内部名) | None
    page_files: 排序后的全部页面（阅读器用），统一页面描述（P2-7）：
      {"p": 散图绝对路径} | {"z": zip路径, "n": 包内页名} | {"r": rar路径, "n": 包内页名}
    文件夹作品的嵌套压缩包页一并计入 → pages 与阅读器可读页数恒一致，嵌套包页可读。
    增量索引：键命中（源未变动）直接复用上次元数据，不再打开压缩包枚举页名。

    3.6.63 结构：本函数只做编排（cc 31→5）。取签名/命中缓存分 archive/folder 两条
    （`_prepare_archive` / `_prepare_folder`），封面挑选独立成 `_pick_cover`。
    """
    prepare = _prepare_archive if kind == "archive" else _prepare_folder
    hit, ikey, images, archives, page_files = prepare(path, name)
    if hit is not None:
        return hit                       # 增量缓存命中（身份字段已在 _reresolve 里按当前逻辑重算）
    if ikey is None or (not images and not archives):
        return None

    # 页数语义统一：文件夹作品把嵌套压缩包的页并入 page_files，页数 = 可读页数
    if kind != "archive":
        for _rel, apath in archives:
            page_files.extend(h()._archive_page_entries(apath))
    page_count = len(page_files)
    cover = _pick_cover(images, archives, page_files, kind, path)

    parsed = h().parse_filename(os.path.basename(path), h().state.originals, h().state.norm_to_canon)
    # 3.6.12：身份字段每轮都按当前逻辑重算；缓存命中时也走 _reresolve_cached_work → 不会
    # 被 library_index.json（修复前）里的旧 circle/bare 值污染，归一才能稳定收敛。
    circle, personals, bare, circles, _loose_group = h()._normalize_identity(name, parsed, path)
    work = {
        "name": name, "path": path, "kind": kind,
        "pages": page_count, "cover": cover,
        "page_files": page_files,
        "mtime": h().work_mtime(images, archives, path),
        # 3.6.151：「按文件大小排序」用（查重复下载/洗版留下的近似体积条目）
        "size": _work_size(kind, path, images, archives),
        "circle": circle, "circles": circles, "personal": (personals[0] if personals else ""),
        "personals": personals,
        "bare": bare,
        "tags": parsed["tags"],
    }
    if _loose_group:
        work["_group"] = _loose_group        # 真实归档名（落库 key 用），public_work 不会外泄
    h()._index_put_work(ikey, work)
    return work


def _work_size(kind, path, images, archives):
    """作品的磁盘占用（字节）。压缩包 = 包大小；文件夹 = 散图 + 嵌套包之和。

    用途是「按文件大小排序」查重：同一部作品被重复下载 / 洗版时，文库会出现两条标题
    不同但体积接近的记录，按大小一排就挨在一起。**只统计已枚举到的页面文件**（不额外
    os.walk），所以和"资源管理器里看目录大小"可能略有出入（忽略非图片附件），
    但对查重足够，且不增加扫描开销。"""
    if kind == "archive":
        try:
            return os.stat(path).st_size
        except OSError:
            return 0
    total, seen = 0, set()
    for _rel, p in list(images) + list(archives):
        if p in seen:
            continue
        seen.add(p)
        try:
            total += os.path.getsize(p)
        except OSError:
            pass
    return total


def _prepare_archive(path, name):
    """压缩包作品：签名 = (mtime_ns, size)；命中则直接复用缓存元数据。
    返回 (命中作品|None, 缓存键|None, images, archives, page_files)。"""
    try:
        st = os.stat(path)
    except OSError:
        return None, None, [], [], []
    ikey = f"a|{st.st_mtime_ns}|{st.st_size}|{path}"
    hit = h()._index_get_work(ikey)
    if hit is not None:
        return h()._reresolve_cached_work(hit, name), None, [], [], []
    ext = os.path.splitext(path)[1].lower()
    page_files = h()._archive_page_entries(path) if ext in h().ARCHIVE_EXTS else []
    return None, ikey, [], [(os.path.basename(path), path)], page_files


def _prepare_folder(path, name):
    """文件夹作品：签名 = 全树 (相对名, mtime_ns) —— 增删改名改内容任一变化都会改变签名。"""
    images, archives = h().scan_images_and_archives(path)
    if not images and not archives:
        return None, None, [], [], []
    sig_parts = []
    for _rel, p in list(images) + list(archives):
        try:
            sig_parts.append([os.path.relpath(p, path), os.stat(p).st_mtime_ns])
        except OSError:
            pass
    sig_parts.sort()
    sig = hashlib.sha1(json.dumps(sig_parts, ensure_ascii=False).encode("utf-8")).hexdigest()
    ikey = f"f|{sig}|{path}"
    hit = h()._index_get_work(ikey)
    if hit is not None:
        return h()._reresolve_cached_work(hit, name), None, [], [], []
    return None, ikey, images, archives, [{"p": p} for _rel, p in images]


def _pick_cover(images, archives, page_files, kind, path):
    """封面必须是普通图片（webm 无法缩略，也不适合 <img> 预览）：
    取第一个"图片页"；若整部作品只有 webm 页则无封面。"""
    for _rel, abspath in images:
        if h().is_image_name(abspath):
            return ("file", abspath)
    if kind == "archive":
        ext = os.path.splitext(path)[1].lower()
        for pg in page_files:
            if h().is_image_name(pg["n"]):
                return (("zip" if ext in (".zip", ".cbz") else "rar"), path, pg["n"])
        return None
    for _rel, apath in archives:
        aext = os.path.splitext(apath)[1].lower()
        names = h().list_zip_images(apath) if aext in (".zip", ".cbz") else (
            h().list_rar_images(apath) if aext in (".rar", ".cbr") else [])
        for f in names:
            if h().is_image_name(f):
                return (("zip" if aext in (".zip", ".cbz") else "rar"), apath, f)
    return None


def collect_works_in_dir(path, depth=0):
    """
    递归收集目录下的作品：
      - 目录直接含图片 → 整个目录视为一部作品（以本目录名命名，含其下所有图片）
      - 目录有压缩包 → 每个压缩包视为一部作品
      - 子目录直接含图片 → 子目录自己是一部作品
      - 否则子目录作为容器继续递归

    3.6.69 结构：目录枚举 `_scan_dir_entries`、压缩包 `_works_from_archives`、
    子目录 `_works_from_subdirs`（cc 19→5）。
    """
    if depth > h().MAX_DEPTH:
        return []
    images, archives, subdirs = _scan_dir_entries(path)
    if images:
        # 目录直接含图片 → 整目录算一部作品，不再往下递归
        w = h().make_work(os.path.basename(path), path, "folder")
        return [w] if w else []
    out = _works_from_archives(archives)
    out.extend(_works_from_subdirs(subdirs, depth))
    return out


def _scan_dir_entries(path):
    """一级目录内容分三类（图片 / 压缩包 / 子目录）；读不了就当空目录。"""
    images, archives, subdirs = [], [], []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        subdirs.append(e)
                    elif e.is_file(follow_symlinks=False):
                        ext = os.path.splitext(e.name)[1].lower()
                        if ext in h().PAGE_EXTS:
                            images.append(e)
                        elif ext in h().ARCHIVE_EXTS:
                            archives.append(e)
                except OSError:
                    pass
    except OSError:
        return [], [], []
    return images, archives, subdirs


def _works_from_archives(archives):
    """每个压缩包一部作品（按自然序，保证两次扫描顺序一致）。"""
    out = []
    for a in sorted(archives, key=lambda e: h().natural_key(e.name)):
        w = h().make_work(os.path.splitext(a.name)[0], a.path, "archive")
        if w:
            out.append(w)
    return out


def _works_from_subdirs(subdirs, depth):
    """子目录：自己直接含图片 → 单独一部作品；否则作为容器继续递归。"""
    out = []
    for d in sorted(subdirs, key=lambda e: h().natural_key(e.name)):
        if _dir_has_images(d.path):
            w = h().make_work(d.name, d.path, "folder")
            if w:
                out.append(w)
        else:
            out.extend(h().collect_works_in_dir(d.path, depth + 1))
    return out


def _dir_has_images(path):
    """目录一级是否直接含图片（决定它算"作品"还是"容器"）。"""
    try:
        return any(x.is_file(follow_symlinks=False)
                   and os.path.splitext(x.name)[1].lower() in h().PAGE_EXTS
                   for x in os.scandir(path))
    except OSError:
        return False

def build_group(name, works, dir_path=None):
    """社团 = 一级分类。封面 = 该社团下修改时间最晚作品的第一张图。
    created_at = 社团档案的创建时间（真实目录 = 目录创建时间；根目录散包构成的虚拟社团
                 取最早一部作品的创建时间）；updated_at = 最新作品的修改时间，
                 也就是"最近入库新作品"的时间。两者供社团排序使用。
    works 为空时返回空档案（未分类可能没有任何作品，此时前端应显示"已清空"而不是报错）。

    3.7.43 结构：创建时间 `_group_created`、封面 `_cover_for_group` 各自独立
    （原函数 53 行，两个 try/OSError 分支是主要复杂度来源）。
    """
    if not works:
        created = _group_created(dir_path)
        # 记下"当前 0 部作品"：这样这个社团将来第一次入库作品时能被判为"新增"（n 从 0 涨到 1）
        return {"name": name, "works": [], "cover_work": None, "cover_mtime": 0.0,
                "latest_work": "", "created_at": created, "total_bytes": 0,
                "updated_at": h()._group_arrival(name, [], created, 0.0)}
    works.sort(key=lambda w: h().natural_key(w["name"]))
    latest = max(works, key=lambda w: w["mtime"])
    cover_work, cover_group = _cover_for_group(name, works, latest)
    created = _group_created(dir_path, works)
    arrival = h()._group_arrival(name, works, created, latest["mtime"])
    return {
        "name": name, "works": works,
        "cover_work": cover_work,
        "cover_group": cover_group,
        "cover_mtime": latest["mtime"],      # 内容最新（封面/"最新：X" 用），不参与排序
        "latest_work": latest["name"],
        "created_at": created,
        "updated_at": arrival,               # 「最近入库新作品」时间，只有新增作品才前进
        # 3.6.151：「按文件大小排序」的社团汇总（查重时先看哪个社团占得最多）
        "total_bytes": sum(int(w.get("size") or 0) for w in works),
    }


def _group_created(dir_path, works=()):
    """社团档案创建时间：真实目录取目录 ctime；取不到（或虚拟社团）退到
    最早一部作品的 ctime；都没有则 0.0。"""
    if dir_path:
        try:
            created = os.stat(dir_path).st_ctime      # Windows 上 st_ctime 就是创建时间
            if created:
                return created
        except OSError:
            pass
    ts = []
    for w in works:
        try:
            ts.append(os.stat(w["path"]).st_ctime)
        except OSError:
            pass
    return min(ts) if ts else 0.0


def _cover_for_group(name, works, latest):
    """社团封面 = 修改时间最晚作品的第一张图；区域封面覆盖优先（按物理所在社团取图）。"""
    cover_work = latest if latest.get("cover") else max(
        (w for w in works if w.get("cover")), key=lambda w: w["mtime"], default=None)
    cover_group = name
    ov = h()._resolve_region_cover("circle", name)
    if ov:
        owk = h().find_work(ov["group"], ov["work"])
        if owk:
            return owk, ov["group"]       # 用户在社团页设过覆盖：跨引用同理
    return cover_work, cover_group


def _work_belongs(w):
    """这部作品能否归属到某个社团（虚拟档案）？
    有社团词条 / 有待定词条 / 属合作社团 → True（进文库）；完全无词条 → False（应进收件箱待整理）。"""
    term = w.get("circle") or ""
    if not term and w.get("bare"):
        term = h()._clean_term(w["bare"])
    coop = [c for c in (w.get("circles") or []) if c]
    return bool(term) or len(coop) >= 2

def _archive_dest_dir(circle):
    """入库目标目录的**绝对路径**。

    无法解析出社团词条的归入**收件箱目录**（程序目录内的 _app/_inbox，不进文库），
    而不是在文库根新建一个中文目录——那里只该有真实社团目录。
    调用方据此 Jah mkdir / 拼文件名即可，不要再 join 文库根。"""
    if not circle:
        return h()._inbox_dir()
    return os.path.join(h().CFG.get("root", ""),
                        h()._existing_archive_dir(h()._dp.sanitize_windows_name(h()._coop_primary(circle))))


def _merge_alias_circles(raw):
    """3.6.11 社团别名归并：raw = [(社团名, [作品], 目录路径|None)]。

    登记了「B → A」之后，B 不再作为独立社团出现，其作品并入 A 的档案页；
    作品对象自带真实 path → `find_work(A, 作品名)` 照样命中，打开/删除/续读全部照旧。
    **作品的 key 仍是「真实所在目录/作品名」**，所以合并不会打乱阅读进度与收藏
    （改名那种物理迁移才会动 key，别名是纯展示层归并，随时可撤销）。
    两边目录都存在时作品做 path 去重；别名链 A→B→C 由 _canon_circle_name 沿链解析。
    """
    aliases = h()._circle_aliases()
    if not aliases:
        return raw
    target_of = {}
    for name, _ws, _d in raw:
        c = h()._canon_circle_name(name)
        if c and c != name:
            target_of[name] = c
    if not target_of:
        return raw
    buckets, order = {}, []
    for name, ws, d in raw:
        t = target_of.get(name, name)
        if t not in buckets:
            buckets[t] = [[], None]
            order.append(t)
        bucket = buckets[t]
        if name == t:                      # 正名自己的目录（决定社团页/归档路径）
            bucket[1] = d
        for w in ws:
            if all(x["path"] != w["path"] for x in bucket[0]):
                if name != t:
                    # 记住**真实所在社团**：元数据库据此落 key/group_name（"社团B/作品二"），
                    # 展示归到正名社团不改变作品身份 —— 阅读进度/收藏的 key 因此稳如泰山。
                    # public_work 是白名单，这个内部标记不会外泄给前端/安卓。
                    w = dict(w, _group=name)
                bucket[0].append(w)
    return [(n, buckets[n][0], buckets[n][1]) for n in order]

def scan_groups(root):
    """扫描根目录，返回社团列表。进度实时写入 state.scan_state（前端轮询显示）。

    3.6.63 结构：编排只留五个阶段，各阶段独立成函数（本函数 cc 46→4）。
    顺序即语义：一级目录 → 根目录散包（虚拟社团）→ 合作社团交叉引用 → 别名合并
    → 同名合并 → 建组 + 修剪 + 排序。
    """
    if not root or not os.path.isdir(root):
        return []
    try:
        entries = sorted(os.scandir(root), key=lambda e: h().natural_key(e.name))
    except OSError:
        return []
    h().state.scan_state["running"] = True
    h().state.scan_state["total"] = len(entries)
    h().state.scan_state["done"] = 0
    raw = []
    loose = _scan_entries(entries, raw)
    h().state.scan_state["running"] = False
    if loose:
        _scan_loose(loose, raw)
    # 合作社团（[A、B] / [A,B]）：作品按各自子社团交叉引用，合成名社团随之退场
    raw = h()._build_coop_groups(raw)
    # 3.6.11 社团别名：别名的作品并入正名社团，别名自身不再单列
    raw = h()._merge_alias_circles(raw)
    raw = _merge_same_name(raw)
    # 默认排序：最近**入库新作品**的社团排前面（同时间按名称自然排序）；
    # 具体排序方式由 /api/library?sort=&order= 决定（sort_groups），客户端的"社团排序"开关用它
    groups = [h().build_group(n, w, d) for n, w, d in raw]
    h()._groups_prune({g["name"] for g in groups})     # 清掉已消失社团的入库记录
    return h().sort_groups(groups, "updated", "desc")


def _scan_entries(entries, raw):
    """遍历根目录一级项：目录交给 _scan_dir_entry，散包文件收集起来稍后处理。
    逐项推进 scan_state.done（前端进度条），单个条目 OSError 不影响其余条目。"""
    ignore_files = set(h().CFG.get("ignore_files") or [])   # 根目录散落压缩包的忽略名单（config.json）
    loose = []
    for e in entries:
        try:
            if e.is_dir(follow_symlinks=False):
                _scan_dir_entry(e, raw)
            elif (e.is_file(follow_symlinks=False)
                  and os.path.splitext(e.name)[1].lower() in h().ARCHIVE_EXTS
                  and e.name not in ignore_files):
                loose.append(e)
        except OSError:
            continue
        finally:
            h().state.scan_state["done"] += 1
    return loose


def _scan_dir_entry(e, raw):
    """一个一级目录：跳过程序/隐藏目录；「未分类」汇入收件箱；其余按圈子分桶进 raw。"""
    if e.name in h().IGNORE_DIRS or e.name.startswith("."):
        return
    # 3.6.3 遗留的「未分类」目录不再算社团：里面的作品汇入收件箱待整理
    # （由 _inbox_sync 物理搬进 _app/_inbox），目录搬空后会被 _clean_empty_dirs 自动清除
    if e.name == "未分类":
        try:
            for sub in h().collect_works_in_dir(e.path):
                h().state.unfiled_paths.add(sub["path"])
        except OSError:
            pass
        return
    works = h().collect_works_in_dir(e.path)
    if not works:
        return
    for circ, ws in _bucket_by_circle(works, e.name).items():
        if circ:
            raw.append((circ, ws, None))       # 虚拟社团档案（按圈子归）
        else:
            raw.append((e.name, ws, e.path))


def _bucket_by_circle(works, dir_name):
    """按「解析/印证出的圈子」分桶（3.6.12），空串桶 = 留在本目录名下的作品。

    目录只是存储容器：若不按圈子分桶，会冒出两类错：
      ① 同名圈子因分隔符写法各异碎成多个社团（TOZAN_BU / TOZAN：BU / TOZANBU / TOZAN-BU）；
      ② 画师名目录（如「富士やま」）被当成社团、沦为"未定社团"。
    作品 key 仍锚定真实目录（`_group`=目录名），所以阅读进度/收藏不丢；
    合作作品（circles≥2）不在此预拆，留给 _build_coop_groups 交叉引用。
    """
    buckets = {}
    for w in works:
        circ = (w.get("circle") or "").strip()
        cs = w.get("circles") or []
        if circ and len(cs) < 2:
            buckets.setdefault(circ, []).append(dict(w, _group=dir_name))
        else:
            buckets.setdefault("", []).append(w)
    return buckets


def _scan_loose(loose, raw):
    """根目录平铺压缩包：按文件名 [] 归入社团 / 待定词条建新档；完全无词条 → 收件箱待整理。"""
    virtual = {}
    for f in sorted(loose, key=lambda e: h().natural_key(e.name)):
        w = h().make_work(os.path.splitext(f.name)[0], f.path, "archive")
        if not w:
            continue
        if not h()._work_belongs(w):
            h().state.unfiled_paths.add(f.path)      # 无任何词条：不进文库，交给收件箱同步搬进 _app/_inbox
            continue
        term = w.get("circle") or ""
        if not term and w.get("bare"):
            term = h()._clean_term(w["bare"])
        # 合作社团：散包同时归入每个子社团（走进各自的虚拟档案），不造"A、B"合成组
        coop = [c for c in (w.get("circles") or []) if c]
        targets = coop if len(coop) >= 2 else [term]
        for t in targets:
            virtual.setdefault(t, []).append(w)
    for cname, ws in virtual.items():
        raw.append((cname, ws, None))


def _merge_same_name(raw):
    """同名社团合并：真实档案目录 + 根目录散包归出的虚拟档案可能同名 → 合成一个。
    同名时以先出现的目录为准（`md or d`），作品按 path 去重。"""
    merged = {}
    for n, ws, d in raw:
        if n not in merged:
            merged[n] = (list(ws), d)
            continue
        mws, md = merged[n]
        for w in ws:
            if all(x["path"] != w["path"] for x in mws):
                mws.append(w)
        merged[n] = (mws, md or d)
    return [(n, ws, d) for n, (ws, d) in merged.items()]
