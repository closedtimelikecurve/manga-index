@file:OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)

package com.biblioteca.reader

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyGridScope
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.CircleShape
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

/* 3.7.48：首页三种信息流（画师 / 原作 / 社团），从 FeaturesHome.kt 拆出独立文件，函数拆到 ≤50 行。 */

/** 首页「全部画师」流（3.7.46 从 HomeScreen 拆出；3.7.48 再拆卡）。 */
internal fun LazyGridScope.homeArtistFeed(
    artists: List<Api.ArtistItem>?, feedSort: String, feedSortAsc: Boolean,
    onFeedRetry: () -> Unit, onOpenArtist: (String) -> Unit,
    onToggleFavorite: (String, Boolean) -> Unit
) {
    val cmpLatest = feedSort == "latest"
    val arts = artists.orEmpty().sortedWith { x, y ->
        val ka = if (cmpLatest) x.latest else x.works.toLong()
        val kb = if (cmpLatest) y.latest else y.works.toLong()
        var r = kb.compareTo(ka)
        if (feedSortAsc) r = -r
        if (r != 0) r else x.name.compareTo(y.name)
    }
    if (artists == null) FeedMessage(AppI18n.s("加载中…"), retry = true, onRetry = onFeedRetry)
    else if (arts.isEmpty()) FeedMessage(AppI18n.s("还没有画师数据"))
    else items(arts, key = { it.name }) { a -> ArtistCard(a, onOpenArtist, onToggleFavorite) }
}

/** 首页「原作分区」流（3.7.46 从 HomeScreen 拆出；3.7.48 再拆卡）。 */
internal fun LazyGridScope.homeOriginalFeed(
    originals: List<Api.OriginalItem>?, feedSort: String, feedSortAsc: Boolean,
    onFeedRetry: () -> Unit, onAddOriginal: () -> Unit,
    onOpenOriginal: (String) -> Unit, onLongPressOriginal: (String, IntRect) -> Unit
) {
    // 3.6.39 #37：默认"创建次序"直接用后端顺序；3.7.36 补：created 也支持反序
    val origs = if (feedSort == "created") {
        val src = originals.orEmpty()
        if (feedSortAsc) src.reversed() else src
    } else originals.orEmpty().sortedWith { x, y ->
        val ka = if (feedSort == "latest") x.latest else x.works.toLong()
        val kb = if (feedSort == "latest") y.latest else y.works.toLong()
        var r = kb.compareTo(ka)
        if (feedSortAsc) r = -r
        if (r != 0) r else x.name.compareTo(y.name)
    }
    if (originals == null) FeedMessage(AppI18n.s("加载中…"), retry = true, onRetry = onFeedRetry)
    else if (origs.isEmpty()) FeedMessage(AppI18n.s("还没有同人标签——导入时带 (同人名) 的作品会归到这里"))
    // 3.6.19 #21：分区列表旁常驻「＋ 添加原作」横条（空态/非空态都有）
    item(span = { GridItemSpan(maxLineSpan) }) { AddOriginalBar(onAddOriginal) }
    items(origs, key = { it.name }) { t -> OriginalCard(t, onOpenOriginal, onLongPressOriginal) }
}

/** 首页「全部社团」流（3.7.46 从 HomeScreen 拆出；3.7.48 再拆卡）。 */
internal fun LazyGridScope.homeGroupFeed(
    shownGroups: List<Api.Group>, onOpen: (String) -> Unit,
    onLongPressCircle: (String, IntRect) -> Unit
) {
    items(shownGroups, key = { it.name }) { g -> GroupCard(g, onOpen, onLongPressCircle) }
}

/** 信息流加载中 / 空态提示（3.7.48 抽出，画师流与原作流共用）。 */
private fun LazyGridScope.FeedMessage(primary: String, retry: Boolean = false, onRetry: () -> Unit = {}) {
    item(span = { GridItemSpan(maxLineSpan) }) {
        Column(Modifier.fillMaxWidth().padding(top = 60.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(primary, color = Color(0xFF9A8FB8), fontSize = 13.sp)
            if (retry) Text("⟳ " + AppI18n.s("点此重试"), color = ACCENT2, fontSize = 12.sp,
                modifier = Modifier.padding(top = 10.dp).clickable { onRetry() })
        }
    }
}

/** 原作分区列表旁常驻「＋ 添加原作」横条（3.7.48 抽出）。 */
@Composable
private fun AddOriginalBar(onAddOriginal: () -> Unit) {
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Color(0xFF1A1430))
        .clickable { onAddOriginal() }.padding(horizontal = 14.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text("＋", color = ACCENT2, fontSize = 18.sp)
        Column(Modifier.padding(start = 10.dp)) {
            Text(AppI18n.s("添加同人"), color = Color(0xFFF2EEFA), fontSize = 13.sp)
            Text(AppI18n.s("输入词条，自动把相关作品归为新分区"), color = Color(0xFF9A8FB8), fontSize = 10.sp)
        }
    }
}

/** 画师卡（3.7.48 从 homeArtistFeed 抽出）。 */
@Composable
private fun ArtistCard(a: Api.ArtistItem, onOpenArtist: (String) -> Unit, onToggleFavorite: (String, Boolean) -> Unit) {
    Column(Modifier.clip(RoundedCornerShape(10.dp)).background(Color(0xFF140F22))
        .combinedClickable(onClick = { onOpenArtist(a.name) })) {
        Box(Modifier.fillMaxWidth().aspectRatio(3f / 4f).background(Color(0xFF1C1433)), contentAlignment = Alignment.Center) {
            Text("👤", fontSize = 30.sp)
            if (a.coverGroup != null && a.coverWork != null) {
                AsyncImage(model = Api.coverUrl(a.coverGroup, a.coverWork, a.coverVer), contentDescription = a.name,
                    contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            }
            // 3.3.1 右下角爱心:点亮 = 喜爱;点卡片进档案,点爱心即切换
            Text(if (a.followed) "❤" else "🤍", fontSize = 15.sp,
                modifier = Modifier.align(Alignment.BottomEnd).padding(6.dp)
                    .clip(CircleShape).background(Color(0x99060411))
                    .clickable { onToggleFavorite(a.name, !a.followed) }.padding(4.dp))
        }
        Column(Modifier.padding(8.dp)) {
            Text(a.name, color = Color(0xFFF2EEFA), fontSize = 12.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(AppI18n.sf("%1 部 · 点看档案", a.works), color = Color(0xFF9A8FB8), fontSize = 10.sp)
        }
    }
}

/** 原作分区卡（3.7.48 从 homeOriginalFeed 抽出）。 */
@Composable
private fun OriginalCard(t: Api.OriginalItem, onOpenOriginal: (String) -> Unit, onLongPressOriginal: (String, IntRect) -> Unit) {
    var cardRect by remember { mutableStateOf(IntRect.Zero) }
    Column(Modifier.onGloballyPositioned { p ->
        cardRect = IntRect(p.positionInRoot().x.toInt(), p.positionInRoot().y.toInt(),
            (p.positionInRoot().x + p.size.width).toInt(), (p.positionInRoot().y + p.size.height).toInt())
    }.clip(RoundedCornerShape(10.dp)).background(Color(0xFF140F22))
        .clickable { onOpenOriginal(t.name) }) {
        Box(Modifier.fillMaxWidth().aspectRatio(3f / 4f).background(Color(0xFF1C1433))
            // 3.6.21：分区卡封面长按 → 分区操作栏（改名 / 移除）
            .combinedClickable(onClick = { onOpenOriginal(t.name) }, onLongClick = { onLongPressOriginal(t.name, cardRect) }),
            contentAlignment = Alignment.Center) {
            Text("🎴", fontSize = 30.sp)
            if (t.coverGroup != null && t.coverWork != null) {
                AsyncImage(model = Api.coverUrl(t.coverGroup, t.coverWork, t.coverVer), contentDescription = t.name,
                    contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            }
        }
        Column(Modifier.padding(8.dp)) {
            Text(t.name, color = Color(0xFFF2EEFA), fontSize = 12.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(AppI18n.sf("%1 部 · 点进分区", t.works), color = Color(0xFF9A8FB8), fontSize = 10.sp)
        }
    }
}

/** 社团卡（3.7.48 从 homeGroupFeed 抽出）。 */
@Composable
private fun GroupCard(g: Api.Group, onOpen: (String) -> Unit, onLongPressCircle: (String, IntRect) -> Unit) {
    var cardRect by remember { mutableStateOf(IntRect.Zero) }
    Column(Modifier.onGloballyPositioned { p ->
        cardRect = IntRect(p.positionInRoot().x.toInt(), p.positionInRoot().y.toInt(),
            (p.positionInRoot().x + p.size.width).toInt(), (p.positionInRoot().y + p.size.height).toInt())
    }.clip(RoundedCornerShape(10.dp)).background(Color(0xFF140F22))
        // 3.6.14：社团操作菜单只在封面区（下方 Box）唤出；社团名文字区长按 = 直接复制社团名
        .combinedClickable(onClick = { onOpen(g.name) })) {
        Box(Modifier.fillMaxWidth().aspectRatio(3f / 4f).background(Color(0xFF1C1433))
            .combinedClickable(onClick = { onOpen(g.name) }, onLongClick = { onLongPressCircle(g.name, cardRect) }),
            contentAlignment = Alignment.Center) {
            if (g.hasCover) {
                // 3.6.166：用 coverGroup（封面作品实际所在社团），不是社团名——
                // 社团封面常常取自画师页口径的**别的**社团，按 name 拼会 404、封面空白。
                AsyncImage(model = Api.coverUrl(g.coverGroup, g.coverWork), contentDescription = g.name,
                    contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            } else {
                Text("📦", fontSize = 30.sp)
            }
            // 3.5.0 有新角标：社团内有"上次访问后新入库"的作品
            val newN = ReadingHub.newCountInCircle(g.name)
            if (newN > 0) {
                Text(AppI18n.sf("有新 %1", newN), color = Color(0xFF1C1433), fontSize = 9.sp, maxLines = 1,
                    modifier = Modifier.align(Alignment.TopEnd).padding(4.dp)
                        .clip(RoundedCornerShape(999.dp)).background(ACCENT2)
                        .padding(horizontal = 6.dp, vertical = 2.dp))
            }
        }
        Column(Modifier.padding(8.dp)) {
            Text(g.name, color = Color(0xFFF2EEFA), fontSize = 12.sp, maxLines = 2, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.combinedClickable(onClick = { onOpen(g.name) }))
            Text(AppI18n.sf("%1 部", g.workCount), color = Color(0xFF9A8FB8), fontSize = 10.sp)
        }
    }
}
