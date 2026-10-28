package com.biblioteca.reader

import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import java.io.File

/** 下载项状态：排队 / 进行中 / 完成 / 失败 / 已暂停（断点 .part 保留，点「继续」可续传） */
enum class DlState { QUEUED, RUNNING, DONE, FAILED, PAUSED }

class DlItem(val group: String, val work: String) {
    var state by mutableStateOf(DlState.QUEUED)
    var done by mutableStateOf(0L)
    var total by mutableStateOf(-1L)          // -1 = 服务端未给总长
    var error by mutableStateOf("")
    // 下载目标文件名（manifest.file 末段；暂停/删除时据此定位 .part 残存）
    var fileName by mutableStateOf("")
    // 批量入队（画师/社团「下载全部」）：失败不逐条弹 toast，只在列表里标记，
    // 汇总由发起方一次性告知（否则一个社团混几个文件夹作品就 toast 刷屏）
    var silent by mutableStateOf(false)
    val key: String get() = "$group/$work"
    val active: Boolean get() = state == DlState.QUEUED || state == DlState.RUNNING
}

/**
 * 下载管理器（3.7.13 并发队列；3.6.9 断点续下语义重构）。
 *
 * 需求来源：此前全局同时只允许一个下载（downloadWork 见到在跑任务直接拒绝），
 * 用户要求「至少三个文件同时下载，且下载中不拒绝新任务（排队等候）」。
 *
 *  * 最多 [MAX_CONCURRENT] 个并发，超出进队列按入队顺序顶上；
 *  * 断点续传沿用 Api.downloadResumable（.part + Range）；
 *  * **暂停**（3.6.9，原「停止」）：只断进行中的连接，.part 半成品保留，
 *    状态置 PAUSED，点「继续」重新入队从断点续下；
 *  * **网络异常自动断点**：IOException 类（断网/超时/连接重置）不再判失败，
 *    自动置 PAUSED 保留断点，用户点「继续」即可重试；确定性错误
 *    （文件夹作品不支持、size=0 等）仍判 FAILED；
 *  * **删除**（3.6.9，原「停止」文案统一改为「删除」）：移除下载项目并
 *    **连同 .part 残存文件一并清理**；已完成项只移出列表（文件已入书架，
 *    删文件请到本地书架长按）；
 *  * 完成后自动登记本地书架（LibraryStore.put）并通知 onShelfChanged 刷新界面。
 */
object DownloadManager {
    const val MAX_CONCURRENT = 3

    /** 全部下载项（含进行中/排队/已完成/失败/已暂停） */
    val items = mutableStateListOf<DlItem>()

    /** 有活动任务时自动弹出的进度横幅（用户点掉后不再自动出，可手动进下载页看） */
    var autoPopup by mutableStateOf(false)
        private set

    private val jobs = mutableMapOf<String, Job>()
    private var scope: CoroutineScope? = null
    private var appCtx: Context? = null

    /** 有作品下载成功 → 通知刷新本地书架 */
    var onShelfChanged: (() -> Unit)? = null
    /** 吐司（主线程 Handler 包裹，IO 线程可调） */
    var toast: ((String) -> Unit)? = null

    fun bind(ctx: Context, scope: CoroutineScope) {
        appCtx = ctx.applicationContext
        this.scope = scope
    }

    fun runningCount(): Int = items.count { it.state == DlState.RUNNING }
    fun queuedCount(): Int = items.count { it.state == DlState.QUEUED }
    fun activeCount(): Int = items.count { it.active }
    fun doneCount(): Int = items.count { it.state == DlState.DONE }
    fun failedCount(): Int = items.count { it.state == DlState.FAILED }
    fun pausedCount(): Int = items.count { it.state == DlState.PAUSED }

    /** 发起下载；已在队列/在跑/已完成 的重复项返回 false（不重复入队）。
     *  silent：批量入队标记，失败不逐条 toast（见 DlItem.silent）。 */
    fun enqueue(group: String, work: String, silent: Boolean = false): Boolean {
        val key = "$group/$work"
        val exist = items.firstOrNull { it.key == key }
        if (exist != null && (exist.active || exist.state == DlState.DONE)) return false
        exist?.let { items.remove(it) }
        val it = DlItem(group, work)
        it.silent = silent
        items.add(it)
        autoPopup = true
        pump()
        return true
    }

    /** 暂停单项：在跑的取消协程（.part 保留可续传），排队的直接置暂停 */
    fun pause(key: String) {
        val it = items.firstOrNull { it.key == key } ?: return
        jobs.remove(key)?.cancel()
        if (it.state != DlState.DONE) it.state = DlState.PAUSED
        checkAutoPopup()
    }

    fun pauseAll() {
        items.filter { it.active }.forEach { pause(it.key) }
    }

    /** 「继续」（断点续下）：已暂停/失败 → 重新入队，.part 从头续传 */
    fun resume(key: String) {
        val it = items.firstOrNull { it.key == key } ?: return
        if (it.state != DlState.PAUSED && it.state != DlState.FAILED) return
        it.state = DlState.QUEUED
        it.error = ""
        autoPopup = true
        pump()
    }

    /** 删除下载项目：停任务 + 移出列表 + **清掉 .part 残存文件**（3.6.9）。
     *  已完成项只移出列表——文件已登记进本地书架，删作品请到书架长按。 */
    fun remove(key: String) {
        val it = items.firstOrNull { it.key == key } ?: return
        jobs.remove(key)?.cancel()
        if (it.state != DlState.DONE && it.fileName.isNotEmpty()) {
            try {
                val part = File(File(LibraryStore.worksDir(appCtx ?: return), it.group),
                    it.fileName + ".part")
                if (part.exists()) part.delete()
            } catch (_: Exception) { }
        }
        items.remove(it)
        checkAutoPopup()
    }

    fun clearFinished() {
        items.removeAll { it.state == DlState.DONE }
    }

    fun dismissAutoPopup() {
        autoPopup = false
    }

    private fun checkAutoPopup() {
        if (activeCount() == 0) autoPopup = false
    }

    /** 补位：并发槽有空位时按入队顺序启动排队项 */
    private fun pump() {
        val s = scope ?: return
        var slots = MAX_CONCURRENT - runningCount()
        if (slots <= 0) return
        for (it in items) {
            if (slots <= 0) break
            if (it.state == DlState.QUEUED) {
                slots--
                start(s, it)
            }
        }
    }

    private fun fail(it: DlItem, msg: String) {
        if (it.state == DlState.PAUSED) return       // 用户主动暂停：不改判失败
        it.state = DlState.FAILED
        it.error = msg
        if (!it.silent) toast?.invoke(AppI18n.sf("下载失败：%1", msg))
    }

    /** 网络类异常（断网/超时/连接重置）→ 自动断点暂停，保留 .part 待「继续」 */
    private fun netPause(it: DlItem, msg: String) {
        if (it.state == DlState.PAUSED) return
        it.state = DlState.PAUSED
        it.error = msg
        if (!it.silent) toast?.invoke(AppI18n.sf("网络中断，已保留断点：%1", it.work))
    }

    /**
     * 下载前置校验（3.7.43 从 start 抽出）：返回非空错误信息即终止（调用方置 FAILED），
     * null = 通过。顺序即语义：可下载性 → 格式 → size → 磁盘空间（目标体积 + 64MB 余量）。
     */
    private fun precheckDownload(ctx: Context, m: Api.ExportManifest): String? {
        if (!m.downloadable) return AppI18n.s("文件夹作品暂不支持导出下载")
        val ext = m.file.substringAfterLast('.', "").lowercase()
        if (ext !in setOf("zip", "cbz")) return AppI18n.s("暂仅支持 zip/cbz 包下载到本地")
        if (m.size <= 0) return AppI18n.s("清单异常（size=0），已取消")
        LibraryStore.root(ctx).mkdirs()
        val avail = android.os.StatFs(LibraryStore.root(ctx).absolutePath).availableBytes
        if (avail < m.size + 64L * 1024 * 1024) {
            return AppI18n.sf("存储空间不足（需 %1，可用 %2）", fmtBytesShelf(m.size), fmtBytesShelf(avail))
        }
        return null
    }

    /**
     * 下载完成收尾（3.7.43 从 start 抽出）：封面快照 → 本地 kinds → 登记书架 →
     * 置 DONE → 通知刷新。封面/kinds 失败不致命（书架显示占位/按服务端页数）。
     */
    private fun finishDownload(ctx: Context, it: DlItem, dest: File, m: Api.ExportManifest) {
        // 封面快照（失败不致命：书架显示占位）
        val cover = LibraryStore.coverFile(ctx, it.group, it.work)
        try {
            cover.parentFile?.mkdirs()
            Api.downloadTo("/cover?group=${Api.enc(it.group)}&work=${Api.enc(it.work)}", cover)
        } catch (_: Exception) { }
        // 本地 kinds：按 zip 条目扩展名生成（与服务端 media_kind 同口径）
        val kinds = try { listZipKinds(dest) } catch (_: Exception) { emptyList() }
        LibraryStore.put(LibraryStore.Entry(
            key = it.key, group = it.group, work = it.work, file = it.fileName,
            size = dest.length(), mtime = (m.mtime * 1000).toLong(),
            pages = if (kinds.isNotEmpty()) kinds.size else m.pages,
            kinds = kinds, circle = m.circle, personals = m.personals, tags = m.tags,
            cover = cover.exists(), downloadedAt = System.currentTimeMillis() / 1000,
            serverSize = m.size, serverMtime = m.mtime))
        it.done = if (it.total > 0) it.total else dest.length()
        it.state = DlState.DONE
        onShelfChanged?.invoke()
        toast?.invoke(AppI18n.sf("已下载到本地书架：%1", it.work))
    }

    private fun start(scope: CoroutineScope, it: DlItem) {
        it.state = DlState.RUNNING
        var job: Job? = null
        job = scope.launch(Dispatchers.IO) {
            try {
                val ctx = appCtx ?: throw IllegalStateException("DownloadManager 未绑定 Context")   // i18n:data 开发者错误
                val m = Api.exportManifest(it.group, it.work)
                val bad = precheckDownload(ctx, m)
                if (bad != null) { fail(it, bad); return@launch }
                val destDir = File(LibraryStore.worksDir(ctx), it.group)
                destDir.mkdirs()
                it.fileName = m.file.substringAfterLast('/')
                val dest = File(destDir, it.fileName)
                Api.downloadResumable(
                    "/api/export/file?group=${Api.enc(it.group)}&work=${Api.enc(it.work)}", dest,
                    progress = { d, t ->
                        // 暂停破阻塞：cancel() 打不断 OkHttp 的阻塞读，靠每 64KB 一次的回调检查
                        if (job?.isActive == false) throw DownloadStoppedException()
                        it.done = d
                        it.total = t
                    })
                finishDownload(ctx, it, dest, m)
            } catch (e: CancellationException) {
                throw e
            } catch (e: DownloadStoppedException) {
                // 用户点暂停：progress 回调抛出破阻塞，状态已由 pause() 置好，这里什么都不做
            } catch (e: Exception) {
                // 3.6.9 网络类异常 → 自动断点（保留 .part，点「继续」续下）；
                // 确定性错误（清单/size/格式）→ 失败
                if (e is java.io.IOException || e is ApiException || e is AuthException) {
                    netPause(it, AppI18n.sf("网络中断：%1", e.message ?: e.toString()))
                } else {
                    fail(it, e.message ?: e.toString())
                }
            } finally {
                jobs.remove(it.key)
                checkAutoPopup()
                pump()      // 本项腾出槽位，排队项顶上
            }
        }
        jobs[it.key] = job
    }
}
