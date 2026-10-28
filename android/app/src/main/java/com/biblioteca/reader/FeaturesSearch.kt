package com.biblioteca.reader

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

/* ---------------- 搜索页 ---------------- */
@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun SearchScreen(onBack: () -> Unit,
                 onOpenCircle: (String) -> Unit,
                 onOpenReader: (String, String) -> Unit,
                 // 3.7.12 滚动位置跨返回保留
                 gridState: LazyGridState = LazyGridState()) {
    var q by remember { mutableStateOf("") }
    var searching by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf("") }
    var groups by remember { mutableStateOf<List<Api.Group>>(emptyList()) }
    var works by remember { mutableStateOf<List<Api.WorkHit>>(emptyList()) }
    val scope = rememberCoroutineScope()

    // 3.7.12 下拉刷新（重跑当前关键词的检索）；3.7.66 复位挂 doSearchImpl 收尾回调
    // （onSearching(false) 必达）——结果结构相等时 LaunchedEffect(数据) 不重跑，箭头会卡死
    var refreshing by remember { mutableStateOf(false) }
    fun doSearch(query: String) {
        doSearchImpl(scope, query, { searching = it; if (!it) refreshing = false },
            { error = it }, { groups = it }, { works = it })
    }

    LaunchedEffect(q) {
        if (q.isNotBlank()) {
            delay(300)   // 防抖
            doSearch(q.trim())
        }
    }
    BackHandlerOn(onBack)
    // 3.7.12 下拉刷新：任何界面都能下拉（重跑当前关键词的检索）
    Column(Modifier.fillMaxSize()) {
        TopBar("🔍 " + AppI18n.s("搜索"), onBack)
        OutlinedTextField(q, { q = it }, label = { Text(AppI18n.s("搜索社团 / 作品 / 画师 / 标签")) },
            singleLine = true, colors = appFieldColors(),
            modifier = Modifier.fillMaxWidth().padding(12.dp, 0.dp))
        // 3.7.12 下拉刷新：列表顶部下拉重跑检索
        androidx.compose.material3.pulltorefresh.PullToRefreshBox(
            isRefreshing = refreshing,
            onRefresh = { if (q.isNotBlank()) { refreshing = true; doSearch(q.trim()) } },
            modifier = Modifier.fillMaxSize()
        ) {
            when {
                searching -> SearchHint { CircularProgressIndicator(color = ACCENT) }
                error.isNotEmpty() -> SearchHint { Text(AppI18n.sf("搜索失败：%1", error), color = ERR, fontSize = 13.sp) }
                q.isBlank() -> SearchHint { Text(AppI18n.s("输入关键词开始搜索（空格分隔多个词）"), color = MUTED, fontSize = 13.sp) }
                groups.isEmpty() && works.isEmpty() ->
                    SearchHint { Text(AppI18n.s("没有匹配的结果"), color = MUTED, fontSize = 13.sp) }
                else -> SearchResults(groups, works, gridState, onOpenCircle, onOpenReader)
            }
        }
    }
}

/** 搜索结果网格（3.7.43 从 SearchScreen 拆出）：社团卡 + 作品卡两个分区。
 *  提示盒 SearchHint 已移到 FeaturesCommon.kt —— 标签检索页同样用它显示
 *  「加载中 / 检索失败 / 没有作品」，不是搜索页私有。 */
@Composable
private fun SearchResults(groups: List<Api.Group>, works: List<Api.WorkHit>,
                          gridState: LazyGridState, onOpenCircle: (String) -> Unit,
                          onOpenReader: (String, String) -> Unit) {
    LazyVerticalGrid(
        state = gridState,
        columns = GridCells.Adaptive(110.dp),
        contentPadding = PaddingValues(10.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.fillMaxSize()
    ) {
        if (groups.isNotEmpty()) {
            item(span = { GridItemSpan(maxLineSpan) }) {
                Text(AppI18n.sf("🏢 社团（%1）", groups.size), color = MUTED, fontSize = 12.sp,
                    modifier = Modifier.padding(2.dp, 4.dp))
            }
        }
        items(groups, key = { "g" + it.name }) { g ->
            SearchGroupCard(g, onOpenCircle)
        }
        if (works.isNotEmpty()) {
            item(span = { GridItemSpan(maxLineSpan) }) {
                Text(AppI18n.sf("📚 作品（%1）", works.size), color = MUTED, fontSize = 12.sp,
                    modifier = Modifier.padding(2.dp, 4.dp))
            }
        }
        items(works, key = { "w" + it.group + "/" + it.work.name }) { h ->
            SearchWorkCard(h, onOpenReader)
        }
    }
}

/** 搜索结果社团卡：封面 + 社团名 + 作品数，点击进社团页。 */
@Composable
private fun SearchGroupCard(g: Api.Group, onOpenCircle: (String) -> Unit) {
    Column(Modifier
        .clip(RoundedCornerShape(10.dp))
        .background(CARD_BG)
        .clickable { onOpenCircle(g.name) }) {
        Box(Modifier.fillMaxWidth().aspectRatio(3f / 4f).background(CARD_BG2),
            contentAlignment = Alignment.Center) {
            if (g.hasCover) {
                AsyncImage(model = Api.coverUrl(g.name, g.coverWork),
                    contentDescription = g.name, contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize())
            } else Text("📦", fontSize = 30.sp)
        }
        Column(Modifier.padding(8.dp)) {
            Text(g.name, color = TXT, fontSize = 12.sp,
                maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(AppI18n.sf("%1 部", g.workCount), color = MUTED, fontSize = 10.sp)
        }
    }
}

/** 搜索结果作品卡：封面 + 名称 + 社团标签（3.7.40 起长按复制）。 */
@Composable
private fun SearchWorkCard(h: Api.WorkHit, onOpenReader: (String, String) -> Unit) {
    Column(Modifier
        .clip(RoundedCornerShape(10.dp))
        .background(CARD_BG)
        .clickable { onOpenReader(h.group, h.work.name) }) {
        Box(Modifier.fillMaxWidth().aspectRatio(3f / 4f).background(CARD_BG2),
            contentAlignment = Alignment.Center) {
            if (h.work.hasCover) {
                AsyncImage(model = Api.coverUrl(h.group, h.work.name),
                    contentDescription = h.work.name, contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize())
            } else Text("📄", fontSize = 30.sp)
        }
        Column(Modifier.padding(8.dp)) {
            Text(h.work.name.dispWorkName(), color = TXT, fontSize = 12.sp,
                maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text("🏢 ${h.group}", color = MUTED, fontSize = 10.sp,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.tagCopy(h.group))   // 3.7.40：长按复制
        }
    }
}

/** 执行检索（3.7.48 从 SearchScreen 的 doSearch 抽出为文件级实现）。 */
private fun doSearchImpl(scope: CoroutineScope, query: String,
                        onSearching: (Boolean) -> Unit, onError: (String) -> Unit,
                        onGroups: (List<Api.Group>) -> Unit, onWorks: (List<Api.WorkHit>) -> Unit) {
    scope.launch {
        onSearching(true); onError("")
        try {
            val (gs, ws) = withContext(Dispatchers.IO) { Api.search(query) }
            onGroups(gs); onWorks(ws)
        } catch (e: Exception) { onError(e.message ?: e.toString()) }
        onSearching(false)
    }
}