package com.biblioteca.reader

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyGridState
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.Locale

/* ================================================================
   本地书架（APP 3.0）：已下载作品的离线阅读入口
   * 卡片 = 本地封面快照 + 名称/社团/页数/大小；角标：「有更新」「来源失效」
   * 长按 = 删除作品（3.6.9 起改回直接删：连作品文件与封面一起删）
   * 离线模式：顶部横幅 + 重试连接；本地作品全程不依赖服务器

   3.7.43 结构：页头/统计/主体/网格/卡片/角标/删除弹窗各自独立
   （原 ShelfScreen 160 行，网格卡片段是最大一块）。
   ================================================================ */

fun fmtBytesShelf(n: Long): String = when {
    n >= 1073741824L -> String.format(Locale.US, "%.2f GB", n / 1073741824.0)
    n >= 1048576L -> String.format(Locale.US, "%.1f MB", n / 1048576.0)
    n >= 1024L -> String.format(Locale.US, "%.0f KB", n / 1024.0)
    else -> "$n B"
}

/* 3.7.85（用户需求②）：搜索栏提到最顶层——原来夹在页头与统计行之间，
   既不属于页头也不属于内容，是四个一级界面里最"不上不下"的一处。 */
@OptIn(ExperimentalFoundationApi::class, androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun ShelfScreen(offline: Boolean, entries: List<LibraryStore.Entry>,
                updateFlags: Map<String, Boolean>,
                onOpenReader: (LibraryStore.Entry) -> Unit,
                onDelete: (LibraryStore.Entry) -> Unit, onRetryOnline: () -> Unit,
                // 3.7.13：下载管理入口（更新检查移入下载页）；3.7.95：菜单键→抽屉
                onOpenDownloads: () -> Unit, onOpenDrawer: () -> Unit = {},
                // 3.7.60：从 works/ 找回作品（索引丢了但文件还在时用）
                onRecover: () -> Unit = {},
                // 3.7.12 下拉刷新（本地数据重扫）/ 滚动位置跨返回保留
                onRefresh: () -> Unit = {}, gridState: LazyGridState = LazyGridState()) {
    val ctx = LocalContext.current
    var askDelete by remember { mutableStateOf<LibraryStore.Entry?>(null) }
    // 3.7.12 区域内搜索：只在本书架已加载条目里按作品名/社团名过滤（本地模式无菜单）
    var query by remember { mutableStateOf("") }
    // 3.7.12 下拉刷新指示。3.7.67：收箭头靠 isRefreshing 真实翻转 false→true→false（M3 靠该翻转走
    // endRefresh）——同帧写 true 再写 false 会被合并成"没变过"，手势拉起的转圈永远收不起来
    // （3.7.66 教训）；refreshTick 完成拍保证复位落在 true 帧之后（refreshShelf 本身同步完成）。
    var refreshing by remember { mutableStateOf(false) }; var refreshTick by remember { mutableIntStateOf(0) }
    LaunchedEffect(refreshTick) { if (refreshTick > 0) refreshing = false }
    // 3.5.0 占用统计移出组合期：usageBytes 递归 walk 全部文件，书架大时在主线程同步
    // 磁盘 I/O 掉帧；现在后台算，先显示"统计中…"（首次为 0 也无碍，随即被真实值替换）
    var usage by remember { mutableStateOf(0L) }
    LaunchedEffect(entries) { usage = withContext(Dispatchers.IO) { LibraryStore.usageBytes(ctx) } }
    // 3.7.10 区域内搜索过滤（作品名 / 社团名，忽略大小写）
    val shown = shelfShown(entries, query)

    Column(Modifier.fillMaxSize()) {
        RegionSearchBar(
            query = query, onQueryChange = { query = it },
            placeholder = AppI18n.s("搜索本地书架作品 / 社团"),
            onMenu = onOpenDrawer,
            counter = if (query.isNotBlank()) AppI18n.sf("%1 部", shown.size) else "")
        // 3.7.12 下拉刷新：列表顶部下拉重扫本地书架
        androidx.compose.material3.pulltorefresh.PullToRefreshBox(
            isRefreshing = refreshing,
            onRefresh = { refreshing = true; refreshTick++; onRefresh() },
            modifier = Modifier.fillMaxSize()
        ) {
            // 3.7.86：标题/统计/离线横幅全部进滚动内容，只有搜索栏常驻顶部
            ShelfBody(entries.isEmpty(), query, shown, ctx, gridState, updateFlags,
                header = { ShelfTopHeader(offline, onOpenDownloads, entries.size, usage, onRetryOnline) },
                onOpenReader = onOpenReader, onRecover = onRecover,
                onLongPress = { askDelete = it })
        }   // PullToRefreshBox（3.7.12）
    }

    askDelete?.let { e ->
        ShelfDeleteDialog(e, onDismiss = { askDelete = null }) { onDelete(e) }
    }
}

/** 3.7.10 区域内搜索过滤（作品名 / 社团名，忽略大小写；空 query 全量返回）。 */
private fun shelfShown(entries: List<LibraryStore.Entry>, query: String) =
    entries.filter { e ->
        e.work.contains(query, ignoreCase = true) || e.group.contains(query, ignoreCase = true) }

/** 离线横幅（3.7.37 起统一走 OfflineBanner，与首页/续读/喜爱同一份样式）。 */
@Composable
private fun ShelfOfflineBanner(onRetryOnline: () -> Unit) {
    OfflineBanner(onRetry = onRetryOnline)
    Spacer(Modifier.height(8.dp))
}

/** 页头：标题 + 下载入口（在线时常驻；有活动任务时文字变「下载中」）。 */
@Composable
private fun ShelfHeader(offline: Boolean, onOpenDownloads: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(AppI18n.s("📚 本地书架"), color = Color(0xFFF2EEFA), fontSize = 18.sp, modifier = Modifier.weight(1f))
        if (!offline) {
            // 3.7.13：下载入口（常驻显示；有活动任务时文字变「下载中」）
            val dlActive = DownloadManager.activeCount() > 0
            Text(if (dlActive) AppI18n.s("⬇ 下载中") else AppI18n.s("⬇ 下载"), color = ACCENT2, fontSize = 13.sp,
                modifier = Modifier.clickable { onOpenDownloads() }
                    .padding(start = 8.dp))
        }
    }
}

/** 书架页头（3.7.86）：标题 + 下载入口 + 离线横幅 + 统计行——整体随内容滚走。 */
@Composable
private fun ShelfTopHeader(offline: Boolean, onOpenDownloads: () -> Unit,
                           total: Int, usage: Long, onRetryOnline: () -> Unit) {
    Column {   // 3.7.95：grid item 里多根内容会同格叠放（标题与统计行重叠的根因），必须包容器
        ShelfHeader(offline, onOpenDownloads)
        if (offline) ShelfOfflineBanner(onRetryOnline)
        ShelfStatsRow(total, usage)
    }
}

/** 统计行：部数 + 占用（usage 后台算，首帧显示"统计中…"）。 */
@Composable
private fun ShelfStatsRow(total: Int, usage: Long) {
    Text(when {
        total == 0 -> AppI18n.s("书架还是空的")
        usage <= 0L -> AppI18n.sf("共 %1 部 · 占用统计中…", total)
        else -> AppI18n.sf("共 %1 部 · 占用 %2", total, fmtBytesShelf(usage))
    },
        color = Color(0xFF9A8FB8), fontSize = 11.sp,
        modifier = Modifier.padding(horizontal = 14.dp, vertical = 4.dp))
}

/** 主体：空态 / 搜索无匹配 / 作品网格（3.7.43 从 ShelfScreen 抽出）。 */
@Composable
private fun ShelfBody(empty: Boolean, query: String, shown: List<LibraryStore.Entry>,
                      ctx: android.content.Context, gridState: LazyGridState,
                      updateFlags: Map<String, Boolean>,
                      header: @Composable () -> Unit,
                      onOpenReader: (LibraryStore.Entry) -> Unit,
                      onRecover: () -> Unit,
                      onLongPress: (LibraryStore.Entry) -> Unit) {
    when {
        empty -> Column(Modifier.fillMaxSize()) {
            header()
            ShelfEmptyState(onRecover)
        }
        shown.isEmpty() -> Column(Modifier.fillMaxSize()) {
            header()
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(AppI18n.sf("没有匹配「%1」的本地作品", query),
                    color = Color(0xFF9A8FB8), fontSize = 12.sp)
            }
        }
        else -> ShelfGrid(shown, ctx, gridState, updateFlags, header,
            onOpenReader, onLongPress)
    }
}

/** 空书架态（3.7.86 抽出：ShelfBody 要留预算给 header 槽位）。 */
@Composable
private fun ShelfEmptyState(onRecover: () -> Unit) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text("📭", fontSize = 34.sp)
                Text(AppI18n.s("在首页/社团页长按作品，选择「下载到本地」"),
                    color = Color(0xFF9A8FB8), fontSize = 13.sp,
                    modifier = Modifier.padding(top = 10.dp))
                // 3.7.60：书架空了但作品文件还在设备上时，这个按钮能把条目找回来
                Text(AppI18n.s("🔍 从设备找回已下载作品"), color = ACCENT2, fontSize = 12.5.sp,
                    modifier = Modifier.padding(top = 14.dp)
                        .clip(RoundedCornerShape(999.dp))
                        .border(1.dp, ACCENT2, RoundedCornerShape(999.dp))
                        .clickable { onRecover() }
                        .padding(horizontal = 14.dp, vertical = 7.dp))
        }
    }
}

/** 作品网格（自适应列宽，滚动位置跨返回保留）+ 底部操作提示。 */
@Composable
private fun ShelfGrid(shown: List<LibraryStore.Entry>, ctx: android.content.Context,
                      gridState: LazyGridState, updateFlags: Map<String, Boolean>,
                      header: @Composable () -> Unit,
                      onOpenReader: (LibraryStore.Entry) -> Unit,
                      onLongPress: (LibraryStore.Entry) -> Unit) {
    LazyVerticalGrid(
        state = gridState,
        columns = GridCells.Adaptive(110.dp),
        contentPadding = PaddingValues(start = 10.dp, end = 10.dp, top = 10.dp, bottom = 96.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.fillMaxSize()
    ) {
        item(span = { GridItemSpan(maxLineSpan) }) { header() }
        items(shown, key = { it.key }) { e ->
            ShelfCard(e, ctx, updateFlags[e.key] == true, onOpenReader) { onLongPress(e) }
        }
        item(span = { GridItemSpan(maxLineSpan) }) {
            Text(AppI18n.s("长按作品即删除（作品文件与封面一并删除，释放占用）；「来源失效」= 面板上已改名/解散/删除，仅本地可读；书库/本地由底部胶囊切换。"),
                color = Color(0xFF6E6787), fontSize = 10.sp, lineHeight = 14.sp,
                modifier = Modifier.padding(6.dp, 4.dp))
        }
    }
}

/**
 * 书架作品卡：本地封面快照 + 名称/社团/页数/大小；角标「有更新」「来源失效」。
 * 长按删除由 onLongPress 上报（确认弹窗在页面级，避免每卡一份）。
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ShelfCard(e: LibraryStore.Entry, ctx: android.content.Context, hasUpdate: Boolean,
                      onOpenReader: (LibraryStore.Entry) -> Unit, onLongPress: () -> Unit) {
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
        .combinedClickable(
            onClick = { onOpenReader(e) },
            onLongClick = onLongPress)) {
        Box(Modifier.fillMaxWidth().aspectRatio(3f / 4f)
            .background(Color(0xFF1C1433)), contentAlignment = Alignment.Center) {
            val cover = LibraryStore.coverFile(ctx, e.group, e.work)
            if (e.cover && cover.exists()) {
                AsyncImage(model = cover,
                    contentDescription = e.work, contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize())
            } else Text("📦", fontSize = 30.sp)
            // 角标：右上有更新 / 左上来源失效
            if (hasUpdate) ShelfBadge(AppI18n.s("有更新"), Color(0xFFFFC86B), Color(0xFF1C1433), Alignment.TopEnd)
            if (e.stale) ShelfBadge(AppI18n.s("来源失效"), Color(0x66FF6B8B), Color(0xFFFFC86B), Alignment.TopStart)
        }
        Column(Modifier.padding(8.dp)) {
            Text(e.work, color = Color(0xFFF2EEFA), fontSize = 12.sp,
                maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(shelfMetaLine(e),
                color = Color(0xFF9A8FB8), fontSize = 10.sp, maxLines = 2,
                overflow = TextOverflow.Ellipsis)
        }
    }
}

/** 卡片元信息行：社团 + 页数/读完/续读 + 大小。 */
private fun shelfMetaLine(e: LibraryStore.Entry): String = buildString {
    append("🏢 ${e.group}")
    if (e.pages > 0) append(AppI18n.sf(" · %1 页", e.pages))
    // 3.6.9 书架内部续读记录（本地续读不参与续读区，就在这里显示）
    if (e.finished) append(AppI18n.s(" · 已读完"))
    else if (e.lastPage > 0) append(AppI18n.sf(" · 续读到第 %1 页", e.lastPage + 1))
} + " · ${fmtBytesShelf(e.size)}"

/** 角标胶囊（有更新=右上，来源失效=左上）。 */
@Composable
private fun BoxScope.ShelfBadge(text: String, bg: Color, fg: Color, align: Alignment) {
    Text(text, color = fg, fontSize = 9.sp,
        modifier = Modifier.align(align).padding(4.dp)
            .clip(RoundedCornerShape(999.dp))
            .background(bg).padding(horizontal = 6.dp, vertical = 2.dp))
}

/** 删除确认弹窗（长按卡片后弹出；作品文件与封面一并删，服务器不受影响）。 */
@Composable
private fun ShelfDeleteDialog(e: LibraryStore.Entry, onDismiss: () -> Unit, onConfirm: () -> Unit) {
    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(AppI18n.s("删除作品")) },
        text = { Text(AppI18n.sf("确定删除「%1」？\n\n作品文件与封面将一并从手机存储删除，占用随即释放；服务器上的作品不受影响，日后可重新下载。", e.work)) },
        confirmButton = {
            androidx.compose.material3.TextButton(onClick = {
                onDismiss()
                onConfirm()
            }) { Text(AppI18n.s("删除"), color = Color(0xFFFF6B8B)) }
        },
        dismissButton = {
            androidx.compose.material3.TextButton(onClick = onDismiss) { Text(AppI18n.s("取消")) }
        }
    )
}

/** 检查更新（在线时逐条取 manifest 与下载时快照比对）：返回 (失效的 key 集合, 有更新的 key 集合)。
 * 仅服务端明确 404 才标记「来源失效」；瞬态网络错误不误标。 */
suspend fun checkShelfUpdates(entries: List<LibraryStore.Entry>): Pair<Set<String>, Set<String>> =
    withContext(Dispatchers.IO) {
        val stale = mutableSetOf<String>()
        val updated = mutableSetOf<String>()
        for (e in entries) {
            try {
                val m = Api.exportManifest(e.group, e.work)
                if (!m.downloadable) {           // 文件夹作品本就不可导出：来源仍有效
                    LibraryStore.setStale(e.key, false)
                    continue
                }
                LibraryStore.setStale(e.key, false)
                if (m.size != e.serverSize || m.mtime != e.serverMtime) updated.add(e.key)
            } catch (e2: ApiException) {
                if (e2.message == "HTTP 404") {  // 服务端已无此作品（改名/解散/删除）
                    stale.add(e.key)
                    LibraryStore.setStale(e.key, true)
                }
            } catch (_: Exception) {
                // 瞬态网络错误：不误标失效
            }
        }
        stale to updated
    }
