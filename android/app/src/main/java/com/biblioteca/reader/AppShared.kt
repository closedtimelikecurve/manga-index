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

sealed interface Screen {
    data object Blacklist : Screen
    data object Aliases : Screen           // 3.6.11 原 Maintenance（维护收归面板本地，只留别名登记）
    data object Home : Screen
    data class Circle(val name: String) : Screen
    data class Reader(val group: String, val work: String, val localKey: String? = null) : Screen
    data object Shelf : Screen
    data object Downloads : Screen          // 3.7.13 下载管理（并发队列）
    data object Resume : Screen
    data object Favorites : Screen
    data object Stats : Screen
    data object Inbox : Screen
    data class TagWorks(val type: String, val tag: String) : Screen
    data class Artist(val name: String) : Screen
    data object Import : Screen
    data object Crawl : Screen
    data class Probe(val kind: String, val term: String, val site: String = "wnacg") : Screen   // 3.7.57 站点
    data class Info(val group: String, val work: String) : Screen
    data object Lang : Screen               // 3.7.74 语言二级界面（原是抽屉内嵌区块）
    data object Theme : Screen              // 3.7.74 主题二级界面（配色/取色器/背景图库）
    data object ThemeGallery : Screen      // 3.7.76 图库三级界面（增删改查）
}

/* 阅读器音量键翻页的跨层通道：ReaderScreen 进入时置 active 并挂回调，
   离开时复位（音量键恢复系统行为）。由 MainActivity.dispatchKeyEvent 消费。 */
object ReaderVolume {
    @Volatile var active: Boolean = false
    @Volatile var onTurn: ((Int) -> Unit)? = null    // 参数 = +1 下一页 / -1 上一页
}

/* ---- 3.5.0 阅读消费端角标（网页对称）：已读✓ / 读到第 n 页 / 新入库 ----
   启动联网后拉一次（mark-seen 盖基线 → summary 拿全量状态与新增清单）；
   阅读器退出时再刷一次（刚读的作品本地即时更新，"有新"基准随之后移）。 */
object ReadingHub {
    data class Rd(val p: Int, val f: Boolean)
    var states by androidx.compose.runtime.mutableStateOf<Map<String, Rd>>(emptyMap())
        private set
    var newKeys by androidx.compose.runtime.mutableStateOf<Set<String>>(emptySet())
        private set
    @Volatile var loaded = false
        private set
    private val scope = kotlinx.coroutines.CoroutineScope(
        kotlinx.coroutines.SupervisorJob() + Dispatchers.IO)

    /** 拉取/刷新角标数据；离线或失败静默（角标是增强，绝不影响浏览）。 */
    fun refreshAsync() {
        scope.launch {
            try {
                val prev = Api.markSeen()
                val s = Api.readingSummary(prev)
                states = s.states.mapValues { (_, v) -> Rd(v.first, v.second) }
                newKeys = s.newKeys
                loaded = true
            } catch (_: Exception) { }
        }
    }

    fun rdOf(group: String, work: String): Rd? = states["$group/$work"]
    fun isNew(group: String, work: String): Boolean = loaded && newKeys.contains("$group/$work")
    fun newCountInCircle(name: String): Int =
        if (!loaded) 0 else newKeys.count { it.startsWith("$name/") }
}

// ---- 搜索状态（文件级，HomeScreen 顶层函数与 NavHost 的 onBack/onExit 共享） ----
// 搜索是内联 overlay 而非独立 Screen；从搜索结果点进作品/画师/社团后返回时，需由 NavHost 各返回点
// 恢复 searchOpen，故状态需对 HomeScreen 与 NavHost 同时可见。放在文件顶层（全局可观察 State）。
var searchOpen by mutableStateOf(false)
var pendingSearchRestore by mutableStateOf(false)
var q by mutableStateOf("")
var searching by mutableStateOf(false)
var searchError by mutableStateOf("")
var sGroups by mutableStateOf<List<Api.Group>>(emptyList())
var sWorks by mutableStateOf<List<Api.WorkHit>>(emptyList())
var sAuthors by mutableStateOf<List<Api.TagItem>>(emptyList())

// ---- 3.6.19「添加原作」（文件级：首页入口与 NavHost 刷新后跳转新分区共用） ----
var addOriginalOpen by mutableStateOf(false)
// 待移除确认的原作分区名（长按分区卡 → 确认框；null = 不显示）
var removeOriginalTarget by mutableStateOf<String?>(null)

// ---- 3.7.10 全局菜单抽屉 ----
// 抽屉原先只属于首页（HomeScreen 内的局部 remember），续读/喜爱/本地书架三个一级页
// 拿不到它，左滑手势更无处可唤。提升为文件级：任何界面（含 App 级手势）都能开关同一个抽屉。
var appDrawerOpen by mutableStateOf(false)
