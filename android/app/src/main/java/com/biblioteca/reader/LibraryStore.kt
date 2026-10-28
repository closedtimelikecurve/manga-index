package com.biblioteca.reader

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/**
 * 本地书架（APP 3.0「导出与离线阅读」消费端）
 * =====================================
 * 存储布局（getExternalFilesDir(null)/library/，外部存储私有目录，卸载即清）：
 * ```
 * library/
 * ├── works/<group>/<work>.zip     ← 原样作品包（服务端 /api/export/file 原字节，不改名不改包）
 * ├── covers/<group>/<work>.jpg    ← 封面快照（服务端 /cover 缩略图）
 * └── meta/library.json            ← 书架元数据（v1 用 JSON：条目数百级，SQLite 属过度）
 * ```
 * 写入策略：临时文件 + rename 原子替换；损坏时重置为空并保留作品文件（用户可重新登记）。
 * 条目的 server_size / server_mtime 记录**下载时**的 manifest 值 —— 更新检测 = 现查 manifest
 * 与之比对（有更新），检查本身不回写这两个字段。用户附加事实（阅读进度）本地一份、
 * 服务器一份；离线时进度先进 pending 队列，联网后由 App 启动/探活成功时冲账。
 */
object LibraryStore {
    private const val SCHEMA = 1
    private val MEDIA_SUFFIXES = listOf(".jpg", ".jpeg", ".png", ".gif", ".webp", ".webm", ".mp4")
    private val lock = ReentrantLock()

    /** 运行期全局状态：面板可达性（App 启动/周期探活维护；离线时阅读走 LocalSource） */
    object Runtime {
        @Volatile var online: Boolean = true
    }

    data class Entry(
        val key: String,                 // "社团/作品名"（与面板 workKey 一致；阅读状态上报共用）
        val group: String,
        val work: String,
        val file: String,                // works/<group>/ 下的文件名
        val size: Long,
        val mtime: Long,
        val pages: Int,
        val kinds: List<String>,         // 每页媒体类型 image|gif|video（按 zip 条目扩展名生成）
        val circle: String,
        val personals: List<String>,
        val tags: List<Pair<String, String>>,
        val cover: Boolean,
        val downloadedAt: Long,
        val serverSize: Long,            // 下载时 manifest.size（更新检测基准，检查不回写）
        val serverMtime: Double,         // 下载时 manifest.mtime
        val stale: Boolean = false,      // 服务端来源已失效（改名/解散/删除）→ 仅本地可读
        val lastPage: Int = 0,           // 本地兜底阅读进度
        val finished: Boolean = false,
        val lastReadAt: Long = 0,
    )

    data class PendingReading(
        val key: String, val page: Int, val finished: Boolean?, val at: Long)

    // ---------------- 目录布局 ----------------

    /** 书架根。外部存储不可用时退回内部存储（功能不缺失，只是占用内部空间）。 */
    fun root(ctx: Context): File {
        val ext = ctx.getExternalFilesDir(null)
        return File(ext ?: ctx.filesDir, "library")
    }

    fun worksDir(ctx: Context): File = File(root(ctx), "works")
    fun coversDir(ctx: Context): File = File(root(ctx), "covers")

    fun workFile(ctx: Context, e: Entry): File = File(worksDir(ctx), e.group + "/" + e.file)
    fun coverFile(ctx: Context, group: String, work: String): File =
        File(coversDir(ctx), "$group/$work.jpg")

    private fun metaFile(ctx: Context): File = File(File(root(ctx), "meta"), "library.json")

    // ---------------- 进程内状态 ----------------

    @Volatile private var loaded = false
    @Volatile private var ctxRef: Context? = null
    private val entriesMap = LinkedHashMap<String, Entry>()
    private val pendingMap = LinkedHashMap<String, PendingReading>()

    fun init(ctx: Context) {
        lock.withLock {
            ctxRef = ctx.applicationContext
            if (loaded) return
            loaded = true
            val f = metaFile(ctx)
            try {
                val obj = JSONObject(f.readText())
                if (obj.optInt("v") != SCHEMA) {
                    // 版本不认识 ≠ 书架空了：文件在 works/ 里，按磁盘重建再继续
                    backupBrokenMeta()
                    rebuildFromDiskLocked()
                    return
                }
                for (i in 0 until (obj.optJSONArray("entries")?.length() ?: 0)) {
                    val e = entryFromJson(obj.getJSONArray("entries").getJSONObject(i))
                    if (e != null) entriesMap[e.key] = e
                }
                for (i in 0 until (obj.optJSONArray("pending")?.length() ?: 0)) {
                    val p = obj.getJSONArray("pending").getJSONObject(i)
                    val pr = PendingReading(p.optString("key"), p.optInt("page"),
                        if (p.isNull("finished")) null else p.optBoolean("finished"), p.optLong("at"))
                    if (pr.key.isNotEmpty()) pendingMap[pr.key] = pr
                }
            } catch (e: Exception) {
                // 元数据损坏绝不能"清空书架"：作品文件还在 works/ 里，用户看到的是
                // "本地下载的作品全没了"（反馈里的严重 bug 就是他看到的形态）。
                // 先把坏文件留档便于排查，再按磁盘重建条目——页数/标签这类订正信息会退回
                // 最小集合，但**作品本身不会被误判为不存在**。
                backupBrokenMeta()
                rebuildFromDiskLocked()
            }
            // 索引读成功但一条都没有、works/ 里却有作品：说明元数据曾被清空后重新保存过
            // （旧版损坏处理的后果），此时 JSON 是合法的、不会走进 catch —— 必须在这里兜住。
            if (entriesMap.isEmpty()) recoverOrphansLocked()
        }
    }

    /**
     * 从磁盘找回作品（3.7.60）。
     *
     * 用户问过"作品是不是永远找不回来了"——不是：没有任何代码删过 works 目录，
     * 清缓存只动 `cacheDir/image_cache`。丢的只可能是索引（library.json），
     * 而索引完全可以由文件名反推（社团 = 目录名、作品名 = 文件名）。
     * 代价：页数要重新读写 zip、标签/关注这类服务端信息退回空，阅读进度无法恢复。
     *
     * @return 新找回的条目数
     */
    fun recoverOrphans(ctx: Context): Int = lock.withLock {
        ctxRef = ctx.applicationContext
        recoverOrphansLocked()          // 内部已负责落盘
    }

    /** 扫描 works/，把索引里没有的文件补成条目。调用方需持锁。 */
    private fun recoverOrphansLocked(): Int {
        val ctx = ctxRef ?: return 0
        var added = 0
        for (g in worksDir(ctx).listFiles()?.filter { it.isDirectory } ?: return 0) {
            for (f in g.listFiles() ?: emptyArray()) {
                if (!f.isFile || f.length() <= 0) continue
                val key = g.name + "/" + f.name.substringBeforeLast('.')
                if (entriesMap.containsKey(key)) continue
                val e = rebuildEntry(ctx, g.name, f) ?: continue
                entriesMap[e.key] = e
                added++
            }
        }
        if (added > 0) persistLocked()
        return added
    }

    /** 元数据解析失败时留档（library.json.bad-<ts>），不覆盖、不删除。 */
    private fun backupBrokenMeta() {
        try {
            val f = metaFile(ctxRef ?: return)
            if (f.exists()) f.renameTo(File(f.parentFile, "library.json.bad-" + System.currentTimeMillis()))
        } catch (_: Exception) {
        }
    }

    /**
     * 按磁盘重建书架条目（仅在 library.json 损坏时用）。
     * 从 works/<group>/<file> 反推 key / 大小 / 页数 / 媒体类型；读不动的包跳过
     * （宁可少一条，也不让整屋作品因为一个坏包而消失）。
     */
    private fun rebuildFromDiskLocked() {
        val ctx = ctxRef ?: return
        entriesMap.clear()
        val root = worksDir(ctx)
        val groups = root.listFiles()?.filter { it.isDirectory } ?: return
        for (g in groups) {
            for (f in g.listFiles() ?: emptyArray()) {
                if (!f.isFile || f.length() <= 0) continue
                val e = rebuildEntry(ctx, g.name, f) ?: continue
                entriesMap[e.key] = e
            }
        }
        persistLocked()
    }

    private fun rebuildEntry(ctx: Context, group: String, f: File): Entry? {
        val work = f.name.substringBeforeLast('.')
        if (work.isEmpty()) return null
        val pages = scanZipPages(f) ?: return null
        return Entry(key = group + "/" + work, group = group, work = work, file = f.name,
            size = f.length(), mtime = f.lastModified(), pages = pages.size,
            kinds = pages.map { kindOfEntry(it) },
            circle = group, personals = emptyList(), tags = emptyList(),
            cover = coverFile(ctx, group, work).exists(),
            downloadedAt = f.lastModified() / 1000, serverSize = 0, serverMtime = 0.0)
    }

    /** 读不动的包返回 null（跳过它，不让整屋作品为一个坏包陪葬）。 */
    private fun scanZipPages(f: File): List<String>? {
        val pages = mutableListOf<String>()
        return try {
            java.util.zip.ZipFile(f).use { zf ->
                val es = zf.entries()
                while (es.hasMoreElements()) {
                    val n = es.nextElement().name
                    if (isMediaEntry(n)) pages.add(n)
                }
            }
            pages.ifEmpty { null }
        } catch (_: Exception) {
            null
        }
    }

    private fun isMediaEntry(name: String): Boolean {
        val low = name.lowercase()
        return MEDIA_SUFFIXES.any { low.endsWith(it) }
    }

    private fun kindOfEntry(name: String): String {
        val low = name.lowercase()
        return when {
            low.endsWith(".webm") || low.endsWith(".mp4") -> "video"
            low.endsWith(".gif") -> "gif"
            else -> "image"
        }
    }

    private fun persistLocked() {
        val ctx = ctxRef ?: return
        try {
            val dir = metaFile(ctx).parentFile!!
            dir.mkdirs()
            val obj = JSONObject().put("v", SCHEMA)
            val earr = JSONArray()
            for (e in entriesMap.values) earr.put(entryToJson(e))
            obj.put("entries", earr)
            val parr = JSONArray()
            for (p in pendingMap.values) {
                val po = JSONObject().put("key", p.key).put("page", p.page).put("at", p.at)
                if (p.finished == null) po.put("finished", JSONObject.NULL) else po.put("finished", p.finished)
                parr.put(po)
            }
            obj.put("pending", parr)
            val tmp = File(dir, "library.json.tmp")
            tmp.writeText(obj.toString())
            val dst = metaFile(ctx)
            // 原子替换：Linux/Android 上 renameTo 会覆盖目标。旧写法"先删后改名"在
            // 改名失败（空间不足/被占用）时会让 library.json 直接消失 —— 用户看到
            // 的就是"本地作品全没了"，与清缓存无关却能撞在一起。
            if (!tmp.renameTo(dst)) {
                tmp.copyTo(dst, overwrite = true)
                tmp.delete()
            }
        } catch (_: Exception) {
        }
    }

    // ---------------- 条目 CRUD ----------------

    fun entries(): List<Entry> = lock.withLock { entriesMap.values.toList() }

    /** 全部条目 key（3.6.9：续读页据此把本地已下载作品排除出不参与计数） */
    fun keys(): Set<String> = lock.withLock { entriesMap.keys.toSet() }

    fun get(key: String): Entry? = lock.withLock { entriesMap[key] }

    fun put(e: Entry) = lock.withLock {
        entriesMap[e.key] = e
        persistLocked()
    }

    /**
     * 从书架移除条目。deleteFiles=true（默认）= 连作品文件与封面一起删。
     * 3.6.8 曾一度把书架/下载场景改成 deleteFiles=false（仅移除记录）；3.6.9 用户明确
     * 要求书架长按就是直接删作品，改回默认语义。下载管理页的「删除」另见
     * DownloadManager.remove（删下载项目并清理 .part 残存）。
     * 记录移除后该 key 的待同步进度一并清掉（没有条目，冲账无处安放）。
     */
    fun remove(ctx: Context, key: String, deleteFiles: Boolean = true): Boolean {
        val e = lock.withLock { entriesMap.remove(key) } ?: return false
        pendingMap.remove(key)
        persistLocked()
        if (deleteFiles) {
            try { workFile(ctx, e).delete() } catch (_: Exception) {}
            try { coverFile(ctx, e.group, e.work).delete() } catch (_: Exception) {}
        }
        return true
    }

    /** 书架总占用（实际落盘字节数：works + covers）。 */
    fun usageBytes(ctx: Context): Long {
        var total = 0L
        for (dir in arrayOf(worksDir(ctx), coversDir(ctx))) {
            dir.walkBottomUp().forEach { if (it.isFile) total += it.length() }
        }
        return total
    }

    // ---------------- 阅读进度 ----------------

    /** 本地进度（3.6.9 起本地书架续读只在书架内部记录：本地落盘，不上报服务端、
     *  不入 pending 冲账队列 —— 不参与续读区计数）。 */
    fun saveLocalProgress(ctx: Context, key: String, page: Int, finished: Boolean?) {
        lock.withLock {
            val old = entriesMap[key]
            if (old != null) {
                entriesMap[key] = old.copy(lastPage = page,
                    finished = old.finished || finished == true,
                    lastReadAt = System.currentTimeMillis() / 1000)
                persistLocked()
            }
        }
    }

    fun pendingList(): List<PendingReading> = lock.withLock { pendingMap.values.toList() }

    /** 仅入待同步队列（远程作品离线/断链时的进度暂存；本地作品走 saveLocalProgress）。 */
    fun addPendingReading(key: String, page: Int, finished: Boolean?) = lock.withLock {
        pendingMap[key] = PendingReading(key, page, finished, System.currentTimeMillis() / 1000)
        persistLocked()
    }

    /** 冲账成功后移除该 key 的待同步进度。 */
    fun removePending(key: String) = lock.withLock {
        pendingMap.remove(key)
        persistLocked()
    }

    // ---------------- 服务端来源状态 ----------------

    fun setStale(key: String, stale: Boolean) = lock.withLock {
        val old = entriesMap[key] ?: return
        if (old.stale == stale) return
        entriesMap[key] = old.copy(stale = stale)
        persistLocked()
    }

    // ---------------- JSON ----------------

    private fun entryToJson(e: Entry): JSONObject = JSONObject()
        .put("key", e.key).put("group", e.group).put("work", e.work).put("file", e.file)
        .put("size", e.size).put("mtime", e.mtime).put("pages", e.pages)
        .put("kinds", JSONArray(e.kinds))
        .put("circle", e.circle)
        .put("personals", JSONArray(e.personals))
        .put("tags", JSONArray().apply { for ((t, n) in e.tags) put(JSONObject().put("type", t).put("name", n)) })
        .put("cover", e.cover).put("downloaded_at", e.downloadedAt)
        .put("server_size", e.serverSize).put("server_mtime", e.serverMtime)
        .put("stale", e.stale).put("last_page", e.lastPage)
        .put("finished", e.finished).put("last_read_at", e.lastReadAt)

    private fun entryFromJson(o: JSONObject): Entry? {
        val key = o.optString("key")
        if (key.isEmpty()) return null
        fun strArr(name: String): List<String> {
            val a = o.optJSONArray(name) ?: return emptyList()
            return (0 until a.length()).map { a.optString(it) }.filter { it.isNotEmpty() }
        }
        val tags = mutableListOf<Pair<String, String>>()
        val ta = o.optJSONArray("tags")
        for (i in 0 until (ta?.length() ?: 0)) {
            val t = ta!!.getJSONObject(i)
            tags.add(t.optString("type") to t.optString("name"))
        }
        return Entry(
            key, o.optString("group"), o.optString("work"), o.optString("file"),
            o.optLong("size"), o.optLong("mtime"), o.optInt("pages"),
            strArr("kinds"), o.optString("circle"), strArr("personals"), tags,
            o.optBoolean("cover"), o.optLong("downloaded_at"),
            o.optLong("server_size"), o.optDouble("server_mtime", 0.0),
            o.optBoolean("stale"), o.optInt("last_page"),
            o.optBoolean("finished"), o.optLong("last_read_at"))
    }
}
