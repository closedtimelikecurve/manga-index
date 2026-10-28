package com.biblioteca.reader

import android.app.Activity
import android.content.Context
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.imageLoader
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/* ================================================================
   阅读器 v3（对齐官方 wnacg APP 的阅读体验）——屏壳（3.7.43 重构）
   * 顶栏分段胶囊开关：单页 | 滚动 二选一
   * 自绘细滑轨 + 拖动页码气泡（点轨道直跳、拖动实时预览）
   * 未加载页 3:4 占位卡（一眼看清全文页数与未载入的页），载入失败
     显示「点击重试」（对齐官方文案「第 n 页载入失败」）
   * 沉浸模式：单页模式点中央 40% 切换工具栏、左右 30% 翻页；滚动模式点按不翻页，
     工具栏显示时点按隐藏、隐藏时点图片放大（再次点击恢复，优先级低于工具栏）；
     工具栏 3 秒无操作自动淡出
   * 音量键翻页（在阅读器内接管音量键，离开自动恢复）
   * 阅读期间屏幕常亮

   结构（3.7.43，原单函数 354 行 / cc 59）：
   屏壳只留编排；UI 状态收进 [ReaderUiState]（纪律 §4.1"状态对象化"）；
   模式/媒体/滑轨/顶栏/放大/音声/标题展开各自独立文件。
   ================================================================ */

/** 阅读器 UI 状态：把散在屏幕里的十来个 state 收成一个对象，交互方法与状态同处一地。 */
internal class ReaderUiState(prefs: android.content.SharedPreferences) {
    private val prefs = prefs
    var mode by mutableStateOf(prefs.getString("rd_mode", "page") ?: "page")
    var page by mutableIntStateOf(0)
    var absTotal by mutableIntStateOf(-1)          // 绝对总页数(未过滤版本)
    var kindsAbs by mutableStateOf<List<String>?>(null)
    var versions by mutableStateOf<List<ReaderVersion>>(emptyList())
    var selVersion by mutableIntStateOf(0)
    var error by mutableStateOf("")
    var titleOpen by mutableStateOf(false)         // 标题展开文本泡
    var barsVisible by mutableStateOf(true)
    var tick by mutableIntStateOf(0)               // 交互计数：工具栏淡出计时器的重启键
    var gestureActive by mutableStateOf(false)     // 滑动/翻页手势进行中
    var zoomPage by mutableIntStateOf(-1)          // -1 = 未放大
    var author by mutableStateOf("")
    // 标题展开面板锚定：标题文本与根容器在根坐标中的边界（Windows 重命名式原地展开）
    var origin by mutableStateOf(IntOffset.Zero)
    var titleRect by mutableStateOf(IntRect.Zero)

    /** 3.4.0 版本过滤后的"显示空间"：display = 显示页位 → 绝对页序。
     *  多版本作品(如 RJ 包 日文原版/汉化版):页面/页码/进度条都在所选版本内编号;
     *  阅读进度上报与续读仍用绝对页序(pageAt 映射),跨版本跨端一致。 */
    val display: List<Int>
        get() = if (versions.isEmpty()) (0 until absTotal).toList()
        else versions.getOrElse(selVersion.coerceAtLeast(0)) { ReaderVersion("", emptyList()) }.idx
    val total: Int get() = display.size
    val dispKinds: List<String>?
        get() = kindsAbs?.let { k -> display.map { k.getOrElse(it) { "image" } } }
    val pageAt: (Int) -> Int get() = { d -> display.getOrElse(d) { d } }

    fun interact() { tick++; if (!barsVisible) barsVisible = true }
    fun turn(delta: Int) {
        if (total > 0) page = (page + delta).coerceIn(0, total - 1)
        zoomPage = -1                          // 翻页时退出放大
        if (barsVisible) tick++               // 仅重置淡出计时，不强制唤出
    }
    /** onStageTap：frac = 点击位置在宽度中的比例 0..1（左右 30% 翻页，中间 40% 切工具栏）。 */
    fun onStageTap(frac: Float) {
        when {
            frac < 0.3f -> turn(-1)
            frac > 0.7f -> turn(1)
            else -> { barsVisible = !barsVisible; tick++ }
        }
    }
    fun switchMode(m: String) { mode = m; prefs.edit().putString("rd_mode", m).apply(); interact() }

    /** 3.4.0 版本切换:保留同内容页(按绝对页序匹配),否则落到该版本首页。 */
    fun versionJump(vi: Int) {
        if (vi !in versions.indices || vi == selVersion) return
        val targetAbs = if (total > 0) pageAt(page.coerceIn(0, total - 1)) else 0
        selVersion = vi
        page = versions[vi].idx.indexOf(targetAbs).coerceAtLeast(0)
        zoomPage = -1
        tick++
    }

    /** 元数据加载结果落账（顺序即语义：先空间后定位）。 */
    fun applyMeta(r: ReaderMetaResult) {
        absTotal = r.total
        versions = r.versions
        selVersion = r.selVersion
        kindsAbs = r.kinds
        if (r.page > 0) page = r.page
    }
}

/** 元数据加载 + 续读定位的一次性结果（3.7.43）。 */
internal data class ReaderMetaResult(val total: Int, val versions: List<ReaderVersion>,
                                    val kinds: List<String>?, val selVersion: Int, val page: Int)

@Composable
fun ReaderScreen(source: ReaderSource, onExit: () -> Unit) {
    val ctx = LocalContext.current
    val prefs = remember { ctx.getSharedPreferences("biblioteca", Context.MODE_PRIVATE) }
    // 3.7.63：按作品做键。原来 remember{} 不随 source 变：换一部作品时页码/缩放沿用
    // 上一部的（新作品没有续读进度 → applyMeta 不覆盖 page，直接停在上一部的页码）。
    val ui = remember(source) { ReaderUiState(prefs) }
    // ---- 元数据加载 + 续读定位 ----
    ReaderMetaEffect(source, onLoaded = { ui.applyMeta(it) }, onError = { ui.error = it })
    // ---- 音声模式（v3.0.1）：音频轨 + lrc 同步字幕，与漫画页同屏；无音声作品不出现入口 ----
    var audioTracks by remember(source) { mutableStateOf<List<Api.AudioTrack>>(emptyList()) }
    var audioOn by remember(source) { mutableStateOf(false) }
    LaunchedEffect(source) {
        audioTracks = try { source.audioTracks() } catch (_: Exception) { emptyList() }
        if (audioTracks.isEmpty()) audioOn = false
    }
    // 返回键：展开中先收面板，否则退出阅读器
    BackHandler(enabled = ui.titleOpen) { ui.titleOpen = false }
    BackHandler { onExit() }

    ReaderEffects(source, ui)

    Box(Modifier.fillMaxSize().background(Color(0xFF060411))
        .onGloballyPositioned { p ->
            ui.origin = IntOffset(p.positionInRoot().x.toInt(), p.positionInRoot().y.toInt())
        }) {
        ReaderStage(source, ui)
        // ---- 单独图片界面（对齐官方）：滚动模式双击图片进入；内部双击 2x 缩放，
        //      单击退出回到连续阅读并唤出工具栏 ----
        if (ui.zoomPage >= 0) {
            ReaderZoomOverlay(source, ui)
        }
        // ---- 顶栏（悬浮 overlay，可沉浸隐藏）----
        ReaderTopBar(source, ui, audioTracks.isNotEmpty(), audioOn,
            onAudioToggle = { audioOn = !audioOn; ui.interact() },
            onExit = onExit,
            onTitleRect = { ui.titleRect = it },
            modifier = Modifier.align(Alignment.TopStart))
        // ---- 音声面板（悬浮 overlay：贴底、漫画滑轨之上）——字幕同步 + 播放控制 + 轨道切换 ----
        ReaderAudioPanel(source, audioTracks, audioOn,
            modifier = Modifier.align(Alignment.BottomStart).navigationBarsPadding()
                .padding(horizontal = 12.dp).padding(bottom = 36.dp))
        // ---- 滑轨（悬浮 overlay 贴底，无任何底色面积）：细轨 + 右侧极小页码 ----
        ReaderSliderRow(ui.page, ui.total, ui.barsVisible,
            onSeek = { p -> ui.page = p; ui.tick++ },
            modifier = Modifier.align(Alignment.BottomStart).navigationBarsPadding())
        // ---- 标题展开（Windows 重命名式原地展开）----
        ReaderTitlePopup(source, ui.titleOpen, ui.titleRect, ui.origin, ui.author,
            onClose = { ui.titleOpen = false })
    }
}

/** 单独图片界面覆盖层（对齐官方）：黑底 + 可缩放大图；单击退出并唤出工具栏。 */
@Composable
private fun ReaderZoomOverlay(source: ReaderSource, ui: ReaderUiState) {
    Box(Modifier.fillMaxSize().background(Color.Black)) {
        ZoomableImage(source = source, pageNo = ui.zoomPage, absNo = ui.pageAt(ui.zoomPage),
            total = ui.total,
            onClose = { ui.zoomPage = -1; ui.interact() },
            anim = isAnimAt(ui.dispKinds, ui.zoomPage),
            modifier = Modifier.fillMaxSize())
    }
}

/** 图片区（铺满全屏，顶栏/滑轨都是悬浮 overlay 不占布局）：错误/加载中/单页/滚动 四态。 */
@Composable
private fun ReaderStage(source: ReaderSource, ui: ReaderUiState) {
    Box(Modifier.fillMaxSize()
        .pointerInput(ui.total, ui.mode) {
            detectTapGestures { off ->
                // 点按翻页/工具栏切换仅限单页模式；滚动模式由 ScrollMode 内部处理
                if (ui.mode == "page") ui.onStageTap(off.x / size.width)
            }
        }) {
        when {
            ui.error.isNotEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(AppI18n.sf("加载失败：%1", ui.error), color = Color(0xFFFF5ED0), fontSize = 13.sp)
            }
            ui.total <= 0 -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(AppI18n.s("加载中…"), color = Color(0xFF9A8FB8))
            }
            ui.mode == "page" -> PagerMode(source, ui.pageAt, ui.total, ui.dispKinds, ui.page,
                onPage = { ui.page = it; if (ui.barsVisible) ui.tick++ },
                onGestureActive = { ui.gestureActive = it })
            else -> ScrollMode(source, ui.pageAt, ui.total, ui.dispKinds, ui.page,
                onPage = { ui.page = it; if (ui.barsVisible) ui.tick++ },
                barsVisible = ui.barsVisible,
                onHideBars = { if (ui.barsVisible) { ui.barsVisible = false; ui.tick++ } },
                onShowBars = { ui.interact() },
                onZoom = { idx -> ui.zoomPage = idx },
                onGestureActive = { ui.gestureActive = it })
        }
    }
}

/**
 * 元数据加载 + 续读定位（3.7.43 从 ReaderScreen 抽出）：
 * 默认版本优先 汉化/翻译/中文；上次位置不在默认版本内 → 切到包含它的版本（3.4.0）。
 */
@Composable
private fun ReaderMetaEffect(source: ReaderSource, onLoaded: (ReaderMetaResult) -> Unit,
                             onError: (String) -> Unit) {
    LaunchedEffect(source) {
        try {
            val m = withContext(Dispatchers.IO) { source.loadMeta() }
            val vi = pickDefaultVersion(m.versions)
            val disp = if (m.versions.isEmpty()) (0 until m.total).toList() else m.versions[vi].idx
            var sel = vi
            var pos = 0
            if (m.total > 0) {
                // 继续阅读：面板（在线）/本地（离线）记录的上次位置（绝对页序）
                val rp = withContext(Dispatchers.IO) { source.resumePage(m.total) }
                if (rp > 0) {
                    val (v2, p) = resumePos(disp, m.versions, rp)
                    if (v2 >= 0) sel = v2
                    pos = p
                }
            }
            onLoaded(ReaderMetaResult(m.total, m.versions, m.kinds, sel, pos))
        } catch (e: Exception) {
            onError(e.message ?: e.toString())
        }
    }
}

/** 默认版本：优先 汉化/翻译/中文，都没有则第一个（空列表给 0）。 */
private fun pickDefaultVersion(versions: List<ReaderVersion>): Int {
    if (versions.isEmpty()) return 0
    val pref = versions.indexOfFirst { v ->
        v.name.contains("汉化") || v.name.contains("翻译") || v.name.contains("中文")   // i18n:data 版本名匹配语料   // i18n:data 版本名匹配语料   // i18n:data 版本名匹配语料   // i18n:data 版本名匹配语料   // i18n:data 版本名匹配语料
    }
    return if (pref >= 0) pref else 0
}

/** 续读定位：上次绝对页在默认版本内的位置；不在则找包含它的版本。
 *  返回 (应切到的版本下标 or -1 保持当前, 该版本内的页位)；页位 0 = 不定位。 */
private fun resumePos(disp: List<Int>, versions: List<ReaderVersion>, rp: Int): Pair<Int, Int> {
    val pos = disp.indexOf(rp)
    if (pos < 0 && versions.isNotEmpty()) {
        val v2 = versions.indexOfFirst { rp in it.idx }
        if (v2 >= 0) return v2 to versions[v2].idx.indexOf(rp)
    }
    return -1 to pos
}

/**
 * 阅读器副作用组（3.7.43 从 ReaderScreen 抽出）：常亮 / 音量键 / 工具栏淡出 /
 * 作者解析 / 阅读进度上报（翻页节流 + 退出兜底）/ 预读后续 5 页。
 */
@Composable
private fun ReaderEffects(source: ReaderSource, ui: ReaderUiState) {
    val ctx = LocalContext.current
    // ---- 阅读期间屏幕常亮 ----
    val activity = ctx as? Activity
    DisposableEffect(Unit) {
        activity?.window?.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        onDispose { activity?.window?.clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
    }
    // ---- 音量键翻页（离开阅读器自动恢复音量） ----
    DisposableEffect(Unit) {
        ReaderVolume.active = true
        ReaderVolume.onTurn = { d -> ui.turn(d) }
        onDispose { ReaderVolume.active = false; ReaderVolume.onTurn = null }
    }
    // ---- 工具栏显隐：显示期间 3 秒无交互自动淡出；滑动手势进行中绝不淡出 ----
    LaunchedEffect(ui.barsVisible, ui.tick, ui.gestureActive) {
        if (ui.barsVisible && !ui.gestureActive) { delay(3000); ui.barsVisible = false }
    }
    // 展开时解析作者（个人名 → 未定词条 bare），供「复制作者」
    LaunchedEffect(ui.titleOpen) {
        if (ui.titleOpen && ui.author.isEmpty()) {
            ui.author = withContext(Dispatchers.IO) {
                try { source.authorName() } catch (_: Exception) { "" }
            }
        }
    }
    ReaderProgressSync(source, ui)
    // ---- 预读后续页（对齐官方）：提前拉取后面 5 页，滚动到时秒开、占位条几乎不可见 ----
    // 关键约束：① 必须显式给 size（不设 size 会被 Coil 按原图解码，GIF 直接打爆内存）；
    // ② 视频页与动图页都不预读（动图内存 = 帧数 × 像素，留到真正翻到它时再解码一张）。
    val (vpW, vpH) = viewportPx()
    LaunchedEffect(ui.page, ui.total, ui.dispKinds) {
        prefetchPages(ctx, source, ui.pageAt, ui.page, ui.total, ui.dispKinds, vpW, vpH)
    }
}

/**
 * 阅读进度同步（3.7.43 从 ReaderEffects 拆出）：翻页节流上报 + 退出兜底。
 *   * 在线：POST /api/reading/state（finished 仅在翻到最后一页时置 true，往回翻不清已读）；
 *   * 离线/断链：进度进 LibraryStore.pending 队列，联网后自动冲账；
 *   * 退出阅读器时无条件兜底上报一次（非取消协程，不受组合销毁影响）。
 */
@Composable
private fun ReaderProgressSync(source: ReaderSource, ui: ReaderUiState) {
    var lastReportAt by remember { mutableStateOf(0L) }
    LaunchedEffect(ui.page, ui.total) {
        if (ui.total <= 0) return@LaunchedEffect
        val now = android.os.SystemClock.elapsedRealtime()
        if (now - lastReportAt >= 4000 || ui.page == ui.total - 1) {
            lastReportAt = now
            source.reportProgress(ui.pageAt(ui.page), if (ui.page == ui.total - 1) true else null)
        }
    }
    DisposableEffect(source) {
        onDispose {
            reportProgressOnExit(source, ui.page, ui.total, ui.pageAt)
            source.cleanup()   // 本地来源：清掉 cacheDir/offline_video/<key>/
        }
    }
}

/** 退出兜底上报（3.7.43 提为模块级）：非取消协程，不受组合销毁影响。 */
private fun reportProgressOnExit(source: ReaderSource, page: Int, total: Int, pageAt: (Int) -> Int) {
    if (total <= 0 || page < 0) return
    val abs = pageAt(page)
    CoroutineScope(Dispatchers.IO).launch {
        try { source.reportProgress(abs, if (page == total - 1) true else null) } catch (_: Exception) {}
    }
}

/** 预读后续 5 页（3.7.43 提为模块级）：跳过视频/动图；显式 size 与原显示请求同盒子同键。 */
private fun prefetchPages(ctx: Context, source: ReaderSource, pageAt: (Int) -> Int,
                          page: Int, total: Int, kinds: List<String>?, vpW: Int, vpH: Int) {
    for (i in 1..5) {
        val idx = page + i
        if (idx >= total) break
        if (isVideoAt(kinds, idx) || isAnimAt(kinds, idx)) continue
        val model = source.pageModel(pageAt(idx))
        ctx.imageLoader.enqueue(
            coil.request.ImageRequest.Builder(ctx).data(model)
                .addHeader("X-Token", Api.token)
                .memoryCacheKey(
                    when (model) {
                        is LocalPage -> "${model.cacheKey}#0"
                        else -> "$model#0"
                    })
                // 显式限制解码尺寸：与显示请求同一套盒子，既避免按原图解码，
                // 又保证预读进内存缓存的位图与真正显示时用的是同一张（键也一致）
                .size(vpW.coerceAtLeast(1), (vpH * 2).coerceAtLeast(1))
                .build())
    }
}
