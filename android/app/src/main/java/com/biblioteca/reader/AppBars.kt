@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class, androidx.compose.foundation.ExperimentalFoundationApi::class)
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
import androidx.compose.material3.Checkbox
import androidx.compose.material3.TextButton
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import coil.Coil
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.CoroutineScope

/** 排序条(3.4.0)：档位 + 方向键——分区列表 / 社团列表 / 作品列表共用同一外观 */
@Composable
internal fun SortBar(modes: List<Pair<String, String>>, mode: String, asc: Boolean,
                     onSort: (String, Boolean) -> Unit, dirLabel: String, onDir: () -> Unit,
                     modifier: Modifier = Modifier) {
    // 3.7.40：行内容可横滑——社团四档 + 方向键在窄屏会溢出（用户报障"按键被挤坏"）。
    // 首页三种信息流与分区内部共用同一外观/间距，位置统一在内容区顶部。
    Row(modifier.fillMaxWidth().padding(horizontal = 2.dp),
        verticalAlignment = Alignment.CenterVertically) {
        // 3.7.41：**只有档位可横滑**，方向键固定在右侧不跟着滚（用户报障：
        // 逆序键跟着一起滚走了，想翻方向还得先滑回来）
        Row(Modifier.weight(1f).horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Text(AppI18n.s("排序"), color = MUTED, fontSize = 11.sp)
            modes.forEach { (m, label) ->
                val on = mode == m
                Text(label, color = if (on) TXT else MUTED, fontSize = 11.sp, maxLines = 1,
                    modifier = Modifier
                        .clip(RoundedCornerShape(999.dp))
                        .background(if (on) ACCENT.copy(alpha = 0x33 / 255f) else CARD_BG2)
                        .border(1.dp, if (on) ACCENT else Color(0x24FFFFFF),
                            RoundedCornerShape(999.dp))
                        .clickable { onSort(m, asc) }
                        .padding(horizontal = 8.dp, vertical = 6.dp))
            }
        }
        Text(dirLabel, color = ACCENT, fontSize = 11.sp, maxLines = 1,
            modifier = Modifier.padding(start = 6.dp)
                .clip(RoundedCornerShape(999.dp))
                .background(ACCENT.copy(alpha = 0x22 / 255f))
                .border(1.dp, ACCENT, RoundedCornerShape(999.dp))
                .clickable { onDir() }
                .padding(horizontal = 8.dp, vertical = 6.dp))
    }
}

/** 页面右上角的胶囊按钮（3.6.152）：分区页「＋ 添加」的规格，现也用于「⛏ 联网获取」。
 *  字色 ACCENT / 13sp、底色 ACCENT 22% 扁透明、999 圆角、10×4 内边距——两个入口同一套。 */
@Composable
internal fun TopChip(label: String, onClick: () -> Unit) {
    Text(label, color = ACCENT, fontSize = 13.sp, maxLines = 1,
        modifier = Modifier.clip(RoundedCornerShape(999.dp))
            .background(ACCENT.copy(alpha = 0x33 / 255f))
            .clickable { onClick() }
            .padding(horizontal = 10.dp, vertical = 4.dp))
}

/** 画师/原作分区排序条（保留原函数名，调用点不变）。 */
@Composable
internal fun FeedSortBar(mode: String, asc: Boolean, onSort: (String, Boolean) -> Unit,
                        showCreated: Boolean = false) {
    // 画师视图没有"创建次序"档；此时默认态 created 按"作品数量"高亮，行为也一致
    val eff = if (!showCreated && mode == "created") "works" else mode
    // 3.6.152：与社团排序条同口径——箭头固定朝下，只有文字随"维度 + 方向"变。
    // 旧版这里是 ↑/↓ 翻转，且 created/latest 共用"由少到多"一句（维度名与方向说明打架）。
    val dirLabel = if (eff == "works") {
        if (asc) AppI18n.s("↓ 由少到多") else AppI18n.s("↓ 由多到少")
    } else {
        if (asc) AppI18n.s("↓ 由旧到新") else AppI18n.s("↓ 由新到旧")
    }
    val modes = buildList {
        if (showCreated) add("created" to AppI18n.s("创建次序"))
        add("works" to AppI18n.s("作品数量"))
        add("latest" to AppI18n.s("最新入库"))
    }
    // 方向键只翻方向、不换维度：传 eff 而不是 raw mode，画师视图点方向键不会顺手切档
    SortBar(modes, eff, asc, onSort, dirLabel, onDir = { onSort(eff, !asc) })
}

/** 社团排序条：最近入库 / 创建时间 / 作品数量 + 方向键。
 *  3.6.166：**去掉「文件大小」档**——用户要求大小排序只在分区内部按作品排，
 *  社团层面不需要。存量偏好存着 size 的，AppState 里已回落成 updated。 */
@Composable
internal fun CircleSortBar(mode: String, asc: Boolean, onSort: (String, Boolean) -> Unit) {
    val modes = listOf("updated" to AppI18n.s("最近入库"), "created" to AppI18n.s("创建时间"),
                       "count" to AppI18n.s("作品数量"))
    // 3.6.151：**箭头固定朝下**（表示列表从上到下的方向），只有文字随正/倒序变。
    // 用户明确要求：箭头跟着翻转会让人误以为排序维度变了，实际只是顺序反过来。
    val dirLabel = when {
        mode == "count" -> if (asc) AppI18n.s("↓ 由少到多") else AppI18n.s("↓ 由多到少")
        else -> if (asc) AppI18n.s("↓ 由旧到新") else AppI18n.s("↓ 由新到旧")
    }
    SortBar(modes, mode, asc, onSort, dirLabel, onDir = { onSort(mode, !asc) })
}


/* ---- 一级界面切换胶囊（对齐官方 wnacg 底部导航形态）：滑动指示器 + spring 物理回弹 ----
   指示器是一枚独立滑块，切换时以 spring 动画滑到目标 tab（官方同款"丝滑"手感）；
   离线模式下书库入口隐藏（首页不可达），胶囊只剩「本地」。 */

/** tab 元数据：路由 key → (名称, emoji)——名称走 AppI18n.s（3.7.73 多语言）。 */
internal val TAB_LABELS = listOf(   // i18n:data 名称是 key，显示处统一 AppI18n.s
    Triple("home", "书库", "📚"),   // i18n:data key 定义，显示处统一 AppI18n.s
    Triple("resume", "续读", "📖"),   // i18n:data key 定义，显示处统一 AppI18n.s
    Triple("favorites", "喜爱", "❤"),   // i18n:data key 定义，显示处统一 AppI18n.s
    Triple("shelf", "本地", "📥"),   // i18n:data key 定义，显示处统一 AppI18n.s
)

@Composable
fun BottomCapsule(active: String, onHome: () -> Unit, onResume: () -> Unit,
                  onFavorites: () -> Unit = {}, onShelf: () -> Unit,
                  modifier: Modifier = Modifier) {
    val tabs = listOf("home", "resume", "favorites", "shelf")
    val activeIdx = (tabs.indexOf(active)).coerceAtLeast(0)
    // 3.7.76：66dp 放不下俄语等长译文（两行裁半），放宽到 76dp + maxLines=1 兜底
    val tabW = 76.dp
    // spring 物理动画：MediumBouncy 阻尼 = 官方那种带一点回弹的丝滑滑动
    val indicatorX by androidx.compose.animation.core.animateDpAsState(
        targetValue = tabW * activeIdx,
        animationSpec = androidx.compose.animation.core.spring(
            dampingRatio = androidx.compose.animation.core.Spring.DampingRatioMediumBouncy,
            stiffness = androidx.compose.animation.core.Spring.StiffnessMediumLow),
        label = "capsuleIndicator")
    Box(modifier.clip(RoundedCornerShape(999.dp))
        .background(Color(0xF2140F22))
        .border(1.dp, ACCENT.copy(alpha = 0x33 / 255f), RoundedCornerShape(999.dp))
        .padding(4.dp)) {
        // 滑动指示器（在 tab 内容层之下）
        Box(Modifier.offset(x = indicatorX).width(tabW).height(36.dp)
            .clip(RoundedCornerShape(999.dp)).background(ACCENT2))
        Row {
            tabs.forEach { t ->
                val on = t == active
                Box(Modifier.width(tabW).height(36.dp).clickable {
                    when (t) {
                        "home" -> onHome()
                        "resume" -> onResume()
                        "favorites" -> onFavorites()
                        else -> onShelf()
                    }
                }, contentAlignment = Alignment.Center) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        // 3.7.73：文案走 AppI18n.s（tab 名/图标查表，随语言切换即时重组）
                        val tab = TAB_LABELS.firstOrNull { it.first == t }
                        Text(tab?.third ?: "",
                            fontSize = 13.sp,
                            color = if (on) Color(0xFF1C1433) else Color(0xFF9A8FB8))
                        // 3.7.76：maxLines=1 —— 修复长译文折成两行、下行被胶囊裁一半
                        Text(AppI18n.s(tab?.second ?: ""),
                            color = if (on) Color(0xFF1C1433) else Color(0xFF9A8FB8), fontSize = 12.sp,
                            maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
        }
    }
}

// 抽屉里的整行菜单条目（仿侧边栏样式，整行可点）
@Composable
fun DrawerRow(text: String, onClick: () -> Unit) {
    Text(text, color = Color(0xFFF2EEFA), fontSize = 15.sp,
        modifier = Modifier.fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 20.dp, vertical = 14.dp))
}

/* 3.7.110 内测模式：抽屉里的开关行。
   整行可点（不是只有开关能点）——手机上 15sp 的文字比开关本体好按。
   配色显式指定：抽屉是固定深底（0xFF140F22），Material 默认的 secondaryContainer
   在这个底色上几乎看不见，与 DrawerRow 的显式 0xFFF2EEFA 同理。 */
@Composable
fun DrawerSwitchRow(text: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth()
        .clickable { onChange(!checked) }
        .padding(horizontal = 20.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(text, color = Color(0xFFF2EEFA), fontSize = 15.sp)
        Spacer(Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onChange,
            colors = SwitchDefaults.colors(
                checkedThumbColor = Color(0xFFFFFFFF),
                checkedTrackColor = ThemePrefs.accent,
                uncheckedThumbColor = Color(0xFFB9AFD0),
                uncheckedTrackColor = Color(0xFF2A2340)))
    }
}

/* ---- 3.5.0 作品卡阅读角标（与网页 makeWorkCard 同款语义，双端对称）----
   右上：✓已读（绿）/ 读n（上次读到第 n+1 页）；左上：新（基线后新入库）。
   ReadingHub 未加载（离线/首次）时整体静默，不占位。 */
@Composable
fun BoxScope.ReadingBadges(group: String, work: String) {
    if (!ReadingHub.loaded) return
    val rd = ReadingHub.rdOf(group, work)
    if (rd != null) {
        Text(if (rd.f) AppI18n.s("✓ 已读") else AppI18n.sf("读%1", rd.p + 1),
            color = if (rd.f) Color(0xFF7FD4A8) else Color(0xFFCFC4E8),
            fontSize = 9.sp, maxLines = 1,
            modifier = Modifier.align(Alignment.TopEnd).padding(4.dp)
                .clip(RoundedCornerShape(999.dp))
                .background(Color(0xB3060411)).padding(horizontal = 6.dp, vertical = 2.dp))
    }
    if (ReadingHub.isNew(group, work)) {
        Text(AppI18n.s("新"), color = Color(0xFF1C1433), fontSize = 9.sp,
            modifier = Modifier.align(Alignment.TopStart).padding(4.dp)
                .clip(RoundedCornerShape(999.dp))
                .background(ACCENT2).padding(horizontal = 6.dp, vertical = 2.dp))
    }
}

// 长按卡片弹出的操作菜单：面板与卡片左右边缘对齐（卡片过窄时居中放宽）、底边贴卡片底边，
// 完全位于卡片上方淡入；点空白遮罩关闭
