# -*- coding: utf-8 -*-
"""services/coop.py —— 合作社团（3.6.69 从 services/scan.py 拆出）。

`[A、B]` / `[A,B]` 这类多社合作作品的处理规则：
  1. `_coop_primary`：合作串里的"主社团"（归档目录 / key 用它）；
  2. `_work_coop_circles`：一部作品该同时归入哪几个社团；
  3. `_build_coop_groups`：把交叉引用并进各社团、给没有档案的子社团建虚拟条目、
     最后摘掉"合成社团"壳（`[A、B]` 目录）——但**只要还有归不走的作品就留壳**，
     宁可留一个空壳，也绝不让作品消失。
"""
import os

from panel.host import h


def _coop_primary(name):
    """合作社团名 "A、B" / "A,B" → 主社团 "A"（第一个）；非合作串原样返回。

    归档/入库时用：合作作品落到主社团的档案夹，其余子社团靠扫描时的交叉引用呈现，
    从而不再生成 "A、B" 这种把两个社团粘在一起的合成目录。"""
    parts = h()._dp.split_circles(h()._dp.normalize_symbols(name))
    return parts[0] if parts else h()._dp.normalize_symbols(name)


def _work_coop_circles(w, group_name):
    """该作品**另外**还属于哪些合作社团（[A、B] / [A,B] 拆出的子社团），不含其本社团。

    circles 是解析层给出的合作社团列表；少于 2 个说明不是合作作品，无需交叉引用。"""
    cs = [c for c in (w.get("circles") or []) if c]
    if len(cs) < 2:
        return []
    return [c for c in cs if c != group_name]


def _build_coop_groups(raw):
    """合作社团处理（3.7.4）：raw = [(社团名, [作品], 目录路径|None)]。

    对应"识别为多社合作 → 各社团交叉引用 → 不再单列一个合成社团"：
      1. 文件名 [A、B] / [A,B] 的作品 → 同时出现在 A 与 B 两个社团下；
         目标社团已存在（真实目录）就并入，不存在就按该社团名建虚拟档案。
      2. 社团名本身是合作串（历史把整个串当成一个社团名归档出的 "A、B" 目录）→
         其作品各自归位后不再作为独立社团出现；只有"无从归位"的作品仍留在其中
         （宁可留一个壳，也绝不让作品凭空消失）。

    3.6.69 结构：交叉引用 `_coop_refs`、合并 `_merge_coop_refs`、摘壳 `_prune_composite_groups`。
    """
    refs = _coop_refs(raw)
    if not refs:
        return raw
    return _prune_composite_groups(_merge_coop_refs(raw, refs))


def _coop_refs(raw):
    """子社团 → 该社团名下所有作品（按 path 去重，保序）。"""
    refs = {}
    for _name, works, _dir in raw:
        for w in works:
            for c in h()._work_coop_circles(w, _name):
                bucket = refs.setdefault(c, [])
                if all(x["path"] != w["path"] for x in bucket):
                    bucket.append(w)
    return refs


def _merge_coop_refs(raw, refs):
    """把交叉引用并进已有社团；尚无档案的子社团按虚拟社团补条目。"""
    out, seen = [], set()
    for name, works, dir_path in raw:
        ws = list(works)
        for w in refs.get(name, []):
            if all(x["path"] != w["path"] for x in ws):
                ws.append(w)
        out.append((name, ws, dir_path))
        seen.add(name)
    for c, ws in refs.items():
        if c not in seen:                 # 合作社团尚无自己的档案 → 建虚拟社团条目
            out.append((c, list(ws), None))
    return out


def _prune_composite_groups(items):
    """合作串命名的社团：作品全部交叉归位后摘掉这个"合成社团"；
    仍有归不走的作品时保留（宁可留壳，也不让作品消失）。"""
    pruned = []
    for name, works, dir_path in items:
        subs = h()._dp.split_circles(name)
        if len(subs) >= 2:
            remaining = [w for w in works if not (set(w.get("circles") or []) & set(subs))]
            if not remaining:
                continue                  # 全部作品已归位 → 不再作为独立社团
            works = remaining
        pruned.append((name, works, dir_path))
    return pruned
