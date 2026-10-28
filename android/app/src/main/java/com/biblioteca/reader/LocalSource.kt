package com.biblioteca.reader

import android.content.Context
import coil.decode.DataSource
import coil.decode.ImageSource
import coil.fetch.Fetcher
import coil.fetch.SourceResult
import coil.request.Options
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.util.zip.ZipFile

/**
 * 阅读器数据源抽象（APP 3.0 最大工程点）
 * =====================================
 * 阅读器不再直接依赖 Api 的 group/work URL 拼装，而是面向 [ReaderSource]：
 *   * [RemoteSource] —— 在线作品（原有 /api/pages、/page、/cover 调用原样搬入）；
 *   * [LocalSource] —— 本地书架作品：原 zip 直读，**不逐页解压落盘**（Coil 自定义
 *     [LocalPageFetcher] 按条目名读流）；webm 视频页阅读时才解压到 cacheDir，退出即清理；
 *     社团改名/解散后 workKey 失效的条目仍可读（仅本地）。
 * 阅读进度同步对两个来源一视同仁：在线上报面板，离线进 LibraryStore.pending 队列冲账。
 */
data class ReaderVersion(val name: String, val idx: List<Int>)

data class ReaderMeta(val total: Int, val kinds: List<String>,
                      val versions: List<ReaderVersion> = emptyList())

interface ReaderSource {
    /** 阅读状态上报键（与面板 workKey 一致："社团/作品名"） */
    val key: String
    val displayTitle: String

    /** 总页数 + 每页媒体类型(image|gif|video) + 多版本分组(3.2.4,无多版本时空表) */
    suspend fun loadMeta(): ReaderMeta

    /** 继续阅读起始页（无记录 0；在线以面板记录为准，离线用本地兜底） */
    suspend fun resumePage(total: Int): Int

    /** Coil 图片模型：远程 = URL 字符串；本地 = [LocalPage]（自定义 Fetcher 直读 zip） */
    fun pageModel(n: Int): Any

    /** ExoPlayer 可播 URI：远程 = 带 token 的 http URL；本地 = 解压到缓存后的 file:// */
    suspend fun videoUri(n: Int): String

    /** 「复制作者」的作者名（空串 = 阅读器本地按标题正则兜底） */
    suspend fun authorName(): String

    /** 上报阅读进度。finished=null 表示不改动"已读"标记（避免往回翻被误清）。 */
    suspend fun reportProgress(page: Int, finished: Boolean?)

    /** 退出阅读器清理（本地视频缓存等） */
    fun cleanup() {}

    // ---- v3.0.1 音声作品（音频 + lrc 同步字幕）----

    /** 音声轨道（natural 序，含同名 lrc 解析结果）。空表 = 无音声。 */
    suspend fun audioTracks(): List<Api.AudioTrack>

    /** 第 n 轨可播 URI：远程 = /audio 流式 URL；本地 = 解压到缓存后的 file://（缓存保留，重听不重解压） */
    suspend fun audioUri(n: Int): String
}

/* ---------------- 本地 lrc 解析（与服务端 _parse_lrc_bytes 同口径） ---------------- */

private val LRC_TIME = Regex("""\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]""")
private val LRC_OFFSET = Regex("""\[offset:\s*([+-]?\d+)\s*\]""", RegexOption.IGNORE_CASE)

private fun decodeLrcText(bytes: ByteArray): String {
    // utf-8(带 BOM) 严格 → gb18030（简中音声汉化常态）→ ISO-8859-1 兜底
    // 严格解码失败会抛 CharacterCodingException，据此驱动编码回退（String() 是宽松的，不能用）
    for (enc in listOf(Charsets.UTF_8, charset("gb18030"))) {
        try {
            return enc.newDecoder().decode(java.nio.ByteBuffer.wrap(bytes))
                .toString().trimStart('\ufeff')
        } catch (_: Exception) {
        }
    }
    return String(bytes, Charsets.ISO_8859_1)
}

fun parseLrcBytes(bytes: ByteArray): List<Pair<Long, String>> {
    val text = decodeLrcText(bytes)
    var offsetMs = 0L
    var offsetDone = false
    val out = mutableListOf<Pair<Long, String>>()
    for (raw in text.lines()) {
        val line = raw.trim()
        if (line.isEmpty()) continue
        val om = LRC_OFFSET.find(line)
        if (om != null && !offsetDone) {
            offsetMs = om.groupValues[1].toLongOrNull() ?: 0L
            offsetDone = true
            continue
        }
        val times = mutableListOf<Long>()
        var pos = 0
        while (true) {
            val m = LRC_TIME.find(line, pos) ?: break
            val frac = (m.groupValues[3].ifEmpty { "0" }).padEnd(3, '0').take(3)
            times.add(m.groupValues[1].toLong() * 60000 + m.groupValues[2].toLong() * 1000 + frac.toLong())
            pos = m.range.last + 1
        }
        if (times.isEmpty()) continue          // [ti:]/[ar:] 等元数据行
        val body = line.substring(pos).trim()
        for (t in times) out.add(((t - offsetMs).coerceAtLeast(0)) to body)
    }
    return out.sortedBy { it.first }
}

/* ---------------- 页面媒体类型（与服务端 media_kind 同口径） ---------------- */

private val PAGE_IMAGE_EXTS = setOf("jpg", "jpeg", "png", "webp", "gif", "bmp")
private val PAGE_VIDEO_EXTS = setOf("webm")
private val AUDIO_EXTS = setOf("mp3", "m4a", "aac", "wav", "flac", "ogg", "opus", "wma")

fun localKindOf(entryName: String): String {
    val ext = entryName.substringAfterLast('.', "").lowercase()
    return when {
        ext in PAGE_VIDEO_EXTS -> "video"
        ext == "gif" -> "gif"
        else -> "image"
    }
}

fun localMimeOf(entryName: String): String? = when (entryName.substringAfterLast('.', "").lowercase()) {
    "jpg", "jpeg" -> "image/jpeg"
    "png" -> "image/png"
    "webp" -> "image/webp"
    "gif" -> "image/gif"
    "bmp" -> "image/bmp"
    else -> null
}

/** 服务端 natural_key 同款自然排序：1.jpg < 2.jpg < 10.jpg */
fun naturalCompare(a: String, b: String): Int {
    val ra = Regex("""(\d+|\D+)""").findAll(a).map { it.value }.toList()
    val rb = Regex("""(\d+|\D+)""").findAll(b).map { it.value }.toList()
    for (i in 0 until minOf(ra.size, rb.size)) {
        val x = ra[i]; val y = rb[i]
        val nx = x.toLongOrNull(); val ny = y.toLongOrNull()
        val c = if (nx != null && ny != null) nx.compareTo(ny)
                else if (nx != null) -1
                else if (ny != null) 1
                else x.compareTo(y)
        if (c != 0) return c
    }
    return ra.size.compareTo(rb.size)
}

/** 下载完成后的本地 kinds 清单：zip 内媒体条目按自然排序生成（image|gif|video）。 */
fun listZipKinds(file: File): List<String> {
    ZipFile(file).use { zf ->
        return zf.entries().asSequence()
            .filter { !it.isDirectory }
            .map { it.name }
            .filter { n ->
                val ext = n.substringAfterLast('.', "").lowercase()
                ext in PAGE_IMAGE_EXTS || ext in PAGE_VIDEO_EXTS
            }
            .sortedWith { a, b -> naturalCompare(a, b) }
            .map { localKindOf(it) }
            .toList()
    }
}

/* ---------------- 远程来源：原有在线阅读路径 ---------------- */

class RemoteSource(private val group: String, private val work: String) : ReaderSource {
    override val key: String get() = "$group/$work"
    override val displayTitle: String get() = work.dispWorkName()

    override suspend fun loadMeta(): ReaderMeta {
        val p = Api.pages(group, work)
        return ReaderMeta(p.total, p.kinds, p.versions.map { ReaderVersion(it.first, it.second) })
    }

    override suspend fun resumePage(total: Int): Int = withContext(Dispatchers.IO) {
        if (!LibraryStore.Runtime.online) return@withContext 0
        try {
            Api.readingState(key).lastPage.coerceIn(0, (total - 1).coerceAtLeast(0))
        } catch (_: Exception) { 0 }
    }

    override fun pageModel(n: Int): Any = Api.pageUrl(group, work, n)

    override suspend fun videoUri(n: Int): String = Api.pageUrl(group, work, n)

    override suspend fun authorName(): String = withContext(Dispatchers.IO) {
        try {
            val i = Api.parseInfo(group, work)
            i.personal.ifEmpty { i.bare }
        } catch (_: Exception) { "" }
    }

    override suspend fun reportProgress(page: Int, finished: Boolean?) = withContext(Dispatchers.IO) {
        if (LibraryStore.Runtime.online) {
            try {
                Api.postReadingState(key, page, finished)
                LibraryStore.removePending(key)
            } catch (_: Exception) {
                LibraryStore.addPendingReading(key, page, finished)   // 断链兜底：联网后冲账
            }
        } else {
            LibraryStore.addPendingReading(key, page, finished)
        }
    }

    override suspend fun audioTracks(): List<Api.AudioTrack> = withContext(Dispatchers.IO) {
        if (!LibraryStore.Runtime.online) return@withContext emptyList()
        try { Api.audioManifest(group, work) } catch (_: Exception) { emptyList() }
    }

    override suspend fun audioUri(n: Int): String = Api.audioUrl(group, work, n)
}

/* ---------------- 本地来源：本地书架 zip 直读 ---------------- */

/** Coil 图片模型：zip 内一个媒体条目 */
data class LocalPage(val zip: File, val entry: String) {
    val cacheKey: String
        get() = "localzip|${zip.absolutePath}|${zip.lastModified()}|$entry"
}

/** 自定义 Fetcher：按条目名从 zip 读流（整页字节进内存 Buffer——图片页体积有限，可接受） */
class LocalPageFetcher(private val page: LocalPage, private val cacheDir: File) : Fetcher {
    override suspend fun fetch(): SourceResult {
        val (bytes, mime) = withContext(Dispatchers.IO) {
            val zf = ZipFile(page.zip)
            zf.use {
                val e = it.getEntry(page.entry) ?: throw java.io.IOException(AppI18n.sf("页面条目不存在：%1", page.entry))
                val data = it.getInputStream(e).use { ins -> ins.readBytes() }
                data to localMimeOf(page.entry)
            }
        }
        // 顶层工厂 ImageSource(source, cacheDirectory)：整页字节进内存 Buffer（图片页体积有限，可接受）
        val src = ImageSource(okio.Buffer().apply { write(bytes) }, cacheDir)
        return SourceResult(src, mime, DataSource.DISK)
    }

    class Factory : Fetcher.Factory<LocalPage> {
        override fun create(data: LocalPage, options: Options, imageLoader: coil.ImageLoader): Fetcher =
            LocalPageFetcher(data, options.context.cacheDir)
    }
}

class LocalSource(private val ctx: Context, val entry: LibraryStore.Entry) : ReaderSource {
    override val key: String get() = entry.key
    override val displayTitle: String get() = entry.work.dispWorkName()
    private val file = LibraryStore.workFile(ctx, entry)

    @Volatile private var pagesList: List<Pair<String, String>>? = null   // (条目名, kind)

    private fun loadPages(): List<Pair<String, String>> {
        pagesList?.let { return it }
        synchronized(this) {
            pagesList?.let { return it }
            if (!file.exists()) throw Exception(AppI18n.sf("本地文件不存在（可能已被删除）：%1", entry.work))
            val out = mutableListOf<Pair<String, String>>()
            ZipFile(file).use { zf ->
                val names = zf.entries().asSequence()
                    .filter { !it.isDirectory }
                    .map { it.name }
                    .filter { n ->
                        val ext = n.substringAfterLast('.', "").lowercase()
                        ext in PAGE_IMAGE_EXTS || ext in PAGE_VIDEO_EXTS
                    }
                    .sortedWith { a, b -> naturalCompare(a, b) }
                    .toList()
                for (n in names) out.add(n to localKindOf(n))
            }
            pagesList = out
            return out
        }
    }

    override suspend fun loadMeta(): ReaderMeta = withContext(Dispatchers.IO) {
        val p = loadPages()
        if (p.isEmpty()) throw Exception(AppI18n.s(AppI18n.s(AppI18n.s(AppI18n.s(AppI18n.s("本地包内没有可读页面"))))))
        ReaderMeta(p.size, p.map { it.second }, detectVersions(p))
    }

    /** 本地 zip 多版本检测(与面板 _page_versions 同口径):一级子目录分组,≥2 组且每组 ≥5 页 */
    private fun detectVersions(pages: List<Pair<String, String>>): List<ReaderVersion> {
        val groups = LinkedHashMap<String, MutableList<Int>>()
        for ((i, pair) in pages.withIndex()) {
            val name = pair.first
            if ("/" !in name) continue
            val seg = name.substringBefore('/').trim()
            if (seg.isNotEmpty()) groups.getOrPut(seg) { mutableListOf() }.add(i)
        }
        if (groups.size < 2) return emptyList()
        val extSuffix = Regex("（png）$|（jpg）$|（jpeg）$|（gif）$|（webp）$")
        val vers = groups.filter { it.value.size >= 5 }.map { (seg, idx) ->
            ReaderVersion(extSuffix.replace(seg, "").trim(), idx)
        }
        return if (vers.size >= 2) vers else emptyList()
    }

    override suspend fun resumePage(total: Int): Int = withContext(Dispatchers.IO) {
        // 3.6.9 本地书架续读不参与服务端续读区：本地作品只读本地 lastPage，
        // 不再回退查服务端（老冲账记录可能比本地旧，会覆盖本地进度）
        entry.lastPage.coerceIn(0, (total - 1).coerceAtLeast(0))
    }

    override fun pageModel(n: Int): Any = LocalPage(file, loadPages()[n].first)

    override suspend fun videoUri(n: Int): String = withContext(Dispatchers.IO) {
        val name = loadPages()[n].first
        val dir = File(ctx.cacheDir, "offline_video/" + key.replace("/", "__"))
        val dst = File(dir, name.substringAfterLast('/').ifEmpty { "page.webm" })
        if (!dst.exists() || dst.length() == 0L) {
            dir.mkdirs()
            ZipFile(file).use { zf ->
                val e = zf.getEntry(name) ?: throw java.io.IOException(AppI18n.sf("视频页缺失：%1", name))
                zf.getInputStream(e).use { ins -> dst.outputStream().use { ins.copyTo(it) } }
            }
        }
        android.net.Uri.fromFile(dst).toString()
    }

    override suspend fun authorName(): String =
        entry.personals.firstOrNull() ?: entry.circle

    override suspend fun reportProgress(page: Int, finished: Boolean?) = withContext(Dispatchers.IO) {
        // 3.6.9 本地书架续读只在书架内部记录（saveLocalProgress 本地落盘），
        // 不再 postReadingState 上报服务端、不再入 pending 冲账队列 —— 不参与续读区计数
        LibraryStore.saveLocalProgress(ctx, entry.key, page, finished)
    }

    override fun cleanup() {
        try {
            File(ctx.cacheDir, "offline_video/" + key.replace("/", "__")).deleteRecursively()
        } catch (_: Exception) {}
    }

    // ---- 音声（本地 zip 直读；音频轨解压缓存保留 —— 65MB 级整轨重解压代价高，交给系统缓存管理） ----

    @Volatile private var audioList: List<Pair<String, Long>>? = null   // (条目名, size)

    private fun loadAudio(): List<Pair<String, Long>> {
        audioList?.let { return it }
        synchronized(this) {
            audioList?.let { return it }
            if (!file.exists()) return emptyList()
            val out = mutableListOf<Pair<String, Long>>()
            ZipFile(file).use { zf ->
                zf.entries().asSequence()
                    .filter { !it.isDirectory }
                    .filter { it.name.substringAfterLast('.', "").lowercase() in AUDIO_EXTS }
                    .sortedWith { a, b -> naturalCompare(a.name, b.name) }
                    .forEach { out.add(it.name to it.size) }
            }
            audioList = out
            return out
        }
    }

    private fun findLocalLrc(stem: String): List<Pair<Long, String>> {
        if (!file.exists()) return emptyList()
        ZipFile(file).use { zf ->
            val e = zf.entries().asSequence()
                .firstOrNull {
                    !it.isDirectory &&
                        it.name.substringAfterLast('.', "").lowercase() == "lrc" &&
                        it.name.substringAfterLast('/').substringBeforeLast('.') == stem
                } ?: return emptyList()
            zf.getInputStream(e).use { return parseLrcBytes(it.readBytes()) }
        }
    }

    override suspend fun audioTracks(): List<Api.AudioTrack> = withContext(Dispatchers.IO) {
        loadAudio().map { (name, size) ->
            val stem = name.substringAfterLast('/').substringBeforeLast('.')
            Api.AudioTrack(name, size, findLocalLrc(stem))
        }
    }

    override suspend fun audioUri(n: Int): String = withContext(Dispatchers.IO) {
        val name = loadAudio().getOrNull(n)?.first ?: throw java.io.IOException(AppI18n.s(AppI18n.s(AppI18n.s(AppI18n.s(AppI18n.s("音声轨不存在"))))))
        val dir = File(ctx.cacheDir, "offline_audio/" + key.replace("/", "__"))
        val dst = File(dir, name.substringAfterLast('/').ifEmpty { "track.mp3" })
        if (!dst.exists() || dst.length() == 0L) {
            dir.mkdirs()
            ZipFile(file).use { zf ->
                val e = zf.getEntry(name) ?: throw java.io.IOException(AppI18n.sf("音声轨缺失：%1", name))
                zf.getInputStream(e).use { ins -> dst.outputStream().use { ins.copyTo(it) } }
            }
        }
        android.net.Uri.fromFile(dst).toString()
    }
}
