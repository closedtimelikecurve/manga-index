package com.biblioteca.reader

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyGridState
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/* ================================================================
   3.3.1 喜爱一级页（胶囊「❤ 喜爱」）：已喜爱画师封面墙，点击进档案页
   3.7.43 从 Screens31.kt 拆出（原 FavoritesScreen 112 行 / cc 12）：
   屏壳（状态+拉取+下拉刷新）/ 网格（三态）/ 画师卡。
   ================================================================ */
@Composable
@OptIn(ExperimentalFoundationApi::class, androidx.compose.material3.ExperimentalMaterial3Api::class)
fun FavoritesScreen(onOpenArtist: (String) -> Unit = {},
                    // 3.7.10 喜爱页同样挂全局菜单抽屉（除本地书架外的一级页都要有菜单）
                    onOpenMenu: () -> Unit = {},
                    // 3.6.9 收件箱入口（一级页右上角）
                    onOpenInbox: () -> Unit = {},
                    // 3.7.12 滚动位置跨返回保留：LazyGridState 由外层（MainActivity）按页持存
                    gridState: LazyGridState = LazyGridState(),
                    // 3.7.37：离线时顶部黄色警告条（替代原断线弹窗）
                    offline: Boolean = false, onRetryOnline: () -> Unit = {}) {
    val scope = rememberCoroutineScope()
    val ctx = LocalContext.current       // 3.6.11 画师名长按复制
    var items by remember { mutableStateOf<List<Api.FollowItem>?>(null) }
    // 3.7.10 区域内搜索：只在本页已加载的喜爱画师里按名字过滤（不打全库接口）
    var query by remember { mutableStateOf("") }
    // keep：下拉刷新时保留旧数据占位（不清空 → 不闪白），首次加载仍走空态
    // 3.7.66 复位挂加载完成点——LaunchedEffect(items) 在数据结构相等时不重跑，箭头会卡死
    var refreshing by remember { mutableStateOf(false) }
    fun load(keep: Boolean = false) {
        scope.launch {
            if (!keep) items = null
            items = try { withContext(Dispatchers.IO) { Api.follows() } }
                catch (_: Exception) { emptyList() }
            refreshing = false
        }
    }
    LaunchedEffect(Unit) { load() }
    Column(Modifier.fillMaxSize()) {
        FavoritesTopBar(items, query, offline, onOpenMenu, onOpenInbox,
            onQueryChange = { query = it }, onRetryOnline = onRetryOnline)
        // 3.7.12 下拉刷新：列表顶部下拉重新拉取喜爱画师
        androidx.compose.material3.pulltorefresh.PullToRefreshBox(
            isRefreshing = refreshing,
            onRefresh = { refreshing = true; load(keep = true) },
            modifier = Modifier.fillMaxSize()
        ) {
            FavoritesGrid(items, query, gridState, onOpenArtist, onRetry = { load() },
                header = { FavoritesTitle(items) })
        }
    }
}

/** 喜爱页页头：区域搜索栏（**固定在顶部**）+ 离线横幅。
 *  3.7.86（用户需求）：标题行不再固定——它跟着内容一起滚走，只有搜索栏常驻。 */
@Composable
private fun FavoritesTopBar(items: List<Api.FollowItem>?, query: String, offline: Boolean,
                            onOpenMenu: () -> Unit, onOpenInbox: () -> Unit,
                            onQueryChange: (String) -> Unit, onRetryOnline: () -> Unit) {
    // 3.7.85（用户需求②）：搜索栏提到**最顶层**（与首页一致）——此前它夹在标题行与
    // 内容之间，既不属于页头也不属于内容，视觉上"不上不下"。
    RegionSearchBar(
        query = query, onQueryChange = onQueryChange,
        placeholder = AppI18n.s("搜索喜爱的画师"),
        onMenu = onOpenMenu,
        onOpenInbox = onOpenInbox,
        counter = if (query.isNotBlank() && items != null) AppI18n.sf("%1 位", items!!.count { it.author.contains(query, true) }) else "")
    // 3.7.37：离线黄色警告条（替代原断线弹窗）
    if (offline) {
        OfflineBanner(onRetry = onRetryOnline)
        Spacer(Modifier.height(8.dp))
    }
}

/** 标题行（3.7.86）：作为网格首项渲染 → 随内容滚走，不再常驻。 */
@Composable
private fun FavoritesTitle(items: List<Api.FollowItem>?) {
    Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("❤ " + AppI18n.s("喜爱的画师"), color = Color(0xFFF2EEFA), fontSize = 18.sp, modifier = Modifier.weight(1f))
        Text(if (items == null) "" else AppI18n.sf("%1 位", items!!.size),
            color = Color(0xFF9A8FB8), fontSize = 11.sp)
    }
}

/** 喜爱网格三态：加载中 / 空态（还没有喜爱的画师）/ 搜索结果或卡片墙。 */
@Composable
private fun FavoritesGrid(items: List<Api.FollowItem>?, query: String, gridState: LazyGridState,
                          onOpenArtist: (String) -> Unit, onRetry: () -> Unit,
                          header: @Composable () -> Unit) {
    val shown = items?.filter { it.author.contains(query, ignoreCase = true) }
    // 过滤后判空：加载中 / 还没喜爱 / 搜索无命中，三态都带标题行（否则标题时有时无）
    if (shown.isNullOrEmpty()) {
        Column(Modifier.fillMaxSize()) {
            header()
            FavoritesEmpty(items, items.isNullOrEmpty(), query, onRetry)
        }
        return
    }
    LazyVerticalGrid(
        state = gridState,
        columns = GridCells.Adaptive(110.dp),
        contentPadding = PaddingValues(start = 10.dp, end = 10.dp, top = 4.dp, bottom = 96.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.fillMaxSize()
    ) {
        item(span = { GridItemSpan(maxLineSpan) }) { header() }
        items(shown, key = { it.author }) { f -> FavoritesArtistCard(f, onOpenArtist) }
    }
}

/** 喜爱页三态空体（3.7.86 抽出：网格主函数要留预算给 header 槽位）。 */
@Composable
private fun FavoritesEmpty(items: List<Api.FollowItem>?, noFavorites: Boolean,
                           query: String, onRetry: () -> Unit) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        when {
            items == null -> CircularProgressIndicator(color = ACCENT2)
            noFavorites -> Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text("🤍", fontSize = 34.sp)
                Text(AppI18n.s("还没有喜爱的画师——去首页「全部画师」\n点亮右下角的爱心吧"),
                    color = Color(0xFF9A8FB8), fontSize = 12.sp, lineHeight = 18.sp,
                    modifier = Modifier.padding(top = 10.dp))
                Text("⟳ " + AppI18n.s("点此重试"), color = ACCENT2, fontSize = 12.sp,
                    modifier = Modifier.padding(top = 10.dp).clickable { onRetry() })
            }
            else -> Text(AppI18n.sf("没有匹配「%1」的喜爱画师", query),
                color = Color(0xFF9A8FB8), fontSize = 12.sp)
        }
    }
}

/** 喜爱画师卡：封面（有则拉服务端快照）+ 姓名 + 作品数；点击进档案页。 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun FavoritesArtistCard(f: Api.FollowItem, onOpenArtist: (String) -> Unit) {
    // 3.7.21 需求1：喜爱页画师卡去长按复制（点击照旧开档案）
    Column(Modifier
        .clip(RoundedCornerShape(10.dp))
        .background(Color(0xFF140F22))
        .combinedClickable(onClick = { onOpenArtist(f.author) })) {
        Box(Modifier.fillMaxWidth().aspectRatio(3f / 4f)
            .background(Color(0xFF1C1433)), contentAlignment = Alignment.Center) {
            Text("👤", fontSize = 30.sp)
            if (f.coverGroup != null && f.coverWork != null) {
                AsyncImage(model = Api.coverUrl(f.coverGroup, f.coverWork, f.coverVer),
                    contentDescription = f.author, contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize())
            }
            // 3.7.10 左上角「新 N」计数红点已移除：用户明确该系统不需要红点
            Text("❤", fontSize = 14.sp,
                modifier = Modifier.align(Alignment.BottomEnd).padding(6.dp)
                    .clip(CircleShape)
                    .background(Color(0x99060411)).padding(4.dp))
        }
        Column(Modifier.padding(8.dp)) {
            Text(f.author, color = Color(0xFFF2EEFA), fontSize = 12.sp,
                maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(AppI18n.sf("%1 部 · 点看档案", f.works),
                color = Color(0xFF9A8FB8), fontSize = 10.sp)
        }
    }
}
