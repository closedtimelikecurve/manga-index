package com.biblioteca.reader

import org.json.JSONObject

/* 3.7.54「分区爬取」的接口层：按作者 / 社团 / 原作名搜索 → 勾选 → 后台下载并自动入库归区。
   服务端：routes/probe.py（搜索 / 封面 / 起任务 / 进度 / 取消）。 */

/** 搜索命中的一条（站点作品卡）。cover 是本站代理地址（`/api/crawl/probe/cover?u=…`）。
 *  token 是 E站画廊 token（勾选下载必需；其它站为空）。 */
data class ProbeWork(val aid: Int, val title: String, val pages: Int, val cover: String,
                     /** 3.7.61：库内疑似重复的作品名（空 = 不重复）；判定在服务端做 */
                     val dupName: String = "", val token: String = "")

/** 任务里的一部作品：state = queued / downloading / importing / ok / fail / skip。
 *  bytes / bytesTotal 是 3.7.56 的下载字节进度（旧服务端没有时默认 0）；
 *  cover 是 3.7.69 看板封面卡用的代理地址（picks 自带，旧服务端没有时为空）。 */
data class ProbeItem(val aid: Int, val title: String, val state: String, val msg: String,
                     val bytes: Long = 0, val bytesTotal: Long = 0, val cover: String = "")

/** 一次勾选任务。3.7.56 新增字段与网页 `pick_status()` 对齐：
 *  elapsed/current/currentState/queue/rev/term/kind 让任何界面只凭一次响应就能画进度。 */
data class ProbeJob(val running: Boolean, val done: Int, val failed: Int, val total: Int,
                    val message: String, val finished: Long, val items: List<ProbeItem>,
                    val elapsed: Int = 0, val current: String = "", val currentState: String = "",
                    val queue: Int = 0, val rev: Int = 0, val term: String = "", val kind: String = "",
                    val site: String = "wnacg", val id: Long = 0)

/** 起任务的结果：error 非空即失败；job 是服务端立即返回的首帧进度（可能为 null）。 */
data class ProbePickResult(val error: String, val job: ProbeJob?)

/** 搜索结果（ok=false 时 message 是原因；works 为空表示站点没命中）。
 *  total = 站点报的命中总数；hasMore/nextStart 用于"继续加载"（纯增量，不重拉前面的页）。 */
data class ProbeResult(val ok: Boolean, val total: Int, val domain: String,
                       val works: List<ProbeWork>, val hasMore: Boolean = false,
                       val nextStart: Int = 1, val message: String = "",
                       val site: String = "wnacg", val autoLoad: Boolean = true)

/** pages=0 表示"按站点总数抓全"；start>1 表示从该页起增量抓（继续加载）。 */
internal fun Api.probeSearch(term: String, kind: String, pages: Int = 0,
                             start: Int = 1, site: String = "wnacg"): ProbeResult {
    val o = postJson("/api/crawl/probe", JSONObject().put("term", term)
        .put("kind", kind).put("pages", pages).put("start", start).put("site", site))
    val arr = o.optJSONArray("works")
    val works = mutableListOf<ProbeWork>()
    for (i in 0 until (arr?.length() ?: 0)) {
        val w = arr!!.optJSONObject(i) ?: continue
        works.add(ProbeWork(w.optInt("aid"), w.optString("title"),
            w.optInt("pages"), w.optString("cover"),
            w.optJSONObject("dup")?.optString("name") ?: "", w.optString("token")))
    }
    return ProbeResult(o.optBoolean("ok"), o.optInt("total"), o.optString("domain"),
        works, o.optBoolean("hasMore"), o.optInt("nextStart", 1), o.optString("message"),
        o.optString("site", "wnacg"), o.optBoolean("autoLoad", true))
}

/** 起后台任务：服务端立即返回首帧进度，后续靠 ProbeWatch 轮询。 */
internal fun Api.probePick(term: String, kind: String, picks: List<ProbeWork>,
                          site: String = "wnacg"): ProbePickResult {
    val arr = org.json.JSONArray()
    picks.forEach {
        arr.put(JSONObject().put("aid", it.aid).put("title", it.title)
            .put("token", it.token).put("cover", it.cover))
    }
    val o = postJson("/api/crawl/pick",
        JSONObject().put("term", term).put("kind", kind).put("picks", arr).put("site", site))
    val job = o.optJSONObject("job")?.let(::parseProbeJob)
    return ProbePickResult(
        if (o.optBoolean("ok")) "" else o.optString("message").ifEmpty { AppI18n.s("启动失败") }, job)
}

internal fun Api.probeJob(): ProbeJob? =
    getJson("/api/crawl/pick/status").optJSONObject("job")?.let(::parseProbeJob)

private fun parseProbeJob(o: JSONObject): ProbeJob {
    val arr = o.optJSONArray("items")
    val items = mutableListOf<ProbeItem>()
    for (i in 0 until (arr?.length() ?: 0)) {
        val it = arr!!.optJSONObject(i) ?: continue
        items.add(ProbeItem(it.optInt("aid"), it.optString("title"), it.optString("state"),
            it.optString("msg"), it.optLong("bytes"), it.optLong("bytes_total"),
            it.optString("cover")))
    }
    return ProbeJob(o.optBoolean("running"), o.optInt("done"), o.optInt("failed"),
        o.optInt("total"), o.optString("message"), o.optLong("finished"), items,
        o.optInt("elapsed"), o.optString("current"), o.optString("current_state"),
        o.optInt("queue"), o.optInt("rev"), o.optString("term"), o.optString("kind"),
        o.optString("site", "wnacg"), o.optLong("id"))
}

internal fun Api.probeCancel(): String =
    postJson("/api/crawl/pick/cancel", JSONObject()).optString("message")

/**
 * 封面 URL，两种形状都要吃得下（3.7.65）：
 *  * 分区爬虫给的是站内相对路径 `/api/crawl/probe/cover?u=…`，直接补 host + token；
 *  * 清单爬虫锁定阶段给的是**站点图床原始地址**（`t4.wnimg2.cfd` / `cdn-msp…`），
 *    手机直连会被图床按 Referer 拒掉，必须先套一层本站代理——网页端一直是这么拼的
 *    (`crawlmon.js`)，APP 早先漏了这一步，于是封面整列显示占位图。
 */
fun Api.probeCoverUrl(cover: String): String {
    if (cover.isEmpty()) return ""
    if (cover.startsWith("/")) return url(cover) + "&token=" + enc(token)
    val abs = if (cover.startsWith("//")) "https:$cover" else cover
    return url("/api/crawl/probe/cover?u=" + enc(abs)) + "&token=" + enc(token)
}
