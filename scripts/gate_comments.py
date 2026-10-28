#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/gate_comments.py —— F007：注释里点名的文件必须真实存在。

**针对的问题**：重构把文件拆了/删了，注释还写着旧名字。名字找不到时 IDE 不报错、
import 也不报错，只有读者会照着注释去找一个已不存在的文件（"static/app.js 里的
renderCrawl"——那文件已经拆成 13 片）。2026-10-20 的注释审计一次就扫出 8 处。

**判定口径（故意保守，宁可漏报不可误报）**：
  * 只看**反引号包裹**的文件名（如 xxx.py 外面加一对反引号）。项目约定：反引号 = 代码实体，
    写历史时用普通文字（"原来的 static/app.js"），规则天然不误伤。
  * 只扫注释：Python 用 `tokenize` 取 `#` 注释 + `ast` 取 docstring；JS/Kotlin 只看
    行首为 `//` `/*` `*` 的整行注释（行尾 `//` 注释不扫，避免把代码里的字符串当引用）。
  * 解析顺序：相对当前文件目录 → 相对项目根 → 全项目同名文件。三级都找不到才报。
  * 运行时产物（`_state/`、`config.json`、`meta.db` 等）不参与判定——它们本就不在仓库里。
  * 确实要提"已经删掉的文件"时，在该行写 `noqa: F007`。

回归：`tests/test_gate_comments.py`。
"""
import ast
import io
import os
import re
import tokenize

REF = re.compile(r"`([\w./\\-]+\.(?:py|kt|kts|js|json|md|bat|spec))`")

# 运行时生成 / 不入库的路径：提到它们不算"指向不存在的文件"
RUNTIME_PREFIX = ("_state/", "_logs/", "_cache/", "_inbox/", "backups/", "app_releases/")
_CACHE = {}

RUNTIME_NAMES = {"config.json", "meta.db", "panel.log", "Index_error.log",
                 "library_index.json", "region_covers.json", "crawl_state.json"}


def _is_runtime(ref):
    if ref.startswith(RUNTIME_PREFIX):
        return True
    base = os.path.basename(ref)
    # 3.6.150：爬虫清单改 ASCII 名（`待爬*.txt` → `pending_*.txt`），运行时名单随之更新
    return base in RUNTIME_NAMES or base.startswith(("crawl_state", "pending_", "meta.db"))


def _python_comments(src):
    """(行号, 文本)：`#` 注释 + 模块/函数/类 docstring。"""
    out = []
    try:
        for tk in tokenize.generate_tokens(io.StringIO(src).readline):
            if tk.type == tokenize.COMMENT:
                out.append((tk.start[0], tk.string))
    except (tokenize.TokenError, IndentationError):
        pass
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for n in ast.walk(tree):
        if not isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue                                  # IfExp/Lambda 的 body 是单个表达式，不是语句列表
        body = getattr(n, "body", None) or []
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            for i in range(body[0].lineno, body[0].end_lineno + 1):
                out.append((i, "\x00doc"))
    return out


def _line_comments(src):
    """JS/Kotlin：整行注释（行首 `//` `/*` `*`），附行号。"""
    out = []
    in_block = False
    for i, ln in enumerate(src.split("\n"), 1):
        s = ln.strip()
        if s.startswith("//"):
            out.append((i, s))
        elif s.startswith("/*"):
            in_block = "*/" not in s
            out.append((i, s))
        elif in_block:
            out.append((i, s))
            if "*/" in s:
                in_block = False
    return out


def _index_basenames(root, skip):
    names = set()
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(("_", "."))]
        for f in files:
            names.add(f)
    return names


def _resolves(ref, here, root, index):
    if os.path.exists(os.path.normpath(os.path.join(here, ref))):
        return True
    if os.path.exists(os.path.normpath(os.path.join(root, ref))):
        return True
    return os.path.basename(ref) in index


def _index_cached(root, skip):
    key = (root, tuple(sorted(skip)))
    if key not in _CACHE:
        _CACHE[key] = _index_basenames(root, skip)
    return _CACHE[key]


def missing_refs(rel_path, src, root, skip=()):
    """返回 [(行号, 引用)]：注释里点名但三级解析都找不到的文件。"""
    index = _index_cached(root, skip)
    fname = os.path.basename(rel_path)
    here = os.path.join(root, os.path.dirname(rel_path))
    comments = _python_comments(src) if fname.endswith(".py") else _line_comments(src)
    out = []
    for lineno, text in comments:
        if text == "\x00doc":            # docstring 只有行号：取原文那一行
            text = src.split("\n")[lineno - 1]
        if "noqa: F007" in text:
            continue
        for m in REF.finditer(text):
            ref = m.group(1)
            if _is_runtime(ref):
                continue
            if not _resolves(ref, here, root, index):
                out.append((lineno, ref))
    return out


def check(rel_path, src, root, skip=()):
    """F007 的闸门适配：返回 (规则名, 消息) 列表，供 quality_gate 直接 extend。"""
    return [("F007 注释指向不存在的文件",
             f"{rel_path} L{ln} · `{ref}`（拆分/改名后忘了改注释？确属历史叙述请写 noqa: F007）")
            for ln, ref in missing_refs(rel_path, src, root, skip)]
