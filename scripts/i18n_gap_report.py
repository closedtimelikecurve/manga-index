# -*- coding: utf-8 -*-
"""i18n 缺口清单（只读报表，不改任何代码）。

用途：回答"双端界面还有哪些系统文本没多语言化"，并给后续分批提供可复跑的底账。

产出 markdown（默认 `docs/i18n-gap-<YYYY-MM-DD>.md`）：
1. 概览：网页/APP 各有多少唯一文案未走 `t()`/`s()`、多少是"字典已有只差接线"、多少需要新译；
2. 明细：按文件列出未接线的文案（含行号），并标注该 key 在语言包里是否已有译文；
3. 缺译：已经用了 `t()`/`s()`/`data-i18n` 但语言包里查不到的 key（"假覆盖"）；
4. 建议分批顺序（按界面可见度，不按文件字母序）。

口径（与项目其它守卫一致）：
* key = 简体中文原文；
* APP 的 `AppI18n.sf("…%1…")` 也算已接线（模板句，译文里用 %1..%9）；
* 注释、字符串里的 `/*` 不会误当注释（引号感知扫描）；
* 纯数字/符号/纯英文不统计，只统计含中日韩统一表意文字的字面量。

用法：
    python scripts/i18n_gap_report.py            # 写到 docs/i18n-gap-<今天>.md
    python scripts/i18n_gap_report.py --out x.md # 指定路径
    python scripts/i18n_gap_report.py --quiet    # 只打印概览
"""
import argparse
import datetime
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(ROOT, "static", "js")
HTML = os.path.join(ROOT, "static", "index.html")
KT_DIR = os.path.join(ROOT, "android", "app", "src", "main", "java", "com", "biblioteca", "reader")
CJK = re.compile(r"[\u4e00-\u9fff]")
# 「是不是界面文案」的判据：含汉字**或**带 %1..%9 占位符。
# 只认汉字会让 `（%1）` 这类"纯标点 + 占位符"的 key 在报表与覆盖守卫里**隐身**
# （3.6.135 接线时发现：它明明写进了语言包，工具却看不见它，缺译也不会红）。
KEY_TEXT = re.compile(r"[\u4e00-\u9fff]|%[1-9]")
SKIP_JS = {"i18n_langs.js"}

# 界面可见度排序：先补一级界面，再补确认弹窗/长说明
WEB_ORDER = ["home", "search", "detail", "tag", "inbox", "crawl", "probe", "import",
             "core", "panel", "ctxmenu", "crawlmon", "reader", "probejob", "probecards",
             "router", "alias", "theme", "menu", "drawer", "probeclock"]
APP_ORDER = ["FeaturesHome", "FeaturesHomeFeeds", "FeaturesHomeRecs", "FeaturesSearch",
             "FeaturesWorks", "FeaturesCircle", "ArtistScreen", "InboxScreen",
             "FeaturesCrawl", "ProbeScreen", "FeaturesImport", "FeaturesAlias",
             "AppSheets", "AppState", "MainActivity", "ShelfScreen", "DownloadsScreen",
             "AppBars", "FeaturesCommon", "StatsScreen", "FavoritesScreen"]


# ---------- 扫描原语（引号感知，避免把字符串里的 /* 当注释） ----------

def strip_comments(src):
    out, i, n, quote = [], 0, len(src), ""
    while i < n:
        c = src[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if c == quote:
                quote = ""
            i += 1
            continue
        if c in "\"'":
            quote = c
            out.append(c)
            i += 1
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _string_end(src, pos):
    """从 pos 处的引号开始，返回结束引号**之后**的下标（跳过转义）。

    不能再用 `pos + len(值) + 2` —— `len()` 算的是反转义后的长度，
    而 key 里一旦有 `
` 这类转义，原始跨度就比它长，偏移会落进字符串中间，
    于是"key 后面不是冒号"→ 整条被当成缺译（3.6.132 的误报就是这个）。
    """
    q = src[pos]
    j = pos + 1
    while j < len(src):
        if src[j] == "\\":
            j += 2
            continue
        if src[j] == q:
            return j + 1
        j += 1
    return len(src)


def quoted_spans(src):
    """[(值, 起始下标)]：单/双引号字符串（跳过转义）。"""
    out, i, n = [], 0, len(src)
    while i < n:
        q = src[i]
        if q in "\"'":
            j, buf = i + 1, []
            while j < n and src[j] != q:
                if src[j] == "\n":
                    break
                if src[j] == "\\" and j + 1 < n:
                    buf.append(src[j + 1])
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            if j < n and src[j] == q:
                out.append(("".join(buf), i))
                i = j + 1
                continue
        i += 1
    return out


def call_args(src, names):
    """`name("…")` / `name('…')` 里被包裹的字面量集合。"""
    out = set()
    for name in names:
        start = 0
        while True:
            k = src.find(name + "(", start)
            if k < 0:
                break
            j = k + len(name) + 1
            while j < len(src) and src[j] in " \n\t":
                j += 1
            if j < len(src) and src[j] in "\"'":
                for val, pos in quoted_spans(src[j:j + 400]):
                    out.add(val)
                    break
            start = k + 1
    return out


def line_of(src, pos):
    return src.count("\n", 0, pos) + 1


DATA_MARKER = "i18n:data"


def data_literals(src):
    """标了 `// i18n:data` 的行里的字面量 → 数据字面量（文件名 / 格式记号），**不计入缺口**。

    来源：爬虫页的清单标题就是磁盘上的文件名（`pending_index.txt` …），翻了用户就找不到文件；
    收件箱的 `[無修正]` 是汉化组标记、`【直连词条】` 是粘贴内容的格式记号，同理。
    用**行内标记**而不是字符串白名单：文案改了标记跟着走，不会留下一条指向旧文案的白名单。
    注意标记必须写在**真正含该字面量**的那一行（跨行字符串请在起始行标）。
    """
    out = set()
    for line in src.split("\n"):
        if DATA_MARKER in line:
            out.update(val for val, _ in quoted_spans(line))
    return out


def code_literals(src):
    """含中文的字符串字面量（去注释后）→ {值: 首次出现的行号}；含 `i18n:data` 标记的行除外。"""
    skip = data_literals(src)
    src = strip_comments(src)
    found = {}
    for val, pos in quoted_spans(src):
        if CJK.search(val) and len(val) < 200 and val.strip() and val not in skip:
            found.setdefault(val, line_of(src, pos))
    return found


# ---------- 字典 ----------

def js_pack_pairs(path):
    """`'key': 'value'` 键值对（只认含中文的 key）。键在冒号前、值紧随其后。"""
    src = strip_comments(open(path, encoding="utf-8").read())
    spans, pairs = quoted_spans(src), {}
    for i, (val, pos) in enumerate(spans):
        j = _string_end(src, pos)
        while j < len(src) and src[j] in " \t":
            j += 1
        if j < len(src) and src[j] == ":" and KEY_TEXT.search(val) and i + 1 < len(spans):
            v, vpos = spans[i + 1]
            if vpos >= j:
                pairs[val] = v
    return pairs


def js_pack_keys(path):
    """`'key': 'value'` 里出现在冒号前的 key（只认含中文的）。"""
    return set(js_pack_pairs(path))


def kt_pack_keys(path):
    """`"key" to "value"` 的 key。"""
    src = open(path, encoding="utf-8").read()
    keys = set()
    for val, pos in quoted_spans(src):
        j = _string_end(src, pos)
        while j < len(src) and src[j] in " \t":
            j += 1
        if src.startswith("to ", j) and KEY_TEXT.search(val):
            keys.add(val)
    return keys


def web_packs():
    """{语言: key 集合}；zh-CN 是基准语言（key 本身），不需要包。

    3.6.135 起每个语言包分 2 片（`i18n_lang_<x>.js` + `i18n_lang_<x>_2.js`），
    文件名里的 `_2` 是分片号，不是语言码的一部分——同一语言的各片合并成一份 key 集合。
    """
    packs = {}
    for fn in sorted(os.listdir(JS_DIR)):
        if not (fn.startswith("i18n_lang_") and fn.endswith(".js")):
            continue
        base = re.sub(r"_\d+$", "", fn[len("i18n_lang_"):-3])
        lang = base.replace("_", "-")
        packs.setdefault(lang, set()).update(js_pack_keys(os.path.join(JS_DIR, fn)))
    return packs


def kt_pack_pairs(path):
    """`Strings*.kt` → {语言: {key: 译文}}。

    按 `"xx" to mapOf(` 切段收集——一个文件里装着 7 段语言块，段与段之间不得串味。
    返回值同时供缺口报表（只关心 key）与 `tests/test_app_i18n_coverage.py` 的
    占位符/汉字残留守卫使用：**口径只留一处**，否则两边慢慢会分成两套。
    """
    src = open(path, encoding="utf-8").read()
    packs = {}
    parts = re.split(r'("(?:[a-zA-Z\-]+)" to mapOf\()', src)
    cur = None
    for part in parts:
        m = re.match(r'"([a-zA-Z\-]+)" to mapOf\($', part)
        if m:
            cur = m.group(1)
            packs.setdefault(cur, {})
            continue
        if not cur:
            continue
        spans = quoted_spans(part)
        i = 0
        while i + 1 < len(spans):
            val, pos = spans[i]
            j = _string_end(part, pos)
            while j < len(part) and part[j] in " \t":
                j += 1
            if part.startswith("to ", j) and KEY_TEXT.search(val):
                v, vpos = spans[i + 1]
                if vpos >= j:              # 值确实紧随 key（排除 key 出现在注释/其它位置）
                    packs[cur][val] = v
                    i += 2
                    continue
            i += 1
    return packs


def app_packs():
    """{语言: key 集合}——语言包按批分文件（Strings / StringsExtra…），合并成一份。"""
    packs = {}
    for fn in sorted(os.listdir(KT_DIR)):
        if not (fn.startswith("Strings") and fn.endswith(".kt")):
            continue
        for lang, pairs in kt_pack_pairs(os.path.join(KT_DIR, fn)).items():
            packs.setdefault(lang, set()).update(pairs)
    return packs


# ---------- 报表 ----------

def _is_markup(text):
    """内联 HTML 模板片段（含标签/属性）——单独归类，否则"文案"清单里全是 `<span …>`。"""
    return "<" in text or '="' in text


def web_hardcoded():
    """{文件: {文案: 行号}}：去掉 t()/esc() 包裹后的裸中文（含内联 HTML 片段）。"""
    out = {}
    for fn in sorted(os.listdir(JS_DIR)):
        if not fn.endswith(".js") or fn.startswith("i18n_lang_") or fn in SKIP_JS:
            continue
        src = open(os.path.join(JS_DIR, fn), encoding="utf-8").read()
        # tf()/tf 也是翻译入口（3.6.132 起错误提示走占位模板），其首个参数同样是 key
        wrapped = call_args(strip_comments(src), ["t", "tf", "esc"])
        lits = {k: v for k, v in code_literals(src).items() if k not in wrapped}
        if lits:
            out[fn] = lits
    return out


def html_keys():
    src = open(HTML, encoding="utf-8").read()
    keys = set(re.findall(r'data-i18n(?:-ph|-title)?="([^"]+)"', src))
    return {k for k in keys if KEY_TEXT.search(k)}


def app_hardcoded():
    out = {}
    for fn in sorted(os.listdir(KT_DIR)):
        if not fn.endswith(".kt") or fn.startswith("Strings") or fn == "AppI18n.kt":
            continue
        src = open(os.path.join(KT_DIR, fn), encoding="utf-8").read()
        wrapped = call_args(strip_comments(src), ["AppI18n.s", "AppI18n.sf"])
        lits = {k: v for k, v in code_literals(src).items() if k not in wrapped}
        if lits:
            out[fn] = lits
    return out


def _order(names, preferred):
    rank = {n: i for i, n in enumerate(preferred)}
    return sorted(names, key=lambda n: (rank.get(os.path.splitext(n)[0], 999), n))


def web_used_keys():
    """已用 t('…') 或 data-i18n 标注的 key（这些缺译 = 用户看到的"假覆盖"）。"""
    used = set(html_keys())
    for fn in sorted(os.listdir(JS_DIR)):
        if not fn.endswith(".js") or fn.startswith("i18n_lang_") or fn in SKIP_JS:
            continue
        src = open(os.path.join(JS_DIR, fn), encoding="utf-8").read()
        used |= call_args(strip_comments(src), ["t"]) | call_args(strip_comments(src), ["tf"])
    return {k for k in used if KEY_TEXT.search(k)}


def build_report():
    wp, ap = web_packs(), app_packs()
    wh, ah, hk = web_hardcoded(), app_hardcoded(), html_keys()
    web_all = set().union(*wh.values()) if wh else set()
    app_all = set().union(*ah.values()) if ah else set()
    web_dict = set().union(*wp.values()) if wp else set()
    app_dict = set().union(*ap.values()) if ap else set()
    missing_web = {lang: (web_used_keys() - keys) for lang, keys in wp.items()}
    missing_app = {lang: (app_all - keys) for lang, keys in ap.items()}
    clean_all = {k for k in web_all if not _is_markup(k)}
    stats = {
        "web_hard": len(web_all), "web_in_dict": len(web_all & web_dict),
        "web_new": len(web_all - web_dict),
        "web_clean": len(clean_all),
        "web_clean_new": len(clean_all - web_dict),
        "web_markup": len(web_all) - len(clean_all),
        "app_hard": len(app_all), "app_in_dict": len(app_all & app_dict),
        "app_new": len(app_all - app_dict),
        "html_keys": len(hk), "html_missing": len(hk - web_dict),
        "web_used": len(web_used_keys()),
        "web_used_missing": len(web_used_keys() - web_dict),
        "union_new": len((web_all - web_dict) | (app_all - app_dict)),
        "langs_web": len(wp), "langs_app": len(ap),
    }
    return stats, (wh, ah, hk, wp, ap, missing_web, missing_app, web_dict, app_dict)


def _section_header(stats):
    return [
        "# 双端多语言缺口清单（%s 生成）" % datetime.date.today().isoformat(),
        "",
        "> 由 `scripts/i18n_gap_report.py` 生成，**只读盘点**。key = 简体中文原文；",
        "> 语言包：网页 %d 种（`static/js/i18n_lang_*.js`）、APP %d 种（`Strings*.kt`）。"
        % (stats["langs_web"], stats["langs_app"]),
        "",
        "## 一、概览",
        "",
        "| 项 | 唯一文案 | 字典已有（只差接线） | 需要新译 |",
        "|---|---:|---:|---:|",
        "| 网页 JS（未走 t()，纯文案） | %d | %d | %d |" %
        (stats["web_clean"], stats["web_in_dict"], stats["web_clean_new"]),
        "| ↳ 内联 HTML 模板片段 | %d | — | 需按片段重构成 t() 后再译 |" % stats["web_markup"],
        "| APP Kotlin（未走 s()） | %d | %d | %d |" %
        (stats["app_hard"], stats["app_in_dict"], stats["app_new"]),
        "| 网页静态 HTML（data-i18n） | %d | — | %d 无译文 |" %
        (stats["html_keys"], stats["html_missing"]),
        "",
        "| 已用 t()/data-i18n 的 key | %d | — | %d 个在语言包里查不到 |" %
        (stats["web_used"], stats["web_used_missing"]),
        "",
        "**双端合计需新增 key：约 %d 条**（纯文案口径；× %d 语言 ≈ %d 条译文）。"
        % (stats["web_clean_new"] + stats["app_new"], stats["langs_web"],
           (stats["web_clean_new"] + stats["app_new"]) * stats["langs_web"]),
        "",
    ]


def _section_web(wh, web_dict):
    L = ["## 二、网页 JS：还没走 t() 的纯文案"]
    for fn in _order(wh, WEB_ORDER):
        items = {k: v for k, v in wh[fn].items() if not _is_markup(k)}
        if not items:
            continue
        have = sum(1 for k in items if k in web_dict)
        L += ["", "### `static/js/%s`（%d 条，其中 %d 条字典已有）" % (fn, len(items), have), ""]
        for k in sorted(items, key=lambda x: items[x]):
            mark = "✅" if k in web_dict else "＋"
            L.append("- L%d %s `%s`" % (items[k], mark, k.replace("`", "'")))
    return L


def _section_markup(wh):
    L = ["", "## 二·附：内联 HTML 模板片段（需先拆模板再接 t()）", "",
         "| 文件 | 片段数 |", "|---|---:|"]
    for fn in _order(wh, WEB_ORDER):
        n = sum(1 for k in wh[fn] if _is_markup(k))
        if n:
            L.append("| `static/js/%s` | %d |" % (fn, n))
    return L


def _section_html(hk, web_dict):
    L = ["", "## 三、网页静态 HTML：data-i18n 键缺译", "", "| key | 状态 |", "|---|---|"]
    for k in sorted(hk):
        L.append("| `%s` | %s |" % (k.replace("|", "｜"),
                                    "✅ 已有译文" if k in web_dict else "＋ 缺译"))
    return L


def _section_fake(missing_web):
    L = ["", "## 四、网页：已用 t() 但语言包查不到（假覆盖）"]
    for lang in sorted(missing_web):
        miss = sorted(missing_web[lang])
        tail = ("（前 30 条：%s）" % "；".join(miss[:30])) if miss else ""
        L += ["", "- `%s`：%d 条未译%s" % (lang, len(miss), tail)]
    return L


def _section_app(ah, app_dict):
    L = ["", "## 五、APP：还没走 AppI18n.s() 的文案"]
    for fn in _order(ah, APP_ORDER):
        items = ah[fn]
        have = sum(1 for k in items if k in app_dict)
        L += ["", "### `%s`（%d 条，其中 %d 条字典已有）" % (fn, len(items), have), ""]
        for k in sorted(items, key=lambda x: items[x]):
            mark = "✅" if k in app_dict else "＋"
            L.append("- L%d %s `%s`" % (items[k], mark, k.replace("`", "'")))
    return L


def _section_app_fake(missing_app):
    L = ["", "## 六、APP：已用 s() 但英文包查不到（守卫会拦）"]
    for lang in sorted(missing_app):
        miss = sorted(missing_app[lang])
        if miss:
            L += ["", "- `%s`：%d 条未译（%s）" % (lang, len(miss), "；".join(miss[:30]))]
    return L


def _section_batches():
    return [
        "", "## 七、建议分批", "",
        "1. **已做**：主题/图库/返回/别名页新增界面（3.6.123~3.6.126 已配齐 7 语）。",
        "0. **结构**：每个语言包 3.6.135 起分 2 片（`i18n_lang_<x>.js` + `i18n_lang_<x>_2.js`，纯搬移）——",
        "   两批各加 56/92 条后每包到 446 行（上限 400）；新条目往后加在**末片**，满了再加 `_3`。",
        "2. **已做**：「假覆盖」清零——3.6.132 模板化把 40 降到 4，3.6.133 收掉最后 5 条 prompt 段落，现为 0；",
        "   守卫 `test_no_wired_web_key_missing_from_any_pack` 盯着不许回潮。",
        "   口径修订（3.6.135）：报表原先只认「含汉字」的字面量，`（%1）` 这类**纯标点 + 占位符**的 key",
        "   因此对覆盖守卫隐身；现改为「含汉字**或**含 %1..%9」（`KEY_TEXT`）。",
        "3. **已做 · 第二批**：一级界面的按钮与空态（约 150 条）。",
        "   - 网页已做（一级界面全部接线完成）：`home.js`（首页社团墙 / 画师与分区）与 `search.js`（搜索 / 续读 / 喜爱）"
        "——3.6.134；",
        "     `detail.js`（社团页 / 增补信息表单）与 `tag.js`（标签页 / 画师档案 / 作品卡片）——3.6.135；",
        "     `inbox.js`（收件箱）——3.6.136。",
        "   - APP 已做（3.7.87）：`FeaturesHome` / `FeaturesHomeFeeds` / `FeaturesHomeRecs` / `FeaturesSearch` /"
        " `ResumeScreen` / `FavoritesScreen` / `ArtistScreen`",
        "     接线 26 key × 7 语（`StringsExtra5.kt`），拼接句一律先拆成 `AppI18n.sf(\"…%1…\")` 模板再译，与网页 `tf()` 同思路。",
        "   - APP 补齐（3.7.87）：3.7.78~3.7.86 只接线、未配译文的 34 条模板句一次补齐（`StringsExtra6.kt`）"
        "——覆盖守卫扩面后照出的存量。",
        "   - APP 守卫已扩面：`tests/test_app_i18n_coverage.py` 从「只查 en 的 s() key」改为"
        "「7 语 × `s()`/`sf()` 全查 + 占位符一致 + 非汉字语不残留汉字 + 包容器必须登记进 `AppI18n.LAYERS`」。",
        "   - 结构：APP 语言包 3.7.87 起按**批次**分文件（`StringsExtra5/6…`，一批一文件装 7 语，可整批回退）；"
        "旧四文件是「一文件两语」的历史存法，不再追加。",
        "4. **第三批**：爬虫/探测/导入/统计页，约 150 条。",
        "5. **末批**：长确认弹窗、API 层错误消息、阅读器操作说明。",
        "",
        "> 标 ✅ 的条目只需把字面量换成 `t('…')` / `AppI18n.s(\"…\")`，无需写译文；",
        "> 标 ＋ 的需要先补 7 语译文再接。接线时注意：中文原文即 key，**改一个字七语全失效**。",
        "",
    ]


def render(stats, data):
    wh, ah, hk, _wp, _ap, missing_web, missing_app, web_dict, app_dict = data
    lines = []
    for part in (_section_header(stats), _section_web(wh, web_dict), _section_markup(wh),
                 _section_html(hk, web_dict), _section_fake(missing_web),
                 _section_app(ah, app_dict), _section_app_fake(missing_app),
                 _section_batches()):
        lines.extend(part)
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="生成双端多语言缺口清单（只读）")
    ap.add_argument("--out", default="", help="输出路径（默认 docs/i18n-gap-<今天>.md）")
    ap.add_argument("--quiet", action="store_true", help="只打印概览，不写文件")
    args = ap.parse_args()
    stats, data = build_report()
    print("网页 JS 未接线 %d 条（纯文案 %d / 内联 HTML 片段 %d；字典已有 %d）" %
          (stats["web_hard"], stats["web_clean"], stats["web_markup"], stats["web_in_dict"]))
    print("APP  Kotlin 未接线 %d 条（字典已有 %d / 需新译 %d）" %
          (stats["app_hard"], stats["app_in_dict"], stats["app_new"]))
    print("HTML data-i18n %d 个 key（缺译 %d）" % (stats["html_keys"], stats["html_missing"]))
    print("已接线 key %d 个，其中 %d 个语言包查不到（假覆盖）" %
          (stats["web_used"], stats["web_used_missing"]))
    if args.quiet:
        return 0
    out = args.out or os.path.join(ROOT, "docs",
                                   "i18n-gap-%s.md" % datetime.date.today().isoformat())
    with open(out, "w", encoding="utf-8") as f:
        f.write(render(stats, data))
    print("已写入 %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
