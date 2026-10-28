package com.biblioteca.reader

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/* ================================================================
   M4 画师档案页：跨社团封面墙（按入库时间倒序）+ 别名/社团聚合 + 关注
   3.7.43 从 Screens31.kt 拆出（原 ArtistScreen 196 行 / cc 22）：
   屏壳（状态+拉取+下拉刷新）/ 页头卡 / 社团标签行 / 作品卡 / 作品标签行。
   ================================================================ */
@OptIn(ExperimentalFoundationApi::class, androidx.compose.material3.ExperimentalMaterial3Api::class)
/**
 * 画师档案页。
 *
 * 3.7.63：**所有页面状态都按画师名做键**（`remember(name)`）。Compose 会把同一组合位置
 * 复用给不同参数：从画师 A 进 B、再返回 A 时，若 data 不随 name 重置，就会出现
 * "A 的滚动状态 + B 的作品列表"；B 的作品少时列表索引被钳到 0，换回 A 之后仍停在顶部——
 * 用户看到的就是"莫名刷新并回到顶部"。
 */
@Composable
fun ArtistScreen(name: String, onBack: () -> Unit,
                 onOpenCircle: (String) -> Unit = {}, onOpenReader: (String, String) -> Unit = { _, _ -> },
                 onOpenArtist: (String) -> Unit = {},
                 // 3.6.14：页头画师名长按改为「直接复制」（原 3.6.5 的操作菜单入口撤掉，
                 // 改名/合并改由搜索页画师卡封面长按唤出——卡片操作区一律在封面）。
                 onLongPressWork: (String, String, IntRect) -> Unit = { _, _, _ -> },
                 onOpenOriginal: (String) -> Unit = {},   // 3.7.51：原作标签可点进分区
                 // 3.6.152：页头「⬇ 下载全部」已下架（批量下载走长按操作栏），参数一并撤掉
                 onProbe: () -> Unit = {},   // 3.6.152 右上角「⛏ 联网获取」：按本画师名搜、勾选后自动归区
                 // 3.7.12 滚动位置跨返回保留：LazyGridState 由外层（MainActivity）按画师持存
                 gridState: LazyGridState = LazyGridState(),
                 reloadKey: Int = 0) {
    BackHandler { onBack() }
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope(); var data by remember(name) { mutableStateOf<Api.ArtistPage?>(null) }
    var error by remember(name) { mutableStateOf("") }
    var busy by remember(name) { mutableStateOf(false) }
    // 3.7.12 下拉刷新；3.7.66 复位挂加载完成回调——LaunchedEffect(data) 在数据结构相等时不重跑，箭头会卡死
    var refreshing by remember(name) { mutableStateOf(false) }
    fun load() {
        loadArtistPage(scope, name, { data = it; refreshing = false }, { error = it }) { busy = it }
    }
    // reloadKey：作品级改动（来自长按菜单的删除/删首页图）后由外层自增，据此重载去掉旧卡片
    LaunchedEffect(name, reloadKey) { load() }
    var worksAsc by remember(name) { mutableStateOf(false) }     // 3.7.40：作品排序方向（默认新→旧）
    // 3.6.151：排序维度 time / size / name（不带 key，换画师时沿用同一偏好）
    var worksSort by remember { mutableStateOf("time") }

    Column(Modifier.fillMaxSize()) {
        // 3.6.152：⛏ 联网获取 搬到页面右上角（规格同分区页「＋ 添加」）
        ArtistPageHeader(busy, onBack, onProbe)
        // 3.7.12 下拉刷新：列表顶部下拉重新拉取画师档案
        androidx.compose.material3.pulltorefresh.PullToRefreshBox(
            isRefreshing = refreshing,
            onRefresh = { refreshing = true; load() },
            modifier = Modifier.fillMaxSize()
        ) {
            ArtistContent(error, data, gridState, worksSort, worksAsc,
                onSort = { m, a -> worksSort = m; worksAsc = a },
                onOpenCircle = onOpenCircle, onOpenReader = onOpenReader,
                onOpenArtist = onOpenArtist, onLongPressWork = onLongPressWork,
                onOpenOriginal = onOpenOriginal, onProbe = onProbe,
                onFollow = { toggleFollow(scope, ctx, data!!.author, it, { b -> busy = b }) { load() } })
        }   // PullToRefreshBox（3.7.12）
    }
}

/** 拉取画师档案（3.7.43 提为模块级，原 ArtistScreen 局部函数 load 的主体）。 */
private fun loadArtistPage(scope: kotlinx.coroutines.CoroutineScope, name: String,
                           onLoaded: (Api.ArtistPage) -> Unit, onError: (String) -> Unit,
                           onBusy: (Boolean) -> Unit) {
    scope.launch {
        onBusy(true)
        try { onLoaded(withContext(Dispatchers.IO) { Api.artistPage(name) }) }
        catch (e: Exception) { onError(e.message ?: e.toString()) }
        onBusy(false)
    }
}

/** 喜爱/取消喜爱画师（toast 结果后重载；失败静默——重载会暴露真实状态）。 */
private fun toggleFollow(scope: kotlinx.coroutines.CoroutineScope, ctx: android.content.Context,
                         author: String, following: Boolean, onBusy: (Boolean) -> Unit,
                         onDone: () -> Unit) {
    scope.launch {
        onBusy(true)
        try {
            val msg = withContext(Dispatchers.IO) {
                if (following) Api.unfollow(author) else Api.follow(author)
            }
            android.widget.Toast.makeText(ctx, msg, android.widget.Toast.LENGTH_SHORT).show()
            onDone()
        } catch (e: Exception) { /* toast 失败静默重载 */ }
        onBusy(false)
    }
}

/** 画师页正文三态（3.6.151 从 ArtistScreen 抽出：原函数 53 行，超 50 行预算）。 */
@Composable
private fun ArtistContent(error: String, d: Api.ArtistPage?, gridState: LazyGridState,
                          worksSort: String, worksAsc: Boolean,
                          onSort: (String, Boolean) -> Unit, onOpenCircle: (String) -> Unit,
                          onOpenReader: (String, String) -> Unit, onOpenArtist: (String) -> Unit,
                          onLongPressWork: (String, String, IntRect) -> Unit,
                          onOpenOriginal: (String) -> Unit,
                          onProbe: () -> Unit, onFollow: (Boolean) -> Unit) {
    when {
        error.isNotEmpty() -> ArtistErrorBox(error)
        d == null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator(color = ACCENT2)
        }
        else -> ArtistGrid(d, gridState, worksSort, worksAsc, onSort, onOpenCircle, onFollow,
            onOpenReader, onOpenArtist, onLongPressWork, onOpenOriginal, onProbe)
    }
}

/** 画师页页头：返回 + 标题 + 忙碌指示（拉取/关注进行中）。 */
@Composable
private fun ArtistPageHeader(busy: Boolean, onBack: () -> Unit, onProbe: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("←", color = Color(0xFFF2EEFA), fontSize = 20.sp,
            modifier = Modifier.clickable { onBack() }.padding(end = 10.dp))
        Text("👤 " + AppI18n.s("画师档案"), color = Color(0xFFF2EEFA), fontSize = 18.sp, modifier = Modifier.weight(1f))
        // 3.6.152：右上角「⛏ 联网获取」，与分区页「＋ 添加」同一规格（TopChip）
        TopChip("⛏ " + AppI18n.s("联网获取"), onProbe)
        if (busy) CircularProgressIndicator(color = ACCENT2, strokeWidth = 2.dp,
            modifier = Modifier.size(16.dp).padding(start = 6.dp))
    }
}

/** 画师作品网格：页头卡（跨满）+ 作品卡（按首次入库时间排序，3.7.69 起）。 */
@Composable
private fun ArtistGrid(d: Api.ArtistPage, gridState: LazyGridState,
                       worksSort: String, worksAsc: Boolean,
                       onSort: (String, Boolean) -> Unit, onOpenCircle: (String) -> Unit,
                       onFollow: (Boolean) -> Unit, onOpenReader: (String, String) -> Unit,
                       onOpenArtist: (String) -> Unit,
                       onLongPressWork: (String, String, IntRect) -> Unit,
                       onOpenOriginal: (String) -> Unit = {},
                       onProbe: () -> Unit = {}) {
    LazyVerticalGrid(
        state = gridState,
        columns = GridCells.Adaptive(110.dp),
        contentPadding = PaddingValues(10.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.fillMaxSize()
    ) {
        item(span = { GridItemSpan(maxLineSpan) }) {
            ArtistHeaderCard(d, onOpenCircle, onFollow, worksSort, worksAsc, onSort)
        }
        // 3.7.69：排序键从 mtime 换成 addedAt（首次入库时间）——删首页图等重写操作会
        // 推进 mtime，作品错误顶到"最新"；added_at 修改不推进（0 值老数据兜底 mtime）
        items(sortWorksList(d.works, worksSort, worksAsc,
            { (if (it.addedAt > 0) it.addedAt else it.mtime).toDouble() },
            { it.size }, { it.work }),
            key = { it.key }) { w ->
            ArtistWorkCard(w, d.author, onOpenReader, onOpenCircle, onOpenArtist,
                onLongPress = { onLongPressWork(w.group, w.work, it) },
                onOpenOriginal = onOpenOriginal)
        }
    }
}

/** 画师页错误态：404 给面板版本提示，其余给加载失败。 */
@Composable
private fun ArtistErrorBox(error: String) {
    Box(Modifier.fillMaxSize().padding(24.dp), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(if (error.contains("404"))
                    AppI18n.s("画师档案需要面板 3.2.0 及以上\n(当前面板版本过旧或尚未重启)\n更新面板后即可正常打开")
                else AppI18n.sf("加载失败：%1", error),
                color = if (error.contains("404")) Color(0xFFFFC86B) else Color(0xFFFF5ED0),
                fontSize = 13.sp, lineHeight = 20.sp,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        }
    }
}

/**
 * 画师页头卡（网格首项，跨满）：封面 + 姓名/喜爱按钮 + 别名 + 社团聚合 + 作品数 + 排序。
 * 3.7.43 从 ArtistScreen 拆出（原页头 inline 58 行）。
 */
@Composable
private fun ArtistHeaderCard(d: Api.ArtistPage, onOpenCircle: (String) -> Unit,
                             onFollow: (Boolean) -> Unit,
                             worksSort: String, worksAsc: Boolean,
                             onSort: (String, Boolean) -> Unit) {
    Column {
        if (d.coverGroup != null && d.coverWork != null) {
            Box(Modifier.fillMaxWidth().height(132.dp).clip(RoundedCornerShape(10.dp))
                .background(Color(0xFF1C1433)).padding(bottom = 8.dp)) {
                AsyncImage(model = Api.coverUrl(d.coverGroup, d.coverWork, d.coverVer),
                    contentDescription = AppI18n.s("画师封面"), contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize())
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            // 3.7.21 需求1：画师页标题去长按复制；改名/合并菜单在搜索页画师卡封面长按。
            Text("👤 " + d.author, color = Color(0xFFF2EEFA), fontSize = 18.sp,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f))
            Text(if (d.isFollowing) "❤ " + AppI18n.s("已喜爱") else "🤍 " + AppI18n.s("喜爱"),
                color = if (d.isFollowing) ACCENT2 else Color(0xFF9A8FB8),
                fontSize = 13.sp,
                modifier = Modifier.clip(RoundedCornerShape(999.dp))
                    .background(if (d.isFollowing) ACCENT2.copy(alpha = 0x33 / 255f) else Color(0x1AFFFFFF))
                    .clickable { onFollow(d.isFollowing) }
                    .padding(horizontal = 14.dp, vertical = 7.dp))
        }
        if (d.aliases.isNotEmpty()) {
            Text(AppI18n.s("别名：") + d.aliases.joinToString("、"), color = Color(0xFF9A8FB8),
                fontSize = 11.sp, modifier = Modifier.padding(top = 4.dp))
        }
        if (d.circles.isNotEmpty()) {
            ArtistCircles(d.circles, onOpenCircle)
        }
        ArtistWorkActions(d.works.size, worksSort, worksAsc, onSort)
    }
}

/** 画师卡底部：作品数 + 排序条（3.6.151 抽出；3.6.152 起 ⛏爬取 移至页头右上角、
 *  ⬇下载全部 下架——批量下载走长按操作栏）。 */
@Composable
private fun ArtistWorkActions(count: Int, worksSort: String, worksAsc: Boolean,
                              onSort: (String, Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 2.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(AppI18n.sf("%1 部作品", count), color = Color(0xFF6E6787),
            fontSize = 10.sp, modifier = Modifier.weight(1f))
    }
    // 3.6.151：作品排序（时间 / 文件大小 / 名称），与社团页/原作分区页统一
    WorksSortBar(worksSort, worksAsc, onSort, Modifier.padding(bottom = 4.dp))
}

/** 画师的社团聚合行：🏢 社团名（作品数），点击进社团。 */
@Composable
private fun ArtistCircles(circles: List<Pair<String, Int>>, onOpenCircle: (String) -> Unit) {
    Row(Modifier.padding(top = 6.dp).horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        circles.forEach { (cname, n) ->
            // 3.7.21 需求1：画师页社团标签去长按复制（点击照旧进社团）
            Text("🏢 $cname（$n）", color = Color(0xFF9A8FB8), fontSize = 11.sp,
                modifier = Modifier.clip(RoundedCornerShape(999.dp))
                    .background(Color(0x1AFFFFFF))
                    .tagClickable(cname) { onOpenCircle(cname) }   // 3.7.40：长按复制
                    .padding(horizontal = 10.dp, vertical = 4.dp))
        }
    }
}

/**
 * 画师作品卡：封面（长按唤操作菜单）+ 作品名 + 合作画师/社团标签 + 入库日期。
 * 3.7.43 从 ArtistScreen 拆出（原卡片 inline 55 行）。
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ArtistWorkCard(w: Api.ArtistWork, author: String,
                           onOpenReader: (String, String) -> Unit, onOpenCircle: (String) -> Unit,
                           onOpenArtist: (String) -> Unit,
                           onLongPress: (IntRect) -> Unit,
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
            onClick = { onOpenReader(w.group, w.work) })) {
        Box(Modifier.fillMaxWidth().aspectRatio(3f / 4f)
            .background(Color(0xFF1C1433))
            .combinedClickable(
                onClick = { onOpenReader(w.group, w.work) },
                onLongClick = { onLongPress(cardRect) }),
            contentAlignment = Alignment.Center) {
            AsyncImage(model = Api.coverUrl(w.group, w.work),
                contentDescription = w.work, contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize())
        }
        Column(Modifier.padding(8.dp)) {
            Text(w.work, color = Color(0xFFF2EEFA), fontSize = 12.sp,
                maxLines = 2, overflow = TextOverflow.Ellipsis)
            // 3.6.14：画师标签 + 社团标签进卡片下方（点击跳转、长按直接复制名称）；
            // 社团名用归一的 circle（目录名≠圈子名时展示圈子名，与社团浏览一致）。
            ArtistWorkTags(w, author, onOpenCircle, onOpenArtist, onOpenOriginal)
            if (w.addedAt > 0) {
                Text(AppI18n.sf("📥 %1 入库", java.text.SimpleDateFormat("yy-MM-dd", java.util.Locale.US)
                    .format(java.util.Date(w.addedAt * 1000))),
                    color = Color(0xFF6E6787), fontSize = 10.sp, maxLines = 1,
                    overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

/** 画师作品卡标签行：合作画师（不含本画师）+ 社团；点击跳转、长按复制。 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ArtistWorkTags(w: Api.ArtistWork, author: String,
                           onOpenCircle: (String) -> Unit, onOpenArtist: (String) -> Unit,
                           onOpenOriginal: (String) -> Unit = {}) {
    Row(Modifier.padding(top = 4.dp)
        .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        // 3.6.15 需求3：本画师标签不显示，仅渲染合作画师（合作作品多人各一个）
        val cname = if (w.circle.isNotEmpty()) w.circle else w.group
        val collabs = w.personals.filter { it != author }
        collabs.forEach { a ->
            Text("👤 " + a, color = ACCENT2, fontSize = 10.sp,
                maxLines = 1,
                modifier = Modifier.clip(RoundedCornerShape(999.dp))
                    .background(Color(0x1AFFFFFF))
                    .tagClickable(a) { onOpenArtist(a) }   // 3.7.41：长按复制
                    .padding(horizontal = 8.dp, vertical = 3.dp))
        }
        Text("🏢 " + cname, color = Color(0xFF9A8FB8), fontSize = 10.sp,
            maxLines = 1,
            modifier = Modifier.clip(RoundedCornerShape(999.dp))
                .background(Color(0x1AFFFFFF))
                .tagClickable(cname) { onOpenCircle(cname) }   // 3.7.41：长按复制
                .padding(horizontal = 8.dp, vertical = 3.dp))
        // 3.7.51：原作标签（任何分区都显示）
        WorkOriginalsRow(w.originals, onOpenOriginal)
    }
}
