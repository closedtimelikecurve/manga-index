# -*- coding: utf-8 -*-
"""panel/naming.py —— 「增补信息 → 规范文件名」的纯函数层（3.6.45 结构重构 Stage4）。

为什么单独成模块：这条规则原来是 `app.api_supplement_info` 方法体里 70 多行顺序代码，
与 Flask 请求、find_work、_apply_rename 搅在一起，圈复杂度 90（全仓最高），
谁都不敢动——而它恰恰是**用户可见的命名契约**（README「文件名规范格式」一节）：

    [無修正] (展会) [社团 (个人)] 标题 【汉化组】 (原作) [其他词条]

现在把「字段归一」+「按规范拼装」收进这里，端点只负责 HTTP：取参 → 解析当前文件名 →
调本模块 → 落盘改名。收益：
  * **可单测**：不需要 Flask/文献库，喂 dict 就能验证命名规则；
  * **改一处读一个文件**：命名规则变更不必在当年 5000 行级的 app.py 里翻找；
  * **无副作用**：不读写文件、不碰数据库、不碰模块级状态（纯函数，行为与拆分前逐字对齐）。

依赖方向：本模块 → djc_parse（纯解析），**不反向依赖 app.py**，故不存在循环导入。
"""
from djc_parse import (clean_spaces, sanitize_windows_name, split_authors,
                       strip_wrappers, repair_name, _norm)


def canonical_from_fields(fields, analyzed, canon_author=None):
    """按「填表字段」生成规范文件名主干（**不含扩展名**）。

        参数
          fields       : 前端提交的 fields 字典（可只含部分键）
          analyzed     : `djc_parse.analyze_filename(当前文件名主干)` 的结果，用于留空兜底
          canon_author : 个人名归一函数（笔名别名 → 正名）。由调用方注入，因为别名表在
                         元数据层；不传则原样使用输入。

        返回
          规范名字符串；无任何内容可组成名字时返回 ""（调用方据此返回 400）。

        语义细节（与拆分前完全一致，逐条都有踩坑史，改动前先看 README/CHANGELOG）：
          * 表单字段 > 解析值；字段存在但为空 = 显式清空，仍回退到解析值（历史行为）；
          * `_` 一律转空格、清 Windows 非法字符；**原作名不清 `_`**（词条规范名要保留）；
          * 多作者以 " & " 连写，各段过笔名别名归一；
          * 「其他信息」里的词条若与社团/个人/展会/原作/标题/汉化组重复 → 丢弃；
          * 表单没有 other_info 栏（老客户端）时，跑**隐式兜底**：把原文件名里剩余的
            [cn_lang]/[方括号词条] 与 (圆括号词条) 原样带过来；
          * 其他信息里原本是圆括号的词条保持圆括号（"只是打开表单点保存"不得悄悄改形态）；
          * 最后过一遍 `repair_name`：任何来源的嵌套/重复/空括号在此收敛。
        """
    canon_author = canon_author or (lambda x: x)
    a = analyzed or {}
    vals = _normalize_fields(fields, a, canon_author)
    return repair_name(" ".join(p for p in _compose_parts(vals, a) if p))


def _clean(text, underscores=True):
    """剥外层括号 + `_`→空格（原作词条不清）+ Windows 非法字符清洗。"""
    raw = strip_wrappers(str(text or "").strip())
    return sanitize_windows_name(clean_spaces(raw) if underscores else raw)


def _pick(fields, key, fallback):
    """表单字段优先；字段缺失或为空都回退到解析值（历史行为，见模块 docstring）。"""
    return strip_wrappers(str(fields.get(key, "")).strip()) or (fallback or "")


def _clean_terms(items):
    """逐个清洗并丢掉空串（保留顺序，调用方负责去重）。"""
    out = []
    for x in items or []:
        t = _clean(x)
        if t:
            out.append(t)
    return out


def _join_authors(personal, canon_author):
    """`A & B` 合作作品：逐段过笔名归一，再以 " & " 连写（E-Hentai 惯例）。"""
    parts = split_authors(personal)
    if len(parts) >= 2:
        return " & ".join(canon_author(x) for x in parts)
    return canon_author(personal) if personal else ""


def _normalize_fields(fields, a, canon_author):
    """第一阶段：把提交字段与解析结果合成一组归一值（不做任何拼装）。"""
    has_translator = "translator" in fields
    translator_raw = str(fields.get("translator", "")).strip()
    other_info_raw = str(fields.get("other_info", "")).strip()
    uncensored = a.get("uncensored", False)
    if "uncensored" in fields:
        uncensored = bool(fields.get("uncensored"))

    vals = {
        "event": _clean(_pick(fields, "event", (a.get("events") or [""])[0])),
        "circle": _clean(_pick(fields, "circle", a.get("circle"))),
        "personal": _join_authors(_clean(_pick(fields, "personal", a.get("personal"))),
                                  canon_author),
        "title": _clean(_pick(fields, "title", a.get("title"))),
        # 原作名走词条规范名：不清 `_`
        "original": _clean(_pick(fields, "original", (a.get("originals") or [""])[0]),
                           underscores=False),
        "uncensored": uncensored,
        "has_other": "other_info" in fields,          # 老客户端不带这一栏 → 隐式兜底
        "translator_terms": _clean_terms(translator_raw.split() if has_translator
                                         else (a.get("groups") or [])),
        "other_brackets": _clean_terms(a.get("other_brackets")),
        "other_parens": _clean_terms(a.get("other_parens")),
        "paren_norms": {_norm(p) for p in (a.get("other_parens") or [])},
    }
    # 「其他信息」里与其他栏重复的词条直接丢掉（同一词条粘两处时自动收敛）
    taken = {_norm(vals[k]) for k in ("circle", "personal", "event", "original", "title")
             if vals[k]}
    taken |= {_norm(t) for t in vals["translator_terms"]}
    vals["other_terms"] = [t for t in _clean_terms(other_info_raw.split())
                           if _norm(t) not in taken]
    return vals


def _compose_parts(v, a):
    """第二阶段：按 `[無修正] (展会) [社团 (个人)] 标题 【汉化组】 (原作) [其他]` 顺序拼装。"""
    parts = []
    if v["uncensored"]:
        parts.append("[無修正]")
    if v["event"]:
        parts.append(f"({v['event']})")
    circle_part = _circle_part(v, a)
    if circle_part:
        parts.append(circle_part)
    if v["title"]:
        parts.append(v["title"])
    if v["translator_terms"]:
        parts.append("【" + " ".join(v["translator_terms"]) + "】")
    if v["original"]:
        parts.append(f"({v['original']})")
    if not v["has_other"]:
        # 老客户端没提交「其他信息」栏 → 整标题里的其余内容照旧带过来
        parts.extend(f"[{c}]" for c in a.get("cn_lang") or [])
        parts.extend(f"[{o}]" for o in v["other_brackets"])
        parts.extend(f"({p})" for p in v["other_parens"])
    # 「其他信息」栏按原形态回填：原本圆括号的保持圆括号
    parts.extend(("(%s)" % t) if _norm(t) in v["paren_norms"] else ("[%s]" % t)
                 for t in v["other_terms"])
    return parts

def _circle_part(v, a):
    """正文那条 `[社团 (个人)]`：无社团名时退回 [个人]，再退回 [待定词条]。"""
    if v["circle"]:
        if v["personal"] and f"({v['personal']})" not in v["circle"]:
            return f"[{v['circle']} ({v['personal']})]"      # 社团名已含个人名则不重复
        return f"[{v['circle']}]"
    if v["personal"]:                       # 未填社团名但保留词条 → [个人/待定词条]
        return f"[{v['personal']}]"
    if a.get("bare") and a["bare"] not in v["other_terms"]:   # 待定词条未进其他信息时保留
        return f"[{a['bare']}]"
    return ""
