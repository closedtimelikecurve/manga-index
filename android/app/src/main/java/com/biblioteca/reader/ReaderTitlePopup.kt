package com.biblioteca.reader

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/* ================================================================
   阅读器 · 标题展开面板（3.7.43 从 ReaderScreen.kt 拆出）
   Windows 重命名式原地展开：面板锚定在标题文本自身的位置，同字号向下生长，
   只覆盖标题正下方的内容；返回键与模式键完全不被遮挡。
   全屏透明捕获层：点展开文本以外任意区域即收起。
   ================================================================ */

/**
 * 服务端解析失败时本地兜底猜作者名（3.7.43 提为纯函数）：
 * 优先 [C (P)] 的 P，其次首个非标记方括号段（未定词条），再不行用整题。
 */
private fun fallbackAuthorName(title: String): String =
    Regex("""\[([^[\]]+) \(([^[\]]+)\)]""").find(title)
        ?.groupValues?.getOrNull(2)
        ?: Regex("""\[([^[\]]+)]""").findAll(title)
            .map { it.groupValues[1].trim() }
            .firstOrNull {
                !Regex("(?i)無修正|无修正|c\\d+|汉化|翻訳|DL版|raw")   // i18n:data 正则语料   // i18n:data 正则语料   // i18n:data 正则语料
                    .containsMatchIn(it)
            }
        ?: title

@Composable
fun ReaderTitlePopup(source: ReaderSource, titleOpen: Boolean, titleRect: IntRect,
                     origin: IntOffset, author: String, onClose: () -> Unit) {
    if (!titleOpen) return
    val ctx = LocalContext.current
    // 全屏透明捕获层：点展开文本以外任意区域（返回键 / 模式键 / 页码条 / 图片区）即收起。
    // 根 Box 已 fillMaxSize，这里 fillMaxSize 即覆盖全屏（原 matchParentSize 是 BoxScope
    // 扩展，拆出函数后不可用；在此场景下两者等价）
    Box(Modifier.fillMaxSize()
        .pointerInput(Unit) { detectTapGestures { onClose() } })
    // Windows 重命名式原地展开：面板锚定在标题文本自身的位置，同字号向下生长
    val density = LocalDensity.current
    val clipboard = LocalClipboardManager.current
    Column(
        Modifier
            .offset { IntOffset(titleRect.left - origin.x, titleRect.top - origin.y) }
            .width(with(density) { titleRect.width.coerceAtLeast(1).toDp() })
            .clip(RoundedCornerShape(6.dp))
            .background(Color(0xF21C1433))
            .border(1.dp, ACCENT.copy(alpha = 0x44 / 255f), RoundedCornerShape(6.dp))
            .padding(horizontal = 10.dp, vertical = 6.dp)
            .clickable(interactionSource = remember { MutableInteractionSource() },
                indication = null) { /* 吞掉面板内点击，避免误触收起 */ }
    ) {
        SelectionContainer {
            Text(source.displayTitle, color = Color(0xFFF2EEFA), fontSize = 13.sp,
                modifier = Modifier
                    .heightIn(max = 300.dp)
                    .verticalScroll(rememberScrollState()))
        }
        Text(AppI18n.s(AppI18n.s(AppI18n.s("📋 复制作者"))), color = ACCENT2, fontSize = 13.sp,
            modifier = Modifier
                .padding(top = 8.dp)
                .clickable {
                    val name = author.ifEmpty { fallbackAuthorName(source.displayTitle) }
                    clipboard.setText(AnnotatedString(name))
                    android.widget.Toast.makeText(ctx, AppI18n.sf("已复制作者：%1", name),
                        android.widget.Toast.LENGTH_SHORT).show()
                })
    }
}
