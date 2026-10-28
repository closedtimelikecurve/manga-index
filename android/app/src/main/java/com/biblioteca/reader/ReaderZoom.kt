package com.biblioteca.reader

import androidx.compose.animation.core.animate
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.calculatePan
import androidx.compose.foundation.gestures.calculateZoom
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.PointerInputScope
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChange
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.IntSize
import coil.compose.SubcomposeAsyncImage
import kotlinx.coroutines.launch

/* ================================================================
   阅读器 · 单独图片界面（3.7.43 从 ReaderScreen.kt 拆出）
   双击/双指缩放 + 缩放后拖动（钳制在图片实际显示范围内）——仅作为滚动模式的
   放大覆盖层使用；未缩放时的单指点按 → onClose（退出放大并唤出工具栏）。
   载入中/失败显示占位卡（页码一目了然），失败可点按重试。
   ================================================================ */
@Composable
fun ZoomableImage(source: ReaderSource, pageNo: Int, absNo: Int = pageNo, total: Int,
                  modifier: Modifier = Modifier,
                  onClose: (() -> Unit)? = null, anim: Boolean = false) {
    val ctx = LocalContext.current
    val (vpW, vpH) = viewportPx()
    // 打开即放大 2.5 倍（对齐官方：点图片 = 看放大图，而不是原尺寸再看一遍）
    var scale by remember(pageNo) { mutableFloatStateOf(1f) }
    var offset by remember(pageNo) { mutableStateOf(Offset.Zero) }
    var aspect by remember { mutableFloatStateOf(0f) }          // 图片宽高比（加载成功后回填）
    var boxSize by remember { mutableStateOf(IntSize.Zero) }
    var retry by remember(pageNo) { mutableIntStateOf(0) }         // 失败重试计数（重建请求绕过缓存）
    val scope = rememberCoroutineScope()

    // 双击缩放（对齐官方：2 倍，带动画过渡）
    fun animateScale(target: Float) {
        scope.launch {
            animate(initialValue = scale, targetValue = target,
                animationSpec = tween(220)) { v, _ -> scale = v }
        }
    }

    Box(modifier
        .background(Color.Black)
        .onSizeChanged { boxSize = it }
        .zoomTapGestures(scale, { animateScale(1f) }, { offset = Offset.Zero },
            { onClose?.invoke() })
        .pointerInput(Unit) {
            // scale/offset 用 getter 传：手势循环里每个事件都要读最新值（参数快照会失效）
            zoomDragGestures(
                scale = { scale }, offset = { offset },
                onScale = { scale = it }, onOffset = { offset = it },
                maxOffset = { maxOffsetFor(aspect, boxSize, it) },
                onReset = { scale = 1f; offset = Offset.Zero })
        }) {
        ZoomablePageImage(source, absNo, pageNo, total, retry, anim, scale, offset,
            onAspect = { aspect = it },
            onRetry = { retry++ })
    }
}

/** 放大图点按手势（3.7.43 抽出）：双击 1x↔2x（动画过渡），单击退出单独界面。 */
private fun Modifier.zoomTapGestures(scale: Float, onAnimateScale: (Float) -> Unit,
                                     onResetOffset: () -> Unit, onClose: () -> Unit) =
    pointerInput(Unit) {
        detectTapGestures(
            onDoubleTap = {
                // 双击缩放：1x ↔ 2x（官方同款倍率，动画过渡）；缩放后可拖动平移
                if (scale > 1.5f) {
                    onAnimateScale(1f)
                    onResetOffset()
                } else {
                    onResetOffset()
                    onAnimateScale(2f)
                }
            },
            onTap = {
                // 单击退出单独图片界面（回到连续阅读并唤出工具栏）
                onClose()
            })
    }

/**
 * 缩放 s 下允许的最大平移量（3.7.43 提为纯函数）：
 * ContentScale.Fit 的实际显示尺寸 × s 超出视口的一半。宽高比或盒子未就绪 → 零平移。
 */
private fun maxOffsetFor(aspect: Float, boxSize: IntSize, s: Float): Offset {
    if (aspect <= 0f || boxSize == IntSize.Zero) {
        return Offset.Zero
    }
    val boxAspect = boxSize.width.toFloat() / boxSize.height
    val fitW: Float; val fitH: Float
    if (aspect > boxAspect) { fitW = boxSize.width.toFloat(); fitH = fitW / aspect }
    else { fitH = boxSize.height.toFloat(); fitW = fitH * aspect }
    return Offset(
        ((fitW * s - boxSize.width) / 2f).coerceAtLeast(0f),
        ((fitH * s - boxSize.height) / 2f).coerceAtLeast(0f))
}

/**
 * 双指缩放 + 缩放后拖动（3.7.43 从 ZoomableImage 抽出）：
 * 双指 → 缩放（1~6 倍）并按新尺度钳制平移；单指且已缩放 → 拖动平移。
 * scale/offset 经 getter 读取，保证一个手势循环内的多次事件都基于最新值。
 */
private suspend fun PointerInputScope.zoomDragGestures(
    scale: () -> Float, offset: () -> Offset,
    onScale: (Float) -> Unit, onOffset: (Offset) -> Unit,
    maxOffset: (Float) -> Offset, onReset: () -> Unit) {
    awaitEachGesture {
        awaitFirstDown(requireUnconsumed = false)
        do {
            val event = awaitPointerEvent()
            val pressed = event.changes.filter { it.pressed }
            if (pressed.size >= 2) {
                val zoomChange = event.calculateZoom()
                val panChange = event.calculatePan()
                val s = (scale() * zoomChange).coerceIn(1f, 6f)
                onScale(s)
                if (s > 1f) {
                    val m = maxOffset(s)
                    onOffset(Offset(
                        (offset().x + panChange.x).coerceIn(-m.x, m.x),
                        (offset().y + panChange.y).coerceIn(-m.y, m.y)))
                }
                event.changes.forEach { it.consume() }
            } else if (pressed.size == 1 && scale() > 1f) {
                val drag = pressed.first().positionChange()
                val m = maxOffset(scale())
                onOffset(Offset(
                    (offset().x + drag.x).coerceIn(-m.x, m.x),
                    (offset().y + drag.y).coerceIn(-m.y, m.y)))
                event.changes.forEach { it.consume() }
            }
        } while (event.changes.any { it.pressed })
        if (scale() < 1f) onReset()
    }
}

/** 放大图本体（3.7.43 从 ZoomableImage 抽出）：SubcomposeAsyncImage + graphicsLayer 变换。 */
@Composable
private fun ZoomablePageImage(source: ReaderSource, absNo: Int, pageNo: Int, total: Int,
                              retry: Int, anim: Boolean, scale: Float, offset: Offset,
                              onAspect: (Float) -> Unit, onRetry: () -> Unit) {
    val ctx = LocalContext.current
    val (vpW, vpH) = viewportPx()
    Box(
        Modifier.fillMaxSize().graphicsLayer {
            scaleX = scale; scaleY = scale
            translationX = offset.x; translationY = offset.y
        }) {
        SubcomposeAsyncImage(
            model = pageRequest(ctx, source.pageModel(absNo), retry, vpW, vpH, anim = anim, crossfade = true),
            contentDescription = AppI18n.sf("第%1页", pageNo + 1),
            contentScale = ContentScale.Fit,
            onSuccess = { r ->
                val s = r.painter.intrinsicSize
                if (s.width > 0f && s.height > 0f && s != Size.Unspecified) {
                    onAspect(s.width / s.height)
                }
            },
            loading = { PagePlaceholder(pageNo + 1, total, fill = true) },
            error = { PageLoadFailed(pageNo + 1, fill = true) { onRetry() } },
            modifier = Modifier.fillMaxSize())
    }
}
