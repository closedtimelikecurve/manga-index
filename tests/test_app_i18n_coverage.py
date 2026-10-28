# -*- coding: utf-8 -*-
"""APP 多语言覆盖守卫（3.7.87 扩面）。

3.7.77 立的原守卫只校验一件事：`AppI18n.s("…")` 的 key 在 **en** 包里查得到。
它留下三块盲区，本文件补齐：

1. **模板句**：`AppI18n.sf("…%1…")` 一个都不查——而拼接句恰恰最容易漏译（数值 + 语序），
   翻译时少一个 `%1`，界面上那个数字直接消失且不报错；
2. **只查 en**：其余 6 种语言缺译不会被发现，用户切到日语仍看到中文；
3. **语言包按批分文件**（`Strings/Extra/Extra2…`）：新文件漏登记就整片隐身；
   若漏的是 `AppI18n.LAYERS` 里的名字，译文写进包也永远查不到（与网页 3.6.135 拆片
   `I18N_PACKS['zh_hant']` 是同一类事故）。

口径唯一事实源仍是 `scripts/i18n_gap_report.py`（Kotlin 包解析 `kt_pack_pairs`）。
"""
import glob
import importlib.util
import os
import re

PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KT_DIR = os.path.join(PROG_DIR, "android", "app", "src", "main", "java", "com", "biblioteca", "reader")
LANGS = ("zh-Hant", "en", "ja", "ko", "ru", "th", "vi")
NON_CJK_LANGS = ("en", "ko", "ru", "th", "vi")


def _report():
    path = os.path.join(PROG_DIR, "scripts", "i18n_gap_report.py")
    spec = importlib.util.spec_from_file_location("i18n_gap_report_app", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sources():
    """{文件名: 源码}——除语言包与 AppI18n 本体外的全部 Kotlin 源码。"""
    out = {}
    for path in sorted(glob.glob(os.path.join(KT_DIR, "*.kt"))):
        fn = os.path.basename(path)
        if fn.startswith("Strings") or fn == "AppI18n.kt":
            continue
        with open(path, encoding="utf-8") as f:
            out[fn] = f.read()
    return out


def _packs():
    """{语言: {key: 译文}}：全部语言包文件合并（分片只是存法，不是语义）。"""
    mod = _report()
    packs = {}
    for path in sorted(glob.glob(os.path.join(KT_DIR, "Strings*.kt"))):
        for lang, pairs in mod.kt_pack_pairs(path).items():
            packs.setdefault(lang, {}).update(pairs)
    assert packs, "一个语言包都没解析到（解析器坏了）"
    return packs


def _used_keys():
    """已接线的 key：`AppI18n.s(…)` 与模板句 `AppI18n.sf(…)` 的首参。"""
    mod = _report()
    used = set()
    for src in _sources().values():
        used |= mod.call_args(mod.strip_comments(src), ["AppI18n.s", "AppI18n.sf"])
    return {k for k in used if mod.KEY_TEXT.search(k)}


def test_every_wired_app_key_has_all_seven_translations():
    packs = _packs()
    missing = [lang for lang in LANGS if lang not in packs]
    assert not missing, "语言包缺这些语言：%s" % missing
    used = _used_keys()
    assert used, "没有收集到任何 AppI18n.s/sf 调用（收集器坏了）"
    bad = {lang: sorted(k for k in used if k not in packs[lang]) for lang in LANGS}
    bad = {lang: keys for lang, keys in bad.items() if keys}
    assert not bad, "这些 key 已接线但语言包里查不到（切语言会静默回退中文）：%s" % bad


def test_app_pack_placeholders_match_source_key():
    """译文里的 %1..%9 集合必须与简中 key 完全一致（少一个 = 数值消失）。"""
    bad = []
    for lang, pairs in _packs().items():
        for key, val in pairs.items():
            if set(re.findall(r"%[1-9]", key)) != set(re.findall(r"%[1-9]", val)):
                bad.append("%s: %r -> %r" % (lang, key, val))
    assert not bad, "占位符与简中原文不一致：%s" % bad[:10]


def test_non_cjk_app_packs_have_no_han_leftovers():
    """非汉字语言的译文里不许残留汉字——那是"没翻干净"，不是风格问题。

    唯一例外是**文件名/格式字面量** `[無修正]`（后端真的把它写进文件名，见 `panel/naming.py`）。"""
    han = re.compile(r"[\u4e00-\u9fff]")
    packs = _packs()
    bad = []
    for lang in NON_CJK_LANGS:
        for key, val in packs.get(lang, {}).items():
            if han.search(val) and "[無修正]" not in val:
                bad.append("%s: %r -> %r" % (lang, key, val))
    assert not bad, "非汉字语言的译文里残留汉字：%s" % bad[:10]


def test_every_pack_file_is_reachable_from_app_i18n():
    """每个语言包文件里的 `I18N_*` 容器都必须出现在 `AppI18n.LAYERS` 里。

    事故画像：新批次加了 `StringsExtra6.kt`、译文也写全了，却忘了往查找链里登记——
    `s()` 永远走不到那一层，界面回退中文，**没有任何报错**。"""
    names = set()
    for path in sorted(glob.glob(os.path.join(KT_DIR, "Strings*.kt"))):
        with open(path, encoding="utf-8") as f:
            names |= set(re.findall(r"^internal val (I18N_[A-Z0-9_]+)", f.read(), re.M))
    assert names, "语言包里没找到 I18N_* 容器（解析器坏了）"
    with open(os.path.join(KT_DIR, "AppI18n.kt"), encoding="utf-8") as f:
        layers = f.read()
    missing = sorted(n for n in names if n not in layers)
    assert not missing, "这些语言包容器没登记进 AppI18n.LAYERS（译文写了也查不到）：%s" % missing