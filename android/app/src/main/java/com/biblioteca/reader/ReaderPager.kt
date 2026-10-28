package com.biblioteca.reader

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.SubcomposeAsyncImage

/* ================================================================
   阅读器 · 模式一：左右滑动翻页（3.7.43 从 ReaderScreen.kt 拆出）
   无缩放——放大只在滚动模式（对齐官方）。
   ================================================================ */

@Composable
fun PagerMode(source: ReaderSource, pageAt: (Int) -> Int, total: Int, kinds: List<String>?,
              page: Int, onPage: (Int) -> Unit, onGestureActive: (Boolean) -> Unit) {
    val pagerState = rememberPagerState(initialPage = page, pageCount = { total })
    val ctx = LocalContext.current
    val (vpW, vpH) = viewportPx()
    LaunchedEffect(page) {
        if (pagerState.currentPage != page) pagerState.scrollToPage(page)
    }
    LaunchedEffect(pagerState) {
        snapshotFlow { pagerState.currentPage }.collect { onPage(it) }
    }
    // 滑动手势进行中 → 工具栏绝不自动淡出
    LaunchedEffect(pagerState) {
        snapshotFlow { pagerState.isScrollInProgress }.collect { onGestureActive(it) }
    }
    HorizontalPager(state = pagerState, modifier = Modifier.fillMaxSize()) { p ->
        if (isVideoAt(kinds, p)) {
            VideoPageAsync(source, pageAt(p), Modifier.fillMaxSize())
        } else {
            var retry by remember(p) { mutableIntStateOf(0) }   // 失败点按重试（重建请求绕过缓存）
            SubcomposeAsyncImage(
                model = pageRequest(ctx, source.pageModel(pageAt(p)), retry, vpW, vpH,
                    anim = isAnimAt(kinds, p), crossfade = true),
                contentDescription = AppI18n.sf("第%1页", p + 1),
                contentScale = ContentScale.Fit,
                loading = { PagePlaceholder(p + 1, total, fill = true) },
                error = { PageLoadFailed(p + 1, fill = true) { retry++ } },
                modifier = Modifier.fillMaxSize())
        }
    }
}

/* ---- 顶栏分段胶囊（仅图标）：选中粉底深字，未选中透底灰字 ---- */
@Composable
fun ModePill(label: String, on: Boolean, onClick: () -> Unit) {
    Text(label, color = if (on) Color(0xFF1C1433) else Color(0xFF9A8FB8), fontSize = 14.sp,
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(if (on) ACCENT2 else Color.Transparent)
            .clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 4.dp))
}
