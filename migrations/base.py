# -*- coding: utf-8 -*-
"""migrations/base.py —— 整理脚本的共享常量、路径与工具函数（3.6.78 从 migrate.py 拆出）。

**APP_DIR 必须是 `<文库根>/_app`**（不是 `_app/migrations`）：默认文库根 = APP_DIR 的上级目录。
写错一层就会把程序目录当文库根去整理——这是本文件最危险的一行，改动前先跑
`python -c "from migrations.base import APP_DIR, DEFAULT_LIB_ROOT; print(APP_DIR, DEFAULT_LIB_ROOT)"`。
"""
import os
import sys
from collections import Counter, defaultdict

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LIB_ROOT = os.path.dirname(APP_DIR)
sys.path.insert(0, APP_DIR)

import common                                  # noqa: E402
import djc_parse                               # noqa: E402
from djc_parse import (                        # noqa: E402
    circle_of, bare_of, normalize_filename, load_originals,
    primary_bracket_info, clean_spaces,
)

# 加载原作名单（供规范化引擎识别 (原神)、(Fate) 等原作词条）
_, djc_parse.NORM_TO_CANON = load_originals(os.path.join(APP_DIR, "config.json"))

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
ARCHIVE_EXTS = {".zip", ".cbz", ".rar", ".cbr"}
NO_CIRCLE_DIR = "未分类"
IGNORE_DIRS = {"static", "templates", "__pycache__", ".git", ".idea", "node_modules", "venv",
               ".thumb_cache", "1区"}
IGNORE_DIRS.add(os.path.basename(APP_DIR))     # 程序目录本身（随所在位置自适应）
SELF_PUB_CIRCLE_THRESHOLD = 3


def ask(question):
    try:
        return input(question + " [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def dir_has_files(path):
    for _d, _dnames, fnames in os.walk(path):
        if fnames:
            return True
    return False


def unique_path(path, taken=()):
    """目标已存在（磁盘或计划内）→ 追加 (2)/(3)… 后缀，绝不覆盖。"""
    if not os.path.exists(path) and path not in taken:
        return path
    stem, ext = os.path.splitext(path)
    i = 2
    while True:
        cand = f"{stem} ({i}){ext}"
        if not os.path.exists(cand) and cand not in taken:
            return cand
        i += 1


def _iter_group_archives(group_path):
    for d, _dn, fnames in os.walk(group_path):
        for fn in fnames:
            if os.path.splitext(fn)[1].lower() in ARCHIVE_EXTS:
                yield os.path.join(d, fn)


def learn_registry(root):
    """从全部文件名学习：circles / personal_circles / selfpub"""
    circles, personal_circles, selfpub = set(), {}, {}
    for g in [x for x in os.listdir(root) if os.path.isdir(os.path.join(root, x))]:
        if g in IGNORE_DIRS or g.startswith("."):
            continue
        for fp in _iter_group_archives(os.path.join(root, g)):
            n = os.path.splitext(os.path.basename(fp))[0]
            kind, c, pp, b = primary_bracket_info(n)
            if kind == "circle":
                circles.add(c)
                if pp:
                    personal_circles.setdefault(pp, set()).add(c)
            elif kind == "bare":
                selfpub[b] = selfpub.get(b, 0) + 1
    for name, cnt in selfpub.items():
        if cnt >= SELF_PUB_CIRCLE_THRESHOLD:
            circles.add(name)
    return circles, personal_circles


def resolve_dir_target(dir_name, circle_count, bare_count, total, circles, personal_circles):
    """
    目录目标：(target, kind, embed_personal)
    安全原则：仅当目录内全部作品的解析结果一致（单一社团 / 单一裸词条）时才调整；
    混合内容目录（作者合集、合作混编）一律保留原样。
    """
    if not total:
        return dir_name, "keep", ""
    if circle_count:
        if len(circle_count) == 1 and len(circle_count) == total:
            target = next(iter(circle_count))
            return (dir_name, "same", "") if target == dir_name else (target, "circle", "")
        return dir_name, "mixed", ""     # 同一目录内出现多个社团 → 保留
    if bare_count:
        if len(bare_count) == 1 and len(bare_count) == total:
            a = next(iter(bare_count))
            if a in circles:
                return (dir_name, "same", "") if a == dir_name else (a, "circle-resolved", "")
            owners = personal_circles.get(a)
            if owners and len(owners) == 1:
                return (next(iter(owners)), "personal", a)
        return dir_name, "pending", ""
    return dir_name, "keep", ""
