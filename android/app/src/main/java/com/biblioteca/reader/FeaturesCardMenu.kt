package com.biblioteca.reader


import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyGridState
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items as lazyRowItems
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import coil.Coil
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/* 3.7.46：从 MainActivity.kt 搬出（长按卡片操作菜单）。原函数超当时的 80 行 / cc15 预算（2026-10-20 已收紧到 50 行），且 MainActivity 当时已顶到 2739 行文件上限——就地抽函数会让文件行数回升触发 F001，故整体搬到独立文件。 */
/* 3.7.46：从 MainActivity.kt 搬出（长按卡片操作菜单），并由 9 段重复的
 * 「菜单行 + 分隔线」改写为**数据驱动**：菜单项先收集进列表，再统一渲染。
 * 原函数 178 行 / cc 25（9 个 if 各 +1），改后行数与复杂度都进预算。 */

private data class MenuItem(val label: String, val color: Color, val act: () -> Unit)

/** 回调为 null 的项不出现在菜单里（调用方不传该回调 = 不提供这项操作）。 */
private fun menuItem(label: String, color: Color, act: (() -> Unit)?): MenuItem? =
    act?.let { MenuItem(label, color, it) }

private val MENU_TXT = Color(0xFFF2EEFA)      // 中性操作
private val MENU_WARN = Color(0xFFFFC86B)     // 有副作用但可恢复
private val MENU_OK = Color(0xFF7FD4A8)       // 正向操作
private val MENU_DANGER = Color(0xFFFF6B8B)   // 不可逆

/** 面板尺寸与位置：行高固定 → 高度可预知，展开动画不因测量时序跳动。 */
private data class PopupMetrics(val width: Int, val height: Int, val x: Int, val y: Int)

private fun popupMetrics(card: IntRect, compact: Boolean, rows: Int,
                         density: Density, screenWpx: Int): PopupMetrics {
    val pad8 = with(density) { 8.dp.roundToPx() }
    val minW = with(density) { (if (compact) 116.dp else 150.dp).roundToPx() }
    val gap = with(density) { 4.dp.roundToPx() }
    val rowH = with(density) { (if (compact) 32.dp else 44.dp).roundToPx() }
    val width = maxOf(card.width, minW)
    val height = rowH * rows + 1
    // 宽 = 卡片宽（不小于 150dp）：宽相等时左右边缘与卡片严格对齐；卡片过窄则居中并夹取到屏内
    val x = (card.left + (card.width - width) / 2)
        .coerceIn(pad8, (screenWpx - width - pad8).coerceAtLeast(pad8))
    return PopupMetrics(width, height, x, card.bottom - height - gap)
}

/** 单条菜单行（固定行高，文字垂直居中，整行可点）。 */
@Composable
private fun MenuRow(label: String, color: Color, rowH: Int, fs: TextUnit,
                    hpad: Dp, onAct: () -> Unit) {
    val density = LocalDensity.current
    Box(Modifier.fillMaxWidth().height(with(density) { rowH.toDp() }),
        contentAlignment = Alignment.CenterStart) {
        Text(label, color = color, fontSize = fs, maxLines = 1,
            modifier = Modifier.fillMaxWidth().clickable { onAct() }.padding(horizontal = hpad))
    }
}

@Composable
private fun MenuDivider(sepPad: Dp) {
    Box(Modifier.padding(horizontal = sepPad).fillMaxWidth()
        .height(1.dp).background(Color(0x24FFFFFF)))
}

/** 收集菜单项；act 为 null 的项自动剔除（该操作不可用）。 */
private fun buildCardMenuItems(showInfo: Boolean, onInfo: () -> Unit,
                               onDelCover: (() -> Unit)?, onSetCover: (() -> Unit)?,
                               onDownload: (() -> Unit)?, onDownloadAll: (() -> Unit)?,
                               onRename: (() -> Unit)?, onDissolve: (() -> Unit)?,
                               onRemoveZone: (() -> Unit)?, onDelete: (() -> Unit)?): List<MenuItem> =
    listOfNotNull(
        MenuItem(AppI18n.s("✏ 增补信息"), MENU_TXT, onInfo).takeIf { showInfo },
        menuItem(AppI18n.s("🖼 删除首页图片"), MENU_WARN, onDelCover),
        menuItem(AppI18n.s("🏞 设为封面"), MENU_OK, onSetCover),
        menuItem(AppI18n.s("⬇ 下载到本地"), MENU_OK, onDownload),
        menuItem(AppI18n.s("⬇ 下载全部"), MENU_OK, onDownloadAll),
        menuItem(AppI18n.s("✏ 改名"), MENU_TXT, onRename),
        menuItem(AppI18n.s("🕳 解散"), MENU_WARN, onDissolve),
        menuItem(AppI18n.s("🗑 移除分区"), MENU_DANGER, onRemoveZone),
        menuItem(AppI18n.s("🗑 删除"), MENU_DANGER, onDelete))

/** 全屏透明捕获层：点任意处关闭，并回传根坐标原点（供面板定位）。 */
@Composable
private fun MenuScrim(onDismiss: () -> Unit, onPositioned: (IntOffset) -> Unit,
                      content: @Composable () -> Unit) {
    Box(Modifier.fillMaxSize()
        .onGloballyPositioned { p ->
            onPositioned(IntOffset(p.positionInRoot().x.toInt(), p.positionInRoot().y.toInt()))
        }
        .clickable(interactionSource = remember { MutableInteractionSource() },
            indication = null) { onDismiss() }
    ) { content() }
}

/** 变暗覆盖层（仅盖住被选卡片）+ 底边对齐卡片底边的展开面板。 */
@Composable
private fun MenuPanel(m: PopupMetrics, items: List<MenuItem>, density: Density,
                     card: IntRect, origin: IntOffset, shown: Boolean,
                     rowH: Int, fs: TextUnit, hpad: Dp, sepPad: Dp, corner: Dp) {
    Box(Modifier.offset { IntOffset(card.left - origin.x, card.top - origin.y) }
        .size(with(density) { card.width.toDp() }, with(density) { card.height.toDp() })
        .background(Color(0x44000000)))
    Box(Modifier.offset { IntOffset(m.x - origin.x, m.y - origin.y) }
        .height(with(density) { m.height.toDp() })
    ) {
        AnimatedVisibility(
            visible = shown,
            enter = fadeIn() + expandVertically(expandFrom = Alignment.Bottom),
            exit = fadeOut() + shrinkVertically(shrinkTowards = Alignment.Bottom),
            modifier = Modifier.align(Alignment.BottomStart)
        ) {
            MenuItemsColumn(items, density, m.width, corner, rowH, fs, hpad, sepPad)
        }
    }
}

/** 数据驱动渲染菜单行 + 分隔线（行高/字号/内边距已在外层算好）。 */
@Composable
private fun MenuItemsColumn(items: List<MenuItem>, density: Density, widthPx: Int,
                            corner: Dp, rowH: Int, fs: TextUnit, hpad: Dp, sepPad: Dp) {
    Column(
        Modifier
            .width(with(density) { widthPx.toDp() })
            .clip(RoundedCornerShape(corner))
            .background(Color(0xFF1C1433))
            .border(1.dp, ACCENT.copy(alpha = 0x44 / 255f), RoundedCornerShape(corner))
    ) {
        items.forEachIndexed { i, it ->
            MenuRow(it.label, it.color, rowH, fs, hpad, it.act)
            if (i < items.lastIndex) MenuDivider(sepPad)
        }
    }
}

@Composable
fun CardActionPopup(card: IntRect, showInfo: Boolean,
                    onDismiss: () -> Unit, onInfo: () -> Unit,
                    onDelCover: (() -> Unit)?, onDownload: (() -> Unit)? = null,
                    onSetCover: (() -> Unit)? = null,
                    onRename: (() -> Unit)? = null, onDissolve: (() -> Unit)? = null,
                    onDownloadAll: (() -> Unit)? = null,
                    // 3.6.21 原作分区：「移除分区」是与「删除(作品)」语义不同的一项
                    //（只删标签/词条，作品文件不动），故单独给一路文案，不借用 onDelete。
                    onRemoveZone: (() -> Unit)? = null,
                    // compact：卡片本身更小时菜单等比缩小（每日推荐卡 120dp 宽，比常规卡小小一圈）。
                    // 必须放在 onDelete **之前**：尾随 lambda 映射最后一个参数，onDelete 得留在末位。
                    compact: Boolean = false,
                    onDelete: (() -> Unit)? = null) {
    val density = LocalDensity.current
    val screenWpx = with(density) { LocalConfiguration.current.screenWidthDp.dp.toPx().toInt() }
    val rowH = with(density) { (if (compact) 32.dp else 44.dp).roundToPx() }
    val fs = if (compact) 11.sp else 13.sp
    val hpad = if (compact) 11.dp else 14.dp
    val sepPad = if (compact) 8.dp else 10.dp
    val corner = if (compact) 10.dp else 12.dp
    val items = buildCardMenuItems(showInfo, onInfo, onDelCover, onSetCover, onDownload,
        onDownloadAll, onRename, onDissolve, onRemoveZone, onDelete)
    val m = popupMetrics(card, compact, items.size, density, screenWpx)
    var origin by remember { mutableStateOf(IntOffset.Zero) }  // 覆盖层在根坐标中的原点（含安全边距）
    var shown by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { shown = true }
    MenuScrim(onDismiss, { origin = it }) {
        MenuPanel(m, items, density, card, origin, shown, rowH, fs, hpad, sepPad, corner)
    }
}
