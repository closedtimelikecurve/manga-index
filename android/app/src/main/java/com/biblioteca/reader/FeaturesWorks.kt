package com.biblioteca.reader

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
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyGridState
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
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
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext


/* ================================================================
   作品网格族（3.7.43 从 Features.kt 拆出）：
   WorksHitGrid（标签/搜索共用网格）/ SearchScreen / TagWorksScreen。
   ================================================================ */

/** 标签检索 / 搜索共用的作品网格（带所属社团行，点击进阅读器）
 * 3.6.19 #19：原作分区页补齐基础配套设施——封面长按操作菜单、已读角标、
 * 合作画师可点标签（默认关闭，搜索页行为不变）。 */
@OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)
@Composable
fun WorksHitGrid(hits: List<Api.WorkHit>, onOpenReader: (String, String) -> Unit,
                 // 3.7.12 滚动位置跨返回保留：由调用页（搜索/标签页）持存
                 gridState: LazyGridState = LazyGridState(),
                 onLongPressWork: (String, String, IntRect) -> Unit = { _, _, _ -> },
                 showBadges: Boolean = false,
                 showAuthors: Boolean = false,
                 onOpenArtist: (String) -> Unit = {},
                 // 3.6.27 需求4：作品卡上的原作标签可点进该原作分区
                 onOpenOriginal: (String) -> Unit = {},
                 // 3.7.22 #24：网格头部插槽（原作分区封面横幅+说明）——随网格一起滚动，
                 // 与画师页/社团页同规格（封面是 LazyGrid 首 item，不是 Column 固定块）
                 header: (@Composable () -> Unit)? = null) {
    LazyVerticalGrid(
        state = gridState,
        columns = GridCells.Adaptive(110.dp),
        contentPadding = PaddingValues(10.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.fillMaxSize()
    ) {
        if (header != null) {
            item(span = { GridItemSpan(maxLineSpan) }) { header() }
        }
        items(hits, key = { it.group + "/" + it.work.name }) { h ->
            WorkHitCard(h, onOpenReader, onLongPressWork, showBadges, showAuthors,
                onOpenArtist, onOpenOriginal)
        }
    }
}

/**
 * 作品卡（3.7.43 从 WorksHitGrid 的 items() lambda 拆出，原函数 82 行）：
 * 封面（长按唤操作菜单）+ 名称 + 社团标签（长按复制）+ 可选合作画师/原作标签。
 */
@OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)
@Composable
private fun WorkHitCard(h: Api.WorkHit, onOpenReader: (String, String) -> Unit,
                        onLongPressWork: (String, String, IntRect) -> Unit,
                        showBadges: Boolean, showAuthors: Boolean,
                        onOpenArtist: (String) -> Unit, onOpenOriginal: (String) -> Unit) {
    var cardRect by remember { mutableStateOf(IntRect.Zero) }
    Column(Modifier
        .onGloballyPositioned { p ->
            cardRect = IntRect(
                p.positionInRoot().x.toInt(), p.positionInRoot().y.toInt(),
                (p.positionInRoot().x + p.size.width).toInt(),
                (p.positionInRoot().y + p.size.height).toInt())
        }
        .clip(RoundedCornerShape(10.dp))
        .background(CARD_BG)
        .clickable { onOpenReader(h.group, h.work.name) }) {
        // 3.6.19：封面区长按唤出卡片操作菜单（与社团/画师页同规则；整卡点击仍走外层）
        Box(Modifier.fillMaxWidth().aspectRatio(3f / 4f).background(CARD_BG2)
            .combinedClickable(
                onClick = { onOpenReader(h.group, h.work.name) },
                onLongClick = { onLongPressWork(h.group, h.work.name, cardRect) }),
            contentAlignment = Alignment.Center) {
            if (h.work.hasCover) {
                AsyncImage(
                    model = Api.coverUrl(h.group, h.work.name),
                    contentDescription = h.work.name,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize())
            } else Text("📄", fontSize = 30.sp)
            if (showBadges) ReadingBadges(h.group, h.work.name)
        }
        Column(Modifier.padding(8.dp)) {
            Text(h.work.name.dispWorkName(), color = TXT, fontSize = 12.sp,
                maxLines = 2, overflow = TextOverflow.Ellipsis)
            val circleTag = if (h.work.circle.isNotEmpty()) h.work.circle else h.group
            Text("🏢 " + circleTag,
                color = MUTED, fontSize = 10.sp,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.tagCopy(circleTag))
            // 3.6.19：合作画师可点标签（点击进画师档案；仅原作分区页开启）
            if (showAuthors) WorkCardPersonals(h, onOpenArtist)
            // 3.6.27 需求4：作品卡下方显示原作标签（可点进该原作分区）
            WorkCardOriginals(h, onOpenOriginal)
        }
    }
}

/** 作品卡的合作画师标签行（3.7.48 从 WorkHitCard 抽出）。 */
@Composable
private fun WorkCardPersonals(h: Api.WorkHit, onOpenArtist: (String) -> Unit) {
    h.work.authors.forEach { a ->
        Text("👤 $a", color = ACCENT2, fontSize = 10.sp,
            maxLines = 1,
            modifier = Modifier.clip(RoundedCornerShape(999.dp))
                .background(Color(0x1AFFFFFF))
                .tagClickable(a) { onOpenArtist(a) }
                .padding(horizontal = 6.dp, vertical = 2.dp))
    }
}

/** 原作标签行（3.7.51 提为公共组件）：**任何分区的作品卡**都该显示原作标签。
 *  此前只有原作分区页有，因为只有那边的数据带 tags；服务端现已随画师 / 续读接口
 *  下发 originals，社团页 / 画师页 / 续读页统一调用本组件。 */
@Composable
fun WorkOriginalsRow(originals: List<String>, onOpenOriginal: (String) -> Unit) {
    originals.forEach { o ->
        Text("🎴 $o", color = Color(0xFF7FD4FF), fontSize = 10.sp,
            maxLines = 1, overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(top = 2.dp)
                .clip(RoundedCornerShape(999.dp))
                .background(Color(0x1A4FC3F7))
                .tagClickable(o) { onOpenOriginal(o) }
                .padding(horizontal = 6.dp, vertical = 2.dp))
    }
}

@Composable
private fun WorkCardOriginals(h: Api.WorkHit, onOpenOriginal: (String) -> Unit) =
    WorkOriginalsRow(h.work.originals, onOpenOriginal)


/* ---------------- 标签检索结果页 ---------------- */
@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun TagWorksScreen(type: String, tag: String, onBack: () -> Unit,
                   onOpenReader: (String, String) -> Unit,
                   onOpenArtist: (String) -> Unit = {},
                   // 3.6.27 需求3：头部社团标签可点进社团（对齐画师页头部）
                   onOpenCircle: (String) -> Unit = {},
                   // 3.6.27 需求4：作品卡上的原作标签可点进该原作分区
                   onOpenOriginal: (String) -> Unit = {},
                   // 3.6.19 #19：分区封面横幅（原作 zone 用；传入即渲染）
                   cover: Api.CircleCover? = null,
                   // 3.6.19 #19：作品卡长按唤出操作菜单（增补信息/下载/设为封面/删除…）
                   onLongPressWork: (String, String, IntRect) -> Unit = { _, _, _ -> },
                   // 3.7.27 外部强制重载键：设分区封面/删作品后由 MainActivity 的
                   // screenReload 驱动重新拉列表（此前只有 type/tag 变化才重载）。
                   reloadKey: Int = 0,
                   // 3.6.152：页头「⬇ 下载全部」已下架（批量下载走长按操作栏），
                   // 参数一并撤掉——留着是死接线，调用方会以为这个入口还在。
                   onProbe: (() -> Unit)? = null,   // 3.6.152：搬到右上角（与「＋ 添加」同规格）
                   gridState: LazyGridState = LazyGridState()) {
    var hits by remember(type, tag) { mutableStateOf<List<Api.WorkHit>?>(null) }   // 必须按分区键控
    var worksAsc by remember(type, tag) { mutableStateOf(false) }   // 3.7.40：排序方向（默认新→旧）
    // 3.6.151：排序维度 time / size / name。**不带 key**——切分区时沿用同一偏好，
    // 查重时逐个社团翻页比较大小，每换一个分区都要重选一次会非常难用。
    var worksSort by remember { mutableStateOf("time") }
    var error by remember(type, tag) { mutableStateOf("") }
    // 3.6.36 #33：分区内手动添加作品对话框（原作分区专用）
    var showAddWorks by remember(type, tag) { mutableStateOf(false) }
    // 3.6.41：本分区的「旧名」（原作别名）——显示成 chip，点 × 直接删。
    var oldAliases by remember(type, tag) { mutableStateOf<List<String>>(emptyList()) }
    var refreshing by remember(type, tag) { mutableStateOf(false) }  // 3.7.12 下拉刷新
    val scope = rememberCoroutineScope()
    LaunchedEffect(type, tag, reloadKey) {
        tagWorksLoad(scope, type, tag, { hits = it }, { error = it }, { oldAliases = it },
            onDone = { refreshing = false })   // 3.7.66 完成拍复位，数据相等也能收箭头
    }
    BackHandlerOn(onBack)
    Column(Modifier.fillMaxSize()) {
        TagWorksTopRow(type, tag, onBack, onOpenArtist, { showAddWorks = true }, onProbe)
        TagWorksContent(type, tag, cover, oldAliases, hits, error, refreshing,
            worksSort, worksAsc, gridState, onRefresh = { refreshing = true },
            onSortChange = { m, a -> worksSort = m; worksAsc = a },
            onOpenArtist = onOpenArtist, onOpenCircle = onOpenCircle,
            onOpenReader = onOpenReader,
            onLongPressWork = onLongPressWork, onOpenOriginal = onOpenOriginal)
        if (showAddWorks && type == "original") {        // 3.6.36 #33 手动添加作品
            AddWorksDialog(zone = tag, onDismiss = { showAddWorks = false },
                onAdded = { showAddWorks = false; refreshing = true })
        }
    }
}

/** 分区页正文 + 头部 lambda（3.6.151 从 TagWorksScreen 抽出：原函数 55 行，超预算）。 */
@Composable
private fun TagWorksContent(type: String, tag: String, cover: Api.CircleCover?,
                            oldAliases: List<String>, hits: List<Api.WorkHit>?, error: String,
                            refreshing: Boolean, worksSort: String, worksAsc: Boolean,
                            gridState: LazyGridState, onRefresh: () -> Unit,
                            onSortChange: (String, Boolean) -> Unit,
                            onOpenArtist: (String) -> Unit, onOpenCircle: (String) -> Unit,
                            onOpenReader: (String, String) -> Unit,
                            onLongPressWork: (String, String, IntRect) -> Unit,
                            onOpenOriginal: (String) -> Unit) {
    TagWorksBody(
        refreshing = refreshing, onRefresh = onRefresh, error = error, hits = hits,
        header = {
            TagWorksHeaderBox(type, tag, cover, oldAliases, hits, worksSort, worksAsc,
                onOpenArtist, onOpenCircle, onSort = onSortChange)
        },
        onOpenReader = onOpenReader, gridState = gridState,
        onLongPressWork = onLongPressWork, onOpenArtist = onOpenArtist,
        onOpenOriginal = onOpenOriginal, worksSort = worksSort, worksAsc = worksAsc)
}

/** 拉取标签作品 + 旧名别名（3.7.46 抽出：合并原 load() 与 oldAliases 两个 LaunchedEffect）。
 *
 *  3.7.63 两条规矩：
 *   * 调用方对本函数的页面状态必须 `remember(type, tag)`——Compose 会把同一组合位置复用给
 *     不同分区，裸 `remember{}` 会留下"新分区的滚动状态 + 旧分区的作品列表"，列表变短时
 *     索引被钳到 0，用户看到"莫名刷新并回到顶部"；
 *   * `refreshing` 不能进 LaunchedEffect 的键：下拉把它写成 true 触发一次、拉完复位 false
 *     又触发一次，等于每次下拉多跑一趟。3.7.66 起复位也不挂在 LaunchedEffect(hits) 上——
 *     刷新后 hits 结构相等时该 effect 不会重跑，箭头会永远卡在转圈态；改挂 onDone 完成拍。 */
private fun tagWorksLoad(scope: CoroutineScope, type: String, tag: String,
                         onHits: (List<Api.WorkHit>?) -> Unit,
                         onError: (String) -> Unit,
                         onOldAliases: (List<String>) -> Unit,
                         onDone: () -> Unit = {}) {
    scope.launch {
        onError("")
        try {
            onHits(withContext(Dispatchers.IO) { Api.tagWorks(type, tag) })
            onOldAliases(if (type != "original") emptyList() else runCatching {
                withContext(Dispatchers.IO) { Api.aliasList("original") }
                    .filterValues { it == tag }.keys.toList()
            }.getOrDefault(emptyList()))
        } catch (e: Exception) { onError(e.message ?: e.toString()) }
        onDone()
    }
}

/** 标签页头部（3.7.46 抽出 header lambda）：封面横幅 + 旧名 chip + 排序条。 */
@Composable
private fun TagWorksHeaderBox(type: String, tag: String, cover: Api.CircleCover?,
                              oldAliases: List<String>, hits: List<Api.WorkHit>?,
                              worksSort: String, worksAsc: Boolean, onOpenArtist: (String) -> Unit,
                              onOpenCircle: (String) -> Unit,
                              onSort: (String, Boolean) -> Unit) {
    TagWorksHeader(type, tag, cover, oldAliases, hits, worksSort, worksAsc,
        onSort = onSort, onOpenArtist = onOpenArtist, onOpenCircle = onOpenCircle)
}

/** 标签页主体（3.7.46 从 TagWorksScreen 拆出）：下拉刷新 + 四态
 *  （检索失败 / 加载中 / 无结果 / 作品网格）。原函数 84 行超当时预算（80 行；现标准 50 行）。 */
@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
private fun TagWorksBody(
    refreshing: Boolean, onRefresh: () -> Unit,
    error: String, hits: List<Api.WorkHit>?,
    header: @Composable () -> Unit,
    onOpenReader: (String, String) -> Unit,
    gridState: LazyGridState,
    onLongPressWork: (String, String, IntRect) -> Unit,
    onOpenArtist: (String) -> Unit,
    onOpenOriginal: (String) -> Unit,
    worksSort: String,
    worksAsc: Boolean
) {
    androidx.compose.material3.pulltorefresh.PullToRefreshBox(
        isRefreshing = refreshing,
        onRefresh = onRefresh,
        modifier = Modifier.fillMaxSize()
    ) {
        when {
            error.isNotEmpty() ->
                SearchHint { Text(AppI18n.sf("检索失败：%1", error), color = ERR, fontSize = 13.sp) }
            hits == null -> SearchHint { CircularProgressIndicator(color = ACCENT) }
            hits.isEmpty() ->
                SearchHint { Text(AppI18n.s("没有含该标签的作品"), color = MUTED, fontSize = 13.sp) }
            else -> WorksHitGrid(
                // 3.6.151：时间 / 文件大小 / 名称三档（3.7.69 起时间用 addedAt，删首页图等
                // 重写操作会推进 mtime，作品会错误顶到"最新"；0 值老数据兜底 mtime）
                sortWorksList(hits, worksSort, worksAsc,
                    { (if (it.work.addedAt > 0) it.work.addedAt else it.work.mtime) },
                    { it.work.size },
                    { it.work.name }),
                onOpenReader, gridState = gridState,
                onLongPressWork = onLongPressWork,
                showBadges = true, showAuthors = true, onOpenArtist = onOpenArtist,
                onOpenOriginal = onOpenOriginal,
                header = header)
        }
    }
}

/** 标签页顶部行（3.7.43 拆出）：返回 + 页面标识 + 右上角入口（＋添加 / ⛏联网获取 / 画师档案）。
 *
 *  3.6.152（用户需求④）：分区页的「⛏ 联网获取」从页头作品数那一行搬到**右上角**，
 *  与「＋ 添加」同一套胶囊规格（[TopChip]）——两个入口挨着，位置和样式都是"页面级动作"。 */
@Composable
private fun TagWorksTopRow(type: String, tag: String, onBack: () -> Unit,
                           onOpenArtist: (String) -> Unit, onAdd: () -> Unit,
                           onProbe: (() -> Unit)?) {
    Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("←", color = TXT, fontSize = 20.sp,
            modifier = Modifier.clickable { onBack() }.padding(end = 10.dp))
        // 3.6.36 #32：对齐画师页——顶部行只放页面标识，分区名移到封面下方大字
        Text(if (type == "original") AppI18n.s("🎴 同人分区") else "🏷 " + (tagLabels()[type] ?: type),
            color = TXT, fontSize = 18.sp, modifier = Modifier.weight(1f))
        if (type == "original") {
            // 3.6.36 #33：手动添加作品（右上角）
            TopChip(AppI18n.s("＋ 添加"), onAdd)
        }
        if (onProbe != null) {
            Spacer(Modifier.width(6.dp))
            TopChip("⛏ " + AppI18n.s("联网获取"), onProbe)
        }
        if (type == "personal") {
            Text(AppI18n.s("📖 画师档案"), color = ACCENT, fontSize = 13.sp,
                modifier = Modifier.clickable { onOpenArtist(tag) }.padding(start = 8.dp))
        }
    }
}

/**
 * 标签页网格头（3.7.43 从 TagWorksScreen 拆出）：封面横幅 + 分区名大字 +
 * 旧名 chips + 画师/社团聚合行 + 作品数 + 排序 chip。
 */
@Composable
private fun TagWorksHeader(type: String, tag: String, cover: Api.CircleCover?,
                           oldAliases: List<String>, hits: List<Api.WorkHit>?,
                           worksSort: String, worksAsc: Boolean,
                           onSort: (String, Boolean) -> Unit,
                           onOpenArtist: (String) -> Unit, onOpenCircle: (String) -> Unit) {
    Column {
        if (cover?.coverGroup != null && !cover.coverWork.isNullOrEmpty()) {
            Box(Modifier.fillMaxWidth().height(132.dp).clip(RoundedCornerShape(10.dp))
                .background(Color(0xFF1C1433)).padding(bottom = 8.dp)) {
                AsyncImage(model = Api.coverUrl(cover.coverGroup, cover.coverWork, cover.coverVer),
                    contentDescription = AppI18n.s("分区封面"), contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize())
            }
            Spacer(Modifier.height(4.dp))
        }
        // 3.6.36 #32：分区名大字置于封面下方（画师页同规格：
        // 画师名在封面下、与返回键分离），替代原来与返回键并列的小字
        if (type == "original") {
            Text("🎴 $tag", color = TXT, fontSize = 18.sp,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(top = 6.dp))
            // 3.7.41：旧名（别名）只作**展示标签**——不跳转、不带删除叉，长按可复制。
            // 3.6.41 在这里加的 × 是误解了需求（用户要的是「改名输入框右侧的清空叉」），
            // 已移到改名对话框里；别名本身要能在改名后核对/复制，而不是在这儿删。
            if (oldAliases.isNotEmpty()) TagWorksOldNames(oldAliases)
        }
        // 3.6.27 需求3：头部对齐画师页——封面下方给本分区的**画师标签 + 社团标签**
        // （点击分别进画师档案 / 社团页）。原作分区没有画师页那个"喜爱"键，其余规格一致。
        if (hits != null && hits.isNotEmpty()) {
            TagWorksAggRow(hits, onOpenArtist, onOpenCircle)
        }
        // 3.6.19 #19：分区作品数（3.7.54 抽成 TagWorksCountRow，函数行数预算）
        if (hits != null) {
            // 3.6.152：⛏ 联网获取 已搬到右上角（TagWorksTopRow）；
            // ⬇ 下载全部 已下架——批量下载本来就在长按操作栏里（用户需求③）。
            TagWorksCountRow(hits)
            WorksSortBar(worksSort, worksAsc, onSort)
        }
    }
}

/** 分区页头的「N 部作品」一行（3.7.54 抽出；3.6.152 起只剩计数——⛏爬取 移到右上角、
 *  ⬇下载全部 下架，两者都不再占这一行）。 */
@Composable
private fun TagWorksCountRow(hits: List<Api.WorkHit>) {
    Row(Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 2.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(AppI18n.sf("%1 部作品", hits.size), color = MUTED, fontSize = 10.sp, modifier = Modifier.weight(1f))
    }
}

/** 原作分区的旧名（别名）展示标签行（3.7.48 从 TagWorksHeader 抽出）。 */
@Composable
private fun TagWorksOldNames(oldAliases: List<String>) {
    Row(Modifier.padding(top = 6.dp)
        .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(AppI18n.s("旧名"), color = MUTED, fontSize = 10.sp)
        oldAliases.forEach { a ->
            Text(a, color = Color(0xFF9A8FB8), fontSize = 10.sp,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.clip(RoundedCornerShape(999.dp))
                    .background(Color(0x1AFFFFFF))
                    .tagCopy(a)
                    .padding(horizontal = 8.dp, vertical = 3.dp))
        }
    }
}

/** 分区页头聚合行（3.7.43 拆出）：画师标签 + 社团标签（各带作品数，可点）。 */
@Composable
private fun TagWorksAggRow(hits: List<Api.WorkHit>, onOpenArtist: (String) -> Unit,
                           onOpenCircle: (String) -> Unit) {
    val authorCount = LinkedHashMap<String, Int>()
    val circleCount = LinkedHashMap<String, Int>()
    hits.forEach { h ->
        h.work.authors.forEach { a -> authorCount[a] = (authorCount[a] ?: 0) + 1 }
        val c = if (h.work.circle.isNotEmpty()) h.work.circle else h.group
        if (c.isNotEmpty()) circleCount[c] = (circleCount[c] ?: 0) + 1
    }
    Row(Modifier.padding(top = 6.dp).horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        authorCount.forEach { (a, n) ->
            Text("👤 $a（$n）", color = ACCENT2, fontSize = 11.sp,
                maxLines = 1,
                modifier = Modifier.clip(RoundedCornerShape(999.dp))
                    .background(Color(0x1AFFFFFF))
                    .tagClickable(a) { onOpenArtist(a) }
                    .padding(horizontal = 10.dp, vertical = 4.dp))
        }
        circleCount.forEach { (c, n) ->
            Text("🏢 $c（$n）", color = Color(0xFF9A8FB8), fontSize = 11.sp,
                maxLines = 1,
                modifier = Modifier.clip(RoundedCornerShape(999.dp))
                    .background(Color(0x1AFFFFFF))
                    .tagClickable(c) { onOpenCircle(c) }
                    .padding(horizontal = 10.dp, vertical = 4.dp))
        }
    }
}
