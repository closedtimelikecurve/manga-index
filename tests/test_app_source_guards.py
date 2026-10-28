# -*- coding: utf-8 -*-
"""APP 源码结构守卫（3.7.52）。

这两类事故 CI 看不见、编译器也不报：**"函数、字段都还在，但没有任何调用点"**，
以及 **"UI 上写着省略号，用户永远看不全"**。Kotlin 侧没有单测框架，
所以这里用源码文本做最小断言，防的是"重构把接线弄丢"这一类回归。

事故一：3.7.50 把 MainActivity 拆成六片时，原主 composable 里的
`LaunchedEffect(feedMode, feedTick)`（切到分区就拉一次 / 点重试再拉一次）没被搬走，
`homeArtists` / `homeOriginals` 从此只有"结构变更后 invalidateRegions"这一条路会写，
于是首页「全部画师」「原作分区」永久停在「加载中…」，重试也没用（feedTick 无人消费）。

事故二：3.7.41 的别名树行高/列宽是定值，词条只能单行省略，长笔名与长原作名看不全；
3.7.52 改为纵向全展开，登记入口也从常驻双输入框改为"点正名唤起弹窗"。
"""
import os
import re

PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KT_DIR = os.path.join(PROG_DIR, "android", "app", "src", "main", "java", "com", "biblioteca", "reader")


def _kt(name):
    with open(os.path.join(KT_DIR, name + ".kt"), "r", encoding="utf-8") as f:
        return f.read()


def _fn_body(src, header_re):
    """取函数体（从头到第一个顶格 `}`），够用即可：这些文件里的目标函数都是顶层函数。"""
    m = re.search(header_re + r".*?\n\}", src, re.S)
    assert m, "找不到函数：%s" % header_re
    return m.group(0)


def _strip_comments(src):
    """去掉 Kotlin 注释（含 KDoc 的 `*` 行）：注释里提到 maxLines/省略号是说明，不是用法。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("//"))


def test_feed_regions_are_actually_loaded():
    """分区信息流必须有"谁去拉数据"的调用点，且重试键必须被消费。"""
    state = _kt("AppState")
    assert re.search(r"(?m)^\s*fun loadFeedRegion\s*\(", state), \
        "AppState 少了 loadFeedRegion()——分区信息流没有拉取入口"
    body = _fn_body(state, r"(?m)^\s*fun loadFeedRegion\s*\(\)\s*\{")
    assert "Api.artists()" in body and "Api.originals()" in body, \
        "loadFeedRegion 必须按模式分别拉 /api/artists 与 /api/originals"

    nav = _kt("AppNav")
    assert re.search(r"LaunchedEffect\(\s*s\.feedMode\s*,\s*s\.feedTick\s*\)", nav), \
        "首页没有 LaunchedEffect(feedMode, feedTick) —— 切到画师/原作分区不会去拉数据"
    assert "loadFeedRegion()" in nav, "LaunchedEffect 里没有调用 loadFeedRegion()"
    home = _kt("FeaturesHome")
    assert "onFeedRetry" in home, "首页缺少重试回调，加载失败后无法重试"


def test_alias_tree_shows_full_terms():
    """别名树里的词条必须完整展开：不许单行/多行省略。"""
    raw = _kt("AliasTree")
    assert "AliasTree(" in raw and "onCanonClick" in raw, \
        "别名树缺少点正名回调（3.7.52：点按正名唤起添加别名弹窗）"
    tree = _strip_comments(raw)
    assert "maxLines" not in tree, "别名树仍限制行数——词条会被截断，必须完全展开"
    assert "TextOverflow" not in tree, "别名树仍设置省略号——词条看不全"
    assert "rowH" not in tree, "别名树又用了定值行高——换行后的长词条会被裁掉"


def test_alias_entry_is_a_dialog_not_inline_form():
    """登记入口：点正名/按钮唤起弹窗，不再有常驻的"别名 + 正名"双输入框。"""
    src = _kt("FeaturesAlias")
    assert "AliasEntryRow" not in src, "常驻输入框 AliasEntryRow 应已删除（改为弹窗登记）"
    assert "AlertDialog" in src, "别名登记没有弹窗"
    assert re.search(r"AliasAddDialog\(", src), "找不到登记别名弹窗"
    assert re.search(r"onCanonClick\s*=", src), "别名树没有接上点正名的回调"


def test_original_canon_rename_is_zone_rename():
    """3.7.53：别名栏里"改原作正名"必须等价于"改原作区名"。

    原作名不在文件名里，分区名就是 DB 里的 original 标签——只改别名表的 canon 而不动
    分区，会得到"正名变了、点进去还是旧区/空区"的分裂状态。所以必须走
    `/api/originals/rename`，且固定 keep_alias=true（旧正名自动并入别名，
    否则重扫时旧写法会把旧分区重新长出来）。
    """
    alias = _strip_comments(_kt("FeaturesAlias"))
    assert "Api.originalsRename(" in alias, \
        "原作正名改名没走 /api/originals/rename —— 只会改别名表，分区名不同步"
    assert re.search(r"keepAlias\s*=\s*true", alias), \
        "改名没有强制 keep_alias=true —— 旧正名不会自动并入别名"
    assert 'kind == "original"' in alias, \
        "「改区名」入口没限定在 original（画师/社团改名会搬文件，不能在别名页做）"

    tree = _strip_comments(_kt("AliasTree"))
    assert "canRenameCanon" in tree and "onRename" in tree, \
        "别名树没有接到「改区名」入口"


def test_crawl_domain_runs_two_phase_job_with_covers():
    """3.7.58/3.7.59：清单爬虫的面板逐部显示封面，且与分区爬虫彻底分开。

    * 数据来源是 /api/crawl/job（网页与 APP 同一份快照），封面走同一套代理；
    * 清单爬虫页里**不再出现**分区爬虫的入口/任务卡（两边独立运行）；
    * 作品卡与分区爬虫一致：AsyncImage + Api.probeCoverUrl、单列竖排。
    """
    api = _strip_comments(_kt("ApiCrawl"))
    assert "/api/crawl/job" in api and "fun Api.crawlJob(" in api, "APP 没有拉任务快照——面板只能退回看日志"
    assert "fun Api.crawlRunningKinds(" in api, "APP 没有拉五任务运行状态（胶囊无法变绿）"
    crawl = _strip_comments(_kt("FeaturesCrawl"))
    assert "CrawlMonitorCard(" in crawl, "APP 清单爬虫页没有挂监控面板"
    assert "ProbeCrawlCard" not in crawl and "onProbe" not in crawl, "清单爬虫页又出现了分区爬虫入口/任务卡"
    mon = _strip_comments(_kt("CrawlMonitor"))
    assert "AsyncImage(" in mon and "Api.probeCoverUrl(" in mon, "监控面板没有显示封面（或没走封面代理）"
    assert "CRAWL_JOB_STATES" in mon, "监控面板缺少条目状态文案"


def test_crawl_chips_turn_green_while_running():
    """3.7.59：去掉状态灯面板，改为"运行中的任务胶囊文字变绿"（双端）。"""
    from_kt = _strip_comments(_kt("FeaturesCrawl"))
    assert "runningKinds.contains(k)" in from_kt, "APP 胶囊没有按任务运行状态上色"
    assert "0xFF43C6A8" in from_kt, "APP 胶囊缺少绿色"
    assert "CrawlStatusCard" not in from_kt and "CrawlLogBox" not in from_kt, "状态灯面板/日志面板应已移除"
    state = _strip_comments(_kt("FeaturesCrawlTask"))
    assert "runningKinds" in state, "APP 状态对象没有保存运行中的任务集合"


def test_cache_clear_never_touches_shelf():
    """3.7.59 严重 bug：清缓存绝不能碰本地书架。

    书架在 `getExternalFilesDir(null)/library`，缓存只允许动 `cacheDir/image_cache`。
    另外：元数据损坏时旧代码会把书架索引清空（用户看到"作品全没了"），
    现在必须改为按 works/ 重建。
    """
    cache = _strip_comments(_kt("ImageCache"))
    assert 'd.name == "image_cache"' in cache, "清缓存没有校验目标目录名"
    assert "d.parentFile == cacheRoot" in cache, "清缓存没有校验目标必须是 cacheDir 直接子目录"
    assert "getExternalFilesDir" not in cache and "worksDir" not in cache, "清缓存碰了书架目录"
    store = _strip_comments(_kt("LibraryStore"))
    assert "rebuildFromDiskLocked()" in store, "元数据中心损坏时没有按磁盘重建（书架会被清空）"
    assert "backupBrokenMeta()" in store, "损坏的 library.json 没有留档"


def test_shelf_can_recover_downloads_from_disk():
    """3.7.60：书架索引丢了也要能把作品找回来（否则就是"文件在、永远看不到"）。

    事故链：旧版 library.json 解析失败 → entriesMap.clear()；之后任意一次下载/改动
    会把**空索引**重新落盘 → JSON 变成合法的空书架，catch 分支再也不会触发。
    所以只修"损坏时重建"不够，必须再加两件事：
      ① 索引读成功但为空、磁盘有作品 → 自动按 works/ 重建；
      ② 书架空态给一个「从设备找回」按钮（用户自己点也能触发）。
    """
    store = _strip_comments(_kt("LibraryStore"))
    assert "fun recoverOrphans(" in store, "书架没有从磁盘找回的入口"
    assert "if (entriesMap.isEmpty()) recoverOrphansLocked()" in store, \
        "索引为空时没有自动重建——文件在也永远显示不出来"
    assert "obj.optInt(\"v\") != SCHEMA" in store and "rebuildFromDiskLocked()" in store, \
        "schema 不认识时直接 return 了，书架会空着"
    shelf = _strip_comments(_kt("ShelfScreen"))
    assert "onRecover" in shelf and "从设备找回已下载作品" in shelf, \
        "书架空态没有「从设备找回」按钮"


def test_shelf_can_recover_downloads_from_disk():
    """3.7.60：书架索引丢了也要能把作品找回来（否则就是"文件在、永远看不到"）。

    事故链：旧版 library.json 解析失败 → entriesMap.clear()；之后任意一次下载/改动
    会把**空索引**重新落盘 → JSON 变成合法的空书架，catch 分支再也不会触发。
    所以只修"损坏时重建"不够，必须再加两件事：
      ① 索引读成功但为空、磁盘有作品 → 自动按 works/ 重建；
      ② 书架空态给一个「从设备找回」按钮（用户自己点也能触发）。
    """
    store = _strip_comments(_kt("LibraryStore"))
    assert "fun recoverOrphans(" in store, "书架没有从磁盘找回的入口"
    assert "if (entriesMap.isEmpty()) recoverOrphansLocked()" in store, \
        "索引为空时没有自动重建——文件在也永远显示不出来"
    assert "obj.optInt(\"v\") != SCHEMA" in store and "rebuildFromDiskLocked()" in store, \
        "schema 不认识时直接 return 了，书架会空着"
    shelf = _strip_comments(_kt("ShelfScreen"))
    assert "onRecover" in shelf and "从设备找回已下载作品" in shelf, \
        "书架空态没有「从设备找回」按钮"


def test_shelf_snapshot_is_filled_after_store_init():
    """3.7.63：APP 重启后书架不能是空的（用户报障：必须点「找回」才出现）。

    Kotlin 的属性初始化**早于** `init{}` 块：`var shelfEntries by mutableStateOf(
    LibraryStore.entries())` 会在 LibraryStore.init(ctx) 之前执行，那时索引还没加载，
    拿到的必然是空表；之后没有任何地方再刷新，书架就一直空着（点「找回」才会 refreshShelf）。
    修法：属性只放空表占位，`init{}` 里 init(ctx) 之后立刻重取一次。
    """
    state = _strip_comments(_kt("AppState"))
    assert "var shelfEntries by mutableStateOf(emptyList<LibraryStore.Entry>())" in state, \
        "shelfEntries 又在属性初始化里直接读 LibraryStore.entries() 了（那时还没 init）"
    assert "LibraryStore.init(ctx)" in state
    after = state.split("LibraryStore.init(ctx)", 1)[1]
    assert "shelfEntries = LibraryStore.entries()" in after[:300], \
        "LibraryStore.init 之后没有填充书架快照"


def test_screen_state_is_keyed_by_its_own_identity():
    """3.7.63：跨页复用组合位置时，页面状态必须跟着"是哪一页"重置。

    Compose 会把同一位置的 composable 复用给不同的参数。此前这些页面的数据状态是
    裸 `remember {}`：从画师 A 进 B 再返回 A，会出现"A 的滚动状态 + B 的作品列表"，
    B 的作品少时索引被钳到 0 —— 用户看到"莫名刷新并回到顶部"。
    """
    artist = _strip_comments(_kt("ArtistScreen"))
    assert "var data by remember(name)" in artist, "画师页数据没按画师名键控"
    assert "remember(name) { mutableStateOf(false) }" in artist, "画师页刷新/排序态没按画师名键控"
    works = _strip_comments(_kt("FeaturesWorks"))
    assert "var hits by remember(type, tag)" in works, "分区页列表没按 (type, tag) 键控"
    probe = _strip_comments(_kt("ProbeScreen"))
    assert "remember(kindInit, termInit, siteInit)" in probe, "探针页状态没按入口参数键控"
    reader = _strip_comments(_kt("ReaderScreen"))
    assert "remember(source) { ReaderUiState(prefs) }" in reader, "阅读器 UI 状态没按作品键控"


def test_pull_to_refresh_does_not_double_load():
    """3.7.63：下拉刷新只该拉一次。

    此前 `LaunchedEffect(type, tag, reloadKey, refreshing)` 把 `refreshing` 也当键：
    下拉把它写成 true（触发一次），拉完复位 false（又触发一次），等于每次下拉都多跑
    一趟，列表被换成新对象，滚动位置跟着抖。
    """
    works = _strip_comments(_kt("FeaturesWorks"))
    assert "LaunchedEffect(type, tag, reloadKey, refreshing)" not in works, \
        "refreshing 又进了 LaunchedEffect 的键（一次下拉会拉两次）"
    assert "LaunchedEffect(type, tag, reloadKey)" in works


def test_update_check_runs_on_start_and_on_reconnect():
    """3.7.64：更新检查不能只挂在"首页加载成功"这一条路上。

    用户反馈"没收到更新"：`checkUpdate()` 原先只在 `loadHome()` 成功后调用。启动那次首页
    请求失败（离线 / 扫描中）就再也不会检查，直到重启且首页恰好成功。现在三条路都要有：
    启动、恢复联网、首页加载成功；设置页还要有手动入口（force，无视"暂不更新"，必须给反馈）。
    """
    main = _strip_comments(_kt("MainActivity"))
    assert "LaunchedEffect(Unit) { s.checkUpdate() }" in main, "启动时没有检查更新"
    assert "LaunchedEffect(s.online)" in main and "s.checkUpdate()" in main, "恢复联网时没有重新检查"
    assert 'AppI18n.s("检查更新")' in main, "设置页没有手动检查入口（3.7.76 起 i18n 化）"
    update = _strip_comments(_kt("UpdateActions"))
    assert "fun AppState.checkUpdate(force: Boolean = false)" in update, "checkUpdate 没有手动模式"
    assert "已是最新" in update and "检查更新失败" in update, "手动检查没有给出反馈"
    assert "v.versionCode > cur" in update, "版本比较没有用 versionCode"
