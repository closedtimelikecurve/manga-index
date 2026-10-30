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
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.CoroutineScope

class AppState(
    val ctx: Context,
    val prefs: android.content.SharedPreferences,
    val scope: kotlinx.coroutines.CoroutineScope
) {
    var serverUrl by mutableStateOf(prefs.getString("url", "") ?: "")
    var token by mutableStateOf(prefs.getString("token", "") ?: "")
    var navStack by mutableStateOf(listOf<Screen>(Screen.Home))
    val screen: Screen get() = navStack.last()
    var showSettings by mutableStateOf(serverUrl.isEmpty())

    // 3.7.56：分区爬取的 APP 级看护（对齐网页 probeWatch）；AppEffects 常驻轮询。
    internal val probeWatch = ProbeWatch()

    var online by mutableStateOf<Boolean?>(null)
    /** 3.7.110 内测模式：所有封面换占位图（服务端 config.safe_covers 的本地镜像）。 */
    var safeCovers by mutableStateOf(Api.safeCovers)
    // 3.7.66 下拉刷新收尾信号：loadHome/loadCircle 每轮必 bump——刷新后数据结构相等时
    // LaunchedEffect(数据) 不会重跑，箭头会永远卡在转圈态，故复位改由完成拍驱动。
    var homeLoadTick by mutableIntStateOf(0)
    val circleLoadTicks = mutableStateMapOf<String, Int>()
    // 注意：属性初始化**早于**下面的 init{} 块，那时 LibraryStore 还没 init，
    // entries() 必然是空表 → 重启后书架一片空白（用户以为作品丢了，得点「找回」）。
    // 所以这里只占位，真正的首次填充在 init{} 里 LibraryStore.init(ctx) 之后。
    var shelfEntries by mutableStateOf(emptyList<LibraryStore.Entry>())
    var shelfUpdateFlags by mutableStateOf<Map<String, Boolean>>(emptyMap())
    var shelfChecking by mutableStateOf(false)

    var inForeground by mutableStateOf(true)

    var homeLib by mutableStateOf<Api.Library?>(null)
    var homeError by mutableStateOf("")
    val homeGrid = LazyGridState()
    val circleWorks = mutableStateMapOf<String, List<Api.Work>>()
    val circleAuthors = mutableStateMapOf<String, List<Api.TagItem>>()
    val circleCovers = mutableStateMapOf<String, Api.CircleCover>()
    val circleErrors = mutableStateMapOf<String, String>()
    val circleGrids = mutableMapOf<String, LazyGridState>()

    val resumeGrid = LazyGridState()
    val favoritesGrid = LazyGridState()
    val shelfGrid = LazyGridState()
    val artistGrids = mutableMapOf<String, LazyGridState>()
    val tagGrids = mutableMapOf<String, LazyGridState>()
    val inboxListState = LazyListState()
    val statsScroll = ScrollState(0)

    var updateInfo by mutableStateOf<Api.AppVersionInfo?>(null)
    var updateMsg by mutableStateOf("")
    var updateChecking by mutableStateOf(false)
    val dismissedVersion = mutableIntStateOf(prefs.getInt("dismissed_version", 0))
    var compatTitle by mutableStateOf("")
    var compatMsg by mutableStateOf("")
    var compatShown by mutableStateOf(false)

    var libRev by mutableIntStateOf(-1)
    var libScannedAt by mutableLongStateOf(0L)

    var delCircle by mutableStateOf<Pair<String, IntRect>?>(null)
    var renameCircleName by mutableStateOf<String?>(null)
    var dissolveCircleName by mutableStateOf<String?>(null)
    var renameInput by mutableStateOf("")
    var delWork by mutableStateOf<Triple<String, String, IntRect>?>(null)
    var delWorkScope by mutableStateOf<String?>(null)
    var delWorkRegion by mutableStateOf<String?>(null)
    var delWorkCompact by mutableStateOf(false)
    var delArtist by mutableStateOf<Pair<String, IntRect>?>(null)
    var artistRenameName by mutableStateOf<String?>(null)
    var origMenu by mutableStateOf<Pair<String, IntRect>?>(null)
    var origRenameName by mutableStateOf<String?>(null)
    var origRenameKeepAlias by mutableStateOf(false)
    var screenReload by mutableIntStateOf(0)
    var askDelCover by mutableStateOf(false)
    var circleReload by mutableStateOf(0)

    var feedTick by mutableIntStateOf(0)
    var feedMode by mutableStateOf(prefs.getString("feed_mode", "circles") ?: "circles")
    var feedSort by mutableStateOf(prefs.getString("feed_sort", "created") ?: "created")
    var feedSortAsc by mutableStateOf(prefs.getBoolean("feed_sort_asc", false))
    var homeArtists by mutableStateOf<List<Api.ArtistItem>?>(null)
    var homeOriginals by mutableStateOf<List<Api.OriginalItem>?>(null)
    // 3.6.151：touched（最近更新）档已删除；3.6.166：size（文件大小）档已删除。
    // 存量偏好一律回落成 updated，否则排序条上没有高亮项、点了也看不出变化。
    var circleSort by mutableStateOf(
        (prefs.getString("circle_sort", "updated") ?: "updated")
            .let { if (it == "touched" || it == "size") "updated" else it })
    var circleSortAsc by mutableStateOf(prefs.getBoolean("circle_sort_asc", false))

    var addOriginalMsg by mutableStateOf("")
    var addOriginalPreview by mutableStateOf<Api.OriginalSearch?>(null)
    var imgCacheMb by mutableStateOf(0f)

    init {
        Api.baseUrl = serverUrl
        Api.token = token
        Api.imgMode = "auto"      // 3.7.81：用户要求删掉图片质量切换，一律走自动（直连原图 / 中继省流）
        LibraryStore.init(ctx)
        // 3.7.63：init 之后立刻把书架快照填上（否则重启后必须手动「找回」才看得到）。
        // 若索引损坏/缺失，init 内部已按 works/ 重建，这里拿到的就是重建后的结果。
        shelfEntries = LibraryStore.entries()
    }

    fun onSettingsSaved(u: String, t: String) {
        prefs.edit().putString("url", u).putString("token", t).apply()
        serverUrl = u; token = t
        Api.baseUrl = u; Api.token = t
        showSettings = false
    }

    fun nav(sc: Screen) { navStack = navStack + sc }

    fun back(): Boolean {
        if (navStack.size > 1) {
            navStack = navStack.dropLast(1)
            if (navStack.size == 1 && navStack.last() is Screen.Home && pendingSearchRestore) {
                pendingSearchRestore = false
                searchOpen = true
            }
            return true
        }
        if (pendingSearchRestore) { pendingSearchRestore = false; searchOpen = true }
        return false
    }

    fun goTab(sc: Screen) {
        if (sc is Screen.Home && pendingSearchRestore) { pendingSearchRestore = false; searchOpen = true }
        navStack = listOf(sc)
    }

    fun appToast(msg: String) {
        android.os.Handler(android.os.Looper.getMainLooper()).post {
            android.widget.Toast.makeText(ctx, msg, android.widget.Toast.LENGTH_SHORT).show()
        }
    }

    /** 3.7.66 探活一次并落盘连接状态；探活循环与手动「重试连接」共用。 */
    suspend fun probeOnce(): Boolean {
        val ok = try { withContext(Dispatchers.IO) { Api.probe() } } catch (_: Exception) { false }
        LibraryStore.Runtime.online = ok
        online = ok
        return ok
    }

    fun retryOnline() {
        scope.launch {
            val ok = probeOnce()
            appToast(if (ok) AppI18n.s("已连接服务器") else AppI18n.s("仍然连不上服务器"))
        }
    }

    /** 3.7.66 静默重连的收尾：把离线期间加载失败的页面数据自动补拉回来（无任何提示）。 */
    fun recoverAfterReconnect() {
        if (homeError.isNotEmpty()) invalidateHome()
        if (circleErrors.isNotEmpty()) { circleErrors.clear(); circleReload++ }
    }

    fun flushPendingReadings() {
        scope.launch(Dispatchers.IO) {
            for (p in LibraryStore.pendingList()) {
                if (LibraryStore.get(p.key) != null) { LibraryStore.removePending(p.key); continue }
                try {
                    Api.postReadingState(p.key, p.page, p.finished)
                    LibraryStore.removePending(p.key)
                } catch (_: Exception) { return@launch }
            }
        }
    }

    fun downloadAll(pairs: List<Pair<String, String>>, label: String) {
        if (pairs.isEmpty()) { appToast(AppI18n.sf("%1 下没有可下载的作品", label)); return }
        val localKeys = LibraryStore.entries().map { it.key }.toSet()
        val queuedKeys = DownloadManager.items
            .filter { it.active || it.state == DlState.DONE }.map { it.key }.toSet()
        var added = 0; var skipped = 0
        for ((g, w) in pairs) {
            if ("$g/$w" in localKeys || "$g/$w" in queuedKeys) { skipped++; continue }
            if (DownloadManager.enqueue(g, w, silent = true)) added++ else skipped++
        }
        appToast(when {
            added > 0 && skipped > 0 -> AppI18n.sf("已加入 %1 部下载，跳过 %2 部（已下载或在队列）", added, skipped)
            added > 0 -> AppI18n.sf("已加入 %1 部下载", added)
            skipped > 0 -> AppI18n.sf("全部 %1 部都已下载或在队列", skipped)
            else -> AppI18n.s("没有可下载的作品")
        } + "——$label")
    }

    fun runShelfCheck() {
        if (shelfChecking || LibraryStore.Runtime.online == false || shelfEntries.isEmpty()) return
        shelfChecking = true
        scope.launch {
            try {
                val (stale, updated) = withContext(Dispatchers.IO) { checkShelfUpdates(shelfEntries) }
                refreshShelf()
                shelfUpdateFlags = updated.associateWith { true }
                appToast(when {
                    stale.isEmpty() && updated.isEmpty() -> AppI18n.s("书架全部为最新")
                    else -> buildString {
                        if (updated.isNotEmpty()) append(AppI18n.sf("%1 部有更新", updated.size))
                        if (stale.isNotEmpty()) {
                            if (updated.isNotEmpty()) append("，")
                            append(AppI18n.sf("%1 部来源已失效", stale.size))
                        }
                    }
                })
            } catch (_: Exception) { }
            finally { shelfChecking = false }
        }
    }

    suspend fun checkCompat() {
        if (compatShown) return
        try {
            val server = withContext(Dispatchers.IO) { Api.serverInfo() }
            compatShown = true
            val (title, text) = when {
                server.minAppApi > APP_API_LEVEL -> AppI18n.s("APP 需要更新") to
                    AppI18n.sf("面板 v%1 要求 APP 接口级 ≥ %2，本机 APP 为 %3。\n请更新 APP 后再使用。", server.panelVersion, server.minAppApi, APP_API_LEVEL)
                server.apiLevel < APP_API_LEVEL -> AppI18n.s("面板版本较旧") to
                    AppI18n.sf("本机 APP 接口级 %1 高于面板 v%2 的 %3。\n建议重启/更新面板，否则部分新功能可能不可用。", APP_API_LEVEL, server.panelVersion, server.apiLevel)
                else -> "" to ""
            }
            if (text.isNotEmpty()) { compatTitle = title; compatMsg = text }
        } catch (_: Exception) { }
    }

    fun loadHome(force: Boolean = false) {        scope.launch {
            homeError = ""
            try {
                homeLib = withContext(Dispatchers.IO) { Api.library(force) }
                try {
                    val m = withContext(Dispatchers.IO) { Api.libraryMeta() }
                    libRev = m.rev; libScannedAt = m.scannedAt
                } catch (_: Exception) { }
                checkUpdate()
            } catch (e: Exception) { homeError = e.message ?: e.toString() }
            homeLoadTick++   // 3.7.66 成功失败都落一拍，HomeScreen 据此收起下拉刷新箭头
        }
    }

    fun invalidateCircle(name: String) { circleReload++ }

    fun invalidateAllCircles() {
        circleWorks.clear(); circleAuthors.clear(); circleErrors.clear(); circleGrids.clear()
        circleReload++
    }

    /** 3.7.71：首页失效改为**后台重拉、旧数据占位**——原 `homeLib = null` 会让首页闪
     *  加载态并销毁滚动位置（与社团页同构的回顶源）。loadHome 完成后原地替换。 */
    fun invalidateHome() { loadHome() }

    fun onFeedSort(m: String, asc: Boolean) {
        feedSort = m; feedSortAsc = asc
        prefs.edit().putString("feed_sort", m).putBoolean("feed_sort_asc", asc).apply()
    }

    fun invalidateRegions() {
        loadHome()      // 3.7.71：不再置 homeLib = null（旧数据占位，滚动不丢）
        scope.launch {
            homeArtists = try { withContext(Dispatchers.IO) { Api.artists() } } catch (_: Exception) { homeArtists }
            homeOriginals = try { withContext(Dispatchers.IO) { Api.originals() } } catch (_: Exception) { homeOriginals }
        }
    }

    /** 3.7.52：按当前信息流模式拉取「全部画师 / 原作分区」的数据源。
     *
     * 3.7.50 把 MainActivity 拆成六片时，原来那段 `LaunchedEffect(feedMode, feedTick)`
     * （切到分区就拉一次、点「重试」再拉一次）**没有被搬过来**——函数和数据字段都在，
     * 但没有任何调用点，于是两个分区永远停在「加载中…」（重试也只会让 feedTick 自增，
     * 而 feedTick 已无人消费）。这里把"谁来拉"收回状态层，由 AppScreenHome 的
     * LaunchedEffect 驱动；失败保持 null（= 加载中 + 点此重试），与 3.3.2 的约定一致。 */
    fun loadFeedRegion() {
        val mode = feedMode
        if (mode != "artists" && mode != "originals") return
        scope.launch {
            if (mode == "artists") {
                homeArtists = try { withContext(Dispatchers.IO) { Api.artists() } } catch (_: Exception) { null }
            } else {
                homeOriginals = try { withContext(Dispatchers.IO) { Api.originals() } } catch (_: Exception) { null }
            }
        }
    }

    suspend fun refreshAfterStructureChange() {
        try { withContext(Dispatchers.IO) { Api.library(refresh = true) } } catch (_: Exception) { }
        invalidateRegions(); invalidateAllCircles(); screenReload++
    }

    fun toggleFavorite(author: String, loved: Boolean) {
        scope.launch {
            try {
                val msg = withContext(Dispatchers.IO) {
                    if (loved) Api.follow(author) else Api.unfollow(author)
                }
                appToast(msg)
                homeArtists = homeArtists?.map { if (it.name == author) it.copy(followed = loved) else it }
            } catch (e: Exception) { appToast(AppI18n.sf("失败：%1", e.message ?: "")) }
        }
    }

    fun cycleFeed() {
        feedMode = when (feedMode) {
            "circles" -> "artists"; "artists" -> "originals"; else -> "circles"
        }
        prefs.edit().putString("feed_mode", feedMode).apply()
    }

    suspend fun syncFromServer() {
        try {
            val m = withContext(Dispatchers.IO) { Api.libraryMeta() }
            if (libRev < 0) { libRev = m.rev; libScannedAt = m.scannedAt; return }
            if (m.rev == libRev) {
                // 3.7.69：rev 相同 = 内容没变，只吸收 scanned_at 后返回。
                // 纯重扫完成只推进 scanned_at（_kick_rescan 不动 rev），此前被误判为
                // "远端变更"→ 清空 circleWorks/circleGrids → 退出阅读器回顶的自激闭环
                // （reloadKey>0 → refresh=1 → 重扫 → scanned_at 变 → 清空 → reload++ → …）。
                libScannedAt = m.scannedAt
                return
            }
            if (m.scanning) return
            libRev = m.rev; libScannedAt = m.scannedAt
            Api.clearVerCache()
            // 3.7.71：内容真变了也**不清空社团容器**——works 被清会让页面闪加载态、
            // grids 被清直接销毁滚动位置（在社团页内部删首图/设封面 → 当场回顶，用户实测）。
            // 改走 reload 标记：各社团页 onLoad(true) 保留旧数据占位、force 重载后原地
            // 替换（gridState 不动），滚动不丢；circleErrors 清掉让失败页重试。
            circleErrors.clear()
            circleReload++
            invalidateHome()
        } catch (_: Exception) { }
    }

    fun loadCircle(name: String, force: Boolean) {
        if (force || circleWorks[name] == null) {
            scope.launch {
                circleErrors[name] = ""
                try {
                    val (works, authors, cover) = withContext(Dispatchers.IO) { Api.circle(name, force) }
                circleWorks[name] = works; circleAuthors[name] = authors; circleCovers[name] = cover
            } catch (e: Exception) { circleErrors[name] = e.message ?: e.toString() }
            circleLoadTicks[name] = (circleLoadTicks[name] ?: 0) + 1   // 3.7.66 完成拍，社团页据此收起箭头
        }
        }
    }

    fun setCoverAndReload(sc: String, rg: String, g: String, w: String) {
        delWork = null; delWorkScope = null; delWorkRegion = null
        scope.launch {
            try {
                val msg = withContext(Dispatchers.IO) { Api.setCover(sc, rg, g, w) }
                invalidateCircle(g); invalidateRegions(); screenReload++
                android.widget.Toast.makeText(ctx, msg, android.widget.Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                android.widget.Toast.makeText(ctx, AppI18n.sf("设置失败：%1", e.message), android.widget.Toast.LENGTH_SHORT).show()
            }
        }
    }

    fun deleteWorkAndReload(g: String, w: String) {
        delWork = null; delWorkScope = null; delWorkRegion = null
        scope.launch {
            try {
                val msg = withContext(Dispatchers.IO) { Api.deleteWork(g, w) }
                // 3.7.72：删除是 SWR 异步重扫，refresh=1 拿到的还是旧缓存（被删作品仍在）
                // ——先阻塞重扫（与删首图/网页端对齐），社团页重载才能即时看到删除结果
                try { withContext(Dispatchers.IO) { Api.library(refresh = true) } } catch (_: Exception) { }
                invalidateCircle(g); invalidateHome(); screenReload++
                android.widget.Toast.makeText(ctx, msg, android.widget.Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                android.widget.Toast.makeText(ctx, AppI18n.sf("删除失败：%1", e.message), android.widget.Toast.LENGTH_SHORT).show()
            }
        }
    }

    fun doOriginalRename(oldName: String) {
        val nn = renameInput.trim(); val keep = origRenameKeepAlias
        if (nn.isEmpty() || nn == oldName) { origRenameName = null; return }
        origRenameName = null
        scope.launch {
            try {
                val j = withContext(Dispatchers.IO) { Api.originalsRename(oldName, nn, keep) }
                appToast(j.optString("message", AppI18n.s("已改名")))
                homeOriginals = try { withContext(Dispatchers.IO) { Api.originals() } } catch (_: Exception) { null }
                invalidateHome()
                val to = j.optString("to")
                if (to.isNotBlank() && to != oldName) nav(Screen.TagWorks("original", to))
            } catch (e: Exception) { appToast(AppI18n.sf("改名失败：%1", e.message)) }
        }
    }

    fun doArtistRename(oldName: String) {
        val nn = renameInput.trim()
        if (nn.isEmpty() || nn == oldName) { artistRenameName = null; return }
        artistRenameName = null
        scope.launch {
            try {
                val msg = withContext(Dispatchers.IO) { Api.renameArtist(oldName, nn) }
                android.widget.Toast.makeText(ctx, msg, android.widget.Toast.LENGTH_SHORT).show()
                refreshAfterStructureChange(); goTab(Screen.Home)
            } catch (e: Exception) {
                android.widget.Toast.makeText(ctx, AppI18n.sf("改名失败：%1", e.message), android.widget.Toast.LENGTH_SHORT).show()
            }
        }
    }

    fun previewOriginal(term: String) {
        scope.launch {
            try {
                val p = withContext(Dispatchers.IO) { Api.originalsSearch(term.trim()) }
                addOriginalPreview = p; addOriginalMsg = ""
            } catch (e: Exception) { addOriginalMsg = AppI18n.sf("预览失败：%1", e.message) }
        }
    }

    fun doAddOriginal(term: String) {
        scope.launch {
            try {
                val resp = withContext(Dispatchers.IO) { Api.originalsAdd(term) }
                val canon = resp.optString("canon").ifEmpty { term }
                addOriginalOpen = false
                val msg = if (resp.optBoolean("existed"))
                    AppI18n.sf("同名分区已存在：命中 %1 部，并入「%2」", resp.optInt("hits"), canon)
                else AppI18n.sf("已新建同人分区「%1」：命中 %2 部", canon, resp.optInt("hits"))
                appToast(msg)
                homeOriginals = try { withContext(Dispatchers.IO) { Api.originals() } } catch (_: Exception) { null }
                nav(Screen.TagWorks("original", canon))
            } catch (e: Exception) { addOriginalMsg = AppI18n.sf("添加失败：%1", e.message) }
        }
    }

    fun createEmptyOriginal(term: String) {
        scope.launch {
            try {
                val resp = withContext(Dispatchers.IO) { Api.originalsAdd(term, empty = true) }
                val canon = resp.optString("canon").ifEmpty { term }
                addOriginalOpen = false
                appToast(AppI18n.sf("已创建空分区「%1」（0 部）——进分区后用右上角「＋ 添加」挂作品", canon))
                homeOriginals = try { withContext(Dispatchers.IO) { Api.originals() } } catch (_: Exception) { null }
                nav(Screen.TagWorks("original", canon))
            } catch (e: Exception) { addOriginalMsg = AppI18n.sf("创建失败：%1", e.message) }
        }
    }

    fun doDeleteCover(g: String, w: String) {
        scope.launch {
            try {
                val msg = withContext(Dispatchers.IO) { Api.deleteCover(g, w) }
                try { withContext(Dispatchers.IO) { Api.library(refresh = true) } } catch (_: Exception) { }
                try { withContext(Dispatchers.IO) { Api.circle(g) } } catch (_: Exception) { }
                invalidateCircle(g); invalidateRegions(); screenReload++
                android.widget.Toast.makeText(ctx, msg, android.widget.Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                android.widget.Toast.makeText(ctx, AppI18n.sf("删除失败：%1", e.message), android.widget.Toast.LENGTH_SHORT).show()
            }
        }
    }

    fun doUpdate(v: Api.AppVersionInfo) {
        updateInfo = null; updateMsg = AppI18n.s("下载中…")
        scope.launch {
            try {
                val apk = java.io.File(ctx.cacheDir, "update.apk")
                withContext(Dispatchers.IO) { Api.downloadTo(v.apkUrl, apk) }
                updateMsg = ""
                val uri = androidx.core.content.FileProvider.getUriForFile(ctx, ctx.packageName + ".fileprovider", apk)
                val intent = android.content.Intent(android.content.Intent.ACTION_VIEW)
                    .setDataAndType(uri, "application/vnd.android.package-archive")
                    .addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION or android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
                ctx.startActivity(intent)
            } catch (e: Exception) {
                updateMsg = ""; android.widget.Toast.makeText(ctx, AppI18n.sf("更新失败：%1", e.message), android.widget.Toast.LENGTH_SHORT).show()
            }
        }
    }

    fun imageCacheMb(): Float = ImageCache.sizeMb(ctx)

    /**
     * 清理图片缓存（封面 / 页面缩略图），**绝不动本地书架**（护栏在 ImageCache.clear）。
     * 清理前由抽屉弹窗确认，结束后回显释放体积与书架部数。
     */
    fun clearImageCache(drawerCtx: Context) {
        kotlinx.coroutines.CoroutineScope(Dispatchers.IO).launch {
            val freed = ImageCache.clear(drawerCtx)
            val shelf = runCatching { LibraryStore.entries().size }.getOrDefault(0)
            withContext(Dispatchers.Main) {
                imgCacheMb = ImageCache.sizeMb(drawerCtx)
                android.widget.Toast.makeText(drawerCtx,
                    AppI18n.sf("已清除图片缓存 %1 MB（书架 %2 部作品未受影响）", String.format("%.0f", freed / 1048576f), shelf),
                    android.widget.Toast.LENGTH_SHORT).show()
            }
        }
    }

}
