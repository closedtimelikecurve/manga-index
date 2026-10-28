@file:OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)

package com.biblioteca.reader

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.Image
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyGridScope
import androidx.compose.foundation.lazy.items as lazyRowItems
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage

/* 3.7.48：首页表头条目（Hero 横幅 + 信息流轮换标签 + 每日推荐），从 FeaturesHome.kt 拆出独立文件，函数拆到 ≤50 行。 */

/** 首页表头条目（3.7.46 从 HomeScreen 拆出）：Hero 横幅 + 信息流轮换标签 + 每日推荐。 */
internal fun LazyGridScope.homeRecsSection(
    lib: Api.Library, feedMode: String, onOpenReader: (String, String) -> Unit,
    onLongPressRecWork: (String, String, IntRect) -> Unit, onCycleFeed: () -> Unit,
    sortMode: String, sortAsc: Boolean, onSort: (String, Boolean) -> Unit,
    feedSort: String, feedSortAsc: Boolean, onFeedSort: (String, Boolean) -> Unit
) {
    item(span = { GridItemSpan(maxLineSpan) }) {
        Column {
            HeroBanner(lib)
            Spacer(Modifier.height(8.dp))
            FeedToggle(feedMode, onCycleFeed)
            Spacer(Modifier.height(8.dp))
            // 3.7.40：三种信息流的排序条统一放这里（此前画师/原作是独立的 grid item，位置不一致）
            if (feedMode == "circles") CircleSortBar(sortMode, sortAsc, onSort)
            else FeedSortBar(feedSort, feedSortAsc, onFeedSort, showCreated = feedMode == "originals")
            Spacer(Modifier.height(10.dp))
            DailyRecsRow(lib, onOpenReader, onLongPressRecWork)
        }
    }
}

/** 首页 Hero 横幅（3.7.48 从 homeRecsSection 抽出）。 */
@Composable
private fun HeroBanner(lib: Api.Library) {
    Box(Modifier.fillMaxWidth().height(112.dp).clip(RoundedCornerShape(14.dp))) {
        Image(painter = painterResource(R.drawable.hero), contentDescription = null,
            contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        Box(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(ACCENT.copy(alpha = 0x22 / 255f), Color(0xF20A0817)))))
        Column(Modifier.align(Alignment.BottomStart).padding(14.dp)) {
            Text("📚 " + AppI18n.s("禁书目录 Index"), color = Color(0xFFFFFFFF), fontSize = 18.sp)
            Text(AppI18n.sf("%1 个社团 · %2 部作品 · 个人本地文库", lib.groups.size, lib.groups.sumOf { it.workCount }),
                color = Color(0xFFCFC4E8), fontSize = 11.sp)
        }
    }
}

/** 信息流三态轮换标签（3.7.48 从 homeRecsSection 抽出）。 */
@Composable
private fun FeedToggle(feedMode: String, onCycleFeed: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        val feedLabel = when (feedMode) {
            "artists" -> AppI18n.s("全部画师")
            "originals" -> AppI18n.s("同人分区")
            else -> AppI18n.s("全部社团")
        }
        Text(feedLabel, color = Color(0xFFF2EEFA), fontSize = 13.sp,
            modifier = Modifier.clip(RoundedCornerShape(999.dp)).background(ACCENT.copy(alpha = 0x33 / 255f))
                .border(1.dp, ACCENT2, RoundedCornerShape(999.dp))
                .clickable { onCycleFeed() }.padding(horizontal = 14.dp, vertical = 7.dp))
        Text(AppI18n.s("点击切换（社团 → 画师 → 同人）"), color = Color(0xFF6E6787), fontSize = 10.sp, modifier = Modifier.padding(start = 10.dp))
    }
}

/** 每日推荐横滑行（3.7.48 从 homeRecsSection 抽出）。 */
@Composable
private fun DailyRecsRow(lib: Api.Library, onOpenReader: (String, String) -> Unit, onLongPressRecWork: (String, String, IntRect) -> Unit) {
    if (lib.recs.isEmpty()) return
    Text("🎲 " + AppI18n.s("每日推荐"), color = Color(0xFF9A8FB8), fontSize = 12.sp, modifier = Modifier.padding(horizontal = 2.dp))
    Spacer(Modifier.height(6.dp))
    LazyRow(contentPadding = PaddingValues(horizontal = 2.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        lazyRowItems(lib.recs, key = { it.work }) { r ->
            var recRect by remember { mutableStateOf(IntRect.Zero) }
            Column(Modifier.onGloballyPositioned { p ->
                recRect = IntRect(p.positionInRoot().x.toInt(), p.positionInRoot().y.toInt(),
                    (p.positionInRoot().x + p.size.width).toInt(), (p.positionInRoot().y + p.size.height).toInt())
            }.width(120.dp).clip(RoundedCornerShape(10.dp)).background(Color(0xFF140F22))
                .combinedClickable(onClick = { onOpenReader(r.group, r.work) })) {
                Box(Modifier.fillMaxWidth().height(150.dp).background(Color(0xFF1C1433))
                    .combinedClickable(onClick = { onOpenReader(r.group, r.work) },
                        // 3.6.5 推荐卡更小 → 菜单 compact 等比缩小
                        onLongClick = { onLongPressRecWork(r.group, r.work, recRect) }), contentAlignment = Alignment.Center) {
                    AsyncImage(model = Api.coverUrl(r.group, r.work), contentDescription = r.work, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                }
                Text(r.work, color = Color(0xFFF2EEFA), fontSize = 11.sp, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(6.dp))
            }
        }
    }
    Spacer(Modifier.height(4.dp))
}
