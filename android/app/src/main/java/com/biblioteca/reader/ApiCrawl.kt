package com.biblioteca.reader

import org.json.JSONObject
import java.io.File

/* 爬虫与探种族（3.7.43 从 Api.kt 拆出）：任务状态/启停/清单 + 版本信息 + 探活。 */


/** 服务端派发的最新 APK（app_releases/ 目录），无包时返回 null */
internal fun Api.appVersion(): Api.AppVersionInfo? {
    val o = getJson("/api/app-version")
    val l = o.optJSONObject("latest") ?: return null
    return Api.AppVersionInfo(
        l.optString("versionName"), l.optInt("versionCode"),
        l.optString("apkUrl"), l.optLong("size")
    )
}


/** 老面板没有 panelVersion/apiLevel 字段时，退化为"与本 APP 同级"，不误报不兼容 */
internal fun Api.serverInfo(): Api.ServerInfo {
    val o = getJson("/api/config")
    val ver = o.optString("panelVersion").ifEmpty { o.optString("version") }
    return Api.ServerInfo(ver, o.optInt("apiLevel", APP_API_LEVEL), o.optInt("minAppApi", 1))
}


/** 3.7.109：面板发行版可用的内置爬取任务（公开版只带 jmdl/ext）。
 *  null = 老面板没有该字段 → 调用方视为"全部可用"。 */
internal fun Api.builtinKinds(): List<String>? {
    val o = getJson("/api/config")
    val arr = o.optJSONArray("builtinKinds") ?: return null
    val out = mutableListOf<String>()
    for (i in 0 until arr.length()) out.add(arr.optString(i))
    return out
}


/** 3.7.110 内测模式：读服务端当前状态。老面板没有 safeCovers 字段 → false（不误开）。
 *
 *  3.7.111：服务端改按端返回——APP 的请求带 `X-Client: app`，拿到的就是**手机这一端**
 *  自己的值，网页那边的开关不再影响这里。 */
internal fun Api.fetchSafeCovers(): Boolean {
    val o = getJson("/api/config")
    val on = o.optBoolean("safeCovers", false)
    safeCovers = on
    return on
}


/** 3.7.110 内测模式：切换并回写本地镜像。返回服务端确认后的值。
 *
 *  3.7.111：带 `safe_covers_scope=app`，**只切手机这一端**——不带 scope 会被服务端
 *  理解成"两端一起设"，那正是这次要修掉的行为。 */
internal fun Api.setSafeCovers(on: Boolean): Boolean {
    val o = postJson("/api/config", JSONObject().put("safe_covers", on)
        .put("safe_covers_scope", "app"))
    val now = o.optBoolean("safeCovers", on)
    safeCovers = now
    return now
}


/**
 * 爬虫状态。since >= 0 走增量日志（只回传新行），since < 0 走末尾 N 行。
 * kind 指定取哪个任务的日志（3.6.7 起三任务日志各自独立）。
 */
internal fun Api.crawlStatus(since: Long = -1, kind: String? = null): Api.CrawlStatus {
    val q = buildList {
        if (since >= 0) add("since=$since")
        if (kind != null) add("kind=$kind")
    }.joinToString("&")
    val o = getJson("/api/crawl/status" + if (q.isEmpty()) "" else "?$q")
    fun lines(key: String): List<String> {
        val arr = o.optJSONArray(key) ?: return emptyList()
        val out = mutableListOf<String>()
        for (i in 0 until arr.length()) out.add(arr.optString(i))
        return out
    }
    val tasks = mutableListOf<Api.CrawlTask>()
    val tarr = o.optJSONArray("tasks")
    if (tarr != null) for (i in 0 until tarr.length()) {
        val t = tarr.optJSONObject(i) ?: continue
        tasks.add(Api.CrawlTask(
            t.optString("kind"), t.optBoolean("running"),
            if (t.isNull("pid")) null else t.optInt("pid"),
            if (t.isNull("startedAt")) null else t.optLong("startedAt"),
            t.optInt("total"), t.optInt("done"), t.optInt("failed")))
    }
    return Api.CrawlStatus(
        o.optBoolean("running"), o.optString("kind").ifEmpty { null },
        if (o.isNull("pid")) null else o.optInt("pid"),
        if (o.isNull("startedAt")) null else o.optLong("startedAt"),
        o.optInt("total"), o.optInt("done"), o.optInt("failed"), lines("logTail"),
        lines("logLines"), o.optLong("logCursor"), o.optLong("logSize"),
        tasks, o.optString("logKind", "wnacg")
    )
}


/**
 * 3.7.59：五个任务里**正在运行**的那些 kind（只给胶囊上色，不带 items）。
 * 用 `?all=1` 的精简快照，5 个任务一起拉也不重。
 */
internal fun Api.crawlRunningKinds(): Set<String> {
    val o = getJson("/api/crawl/job?all=1")
    val arr = o.optJSONArray("jobs") ?: return emptySet()
    val out = mutableSetOf<String>()
    for (i in 0 until arr.length()) {
        val j = arr.optJSONObject(i) ?: continue
        if (j.optBoolean("running")) out.add(j.optString("kind"))
    }
    return out
}


/**
 * 3.7.58：两段式爬取任务的进度快照（先锁定作品、再集中爬取）。
 * 面板靠它画逐部卡片（封面 + 状态 + 字节进度），不再靠日志文本反推。
 */
internal fun Api.crawlJob(kind: String): Api.CrawlJob? {
    val o = getJson("/api/crawl/job?kind=" + kind)
    if (!o.optBoolean("ok")) return null
    val items = mutableListOf<Api.CrawlItem>()
    val arr = o.optJSONArray("items")
    if (arr != null) for (i in 0 until arr.length()) {
        val it = arr.optJSONObject(i) ?: continue
        items.add(Api.CrawlItem(
            it.optInt("idx"), it.optString("entry"), it.optString("title"),
            it.optString("site"), it.optString("aid"), it.optString("cover"),
            it.optString("state", "queued"), it.optString("msg"),
            it.optLong("bytes"), it.optLong("bytes_total"), it.optInt("pages")))
    }
    return Api.CrawlJob(
        o.optString("kind"), o.optString("label"), o.optBoolean("running"),
        o.optString("phase", "idle"), o.optInt("total"), o.optInt("done"),
        o.optInt("failed"), o.optInt("skipped"), o.optInt("locked"), o.optInt("queued"),
        o.optLong("started"), o.optLong("finished"), o.optInt("elapsed"),
        o.optString("current"), o.optString("message"),
        o.optInt("covers"), o.optInt("covers_ready"), items)
}


internal fun Api.crawlStart(kind: String, limit: Int, entries: List<String>?,
               strict: Boolean = false, jmEntries: List<String>? = null,
               tool: String = ""): String {
    val body = JSONObject().put("kind", kind).put("limit", limit)
    if (entries != null) body.put("entries", org.json.JSONArray(entries))
    if (jmEntries != null) body.put("jmEntries", org.json.JSONArray(jmEntries))
    if (tool.isNotEmpty()) body.put("tool", tool)
    if (strict) body.put("strict", true)
    return postJson("/api/crawl/start", body).optString("message", AppI18n.s("已启动"))
}


internal fun Api.crawlStop(kind: String): String =
    postJson("/api/crawl/stop", JSONObject().put("kind", kind))
        .optString("message", AppI18n.s("已停止"))


internal fun Api.crawlListGet(): Api.CrawlLists {
    val o = getJson("/api/crawl/list")
    return Api.CrawlLists(o.optString("wnacg"), o.optString("index"),
        o.optString("jmdlTitles"), o.optString("jmdlIds"),
        o.optString("nhIds"), o.optString("nhdlIds"), o.optString("ehIds"),
        o.optString("ext"))
}


internal fun Api.crawlListSave(wnacg: String, index: String,
                  jmdlTitles: String, jmdlIds: String,
                  nhIds: String = "", nhdlIds: String = "",
                  ehIds: String = "", ext: String = ""): String =
    postJson("/api/crawl/list", JSONObject()
        .put("wnacg", wnacg).put("index", index)
        .put("jmdlTitles", jmdlTitles).put("jmdlIds", jmdlIds)
        .put("nhdlIds", nhdlIds).put("ehIds", ehIds).put("ext", ext))
        .optString("message", AppI18n.s("清单已保存"))


internal fun Api.probe(): Boolean {
    val resp = probeHttp.newCall(req("/api/library/meta").get().build()).execute()
    resp.use { return it.isSuccessful }
}
