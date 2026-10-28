package com.biblioteca.reader

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/* ================================================================
   清单爬虫（3.7.59：原名「爬虫」，与「分区爬虫」彻底分开）
   遥控服务端的两段式任务（先锁定作品、再集中爬取）。
   结构：状态收进 [CrawlScreenState]（纪律 §4.1 状态对象化）；
   拉取/停止/轮询/自动保存提为模块级函数；UI 按卡片拆到 FeaturesCrawl。
   ================================================================ */

// 七个任务各自独立（每个一枚胶囊，运行中文字变绿）。
// 3.7.88：标签改成**渲染期翻译**——顶层 val 里调 AppI18n.s() 会在类加载那一刻把当前语言冻住，
// 切语言后胶囊文字不会变；用函数每次调用才取当前语言（调用点都在组合里，语言切换自动重组）。
internal val CRAWL_KIND_CODES = listOf("wnacg", "jm", "jmdl", "nh", "nhdl", "eh", "ext")

// 3.7.109：发行版可用的内置任务（服务端 /api/config 的 builtinKinds，进页时拉一次）。
// null = 还没拉到或老面板无此字段 → 视为全部可用（完整发行版 / 旧面板行为不变）。
private var _BUILTIN_KINDS by androidx.compose.runtime.mutableStateOf<List<String>?>(null)

internal fun kindAvailable(k: String): Boolean =
    _BUILTIN_KINDS?.let { k in it } ?: true

/** 拉一次可用任务表（幂等；失败按"全部可用"处理，等下次进页再试）。 */
internal suspend fun refreshBuiltinKinds() {
    if (_BUILTIN_KINDS != null) return
    _BUILTIN_KINDS = withContext(Dispatchers.IO) {
        runCatching { Api.builtinKinds() }.getOrNull()
    }
}

internal fun crawlKinds(): List<Pair<String, String>> = listOf(
    "wnacg" to AppI18n.s("wnacg 主下载"), "jm" to AppI18n.s("JM 索引"),
    "jmdl" to AppI18n.s("JM 直连"), "nh" to AppI18n.s("N站索引"),
    "nhdl" to AppI18n.s("N站直连"), "eh" to AppI18n.s("E站直连"),
    "ext" to AppI18n.s("外接下载器")).filter { kindAvailable(it.first) }

internal fun crawlModes(): List<Pair<String, String>> =
    listOf("normal" to AppI18n.s("常规 0.60"), "strict" to AppI18n.s("严格 0.80"))

internal fun crawlKindName(k: String?): String =
    crawlKinds().firstOrNull { it.first == k }?.second ?: (k ?: "")

/** 短 toast（3.7.43 提为模块级，原 CrawlScreen/AliasScreen 各有一份局部 fun）。 */
internal fun toast(ctx: android.content.Context, s: String) =
    android.widget.Toast.makeText(ctx, s, android.widget.Toast.LENGTH_SHORT).show()

/** 清单爬虫页的全部 UI 状态（3.7.59：清掉状态灯/日志相关字段）。 */
internal class CrawlScreenState {
    var busy by mutableStateOf(false)          // 启停/保存操作进行中
    var kind by mutableStateOf("wnacg")        // 当前选中的任务（就是真实 kind，无「索引」中间态）
    var mode by mutableStateOf("normal")
    var limit by mutableStateOf("0")
    // 3.6.7：清单各自独立；3.6.36：JM/N站索引共享 listIndex
    var listWnacg by mutableStateOf("")
    var listIndex by mutableStateOf("")
    var listJmdlT by mutableStateOf("")
    var listJmdlI by mutableStateOf("")
    var listNhdl by mutableStateOf("")
    var listEh by mutableStateOf("")
    var listExt by mutableStateOf("")     // 3.7.108：外接下载器（每行一个 URL/参数行）
    var listsLoaded by mutableStateOf(false)
    var msg by mutableStateOf("")
    // 3.7.58：两段式任务快照（当前任务）；3.7.59：运行中的任务集合（给胶囊上色）
    var job by mutableStateOf<Api.CrawlJob?>(null)
    var runningKinds by mutableStateOf<Set<String>>(emptySet())
    /** 本次进入页面后是否亲眼见过它运行——决定"已结束"是否要保留（离开后回来一律空闲） */
    var sawRunning by mutableStateOf(false)

    /** 当前任务对应的清单条目（直连模式独占两份清单，JM/N站索引共享） */
    fun entriesFor(k: String): List<String> = when (k) {
        "jmdl" -> listJmdlT.split('\n')
        "nhdl" -> listNhdl.split('\n')
        "eh" -> listEh.split('\n')
        "wnacg" -> listWnacg.split('\n')
        "ext" -> listExt.split('\n')
        else -> listIndex.split('\n')   // jm / nh 索引共享
    }

    fun applyLists(l: Api.CrawlLists) {
        listWnacg = l.wnacg
        listIndex = l.index
        listJmdlT = l.jmdlTitles
        listJmdlI = l.jmdlIds
        listNhdl = l.nhdlIds
        listEh = l.ehIds
        listExt = l.ext
    }
}

/** 拉当前任务的两段式进度（含逐部作品与封面）。 */
internal fun refreshCrawlJob(scope: CoroutineScope, ui: CrawlScreenState) {
    val k = ui.kind
    scope.launch {
        try {
            val j = withContext(Dispatchers.IO) { Api.crawlJob(k) }
            if (ui.kind != k) return@launch          // 切换任务时别把旧任务贴上去
            if (j != null && j.running) ui.sawRunning = true
            // 离开页面再回来：上次的"已结束"回到空闲
            ui.job = if (j != null && (j.running || ui.sawRunning)) j else null
        } catch (_: Exception) {
            // 静默：断网/面板重启时下一轮再试
        }
    }
}

/** 拉五个任务的运行状态（只给胶囊上色，不带 items）。 */
internal fun refreshCrawlKinds(scope: CoroutineScope, ui: CrawlScreenState) {
    scope.launch {
        try {
            ui.runningKinds = withContext(Dispatchers.IO) { Api.crawlRunningKinds() }
        } catch (_: Exception) {
        }
    }
}

/** 立即刷新一次（启动/停止后调用，不等轮询）。 */
internal fun refreshCrawlNow(scope: CoroutineScope, ui: CrawlScreenState) {
    refreshCrawlKinds(scope, ui)
    refreshCrawlJob(scope, ui)
}

/**
 * 清单爬虫页轮询主循环：有任务在跑 900ms，空闲 2.5s。
 * 离开页面协程随组合销毁自动停止。
 */
internal fun crawlPollLoop(scope: CoroutineScope, ui: CrawlScreenState,
                           onLists: (Api.CrawlLists) -> Unit,
                           onListsError: (String) -> Unit) {
    scope.launch {
        try {
            onLists(withContext(Dispatchers.IO) { Api.crawlListGet() })
        } catch (e: Exception) {
            onListsError(e.message ?: e.toString())
        }
        ui.listsLoaded = true
        while (true) {
            refreshCrawlKinds(scope, ui)
            refreshCrawlJob(scope, ui)
            val running = ui.job?.running == true || ui.runningKinds.isNotEmpty()
            delay(if (running) 900 else 2_500)
        }
    }
}

/** 清单编辑自动保存（1.2 秒防抖，退出重进不丢）。 */
internal fun autoSaveCrawlLists(scope: CoroutineScope, ui: CrawlScreenState,
                               wnacg: String, index: String, jmdlT: String,
                               jmdlI: String, nhdl: String, eh: String = "",
                               ext: String = "") {
    scope.launch {
        delay(1_200)
        try {
            ui.msg = withContext(Dispatchers.IO) {
                Api.crawlListSave(wnacg, index, jmdlT, jmdlI, nhdlIds = nhdl,
                    ehIds = eh, ext = ext)
            }
        } catch (e: Exception) { ui.msg = AppI18n.sf("自动保存失败：%1", e.message) }
    }
}

/** 启动任务：清单取当前可见的那份（jmdl 额外带车号清单）。 */
internal fun startCrawlTask(scope: CoroutineScope, ui: CrawlScreenState,
                            ctx: android.content.Context) {
    ui.busy = true
    scope.launch {
        try {
            val k = ui.kind
            val entries = ui.entriesFor(k)
            val jmEntries = if (k == "jmdl") ui.listJmdlI.split('\n') else null
            ui.msg = withContext(Dispatchers.IO) {
                Api.crawlStart(k, ui.limit.toIntOrNull() ?: 0, entries,
                    strict = ui.mode == "strict", jmEntries = jmEntries)
            }
            toast(ctx, ui.msg)
            ui.sawRunning = true
            refreshCrawlNow(scope, ui)
        } catch (e: Exception) { toast(ctx, AppI18n.sf("启动失败：%1", e.message)) }
        ui.busy = false
    }
}

/** 停止指定任务（只挡"下一部"，正在传的下完）。 */
internal fun stopCrawlTask(scope: CoroutineScope, ui: CrawlScreenState, k: String,
                           ctx: android.content.Context) {
    if (ui.busy) return
    ui.busy = true
    scope.launch {
        try {
            toast(ctx, withContext(Dispatchers.IO) { Api.crawlStop(k) })
            refreshCrawlNow(scope, ui)
        } catch (e: Exception) { toast(ctx, AppI18n.sf("停止失败：%1", e.message)) }
        ui.busy = false
    }
}
