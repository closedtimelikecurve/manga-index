package com.biblioteca.reader

import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import kotlinx.coroutines.flow.Flow

/* ================================================================
   阅读器 · 模式二：瀑布流连续阅读（3.7.43 从 ReaderScreen.kt 拆出）
   全部页面纵向无缝拼接，LazyColumn 懒加载。
   未载入页显示 64dp 矮条，成功后按真实宽高比展开；已载入页用普通 AsyncImage
   （内存缓存命中即出图，不闪加载位——SubcomposeAsyncImage 每次进视口会先闪一帧
   深色加载位，快速滚动时就是一条条灰带，灰区元凶）。
   点按不翻页（对齐官方）：点按 = 切换工具栏；双击图片 = 进入单独图片界面。
   ================================================================ */

@Composable
fun ScrollMode(source: ReaderSource, pageAt: (Int) -> Int, total: Int, kinds: List<String>?,
               page: Int, onPage: (Int) -> Unit, barsVisible: Boolean,
               onHideBars: () -> Unit, onShowBars: () -> Unit, onZoom: (Int) -> Unit,
               onGestureActive: (Boolean) -> Unit) {
    val listState = rememberLazyListState(initialFirstVisibleItemIndex = page)
    val ctx = LocalContext.current
    val (vpW, vpH) = viewportPx()
    var reported by remember { mutableIntStateOf(-1) }   // 最近一次由滚动回传的页码
    val ratios = remember { mutableStateMapOf<Int, Float>() }   // 已知页面的宽高比，稳定高度防抖动

    // 仅响应“外部”页码变化（拉条跳页/切模式/首次进入）才重新定位；
    // 用户滚动产生的页码回传不触发定位，否则会瞬间吸附到下一页顶部。
    // 滚动/惯性进行中绝不重定位：GIF 页加载前后高度跳变会让中心页码猛跳，
    // 滞后的 page 会误判为外部跳页，把用户强行拉回旧位置（无法正常向下阅读）。
    LaunchedEffect(page) {
        if (page != reported && !listState.isScrollInProgress) {
            listState.scrollToItem(page)
            reported = page
        }
    }
    // 当前页判定：顶部可见页即为正在读的页（细则见 currentPageFlow）
    LaunchedEffect(listState) {
        currentPageFlow(listState).collect { idx ->
            if (idx >= 0 && idx != reported) {
                reported = idx
                onPage(idx)
            }
        }
    }
    // 滚动手势进行中 → 工具栏绝不自动淡出（滑动时消失的问题根源：手势中页码不变、
    // 计时器不刷新，3 秒一到就在滑动中途消失）
    LaunchedEffect(listState) {
        snapshotFlow { listState.isScrollInProgress }.collect { onGestureActive(it) }
    }
    // 点按 = 切换工具栏显隐；双击图片页 = 进入单独图片界面（对齐官方）
    Box(Modifier.fillMaxSize()
        .scrollModeTaps(barsVisible, listState, kinds, onHideBars, onShowBars, onZoom)) {
        LazyColumn(state = listState, modifier = Modifier.fillMaxSize()) {
            items(total) { p ->
                ScrollModePage(source, pageAt(p), p, total, kinds, ratios, vpW, vpH, ctx)
            }
        }
    }
}

/** 连续模式点按手势（3.7.43 抽出）：点按切工具栏显隐，双击图片页进单独界面（跳过视频页）。 */
private fun Modifier.scrollModeTaps(barsVisible: Boolean, listState: LazyListState,
                                    kinds: List<String>?, onHideBars: () -> Unit,
                                    onShowBars: () -> Unit, onZoom: (Int) -> Unit) =
    pointerInput(barsVisible) {
        detectTapGestures(
            onTap = {
                if (barsVisible) onHideBars() else onShowBars()
            },
            onDoubleTap = { off ->
                val idx = itemIndexAt(listState, off.y)
                if (idx >= 0 && !isVideoAt(kinds, idx)) onZoom(idx)
            })
    }

/**
 * 当前阅读页流（3.7.43 从 ScrollMode 抽出）：顶部可见页即为正在读的页；
 * 下一页露出自身高度过半 → 视为已翻到下一页。
 * 修复：末页过矮（宽而不长）时其缝隙永远到不了视口正中，旧逻辑会卡在倒数第二页、赖在续读区。
 */
private fun currentPageFlow(listState: LazyListState): Flow<Int> = snapshotFlow {
    val info = listState.layoutInfo
    val vis = info.visibleItemsInfo
    if (vis.isEmpty()) -1
    else {
        // 顶部可见页 = 视口内 offset 最小（最靠上）的那一页
        val cur = vis.minByOrNull { it.offset }!!.index
        val nxt = vis.firstOrNull { it.index == cur + 1 }
        if (nxt != null && nxt.size > 0) {
            val visH = (minOf(info.viewportEndOffset, nxt.offset + nxt.size)
                - maxOf(info.viewportStartOffset, nxt.offset)).coerceAtLeast(0)
            // 下一页可见高度占其自身高度的比例：过半则翻到下一页
            if (visH.toFloat() / nxt.size >= 0.5f) cur + 1 else cur
        } else cur
    }
}

/** 双击落点命中的列表项下标（没有命中返回 -1）。 */
private fun itemIndexAt(listState: LazyListState, y: Float): Int {
    val item = listState.layoutInfo.visibleItemsInfo.firstOrNull {
        y >= it.offset && y < it.offset + it.size
    }
    return item?.index ?: -1
}

/**
 * 连续模式单页（3.7.43 从 ScrollMode 抽出）：
 * 已知宽高比的页按比例展开（防抖动），未知的先用 64dp 矮条占位；
 * 失败可点按重试（重建请求绕过缓存）。
 */
@Composable
private fun ScrollModePage(source: ReaderSource, absNo: Int, p: Int, total: Int,
                           kinds: List<String>?, ratios: MutableMap<Int, Float>,
                           vpW: Int, vpH: Int, ctx: android.content.Context) {
    if (isVideoAt(kinds, p)) {
        VideoPageAsync(source, absNo, Modifier.fillMaxWidth().aspectRatio(16f / 9f))
        return
    }
    val ratio = ratios[p]
    var failed by remember(p) { mutableStateOf(false) }
    var retry by remember(p) { mutableIntStateOf(0) }   // 失败重试（重建请求绕过缓存）
    // 普通页（已载入过）：AsyncImage + 内存缓存命中即出图，无加载位闪烁
    Box(Modifier.fillMaxWidth()
        .then(if (ratio != null) Modifier.aspectRatio(ratio)
              else Modifier.height(64.dp))
        .background(Color(0xFF12101F))) {
        if (!failed) {
            AsyncImage(
                model = pageRequest(ctx, source.pageModel(absNo), retry, vpW, vpH,
                    anim = isAnimAt(kinds, p), crossfade = false),
                contentDescription = AppI18n.sf("第%1页", p + 1),
                contentScale = ContentScale.FillWidth,
                onSuccess = { st ->
                    failed = false
                    if (ratios[p] == null) {
                        val d = st.painter.intrinsicSize
                        if (d.width > 0 && d.height > 0 &&
                            d != androidx.compose.ui.geometry.Size.Unspecified)
                            ratios[p] = d.width / d.height
                    }
                },
                onError = { if (retry == 0) failed = true },
                modifier = Modifier.fillMaxSize())
        } else {
            PageLoadFailed(p + 1, fill = false) { retry++; failed = false }
        }
        if (ratio == null && !failed) {
            Text(AppI18n.sf("第 %1 / %2 页 · 载入中…", p + 1, total),
                color = Color(0xFF9A8FB8), fontSize = 10.sp,
                modifier = Modifier.align(Alignment.Center))
        }
    }
}
