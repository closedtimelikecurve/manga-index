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

/* 3.7.46：从 MainActivity.kt 搬出（社团页）。原函数超当时的 80 行 / cc15 预算（2026-10-20 已收紧到 50 行），且 MainActivity 当时已顶到 2739 行文件上限——就地抽函数会让文件行数回升触发 F001，故整体搬到独立文件。 */
/** 3.7.69 reloadKey 消费一次性化：LaunchedEffect 每次**重进组合**都会重跑（退出阅读器
 *  返回也算），而 circleReload 是全局计数器永不归零——旧写法每次重进都 onLoad(true) →
 *  /api/circle?refresh=1 → 后台重扫，是"退出阅读回顶"闭环的第一环。记录已消费值，
 *  只有 key 真变化（设封面/删作品/Info 返回等）才强制重载（保留旧数据占位，滚动不丢）。 */
@Composable
private fun rememberCircleReload(name: String, works: List<Api.Work>?, reloadKey: Int,
                                 onLoad: (Boolean) -> Unit) {
    var consumed by remember(name) { mutableStateOf<Int?>(null) }
    LaunchedEffect(name, reloadKey) {
        if (works == null) onLoad(false)
        else if (reloadKey > 0 && consumed != reloadKey) {
            consumed = reloadKey; onLoad(true)
        }
    }
}

@OptIn(ExperimentalFoundationApi::class,
    androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun CircleScreen(name: String, works: List<Api.Work>?, error: String, gridState: LazyGridState,
                 authors: List<Api.TagItem> = emptyList(),
                 cover: Api.CircleCover? = null,
                 onLoad: (Boolean) -> Unit, onOpen: (String) -> Unit, onBack: () -> Unit,
                 onOpenArtist: (String) -> Unit = {},
                 // 3.7.51：作品卡上的原作标签可点进分区
                 onOpenOriginal: (String) -> Unit = {},
                 // 3.7.54：右上角「⛏ 爬取」——按本社团名到站点搜索，勾选后自动入库归区
                 onProbe: () -> Unit = {},
                 // 3.7.66 下拉刷新收尾信号：loadCircle 每轮必 bump 的完成拍（见 LaunchedEffect(loadTick)）
                 loadTick: Int = 0,
                 reloadKey: Int = 0,
                 onLongPressWork: (String, String, IntRect) -> Unit = { _, _, _ -> }) {
    // 3.7.69：reloadKey 消费一次性化（退出阅读回顶闭环的第一环，详见 rememberCircleReload）
    rememberCircleReload(name, works, reloadKey, onLoad)
    BackHandler { onBack() }
    var refreshing by remember(name) { mutableStateOf(false) }
    var worksAsc by remember(name) { mutableStateOf(false) }   // 3.7.40：作品排序方向（默认新→旧）
    // 3.6.151：排序维度 time / size / name（不带 key，换社团时沿用同一偏好，方便逐社团查重）
    var worksSort by remember { mutableStateOf("time") }
    // 3.7.66 复位挂 loadCircle 完成拍——LaunchedEffect(works, error) 在刷新后数据结构相等时
    // 不会重跑，转圈箭头会永远留在原地
    LaunchedEffect(loadTick) { if (loadTick > 0) refreshing = false }
    // 3.6.0：改名/解散的对话框与请求已上移到根层（由社团操作目录触发），本页不再持有相关状态。

    Column(Modifier.fillMaxSize()) {
        CircleTopRow(name, onBack, onProbe)
        // 社团封面（设为社团封面后在此立即可见；无覆盖时回退派生封面）
        if (cover != null && cover.coverGroup != null && !cover.coverWork.isNullOrEmpty()) {
            CircleCoverBox(cover)
            Spacer(Modifier.height(4.dp))
        }
        // 3.2.1 社团内作者聚合 → 画师档案直达
        if (authors.isNotEmpty()) {
            CircleAuthorRow(authors, onOpenArtist)
            Spacer(Modifier.height(4.dp))
        }
        // 3.7.40：分区内作品排序（新→旧 / 逆序）
        if (works != null && works.isNotEmpty()) {
            WorksSortBar(worksSort, worksAsc, { m, a -> worksSort = m; worksAsc = a },
                Modifier.padding(horizontal = 14.dp, vertical = 2.dp))
            Spacer(Modifier.height(4.dp))
        }
        CircleBody(refreshing = refreshing, onRefresh = { refreshing = true; onLoad(true) },
            error = error, works = works, worksSort = worksSort, worksAsc = worksAsc,
            gridState = gridState,
            onOpen = onOpen, name = name, onLongPressWork = onLongPressWork,
            onOpenArtist = onOpenArtist, onOpenOriginal = onOpenOriginal)
    }
}

/** 社团页页头（3.7.46 拆出）：返回箭头 + 社团名。 */
@Composable
private fun CircleTopRow(name: String, onBack: () -> Unit, onProbe: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("←", color = Color(0xFFF2EEFA), fontSize = 20.sp,
            modifier = Modifier.clickable { onBack() }.padding(end = 10.dp))
        // 3.7.21 需求1：社团页标题去长按复制（长按无操作）；改名/解散/删除菜单在首页社团卡封面长按。
        Text("🏢 $name", color = Color(0xFFF2EEFA), fontSize = 18.sp,
            modifier = Modifier.weight(1f),
            maxLines = 1, overflow = TextOverflow.Ellipsis)
        ProbeEntryChip(onClick = onProbe)
    }
}

/** 社团封面横幅（3.7.46 拆出）。 */
@Composable
private fun CircleCoverBox(cover: Api.CircleCover) {
    Box(Modifier.fillMaxWidth().height(132.dp).clip(RoundedCornerShape(10.dp))
        .background(Color(0xFF1C1433)).padding(bottom = 8.dp)) {
        AsyncImage(model = Api.coverUrl(cover.coverGroup ?: "", cover.coverWork ?: "", cover.coverVer),
            contentDescription = AppI18n.s("社团封面"), contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxSize())
    }
}

/** 社团内画师聚合行（3.7.46 拆出）：点进画师档案，长按复制标签。 */
@Composable
private fun CircleAuthorRow(authors: List<Api.TagItem>, onOpenArtist: (String) -> Unit) {
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        authors.forEach { a ->
            // 3.7.28：标签长按复制回归（3.7.21 撤的是**卡片标题**的复制，
            // 标签区与封面长按菜单不重叠，不会重现当时的冲突）。
            Text("👤 ${a.name}（${a.count}）", color = Color(0xFF9A8FB8), fontSize = 11.sp,
                maxLines = 1,
                modifier = Modifier.clip(RoundedCornerShape(999.dp)).background(Color(0x1AFFFFFF))
                    .tagClickable(a.name) { onOpenArtist(a.name) }
                    .padding(horizontal = 10.dp, vertical = 4.dp))
        }
    }
}

/** 社团页主体（3.7.46 拆出）：下拉刷新 + 四态（失败/加载中/无作品/作品网格）。 */
@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
private fun CircleBody(
    refreshing: Boolean, onRefresh: () -> Unit,
    error: String, works: List<Api.Work>?, worksSort: String, worksAsc: Boolean,
    gridState: LazyGridState, onOpen: (String) -> Unit,
    name: String, onLongPressWork: (String, String, IntRect) -> Unit,
    onOpenArtist: (String) -> Unit,
    onOpenOriginal: (String) -> Unit = {}
) {
    androidx.compose.material3.pulltorefresh.PullToRefreshBox(
        isRefreshing = refreshing,
        onRefresh = onRefresh,
        modifier = Modifier.fillMaxSize()
    ) {
        when {
            error.isNotEmpty() -> LazyColumn(Modifier.fillMaxSize()) {
                item {
                    Column(Modifier.fillMaxWidth().padding(top = 90.dp),
                        horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(AppI18n.sf("加载失败：%1", error), color = Color(0xFFFF5ED0), fontSize = 13.sp)
                        Text(AppI18n.s("⟳ 重试"), color = Color(0xFF9A8FB8), fontSize = 14.sp,
                            modifier = Modifier.padding(top = 18.dp).clickable { onRefresh() })
                    }
                }
            }
            works == null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = ACCENT)
            }
            works.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(AppI18n.s("没有作品"), color = Color(0xFF9A8FB8))
            }
            else -> CircleWorksGrid(works, worksSort, worksAsc, gridState, name,
                onOpen, onLongPressWork, onOpenArtist, onOpenOriginal)
        }
    }
}

/** 社团内作品网格（3.6.151 从 CircleBody 抽出：原函数 51 行，超预算）。 */
@Composable
private fun CircleWorksGrid(works: List<Api.Work>, worksSort: String, worksAsc: Boolean,
                            gridState: LazyGridState, name: String, onOpen: (String) -> Unit,
                            onLongPressWork: (String, String, IntRect) -> Unit,
                            onOpenArtist: (String) -> Unit, onOpenOriginal: (String) -> Unit) {
    // 3.7.69：排序键 mtime → addedAt（首次入库时间，删首图重写不推进；0 值兜底 mtime）
    val w = sortWorksList(works, worksSort, worksAsc,
        { (if (it.addedAt > 0) it.addedAt else it.mtime) },
        { it.size }, { it.name })
    LazyVerticalGrid(
        state = gridState,
        columns = GridCells.Adaptive(110.dp),
        contentPadding = PaddingValues(10.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.fillMaxSize()
    ) {
        items(w, key = { it.name }) { item ->
            CircleWorkCard(item, name, onOpen, onLongPressWork, onOpenArtist, onOpenOriginal)
        }
    }
}

/** 社团内作品卡（3.7.46 拆出）：封面区长按唤出操作菜单，文字区不可选。 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun CircleWorkCard(w: Api.Work, name: String, onOpen: (String) -> Unit,
                           onLongPressWork: (String, String, IntRect) -> Unit,
                           onOpenArtist: (String) -> Unit,
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
        .combinedClickable(onClick = { onOpen(w.name) })) {
        Box(Modifier.fillMaxWidth().aspectRatio(3f / 4f)
            .background(Color(0xFF1C1433))
            .combinedClickable(
                onClick = { onOpen(w.name) },
                onLongClick = { onLongPressWork(name, w.name, cardRect) }),
            contentAlignment = Alignment.Center
        ) {
            if (w.hasCover) {
                AsyncImage(
                    model = Api.coverUrl(name, w.name),
                    contentDescription = w.name,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize())
            } else {
                Text("📄", fontSize = 30.sp)
            }
            ReadingBadges(name, w.name)   // 3.5.0 已读✓/读n/新 角标
        }
        Column(Modifier.padding(8.dp)) {
            Text(w.name, color = Color(0xFFF2EEFA), fontSize = 11.sp, maxLines = 2,
                overflow = TextOverflow.Ellipsis)
            // 3.6.15 需求4：社团内作品显示合作画师标签（规则同画师页：显示全部合作者；
            // 社团本身即页面主体，不再额外渲染社团标签）。点击进画师档案。
            if (w.personals.isNotEmpty()) CircleWorkPersonals(w, onOpenArtist)
            // 3.7.51：原作标签（任何分区都显示）
            WorkOriginalsRow(w.originals, onOpenOriginal)
            Text(if (w.pages > 0) AppI18n.sf("%1 页", w.pages) else "",
                color = Color(0xFF9A8FB8), fontSize = 10.sp)
        }
    }
}

/** 社团内作品卡的合作画师标签行（3.7.48 从 CircleWorkCard 抽出）。 */
@Composable
private fun CircleWorkPersonals(w: Api.Work, onOpenArtist: (String) -> Unit) {
    Row(Modifier.padding(top = 3.dp)
        .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        w.personals.forEach { a ->
            Text("👤 " + a, color = ACCENT2, fontSize = 10.sp,
                maxLines = 1,
                modifier = Modifier.clip(RoundedCornerShape(999.dp))
                    .background(Color(0x1AFFFFFF))
                    .tagClickable(a) { onOpenArtist(a) }
                    .padding(horizontal = 8.dp, vertical = 2.dp))
        }
    }
}
