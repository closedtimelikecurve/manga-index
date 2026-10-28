# -*- coding: utf-8 -*-
"""路径 / 文件名 / 媒体类型 工具 —— 3.7 结构重构：从 app.py 抽出。

本模块**不持有业务状态**：只依赖媒体扩展名常量、可选依赖（rarfile）与 config 的
root 路径。app.py 以 `from panel.paths import (...)` 再导出，保持 `app.natural_key`、
`app.media_kind`、`app.list_zip_images` 等既有命名面不变。

打桩点提醒：`list_zip_images` 会被测试包一层计数（test_scan_incremental），
它经 `_archive_page_entries` 被扫描路径调用——打桩请打在**本模块**上。
"""
import hashlib
import os
import re
import zipfile

from common import CFG
from panel.deps import RAR_AVAILABLE, rarfile

# 程序目录（= 本包的上级 = `_app`）。app.py 内有同值定义，两者必须一致。
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
VIDEO_EXTS = {".webm"}                  # 动态图/动画页（阅读器按视频播放）
ANIM_EXTS = {".gif"}                    # 动图页：整帧解码，客户端必须限制解码尺寸（见 media_kind）
PAGE_EXTS = IMAGE_EXTS | VIDEO_EXTS     # 可作为作品“页”的媒体类型
ARCHIVE_EXTS = {".zip", ".cbz", ".rar", ".cbr"}
MAX_DEPTH = 6


def natural_key(s):
    """自然排序：1.jpg < 2.jpg < 10.jpg"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def media_kind(name):
    """页面媒体类型：
      webm  → "video"（阅读器按视频播放）
      gif   → "gif"  （动图：客户端要限制解码尺寸并避免预读，几十帧×上千万像素会打爆内存）
      其余  → "image"
    旧客户端不认识 "gif" 时按图片处理即可，不影响兼容。"""
    ext = os.path.splitext(name)[1].lower()
    if ext in VIDEO_EXTS:
        return "video"
    return "gif" if ext in ANIM_EXTS else "image"


def is_image_name(name):
    return os.path.splitext(name)[1].lower() in IMAGE_EXTS


def scan_images_and_archives(path, depth=0):
    """递归收集目录下的媒体页与压缩包，返回 [(相对名, 绝对路径), ...]（已自然排序）。
    媒体页 = 图片(jpg/png/webp…) + 动态/动画(webm 等)。"""
    images, archives = [], []
    if depth > MAX_DEPTH:
        return images, archives
    try:
        with os.scandir(path) as it:
            entries = sorted(it, key=lambda e: natural_key(e.name))
    except OSError:
        return images, archives
    for e in entries:
        try:
            if e.is_dir(follow_symlinks=False):
                si, sa = scan_images_and_archives(e.path, depth + 1)
                images.extend(si)
                archives.extend(sa)
            elif e.is_file(follow_symlinks=False):
                ext = os.path.splitext(e.name)[1].lower()
                # 与 list_zip_images 同口径：0 字节文件不是有效页（见 3.6.31）
                if ext in PAGE_EXTS and _entry_size(e) > 0:
                    images.append((e.name, e.path))
                elif ext in ARCHIVE_EXTS:
                    archives.append((e.name, e.path))
        except OSError:
            continue
    return images, archives


def _entry_size(e):
    """scandir 条目体积；取不到按 0（当作空文件）处理。Windows 上 DirEntry
    已自带 stat 缓存，这里几乎零开销。"""
    try:
        return e.stat(follow_symlinks=False).st_size
    except OSError:
        return 0


def list_zip_images(zpath):
    """压缩包内全部媒体页名（图片 + webm 等），已自然排序。

    3.6.31：过滤 **0 字节条目**。zip 里可能存在同名的占位/损坏空条目（某些转录包
    把缺失页写成 0 字节的 0005.webp）——此前只按扩展名过滤，这些空条目被当成有效页
    计入页数，阅读器翻到它们读不出内容（用户报「部分页加载失效」）；若首页恰是空条目，
    封面也会取到一张根本读不出来的图。空文件不是页，应当排除。"""
    try:
        with zipfile.ZipFile(zpath) as z:
            names = [i.filename for i in z.infolist()
                     if not i.filename.endswith("/")
                     and os.path.splitext(i.filename)[1].lower() in PAGE_EXTS
                     and i.file_size > 0]
            names.sort(key=natural_key)
            return names
    except Exception:
        return []


def list_rar_images(rpath):
    if not RAR_AVAILABLE:
        return []
    try:
        with rarfile.RarFile(rpath) as rf:
            # 与 list_zip_images 同口径：过滤 0 字节条目（空文件不是页）
            names = [i.filename for i in rf.infolist()
                     if not i.filename.endswith("/")
                     and os.path.splitext(i.filename)[1].lower() in PAGE_EXTS
                     and i.file_size > 0]
            names.sort(key=natural_key)
            return names
    except Exception:
        return []


def work_mtime(images, archives, path):
    """作品修改时间：取内部所有图片/压缩包的最大 mtime（文件夹作品），压缩包作品取文件 mtime。"""
    ts = []
    for _rel, p in list(images) + list(archives):
        try:
            ts.append(os.path.getmtime(p))
        except OSError:
            pass
    try:
        ts.append(os.path.getmtime(path))
    except OSError:
        pass
    return max(ts) if ts else 0.0


def _archive_page_entries(apath):
    """压缩包内全部页 → 统一页面描述列表（P2-7）：{"z"/"r": 包路径, "n": 包内页名}。"""
    aext = os.path.splitext(apath)[1].lower()
    key = "z" if aext in (".zip", ".cbz") else "r"
    if aext in (".zip", ".cbz"):
        names = list_zip_images(apath)
    elif aext in (".rar", ".cbr"):
        names = list_rar_images(apath)
    else:
        names = []
    return [{key: apath, "n": f} for f in names]


def page_media_name(pg):
    """页面描述 → 媒体文件名（判断 image/video 类型用）。"""
    return pg["n"] if "n" in pg else pg["p"]


def mime_for(name):
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".gif": "image/gif", ".bmp": "image/bmp",
        ".webm": "video/webm",
    }.get(os.path.splitext(name)[1].lower(), "application/octet-stream")


def _is_root_loose(path):
    """作品是否落在文库根目录的散包/散目录（而非某个社团子目录内）。

    待定词条印证只改 bare 的**身份**（circle），不改归档位置：
      * 散包（根目录平铺的压缩包 / 根目录下的裸名子目录）的归档名就是词条本身，
        印证把 circle 改了会让作品 key 跳变 → 用 work["_group"] 锚回原词条，
        阅读进度/收藏的 key 才不丢；
      * 目录内作品的归档名本来就是所在目录名，印证只动身份不动归档，无需锚定。"""
    root = str(CFG.get("root", "") or "").rstrip(os.sep)
    if not root or not path:
        return False
    return os.path.dirname(os.path.abspath(path)) == os.path.abspath(root)


# ---------------------------------------------------------------
# 文件内容工具（导入去重 / 收件箱半成品识别 / 类型嗅探）
# ---------------------------------------------------------------
def _sniff_ext(head):
    """按文件头魔数判断类型（返回小写扩展名含点；未知返回 ""）。"""
    head = bytes(head[:16])
    if head.startswith(b"PK\x03\x04"):
        return ".zip"
    if head.startswith(b"Rar!\x1a\x07"):
        return ".rar"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head.startswith(b"\x1aE\xdf\xa3"):
        return ".webm"
    if head.startswith(b"GIF8"):
        return ".gif"
    return ""


def _sha1_file(path, chunk=1024 * 1024):
    """流式 SHA1（不整文件进内存）。失败返回 None。"""
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
    except OSError:
        return None
    return h.hexdigest()


def _is_part_name(name):
    """下载半成品及其来源标记（crawl_wnacg 的断点续传产物）。
    .part.src 结尾是 .src —— 只判 `.part` 后缀会让这类标记漏进收件箱变成
    「不支持的文件类型」垃圾条目，必须一并排除。"""
    low = str(name).lower()
    return low.endswith(".part") or low.endswith(".part.src")
