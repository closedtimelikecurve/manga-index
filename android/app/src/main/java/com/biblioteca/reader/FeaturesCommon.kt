package com.biblioteca.reader

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/* ================================================================
   Features 公共层（3.7.43 从 Features.kt 拆出）：
   标签交互（长按复制）/ 分区排序 chip / 主题常量 / 输入栏配色 /
   页头 / 返回键 / FlowRow 封装 / 离线横幅 / 快照时间格式。
   各业务屏（搜索/标签/信息/导入/爬虫/别名）共用。
   ================================================================ */

/**
 * 标签统一交互（3.7.40 起全站一致）：**点击照旧跳转 + 长按复制标签文本**。
 *
 * 历史：3.6.x 曾因"卡片长按弹菜单 + 同时弹复制条"冲突撤掉过长按复制（SelectionContainer
 * 与 combinedClickable 并存时，长按会同时触发两者）。本次只给**标签 chip** 加回长按复制 ——
 * 标签所在区域与封面区（长按弹菜单）不重叠，不会重现那个冲突。
 *
 * 用法：把标签上的 `.clickable { 跳转 }` / `.combinedClickable(onClick = …)`
 * 换成 `.tagClickable(标签文本) { 跳转 }`，全站标签行为即统一。
 */
@OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)
@Composable
fun Modifier.tagClickable(text: String, onClick: () -> Unit): Modifier {
    val ctx = LocalContext.current
    return this.combinedClickable(
        onClick = onClick,
        onLongClick = {
            val cm = ctx.getSystemService(android.content.Context.CLIPBOARD_SERVICE)
                    as android.content.ClipboardManager
            cm.setPrimaryClip(android.content.ClipData.newPlainText("tag", text))
            android.widget.Toast.makeText(ctx, AppI18n.sf("已复制：%1", text),
                android.widget.Toast.LENGTH_SHORT).show()
        }
    )
}

/** 3.7.40：仅长按复制（标签没有跳转目标时用——如作品卡上的社团名）。
 *  不加背景/内边距，保持原有排版不变，只补上"长按可复制"这一层交互。 */
@Composable
fun Modifier.tagCopy(text: String): Modifier = tagClickable(text) {}

/**
 * 作品列表排序（3.6.151，社团页 / 画师页 / 原作分区页共用）。
 *   mode = "time"（入库时间，默认）/ "size"（**文件大小**，查重用：重复下载体积相近）/
 *          "name"（名称）；
 *   asc = true → 由旧到新 / 由小到大 / A→Z；asc = false → 由新到旧 / 由大到小 / Z→A（默认）。
 * 箭头固定朝下（用户要求），只有文字随方向变。
 */
fun <T> sortWorksList(items: List<T>, mode: String, asc: Boolean,
                      timeOf: (T) -> Double, sizeOf: (T) -> Long,
                      nameOf: (T) -> String): List<T> {
    val cmp = Comparator<T> { a, b ->
        if (mode == "name") {
            val n = nameOf(a).compareTo(nameOf(b))
            if (asc) n else -n
        } else {
            val ka = if (mode == "size") sizeOf(a).toDouble() else timeOf(a)
            val kb = if (mode == "size") sizeOf(b).toDouble() else timeOf(b)
            var r = when {
                ka < kb -> -1
                ka > kb -> 1
                else -> 0
            }
            // 3.6.152：升序比较结果已经是「由旧到新」，只有要降序时才取反（见 Api.sortCircles 同款注释）。
            if (!asc) r = -r
            if (r != 0) r else nameOf(a).compareTo(nameOf(b))
        }
    }
    return items.sortedWith(cmp)
}

/** 作品列表排序条：时间 / 文件大小 / 名称 + 方向键（方向键文案见 workDirLabel 口径）。 */
@Composable
fun WorksSortBar(mode: String, asc: Boolean,
                 onSort: (String, Boolean) -> Unit, modifier: Modifier = Modifier) {
    val modes = listOf("time" to AppI18n.s("时间"), "size" to AppI18n.s("文件大小"),
                       "name" to AppI18n.s("名称"))
    val dirLabel = when (mode) {
        "size" -> if (asc) AppI18n.s("↓ 由小到大") else AppI18n.s("↓ 由大到小")
        "name" -> if (asc) AppI18n.s("↓ A→Z") else AppI18n.s("↓ Z→A")
        else -> if (asc) AppI18n.s("↓ 由旧到新") else AppI18n.s("↓ 由新到旧")
    }
    SortBar(modes, mode, asc, onSort, dirLabel, onDir = { onSort(mode, !asc) }, modifier = modifier)
}

// 主题常量与 MainActivity 保持一致。
// 3.7.73：ACCENT/ACCENT2 运行时可变（ThemePrefs 切换即全 App 重组生效）；BG/TXT 等
// 结构色仍为常量。
internal val BG = Color(0xFF08060F)
internal val CARD_BG = Color(0xFF140F22)
internal val CARD_BG2 = Color(0xFF1C1433)
internal val TXT = Color(0xFFF2EEFA)
internal val MUTED = Color(0xFF9A8FB8)

/** 带主副色的**不透明**功能栏底色（3.7.84）。
 *
 *  历史：3.7.83 为了去掉"功能栏透出背景图"，把顶栏改成实色 `CARD_BG`，
 *  结果原来那种"主副色染色"没了，只剩一层近黑的紫底（用户反馈：没以前好看）。
 *  旧做法是 `ACCENT.copy(alpha = 0x33)` —— 靠**半透明**在背景图上染色，
 *  这正是"透"的来源。现在改成 `compositeOver(CARD_BG)`：先把主色按同样比例
 *  压进不透明底色里，得到一个**不透明**的染色值再画渐变。
 *  视觉上等价于旧版的染色效果，但背景图一点都透不过来。 */
internal fun barTint(color: Color, ratio: Float = 0.22f): Color =
    color.copy(alpha = ratio).compositeOver(CARD_BG)

/** 展示名解码（3.6.139，与服务端 common.display_name 同源）：Windows 文件名禁 `|`，
 *  旧库把它编码成字面 `&#124;` 存盘。只用于 Text/展示标题；key、onOpenReader、
 *  coverUrl 等标识符必须继续用原始名，否则查不到库。 */
internal fun String.dispWorkName(): String = replace("&#124;", "|")
internal var ACCENT by mutableStateOf(Color(0xFFFF3DF2))
internal var ACCENT2 by mutableStateOf(Color(0xFFB06BFF))
internal val ERR = Color(0xFFFF5ED0)

// 3.7.93 函数化：顶层 const 会固化 s()，切语言冻住（与网页 themePresets 同坑）
internal fun tagLabels() = mapOf(
    "original" to AppI18n.s("同人"), "event" to AppI18n.s("展会"), "personal" to AppI18n.s("画师"),
    "group" to AppI18n.s("汉化组"), "other" to AppI18n.s("其他")
)

/** 输入栏高对比度配色：默认灰色文字在深色背景上几乎不可读（搜索/设置/文档共用） */
@Composable
internal fun appFieldColors() = androidx.compose.material3.OutlinedTextFieldDefaults.colors(
    focusedTextColor = TXT, unfocusedTextColor = TXT, disabledTextColor = MUTED,
    cursorColor = ACCENT,
    focusedLabelColor = Color(0xFFCFC4E8), unfocusedLabelColor = MUTED,
    focusedBorderColor = ACCENT2, unfocusedBorderColor = Color(0xFF3A3550),
)

@Composable
internal fun TopBar(title: String, onBack: () -> Unit, trailing: (@Composable () -> Unit)? = null) {
    // 3.7.82（用户需求②）：顶部功能栏不再透出背景图——与网页 header 同一种实色（CARD_BG）。
    Row(Modifier.fillMaxWidth().background(CARD_BG).padding(16.dp, 12.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text("←", color = TXT, fontSize = 20.sp,
            modifier = Modifier.clickable { onBack() }.padding(end = 10.dp))
        Text(title, color = TXT, fontSize = 18.sp,
            modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
        // 3.7.54：右上角插槽（分区页放「⛏ 分区爬虫」入口；不传则与原来完全一致）
        trailing?.invoke()
    }
}

@Composable
fun BackHandlerOn(onBack: () -> Unit) {
    androidx.activity.compose.BackHandler { onBack() }
}

/** FlowRow 的轻封装（隔离 ExperimentalLayoutApi 注解） */
@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
fun FlowRowCompat(horizontalArrangement: Arrangement.Horizontal,
                  verticalArrangement: Arrangement.Vertical,
                  content: @Composable androidx.compose.foundation.layout.FlowRowScope.() -> Unit) {
    androidx.compose.foundation.layout.FlowRow(
        horizontalArrangement = horizontalArrangement,
        verticalArrangement = verticalArrangement, content = content)
}

/** 快照时间戳的短格式（与网页 fmtStamp 同语义） */
private fun fmtStampShelf(ts: Long): String {
    if (ts <= 0) return AppI18n.s("（未知时间）")
    val d = java.util.Date(ts * 1000L)
    return android.text.format.DateFormat.format("yyyy-MM-dd HH:mm:ss", d).toString()
}

/**
 * 3.7.37：统一的「离线模式」黄色警告条（一级界面顶部）。
 *
 * 用户要求取消"连不上服务器"的弹窗（每轮断线弹一次、还挡手势），改成与本地书架页
 * 同款的黄色横幅，插入首页/续读/喜爱/本地书架四个一级界面顶部——离线是**状态**，
 * 应该常驻可感知，而不是靠一个必须点掉的对话框提醒。
 */
@Composable
fun OfflineBanner(onRetry: () -> Unit = {}, modifier: Modifier = Modifier) {
    Row(modifier.fillMaxWidth().padding(horizontal = 12.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(Color(0x33FFC86B))
            .border(1.dp, Color(0x66FFC86B), RoundedCornerShape(10.dp))
            .padding(horizontal = 12.dp, vertical = 9.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(AppI18n.s("📴 离线模式：连不上服务器，本地内容照常可用，进度会在联网后同步"),
            color = Color(0xFFFFC86B), fontSize = 11.sp, lineHeight = 15.sp,
            modifier = Modifier.weight(1f))
        Text(AppI18n.s("重试连接"), color = Color(0xFFF2EEFA), fontSize = 12.sp,
            modifier = Modifier.clickable { onRetry() }.padding(start = 8.dp))
    }
}

/** 四态提示盒（加载 / 失败 / 空输入 / 无结果）——搜索页与标签检索页共用。
 *  3.7.46：原为 FeaturesSearch.kt 的 private，标签页也要用，提到公共文件。 */
@Composable
fun SearchHint(content: @Composable () -> Unit) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { content() }
}

