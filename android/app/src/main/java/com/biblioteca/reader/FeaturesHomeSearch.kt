@file:OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)

package com.biblioteca.reader

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage

/* 3.7.48：首页内联搜索结果（社团 / 作品 / 画师三段），从 FeaturesHome.kt 拆出独立文件，函数拆到 ≤50 行。 */

/** 首页内联搜索结果（3.7.46 从 HomeScreen 拆出）：社团 / 作品 / 画师三段。 */
@Composable
internal fun HomeSearchResults(
    onOpen: (String) -> Unit, onOpenArtist: (String) -> Unit,
    onOpenReader: (String, String) -> Unit,
    onLongPressCircle: (String, IntRect) -> Unit,
    onLongPressArtist: (String, IntRect) -> Unit,
    onLongPressWork: (String, String, IntRect) -> Unit
) {
    LazyVerticalGrid(
        columns = GridCells.Adaptive(110.dp),
        contentPadding = PaddingValues(start = 10.dp, end = 10.dp, top = 10.dp, bottom = 96.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.fillMaxSize()
    ) {
        if (sGroups.isNotEmpty()) item(span = { GridItemSpan(maxLineSpan) }) {
            Text(AppI18n.sf("🏢 社团（%1）", sGroups.size), color = Color(0xFF9A8FB8), fontSize = 12.sp, modifier = Modifier.padding(2.dp, 4.dp))
        }
        items(sGroups, key = { "g" + it.name }) { g -> SearchGroupCard(g, onOpen, onLongPressCircle) }
        if (sAuthors.isNotEmpty()) item(span = { GridItemSpan(maxLineSpan) }) {
            Text(AppI18n.sf("👤 画师（%1）", sAuthors.size), color = Color(0xFF9A8FB8), fontSize = 12.sp, modifier = Modifier.padding(2.dp, 4.dp))
        }
        items(sAuthors, key = { "a" + it.name }) { a -> SearchAuthorCard(a, onOpenArtist, onLongPressArtist) }
        if (sWorks.isNotEmpty()) item(span = { GridItemSpan(maxLineSpan) }) {
            Text(AppI18n.sf("📚 作品（%1）", sWorks.size), color = Color(0xFF9A8FB8), fontSize = 12.sp, modifier = Modifier.padding(2.dp, 4.dp))
        }
        items(sWorks, key = { "w" + it.group + "/" + it.work.name }) { h -> SearchWorkCard(h, onOpenReader, onLongPressWork, onOpen) }
    }
}

/** 搜索结果社团卡（3.7.48 从 HomeSearchResults 抽出）。 */
@Composable
private fun SearchGroupCard(g: Api.Group, onOpen: (String) -> Unit, onLongPressCircle: (String, IntRect) -> Unit) {
    var groupRect by remember { mutableStateOf(IntRect.Zero) }
    Column(Modifier.onGloballyPositioned { p ->
        groupRect = IntRect(p.positionInRoot().x.toInt(), p.positionInRoot().y.toInt(),
            (p.positionInRoot().x + p.size.width).toInt(), (p.positionInRoot().y + p.size.height).toInt())
    }.clip(RoundedCornerShape(10.dp)).background(Color(0xFF140F22))
        .combinedClickable(onClick = { pendingSearchRestore = true; searchOpen = false; onOpen(g.name) })) {
        Box(Modifier.fillMaxWidth().aspectRatio(3f / 4f).background(Color(0xFF1C1433))
            .combinedClickable(onClick = { pendingSearchRestore = true; searchOpen = false; onOpen(g.name) },
                onLongClick = { onLongPressCircle(g.name, groupRect) }), contentAlignment = Alignment.Center) {
            if (g.hasCover) {
                AsyncImage(model = Api.coverUrl(g.name, g.coverWork), contentDescription = g.name, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            } else Text("📦", fontSize = 30.sp)
        }
        Column(Modifier.padding(8.dp)) {
            Text(g.name, color = Color(0xFFF2EEFA), fontSize = 12.sp, maxLines = 2, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.combinedClickable(onClick = { pendingSearchRestore = true; searchOpen = false; onOpen(g.name) }))
            Text(AppI18n.sf("%1 部", g.workCount), color = Color(0xFF9A8FB8), fontSize = 10.sp)
        }
    }
}

/** 搜索结果画师卡（3.7.48 从 HomeSearchResults 抽出）。 */
@Composable
private fun SearchAuthorCard(a: Api.TagItem, onOpenArtist: (String) -> Unit, onLongPressArtist: (String, IntRect) -> Unit) {
    var authorRect by remember { mutableStateOf(IntRect.Zero) }
    Column(Modifier.onGloballyPositioned { p ->
        authorRect = IntRect(p.positionInRoot().x.toInt(), p.positionInRoot().y.toInt(),
            (p.positionInRoot().x + p.size.width).toInt(), (p.positionInRoot().y + p.size.height).toInt())
    }.clip(RoundedCornerShape(10.dp)).background(Color(0xFF140F22))
        .combinedClickable(onClick = { pendingSearchRestore = true; searchOpen = false; onOpenArtist(a.name) })) {
        Box(Modifier.fillMaxWidth().aspectRatio(3f / 4f).background(Color(0xFF1C1433))
            .combinedClickable(onClick = { pendingSearchRestore = true; searchOpen = false; onOpenArtist(a.name) },
                onLongClick = { onLongPressArtist(a.name, authorRect) }), contentAlignment = Alignment.Center) {
            if (a.coverGroup != null && a.coverWork != null) {
                AsyncImage(model = Api.coverUrl(a.coverGroup, a.coverWork), contentDescription = a.name, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            } else Text("👤", fontSize = 30.sp)
        }
        Column(Modifier.padding(8.dp)) {
            Text(a.name, color = Color(0xFFF2EEFA), fontSize = 12.sp, maxLines = 2, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.combinedClickable(onClick = { pendingSearchRestore = true; searchOpen = false; onOpenArtist(a.name) }))
            Text(AppI18n.sf("%1 部", a.count), color = Color(0xFF9A8FB8), fontSize = 10.sp)
        }
    }
}

/** 搜索结果作品卡（3.7.48 从 HomeSearchResults 抽出）。 */
@Composable
private fun SearchWorkCard(h: Api.WorkHit, onOpenReader: (String, String) -> Unit, onLongPressWork: (String, String, IntRect) -> Unit, onOpen: (String) -> Unit) {
    var cardRect by remember { mutableStateOf(IntRect.Zero) }
    Column(Modifier.onGloballyPositioned { p ->
        cardRect = IntRect(p.positionInRoot().x.toInt(), p.positionInRoot().y.toInt(),
            (p.positionInRoot().x + p.size.width).toInt(), (p.positionInRoot().y + p.size.height).toInt())
    }.clip(RoundedCornerShape(10.dp)).background(Color(0xFF140F22))
        .combinedClickable(onClick = { pendingSearchRestore = true; searchOpen = false; onOpenReader(h.group, h.work.name) })) {
        Box(Modifier.fillMaxWidth().aspectRatio(3f / 4f).background(Color(0xFF1C1433))
            .combinedClickable(onClick = { pendingSearchRestore = true; searchOpen = false; onOpenReader(h.group, h.work.name) },
                onLongClick = { onLongPressWork(h.group, h.work.name, cardRect) }), contentAlignment = Alignment.Center) {
            if (h.work.hasCover) {
                AsyncImage(model = Api.coverUrl(h.group, h.work.name), contentDescription = h.work.name, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            } else Text("📄", fontSize = 30.sp)
        }
        Column(Modifier.padding(8.dp)) {
            Text(h.work.name.dispWorkName(), color = Color(0xFFF2EEFA), fontSize = 12.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
            // 3.6.14：所属社团由纯文字改为社团标签（点击进社团）
            Text("🏢 ${h.group}", color = Color(0xFF9A8FB8), fontSize = 10.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(top = 2.dp).clip(RoundedCornerShape(999.dp)).background(Color(0x1AFFFFFF))
                    .tagClickable(h.group) { pendingSearchRestore = true; searchOpen = false; onOpen(h.group) }
                    .padding(horizontal = 8.dp, vertical = 3.dp))
        }
    }
}
