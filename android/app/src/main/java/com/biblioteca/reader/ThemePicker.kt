package com.biblioteca.reader

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog

/* ================================================================
   3.7.74：主题取色器（替代 3.7.73 的"手填十六进制"）。
   手机上没人愿意手打 #ff3df2——用户原话："自定义主题色居然是手动输入"。
   形态：饱和度/明度方块（拖动选色）+ 色相条 + 结果预览与十六进制回显。
   ================================================================ */

private val PICK_LINE = Color(0x24FFFFFF)

/** hsv(0~360, 0~1, 0~1) → Color；走 android.graphics 保证各 API 版本一致。 */
private fun hsvColor(h: Float, s: Float, v: Float): Color =
    Color(android.graphics.Color.HSVToColor(floatArrayOf(h, s, v)))

private fun hueOf(x: Float, w: Int): Float = ((x / w).coerceIn(0f, 1f)) * 360f

@Composable
internal fun HsvColorDialog(initial: Color, title: String,
                            onDismiss: () -> Unit, onPick: (Color) -> Unit) {
    val start = remember(initial) {
        FloatArray(3).also { android.graphics.Color.colorToHSV(initial.toArgb(), it) }
    }
    var hue by remember(initial) { mutableStateOf(start[0]) }
    var sat by remember(initial) { mutableStateOf(start[1]) }
    var value by remember(initial) { mutableStateOf(start[2]) }
    val cur = hsvColor(hue, sat, value)
    Dialog(onDismissRequest = onDismiss) {
        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp))
            .background(CARD_BG).padding(18.dp)) {
            Text(title, color = TXT, fontSize = 16.sp)
            Spacer(Modifier.height(12.dp))
            SvSquare(hue, sat, value) { s, v -> sat = s; value = v }
            Spacer(Modifier.height(12.dp))
            HueBar(hue) { hue = it }
            Spacer(Modifier.height(16.dp))
            PickerFooter(cur, onDismiss) { onPick(cur) }
        }
    }
}

/** 饱和度（横）× 明度（纵）方块：底色是"当前色相的纯色"，叠白→色相渐变与黑→透明渐变。 */
@Composable
private fun SvSquare(hue: Float, sat: Float, value: Float, onChange: (Float, Float) -> Unit) {
    Canvas(Modifier.fillMaxWidth().height(170.dp).clip(RoundedCornerShape(12.dp))
        .border(1.dp, PICK_LINE, RoundedCornerShape(12.dp))
        .pointerInput(Unit) {
            detectDragGestures(
                onDragStart = { off -> applySv(off.x, off.y, size.width, size.height, onChange) },
                onDrag = { ch, _ ->
                    applySv(ch.position.x, ch.position.y, size.width, size.height, onChange)
                })
        }
        .pointerInput(Unit) {
            detectTapGestures { off ->
                applySv(off.x, off.y, size.width, size.height, onChange)
            }
        }) {
        drawRect(Brush.horizontalGradient(listOf(Color.White, hsvColor(hue, 1f, 1f))))
        drawRect(Brush.verticalGradient(listOf(Color.Transparent, Color.Black)))
        val c = Offset(sat * size.width, (1f - value) * size.height)
        drawCircle(Color.White, radius = 9.dp.toPx(), center = c, style = Stroke(2.dp.toPx()))
        drawCircle(Color.Black.copy(alpha = 0.45f), radius = 11.dp.toPx(), center = c,
            style = Stroke(1.dp.toPx()))
    }
}

/** 拖动/点按位置 → (饱和度, 明度)。y 轴向下，明度要翻过来。 */
private fun applySv(x: Float, y: Float, w: Int, h: Int, onChange: (Float, Float) -> Unit) {
    if (w <= 0 || h <= 0) return
    onChange((x / w).coerceIn(0f, 1f), (1f - y / h).coerceIn(0f, 1f))
}

/** 色相条：0~360 全色相渐变 + 当前位置竖线。 */
@Composable
private fun HueBar(hue: Float, onChange: (Float) -> Unit) {
    Canvas(Modifier.fillMaxWidth().height(26.dp).clip(RoundedCornerShape(999.dp))
        .pointerInput(Unit) {
            detectDragGestures(
                onDragStart = { off -> onChange(hueOf(off.x, size.width)) },
                onDrag = { ch, _ -> onChange(hueOf(ch.position.x, size.width)) })
        }
        .pointerInput(Unit) { detectTapGestures { off -> onChange(hueOf(off.x, size.width)) } }
    ) {
        drawRect(Brush.horizontalGradient(listOf(
            hsvColor(0f, 1f, 1f), hsvColor(60f, 1f, 1f), hsvColor(120f, 1f, 1f),
            hsvColor(180f, 1f, 1f), hsvColor(240f, 1f, 1f), hsvColor(300f, 1f, 1f),
            hsvColor(360f, 1f, 1f))))
        val x = hue / 360f * size.width
        drawRect(Color.White, topLeft = Offset(x - 2f, 0f), size = Size(4f, size.height))
    }
}

/** 底部：结果色块 + 十六进制回显 + 取消/确定。 */
@Composable
private fun PickerFooter(cur: Color, onDismiss: () -> Unit, onConfirm: () -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(34.dp).clip(RoundedCornerShape(10.dp)).background(cur)
            .border(1.dp, PICK_LINE, RoundedCornerShape(10.dp)))
        Text("#" + hexOf(cur), color = MUTED, fontSize = 12.sp,
            modifier = Modifier.padding(start = 10.dp).weight(1f))
        Text(AppI18n.s("取消"), color = MUTED, fontSize = 14.sp,
            modifier = Modifier.clickable { onDismiss() }.padding(horizontal = 10.dp, vertical = 8.dp))
        Text(AppI18n.s("确定"), color = ACCENT, fontSize = 14.sp,
            modifier = Modifier.clickable { onConfirm() }
                .padding(horizontal = 10.dp, vertical = 8.dp))
    }
}