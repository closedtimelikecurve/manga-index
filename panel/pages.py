# -*- coding: utf-8 -*-
"""页面组织工具 —— 3.7 结构重构：从 app.py 抽出。

目前只有「多版本作品检测」：页面按一级子目录分组，≥2 个组且每组 ≥5 页才视为
多版本（RJ 包惯例：日文原版/汉化版 两个目录各二十余页；根级散页/宣传图不参与）。
纯函数，无业务状态。
"""
import os
import re

# 显示名去「（png）」等后缀
_RE_VERSION_EXT = re.compile(r"（(?:png|jpg|jpeg|gif|webp)）\s*$")


def _page_versions(w):
    """返回 [{"name": 显示名（去 （png） 等后缀）, "idx": [绝对页序]}]。"""
    pages = w.get("page_files") or []
    groups = {}
    for i, pg in enumerate(pages):
        if "z" in pg or "r" in pg:
            path = str(pg["n"]).replace("\\", "/")
        else:
            try:
                path = os.path.relpath(str(pg.get("p") or ""), str(w.get("path") or "")).replace("\\", "/")
            except Exception:
                continue
        if "/" not in path:
            continue                      # 根级页面不参与版本分组（封面/宣传图）
        seg = path.split("/", 1)[0].strip()
        if seg:
            groups.setdefault(seg, []).append(i)
    if len(groups) < 2:
        return []
    vers = [{"name": _RE_VERSION_EXT.sub("", k).strip(), "idx": v}
            for k, v in groups.items() if len(v) >= 5]
    return vers if len(vers) >= 2 else []
