package com.biblioteca.reader

import androidx.compose.runtime.mutableStateOf
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.File
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

class AuthException : Exception(AppI18n.s("需要访问令牌"))
class ApiException(msg: String) : Exception(msg)

/** 用户在下载管理中点了「停止」：穿透 downloadResumable 的重试循环，半成品 .part 保留可续传 */
class DownloadStoppedException : Exception(AppI18n.s("下载已停止"))

/**
 * 本 APP build 所说的「接口级别」，与面板 /api/config 的 apiLevel / minAppApi 做机器判定：
 *   - 面板的 minAppApi > 本值 → 本 APP 太旧，必须更新 APP；
 *   - 面板的 apiLevel  < 本值 → 面板太旧，建议重启/更新面板。
 * 面板只在**破坏性**接口改动时提高 minAppApi/API 级，届时此处 +1 并随该版 APP 发布。
 * 基线：vc30（2.6.0-beta.7）对应 API 1。
 */
const val APP_API_LEVEL = 1

object Api {
    var baseUrl: String = ""

    var token: String = ""


    /**
     * 图片质量模式（设置页可改，存 SharedPreferences）：
     *   "auto" 不传参 → 服务端自己判：本机/局域网/直连给原图，走 Tailscale 中继给压缩图；
     *   "orig" 强制原图（家里 Wi-Fi 下想看清细节时用）；
     *   "low"  强制省流（外面用流量、或中继很卡时用；动图会抽帧 + 缩小，动画仍在）。
     */
    var imgMode: String = "auto"

    /**
     * 3.7.110 内测模式：所有封面换成占位图（服务端 panel/safecover.py 统一替换）。
     * 服务端是唯一事实源——这里只是本地镜像，抽屉开关按它显示位置，封面 URL 按它加
     * `&sc=1`（换缓存键，否则 Coil 会继续用内存里的旧封面）。
     *
     * 3.7.112：改用 Compose State 承载。原先它是普通静态变量，**不参与快照订阅**——
     * `coverUrl()` 读它时不会建立依赖，开关一变，只有"碰巧因别的原因重组"的那些
     * Composable 才重算 URL，其余仍拿着旧 URL 显示旧图，表现就是"部分作品封面没换"。
     * 换成 mutableStateOf 之后，凡是调过 coverUrl 的 Composable 都会自动重组。
     */
    private val safeCoversState = mutableStateOf(false)
    var safeCovers: Boolean
        get() = safeCoversState.value
        set(v) { safeCoversState.value = v }


    internal val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
        // 文件上传必须显式放大写超时：OkHttp 默认仅 10 秒，大文件经 Tailscale 中继
        // 上传时链路一旦停滞 >10s 就断（表现：连接成功但传输失败）
        .writeTimeout(120, TimeUnit.SECONDS)
        .build()


    /** 拼完整地址。**以 http(s) 开头视为绝对地址**——配对 claim 要打刚扫到的那台服务器，
     *  此刻 `baseUrl` 还是旧的（或空的），不能拼在它后面。 */
    fun url(path: String): String =
        if (path.startsWith("http://") || path.startsWith("https://")) path
        else baseUrl.trimEnd('/') + path


    internal fun req(path: String): Request.Builder {
        val b = Request.Builder().url(url(path))
        // 3.7.111：声明"这是 APP"。服务端按这个头区分端——内测模式已改为各端独立
        // （网页开了不该连带手机一起遮），封面出口要据此取各自那一端的开关。
        // 浏览器不会发这个头，服务端默认算 web，所以网页侧不需要改。
        b.header("X-Client", "app")
        if (token.isNotEmpty()) b.header("X-Token", token)
        return b
    }


    fun enc(s: String): String = URLEncoder.encode(s, "UTF-8")


    /** 用于 URL 路径段：URLEncoder 会把空格编成 +，而 Flask 路径不解码 +，导致 404 */
    fun encPath(s: String): String = URLEncoder.encode(s, "UTF-8").replace("+", "%20")


    /**
     * 封面 URL。ver 是服务端给的内容版本键（作品 ver / 社团 coverVer）：
     * Coil 的内存缓存与磁盘缓存都按 URL 索引，不带版本键时「删了首页图片」URL 不变 →
     * 永远显示旧图。带上 ver 后内容一变（改名/删首页图片/重扫）URL 就变，缓存自然失效。
     * 不传 ver 时自动查版本登记表（由 /api/library、/api/circle、/api/pages 的响应填充），
     * 这样阅读器/列表等大量既有调用点无需逐个改签名也能拿到正确的缓存键。
     */
    fun coverUrl(group: String, work: String, ver: String = ""): String {
        val v = ver.ifEmpty { verOf(group, work) }
        return url("/cover?group=${enc(group)}&work=${enc(work)}" +
            (if (v.isNotEmpty()) "&v=${enc(v)}" else "") +
            // 3.7.110 内测模式：仅换缓存键，服务端不解析 sc（面板统一在路由层换图）
            (if (safeCovers) "&sc=1" else "") +
            "&token=${enc(token)}")
    }


    fun pageUrl(group: String, work: String, n: Int, ver: String = ""): String {
        val v = ver.ifEmpty { verOf(group, work) }
        return url("/page?group=${enc(group)}&work=${enc(work)}&n=$n" +
            (if (v.isNotEmpty()) "&v=${enc(v)}" else "") + imgParam() + "&token=${enc(token)}")
    }


    /** 图片质量参数：auto 不传（交给服务端判断），其余显式指定 */
    fun imgParam(): String =
        if (imgMode == "orig" || imgMode == "low") "&img=$imgMode" else ""


    // 作品/社团封面内容版本登记表（group + work → ver）
    private val verCache = java.util.concurrent.ConcurrentHashMap<String, String>()


    private fun verKey(group: String, work: String) = group + "\u0000" + work


    fun rememberVer(group: String, work: String, ver: String) {
        if (group.isNotEmpty() && work.isNotEmpty() && ver.isNotEmpty()) {
            verCache[verKey(group, work)] = ver
        }
    }


    fun verOf(group: String, work: String): String = verCache[verKey(group, work)] ?: ""


    /** 文库/社团数据整体换新后清空（避免版本登记表留下上一轮的值） */
    fun clearVerCache() = verCache.clear()


    internal val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()

    internal val BIN_MEDIA = "application/octet-stream".toMediaType()


    /** POST JSON，返回解析后的响应体；非 2xx 抛 ApiException（带服务端 message）。 */
    fun postJson(path: String, body: JSONObject): JSONObject {
        val (code, obj) = postJsonRaw(path, body)
        if (code == 401) throw AuthException()
        if (code !in 200..299) throw ApiException(obj.optString("message").ifEmpty { "HTTP $code" })
        return obj
    }


    /** POST JSON 原始版：返回 (httpCode, 响应JSON)，供需要处理 409 冲突等场景。 */
    fun postJsonRaw(path: String, body: JSONObject): Pair<Int, JSONObject> {
        val resp = http.newCall(req(path).post(body.toString().toRequestBody(JSON_MEDIA)).build()).execute()
        resp.use {
            val text = it.body?.string() ?: ""
            val obj = if (text.isNotEmpty()) {
                try { JSONObject(text) } catch (_: Exception) { JSONObject() }
            } else JSONObject()
            return it.code to obj
        }
    }


    fun getJson(path: String): JSONObject {
        val resp = http.newCall(req(path).get().build()).execute()
        resp.use {
            val body = it.body?.string() ?: ""
            if (it.code == 401) throw AuthException()
            if (!it.isSuccessful) throw ApiException("HTTP ${it.code}")
            return JSONObject(body)
        }
    }


    data class Group(
        val name: String, val workCount: Int, val hasCover: Boolean,
        val coverWork: String, val coverMtime: Long, val coverVer: String = "",
        // 社团排序用（秒，与服务端 createdAt/updatedAt 同单位）：
        // createdAt = 档案创建时间；updatedAt = 最近入库新作品的时间
        val createdAt: Double = 0.0, val updatedAt: Double = 0.0,
        // 3.6.151：社团占用空间（字节）——社团排序已不用（3.6.166 删档），留作兼容
        val totalBytes: Long = 0L,
        // 3.6.166：封面那部作品**实际所在的社团**。社团封面可能跟随画师页口径取自别的
        // 社团（单画师社团 / 手设覆盖），此时 coverGroup ≠ name；拼封面 URL 必须用它，
        // 否则请求落在本社团名下、找不到那部作品，封面直接 404（用户报障：APP 社团封面空白）。
        val coverGroup: String = ""
    )


    data class Work(
        val name: String, val pages: Int, val hasCover: Boolean,
        val personal: String, val bare: String, val ver: String = "",
        // 作者多值（v2.11 数据模型）：合作作品每位作者一个；空 → 回退 personal 单值
        val personals: List<String> = emptyList(),
        // 3.6.27：归一的圈子名（目录名≠圈子名时与社团浏览一致）；空则回退展示群组名
        val circle: String = "",
        // 3.6.27 需求4：作品标签（type/name），作品卡展示原作标签用
        val tags: List<Pair<String, String>> = emptyList(),
        // 3.7.40：文件修改时间（秒）。此前是分区内"新→旧"排序键——但删首页图等重写
        // 操作会推进 mtime（作品错误顶到"最新"），3.7.69 起排序改用 addedAt（首次入库
        // 时间），mtime 仅作 addedAt 缺省（0）时的兜底。
        val mtime: Double = 0.0,
        // 3.7.69：首次入库时间（秒，服务端 _stamp_added_at 盖入/public_work 下发）
        val addedAt: Double = 0.0,
        // 3.6.151：文件大小（字节）——「按文件大小」排序查重用（重复下载的体积相近）
        val size: Long = 0L,
    ) {
        val authors: List<String>
            get() = if (personals.isNotEmpty()) personals
                    else if (personal.isNotEmpty()) listOf(personal) else emptyList()

        /** 原作分区名（type == "original" 的标签）——作品卡下方展示。 */
        val originals: List<String>
            get() = tags.filter { it.first == "original" }.map { it.second }
    }


    data class Rec(val group: String, val work: String, val pages: Int)

    data class TagItem(val name: String, val count: Int,
                       val coverGroup: String? = null, val coverWork: String? = null)

    // 社团页头部封面（设为社团封面后即时可见；无覆盖时回退派生封面）
    data class CircleCover(val coverGroup: String?, val coverWork: String?, val coverVer: String)

    data class WorkHit(val group: String, val work: Work)

    /** 3.6.20 #25：宽松匹配的既有原作分区（添加前明示"将并入该分区"） */
    data class SimilarZone(val name: String, val works: Int)

    /** 添加原作预览结果：命中作品 + 相近既有分区 */
    data class OriginalSearch(val hits: List<WorkHit>, val similar: List<SimilarZone>)

    data class Library(
        val groups: List<Group>, val recs: List<Rec>,
        val tags: Map<String, List<TagItem>> = emptyMap()
    )


    data class PagesInfo(
        val total: Int, val kinds: List<String>, val ver: String,
        // 3.2.4 多版本作品:如 RJ 包的 日文原版/汉化版(name, 绝对页序列表);无多版本时为空表
        val versions: List<Pair<String, List<Int>>>,
    )


    // ---------- v2.4 增补信息 ----------

    data class SupplementFields(
        val uncensored: Boolean,
        val event: String,
        val circle: String,
        val personal: String,
        val title: String,
        val original: String,
        val translator: String,   // 3.6.11 汉化组（【…】），位置在「其他信息」之前
        val otherInfo: String,
    )


    data class ParseInfo(
        val file: String,
        val base: String,
        val uncensored: Boolean,
        val event: String,
        val circle: String,
        val personal: String,
        val bare: String,
        val title: String,
        val original: String,
        val translator: String,   // 3.6.11 汉化组（【…】词条）
        val otherInfo: String,    // 3.6.11 起含整标题里其余全部有效内容（语言标记/其他括号…）
    )


    /** 文库修订号探针：极轻量，用于发现"面板侧改过文库"并自动刷新（不必手动下拉）。 */
    data class LibraryMeta(val rev: Int, val scannedAt: Long, val scanning: Boolean)


    // 分块上传专用客户端:禁用连接池复用——块间空闲期连接会被 NAT/链路掐死,
    // 复用死连接写出的块全部丢失(服务端日志:只有 idx=0 到达)。每块强制全新连接。
    internal val uploadHttp: OkHttpClient = http.newBuilder()
        .connectionPool(okhttp3.ConnectionPool(0, 1, java.util.concurrent.TimeUnit.NANOSECONDS))
        .build()


    data class AppVersionInfo(val versionName: String, val versionCode: Int,
                              val apkUrl: String, val size: Long)


    /** 面板版本与接口级别（分轴版号：面板号 ≠ APP 号，靠 apiLevel 判兼容） */
    data class ServerInfo(val panelVersion: String, val apiLevel: Int, val minAppApi: Int)


    // ---------- v2.5 爬虫管理 / 收件箱一键归档 / 共享文档识别词条 ----------

    /** 3.6.7：单任务快照（三任务各自独立进程/日志/断点/清单） */
    data class CrawlTask(
        val kind: String, val running: Boolean, val pid: Int?, val startedAt: Long?,
        val total: Int, val done: Int, val failed: Int
    )


    data class CrawlStatus(
        val running: Boolean, val kind: String?, val pid: Int?, val startedAt: Long?,
        val total: Int, val done: Int, val failed: Int, val logTail: List<String>,
        // 增量日志：传 since=<上一轮 logCursor> 时服务端只回传新行（连续滚动，不再整段重传）
        val logLines: List<String> = emptyList(),
        val logCursor: Long = 0, val logSize: Long = 0,
        // 3.6.7：三任务快照（顶层字段为「优先任务」的兼容镜像）
        val tasks: List<CrawlTask> = emptyList(),
        val logKind: String = "wnacg"
    )


    /** 3.7.58 两段式爬取任务的一个条目：锁定到的作品 + 封面 + 下载字节进度 */
    data class CrawlItem(
        val idx: Int, val entry: String, val title: String, val site: String,
        val aid: String, val cover: String, val state: String, val msg: String,
        val bytes: Long, val bytesTotal: Long, val pages: Int
    )

    /** 3.7.58 两个阶段：lock（逐条锁定作品）→ download（集中爬取）→ done */
    data class CrawlJob(
        val kind: String, val label: String, val running: Boolean, val phase: String,
        val total: Int, val done: Int, val failed: Int, val skipped: Int,
        val locked: Int, val queued: Int, val started: Long, val finished: Long,
        val elapsed: Int, val current: String, val message: String,
        // 3.7.64：封面准备阶段（下载前必须备好）
        val covers: Int = 0, val coversReady: Int = 0,
        val items: List<CrawlItem> = emptyList()
    )

    /** 3.6.7：清单各自独立；3.6.36：索引系整合为共享清单 index（jm/nh 同文件）；
     *  3.6.110：E站直连清单 ehIds；3.6.155：外接下载器清单 ext */
    data class CrawlLists(val wnacg: String, val index: String,
                          val jmdlTitles: String, val jmdlIds: String,
                          val nhIds: String = "", val nhdlIds: String = "",
                          val ehIds: String = "", val ext: String = "")


    // ---------- v3.0 导出与离线阅读 / 阅读状态同步 ----------

    data class ExportManifest(
        val name: String, val group: String, val work: String,
        val file: String,               // 原始归档文件名（含扩展名；本地落盘沿用）
        val size: Long, val mtime: Double, val pages: Int, val kind: String,
        val circle: String, val personals: List<String>, val bare: String,
        val tags: List<Pair<String, String>>,
        val downloadable: Boolean,
    )


    data class ReadingState(val lastPage: Int, val finished: Boolean, val lastReadAt: Long)


    // ---------- v3.0.1 音声作品（音频 + lrc 同步字幕） ----------

    data class AudioTrack(val name: String, val size: Long, val lrc: List<Pair<Long, String>>) {
        /** 轨道短名（"1-01 椎菜と….mp3" → "1-01"） */
        val shortName: String get() = name.substringBefore(' ').ifEmpty { name }
    }


    // ---------- v3.1 继续阅读 / 个人统计 / 收件箱 ----------

    data class ResumeItem(
        val key: String, val lastPage: Int, val finished: Boolean, val lastReadAt: Long,
        val group: String?, val work: String?, val pages: Int?,
        // 2026-10-15 需求1：续读卡片标签化（社团可点进社团、画师可点进画师档案）
        val circle: String = "", val personals: List<String> = emptyList(),
        // 3.7.51：原作标签（任何分区的作品卡都要显示，服务端已随行下发）
        val originals: List<String> = emptyList(),
    )


    data class StatsOverview(
        val works: Int, val pages: Long, val finished: Int, val started: Int,
        val favorites: Int, val rated: Int, val circles: Int,
        val byDay: List<Pair<String, Int>>,      // (日期, 入库数) 升序
        val topAuthors: List<Pair<String, Int>>, // (画师, 作品数) 降序
    )


    data class InboxItem(
        val id: Int, val name: String, val size: Long, val state: String, val exists: Boolean,
        val kind: String, val circle: String, val bare: String,
        val newName: String, val confidence: String, val dupName: String?,
    ) {
        val pending: Boolean get() = state == "pending" && exists
    }


    /** 下载中断留下的半成品（不是作品，只在清理横条里展示）。 */
    data class InboxPart(val name: String, val size: Long, val ageH: Double)


    data class InboxSnapshot(val items: List<InboxItem>, val parts: List<InboxPart>)


    // ---------- v3.2 画师档案与关注 ----------

    data class ArtistWork(val key: String, val group: String, val work: String,
                          val pages: Int, val addedAt: Long,
                          // 3.6.14：归一的展示社团名（圈子名）——目录名≠圈子名时卡片标签显示它
                          val circle: String = "",
                          // 2026-10-15 需求3：作品全部作者（合作作品多人），卡片只显示合作者（滤掉本画师）
                          val personals: List<String> = emptyList(),
                          // 3.7.40：文件修改时间（服务端早已下发，此前未解析）——画师页"新→旧"排序用
                          val mtime: Long = 0L,
                          // 3.7.51：原作标签——画师页卡片也要显示（此前只有原作分区页有）
                          val originals: List<String> = emptyList(),
                          // 3.6.151：文件大小（字节）——画师页「按文件大小」排序查重用
                          val size: Long = 0L)


    data class ArtistPage(val author: String, val isFollowing: Boolean,
                          val aliases: List<String>,
                          val circles: List<Pair<String, Int>>,
                          val works: List<ArtistWork>,
                          val coverGroup: String?, val coverWork: String?,
                          val coverMtime: Long, val coverVer: String)


    data class FollowItem(val author: String, val works: Int, val newCount: Int,
                          val coverGroup: String?, val coverWork: String?, val coverVer: String)


    data class ArtistItem(val name: String, val works: Int, val latest: Long,
                          val coverGroup: String?, val coverWork: String?,
                          val coverVer: String, val followed: Boolean)


    data class OriginalItem(val name: String, val works: Int, val latest: Long,
                            val coverGroup: String?, val coverWork: String?,
                            val coverVer: String)


    data class ReadingSummary(
        val states: Map<String, Pair<Int, Boolean>>,   // key → (last_page, finished)
        val newKeys: Set<String>,                      // 基线之后新入库的作品 key
    )


    // ---------- 3.5.0 维护 → 3.6.11 收窄为「别名登记」 ----------
    // 备份恢复 / 本机路径导入 3.6.11 起只在面板（本地）做，移动端只保留别名登记，
    // 并扩展到社团名：kind = "author" 笔名 | "circle" 社团。

    data class BackupItem(val file: String, val at: Long, val size: Long, val note: String)


    data class ImportPathResult(val imported: Int, val sourceCount: Int,
                                val stashId: String, val text: String)


    /**
     * 快速探活（离线模式判定）：专用短超时客户端，连不上即按离线处理。
     * 复用 /api/library/meta —— 极轻量、不触发扫描。
     */
    internal val probeHttp: OkHttpClient = http.newBuilder()
        .connectTimeout(3, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.SECONDS)
        .build()
}
