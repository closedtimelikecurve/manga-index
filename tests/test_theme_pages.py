# -*- coding: utf-8 -*-
"""网页端「语言 / 主题二级界面 + 主题图库」守卫（面板 3.6.116）。

用户要求：语言、主题两个新模块不再挤在抽屉里，各自独立成一个二级界面（`#/lang`、`#/theme`）；
主题背景图要有**本机图库**（图存服务端 `_state/theme_gallery/`，可浏览 / 选用 / 添加 / 删除）。

另一条是修 bug 立下的守卫：`color-mix(in srgb, --accent 40%, transparent)` 里的 `--accent`
**不是合法颜色**（必须写 `var(--accent)`），整条声明会被浏览器丢弃——主题色衍生出来的
边框/底色全部不生效，换主题时"看起来只换了一半"。style.css 一次扫出 28 处。

纯文本/结构断言，不需要浏览器，也不碰真实文库。
"""
import os
import re

PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(PROG_DIR, "static", "js")


def _read(*parts):
    with open(os.path.join(PROG_DIR, *parts), "r", encoding="utf-8") as f:
        return f.read()


def _js(name):
    with open(os.path.join(JS_DIR, name + ".js"), "r", encoding="utf-8") as f:
        return f.read()


def test_web_color_mix_uses_var():
    """裸 `--accent` 进 color-mix 是无效值 → 整条声明被丢弃，主题色的衍生边框/底色全不生效。"""
    css = _read("static", "style.css")
    bad = re.findall(r"color-mix\(in srgb,\s*--", css)
    assert not bad, \
        "style.css 里又有裸自定义属性进了 color-mix（无效声明会被整条丢弃）：%d 处" % len(bad)
    assert "color-mix(in srgb, var(--accent)" in css, "主题色衍生色不见了"


def test_web_drawer_has_entries_not_inline_blocks():
    html = _read("static", "index.html")
    assert 'id="btnLang"' in html and 'id="btnTheme"' in html, "抽屉里没有语言/主题入口"
    for dead in ('id="langList"', 'id="themeBlock"', 'class="drawer-sec"'):
        assert dead not in html, "抽屉里又内嵌了 %s（应改为二级界面）" % dead
    drawer = _js("drawer")
    assert "location.hash = '#/lang'" in drawer and "location.hash = '#/theme'" in drawer, \
        "抽屉入口没有指向两个二级界面"
    assert "drawerRenderLangs" not in drawer, "抽屉里的语言区块渲染又回来了"


def test_web_router_routes_lang_and_theme():
    router = _js("router")
    assert "startsWith('#/lang')" in router and "renderLangView()" in router, \
        "router.js 没有 #/lang 路由"
    assert "startsWith('#/theme')" in router and "renderThemeView()" in router, \
        "router.js 没有 #/theme 路由"
    assert "function renderLangView" in _js("i18n"), "i18n.js 缺少语言二级界面"
    assert "function renderThemeView" in _js("theme"), "theme.js 缺少主题二级界面"


def test_web_theme_page_hits_gallery_api():
    theme = _js("theme")
    assert "/api/theme/gallery?client=" in theme, "网页读图库列表时没带本端槽位（会读到 APP 的选择）"
    assert "method: 'DELETE'" in theme, "网页主题页不能删除图库图片"
    assert "themeCellHtml" in theme and "theme-gallery" in theme, "主题页没有图库网格"
    assert "input type=\"color\"" in theme, "网页端自定义色不是取色器"
    css = _read("static", "style.css")
    assert ".theme-gallery" in css and ".lang-row" in css, "二级界面的样式缺失"
    # 抽屉内嵌区块的**规则**要随结构一起清掉（注释里提历史不算）
    for dead_rule in (r"(?m)^\.drawer-sec\{", r"(?m)^\.lang-opt\{", r"(?m)^\.drawer-langs,"):
        assert not re.search(dead_rule, css), "抽屉内嵌区块的样式规则还留着：%s" % dead_rule


def test_web_theme_custom_preset_is_the_only_editable_tier():
    """用户要求：主题色里加「自定义」，只有自定义档能调主副色，预设只展示。"""
    theme = _js("theme")
    assert "function themePresetId" in theme, "缺少「当前档」判定（老数据也要能识别成自定义）"
    assert 'data-preset="custom"' in theme and "theme-preset--custom" in theme, "预设区没有「自定义」档"
    assert "themeSwatchRO" in theme, "预设档没有只读色块"
    # 取色器只能出现在自定义分支里：(custom ? themeSwatchInput : themeSwatchRO)
    m = re.search(r"\(custom\s*\n?\s*\?\s*themeSwatchInput", theme)
    assert m, "取色器没有包在「仅自定义档」条件里（预设档仍可改色就违背需求）"
    assert re.search(r":\s*themeSwatchRO", theme), "自定义分支没有配对的只读分支"
    assert "themeSave('custom'" in theme, "手动改色没有归入自定义档"


def test_web_theme_gallery_keeps_client_slot():
    """图库共用一份，但「选用」按端记录：网页所有读写都必须带 client=web。"""
    theme = _js("theme")
    assert "const WEB_CLIENT = 'web'" in theme, "缺少本端槽位常量"
    assert "client=' + WEB_CLIENT" in theme, "背景预览/列表没带本端槽位"
    assert "client: WEB_CLIENT" in theme, "选用请求没有声明本端槽位"
    assert "/api/theme/bg?client=' + WEB_CLIENT, { method: 'DELETE' }" in theme, \
        "恢复默认没有只清本端槽位"
    assert "--bg-image" in theme and "client=' + WEB_CLIENT" in theme, "铺底图没带本端槽位"


def test_web_theme_builtin_images_are_not_deletable():
    """内置图不可删：格子不渲染删除按钮（服务端也会兜底 400）。"""
    theme = _js("theme")
    assert "it.builtin ? ''" in theme, "内置图仍渲染了删除按钮"
    assert "theme-cell-builtin" in theme and "t('内置')" in theme, "内置图没有角标"


def test_web_secondary_pages_return_to_origin():
    """用户报「主题界面内不支持原路返回」：返回键原先一律跳首页，现在要回进入前那一页。"""
    router = _js("router")
    assert "state.themeReturn" in router and "state.langReturn" in router, \
        "router 没有记录进入主题/语言页前的视图"
    assert "state.themeGalleryReturn = '#/theme'" in router, "图库三级页没有固定回主题页"
    menu = _js("menu")
    assert "state.themeGalleryReturn || '#/theme'" in menu, "图库返回没走原路"
    assert "state.themeReturn || '#/'" in menu, "主题返回没走原路"
    assert "state.langReturn || '#/'" in menu, "语言返回没走原路"


def test_web_alias_per_canon_add_and_rename():
    """3.6.127（对齐 APP）：每个正名下方有「＋ 添加别名」胶囊，同人正名可「✏ 改区名」。"""
    alias = _js("alias")
    assert "data-add=" in alias and "alias-plus" in alias, "正名下方没有快捷添加胶囊"
    assert "aliasPage.add === canon" in alias, "点 ＋ 没有就地展开表单"
    assert "/api/originals/rename" in alias and "keep_alias: true" in alias, \
        "同人正名缺少改区名（与 APP 对齐）"
    assert "aliasPage.kind === 'original'" in alias, "改区名没有限定在同人类别"
    assert "alias-add-row" not in alias, "旧的双输入框还在（应改为胶囊入口）"
    css = _read("static", "style.css")
    assert ".alias-plus" in css and ".alias-inline" in css, "别名页新控件没有样式"


def test_web_fullpage_panels_have_no_hard_border():
    """用户报「背景图里一条近乎透明的竖线」：整页面板（主题/语言/别名）的 1px 描边
    压在背景图边缘上就像一条杂线，改为无描边 + 半透明底。"""
    css = _read("static", "style.css")
    assert ".lang-page,.theme-page,.alias-page{" in css, "缺少整页面板去描边的规则"
    rule = css.split(".lang-page,.theme-page,.alias-page{", 1)[1].split("}", 1)[0]
    assert "border:0" in rule, "整页面板仍有描边（会在背景上出现一条线）"


def test_web_header_opaque_and_statusbar_at_bottom():
    """用户需求②④：顶栏不设透明度、与 APP 同色；扫描状态那行小字移到界面最下方。"""
    css = _read("static", "style.css")
    assert "backdrop-filter:blur(10px)" not in css, "顶栏还在用毛玻璃（半透明）"
    assert "background:rgba(8,6,15,.88)" not in css, "顶栏仍是半透明色"
    assert "body{padding-bottom:36px}" in css, "底部状态栏没有给正文留位置"
    assert ".statusbar{position:fixed;left:0;right:0;bottom:0;top:auto" in css, \
        "状态栏没有固定到界面最下方"
    assert "z-index:1900" in css, "弹窗没有压在抽屉（1800）之上"
    html = _read("static", "index.html")
    assert html.index('class="statusbar"') > html.index("<main>"), \
        "状态栏还在顶栏下面（应移到 main 之后）"


def test_web_hero_image_refreshes_after_select():
    """用户需求⑤：横幅是独立 <img>，选完必须手动换 src，否则首页不生效。"""
    theme = _js("theme")
    assert "function themeRefreshHero" in theme, "缺少首页横幅刷新函数"
    assert "themeRefreshHero(); themePaintHero(name)" in theme, "选了横幅后没刷新首页 <img>"
    reset = theme.split("function themeResetHero")[1]
    assert "themeRefreshHero()" in reset, "恢复默认横幅后没刷新首页 <img>"


def test_web_maintenance_dialogs_are_exclusive():
    """用户需求③：维护菜单的两个弹窗会互相叠加，且抽屉不收起（压在弹窗上面）。"""
    panel = _js("panel")
    assert "function closeAllModals" in panel, "缺少浮层统一关闭"
    assert "drawerClose();" in panel, "点维护时抽屉没有自动收起"
    assert "if (blBusy) return;" in panel and "if (bkBusy) return;" in panel, \
        "两个入口没有防连点互斥（会叠出两个弹窗）"

def test_web_black_background_is_really_black():
    """用户需求①：图库要保留「纯黑」选择。它必须真的把背景变黑——
    只换 --bg-image 的话，0.20 的叠层 + body 渐变底看起来毫无变化。"""
    theme = _js("theme")
    assert "THEME_BLACK_ITEM = 'b00_black.jpg'" in theme, "前端没有纯黑条目的名字"
    assert "function themeApplyBlack" in theme, "缺少纯黑切换逻辑"
    assert "classList.toggle('bg-black'" in theme, "纯黑没有落到 body 上"
    css = _read("static", "style.css")
    assert "body.bg-black{background:#000}" in css, "纯黑样式缺失"
    assert "body.bg-black::before{display:none}" in css, "纯黑时背景图层还在（会盖住黑底）"
    # 选用/恢复必须先定 active 再 themeApply，否则纯黑类晚一拍
    select = theme.split("async function themeSelect")[1].split("async function themeDelete")[0]
    assert "themeActiveName = name; themeBumpBg(); themeApply();" in select, \
        "选用后没先同步 active 就应用主题（纯黑不生效）"


def test_web_bg_opacity_slider_is_live():
    """网页同为需求①：滑条拖动即改 --bg-opacity，松手才落盘。"""
    theme = _js("theme")
    assert "function themeBgAlpha" in theme and "function themeSaveBgAlpha" in theme
    assert "--bg-opacity" in theme, "网页没有把不透明度落到 CSS 变量"
    assert "addEventListener('input'" in theme, "拖动时没有实时预览"
    assert "th.preset = preset" in theme, "themeSave 仍是整体覆盖（换色会把不透明度抹掉）"
    css = _read("static", "style.css")
    assert "opacity:var(--bg-opacity" in css, "背景层没读 --bg-opacity"
    assert ".theme-alpha" in css, "滑条没有样式"
