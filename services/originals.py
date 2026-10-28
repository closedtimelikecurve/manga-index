# -*- coding: utf-8 -*-
"""services/originals.py —— 原作分区的归一与词条库维护（3.6.56 Stage7 从 app.py 抽出）。

宽松相等（NFKC）、别名链折叠、多候选选名（有作品的真实分区优先）、
config 词条库增删（分区创建/移除）。
"""
import os
import re
import unicodedata

import meta_store as meta

import djc_parse as _dp
import common
from panel.host import h

def _loose_term(s):
    """词条宽松归一：NFKC（全半角/兼容字符统一）→ 去空白/下划线/连字符/斜杠 + 小写。

    **必须与 meta_store._loose 完全同规则**（两处各自维护，改动要同步）：
    「添加原作」子串搜索、canon 归一、分区别名判定共用。
    3.6.38 #38：补 NFKC——否则全角 ！ 与半角 ! 被判为不同写法
    （meta_store._loose 加了而此处漏加过一次，表现为识别能过、但归并与别名
    判定仍把两种写法当成两个分区）。"""
    s = unicodedata.normalize("NFKC", str(s or ""))
    return re.sub(r"[\s_\-/]+", "", s).lower()

def _canon_original(term):
    """词条 → 词条库规范名：宽松变体（大小写/分隔符/全半角差异）优先，_norm 精确次之，
    都找不到就用用户输入原样。manual 标签与解析器 canon 必须同名，否则同一原作
    会分裂成两个分区（3.6.19）。宽松优先：用户输 fate grand order 应归一到内置的
    FateGrand Order，而不是把变体本身当成新规范名。

    3.6.38 #38：NFKC 之后「Fate／Grand Order」（全角斜杠）与「FateGrandOrder」宽松串相同，
    一个 query 可能命中多个候选名。此时的目标名按下列优先级选（3.6.39 定稿）：

    ① **库里已存在的实际分区**（作品多的优先）——用户说的"这两者本身就是一个类别"，
       就是要把变体并进他已经在用的那个分区，而不是并进某个只有写法正确、却没作品的
       幽灵名；否则"归一"反而制造分裂。
    ② 空分区（用户显式建过、还没有作品）。
    ③ 本身已是规范形态的（NFKC 不改变它），避免落到带全角标点的历史写法。
    ④ 名单首位。

    注意：这里只决定**目标名**，不改变"宽松相等即同一类别"这个判断本身——全角/半角、
    空格/斜杠差异的写法仍然一律归一（实测 Fate Grand Order / FateGrand Order /
    Fate／Grand Order 均归到同一个名字）。"""
    lt = _loose_term(term)
    if lt:
        cands = list(dict.fromkeys(c for c in h().state.norm_to_canon.values()
                                   if _loose_term(c) == lt))
        if cands:
            try:
                live = {z["name"]: int(z.get("works") or 0) for z in meta.originals_all()}
            except Exception:
                live = {}
            existing = [(live[c], c) for c in cands if c in live]
            if existing:
                return max(existing, key=lambda t: t[0])[1]   # ① / ② 作品多者优先
            for c in cands:
                if unicodedata.normalize("NFKC", c) == c:
                    return c                                   # ③ 规范形态
            return cands[0]                                    # ④
    n = _dp._norm(term)
    return h().state.norm_to_canon.get(n) or term

def _canon_original_name(name):
    """原作名归一（3.6.19）：沿原作别名链折叠到规范名，visited 防环。
    与 _canon_circle_name/_canon_author 并列，只查原作别名表。
    3.6.39：折叠逻辑与 _reload_originals 共用 _fold_alias_chain（单一实现，
    否则一处改、一处漏——本项目的经典踩坑）。"""
    return h()._fold_alias_chain(name, h()._original_aliases())

def _originals_config_set(drop=(), add=()):
    """把原作词条库改造一遍（3.6.27 起按**字面**匹配）：删 drop 里的词条、加 add 里的词条，
    然后重载词条库并清掉因此失去词条的 stale 标签（manual original 不再被 sync_scan
    自动清理，词条删了分区必须显式清，否则分区永不消失——3.6.19 的教训）。
    返回是否真的改了 config（决定要不要 save_config + 重载）。"""
    cur = [str(x).strip() for x in (h().CFG.get("originals") or []) if str(x).strip()]
    # 3.6.27：改名路径传进来的 drop/add 是**用户输入的精确名**，故按字面匹配——
    # 宽松匹配会连词条库里别的写法变体一起删掉（用户可能特意保留两个写法）。
    # 「移除分区」端点仍是模糊操作，它在自己的流程里按宽松匹配，不走本函数。
    drop_set = {str(x).strip() for x in drop if str(x).strip()}
    add_list = [str(x).strip() for x in add if str(x).strip()]
    keep = [x for x in cur if x not in drop_set]
    changed = len(keep) != len(cur)
    for a in add_list:
        if a not in keep:
            keep.append(a)
            changed = True
    if not changed:
        return False
    h().CFG["originals"] = keep
    h().save_config(h().CFG)
    h()._reload_originals()
    for stale in meta.originals_stale_names(h().state.originals):
        meta.originals_remove(stale)
    return True
