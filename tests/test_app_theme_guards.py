# -*- coding: utf-8 -*-
"""APP 端「抽屉黑字 / 语言·主题二级界面 / 取色器 / 图库」守卫（3.7.74）。

用户报障四条，本文件守 APP 侧可判定部分：

1. **抽屉里功能键不显示字（"还是黑底黑字"）**——两条独立根因：
   ① 3.7.73 选预设/自定义色走 `Color(hex.toLong(16).toInt())`，6 位值的 alpha 段是 0
      → ACCENT/ACCENT2 变**全透明**：选中的语言胶囊（字色 = ACCENT）、主题预设圆点
      （底色 = ACCENT2）整排消失，底部胶囊高亮 tab 的深色字压到透明指示条上 = 黑底黑字。
      修法：统一 `parseHexColor()`，6 位值补 `0xFF` alpha。
   ② Compose 的 `LocalContentColor` 默认是**黑**，只有 Surface/Button/Dialog 里的 Text 才
      自动拿前景色；本 App 根容器是自铺深色底的 Box，漏写 color 的 Text（设置页标题等）
      就是黑字。修法：根壳里 `LocalContentColor provides TXT`。

2. **两个新模块不该挤在抽屉里**：语言、主题各自独立成二级界面（`Screen.Lang`/`Screen.Theme`），
   抽屉只留两个入口；原来的抽屉内嵌区块文件 DrawerExtras.kt 已删除（原文件已不存在，
   故此处按纪律 §4.11 用普通文字写历史）。

3. **主题**：不许再手填十六进制（改为可拖动的 HSV 取色器）；背景图来自服务端本机图库
   （`/api/theme/gallery`），可选用 / 从相册添加 / 删除。

纯源码文本断言（Python 侧没有 Kotlin 运行环境），带注释剥离——否则修 bug 时写的说明
（"此前是 Color(hex…)"）会自投罗网。
"""
import glob
import os
import re

PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KT_DIR = os.path.join(PROG_DIR, "android", "app", "src", "main", "java",
                      "com", "biblioteca", "reader")


def _kt(name):
    with open(os.path.join(KT_DIR, name + ".kt"), "r", encoding="utf-8") as f:
        return f.read()


def _strip_comments(src):
    """去注释（引号感知）：`"image/*"` 里的 `/*` 不是注释开头，正则版会把后面半页代码吞掉。"""
    out = []
    i, n, quote = 0, len(src), ""
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


def _kt_code(name):
    return _strip_comments(_kt(name))


def _all_kt_code():
    out = {}
    for path in glob.glob(os.path.join(KT_DIR, "*.kt")):
        with open(path, "r", encoding="utf-8") as f:
            out[os.path.basename(path)] = _strip_comments(f.read())
    return out


# ---------- ① 黑底黑字的两条根因 ----------

def test_app_hex_color_keeps_opaque_alpha():
    """6 位十六进制必须补成不透明：`Color(0xFF3DF2)` 的 alpha 是 0（全透明），
    选完主题色整个 App 的高亮/指示条会集体消失、深色字压在透明底上变成"黑底黑字"。"""
    prefs = _kt("ThemePrefs")
    assert "fun parseHexColor" in prefs, "缺少统一的十六进制解析"
    assert "0xFF000000L or v" in prefs, "解析 6 位色时没有补 0xFF alpha（会得到全透明色）"
    for name, src in _all_kt_code().items():
        assert "Color(v.toLong(16).toInt())" not in src, \
            "%s 又用裸 24 位值构造 Color（alpha=0 → 透明）" % name
        assert "Color(hex.toLong(16).toInt())" not in src, \
            "%s 又用裸 24 位值构造 Color（alpha=0 → 透明）" % name


def test_app_root_provides_content_color():
    """Compose 的 LocalContentColor 默认是黑；根壳不给 TXT，漏写 color 的 Text 就是黑字。"""
    main = _kt("MainActivity")
    assert "fun AppThemeRoot" in main, "根主题壳不见了（深色方案 + 全域前景色）"
    assert "LocalContentColor provides TXT" in main, \
        "根壳没有提供 LocalContentColor = TXT：深底上漏写 color 的文本会变黑字"


def test_app_accent_state_is_single_sourced():
    """主题色必须真的驱动全局 ACCENT/ACCENT2。

    3.7.73 的 ThemePrefs 与 FeaturesCommon 各持一份 mutableStateOf，主题页只写自己那份，
    全局 ACCENT **从未被写过**——选完配色整个 App 纹丝不动（用户："主题功能表现非常不理想"）。
    修法：状态唯一（留在读点最多的 FeaturesCommon），ThemePrefs 只做读写门面。"""
    common = _kt_code("FeaturesCommon")
    assert "internal var ACCENT by mutableStateOf" in common, "全局主色不再是可变状态（切主题不会重组）"
    assert "internal var ACCENT2 by mutableStateOf" in common, "全局副色不再是可变状态"
    prefs = _kt_code("ThemePrefs")
    assert "get() = ACCENT" in prefs and "set(v) { ACCENT = v }" in prefs, \
        "ThemePrefs.accent 不再写穿全局 ACCENT（两份状态各写各的 = 改了没生效）"
    assert "get() = ACCENT2" in prefs and "set(v) { ACCENT2 = v }" in prefs, \
        "ThemePrefs.accent2 不再写穿全局 ACCENT2"


# ---------- ② 语言 / 主题各自独立成二级界面 ----------

def test_app_screens_are_wired():
    shared = _kt("AppShared")
    assert "data object Lang : Screen" in shared and "data object Theme : Screen" in shared, \
        "Screen 里没有 Lang/Theme 两条路由"
    nav = _kt("AppNav")
    assert "Screen.Lang ->" in nav and "LangScreen(" in nav, "AppNav 没有分发语言界面"
    assert "Screen.Theme ->" in nav and "ThemeScreen(" in nav, "AppNav 没有分发主题界面"
    main = _kt("MainActivity")
    assert 'DrawerRow("🌐 " + AppI18n.s("语言"))' in main, "抽屉里没有语言入口"
    assert 'DrawerRow("🎨 " + AppI18n.s("主题"))' in main, "抽屉里没有主题入口"
    for dead in ("DrawerLangBlock", "DrawerThemeBlock", "DrawerExtras"):
        assert dead not in _strip_comments(main), "抽屉又内嵌了 %s（应改为二级界面）" % dead
    assert not os.path.exists(os.path.join(KT_DIR, "DrawerExtras.kt")), \
        "DrawerExtras.kt 应已删除（主题模块已拆成独立界面）"


# ---------- ③ 取色器 + 本机图库 ----------

def test_app_uses_picker_not_manual_hex():
    picker = _kt("ThemePicker")
    assert "fun HsvColorDialog" in picker, "APP 没有取色器（用户：自定义主题色居然是手动输入）"
    assert "detectDragGestures" in picker and "HSVToColor" in picker, \
        "取色器不是可拖动的 HSV 面板"
    for name, src in _all_kt_code().items():
        assert "SmallHexField" not in src, "%s 还留着十六进制手填输入框" % name


def test_app_theme_gallery_hits_server_api():
    api = _kt("ApiTheme")
    assert "/api/theme/gallery" in api, "APP 没有接图库列表/入库端点"
    assert "fun Api.themeBgSelect" in api, "APP 不能从图库里选用（POST /api/theme/bg {name}）"
    assert "fun Api.themeGalleryDelete" in api and "fun Api.themeGalleryAdd" in api, \
        "APP 图库缺少删除/添加"
    assert "ThemeGalleryItem" in api, "图库条目模型不见了"
    gallery = _kt("ThemeGalleryScreen")
    assert "ThemePrefs.gallery" in gallery, "图库页没有渲染图库列表"
    assert "rememberLauncherForActivityResult" in gallery, "图库不能从相册添加图片"
    actions = _kt("ThemeActions")
    assert "fun refresh" in actions and "fun add" in actions, "主题动作层缺少刷新/添加"


# ---------- ④ 3.6.124：二级页的系统返回键 ----------

def test_app_secondary_screens_handle_system_back():
    """用户报「主题界面内不支持原路返回」：主题/语言/图库/下载四个二级页都没注册 BackHandler，
    系统返回键直接 finish Activity（退出 App）。其它二级页都有，属新增页面时的统一遗漏。"""
    for name in ("ThemeScreen", "LangScreen", "ThemeGalleryScreen", "DownloadsScreen"):
        assert "BackHandlerOn(onBack)" in _kt_code(name), \
            "%s 没有处理系统返回键（按返回会直接退出 App）" % name


# ---------- ⑤ 3.7.80：主题「自定义」档 ----------

def test_app_theme_has_custom_tier():
    """用户需求：预设只能展示，只有「自定义」档能调主副色。"""
    prefs = _kt("ThemePrefs")
    assert "internal val THEME_PRESETS" in prefs, "预设表没有收敛到偏好层（界面与档位推断会各一份）"
    assert "var preset by mutableStateOf" in prefs, "没有「当前档」状态"
    assert "fun savePreset" in prefs and "fun inferPreset" in prefs, \
        "缺少档位落盘/存量推断（老用户的色值会被误判成霓虹粉）"
    screen = _kt_code("ThemeScreen")
    assert "ColorRowReadOnly" in screen, "预设档没有只读色行"
    assert "ThemePrefs.preset == CUSTOM_ID" in screen, "没有按档位切换可编辑/只读"
    assert 'PresetDot("自定义"' in screen, "预设区没有「自定义」档"
    assert "ThemeBgSection" not in screen, "主题页还内嵌着旧图库网格（与三级页重复）"
    assert not os.path.exists(os.path.join(KT_DIR, "ThemeGallery.kt")), \
        "ThemeGallery.kt 应已删除（内嵌网格唯一消费方已移除）"


# ---------- ⑥ 3.7.80：图库按端槽位 + 启动同步 ----------

def test_app_theme_slot_is_per_client():
    """图库共用、选用按端：APP 的所有主题读写都必须带 client=app。"""
    api = _kt("ApiTheme")
    assert 'internal const val CLIENT_APP = "app"' in api, "缺少本端槽位常量"
    assert '"/api/theme/gallery?client=" + CLIENT_APP' in api, "列表没带本端槽位"
    assert '"/api/theme/bg?client=" + CLIENT_APP' in api, "恢复默认没带本端槽位"
    assert 'put("client", CLIENT_APP)' in api, "选用请求没有声明本端槽位"
    actions = _kt("ThemeActions")
    assert '"/api/theme/bg?client=" + CLIENT_APP' in actions, "下载背景没带本端槽位"
    assert "fun syncOnStart" in actions, "缺少启动时的静默对齐"
    main = _kt_code("MainActivity")
    assert "ThemeActions.syncOnStart" in main, "启动时没有对齐本端背景（换设备后仍是旧的）"


def test_app_gallery_highlight_and_builtin_guard():
    """三级页的高亮曾经用 remember 初值 → 服务端换图后角标停在旧那张。"""
    gallery = _kt_code("ThemeGalleryScreen")
    assert "mutableStateOf(ThemePrefs.bgName)" not in gallery, \
        "高亮又用了 remember 初值（会过期）"
    assert "ThemePrefs.bgName" in gallery, "高亮没有读实时状态"
    assert "item.builtin" in gallery and 'AppI18n.s("内置")' in gallery, "内置图没有角标"
    assert "if (item.builtin) null else onLongPress" in gallery, "内置图仍可长按删除"


# ---------- ⑦ 3.7.81：背景图真的能看见了 ----------

def test_app_screens_do_not_cover_theme_background():
    """用户报「手机端背景图根本不显示」：根容器画了图，但每个一级界面自己铺了一层
    不透明 `background(BG)`，把图整个盖住。各屏根容器必须留透明。"""
    for name, src in _all_kt_code().items():
        assert "fillMaxSize().background(BG)" not in src, \
            "%s 又给整屏铺了不透明底（会盖住根容器的主题背景图）" % name
        assert "fillMaxSize().background(Color(0xFF08060F))" not in src, \
            "%s 又给整屏铺了不透明底（会盖住根容器的主题背景图）" % name
    bg = _kt_code("ThemeBackground")
    # 3.7.85：不透明度改为主题页滑条实时可调，默认值仍是 0.30（存量观感不变）
    assert "ThemePrefs.bgAlpha" in bg, "背景图没接可调不透明度"
    assert "DEFAULT_BG_ALPHA = 0.30f" in _kt_code("ThemePrefs"), "默认不透明度不是 0.30"


# ---------- ⑧ 3.7.81：扫码走相机 + 删掉图片质量切换 ----------

def test_app_scan_uses_camera():
    """用户报「点扫码只能开相册」→ 主入口必须调相机。

    3.7.83 起进一步改为**实时取景**（用户：拍照再识图不是现代做法），
    所以这里改成"打开取景层"的契约，逐帧识别细节见 tests/test_app_qr_camera.py。"""
    qr = _kt_code("QrConnect")
    assert "QrScanScreen" in qr, "扫码没有打开实时取景层"
    assert "TakePicture" not in qr, "又回到拍照再识图的老路子"
    settings = _kt_code("MainActivity")
    assert "QrConnectRow(" in settings, "设置页没有扫码入口"


def test_app_image_quality_switch_removed():
    """用户要求：去掉图片质量切换，默认走自动。"""
    assert "ImgModeRow" not in _kt_code("FeaturesCommon"), "图片质量切换组件还在"
    settings = _kt_code("MainActivity")
    assert "ImgModeRow" not in settings and "applyImgMode" not in settings, \
        "设置页仍在切换图片质量"
    assert 'Api.imgMode = "auto"' in _kt_code("AppState"), "启动时没有强制走 auto"


# ---------- ⑨ 3.7.82：背景每切一次都要生效 ----------

def test_app_theme_background_refreshes_on_every_change():
    """用户报「背景只能切一次」：换图是覆盖写同一个 theme_bg.img，Coil 默认按路径缓存，
    第二次起命中旧图。必须用 bgVer 拼内存/磁盘缓存键。"""
    bg = _kt_code("ThemeBackground")
    assert "ThemePrefs.bgVer" in bg, "背景组件没读版本键（换图不会重组）"
    assert "memoryCacheKey" in bg and "diskCacheKey" in bg, \
        "没给 Coil 指定版本化缓存键（同路径换图会命中旧缓存）"


def test_app_topbar_is_opaque():
    """用户需求②：顶部功能栏不要透出背景图。"""
    common = _kt_code("FeaturesCommon")
    assert "Row(Modifier.fillMaxWidth().background(CARD_BG)" in common, \
        "TopBar 没有实色底（背景图会从功能栏透出来）"

def test_app_black_background_renders_as_black():
    """用户需求①：图库「纯黑」在 APP 端不能按 0.30 叠层画（那样只是暗一点，不是纯黑）。"""
    bg = _kt_code("ThemeBackground")
    assert 'BLACK_ITEM = "b00_black.jpg"' in bg, "没识别纯黑条目"
    assert "background(Color.Black)" in bg, "纯黑没有铺不透明黑底"
    assert bg.index("ThemePrefs.bgName == BLACK_ITEM") < bg.index("val file ="), \
        "纯黑判定必须在取文件之前（否则会走半透明叠层）"


def test_app_background_opacity_is_adjustable_and_live():
    """需求①：背景不透明度要在主题页用滑条调，拖动即生效（不是保存后才变）。"""
    prefs = _kt_code("ThemePrefs")
    assert "bgAlpha by mutableStateOf(DEFAULT_BG_ALPHA)" in prefs, "不透明度不是 snapshot 状态"
    assert 'putFloat("theme_bg_alpha"' in prefs, "不透明度没有落盘"
    bg = _kt_code("ThemeBackground")
    assert "ThemePrefs.bgAlpha" in bg, "背景渲染没读可调值"
    assert "alpha = 0.30f" not in bg, "背景仍是写死的 0.30"
    screen = _kt_code("ThemeScreen")
    assert "AlphaRow(" in screen and "Slider(" in screen, "主题页没有不透明度滑条"
    assert "ThemePrefs.bgAlpha = it" in screen, "拖动时没有实时写状态（要松手才变）"
    assert "onValueChangeFinished" in screen, "松手没有落盘"


def test_first_level_search_bars_pinned_titles_scroll():
    """需求②（含后续修正）：搜索栏固定在顶部；**标题行进滚动内容**（随内容滚走）。

    此前按"文件里谁先出现"判位置——标题搬进网格后这条断言就没意义了。现在直接守
    结构契约：搜索栏在页头；标题通过 `header = { … }` 作为网格首项传入。
    """
    expect = (("FavoritesScreen", "FavoritesTitle"),
              ("ResumeScreen", "ResumeTitle"),
              ("ShelfScreen", "ShelfTopHeader"))
    for name, title in expect:
        src = _kt_code(name)
        assert "RegionSearchBar(" in src, "%s 没有区域搜索栏" % name
        assert ("{ %s(" % title) in src, "%s 的标题行没作为 header 传给列表" % name
        assert "item(span = { GridItemSpan(maxLineSpan) }) { header() }" in src, \
            "%s 的标题行不是网格首项（不会随内容滚动，仍会常驻）" % name
