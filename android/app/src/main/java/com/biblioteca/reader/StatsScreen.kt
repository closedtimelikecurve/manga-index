package com.biblioteca.reader

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/* ================================================================
   APP 3.1.0：个人统计页
   3.7.43 从 Screens31.kt 拆出（原 StatsScreen 129 行 / cc 15）：
   屏壳（状态+拉取+下拉刷新）/ 总览 / 喜爱画师 / 增长曲线 / Top10。
   ================================================================ */

@Composable
@OptIn(ExperimentalFoundationApi::class, androidx.compose.material3.ExperimentalMaterial3Api::class)
fun StatsScreen(onBack: () -> Unit, onOpenArtist: (String) -> Unit = {},
                // 3.7.12 滚动位置跨返回保留（整页 verticalScroll，state 由外层持存）
                scrollState: ScrollState = rememberScrollState()) {
    BackHandler { onBack() }
    var stats by remember { mutableStateOf<Api.StatsOverview?>(null) }
    var follows by remember { mutableStateOf<List<Api.FollowItem>>(emptyList()) }
    var error by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    // 3.7.12 下拉刷新：任何界面都能下拉
    // 3.7.66 复位挂加载完成点——LaunchedEffect(stats) 在数据结构相等时不重跑，箭头会卡死
    var refreshing by remember { mutableStateOf(false) }
    fun reloadStats() {
        scope.launch {
            try {
                stats = withContext(Dispatchers.IO) { Api.statsOverview() }
                follows = try { withContext(Dispatchers.IO) { Api.follows() } } catch (_: Exception) { emptyList() }
            }
            catch (e: Exception) { error = e.message ?: e.toString() }
            refreshing = false   // 3.7.66 成功失败都收尾
        }
    }
    LaunchedEffect(Unit) { reloadStats() }
    // 3.7.12 外层 PTR；内容仍是整页 verticalScroll 的 Column
    androidx.compose.material3.pulltorefresh.PullToRefreshBox(
        isRefreshing = refreshing,
        onRefresh = { refreshing = true; reloadStats() },
        modifier = Modifier.fillMaxSize()
    ) {
    Column(Modifier.fillMaxSize()
        .verticalScroll(scrollState)) {
        Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("←", color = Color(0xFFF2EEFA), fontSize = 20.sp,
                modifier = Modifier.clickable { onBack() }.padding(end = 10.dp))
            Text("📊 " + AppI18n.s("个人统计"), color = Color(0xFFF2EEFA), fontSize = 18.sp)
        }
        when {
            error.isNotEmpty() -> Box(Modifier.fillMaxWidth().padding(40.dp), contentAlignment = Alignment.Center) {
                Text(AppI18n.sf("加载失败：%1", error), color = Color(0xFFFF5ED0), fontSize = 13.sp)
            }
            stats == null -> Box(Modifier.fillMaxWidth().padding(40.dp), contentAlignment = Alignment.Center) {
                Text(AppI18n.s("加载中…"), color = Color(0xFF9A8FB8), fontSize = 13.sp)
            }
            else -> StatsOverview(stats!!, follows, onOpenArtist)
        }
    }
    }   // PullToRefreshBox（3.7.12）
}

/** 统计总览：喜爱画师 + 六卡数字 + 入库增长曲线 + 最常看画师 Top10。 */
@Composable
private fun StatsOverview(s: Api.StatsOverview, follows: List<Api.FollowItem>,
                          onOpenArtist: (String) -> Unit) {
    // 3.2 关注的画师：新作品计数（浏览档案页即清零）
    if (follows.isNotEmpty()) {
        StatsFollows(follows, onOpenArtist)
        Spacer(Modifier.height(8.dp))
    }
    Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        StatCard("📚 " + AppI18n.s("作品"), "${s.works}", Modifier.weight(1f))
        StatCard("📄 " + AppI18n.s("页数"), "${s.pages}", Modifier.weight(1f))
        StatCard("🏢 " + AppI18n.s("社团"), "${s.circles}", Modifier.weight(1f))
    }
    Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        StatCard("✅ " + AppI18n.s("已读"), "${s.finished}", Modifier.weight(1f))
        StatCard("📖 " + AppI18n.s("在读"), "${s.started}", Modifier.weight(1f))
        StatCard("⭐ " + AppI18n.s("收藏"), "${s.favorites}", Modifier.weight(1f))
    }
    // 入库增长曲线（最近 90 天，柱状）
    if (s.byDay.isNotEmpty()) StatsGrowthChart(s.byDay)
    // 最常看画师 Top10
    if (s.topAuthors.isNotEmpty()) StatsTopAuthors(s.topAuthors, onOpenArtist)
    Spacer(Modifier.height(30.dp))
}

/** 喜爱的画师行：点击开档案；有新作品时挂「新 N」计数（浏览档案页即清零）。 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun StatsFollows(follows: List<Api.FollowItem>, onOpenArtist: (String) -> Unit) {
    Text("❤ " + AppI18n.s("喜爱的画师"), color = Color(0xFF9A8FB8), fontSize = 12.sp,
        modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp))
    follows.forEach { f ->
        // 3.7.21 需求1：喜爱的画师行去长按复制（点击照旧开档案）
        Row(Modifier.fillMaxWidth()
            .combinedClickable(onClick = { onOpenArtist(f.author) })
            .padding(horizontal = 16.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Text("👤 " + f.author, color = Color(0xFFF2EEFA), fontSize = 13.sp,
                maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            if (f.newCount > 0) {
                Text(AppI18n.sf("新 %1", f.newCount), color = Color(0xFF1C1433), fontSize = 10.sp,
                    modifier = Modifier.clip(RoundedCornerShape(999.dp))
                        .background(ACCENT2).padding(horizontal = 8.dp, vertical = 2.dp))
            }
            Text(AppI18n.sf("%1 部", f.works), color = Color(0xFF9A8FB8), fontSize = 11.sp,
                modifier = Modifier.padding(start = 10.dp))
        }
    }
}

/** 入库增长柱状图（最近 N 天）：柱高按最大值归一，0 值画暗柱占位。 */
@Composable
private fun StatsGrowthChart(byDay: List<Pair<String, Int>>) {
    Text(AppI18n.sf("📈 入库增长（近 %1 天）", byDay.size), color = Color(0xFF9A8FB8), fontSize = 12.sp,
        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
    val maxN = (byDay.maxOfOrNull { it.second } ?: 1).coerceAtLeast(1)
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(110.dp),
        verticalAlignment = Alignment.Bottom,
        horizontalArrangement = Arrangement.spacedBy(2.dp)) {
        byDay.forEach { (_, n) ->
            Box(Modifier.weight(1f)
                .fillMaxHeight(if (maxN <= 0) 0f else (n.toFloat() / maxN).coerceIn(0.04f, 1f))
                .clip(RoundedCornerShape(topStart = 3.dp, topEnd = 3.dp))
                .background(if (n > 0) ACCENT2 else Color(0x22FFFFFF)))
        }
    }
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 2.dp)) {
        Text(byDay.first().first, color = Color(0xFF6E6787), fontSize = 9.sp)
        Spacer(Modifier.weight(1f))
        Text(byDay.last().first, color = Color(0xFF6E6787), fontSize = 9.sp)
    }
}

/** 最常看画师 Top10：排名 + 条形比例（点击开档案）。 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun StatsTopAuthors(topAuthors: List<Pair<String, Int>>, onOpenArtist: (String) -> Unit) {
    Text(AppI18n.sf("🏆 最常看画师 Top%1", topAuthors.size), color = Color(0xFF9A8FB8), fontSize = 12.sp,
        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
    val maxN = (topAuthors.maxOfOrNull { it.second } ?: 1).coerceAtLeast(1)
    topAuthors.forEachIndexed { i, (name, n) ->
        // 3.7.21 需求1：Top10 画师行去长按复制（点击照旧开档案）
        Row(Modifier.fillMaxWidth()
            .combinedClickable(onClick = { onOpenArtist(name) })
            .padding(horizontal = 16.dp, vertical = 3.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Text("${i + 1}.", color = Color(0xFF6E6787), fontSize = 11.sp, modifier = Modifier.width(24.dp))
            Text(name, color = Color(0xFFF2EEFA), fontSize = 12.sp,
                maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.width(110.dp))
            Box(Modifier.weight(1f).height(10.dp).clip(RoundedCornerShape(999.dp))
                .background(Color(0x1AFFFFFF))) {
                Box(Modifier.fillMaxHeight().fillMaxWidth((n.toFloat() / maxN).coerceIn(0.02f, 1f))
                    .clip(RoundedCornerShape(999.dp)).background(Color(0xFF7F9CFF)))
            }
            Text("$n", color = Color(0xFF9A8FB8), fontSize = 11.sp,
                modifier = Modifier.padding(start = 8.dp))
        }
    }
}

@Composable
private fun StatCard(label: String, value: String, modifier: Modifier = Modifier) {
    Column(modifier.clip(RoundedCornerShape(12.dp)).background(Color(0xFF140F22)).padding(12.dp)) {
        Text(label, color = Color(0xFF9A8FB8), fontSize = 10.sp)
        Text(value, color = Color(0xFFF2EEFA), fontSize = 18.sp, fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(top = 2.dp))
    }
}
