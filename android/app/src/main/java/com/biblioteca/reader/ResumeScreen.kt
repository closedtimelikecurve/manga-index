package com.biblioteca.reader

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
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
import androidx.compose.foundation.rememberScrollState
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
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/* ================================================================
   3.3.0 继续阅读一级页（胶囊「📖 续读」）：在读书籍封面墙，点击续读
   3.7.43 从 Screens31.kt 拆出（原 ResumeScreen 167 行 / cc 18）：
   屏壳（状态+拉取+过滤+下拉刷新）/ 卡片（含页码角标与标签行）/ 空态。
   ================================================================ */
@OptIn(ExperimentalFoundationApi::class, androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun ResumeScreen(onOpenReader: (String, String) -> Unit = { _, _ -> },
                 onLongPressWork: (String, String, IntRect) -> Unit = { _, _, _ -> },
                 // 3.6.15 需求1：续读卡片标签可点进社团 / 画师档案
                 onOpenCircle: (String) -> Unit = {}, onOpenArtist: (String) -> Unit = {},
                 onOpenOriginal: (String) -> Unit = {},   // 3.7.51：原作标签可点进分区
                 onOpenMenu: () -> Unit = {}, onOpenInbox: () -> Unit = {},
                 // 3.7.12 滚动位置跨返回保留；3.7.37 离线黄色警告条
                 gridState: LazyGridState = LazyGridState(), offline: Boolean = false,
                 onRetryOnline: () -> Unit = {},
                 reloadKey: Int = 0) {
    val scope = rememberCoroutineScope()
    // 3.7.10 区域内搜索：只在本页已加载的续读作品里按作品名/社团名过滤
    var query by remember { mutableStateOf("") }
    var items by remember { mutableStateOf<List<Api.ResumeItem>?>(null) }
    // 3.6.9 本地书架续读不参与续读区：本地已下载作品 key 集合（下载/删除后会变，load 时同步）
    val localKeys = remember { mutableStateOf(LibraryStore.keys()) }
    // 3.7.12 下拉刷新：任何界面都能下拉（此前仅首页/社团页有）
    // 3.7.66 复位挂加载完成回调——LaunchedEffect(items) 在数据结构相等时不重跑，箭头会卡死
    var refreshing by remember { mutableStateOf(false) }
    fun load() {
        loadResume(scope, { items = it; refreshing = false }, { localKeys.value = it })
    }
    // reloadKey：作品级改动（来自长按菜单的删除/删首页图）后由外层自增，据此重载去掉旧卡片
    LaunchedEffect(reloadKey) { load() }
    // 失效条目/本地已下载项的过滤见 resumeVisible（"空位"修复的由来）
    val list = resumeVisible(items, localKeys.value)
    val countText = if (items == null) "" else AppI18n.sf("%1 部在读", list.size)
    val counter = if (query.isNotBlank() && items != null)
        AppI18n.sf("%1 部", list.count { it.second.contains(query, true) || it.third.contains(query, true) }) else ""
    Column(Modifier.fillMaxSize()) {
        ResumeTopBar(countText, query, counter, offline, onOpenMenu, onOpenInbox,
            onQueryChange = { query = it }, onRetryOnline = onRetryOnline)
        // 3.7.12 下拉刷新：列表顶部下拉重新拉取续读数据
        androidx.compose.material3.pulltorefresh.PullToRefreshBox(
            isRefreshing = refreshing,
            onRefresh = { refreshing = true; load() },
            modifier = Modifier.fillMaxSize()
        ) {
            // 3.7.86：标题行进滚动内容（只有搜索栏常驻顶部）
            ResumeBody(items, list, query, gridState, offline, { ResumeTitle(countText) },
                onOpenReader, onOpenCircle, onOpenArtist, onLongPressWork, onOpenOriginal) { load() }
        }   // PullToRefreshBox（3.7.12）
    }
}

/** 拉取续读列表（3.7.43 提为模块级）：失败按空列表；回调同步本地键集合供排除用。 */
private fun loadResume(scope: kotlinx.coroutines.CoroutineScope,
                       onLoaded: (List<Api.ResumeItem>) -> Unit, onKeys: (Set<String>) -> Unit) {
    scope.launch {
        val r = try { withContext(Dispatchers.IO) { Api.readingResume(60) } }
                catch (_: Exception) { emptyList() }
        onLoaded(r)
        onKeys(LibraryStore.keys())   // 重载时同步本地键集合（下载/删除会变）
    }
}

/** 续读页页头：区域搜索栏（**固定在顶部**）+ 离线横幅。
 *  3.7.86（用户需求）：标题行改为随内容滚走，不再常驻。 */
/** 续读列表主体（3.7.86 抽出）：三种状态都带标题行，标题随内容滚走。 */
@Composable
private fun ResumeBody(items: List<Api.ResumeItem>?,
                       list: List<Triple<Api.ResumeItem, String, String>>,
                       query: String, gridState: LazyGridState, offline: Boolean,
                       header: @Composable () -> Unit,
                       onOpenReader: (String, String) -> Unit,
                       onOpenCircle: (String) -> Unit,
                       onOpenArtist: (String) -> Unit,
                       onLongPressWork: (String, String, IntRect) -> Unit,
                       onOpenOriginal: (String) -> Unit,
                       onRetry: () -> Unit) {
    when {
        items == null -> Column(Modifier.fillMaxSize()) {
            header()
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = ACCENT2)
            }
        }
        // 用过滤后的列表判空：全部条目都失效、或搜索无命中时才给空态，绝不渲染一屏空槽位
        list.isEmpty() -> Column(Modifier.fillMaxSize()) {
            header()
            ResumeEmptyState(query, onRetry = onRetry)
        }
        else -> ResumeGrid(list, query, gridState, offline, header, onOpenReader, onOpenCircle,
            onOpenArtist, onLongPressWork, onOpenOriginal)
    }
}

/** 标题行（3.7.86）：作为网格首项渲染 → 随内容滚走。 */
@Composable
private fun ResumeTitle(countText: String) {
    Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("📖 " + AppI18n.s("继续阅读"), color = Color(0xFFF2EEFA), fontSize = 18.sp, modifier = Modifier.weight(1f))
        Text(countText, color = Color(0xFF9A8FB8), fontSize = 11.sp)
    }
}

@Composable
private fun ResumeTopBar(countText: String, query: String, counter: String, offline: Boolean,
                         onOpenMenu: () -> Unit, onOpenInbox: () -> Unit,
                         onQueryChange: (String) -> Unit, onRetryOnline: () -> Unit) {
    // 3.7.85（用户需求②）：搜索栏提到最顶层，与首页同构（原来夹在标题与内容之间）
    RegionSearchBar(
        query = query, onQueryChange = onQueryChange,
        placeholder = AppI18n.s("搜索在读的作品 / 社团"),
        onMenu = onOpenMenu,
        onOpenInbox = onOpenInbox,
        counter = counter)
    // 3.7.37：离线黄色警告条（替代原断线弹窗）
    if (offline) {
        OfflineBanner(onRetry = onRetryOnline)
        Spacer(Modifier.height(8.dp))
    }
}

/**
 * 续读可见列表（3.7.43 提为模块级）：滤掉 group/work 失效项与本地已下载项。
 * 返回 (原始条目, group, work)，后两者已保证非空。
 */
private fun resumeVisible(items: List<Api.ResumeItem>?, localKeys: Set<String>) =
    items?.mapNotNull { r ->
        val g = r.group ?: return@mapNotNull null
        val w = r.work ?: return@mapNotNull null
        if (localKeys.contains("$g/$w")) return@mapNotNull null
        Triple(r, g, w)          // (原始条目, group, work)，后两者已保证非空
    } ?: emptyList()

/** 空态：没有在读（含本地书架说明）/ 搜索无命中两种文案共一个盒子。 */
@Composable
private fun ResumeEmptyState(query: String, onRetry: () -> Unit) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text("🌱", fontSize = 34.sp)
            Text(AppI18n.s("没有正在读的书——去书库挑一部开始吧\n(此列表需要联网；本地书架作品在书架内续读，不在此列表)"),
                color = Color(0xFF9A8FB8), fontSize = 12.sp, lineHeight = 18.sp,
                modifier = Modifier.padding(top = 10.dp))
            Text("⟳ " + AppI18n.s("点此重试"), color = ACCENT2, fontSize = 12.sp,
                modifier = Modifier.padding(top = 10.dp).clickable { onRetry() })
        }
    }
}

/** 在读网格：按查询过滤后渲染；无命中时给对应空态（绝不渲染一屏空槽位）。 */
@Composable
private fun ResumeGrid(list: List<Triple<Api.ResumeItem, String, String>>, query: String,
                       gridState: LazyGridState, offline: Boolean,
                       header: @Composable () -> Unit,
                       onOpenReader: (String, String) -> Unit, onOpenCircle: (String) -> Unit,
                       onOpenArtist: (String) -> Unit,
                       onLongPressWork: (String, String, IntRect) -> Unit,
                       onOpenOriginal: (String) -> Unit = {}) {
    // 3.7.10 按查询过滤（作品名 / 社团名，忽略大小写）
    val shown = list.filter { it.second.contains(query, ignoreCase = true) ||
        it.third.contains(query, ignoreCase = true) }
    if (shown.isEmpty()) {
        Column(Modifier.fillMaxSize()) {
            header()
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(AppI18n.sf("没有匹配「%1」的在读作品", query),
                    color = Color(0xFF9A8FB8), fontSize = 12.sp)
            }
        }
    } else LazyVerticalGrid(
        state = gridState,
        columns = GridCells.Adaptive(110.dp),
        contentPadding = PaddingValues(start = 10.dp, end = 10.dp, top = 4.dp, bottom = 96.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.fillMaxSize()
    ) {
        item(span = { GridItemSpan(maxLineSpan) }) { header() }
        items(shown, key = { it.first.key }) { (r, group, work) ->
            ResumeCard(r, group, work, onOpenReader, onOpenCircle, onOpenArtist,
                onLongPress = { rect -> onLongPressWork(group, work, rect) },
                onOpenOriginal = onOpenOriginal)
        }
    }
}

/**
 * 续读卡：封面 + 页码角标（lastPage+1/pages）+ 作品名 + 社团/画师标签 + 读到第几页。
 * 3.7.43 从 ResumeScreen 拆出（原卡片 inline 55 行）。
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ResumeCard(r: Api.ResumeItem, group: String, work: String,
                       onOpenReader: (String, String) -> Unit, onOpenCircle: (String) -> Unit,
                       onOpenArtist: (String) -> Unit, onLongPress: (IntRect) -> Unit,
                       onOpenOriginal: (String) -> Unit = {}) {
    var cardRect by remember { mutableStateOf(IntRect.Zero) }
    Column(Modifier
        .onGloballyPositioned { p ->
            cardRect = IntRect(
                p.positionInRoot().x.toInt(), p.positionInRoot().y.toInt(),
                (p.positionInRoot().x + p.size.width).toInt(),
                (p.positionInRoot().y + p.size.height).toInt())
        }
        .clip(RoundedCornerShape(10.dp))
        .background(Color(0xFF140F22))
        // 3.6.14：长按操作菜单只在封面区（下方 Box）唤出；
        // 3.7.21 需求1：文字区长按不再有选择/复制（根部 SelectionContainer 已撤）。
        .combinedClickable(
            onClick = { onOpenReader(group, work) })) {
        Box(Modifier.fillMaxWidth().aspectRatio(3f / 4f)
            .background(Color(0xFF1C1433))
            .combinedClickable(
                onClick = { onOpenReader(group, work) },
                onLongClick = { onLongPress(cardRect) }),
            contentAlignment = Alignment.Center) {
            AsyncImage(model = Api.coverUrl(group, work),
                contentDescription = work, contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize())
            Text("${(r.lastPage + 1).coerceAtMost(r.pages ?: 1)}/${r.pages ?: "?"}",
                color = Color(0xFF1C1433), fontSize = 9.sp,
                modifier = Modifier.align(Alignment.BottomEnd).padding(4.dp)
                    .clip(RoundedCornerShape(999.dp))
                    .background(ACCENT2.copy(alpha = 0xCC / 255f))
                    .padding(horizontal = 6.dp, vertical = 2.dp))
        }
        Column(Modifier.padding(8.dp)) {
            Text(work.dispWorkName(), color = Color(0xFFF2EEFA), fontSize = 12.sp,
                maxLines = 2, overflow = TextOverflow.Ellipsis)
            // 3.6.15 需求1：续读卡片标签化 —— 社团标签（点进社团）+ 合作画师标签（点进画师档案）
            ResumeCardTags(r, group, onOpenCircle, onOpenArtist, onOpenOriginal)
            Text(AppI18n.sf("读到 %1 页", r.lastPage + 1),
                color = Color(0xFF6E6787), fontSize = 10.sp, maxLines = 1,
                overflow = TextOverflow.Ellipsis)
        }
    }
}

/** 续读卡标签行：社团（收件箱不显示）+ 合作画师；点击跳转。 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ResumeCardTags(r: Api.ResumeItem, group: String,
                           onOpenCircle: (String) -> Unit, onOpenArtist: (String) -> Unit,
                           onOpenOriginal: (String) -> Unit = {}) {
    val cname = (r.circle.ifEmpty { group }).takeIf { it != "收件箱" }   // i18n:data 真实社团名   // i18n:data 真实社团名   // i18n:data 真实社团名
    Row(Modifier.padding(top = 3.dp)
        .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        if (cname != null) {
            Text("🏢 $cname", color = Color(0xFF9A8FB8), fontSize = 10.sp,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.clip(RoundedCornerShape(999.dp))
                    .background(Color(0x1AFFFFFF))
                    .tagClickable(cname) { onOpenCircle(cname) }   // 3.7.51：长按复制
                    .padding(horizontal = 8.dp, vertical = 3.dp))
        }
        r.personals.forEach { a ->
            Text("👤 $a", color = ACCENT2, fontSize = 10.sp,
                maxLines = 1,
                modifier = Modifier.clip(RoundedCornerShape(999.dp))
                    .background(Color(0x1AFFFFFF))
                    .tagClickable(a) { onOpenArtist(a) }   // 3.7.51：长按复制
                    .padding(horizontal = 8.dp, vertical = 3.dp))
        }
        // 3.7.51：原作标签（续读卡也要显示，此前只在原作分区页有）
        WorkOriginalsRow(r.originals, onOpenOriginal)
    }
}
