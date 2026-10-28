# -*- coding: utf-8 -*-
"""网页端 3.6.126 新增界面文案的七语覆盖（用户需求①：界面系统文本要能跟着语言走）。

为什么单列一条守卫：网页的 `t('…')` 缺译是**静默回退中文**，没有报错、没有日志，
切到英文界面只会"看起来没翻译"。APP 侧早有 `test_app_i18n_coverage.py`，网页侧此前没有。
"""
import os

PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(PROG_DIR, "static", "js")
LANGS = ("zh_hant", "en", "ja", "ko", "ru", "th", "vi")

# 本轮新增/改动的界面文案（主题自定义档 / 内置图 / 四个入口 tooltip / 环境告警 / 阅读器提示）
NEW_KEYS = (
    "自定义",
    "拖动色块调整主色与副色，选完立即生效",
    "预设配色不可单独调整，选择「自定义」后可微调",
    "内置",
    "主题（配色 / 取色器 / 背景图库）",
    "别名登记（笔名 / 社团 / 同人名归并与改名）",
    "收件箱（爬虫落盘 / 手动放入 _app/_inbox 的待确认作品 + 文库里识别不出词条的作品 + 内容哈希去重）",
    "界面语言（8 种，切换立即生效）",
    "⚠ 未安装 pillow，封面将直接显示原图（pip install pillow 可大幅加快加载）",
    "⚠ 未安装 rarfile/UnRAR，.rar/.cbr 封面不可用（pip install rarfile，并安装 WinRAR 或 unrar）",
    "手机端 App 设置页「扫码连接」扫这张图即可",
    "已经是最后一页",
    "内容为空",
    "先输入词条",
    "根目录已设置",
)


def _pack(lang):
    """该语言**全部**分片的文本（3.6.135 起每个语言包分 `_2` 片，只读第一片会漏条目）。"""
    import glob
    parts = []
    for path in sorted(glob.glob(os.path.join(JS_DIR, "i18n_lang_%s*.js" % lang))):
        with open(path, encoding="utf-8") as f:
            parts.append(f.read())
    assert parts, "找不到语言包分片：%s" % lang
    return "\n".join(parts)


def test_new_ui_keys_exist_in_all_seven_packs():
    for lang in LANGS:
        src = _pack(lang)
        missing = [k for k in NEW_KEYS if ('"%s":' % k) not in src and ("'%s':" % k) not in src]
        assert not missing, "%s 缺这些新键的译文：%s" % (lang, missing)


def test_dom_i18n_covers_title():
    """`data-i18n-title` 必须被扫描——否则抽屉/顶栏的悬浮提示只能写死中文，换语言不变。"""
    with open(os.path.join(JS_DIR, "i18n.js"), encoding="utf-8") as f:
        src = f.read()
    assert "data-i18n-title" in src and "el.title = t(k)" in src, \
        "i18nApplyDom 没有处理 data-i18n-title"
    html = open(os.path.join(PROG_DIR, "static", "index.html"), encoding="utf-8").read()
    for anchor in ("btnPairTop", "btnSettings", "btnLang", "btnTheme", "btnInbox"):
        assert 'id="%s" data-i18n-title=' % anchor in html, \
            "%s 的悬浮提示没标 data-i18n-title（换语言不会变）" % anchor


def test_gap_report_script_runs():
    """缺口清单脚本必须一直能跑（它是后续分批的底账，不是一次性产物）。"""
    import importlib.util
    path = os.path.join(PROG_DIR, "scripts", "i18n_gap_report.py")
    spec = importlib.util.spec_from_file_location("i18n_gap_report", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    stats, _data = mod.build_report()
    # 3.6.143 起网页侧全部接线完成（web_hard=0 是稳态，不许回潮）；
    # 扫描器活性改用必然非零的口径（已接线 key / HTML key）验证。
    assert stats["web_used"] > 0 and stats["html_keys"] > 0, "扫描器没扫到东西（口径坏了）"
    assert stats["web_hard"] == 0, "网页又冒出未接线硬编码文案：%d 条" % stats["web_hard"]
    assert stats["langs_web"] == 7 and stats["langs_app"] == 7, "语言包数量变了，报表口径要同步"


def test_web_error_hints_use_placeholder_templates():
    """3.6.132：错误提示不许再拼中文，统一走 tf('%1失败：%2', t('操作'), msg)。

    中文可以「操作 + 失败 + 原因」顺拼，日语动词在句末、俄语语序也不同，
    逐段拼接必然拧巴——这类文案必须整句翻译。"""
    import glob
    import re

    with open(os.path.join(JS_DIR, "i18n.js"), encoding="utf-8") as f:
        assert "function tf(" in f.read(), "缺少模板翻译 tf()"
    bad = []
    for path in glob.glob(os.path.join(JS_DIR, "*.js")):
        if "i18n_lang_" in path:
            continue
        with open(path, encoding="utf-8") as f:
            if re.search(r"失败：'\s*\+", f.read()):
                bad.append(os.path.basename(path))
    assert not bad, "还在拼接失败提示（应用 tf 模板）：%s" % bad


def test_no_wired_web_key_missing_from_any_pack():
    """3.6.133 起：只要走了 t()/tf()/data-i18n，7 个语言包就必须都能查到。

    缺译是**静默回退中文**——切到英文界面只会"看着没翻译"，不报错、不写日志。
    3.6.132 之前口径里"假覆盖 40 条"就是这么攒出来的；这条守卫让它无法再悄悄回来。
    细则用 scripts/i18n_gap_report.py 的口径（唯一事实源），此处只做断言。"""
    import importlib.util

    path = os.path.join(PROG_DIR, "scripts", "i18n_gap_report.py")
    spec = importlib.util.spec_from_file_location("i18n_gap_report_cov", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _stats, data = mod.build_report()
    missing_web = data[5]                      # {语言: 用到了但语言包里没有的 key}
    bad = {lang: sorted(keys) for lang, keys in missing_web.items() if keys}
    assert not bad, "这些 key 已经接线但语言包查不到（切语言会回退中文）：%s" % bad


def test_pack_shards_assign_the_language_code_i18n_looks_up():
    """语言包分片必须写进 `I18N_PACKS[<t() 查表用的语言码>]`。

    拆片时最容易踩的一脚：分片**文件名**是 `i18n_lang_zh_hant`，而 `t()` 查表用的码是
    `zh-Hant`（`i18n.js` 里的 I18N_LANGS）。名字照文件名写成 `I18N_PACKS['zh_hant']`，
    包是在的、却永远查不到——界面静默回退中文，没有报错、没有日志。
    3.6.135 拆第 2 片时真的踩到了（改键名后才被这条守卫逮住），故立此条。"""
    import glob
    import re

    with open(os.path.join(JS_DIR, "i18n.js"), encoding="utf-8") as f:
        codes = set(re.findall(r"\['([A-Za-z\-]+)',\s*'[^']*'\]", f.read()))
    assert "zh-CN" in codes and "zh-Hant" in codes, "i18n.js 的 I18N_LANGS 解析失败（口径变了）"
    want = codes - {"zh-CN"}                    # 基准语言不需要包
    got = set()
    for path in sorted(glob.glob(os.path.join(JS_DIR, "i18n_lang_*.js"))):
        with open(path, encoding="utf-8") as f:
            got |= set(re.findall(r"I18N_PACKS\['([A-Za-z\-]+)'\]", f.read()))
    assert not (got - codes), "语言包写进了 t() 不认识的语言码：%s" % sorted(got - codes)
    assert got == want, "语言包覆盖的语言与 I18N_LANGS 不一致：缺 %s" % sorted(want - got)


def test_non_cjk_packs_have_no_han_leftovers():
    """非汉字语言（en/ko/ru/th/vi）的译文里不该残留汉字——那是"没翻干净"，不是风格问题。

    唯一例外是**文件名/格式字面量** `[無修正]`（后端真的把它写进文件名，见 panel/naming.py，
    界面上必须原样显示，否则用户对不上号）。3.6.136 全量扫描逮到过一条历史遗漏：
    韩语包的「确认入库」曾译作 `입库 확인`（混进了一个汉字"库"）。"""
    import glob
    import importlib.util
    import re

    path = os.path.join(PROG_DIR, "scripts", "i18n_gap_report.py")
    spec = importlib.util.spec_from_file_location("i18n_gap_report_han", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    han = re.compile(r"[\u4e00-\u9fff]")
    bad = []
    for lang in ("en", "ko", "ru", "th", "vi"):
        for shard in sorted(glob.glob(os.path.join(JS_DIR, "i18n_lang_%s*.js" % lang))):
            for key, val in mod.js_pack_pairs(shard).items():
                if han.search(val) and "[無修正]" not in val:
                    bad.append("%s: %r -> %r" % (os.path.basename(shard), key, val))
    assert not bad, "非汉字语言的译文里残留汉字：%s" % bad[:10]


def test_pack_placeholders_match_source_key():
    """译文里的 %1..%9 集合必须与简中 key 完全一致。

    少一个占位符 = 界面上那个数值直接消失（且没人会报错）；多一个 = 出现裸露的 %2。
    这类错误只有机器盯着才拦得住，故对**全部**语言包条目逐一比对。"""
    import importlib.util
    import re

    path = os.path.join(PROG_DIR, "scripts", "i18n_gap_report.py")
    spec = importlib.util.spec_from_file_location("i18n_gap_report_ph", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    bad = []
    import glob
    for lang in LANGS:
        # 每个语言的全部片（_2 起是分片号，同一语言的条目可能落在任一片里）
        for path in sorted(glob.glob(os.path.join(JS_DIR, "i18n_lang_%s*.js" % lang))):
            for key, val in mod.js_pack_pairs(path).items():
                if set(re.findall(r"%[1-9]", key)) != set(re.findall(r"%[1-9]", val)):
                    bad.append("%s: %r -> %r" % (os.path.basename(path), key, val))
    assert not bad, "占位符与简中原文不一致：%s" % bad[:10]
