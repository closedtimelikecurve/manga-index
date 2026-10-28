package com.biblioteca.reader

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/* ================================================================
   APP 3.7.10：一级界面通用「区域内搜索栏」
   —— 与首页同款药丸交互（点开原地变输入框、✕ 清空），
   搜索范围仅限本页已加载内容（作品/画师/社团本地过滤，不打全库接口）。
   onMenu 传 null 时不渲染「⋯」按钮（本地书架按需求没有菜单）。

   3.7.43 从 Screens31.kt 拆出（与各屏幕同级）：折叠态 pill / 展开态输入框
   是两个独立交互态，各自成函数；右侧 counter/📮/⋯ 挂件随 bar 走。
   ================================================================ */
@Composable
fun RegionSearchBar(query: String, onQueryChange: (String) -> Unit,
                    placeholder: String, onMenu: (() -> Unit)? = null,
                    counter: String = "",
                    // 3.6.9 收件箱入口从抽屉移到一级页右上角（原「未分类」位置）：菜单按钮左侧
                    onOpenInbox: (() -> Unit)? = null) {
    var open by remember { mutableStateOf(false) }
    // 3.7.83（用户需求①）：本栏此前没有底色，背景图直接透上来，像"功能栏有透明度"。
    // 3.7.84：改成 `barTint()` —— 主副色压进不透明底色再画渐变，既有颜色又不透背景
    // （比例比首页略低，因为它紧贴在实色 TopBar 下面，太重会像两条不同的带子）。
    Row(Modifier.fillMaxWidth()
        .background(Brush.horizontalGradient(
            listOf(barTint(ACCENT, 0.16f), barTint(ACCENT2, 0.16f))))
        .padding(horizontal = 10.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically) {
        if (!open) {
            SearchPillCollapsed(Modifier.weight(1f), placeholder) { open = true }
        } else {
            SearchPillInput(Modifier.weight(1f), query, placeholder, onQueryChange) { onQueryChange("") }
        }
        if (counter.isNotEmpty()) {
            Text(counter, color = Color(0xFF9A8FB8), fontSize = 11.sp,
                modifier = Modifier.padding(start = 8.dp))
        }
        if (onOpenInbox != null) {
            Text("📮", color = Color(0xFFF2EEFA), fontSize = 16.sp,
                modifier = Modifier.clickable { onOpenInbox() }.padding(horizontal = 6.dp))
        }
        if (onMenu != null) {
            IconButton(onClick = onMenu) { Text("⋯", color = Color(0xFFF2EEFA), fontSize = 20.sp) }
        }
    }
}

/** 折叠态：🔍 + 占位文字的药丸，点一下原地展开。 */
@Composable
private fun SearchPillCollapsed(modifier: Modifier, placeholder: String, onOpen: () -> Unit) {
    Row(modifier
        .clip(RoundedCornerShape(20.dp))
        .background(CARD_BG2)
        .clickable { onOpen() }
        .padding(horizontal = 14.dp, vertical = 9.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text("🔍", fontSize = 13.sp)
        Text(" $placeholder", color = Color(0xFF9A8FB8), fontSize = 13.sp,
            maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** 展开态：自动对焦的输入框 + 占位提示 + ✕ 清空。 */
@Composable
private fun SearchPillInput(modifier: Modifier, query: String, placeholder: String,
                            onQueryChange: (String) -> Unit, onClear: () -> Unit) {
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { focus.requestFocus() }
    Row(modifier
        .clip(RoundedCornerShape(20.dp))
        .background(CARD_BG2)
        .padding(horizontal = 14.dp, vertical = 9.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text("🔍", fontSize = 13.sp)
        BasicTextField(
            value = query, onValueChange = onQueryChange, singleLine = true,
            textStyle = TextStyle(color = Color(0xFFF2EEFA), fontSize = 13.sp),
            cursorBrush = SolidColor(ACCENT),
            modifier = Modifier.weight(1f).padding(start = 6.dp).focusRequester(focus),
            decorationBox = { inner ->
                Box {
                    if (query.isEmpty()) Text(" $placeholder",
                        color = Color(0xFF9A8FB8), fontSize = 13.sp,
                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                    inner()
                }
            })
        Text("✕", color = Color(0xFF9A8FB8), fontSize = 13.sp,
            modifier = Modifier.clickable { onClear() }.padding(start = 8.dp))
    }
}
