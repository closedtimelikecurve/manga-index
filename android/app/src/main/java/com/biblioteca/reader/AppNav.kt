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

@Composable
internal fun AppScreenHost(s: AppState) {
    val sc = s.screen
    when {
        sc is Screen.Circle -> AppScreenCircle(s, sc.name)
        sc is Screen.Reader -> AppScreenReader(s, sc)
        sc is Screen.Shelf -> AppScreenShelf(s)
        sc is Screen.Downloads -> AppScreenDownloads(s)
        sc is Screen.Info -> AppScreenInfo(s, sc)
        sc is Screen.Home -> AppScreenHome(s)
        sc is Screen.TagWorks -> AppScreenTagWorks(s, sc)
        sc is Screen.Artist -> AppScreenArtist(s, sc)
        sc is Screen.Probe -> ProbeScreen(s, sc.kind, sc.term, sc.site, onBack = { s.back() })
        else -> AppScreenHostMore(s, sc)
    }
}

@Composable
private fun AppScreenHostMore(s: AppState, sc: Screen) {
    when (sc) {
        Screen.Resume -> AppScreenResume(s)
        Screen.Favorites -> AppScreenFavorites(s)
        Screen.Stats -> AppScreenStats(s)
        Screen.Inbox -> AppScreenInbox(s)
        Screen.Import -> AppScreenImport(s)
        Screen.Crawl -> AppScreenCrawl(s)
        Screen.Blacklist -> AppScreenBlacklist(s)
        Screen.Aliases -> AppScreenAliases(s)
        Screen.Lang -> LangScreen(onBack = { s.back() })      // 3.7.74
        Screen.Theme -> ThemeScreen(onBack = { s.back() },
            onOpenGallery = { s.nav(Screen.ThemeGallery) })   // 3.7.74/3.7.76
        Screen.ThemeGallery -> ThemeGalleryScreen(onBack = { s.back() })   // 3.7.76
        else -> {}
    }
}

@Composable
private fun AppScreenCircle(s: AppState, name: String) {
    CircleScreen(name = name, works = s.circleWorks[name], cover = s.circleCovers[name],
        authors = s.circleAuthors[name] ?: emptyList(), error = s.circleErrors[name] ?: "",
        gridState = s.circleGrids.getOrPut(name) { LazyGridState() }, reloadKey = s.circleReload,
        loadTick = s.circleLoadTicks[name] ?: 0,
        onLoad = { force -> s.loadCircle(name, force) },
        onOpen = { s.nav(Screen.Reader(name, it)) }, onBack = { s.back() },
        onOpenArtist = { s.nav(Screen.Artist(it)) },
        onOpenOriginal = { s.nav(Screen.TagWorks("original", it)) },   // 3.7.51
        onProbe = { s.nav(Screen.Probe("circle", name)) },             // 3.7.54
        onLongPressWork = { g, w, anchor -> s.delWorkCompact = false
            s.delWorkScope = "circle"; s.delWorkRegion = name; s.delWork = Triple(g, w, anchor) })
}

@Composable
private fun AppScreenReader(s: AppState, sc: Screen.Reader) {
    val src = remember(sc.group, sc.work, sc.localKey) {
        if (sc.localKey != null) LibraryStore.get(sc.localKey!!)?.let { LocalSource(s.ctx, it) }
        else RemoteSource(sc.group, sc.work)
    }
    if (src != null) {
        ReaderScreen(src, onExit = { ReadingHub.refreshAsync(); s.back() })
    } else {
        LaunchedEffect(Unit) { s.goTab(Screen.Shelf) }
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text(AppI18n.s("本地条目不存在"), color = Color(0xFF9A8FB8), fontSize = 13.sp)
        }
    }
}

@Composable
private fun AppScreenShelf(s: AppState) {
    ShelfScreen(offline = s.online == false, entries = s.shelfEntries, updateFlags = s.shelfUpdateFlags,
        onOpenReader = { e -> s.nav(Screen.Reader(e.group, e.work, localKey = e.key)) },
        onOpenDownloads = { s.nav(Screen.Downloads) },
        onOpenDrawer = { appDrawerOpen = true },
        onRecover = { s.recoverShelf() },          // 3.7.60：从设备找回已下载作品
        onDelete = { e -> LibraryStore.remove(s.ctx, e.key); s.shelfUpdateFlags = s.shelfUpdateFlags - e.key
            s.refreshShelf() },
        onRetryOnline = { s.retryOnline() }, onRefresh = { s.refreshShelf() }, gridState = s.shelfGrid)
}

@Composable
private fun AppScreenDownloads(s: AppState) {
    DownloadsScreen(onBack = { s.back() }, onCheckUpdates = { s.runShelfCheck() }, checking = s.shelfChecking)
}

@Composable
private fun AppScreenInfo(s: AppState, sc: Screen.Info) {
    InfoScreen(sc.group, sc.work, onBack = {
        // 3.7.71：不再置 homeLib = null（旧数据占位，回首页滚动不丢）
        s.invalidateCircle(sc.group); s.loadHome(); s.back()
    })
}

@Composable
private fun AppScreenHome(s: AppState) {
    // 3.7.52：分区信息流的数据源由 feedMode / feedTick 驱动（切入分区拉一次、点重试再拉一次）。
    // 3.7.50 拆分时丢的就是这一条——两个分区因此永久停在「加载中…」。
    LaunchedEffect(s.feedMode, s.feedTick) { s.loadFeedRegion() }
    HomeScreen(lib = s.homeLib, error = s.homeError, feedMode = s.feedMode,
        onCycleFeed = { s.cycleFeed() }, artists = s.homeArtists, originals = s.homeOriginals,
        onToggleFavorite = { a, loved -> s.toggleFavorite(a, loved) },
        onFeedRetry = { s.feedTick++ }, feedSort = s.feedSort, feedSortAsc = s.feedSortAsc,
        onFeedSort = { m, a -> s.onFeedSort(m, a) }, gridState = s.homeGrid,
        sortMode = s.circleSort, sortAsc = s.circleSortAsc,
        onSort = { m, a -> s.circleSort = m; s.circleSortAsc = a
            s.prefs.edit().putString("circle_sort", m).putBoolean("circle_sort_asc", a).apply() },
        onLoad = { force -> s.loadHome(force) }, homeTick = s.homeLoadTick,
        offline = s.online == false,
        onRetryOnline = { s.retryOnline() }, onOpen = { s.nav(Screen.Circle(it)) },
        onOpenReader = { g, w -> s.nav(Screen.Reader(g, w)) }, onSettings = { s.showSettings = true },
        onOpenShelf = { s.goTab(Screen.Shelf) }, onOpenArtist = { s.nav(Screen.Artist(it)) },
        onOpenOriginal = { s.nav(Screen.TagWorks("original", it)) }, onAddOriginal = { addOriginalOpen = true },
        onLongPressOriginal = { name, card -> s.origMenu = name to card },
        onOpenStats = { s.nav(Screen.Stats) }, onOpenInbox = { s.nav(Screen.Inbox) },
        onOpenBlacklist = { s.nav(Screen.Blacklist) }, onOpenMaintenance = { s.nav(Screen.Aliases) },
        onOpenImport = { s.nav(Screen.Import) }, onOpenCrawl = { s.nav(Screen.Crawl) },
        onLongPressCircle = { name, card -> s.delCircle = name to card },
        onLongPressArtist = { name, card -> s.delArtist = name to card },
        onLongPressRecWork = { g, w, anchor -> s.delWorkCompact = true; s.delWorkScope = null
            s.delWorkRegion = null; s.delWork = Triple(g, w, anchor) },
        onLongPressWork = { g, w, anchor -> s.delWorkCompact = false; s.delWorkScope = null
            s.delWorkRegion = null; s.delWork = Triple(g, w, anchor) })
}

/** 分区页的「⛏ 爬取」入口（3.7.54）：画师分区按画师名搜、原作分区按原作名搜，其余类型不显示。 */
private fun probeEntry(s: AppState, sc: Screen.TagWorks): (() -> Unit)? = when (sc.type) {
    "personal" -> ({ s.nav(Screen.Probe("author", sc.tag)) })
    "original" -> ({ s.nav(Screen.Probe("original", sc.tag)) })
    else -> null
}

@Composable
private fun AppScreenTagWorks(s: AppState, sc: Screen.TagWorks) {
    val cover = if (sc.type == "original")
        s.homeOriginals?.find { it.name == sc.tag }?.let {
            Api.CircleCover(it.coverGroup, it.coverWork, it.coverVer) } else null
    TagWorksScreen(type = sc.type, tag = sc.tag, onBack = { s.back() },
        onOpenReader = { g, w -> s.nav(Screen.Reader(g, w)) },
        onOpenArtist = { s.nav(Screen.Artist(it)) },
        onOpenCircle = { s.nav(Screen.Circle(it)) },
        onOpenOriginal = { z -> if (z != sc.tag) s.nav(Screen.TagWorks("original", z)) },
        cover = cover,
        onLongPressWork = { g, w, anchor -> s.delWorkCompact = false
            s.delWorkScope = if (sc.type == "original") "original" else null
            s.delWorkRegion = sc.tag; s.delWork = Triple(g, w, anchor) },
        reloadKey = s.screenReload, gridState = s.tagGrids.getOrPut(sc.type + "/" + sc.tag) { LazyGridState() },
        onProbe = probeEntry(s, sc))                                       // 3.6.152：搬到右上角
}

@Composable
private fun AppScreenArtist(s: AppState, sc: Screen.Artist) {
    ArtistScreen(name = sc.name, onBack = { s.back() },
        onOpenCircle = { s.nav(Screen.Circle(it)) },
        onOpenReader = { g, w -> s.nav(Screen.Reader(g, w)) },
        onOpenArtist = { s.nav(Screen.Artist(it)) },
        onOpenOriginal = { s.nav(Screen.TagWorks("original", it)) },   // 3.7.51
        onProbe = { s.nav(Screen.Probe("author", sc.name)) },          // 3.6.152：搬到右上角
        onLongPressWork = { g, w, anchor -> s.delWorkCompact = false
            s.delWorkScope = "artist"; s.delWorkRegion = sc.name; s.delWork = Triple(g, w, anchor) },
        gridState = s.artistGrids.getOrPut(sc.name) { LazyGridState() }, reloadKey = s.screenReload)
}

@Composable
private fun AppScreenResume(s: AppState) {
    ResumeScreen(onOpenReader = { g, w -> s.nav(Screen.Reader(g, w)) },
        onOpenCircle = { s.nav(Screen.Circle(it)) }, onOpenArtist = { s.nav(Screen.Artist(it)) },
        onOpenOriginal = { s.nav(Screen.TagWorks("original", it)) },   // 3.7.51
        onLongPressWork = { g, w, anchor -> s.delWorkCompact = false
            s.delWorkScope = null; s.delWorkRegion = null; s.delWork = Triple(g, w, anchor) },
        onOpenMenu = { appDrawerOpen = true }, onOpenInbox = { s.nav(Screen.Inbox) },
        gridState = s.resumeGrid, offline = s.online == false, onRetryOnline = { s.retryOnline() },
        reloadKey = s.screenReload)
}

@Composable
private fun AppScreenFavorites(s: AppState) {
    FavoritesScreen(onOpenArtist = { s.nav(Screen.Artist(it)) }, onOpenMenu = { appDrawerOpen = true },
        onOpenInbox = { s.nav(Screen.Inbox) }, offline = s.online == false,
        onRetryOnline = { s.retryOnline() }, gridState = s.favoritesGrid)
}

@Composable
private fun AppScreenStats(s: AppState) {
    StatsScreen(onBack = { s.back() }, onOpenArtist = { s.nav(Screen.Artist(it)) }, scrollState = s.statsScroll)
}

@Composable
private fun AppScreenInbox(s: AppState) {
    InboxScreen(offline = s.online == false, onOpenInfo = { s.nav(Screen.Info("收件箱", it)) },   // i18n:data 收件箱=真实社团名
        onOpenReader = { g, w -> s.nav(Screen.Reader(g, w)) }, onBack = { s.back() },
        listState = s.inboxListState)
}

@Composable
private fun AppScreenImport(s: AppState) {
    ImportScreen(onBack = { s.back() })
}

@Composable
private fun AppScreenCrawl(s: AppState) {
    // 3.7.59：清单爬虫与分区爬虫彻底分开，页内不再出现分区爬虫入口/任务卡
    CrawlScreen(onBack = { s.back() })
}

@Composable
private fun AppScreenBlacklist(s: AppState) {
    BlacklistScreen(onBack = { s.back() }, onSaved = { s.invalidateHome() })
}

@Composable
private fun AppScreenAliases(s: AppState) {
    // 3.7.53：原作正名可改名（= 改原作区名），首页的分区列表必须跟着刷新，
    // 所以走 invalidateRegions（同时刷画师/原作两份分区数据），不只是 invalidateHome。
    AliasScreen(onBack = { s.back() }, onChanged = { s.invalidateRegions(); s.invalidateAllCircles() })
}
