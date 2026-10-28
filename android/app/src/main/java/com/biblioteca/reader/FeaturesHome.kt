@file:OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class,
    androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.biblioteca.reader

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyGridState
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

/* 3.7.48：从 MainActivity.kt 搬出（3.7.46）后二次拆分（首页：搜索栏 + 三种信息流 + 每日推荐）。
 * 原函数 607 行 / cc 72；本批按职责拆成 4 个文件（FeaturesHome / Feeds / Search / Recs），
 * 并把每个函数拆到 ≤50 行，以满足 2026-10-20 用户拍板、本批落地的新阈值（单函数 ≤50 行）。
 * 首页搜索态是 MainActivity.kt 的文件级顶层变量（searchOpen / q / sGroups …），同 package 直接引用。 */

/* 3.7.10：功能抽屉已提升到 App() 层（appDrawerOpen 全局开关）：续读/喜爱页的「⋯」与左滑手势都能
 * 唤出同一个抽屉。下方 onOpenImport/onOpenStats/onOpenInbox/onOpenCrawl/onOpenBlacklist/
 * onOpenMaintenance/onSettings 参数位保留仅为兼容，暂无人使用。 */
@Composable
fun HomeScreen(lib: Api.Library?, error: String, gridState: LazyGridState,
               feedMode: String = "circles", onCycleFeed: () -> Unit = {},
               artists: List<Api.ArtistItem>? = null,
               originals: List<Api.OriginalItem>? = null,
               onOpenArtist: (String) -> Unit = {}, onOpenOriginal: (String) -> Unit = {},
               onAddOriginal: () -> Unit = {},
               onLongPressOriginal: (String, IntRect) -> Unit = { _, _ -> },
               onToggleFavorite: (String, Boolean) -> Unit = { _, _ -> },
               onFeedRetry: () -> Unit = {},
               feedSort: String = "created", feedSortAsc: Boolean = false,
               onFeedSort: (String, Boolean) -> Unit = { _, _ -> },
               sortMode: String, sortAsc: Boolean, onSort: (String, Boolean) -> Unit,
               onLoad: (Boolean) -> Unit,
               homeTick: Int = 0,   // 3.7.67 下拉刷新收尾完成拍：loadHome 每轮必 bump
               offline: Boolean = false, onRetryOnline: () -> Unit = {},
               onOpen: (String) -> Unit, onOpenReader: (String, String) -> Unit,
               onSettings: () -> Unit,
               onOpenShelf: () -> Unit = {},
               onOpenStats: () -> Unit = {},
               onOpenInbox: () -> Unit = {},
               onOpenImport: () -> Unit, onOpenCrawl: () -> Unit,
               onOpenBlacklist: () -> Unit,
               onOpenMaintenance: () -> Unit = {},
               onLongPressCircle: (String, IntRect) -> Unit,
               onLongPressArtist: (String, IntRect) -> Unit = { _, _ -> },
               onLongPressRecWork: (String, String, IntRect) -> Unit = { _, _, _ -> },
               onLongPressWork: (String, String, IntRect) -> Unit = { _, _, _ -> }) {
    // 3.7.67：refreshing 收归本域（3.7.66 经包装函数 Boolean 返回、普通局部变量接住——包装函数内
    // 复位只重组包装函数自己，isRefreshing 翻不了、箭头收不起来）；收箭头挂 homeTick 完成拍
    HomeFirstLoad(lib, onLoad); var refreshing by remember { mutableStateOf(false) }
    LaunchedEffect(homeTick) { if (homeTick > 0) refreshing = false }
    HomeSearchEffect()
    BackHandler(enabled = searchOpen) { searchOpen = false; q = "" }
    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize()) {
            HomeSearchBar(onOpenInbox)
            // 3.7.37：离线黄色警告条（替代原「要进入离线模式吗」弹窗）——常驻可感知，不挡手势
            if (offline) { OfflineBanner(onRetry = onRetryOnline); Spacer(Modifier.height(8.dp)) }
            // 下拉刷新：列表顶部下拉触发重新加载
            PullToRefreshBox(isRefreshing = refreshing, onRefresh = { refreshing = true; onLoad(true) },
                modifier = Modifier.fillMaxSize()) {
                HomeBody(lib, error, gridState, feedMode, onCycleFeed, artists, originals,
                    onOpenArtist, onOpenOriginal, onAddOriginal, onLongPressOriginal, onToggleFavorite,
                    onFeedRetry, feedSort, feedSortAsc, onFeedSort, sortMode, sortAsc, onSort,
                    onOpen, onOpenReader, onLongPressCircle, onLongPressArtist, onLongPressRecWork,
                    onLongPressWork, onLoad)
            }
        }
    }
}

/** 首页无缓存首拉（3.7.48 从 HomeScreen 抽出）。3.7.66 前身 rememberHomeRefresh 还经手
 *  refreshing 并以 Boolean 返回——见 HomeScreen 内 3.7.67 注释，refreshing 已收归本域。 */
@Composable
private fun HomeFirstLoad(lib: Api.Library?, onLoad: (Boolean) -> Unit) {
    LaunchedEffect(Unit) { if (lib == null) onLoad(false) }
}

/** 首页内联搜索的防抖拉取（3.7.48：从 HomeScreen 抽出的 LaunchedEffect）。 */
@Composable
private fun HomeSearchEffect() {
    LaunchedEffect(q) {
        if (q.isNotBlank()) {
            delay(300)   // 防抖
            searching = true; searchError = ""
            try {
                val (gs, ws, au) = withContext(Dispatchers.IO) { Api.search(q.trim()) }
                sGroups = gs; sWorks = ws; sAuthors = au
            } catch (e: Exception) { searchError = e.message ?: e.toString() }
            searching = false
        }
    }
}

/** 首页内容分发（3.7.48：从 HomeScreen 抽出的 when 分支）。 */
@Composable
private fun HomeBody(lib: Api.Library?, error: String, gridState: LazyGridState,
                    feedMode: String, onCycleFeed: () -> Unit,
                    artists: List<Api.ArtistItem>?, originals: List<Api.OriginalItem>?,
                    onOpenArtist: (String) -> Unit, onOpenOriginal: (String) -> Unit,
                    onAddOriginal: () -> Unit, onLongPressOriginal: (String, IntRect) -> Unit,
                    onToggleFavorite: (String, Boolean) -> Unit, onFeedRetry: () -> Unit,
                    feedSort: String, feedSortAsc: Boolean, onFeedSort: (String, Boolean) -> Unit,
                    sortMode: String, sortAsc: Boolean, onSort: (String, Boolean) -> Unit,
                    onOpen: (String) -> Unit, onOpenReader: (String, String) -> Unit,
                    onLongPressCircle: (String, IntRect) -> Unit,
                    onLongPressArtist: (String, IntRect) -> Unit,
                    onLongPressRecWork: (String, String, IntRect) -> Unit,
                    onLongPressWork: (String, String, IntRect) -> Unit, onLoad: (Boolean) -> Unit) {
    when {
        // 内联搜索结果：输入非空时直接替换主页内容
        searchOpen && q.isNotBlank() -> HomeSearchResults(onOpen, onOpenArtist, onOpenReader,
            onLongPressCircle, onLongPressArtist, onLongPressWork)
        error.isNotEmpty() -> HomeErrorState(error, onLoad)
        lib == null -> HomeLoadingState()
        lib!!.groups.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text(AppI18n.s("文库为空"), color = Color(0xFF9A8FB8))
        }
        else -> HomeGrid(lib, gridState, feedMode, onCycleFeed, artists, originals, onOpenArtist,
            onOpenOriginal, onAddOriginal, onLongPressOriginal, onToggleFavorite, onFeedRetry,
            feedSort, feedSortAsc, onFeedSort, sortMode, sortAsc, onSort, onOpen, onOpenReader,
            onLongPressCircle, onLongPressRecWork)
    }
}

/** 加载失败态（3.7.48 抽出）。 */
@Composable
private fun HomeErrorState(error: String, onLoad: (Boolean) -> Unit) {
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Column(Modifier.fillMaxWidth().padding(top = 90.dp),
                horizontalAlignment = Alignment.CenterHorizontally) {
                Text(AppI18n.sf("加载失败：%1", error), color = Color(0xFFFF5ED0), fontSize = 13.sp)
                Text("⟳ " + AppI18n.s("重试"), color = Color(0xFF9A8FB8), fontSize = 14.sp,
                    modifier = Modifier.padding(top = 18.dp).clickable { onLoad(true) })
            }
        }
    }
}

/** 文库加载中态（3.7.48 抽出）。 */
@Composable
private fun HomeLoadingState() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator(color = ACCENT)
    }
}

/** 首页主网格：表头推荐 + 三种信息流（3.7.48 从 HomeScreen 抽出）。 */
@Composable
private fun HomeGrid(lib: Api.Library, gridState: LazyGridState, feedMode: String,
                    onCycleFeed: () -> Unit, artists: List<Api.ArtistItem>?,
                    originals: List<Api.OriginalItem>?, onOpenArtist: (String) -> Unit,
                    onOpenOriginal: (String) -> Unit, onAddOriginal: () -> Unit,
                    onLongPressOriginal: (String, IntRect) -> Unit,
                    onToggleFavorite: (String, Boolean) -> Unit, onFeedRetry: () -> Unit,
                    feedSort: String, feedSortAsc: Boolean, onFeedSort: (String, Boolean) -> Unit,
                    sortMode: String, sortAsc: Boolean, onSort: (String, Boolean) -> Unit,
                    onOpen: (String) -> Unit, onOpenReader: (String, String) -> Unit,
                    onLongPressCircle: (String, IntRect) -> Unit,
                    onLongPressRecWork: (String, String, IntRect) -> Unit) {
    // 社团排序：最近入库 / 创建时间 / 作品数量（+ 倒序）——本地排序，切换即时生效
    val shownGroups = Api.sortCircles(lib.groups, sortMode, sortAsc)
    LazyVerticalGrid(
        state = gridState,
        columns = GridCells.Adaptive(110.dp),
        contentPadding = PaddingValues(start = 10.dp, end = 10.dp, top = 10.dp, bottom = 96.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.fillMaxSize()
    ) {
        // 横幅与每日推荐作为表头条目：随内容一起滚出屏幕
        homeRecsSection(lib, feedMode, onOpenReader, onLongPressRecWork, onCycleFeed,
            sortMode, sortAsc, onSort, feedSort, feedSortAsc, onFeedSort)
        // 3.3.0 按信息流模式分流:全部社团 / 全部画师 / 原作分区
        when (feedMode) {
            "artists" -> homeArtistFeed(artists, feedSort, feedSortAsc, onFeedRetry, onOpenArtist, onToggleFavorite)
            "originals" -> homeOriginalFeed(originals, feedSort, feedSortAsc, onFeedRetry, onAddOriginal, onOpenOriginal, onLongPressOriginal)
            else -> homeGroupFeed(shownGroups, onOpen, onLongPressCircle)
        }
    }
}

/** 首页搜索栏（3.7.46 从 HomeScreen 拆出）：折叠态是一颗药丸，点开原地变输入框。
 *  搜索态是 MainActivity.kt 的文件级顶层变量（searchOpen / q），同 package 直接读写。
 *
 *  3.7.83（用户需求①）：本栏曾是主副色 0x33 的横向渐变——那是**半透明**的，
 *  改成实色 CARD_BG 后背景图不会再从功能栏透上来。
 *  3.7.84：但纯实色把"颜色"也一起弄丢了（只剩近黑紫底，用户嫌没以前好看），
 *  因此改用 `barTint()` —— 主副色先压进不透明底色，再画渐变：有颜色、不透明。 */
@Composable
private fun HomeSearchBar(onOpenInbox: () -> Unit) {
    Row(Modifier.fillMaxWidth()
        .background(Brush.horizontalGradient(listOf(barTint(ACCENT), barTint(ACCENT2))))
        .padding(horizontal = 10.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically) {
        // 搜索：点开即在本栏直接输入，不再跳转次级搜索页
        if (!searchOpen) {
            Row(Modifier.weight(1f).clip(RoundedCornerShape(20.dp)).background(CARD_BG2)
                .clickable { searchOpen = true }.padding(horizontal = 14.dp, vertical = 9.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text("🔍", fontSize = 13.sp)
                Text(" " + AppI18n.s("搜索社团 / 作品 / 画师 / 标签"), color = Color(0xFF9A8FB8), fontSize = 13.sp,
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        } else {
            // 输入态保持同一药丸外形，只是原地变为可输入
            val focus = remember { FocusRequester() }
            LaunchedEffect(Unit) { focus.requestFocus() }
            Row(Modifier.weight(1f).clip(RoundedCornerShape(20.dp)).background(CARD_BG2)
                .padding(horizontal = 14.dp, vertical = 9.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text("🔍", fontSize = 13.sp)
                BasicTextField(
                    value = q, onValueChange = { q = it }, singleLine = true,
                    textStyle = TextStyle(color = Color(0xFFF2EEFA), fontSize = 13.sp),
                    cursorBrush = SolidColor(ACCENT),
                    modifier = Modifier.weight(1f).padding(start = 6.dp).focusRequester(focus),
                    decorationBox = { inner ->
                        Box {
                            if (q.isEmpty()) Text(" " + AppI18n.s("搜索社团 / 作品 / 画师 / 标签"),
                                color = Color(0xFF9A8FB8), fontSize = 13.sp,
                                maxLines = 1, overflow = TextOverflow.Ellipsis)
                            inner()
                        }
                    })
                Text("✕", color = Color(0xFF9A8FB8), fontSize = 13.sp,
                    modifier = Modifier.clickable { homeCloseSearch() }.padding(start = 8.dp))
            }
        }
        // 3.6.9 收件箱入口（一级页右上角）：菜单按钮左侧
        Text("📮", color = Color(0xFFF2EEFA), fontSize = 16.sp,
            modifier = Modifier.clickable { onOpenInbox() }.padding(horizontal = 6.dp))
        // 功能抽屉入口（右上角）：面板从屏幕右缘向左滑出（3.7.10 抽屉提升为全局）
        IconButton(onClick = { appDrawerOpen = true }) { Text("⋯", color = Color(0xFFF2EEFA), fontSize = 20.sp) }
    }
}

/** 关闭并清空搜索（3.7.46：从 HomeScreen 的局部函数提升为顶层，供搜索栏调用）。 */
private fun homeCloseSearch() {
    searchOpen = false; q = ""
    sGroups = emptyList(); sWorks = emptyList(); sAuthors = emptyList()
}
