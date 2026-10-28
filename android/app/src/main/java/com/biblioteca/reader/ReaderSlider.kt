package com.biblioteca.reader

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/* ================================================================
   阅读器 · 自绘滑轨（3.7.43 从 ReaderScreen.kt 拆出）
   悬浮、无底色：细轨 + 已读进度 + 圆形拇指，拖动时拇指放大并浮出页码气泡。
   ================================================================ */

/** 滑轨行（悬浮 overlay 贴底）：细轨占满 + 右侧极小页码。modifier 由调用方给（BoxScope.align）。 */
@Composable
fun ReaderSliderRow(page: Int, total: Int, visible: Boolean, onSeek: (Int) -> Unit,
                    modifier: Modifier = Modifier) {
    AnimatedVisibility(
        visible = visible,
        enter = fadeIn() + expandVertically(expandFrom = Alignment.Bottom),
        exit = fadeOut() + shrinkVertically(shrinkTowards = Alignment.Bottom),
        modifier = modifier
    ) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 2.dp),
            verticalAlignment = Alignment.CenterVertically) {
            PageSlider(page = page, total = total,
                onSeek = onSeek,
                modifier = Modifier.weight(1f))
            Text("${page + 1}/$total", color = Color(0xFF9A8FB8), fontSize = 10.sp,
                modifier = Modifier.padding(start = 8.dp))
        }
    }
}

@Composable
fun PageSlider(page: Int, total: Int, onSeek: (Int) -> Unit, modifier: Modifier = Modifier) {
    if (total <= 0) return
    var dragFrac by remember { mutableStateOf<Float?>(null) }   // 非空 = 拖动中
    var barW by remember { mutableIntStateOf(0) }
    val density = LocalDensity.current
    val thumbDp = 14.dp
    val thumbPx = with(density) { thumbDp.toPx() }
    val frac = (dragFrac ?: (page + 1f) / total).coerceIn(0f, 1f)
    val showNo = ((frac * total).toInt().coerceIn(1, total)) - 1
    Box(modifier
        .height(28.dp)
        .onSizeChanged { barW = it.width }
        .pointerInput(total) {
            detectTapGestures { off ->
                onSeek(((off.x / size.width * total).toInt().coerceIn(1, total)) - 1)
            }
        }
        .pointerInput(total) {
            detectHorizontalDragGestures(
                onDragStart = { dragFrac = (it.x / size.width).coerceIn(0f, 1f) },
                onDragEnd = {
                    val f = dragFrac; dragFrac = null
                    if (f != null) onSeek(((f * total).toInt().coerceIn(1, total)) - 1)
                },
                onDragCancel = { dragFrac = null }
            ) { change, _ ->
                dragFrac = (change.position.x / size.width).coerceIn(0f, 1f)
                change.consume()
            }
        }) {
        // 轨道：底轨（未读，加浓到可清晰辨认）+ 前景（已读进度）
        Box(Modifier.align(Alignment.CenterStart).fillMaxWidth()
            .height(4.dp).clip(RoundedCornerShape(999.dp)).background(Color(0x59FFFFFF)))
        Box(Modifier.align(Alignment.CenterStart).fillMaxWidth(frac)
            .height(4.dp).clip(RoundedCornerShape(999.dp)).background(ACCENT2))
        // 拇指（拖动中放大 1.25 倍）
        Box(Modifier.align(Alignment.CenterStart)
            .offset { IntOffset((frac * barW - thumbPx / 2).toInt().coerceIn(0, (barW - thumbPx).toInt().coerceAtLeast(0)), 0) }
            .size(thumbDp)
            .scale(if (dragFrac != null) 1.25f else 1f)
            .clip(CircleShape).background(Color.White)
            .border(2.dp, ACCENT2, CircleShape))
        // 拖动中的页码气泡（跟随拇指，左右钳制在条内）
        if (dragFrac != null && barW > 0) {
            SliderBubble(showNo, total, frac, barW, thumbPx)
        }
    }
}

/** 拖动中的页码气泡（3.7.43 从 PageSlider 抽出）：跟随拇指，左右钳制在条内。 */
@Composable
private fun BoxScope.SliderBubble(showNo: Int, total: Int, frac: Float, barW: Int, thumbPx: Float) {
    val density = LocalDensity.current
    val bubbleW = with(density) { 64.dp.toPx() }
    val bx = (frac * barW - bubbleW / 2).toInt().coerceIn(0, (barW - bubbleW).toInt().coerceAtLeast(0))
    Box(Modifier.align(Alignment.TopStart)
        .offset { IntOffset(bx, -30.dp.roundToPx()) }
        .width(with(density) { bubbleW.toDp() })
        .clip(RoundedCornerShape(8.dp))
        .background(Color(0xF21C1433))
        .border(1.dp, ACCENT.copy(alpha = 0x44 / 255f), RoundedCornerShape(8.dp))
        .padding(vertical = 3.dp),
        contentAlignment = Alignment.Center) {
        Text("${showNo + 1} / $total", color = Color(0xFFF2EEFA), fontSize = 11.sp)
    }
}
