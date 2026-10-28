@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class, androidx.compose.foundation.ExperimentalFoundationApi::class)
package com.biblioteca.reader

import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyGridState
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items as lazyRowItems
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.TextButton
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import coil.Coil
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.CoroutineScope

class MainActivity : ComponentActivity() {
    override fun dispatchKeyEvent(event: android.view.KeyEvent): Boolean {
        if (ReaderVolume.active) {
            when (event.keyCode) {
                android.view.KeyEvent.KEYCODE_VOLUME_UP ->
                    if (event.action == android.view.KeyEvent.ACTION_DOWN) {
                        ReaderVolume.onTurn?.invoke(-1); return true
                    } else return true
                android.view.KeyEvent.KEYCODE_VOLUME_DOWN ->
                    if (event.action == android.view.KeyEvent.ACTION_DOWN) {
                        ReaderVolume.onTurn?.invoke(1); return true
                    } else return true
            }
        }
        return super.dispatchKeyEvent(event)
    }

    // 3.6.152：按用户修正，只保留**收回抽屉**这一条横滑（唤起抽屉的手势已删）。
    // 仍然在 Activity 层拿 MotionEvent（Compose 父层抢不过子节点的滚动/嵌套滚动），
    // 但只在抽屉开着（SwipeNav.closeArmed）时跟踪，其余时间直接透传。
    private var swipeDownX = 0f
    private var swipeDownY = 0f
    private var swipeTracking = false

    override fun dispatchTouchEvent(ev: android.view.MotionEvent): Boolean {
        if (!SwipeNav.closeArmed) return super.dispatchTouchEvent(ev)
        val density = resources.displayMetrics.density
        when (ev.actionMasked) {
            android.view.MotionEvent.ACTION_DOWN -> {
                swipeDownX = ev.x
                swipeDownY = ev.y
                swipeTracking = true
            }
            android.view.MotionEvent.ACTION_MOVE -> if (swipeTracking) {
                if (ev.pointerCount > 1) {
                    swipeTracking = false          // 多指（双指缩放等）不参与横滑
                } else {
                    val dx = ev.x - swipeDownX
                    val dy = ev.y - swipeDownY
                    val limit = SwipeNav.THRESHOLD_DP * density
                    // 只认"向右 + 横向占优"：抽屉从右侧滑出，右滑就是把它推回去。
                    // 向左滑不做事——唤起抽屉没有手势入口了。
                    if (dx >= limit && dx > kotlin.math.abs(dy) * 1.5f) {
                        swipeTracking = false
                        // 先给子层发 CANCEL：否则滑完会顺手点到底下那张卡
                        val cancel = android.view.MotionEvent.obtain(ev)
                        cancel.action = android.view.MotionEvent.ACTION_CANCEL
                        super.dispatchTouchEvent(cancel)
                        cancel.recycle()
                        SwipeNav.onSwipeRightClose()
                        return true
                    }
                }
            }
            android.view.MotionEvent.ACTION_UP,
            android.view.MotionEvent.ACTION_CANCEL -> swipeTracking = false
        }
        return super.dispatchTouchEvent(ev)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { AppThemeRoot { App() } }
    }
}

/** 根主题壳（3.7.74 从 onCreate 抽出：加全域 LocalContentColor 后 onCreate 触到 50 行函数预算）。
 *
 *  三件事：① 深色 colorScheme——3.6.27 需求2：此前 MaterialTheme 不带参数 → 落回默认**浅色**
 *  方案，而全 App 配色是深色系（TXT 近白、CARD_BG 近黑），13 个 AlertDialog 因此全是
 *  "浅底 + 近白字"，输入框与说明文字几乎看不见；② 全域 LocalContentColor = TXT——
 *  3.7.74「黑底黑字」根因之一：Compose 的 LocalContentColor 默认是**黑**，只有写在
 *  Surface/Button/Dialog 里的 Text 才自动拿到前景色，本 App 的根容器是自铺深色底的 Box，
 *  于是任何漏写 color 的 Text（设置页标题、若干说明行）在深底上就是黑字，看着像"字没了"；
 *  ③ 自铺深色底 + 主题背景图：Android 16 强制 edge-to-edge，先用 safeDrawingPadding 留白会
 *  露出 Theme.Material 的深灰窗口底色（全局黑区/灰条的元凶），所以只留 顶部状态栏+左右刘海
 *  内边距，底部内容直通屏幕边缘。 */
@Composable
private fun AppThemeRoot(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = ACCENT,
            onPrimary = Color(0xFF1A0A18),
            primaryContainer = Color(0xFF3A1540),
            onPrimaryContainer = Color(0xFFF2EEFA),
            secondaryContainer = Color(0xFF241A3D),
            onSecondaryContainer = Color(0xFFF2EEFA),
            background = Color(0xFF060411),
            onBackground = Color(0xFFF2EEFA),
            surface = Color(0xFF140F22),          // CARD_BG：对话框容器
            onSurface = Color(0xFFF2EEFA),        // TXT
            surfaceVariant = Color(0xFF1C1433),   // CARD_BG2
            onSurfaceVariant = Color(0xFF9A8FB8), // MUTED
            outline = Color(0xFF3A3550),
            outlineVariant = Color(0xFF2A2340),
            error = Color(0xFFFF5ED0),
            onError = Color(0xFF2A0A22),
        )
    ) {
        androidx.compose.runtime.CompositionLocalProvider(
            androidx.compose.material3.LocalContentColor provides TXT
        ) {
            Box(Modifier.fillMaxSize()
                .background(Color(0xFF060411))
                .windowInsetsPadding(
                    WindowInsets.safeDrawing.only(WindowInsetsSides.Top + WindowInsetsSides.Horizontal))
            ) {
                ThemeBackground(LocalContext.current)   // 3.7.74：主题背景图（ThemeBackground.kt）
                // 3.7.21 需求1：撤掉根部 SelectionContainer（3.6.11 的"全 App 文本可选"）——
                // 各区域卡片标题信息不再支持长按复制/长按选择；作品内（阅读器）不动，
                // ReaderScreen 自带 SelectionContainer 维持文本可选。
                content()
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class, androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun App() {
    val ctx = LocalContext.current
    val prefs = remember { ctx.getSharedPreferences("biblioteca", Context.MODE_PRIVATE) }
    val scope = rememberCoroutineScope()
    val s = remember { AppState(ctx, prefs, scope) }
    // 3.7.73：语言与主题偏好（§4.6 双端对齐，对齐网页 i18n/theme）
    AppI18n.load(prefs)
    ThemePrefs.load(prefs)
    if (s.showSettings) {
        SettingsScreen(s.serverUrl, s.token,
            onSaved = { u, t -> s.onSettingsSaved(u, t) },
            onBack = { s.showSettings = false },
            versionLabel = "${s.currentVersionName()}（${s.currentVersionCode()}）",
            onCheckUpdate = { s.checkUpdate(force = true) })
        return
    }
    AppEffects(s)
    AppGestureFrame(s) { AppContent(s) }
    AppDrawer(s)
}

/* ============================================================
 * AppState —— MainActivity.App 的状态持有者 + 全部业务方法。
 * 把原先 1327 行根函数里的 ~60 个 remember 状态与 ~18 个嵌套 fun
 * 收进一个类：对象是 remember 创建的，属性跨重组存活；
 * 类本身不被 quality_gate 计为函数（只数 fun），故可放宽行长。
 * 每个业务方法独立计行/圈复杂度，均需 ≤50 行 / CC ≤15。
 * ============================================================ */

@Composable
fun AppEffects(s: AppState) {
    val ctx = s.ctx
    // 3.7.66 静默重连：探活循环可被「回前台」「网络变化」事件唤醒立即重探，不必干等下一轮
    val probeWake = remember { Channel<Unit>(Channel.CONFLATED) }
    ForegroundWakeEffect(s, ctx, probeWake)
    NetworkWakeEffect(ctx, probeWake)
    LaunchedEffect(probeWake) { probeLoop(s, probeWake) }
    LaunchedEffect(Unit) {
        while (true) {
            if (s.inForeground) s.syncFromServer()
            delay(if (s.inForeground) 3_000 else 1_000)
        }
    }
    // 3.7.64：更新检查不再只挂在"首页加载成功"这一条路上——启动查一次、恢复联网再查一次
    LaunchedEffect(Unit) { s.checkUpdate() }
    LaunchedEffect(s.online) { if (s.online == true) s.checkUpdate() }
    // 3.7.80：启动时静默对齐**本端**背景（换手机/清缓存后仍能拿回选好的那张）。
    // 失败不打扰（离线是常态）；进主题/图库页会显式重试并把失败原因显示出来。
    LaunchedEffect(Unit) { withContext(Dispatchers.IO) { ThemeActions.syncOnStart(ctx) } }
    AppProbeWatchEffect(s)
    s.imgCacheMb = s.imageCacheMb()
    DownloadManager.bind(ctx, s.scope)
    DownloadManager.onShelfChanged = { s.refreshShelf() }
    DownloadManager.toast = { m -> s.appToast(m) }
}

/** 前后台标记（原有逻辑），3.7.66 起回前台时顺带唤醒探活——回来第一眼就能连上。 */
@Composable
private fun ForegroundWakeEffect(s: AppState, ctx: Context, probeWake: Channel<Unit>) {
    DisposableEffect(ctx as? androidx.lifecycle.LifecycleOwner) {
        val owner = ctx as? androidx.lifecycle.LifecycleOwner
        val obs = androidx.lifecycle.LifecycleEventObserver { _, e ->
            s.inForeground = e == androidx.lifecycle.Lifecycle.Event.ON_RESUME
            if (e == androidx.lifecycle.Lifecycle.Event.ON_RESUME) probeWake.trySend(Unit)
        }
        owner?.lifecycle?.addObserver(obs)
        onDispose { owner?.lifecycle?.removeObserver(obs) }
    }
}

/** 3.7.66 默认网络一变（断网恢复/切 Wi-Fi↔流量）立即唤醒探活。
 *  注意 Tailscale 虚拟网卡常驻"可用"，隧道恢复未必触发 onAvailable——离线短轮询仍是兜底。 */
@Composable
private fun NetworkWakeEffect(ctx: Context, probeWake: Channel<Unit>) {
    DisposableEffect(ctx) {
        val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as android.net.ConnectivityManager
        val cb = object : android.net.ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: android.net.Network) { probeWake.trySend(Unit) }
            override fun onLost(network: android.net.Network) { probeWake.trySend(Unit) }
        }
        cm.registerDefaultNetworkCallback(cb)
        onDispose { cm.unregisterNetworkCallback(cb) }
    }
}

/** 探活主循环。3.7.66：离线重探 6s→3s；固定 delay 改为可被 probeWake 打断的等待；
 *  从离线恢复在线的那一轮把离线期间加载失败的页面数据补拉回来（静默，无提示）。 */
private suspend fun probeLoop(s: AppState, probeWake: Channel<Unit>) {
    var wasOnline = true
    while (true) {
        var ok = false
        if (s.inForeground) {
            ok = s.probeOnce()
            if (ok) {
                if (!wasOnline) s.recoverAfterReconnect()
                if (!ReadingHub.loaded) ReadingHub.refreshAsync()
                if (LibraryStore.pendingList().isNotEmpty()) s.flushPendingReadings()
            }
            wasOnline = ok
        }
        withTimeoutOrNull(if (!s.inForeground) 1_000 else if (ok) 20_000 else 3_000) {
            probeWake.receive()
        }
    }
}

/** 3.7.56：分区爬取全局看护——运行中 2s、空闲 15s，单飞由 ProbeWatch 内部保证。 */
@Composable
private fun AppProbeWatchEffect(s: AppState) {
    LaunchedEffect(Unit) {
        while (true) {
            if (s.inForeground && s.online != false) s.probeWatch.tick(s)
            delay(if (s.probeWatch.job?.running == true) 2_000 else 15_000)
        }
    }
}

@Composable
fun AppGestureFrame(s: AppState, content: @Composable () -> Unit) {
    // 一级页（四个 tab）：返回手势在这里不退出 App
    val firstLevel = s.screen is Screen.Home || s.screen is Screen.Resume ||
        s.screen is Screen.Favorites || s.screen is Screen.Shelf
    // 3.6.152：只同步"抽屉开着时右滑收回"这一条（唤起抽屉的手势已删，不再有 onSwipeLeft）。
    SideEffect {
        SwipeNav.closeArmed = appDrawerOpen
        SwipeNav.onSwipeRightClose = { appDrawerOpen = false }
    }
    // 返回手势/返回键按方向分流：右边缘开抽屉，左边缘只返回、一级页不退出
    BackSwipeBridge(s, firstLevel && !appDrawerOpen && s.navStack.size <= 1)
    Box(Modifier.fillMaxSize()) { content() }
}

@Composable
fun AppContent(s: AppState) {
    Box(Modifier.fillMaxSize()) {
        AppScreenHost(s)
        AppProbeTicker(s)          // 3.7.56：任何页面右下角都能看到分区爬取进度
    }
    AppBottomCapsule(s)
    AppCircleMenu(s)
    AppRenameCircleDialog(s)
    AppDissolveDialog(s)
    AppArtistMenu(s)
    AppOriginalMenu(s)
    AppOriginalRenameDialog(s)
    AppArtistRenameDialog(s)
    AppWorkMenu(s)
    AppAddOriginalDialog(s)
    AppRemoveOriginalDialog(s)
    AppDelCoverDialog(s)
    AppDownloadBanner(s)
    AppCompatDialog(s)
    AppUpdateDialog(s)
}

@Composable
private fun AppDrawer(s: AppState) {
    Box(Modifier.fillMaxSize()) {
        BackHandler(enabled = appDrawerOpen) { appDrawerOpen = false }
        AnimatedVisibility(appDrawerOpen, enter = fadeIn(), exit = fadeOut()) {
            Box(Modifier.fillMaxSize().background(Color(0x8C000000))
                .clickable(interactionSource = remember { MutableInteractionSource() },
                    indication = null) { appDrawerOpen = false })
        }
        AnimatedVisibility(visible = appDrawerOpen, enter = slideInHorizontally(initialOffsetX = { it }),
            exit = slideOutHorizontally(targetOffsetX = { it }), modifier = Modifier.align(Alignment.CenterEnd)) {
            AppDrawerPanel(s)
        }
    }
}

@Composable
private fun AppDrawerPanel(s: AppState) {
    val drawerCtx = LocalContext.current
    // 3.7.59：清缓存前先确认——只清封面缩略图，绝不动本地书架里的作品
    var confirmClear by remember { mutableStateOf(false) }
    // 3.7.74：语言/主题已拆成二级界面，抽屉只剩入口；可滚动保留作窄屏兜底。
    // 3.7.75：根部再提供一次 LocalContentColor=TXT 双保险（DrawerRow 已显式着色，
    // 但任何未来漏写 color 的子组件在深底上不再是黑字）。
    // 3.7.110：抽屉每次展开都拉一次服务端的内测模式状态（抽屉收起时组合被移除，
    // 再次展开会重建 → 这里就重新跑一次）。
    LaunchedEffect(Unit) { s.refreshSafeCovers() }
    Column(Modifier.fillMaxHeight().width(280.dp)
        .background(Color(0xFF140F22))
        .verticalScroll(rememberScrollState())) {
        androidx.compose.runtime.CompositionLocalProvider(
            androidx.compose.material3.LocalContentColor provides Color(0xFFF2EEFA)) {
            Spacer(Modifier.height(20.dp))
            Text("📚 " + AppI18n.s("禁书目录 Index"), color = Color(0xFFF2EEFA), fontSize = 17.sp, modifier = Modifier.padding(horizontal = 20.dp))
            Text(AppI18n.s("个人本地文库"), color = Color(0xFF9A8FB8), fontSize = 11.sp, modifier = Modifier.padding(horizontal = 20.dp, vertical = 5.dp))
            Box(Modifier.fillMaxWidth().height(1.dp).background(Color(0x24FFFFFF)))
            DrawerRow("📥 " + AppI18n.s("导入文件")) { appDrawerOpen = false; s.nav(Screen.Import) }
            DrawerRow("📊 " + AppI18n.s("统计")) { appDrawerOpen = false; s.nav(Screen.Stats) }
            DrawerRow("🕷 " + AppI18n.s("清单下载器")) { appDrawerOpen = false; s.nav(Screen.Crawl) }
            // 3.7.59：新爬虫独立入口（与清单爬虫各跑各的；分区页右上角也是同一个入口）
            DrawerRow("⛏ " + AppI18n.s("搜索下载器")) {
                appDrawerOpen = false; s.nav(Screen.Probe("author", ""))
            }
            DrawerRow("🚫 " + AppI18n.s("词条黑名单")) { appDrawerOpen = false; s.nav(Screen.Blacklist) }
            DrawerRow("🏷 " + AppI18n.s("别名登记")) { appDrawerOpen = false; s.nav(Screen.Aliases) }
            DrawerRow("🧹 " + AppI18n.s("清图片缓存") + "（%.0f MB）".format(s.imgCacheMb)) {
                appDrawerOpen = false; confirmClear = true
            }
            DrawerRow("⚙ " + AppI18n.s("设置")) { appDrawerOpen = false; s.showSettings = true }
            // 3.7.74：🌐 语言 / 🎨 主题 各自独立成二级界面（用户报障：挤在抽屉里既放不下、
            // 手机上也没法用——自定义色只能手填十六进制）。抽屉里只留两个入口。
            Box(Modifier.fillMaxWidth().height(1.dp).background(Color(0x24FFFFFF)))
            DrawerRow("🌐 " + AppI18n.s("语言")) { appDrawerOpen = false; s.nav(Screen.Lang) }
            DrawerRow("🎨 " + AppI18n.s("主题")) { appDrawerOpen = false; s.nav(Screen.Theme) }
            // 3.7.110 内测模式：所有封面换成占位图——把界面截给别人看时不用逐张打码。
            // 状态在服务端 config.json（不是本机 prefs），网页端切过这里也同步。
            DrawerSwitchRow("🛡 " + AppI18n.s("内测模式"), s.safeCovers) { s.toggleSafeCovers(it) }
        }
    }
    if (confirmClear) ClearCacheDialog(
        cacheMb = s.imgCacheMb,
        shelfCount = LibraryStore.entries().size,
        onDismiss = { confirmClear = false },
        onConfirm = { confirmClear = false; s.clearImageCache(drawerCtx) })
}

/** 清缓存确认：把"只清图片缓存、不动书架"说在前面，避免误操作造成恐慌。 */
@Composable
private fun ClearCacheDialog(cacheMb: Float, shelfCount: Int,
                             onDismiss: () -> Unit, onConfirm: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(AppI18n.s("清理图片缓存")) },
        text = {
            Text(AppI18n.sf("将清除封面与页面缩略图缓存（约 %1 MB）。", String.format("%.0f", cacheMb)) +
                AppI18n.sf("本地书架里的 %1 部作品及其文件不受影响；", shelfCount) +
                AppI18n.s("清理后封面需要重新加载一次。"))
        },
        confirmButton = { TextButton(onClick = onConfirm) { Text(AppI18n.s("清理")) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(AppI18n.s("取消")) } })
}

@Composable
fun SettingsScreen(url: String, token: String, onSaved: (String, String) -> Unit,
                   onBack: () -> Unit = {},
                   // 3.7.64：手动检查更新（自动检查可能因为启动时离线而错过）
                   versionLabel: String = "", onCheckUpdate: () -> Unit = {}) {
    val ctx0 = LocalContext.current
    var u by remember { mutableStateOf(url) }
    var t by remember { mutableStateOf(token) }
    // 3.7.81（用户需求⑤）：设置页直接以「扫码连接」为主路径——首次没有地址时才展开手动填写。
    var manual by remember { mutableStateOf(url.isBlank()) }
    var testing by remember { mutableStateOf(false) }
    var msg by remember { mutableStateOf("") }
    val canBack = url.isNotEmpty()   // 首次配置（尚未连接过）不允许返回，否则主界面无法用
    androidx.activity.compose.BackHandler(enabled = canBack) { onBack() }
    Box(Modifier.fillMaxSize()) {
        Image(painter = painterResource(R.drawable.settings_bg), contentDescription = null,
            contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxSize().alpha(0.22f))
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp)) {
            if (canBack) {
                Text("←", color = Color(0xFFF2EEFA), fontSize = 20.sp,
                    modifier = Modifier.clickable { onBack() }.padding(bottom = 14.dp))
            }
            Text(AppI18n.s("禁书目录 · 扫码连接"), color = TXT, fontSize = 20.sp,
                modifier = Modifier.padding(bottom = 6.dp))
            Text(AppI18n.s("电脑面板打开「扫码配对」，用手机扫那张二维码即可完成连接（地址与令牌自动填入）。"),
                color = MUTED, fontSize = 12.sp, lineHeight = 17.sp,
                modifier = Modifier.padding(bottom = 14.dp))
            QrConnectRow(
                onDecoded = { url2, tok2 ->
                    u = url2; t = tok2
                    toast(ctx0, AppI18n.s("已识别并填入，正在连接…"))
                    saveSettings(url2, tok2, { testing = it }, { msg = it }, onSaved)
                },
                onFail = { toast(ctx0, it) })
            Text(if (manual) AppI18n.s("收起手动填写") else AppI18n.s("手动填写服务器地址 / 令牌"),
                color = ACCENT2, fontSize = 12.sp,
                modifier = Modifier.padding(top = 16.dp, bottom = 4.dp)
                    .clickable { manual = !manual })
            if (manual) {
                ManualConnectFields(u, t, { u = it }, { t = it }, testing, msg,
                    onSave = { saveSettings(u.trim(), t.trim(), { testing = it }, { msg = it }, onSaved) })
            } else if (msg.isNotEmpty()) {
                Text(msg, color = if (msg == "OK") ACCENT2 else ERR, fontSize = 12.sp,
                    modifier = Modifier.padding(top = 10.dp))
            }
            ClearIdentityRow(url)
            if (versionLabel.isNotEmpty()) VersionCheckRow(versionLabel, onCheckUpdate)
        }
    }
}

/** 手动填写地址/令牌（3.7.81 从 SettingsScreen 抽出：函数行数预算 50 行）。 */
@Composable
private fun ManualConnectFields(u: String, t: String, onU: (String) -> Unit, onT: (String) -> Unit,
                                testing: Boolean, msg: String, onSave: () -> Unit) {
    OutlinedTextField(u, onU, label = { Text(AppI18n.s("服务器地址")) },
        placeholder = { Text("http://100.x.y.z:8766") },
        modifier = Modifier.fillMaxWidth(), singleLine = true, colors = appFieldColors())
    Spacer(Modifier.height(12.dp))
    OutlinedTextField(t, onT, label = { Text(AppI18n.s("访问令牌（未设置可留空）")) },
        modifier = Modifier.fillMaxWidth(), singleLine = true, colors = appFieldColors())
    Spacer(Modifier.height(12.dp))
    ConnectButton(testing, msg, onSave = onSave)
}

/** 清除服务器身份校验（3.6.146）。
 *
 *  为什么需要这个入口：attest 记的是"上次那台的 secret"，**换服务器后必然对不上**，
 *  不给清除入口就会把用户自己锁死在外面。只在真的有记录时才显示。 */
@Composable
private fun ClearIdentityRow(url: String) {
    val ctx = LocalContext.current
    var has by remember(url) { mutableStateOf(hasServerIdentity(ctx, url)) }
    if (!has) return
    Text("🔓 " + AppI18n.s("清除服务器身份校验"), color = MUTED, fontSize = 12.sp,
        modifier = Modifier.padding(top = 12.dp)
            .clickable {
                clearServerIdentity(ctx, url)
                has = false
                toast(ctx, AppI18n.s("已清除服务器身份校验"))
            }
            .padding(vertical = 4.dp))
}

/** 设置页底部的版本行 + 手动检查更新（3.7.64 抽出：SettingsScreen 行数预算）。 */
@Composable
private fun VersionCheckRow(versionLabel: String, onCheckUpdate: () -> Unit) {
    Spacer(Modifier.height(16.dp))
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(AppI18n.s("当前版本") + " $versionLabel", color = Color(0xFF9A8FB8), fontSize = 12.sp,
            modifier = Modifier.weight(1f))
        Text(AppI18n.s("检查更新"), color = ACCENT2, fontSize = 12.5.sp,
            modifier = Modifier.clip(RoundedCornerShape(999.dp))
                .border(1.dp, ACCENT2, RoundedCornerShape(999.dp))
                .clickable { onCheckUpdate() }
                .padding(horizontal = 12.dp, vertical = 6.dp))
    }
}

/** 保存并连接（3.7.46 抽出原嵌套 save）：校验地址 → 握手 /api/config → 反馈结果。 */
private fun saveSettings(url: String, token: String, onTesting: (Boolean) -> Unit,
                         onMsg: (String) -> Unit, onSaved: (String, String) -> Unit) {
    if (url.isEmpty()) { onMsg(AppI18n.s("请填写服务器地址")); return }
    Api.baseUrl = url; Api.token = token
    onTesting(true); onMsg("")
    kotlinx.coroutines.CoroutineScope(Dispatchers.IO).launch {
        val result = try {
            withContext(Dispatchers.IO) { Api.getJson("/api/config") }
            "OK"
        } catch (e: AuthException) { AppI18n.s("需要令牌：请填写与服务端一致的访问令牌") }
          catch (e: Exception) { AppI18n.sf("连接失败：%1", e.message) }
        onTesting(false)
        onMsg(result)
        if (result == "OK") withContext(Dispatchers.Main) { onSaved(url, token) }
    }
}

/** 连接按钮 + 错误消息行（3.7.77 从 SettingsScreen 抽出：函数行数预算）。 */
@Composable
private fun ConnectButton(testing: Boolean, msg: String, onSave: () -> Unit) {
    Button(onClick = onSave, enabled = !testing, modifier = Modifier.fillMaxWidth()) {
        Text(if (testing) AppI18n.s("连接中…") else AppI18n.s("保存并连接"))
    }
    if (msg.isNotEmpty() && msg != "OK") {
        Text(msg, color = Color(0xFFFF5ED0), fontSize = 13.sp,
            modifier = Modifier.padding(top = 10.dp))
    }
}
