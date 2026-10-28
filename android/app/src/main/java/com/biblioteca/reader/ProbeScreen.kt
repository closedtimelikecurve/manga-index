@file:OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)

package com.biblioteca.reader

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/* ==========================================================================
   3.7.54「分区爬取」：按作者 / 社团 / 原作名到站点搜索 → 横板卡片勾选 → 后台下载
   → 自动入库并归到对应分区（社团检索强制进该社团；原作检索自动挂原作标签）。

   入口两处：爬虫页顶部，以及**各分区页内部右上角**（社团 / 画师 / 原作分区）。
   ========================================================================== */

// 3.7.91：与清单爬虫的 crawlKinds() 同款——**顶层 val 里不能调 AppI18n.s()**，
// 那会在类加载那一刻把语言定型，切语言后 chip 文字不跟着变。改成函数，组合期才取当前语言。
internal fun probeKinds(): List<Pair<String, String>> = listOf(
    "author" to "👤 " + AppI18n.s("画师"), "circle" to "🏢 " + AppI18n.s("社团"),
    "original" to "🎴 " + AppI18n.s("同人"))

// 3.7.57：顶部改为目标站点切换。kind 仍由入口路由携带（社团/画师/原作页进来时
// 用于入库归区），但不再作为可点 chip 展示——原来的三枚 chip 搜索行为完全一样。
// 站点名 `wnacg` / `JM` 是品牌，任何语言都不译；`N站` / `E站` 里的"站"要译（见语言包）。
// 3.7.109：按发行版可用任务过滤（公开版只带 JM 直连 → 只有 JM 站点可搜）；
// 服务端没报 builtinKinds（老面板）→ 全部显示。站点↔任务底座：wnacg↔wnacg、JM↔jmdl、
// N站↔nhdl、E站↔eh。
internal fun probeSites(): List<Pair<String, String>> {
    val all = listOf(
        Triple("wnacg", "wnacg", "wnacg"), Triple("jmcomic", "JM", "jmdl"),
        Triple("nhentai", AppI18n.s("N站"), "nhdl"), Triple("ehentai", AppI18n.s("E站"), "eh"))
    return all.filter { kindAvailable(it.third) }.map { it.first to it.second }
}

internal fun probeSiteOk(site: String): String {
    val sites = probeSites()
    return if (site in sites.map { it.first }) site else sites.firstOrNull()?.first ?: "wnacg"
}


internal fun probeSiteLabel(site: String): String =
    probeSites().firstOrNull { it.first == probeSiteOk(site) }?.second ?: "wnacg"

/** 探针页状态（沿用 `AliasPanel` 的做法：普通类 + mutableStateOf，composable 只做接线）。 */
internal class ProbeState(kind: String, term: String, site: String = "wnacg") {
    var kind by mutableStateOf(if (kind in probeKinds().map { it.first }) kind else "author")
    var term by mutableStateOf(term)
    var site by mutableStateOf(probeSiteOk(site))
    var works by mutableStateOf<List<ProbeWork>?>(null)
    var sel by mutableStateOf<Set<Int>>(emptySet())
    var info by mutableStateOf("")
    var err by mutableStateOf("")
    var busy by mutableStateOf(false)
    var total by mutableStateOf(0)          // 站点报的命中总数
    var hasMore by mutableStateOf(false)    // 还有没抓完的页（>8 页时才会为 true）
    var nextStart by mutableStateOf(2)
    var loadingMore by mutableStateOf(false)
    // 3.7.70：本次进页面后是否亲眼见过它运行——决定"已结束"是否要保留（与清单爬虫对齐：
    // 离开页面再回来，上一次的已结束回到空闲）
    var sawRunning by mutableStateOf(false)

    fun toggle(aid: Int) {
        sel = if (aid in sel) sel - aid else sel + aid
    }

    /** 3.7.61：全选跳过库里已有的（与收件箱「一键入库跳过疑似重复」同一套规矩）。 */
    fun selectAll(on: Boolean) {
        sel = if (on) (works ?: emptyList()).filter { it.dupName.isEmpty() }.map { it.aid }.toSet()
        else emptySet()
    }

    fun picked(): List<ProbeWork> = (works ?: emptyList()).filter { it.aid in sel }

    /** 合并新一页（按 aid 去重、保持顺序、已勾选的保留）。 */
    fun append(list: List<ProbeWork>) {
        val have = (works ?: emptyList()).map { it.aid }.toSet()
        works = (works ?: emptyList()) + list.filter { it.aid !in have }
    }
}

@Composable
fun ProbeScreen(app: AppState, kindInit: String, termInit: String,
                siteInit: String = "wnacg", onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    // 3.7.63：按入口参数做键。Compose 复用同一组合位置，从社团 A 的入口进、再
    // 从社团 B 的入口进时，不重建状态就会沿用 A 的词条与搜索结果。
    val ps = remember(kindInit, termInit, siteInit) { ProbeState(kindInit, termInit, siteInit) }
    // 3.7.70：已结束的任务只有"本次进页面后亲眼见过它运行"才保留（与清单爬虫对齐）
    val rawJob = app.probeWatch.job
    val job = rawJob?.takeIf { it.running || ps.sawRunning }
    LaunchedEffect(rawJob?.running) { if (rawJob?.running == true) ps.sawRunning = true }
    BackHandlerOn(onBack)
    // 3.7.57：不再进入页面就自动搜索（用户要求必须点搜索）；只负责拉一次任务快照。
    LaunchedEffect(Unit) {
        refreshBuiltinKinds()                      // 3.7.109：公开版站点 chip 收窄
        ps.site = probeSiteOk(ps.site)             // 默认站点回退到第一个可用站
        app.probeWatch.tick(app)
    }
    Column(Modifier.fillMaxSize()) {
        TopBar("⛏ " + AppI18n.s("搜索下载器"), onBack)
        ProbeHead(ps, job?.running == true) { probeSearch(scope, ps) }
        ProbeList(ps, scope, job, app)
        ProbeBottomBar(ps, app, job?.running == true, scope)
    }
}

/** 站点 chips + 词条输入 + 搜索按钮（3.7.57：搜索必须点按，切换站点不自动搜）。 */
@Composable
private fun ProbeHead(s: ProbeState, running: Boolean, onSearch: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        probeSites().forEach { (k, label) ->
            val on = s.site == k
            Text(label, color = if (on) TXT else MUTED, fontSize = 12.sp, maxLines = 1,
                modifier = Modifier.clip(RoundedCornerShape(999.dp))
                    .background(if (on) ACCENT.copy(alpha = 0x33 / 255f) else CARD_BG2)
                    .border(1.dp, if (on) ACCENT else Color(0x24FFFFFF), RoundedCornerShape(999.dp))
                    .clickable {
                        if (s.site != k) {
                            s.site = k
                            s.works = null; s.sel = emptySet(); s.info = ""; s.err = ""
                            s.hasMore = false; s.nextStart = 2
                        }
                    }
                    .padding(horizontal = 10.dp, vertical = 6.dp))
        }
    }
    Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically) {
        OutlinedTextField(s.term, { s.term = it }, label = { Text(AppI18n.sf("在 %1 站内搜索", probeSiteLabel(s.site))) },
            singleLine = true, colors = appFieldColors(), modifier = Modifier.weight(1f))
        Spacer(Modifier.width(8.dp))
        Text(if (s.busy) AppI18n.s("搜索中…") else if (running) AppI18n.s("获取中…") else AppI18n.s("搜索"),
            color = if (running) MUTED else ACCENT, fontSize = 13.sp,
            modifier = Modifier.clip(RoundedCornerShape(999.dp))
                .background(ACCENT.copy(alpha = 0x22 / 255f)).border(1.dp, ACCENT, RoundedCornerShape(999.dp))
                .clickable(enabled = !s.busy && !running) { onSearch() }
                .padding(horizontal = 14.dp, vertical = 8.dp))
    }
    if (s.info.isNotEmpty()) {
        Text(s.info, color = MUTED, fontSize = 11.sp, modifier = Modifier.padding(12.dp, 0.dp, 12.dp, 6.dp))
    }
    if (s.err.isNotEmpty()) {
        Text(s.err, color = ERR, fontSize = 12.sp, modifier = Modifier.padding(horizontal = 12.dp))
    }
}

/** 结果卡片列表 + 任务进度（3.7.54；3.7.56 进度改读全局看护，离开页面也不丢）。 */
@Composable
private fun ColumnScope.ProbeList(s: ProbeState, scope: CoroutineScope,
                                  job: ProbeJob?, app: AppState) {
    val works = s.works
    val running = job?.running == true
    LazyColumn(Modifier.fillMaxWidth().weight(1f),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp, 4.dp, 12.dp, 8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)) {
        // 3.7.57：进度面板置顶；3.6.112 起运行中不再隐藏搜索结果（封面墙照常显示）
        if (job != null) {
            item { ProbeJobBox(job) { app.cancelProbePick() } }
        }
        if (works == null && !s.busy) {
            item { ProbeEmptyHint() }
        }
        items(works ?: emptyList(), key = { it.aid }) { w ->
            ProbeCard(w, w.aid in s.sel) { s.toggle(w.aid) }
        }
        if (s.hasMore || s.loadingMore) {
            item { ProbeMoreRow(s, scope) }
        }
    }
}

/** 列表尾部：补全中的提示 / 「继续加载」（3.7.55：命中很多时不再只给 24 部）。 */
@Composable
private fun ProbeMoreRow(s: ProbeState, scope: CoroutineScope) {
    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(if (s.loadingMore) AppI18n.s("正在补全剩余结果…")
            else AppI18n.sf("已显示 %1 / 约 %2 部", s.works?.size ?: 0, s.total),
            color = MUTED, fontSize = 11.sp, modifier = Modifier.weight(1f))
        if (!s.loadingMore && s.hasMore) {
            Text("＋ " + AppI18n.s("加载更多"), color = ACCENT, fontSize = 12.sp,
                modifier = Modifier.clip(RoundedCornerShape(999.dp))
                    .background(ACCENT.copy(alpha = 0x22 / 255f)).border(1.dp, ACCENT, RoundedCornerShape(999.dp))
                    .clickable { probeLoadMore(scope, s) }
                    .padding(horizontal = 12.dp, vertical = 6.dp))
        }
    }
}

@Composable
private fun ProbeEmptyHint() {
    Box(Modifier.fillMaxWidth().padding(top = 60.dp), contentAlignment = Alignment.Center) {
        Text(AppI18n.s("输入词条后点「搜索」才会查询\n命中后勾选要爬的作品，下载完会自动入库并归到对应分区"),
            color = MUTED, fontSize = 12.sp, lineHeight = 18.sp)
    }
}

/** 横板卡片：左封面（服务端压缩过）、右标题与页数、最左勾选框。 */
@Composable
private fun ProbeCard(w: ProbeWork, checked: Boolean, onToggle: () -> Unit) {
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
            .background(if (checked) ACCENT2.copy(alpha = 0x1F / 255f) else CARD_BG)
            .border(1.dp, if (checked) ACCENT else Color(0x1AFFFFFF), RoundedCornerShape(12.dp))
            .clickable { onToggle() }.padding(8.dp),
        verticalAlignment = Alignment.Top) {
        Checkbox(checked, { onToggle() }, colors = CheckboxDefaults.colors(checkedColor = ACCENT))
        ProbeCover(w)
        Column(Modifier.weight(1f).padding(start = 4.dp)) {
            Text(w.title.ifEmpty { "aid ${w.aid}" }, color = TXT, fontSize = 12.sp,
                lineHeight = 17.sp, maxLines = 3, overflow = TextOverflow.Ellipsis)
            Text((if (w.pages > 0) AppI18n.sf("%1 页 · ", w.pages) else "") + "aid ${w.aid}",
                color = MUTED, fontSize = 10.sp, modifier = Modifier.padding(top = 4.dp))
            if (w.dupName.isNotEmpty()) {
                Text(AppI18n.sf("⚠ 疑似重复：与「%1」同内容", w.dupName), color = Color(0xFFFF6B8B),
                    fontSize = 10.sp, lineHeight = 14.sp, maxLines = 2,
                    overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 3.dp))
            }
        }
    }
}

/** 封面：84×112（与网页同比例）；加载失败/无封面时显示占位。 */
@Composable
private fun ProbeCover(w: ProbeWork) {
    Box(Modifier.size(84.dp, 112.dp).clip(RoundedCornerShape(8.dp))
        .background(CARD_BG2), contentAlignment = Alignment.Center) {
        if (w.cover.isEmpty()) {
            Text("🎴", fontSize = 20.sp)
        } else {
            AsyncImage(model = Api.probeCoverUrl(w.cover), contentDescription = null,
                contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        }
    }
}

internal fun probeKindLabel(kind: String): String = when (kind) {
    "circle" -> AppI18n.s("社团名")
    "original" -> AppI18n.s("同人名")
    else -> AppI18n.s("画师名")
}

internal fun probeElapsedText(sec: Int): String {
    val s = sec.coerceAtLeast(0)
    if (s < 60) return AppI18n.sf("%1 秒", s)
    val m = s / 60
    return if (m < 60) AppI18n.sf("%1 分 %2 秒", m, s % 60)
    else AppI18n.sf("%1 时 %2 分", m / 60, m % 60)
}

internal fun probeBytesText(n: Long): String {
    val v = n.coerceAtLeast(0)
    return when {
        v >= 1_073_741_824L -> "%.2f GB".format(v / 1_073_741_824.0)
        v >= 1_048_576L -> "%.1f MB".format(v / 1_048_576.0)
        else -> "${v / 1024} KB"
    }
}

internal fun probeStateLabel(state: String): String = when (state) {
    "ok" -> AppI18n.s("已入库")
    "fail" -> AppI18n.s("失败")
    "downloading" -> AppI18n.s("下载中")
    "importing" -> AppI18n.s("入库中")
    "skip" -> AppI18n.s("已取消")
    else -> AppI18n.s("排队中")
}

/** 条目右侧明细：下载中优先显示字节进度，其余显示服务端消息（与网页 probeItemDetail 同规则）。 */
internal fun probeItemDetail(it: ProbeItem): String {
    if (it.state == "downloading" && it.bytes > 0) {
        val total = if (it.bytesTotal > 0) " / ${probeBytesText(it.bytesTotal)}" else ""
        val pct = if (it.bytesTotal > 0)
            " · ${(it.bytes * 100 / it.bytesTotal).coerceIn(0, 100)}%" else ""
        return probeBytesText(it.bytes) + total + pct
    }
    return it.msg
}

internal fun probeCurrentItem(job: ProbeJob): ProbeItem? =
    job.items.firstOrNull { it.state == "downloading" || it.state == "importing" }

/** 3.7.57：计时器本地逐秒走，服务端快照只做正向校准（避免"每 2s 跳一下"）。 */
@Composable
internal fun rememberJobElapsed(job: ProbeJob): Int {
    var local by remember(job.id) { mutableIntStateOf(job.elapsed) }
    LaunchedEffect(job.running) {
        while (job.running) { delay(1000); local += 1 }
    }
    LaunchedEffect(job.elapsed) {
        if (job.elapsed > local) local = job.elapsed
    }
    return local
}

/**
 * 任务进度看板（3.7.69 与「清单爬虫」监控同款，CrawlMonitor.kt 的组件复用）：
 * 头部（阶段 + 词条·站点·耗时 + done/total 大号 + 停止）→ 5dp 进度条 → 统计行
 * → 逐部封面作品卡（进行中优先，最多 6 张）。
 */
@Composable
private fun ProbeJobBox(job: ProbeJob, onCancel: () -> Unit) {
    val elapsed = rememberJobElapsed(job)
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
        .background(CARD_BG).border(1.dp, ACCENT.copy(alpha = 0x44 / 255f), RoundedCornerShape(12.dp))
        .padding(12.dp)) {
        val spent = probeElapsedText(elapsed)
        val label = listOf(job.term, probeSiteLabel(job.site), probeKindLabel(job.kind),
            if (job.running) AppI18n.sf("已运行 %1", spent) else AppI18n.sf("耗时 %1", spent))
            .filter { it.isNotEmpty() }.joinToString(" · ")
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(if (job.running) "⛏ " + AppI18n.s("正在获取") else "✅ " + AppI18n.s("已结束"),
                color = TXT, fontSize = 13.sp)
            Text("　$label", color = MUTED, fontSize = 10.sp, maxLines = 1,
                overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            Text("${job.done}/${job.total}", color = ACCENT, fontSize = 13.sp)
            if (job.running) {
                Text("  ■ " + AppI18n.s("停止"), color = Color(0xFFFFC86B), fontSize = 11.sp,
                    modifier = Modifier.clickable { onCancel() }.padding(start = 6.dp))
            }
        }
        val pct = if (job.total > 0)
            ((job.done + job.failed).toFloat() / job.total).coerceIn(0f, 1f) else 0f
        Box(Modifier.fillMaxWidth().padding(top = 8.dp).height(5.dp)
            .clip(RoundedCornerShape(999.dp)).background(CARD_BG2)) {
            Box(Modifier.fillMaxWidth(pct).height(5.dp).background(ACCENT))
        }
        val cur = probeCurrentItem(job)
        Text(AppI18n.sf("成功 %1 · 失败 %2", job.done, job.failed) +
                (if (job.queue > 0) " · " + AppI18n.sf("排队 %1", job.queue) else "") +
                (if (cur != null) " · " + AppI18n.s("正在处理：") + cur.title.ifEmpty { "aid ${cur.aid}" } else "") +
                (if (job.message.isNotEmpty()) "　" + job.message.take(24) else ""),
            color = MUTED, fontSize = 11.sp,
            modifier = Modifier.padding(top = 6.dp, bottom = 8.dp))
        probeJobPicks(job).forEach {
            MonitorWorkCard(it.title.ifEmpty { "aid ${it.aid}" }, it.cover, it.state,
                CRAWL_JOB_STATES(it.state),
                probeItemDetail(it), Modifier.fillMaxWidth().padding(bottom = 8.dp))
        }
        if (job.total > CRAWL_CARDS) {
            Text(AppI18n.sf("另有 %1 部未显示（完整卡片见网页端「搜索下载器」）", job.total - CRAWL_CARDS),
                color = MUTED, fontSize = 10.sp)
        }
    }
}

/** 取"最该看的"卡片：进行中优先（与清单爬虫 crawlJobPicks 同一思路，最多 6 张）。 */
private fun probeJobPicks(job: ProbeJob): List<ProbeItem> {
    val order = listOf("downloading", "importing", "queued", "fail", "ok", "skip")
    val rank = order.withIndex().associate { it.value to it.index }
    return job.items.sortedBy { rank[it.state] ?: 99 }.take(CRAWL_CARDS)
}

/** 全局进度浮标（对齐网页右下角 ticker）：任何页面运行中都可见，点击回到探针页。 */
@Composable
internal fun AppProbeTicker(s: AppState) {
    val job = s.probeWatch.job?.takeIf { it.running } ?: return
    val done = job.done + job.failed
    val pct = if (job.total > 0) done * 100 / job.total else 0
    val cur = probeCurrentItem(job)
    val elapsed = rememberJobElapsed(job)
    Box(Modifier.fillMaxSize().navigationBarsPadding(), contentAlignment = Alignment.BottomEnd) {
        Row(Modifier.padding(end = 12.dp, bottom = 96.dp)
            .clip(RoundedCornerShape(999.dp)).background(Color(0xF21C1433))
            .border(1.dp, ACCENT, RoundedCornerShape(999.dp))
            .clickable {
                if (s.screen !is Screen.Probe) {
                    s.nav(Screen.Probe(job.kind.ifEmpty { "author" }, job.term, job.site))
                }
            }.padding(horizontal = 14.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Text("⛏ " + (if (cur != null) probeStateLabel(cur.state) else AppI18n.s("获取中")) +
                " $done/${job.total}",
                color = TXT, fontSize = 11.sp, maxLines = 1)
            Text(" ${probeElapsedText(elapsed)} · $pct%", color = MUTED, fontSize = 10.sp,
                maxLines = 1)
        }
    }
}

/** 底部操作条：已选数量 + 全选 + 开始爬取。 */
@Composable
private fun ProbeBottomBar(s: ProbeState, app: AppState, running: Boolean,
                           scope: CoroutineScope) {
    val n = s.sel.size
    val total = s.works?.size ?: 0
    Row(Modifier.fillMaxWidth().background(CARD_BG).padding(12.dp, 10.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(AppI18n.sf("已选 %1 / %2", n, total), color = MUTED, fontSize = 12.sp, modifier = Modifier.weight(1f))
        Text(if (n > 0 && n == total) AppI18n.s("清空") else AppI18n.s("全选"), color = ACCENT, fontSize = 12.sp,
            modifier = Modifier.clickable(enabled = total > 0) { s.selectAll(n != total) }
                .padding(horizontal = 10.dp, vertical = 6.dp))
        Text(if (running) AppI18n.s("获取中…") else "⛏ " + AppI18n.s("联网获取"), color = TXT, fontSize = 13.sp,
            modifier = Modifier.clip(RoundedCornerShape(999.dp))
                .background(if (n == 0 || running) Color(0x22FFFFFF) else ACCENT.copy(alpha = 0x33 / 255f))
                .border(1.dp, if (n == 0 || running) Color(0x33FFFFFF) else ACCENT,
                    RoundedCornerShape(999.dp))
                .clickable(enabled = n > 0 && !running) { probeStart(scope, app, s) }
                .padding(horizontal = 16.dp, vertical = 8.dp))
    }
}

/** 分区页右上角的小入口（社团 / 画师 / 原作分区 / 爬虫页共用）。 */
@Composable
fun ProbeEntryChip(onClick: () -> Unit, label: String = "⛏ " + AppI18n.s("联网获取")) {
    Text(label, color = ACCENT, fontSize = 11.sp, maxLines = 1,
        modifier = Modifier.clip(RoundedCornerShape(999.dp))
            .background(ACCENT.copy(alpha = 0x22 / 255f))
            .border(1.dp, ACCENT, RoundedCornerShape(999.dp))
            .clickable { onClick() }
            .padding(horizontal = 10.dp, vertical = 5.dp))
}

/* ---------------- 网络动作（普通函数 + scope，与 CrawlScreen 同款） ---------------- */

internal fun probeSearch(scope: CoroutineScope, s: ProbeState) {
    val term = s.term.trim()
    if (term.isEmpty()) { s.err = AppI18n.s("先输入作者名 / 社团名 / 同人名"); return }
    if (s.busy) return
    s.busy = true; s.err = ""; s.info = AppI18n.s("搜索中…（站点响应约 2~5 秒）")
    s.works = emptyList(); s.sel = emptySet(); s.hasMore = false
    scope.launch {
        try {
            // 先只要首屏：wnacg 24 条 / JM 80 条 / N站 25 条，1~2 秒就能看到卡片
            val r = withContext(Dispatchers.IO) {
                Api.probeSearch(term, s.kind, pages = 1, site = s.site)
            }
            s.site = probeSiteOk(r.site)
            s.works = r.works; s.total = r.total; s.hasMore = r.hasMore; s.nextStart = r.nextStart
            s.info = probeInfo(r.total, r.works.size, r.domain, s.site)
        } catch (e: Exception) {
            s.err = AppI18n.sf("搜索失败：%1", e.message)
        }
        s.busy = false
        // wnacg 才自动补全；JM/N站页数可能上百，用户点「继续加载」再增量抓
        if (s.hasMore && s.err.isEmpty() && s.site == "wnacg") probeLoadRest(scope, s)
    }
}

/** 后台补全：首屏出来后把剩下的页一并拉回（服务端并发翻页）。 */
internal fun probeLoadRest(scope: CoroutineScope, s: ProbeState) {
    if (s.loadingMore || s.site != "wnacg") return
    s.loadingMore = true
    scope.launch {
        try {
            val r = withContext(Dispatchers.IO) {
                Api.probeSearch(s.term.trim(), s.kind, pages = 0, site = s.site)
            }
            s.append(r.works); s.total = r.total
            s.hasMore = r.hasMore; s.nextStart = r.nextStart
            s.info = probeInfo(s.total, s.works?.size ?: 0, r.domain, s.site)
        } catch (e: Exception) { s.err = AppI18n.sf("补全剩余结果失败：%1", e.message) }
        s.loadingMore = false
    }
}

/** 「继续加载」：从 nextStart 页起增量抓 8 页（不重复拉前面的页）。 */
internal fun probeLoadMore(scope: CoroutineScope, s: ProbeState) {
    if (s.loadingMore) return
    s.loadingMore = true
    scope.launch {
        try {
            val r = withContext(Dispatchers.IO) {
                Api.probeSearch(s.term.trim(), s.kind, pages = 8, start = s.nextStart, site = s.site)
            }
            s.append(r.works); s.hasMore = r.hasMore; s.nextStart = r.nextStart
        } catch (e: Exception) { s.err = AppI18n.sf("加载更多失败：%1", e.message) }
        s.loadingMore = false
    }
}

private fun probeInfo(total: Int, shown: Int, domain: String, site: String): String {
    val label = probeSiteLabel(site)
    val dom = if (domain.isNotEmpty()) " · $domain" else ""
    return if (total > 0) AppI18n.sf("%1 约 %2 条 · 已显示 %3 部%4", label, total, shown, dom)
    else AppI18n.sf("%1 已显示 %2 部%3", label, shown, dom)
}

internal fun probeStart(scope: CoroutineScope, app: AppState, s: ProbeState) {
    val picks = s.picked()
    if (picks.isEmpty()) return
    scope.launch {
        try {
            val r = withContext(Dispatchers.IO) {
                Api.probePick(s.term.trim(), s.kind, picks, s.site)
            }
            if (r.error.isNotEmpty()) { s.err = r.error; return@launch }
            // 服务端立即返回首帧进度：先画出来，再让全局看护接管后续轮询。
            r.job?.let { app.probeWatch.apply(app, it) }
            app.probeWatch.kick(app)
        } catch (e: Exception) { s.err = AppI18n.sf("启动失败：%1", e.message) }
    }
}
