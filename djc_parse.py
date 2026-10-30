# -*- coding: utf-8 -*-
"""
文件名解析与规范化共享模块 —— migrate.py 与 app.py 共用
=======================================================
解析规则（v4）：
  0. 社团名 = [] 内词条 **减去** () 内词条：
        [Peach Candy (ゆき恵)] → 社团名 Peach Candy，个人名 ゆき恵
  1. 个人名：社团主括号内 () 的内容（非汉化组）
  2. 汉化组词条：[] 或 () 含 汉化/漢化/中国翻訳/中国語/搬運/搬运/個人/个人
     → 一律视为汉化组词条，绝不作为社团名或个人名；全角【…】同样归入汉化组
  3. 展会标签：() 匹配 C+数字 / FF+数字 / COMIC1 等
  4. 原作标签：() 匹配原作名单（config.json 的 originals 可扩展）
  5. 待定词条：主括号为裸 [a]（无 ()）时 → 个人名= a（前端按个人名展示），
     后端标记 bare= a 为“待定词条”（供跨作品印证其归属：社团名或某社团的个人名）；
     无法匹配社团/个人时按其本身建立新档
  6. normalize_filename：把文件名规范为统一格式
      [無修正] (展会) [社团名 (个人名)] 标题 【汉化组名】 (原作名) [其他词条]
      （自由文本中的 "_" 会自动替换为空格；原作词条等规范名除外）
"""
import json
import os
import re


# ---- 纯文本/括号处理（3.6.64 抽至 panel/text.py；此处再导出保持 djc_parse.* 命名面）----
# _dedup / _clean_title 是 analyze_filename 内部要用到的，必须一并导入（不只是对外暴露）。
from panel.text import (                                              # noqa: E402,F401
    clean_spaces, normalize_symbols, sanitize_windows_name,
    strip_wrappers, repair_name, _dedup, _clean_title, _norm,
)
from panel.terms import (                                             # noqa: E402,F401
    DEFAULT_ORIGINALS, GROUP_KEYWORDS, is_group_term, is_platform_term,
    load_originals, _skip_term,
)
# 字形折叠（繁/日文新字体 → 简体）统一放在 panel/variants.py：3.6.173 起它还负责
# "同一社团被 JM 繁体与日文原名劈成两档"这条，表在那里维护、加字只需一行。
from panel.variants import fold as fold_variants                      # noqa: E402

# ---- 词条规范化键（3.6.156 从 crawlers/wnacg_text.py 下沉）----
# services/crawl_dup 等管理层代码也用它做去重比对——文本折叠是中性解析能力，
# 不该让管理层顶层依赖 crawlers 包（公开发行版不含 wnacg 站点适配也能导入）。
_PUNCT = ('[]()（）【】「」『』・·。.，,～~〜!！?？♡♥♪☆★×+:：;；|｜／/\\—_-'
          '"\'“”‘’')

# ⚠ 方向是「简体 → 日文/繁体」，**只给 wnacg 搜索变体用**（wnacg_match 拿它把简体标题
# 转成站点上的日文写法再试一轮：调查→調査、时间→時間）。它和 `panel.variants.fold`
# （繁/日 → 简，用于身份比对键）方向相反、职责不同，**不要合并**——把这里改成简体会让
# 那个搜索变体静默失效（不再报错，只是再也没有第二轮查询）。
_VARIANT_MAP = str.maketrans({"宫": "宮", "乐": "楽", "经": "経", "译": "訳",
                              "变": "変", "实": "実", "满": "満", "传": "伝",
                              "查": "査", "时": "時", "调": "調", "亚": "亜",
                              "间": "間", "无": "無", "后": "後", "阳": "陽",
                              "恋": "戀", "声": "聲", "画": "畫", "丝": "絲"})


def _norm_key(s):
    """词条 → 规范化比对键：NFKC + 小写 + 去空白 + 简繁/日中字形折叠 + 去标点。"""
    import unicodedata
    s = unicodedata.normalize("NFKC", str(s)).lower()
    s = re.sub(r"\s+", "", s)
    s = fold_variants(s)                   # 字形折叠（宫/宮、浜/濱/滨…）
    return s.translate(str.maketrans("", "", _PUNCT))


EVENT_RES = [
    re.compile(r"^C\d{2,3}$"),          # C97 / C100 / C101 / C102
    re.compile(r"^FF\d{1,3}$"),         # FF35 / FF36 …
    re.compile(r"^COMIC1\*?\d+$"),      # COMIC1☆13 → 归一化后 COMIC1*13
]


# 命名符号归一表（命名规范化的一环）：
#   全角括号 → 半角（[社团（画师）] 必须能识别成 [社团 (画师)]，否则整串退化成待定词条）
#   全角逗号 / 日文顿号 → 半角逗号（同一合作社团「A、B」「A，B」「A,B」三种写法归一，
#   否则磁盘上会被建成两个目录——真实库里 きのこのみ,brand nyu 与 きのこのみ、brand nyu 即为此例）
# 注意：【】不动——本系统把全角【…】一律视为汉化组词条，转成 [] 会改变语义。


# Windows 保留设备名（含带扩展名形式，如 CON.txt 同样非法）：CON/PRN/AUX/NUL/COM1-9/LPT1-9


# 前置括号 (X) [画师] 中的 X 不视为社团的例外词（版本/媒介标记，常被误写作开头）
_LEAD_PAREN_SKIP = {
    "dl版", "同人誌", "同人誌dl版", "一般コミック", "成年コミック", "成年同人誌",
    "コミック", "電子書籍", "短編", "sample", "raw", "cg集", "音声作品", "成年漫画",
}


def _lead_paren_circle(name, primary_bracket):
    """前置括号格式 (社团) [画师] 标题：name 以 () 开头且紧邻主括号时，
    返回该 () 内容作为社团名（画师 = 主括号词条）；不符合条件返回 None。
    仅识别这一严格位置——尾部的 (COMIC …)/(C97)/杂志名等不会误判。"""
    if not name or not primary_bracket:
        return None
    m = re.match(r"^\s*\(([^()]*)\)\s*\[([^\[\]]*)\]", name)
    if not m or normalize_symbols(m.group(2).strip()) != primary_bracket:
        return None
    t = m.group(1).strip()
    if (not t or t.lower() in _LEAD_PAREN_SKIP
            or is_group_term(t) or any(er.fullmatch(_norm(t)) for er in EVENT_RES)
            or NORM_TO_CANON.get(_norm(t))):   # 前置 (原作名) 不当作社团
        return None
    return t


def split_circle_personal(bracket):
    """把 [C (P)] 内容拆成 (社团名 C, 个人名 P)。
    取第一个“非汉化组”的 ()；返回 (C, P)；若 (P) 内容为汉化组则继续找。
    无 () → 返回 (None, 整个内容)。"""
    b = bracket
    for m in re.finditer(r"\(([^()]*)\)", b):
        t = m.group(1).strip()
        if t and not is_group_term(t):
            c = (b[:m.start()] + b[m.end():]).strip()
            return c, t
    return None, b


# 合作作品作者分隔符（E-Hentai 惯例 "A x B"；&/＆ 直连；× 全角乘号；、为日文顿号）。
# 拉丁字母 "x" 必须两侧带空格——避免拆散 Rex、xenon 这类含 x 的罗马字名。
_AUTHOR_SEP_RES = (re.compile(r"\s*[&＆]\s*"), re.compile(r"\s*×\s*"),
                   re.compile(r"\s+[xX]\s+"), re.compile(r"\s*、\s*"),
                   re.compile(r"\s*,\s*"))   # 顿号已归一成逗号；直连逗号同样是合作分隔符


def split_authors(text):
    """把作者串按合作分隔符拆成列表；不是合作作品（拆不出 ≥2 个非空段）→ 单元素列表。
    合作作品两名各自成立，不造"合作体"新词（E-Hentai：artist:A x artist:B）。"""
    t = (text or "").strip()
    if not t:
        return []
    parts = [t]
    for sep in _AUTHOR_SEP_RES:
        if any(sep.search(p) for p in parts):
            new = []
            for p in parts:
                new.extend(x for x in sep.split(p) if x.strip())
            parts = new
    out = []
    for p in parts:
        p = p.strip(" 　")
        if p and p not in out:
            out.append(p)
    return out if len(out) >= 2 else ([out[0]] if out else [])


# 合作社团分隔符：社团区域出现 "," / "，" / "、" 时视为多社合作一部作品
# （例：[社团A、社团B] 作品名 → 同时属于社团A 与社团B，前端按各自社团交叉引用呈现）。
_CIRCLE_SEP_RES = (re.compile(r"\s*,\s*"), re.compile(r"\s*，\s*"), re.compile(r"\s*、\s*"))


_WRAPPED_RE = re.compile(r"\([^()]*\)|（[^（）]*）|\[[^\[\]]*\]|【[^【】]*】")


def split_circles(text):
    """把社团区域按合作分隔符拆成社团列表；拆不出 ≥2 个 → 返回 [原名]（或空输入的 []）。
    与合作作者同理：不造"合作体"新词，每个社团各自成立。

    成对括号内的内容整体保护：[milkberry，たまかけ屋（如月みゆ，たまかけ）]
    里的全角括号内部逗号**不是**社团分隔符（那是一位画师的"社团 (笔名)"写法），
    拆开会把名字切碎，所以先把括号段整段占位、拆完再还原。"""
    t = (text or "").strip()
    if not t:
        return []
    holders = []

    def _stash(m):
        holders.append(m.group(0))
        return "\x00%d\x00" % (len(holders) - 1)

    def _restore(s):
        return re.sub("\x00(\\d+)\x00", lambda m: holders[int(m.group(1))], s)

    parts = [_WRAPPED_RE.sub(_stash, t)]
    for sep in _CIRCLE_SEP_RES:
        if any(sep.search(p) for p in parts):
            new = []
            for p in parts:
                new.extend(sep.split(p))
            parts = new
    out = []
    for p in parts:
        p = _restore(p).strip(" 　")
        if p and p not in out:
            out.append(p)
    return out if len(out) >= 2 else ([out[0]] if out else [])


def primary_bracket_info(name):
    """
    解析作品名的主括号。
    返回 (kind, circle, personal, bare)：
      kind='circle' → circle=社团名(已减()内容), personal=个人名, bare=''
      kind='bare'   → circle='', personal='', bare=裸词条名（待定）
      kind='none'   → 全部为空
    """
    # 符号先归一再裁决：全角括号 → 半角，才能把 [社团（画师）] 认成 [社团 (画师)]；
    # 顿号 → 逗号，合作社团「A、B」才与「A,B」同归一种写法。
    brackets = [normalize_symbols(b.strip()) for b in re.findall(r"\[([^\[\]]*)\]", name)]
    candidates = [b for b in brackets if not _skip_term(b)]
    if not candidates:
        return "none", "", "", ""
    chosen = candidates[0]
    for b in candidates:
        if "(" in b and ")" in b:
            chosen = b
            break
    c, p = split_circle_personal(chosen)
    if c is not None:
        return "circle", c, p, ""
    lead = _lead_paren_circle(name, chosen)
    if lead is not None:
        return "circle", lead, chosen, ""
    return "bare", "", "", chosen


def circle_of(name):
    """返回作品所属社团名（[]内容 减 ()内容；裸词条或汉化组 → ""）。"""
    kind, c, _p, _b = primary_bracket_info(name)
    return c if kind == "circle" else ""


def bare_of(name):
    """返回作品名里的待定词条（裸 [] 内容）；无则 ""。"""
    kind, _c, _p, b = primary_bracket_info(name)
    return b if kind == "bare" else ""


def personal_of(name):
    """返回作品个人名（[C (P)] 的 P；裸词条情况下前端视词条为个人名 → 返回词条）。"""
    kind, _c, p, b = primary_bracket_info(name)
    if kind == "circle":
        return p
    if kind == "bare":
        return b
    return ""


def _replace_author_token(text, old, new):
    """在作者串里把等于 old 的**整段**替换为 new，原分隔符样式原样保留。
    返回 (新串, 是否发生替换)。只认整段相等——"Rex" 不会被 "Re" 误伤。"""
    seps = []
    for rex in _AUTHOR_SEP_RES:
        for m in rex.finditer(text):
            seps.append((m.start(), m.end()))
    seps.sort()
    out, last, changed = [], 0, False
    for s, e in seps:
        seg = text[last:s]
        if seg.strip(" 　") == old:
            out.append(new); changed = True
        else:
            out.append(seg)
        out.append(text[s:e])          # 分隔符原样
        last = e
    seg = text[last:]
    if seg.strip(" 　") == old:
        out.append(new); changed = True
    else:
        out.append(seg)
    return "".join(out), changed


def rename_personal_in_name(fname, old, new):
    """把作品文件名**主括号内**的作者词条 old 换成 new（标题部分绝不动）。
    覆盖三种写法：[社团(作者)] / [作者]（裸词条）/ [社团(A & B)]（合作只换命中那段）。
    未发生替换时原样返回。调用方应先用 parse_filename 确认 old 确是该作品的作者之一。"""
    if not fname or not old or not new or old == new:
        return fname
    m = re.search(r"\[([^\[\]]*)\]", fname)
    if not m:
        return fname
    bracket = m.group(1)
    # 作者区定位：先半角 ()，再全角 （）——文件名原样输出，不做符号归一
    pm = re.search(r"\(([^()]*)\)", bracket)
    if pm is None:
        pm = re.search(r"（([^（）]*)）", bracket)
    if pm:                                     # [社团(作者)]：只动 () 内的作者串
        new_inner, changed = _replace_author_token(pm.group(1), old, new)
        if not changed:
            return fname
        new_bracket = bracket[:pm.start(1)] + new_inner + bracket[pm.end(1):]
    else:                                      # [作者] 裸词条：整个括号内容即作者串
        new_bracket, changed = _replace_author_token(bracket, old, new)
        if not changed:
            return fname
    return fname[:m.start(1)] + new_bracket + fname[m.end(1):]


def parse_filename(name, originals=None, norm_to_canon=None):
    """
    解析作品文件名。
    返回 {"circle", "circles", "personal", "bare", "personals", "tags":[(类型,名称),...]}
    类型: event / original / personal / group(汉化组) / other
    personals: 作者列表（合作作品 "A & B"/"A × B"/"A x B" 拆开，两名各自成立；
               非合作 → 单元素列表；bare 待定词条同样可拆）。
    personal: 兼容字段 = personals[0]（历史单值语义，保留第一作者）。
    circles:  合作社团列表（社团区域含 ","/"，"/"、" 时拆开；否则为 [原名]）。

    3.6.64 结构：标签收集在 `_paren_tags`，单条归类在 `_tag_type`。
    """
    norm_to_canon = norm_to_canon or {}
    kind, circle, personal, bare = primary_bracket_info(name)
    shown_personal = personal if kind == "circle" else bare
    personals = split_authors(shown_personal) if shown_personal else []
    # 合作社团：社团区域（[C (P)] 的 C；无社团时看裸词条 bare）出现 , ， 、
    # → 拆成多个社团各自成立，上层据此把作品交叉归入每个社团。
    circles = split_circles(circle if kind == "circle" else bare)
    return {"circle": circle,
            "circles": circles,
            "personal": (personals[0] if personals and kind == "circle" else personal),
            "bare": bare, "personals": personals,
            "tags": _paren_tags(name, circle, shown_personal, personals, norm_to_canon)}


def _paren_tags(name, circle, shown_personal, personals, norm_to_canon):
    """逐个 (…) 记标签；重复的 (类型, 名称) 只记一次（保序）。"""
    tags, seen = [], set()

    def add(ttype, tname):
        key = (ttype, tname)
        if key not in seen:
            seen.add(key)
            tags.append(key)

    for m in re.finditer(r"\(([^()]*)\)", name):
        t = m.group(1).strip()
        if not t or (circle and t == circle):
            continue                       # 前置 (社团) 已作为社团，不再重复记标签
        if shown_personal and t == shown_personal:
            # 合作作品：括号内整串作者串 → 拆开各记一个 personal 标签
            for a in (personals or [t]):
                add("personal", a)
            continue
        add(*_tag_type(t, norm_to_canon))
    return tags


def _tag_type(t, norm_to_canon):
    """一个括号词条 → (类型, 名称)。优先级：展会 > 汉化组 > 原作（词条库）> 其他。"""
    if any(er.fullmatch(_norm(t)) for er in EVENT_RES):
        return "event", t
    if is_group_term(t):
        return "group", t
    canon = norm_to_canon.get(_norm(t))
    if canon is not None:
        return "original", canon
    return "other", t


# ---------------------------------------------------------------
# 文件名规范化（导入 / 增补信息 共用引擎）
# ---------------------------------------------------------------
TOKEN_RE = re.compile(r"\[[^\[\]]*\]|\([^()]*\)|【[^】]*】")


# ---------------------------------------------------------------
# 括号纠错（增补信息/归档输入容错）：用户把 "[社团 (个人)]" 整段粘进「社团名」栏、
# 或在「展会」栏填 "(C102)"、在「其他信息」里带括号粘词条，都会生成嵌套括号
# （[[…]] / ((…)) ）。这里两层兜底：字段层剥壳 + 成品名再纠错一遍。
# ---------------------------------------------------------------


def analyze_filename(name):
    """把文件名拆解为组件（v4 语义）：
    {kind, circle, personal, bare, uncensored, groups, events, originals,
     cn_lang, other_brackets, other_parens, title}

    3.6.64 结构：本函数只做「扫 token → 定主括号 → 组装」，
    分流规则在 `_take_bracket_token`（【】/[]/() 三套），主括号裁决在 `_pick_primary`。
    """
    bag = _token_bag()
    chunks, last = [], 0
    for m in TOKEN_RE.finditer(name):
        chunks.append(name[last:m.start()])
        last = m.end()
        # 词条区符号归一（标题 chunks 不受影响，标题里的顿号/全角括号保持原样）
        _take_bracket_token(m.group(0), bag)
    chunks.append(name[last:])

    kind, circle, personal, bare, others = _pick_primary(bag)
    # 主括号裁决完成后，把禁漫词条合并进其他（不会被裁决重建覆盖）
    other_brackets = _dedup(others + [x for x in bag["jm_other"] if x not in others])
    # 前置括号格式 (社团) [画师]：裸词条 + 开头() → 等价 [社团 (画师)]
    kind, circle, personal, bare, other_parens = _apply_lead_paren(
        name, kind, circle, personal, bare, bag["other_parens"])

    return {
        "kind": kind,
        "circle": circle,
        "personal": personal,
        "bare": bare,
        "uncensored": bag["uncensored"],
        "groups": _dedup(bag["groups"]),
        "events": _dedup(bag["events"]),
        "originals": _dedup(bag["originals"]),
        "cn_lang": _dedup(bag["cn_lang"]),
        "other_brackets": _dedup(other_brackets),
        "other_parens": _dedup(other_parens),
        "title": _clean_title("".join(chunks)),
    }


def _token_bag():
    """扫描期的累加器（避免 10 个并列局部变量在各分支里传来传去）。"""
    return {"groups": [], "events": [], "originals": [], "cn_lang": [], "jm_other": [],
            "other_parens": [], "uncensored": False,
            "circle_candidates": [], "bare_candidates": []}


def _take_bracket_token(raw, bag):
    """一个括号词条 → 按开括号类型分流进 bag（不改 chunks）。"""
    inner = normalize_symbols(raw[1:-1].strip())
    if not inner:
        return
    if raw.startswith("【"):
        bag["groups"].append(inner)          # 全角【…】一律视为汉化组词条
    elif raw.startswith("["):
        _take_square(inner, bag)
    else:                                    # ()
        _take_paren(inner, bag)


def _take_square(inner, bag):
    """[ … ]：语言标记 / 禁漫 / 汉化组 / 無修正 / [社团 (画师)] / 待定词条。"""
    if inner in ("中国翻訳", "中国語"):
        bag["cn_lang"].append(inner)         # 语言标记：保留为末尾 [中国語]/[中国翻訳]
    elif "禁漫" in inner:
        bag["jm_other"].append(inner)        # 主括号裁决会重建 other_brackets，先单独收集
    elif is_group_term(inner):
        bag["groups"].append(inner)          # 汉化组词条
    elif "無修正" in inner:
        bag["uncensored"] = True
    elif "(" in inner and ")" in inner:
        c, p = split_circle_personal(inner)
        bag["circle_candidates"].append({"full": inner, "circle": c or "", "personal": p or ""})
    else:
        bag["bare_candidates"].append(inner)


def _take_paren(inner, bag):
    """( … )：展会 / 汉化组 / 原作（词条库命中）/ 其他。"""
    if any(er.fullmatch(_norm(inner)) for er in EVENT_RES):
        bag["events"].append(inner)
    elif is_group_term(inner):
        bag["groups"].append(inner)
    else:
        canon = NORM_TO_CANON.get(_norm(inner)) if NORM_TO_CANON else None
        if canon is not None:
            bag["originals"].append(canon)
        else:
            bag["other_parens"].append(inner)


def _pick_primary(bag):
    """主括号裁决：优先 () 括号（[社团 (画师)]），否则第一个裸括号。

    返回 (kind, circle, personal, bare, 其余方括号列表)。
    """
    if bag["circle_candidates"]:
        first = bag["circle_candidates"][0]
        others = [x["full"] for x in bag["circle_candidates"][1:]] + bag["bare_candidates"]
        return "circle", first["circle"], first["personal"], "", others
    if bag["bare_candidates"]:
        return "bare", "", "", bag["bare_candidates"][0], bag["bare_candidates"][1:]
    return "none", "", "", "", []


def _apply_lead_paren(name, kind, circle, personal, bare, other_parens):
    """前置括号格式 (社团) [画师]：裸词条 + 开头() → 等价 [社团 (画师)]。

    带"禁漫"的前置括号不视为社团。
    """
    if kind != "bare":
        return kind, circle, personal, bare, other_parens
    lead = _lead_paren_circle(name, bare)
    if lead is None or "禁漫" in lead:
        return kind, circle, personal, bare, other_parens
    return "circle", lead, bare, "", [p for p in other_parens if p != lead]


def normalize_filename(base, ext="", circle=None, personal=None):
    """
    把文件名（base 不含扩展名，ext 含前导点）规范为：
      [無修正] (展会) [社团名 (个人名)] 标题 【汉化组名】 (原作名) [其他词条]
    可用 circle/personal 覆盖主括号（供“待定词条印证后补全社团”场景）。
    自由文本中的 "_" 一律替换为空格（_norm 仅用于词条匹配，不在此处理；
    原作词条走词条库输出，保留其规范写法如 Re_Dive）。
    返回规范后的完整文件名；无法生成时返回 ""。

    3.6.64 结构：`_normalized_fields` 归一字段，`_compose_normalized` 拼装。
    """
    a = analyze_filename(base)
    fields = _normalized_fields(a, circle, personal)
    new = repair_name(" ".join(x for x in _compose_normalized(fields) if x))
    return (new + ext) if new else ""


def _normalized_fields(a, circle, personal):
    """词条类字段（社团/画师/待定词条）再做一次符号归一——caller 传入的值未必已归一。
    标题不动。空串一律归一为 ""，拼装层据此跳过。"""
    def sym(x):
        return normalize_symbols(clean_spaces(x)) if x else ""

    def clean_list(items):
        return [clean_spaces(x) for x in items if clean_spaces(x)]

    return {
        "circle": sym(a["circle"] if circle is None else circle),
        "personal": sym(a["personal"] if personal is None else personal),
        "bare": sym(a["bare"]),
        "title": clean_spaces(a["title"]),
        "uncensored": a["uncensored"],
        "events": a["events"],                    # 展会：正则匹配，保持原样
        "originals": a["originals"],              # 原作：词条库规范名，保留 _ 等写法
        "cn_lang": a["cn_lang"],                  # [中国語]/[中国翻訳]：保持原样
        "groups": clean_list(a["groups"]),
        "other_brackets": clean_list(a["other_brackets"]),
        "other_parens": clean_list(a["other_parens"]),
    }


def _compose_normalized(f):
    """按规范顺序拼装（不含最终 repair_name）。"""
    parts = []
    if f["uncensored"]:
        parts.append("[無修正]")
    parts.extend(f"({e})" for e in f["events"])
    bracket = _primary_bracket_text(f["circle"], f["personal"], f["bare"])
    if bracket:
        parts.append(bracket)
    if f["title"]:
        parts.append(f["title"])
    if f["groups"]:
        parts.append("【" + " ".join(f["groups"]) + "】")
    parts.extend(f"({o})" for o in f["originals"])
    parts.extend(f"[{c}]" for c in f["cn_lang"])
    parts.extend(f"[{o}]" for o in f["other_brackets"])
    parts.extend(f"({p})" for p in f["other_parens"])
    return parts


def _primary_bracket_text(circle, personal, bare):
    """主括号文本：`[社团 (个人)]` → `[个人]` → `[待定词条]` → 空。"""
    if circle:
        if personal and f"({personal})" not in circle:
            return f"[{circle} ({personal})]"
        return f"[{circle}]"
    if personal:
        return f"[{personal}]"
    if bare:
        return f"[{bare}]"
    return ""


# 供 analyze_filename 使用的模块级原作映射（由 load_originals 填充）
NORM_TO_CANON = {}
