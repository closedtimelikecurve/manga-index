package com.biblioteca.reader

import org.json.JSONObject
import java.io.File

/* 同步族（3.7.43 从 Api.kt 拆出）：阅读进度/音声/续读/统计/收件箱/画师/原作/关注。 */


/** 上次阅读位置（继续阅读）。无记录返回 0 页。 */
internal fun Api.readingState(key: String): Api.ReadingState {
    val o = getJson("/api/reading/state?key=${enc(key)}")
    return Api.ReadingState(o.optInt("last_page"), o.optBoolean("finished"), o.optLong("last_read_at"))
}


/** 上报阅读进度（finished=null 表示不动服务端的"已读"标记，避免往回翻被误清）。 */
internal fun Api.postReadingState(key: String, lastPage: Int, finished: Boolean?): JSONObject {
    val body = JSONObject().put("key", key).put("last_page", lastPage)
    if (finished != null) body.put("finished", finished)
    return postJson("/api/reading/state", body)
}


/** 音声清单（轨道 + 同名 lrc 的毫秒时间轴）。无音声/旧面板（无此端点）→ 空表。 */
internal fun Api.audioManifest(group: String, work: String): List<Api.AudioTrack> {
    val o = getJson("/api/audio/manifest?group=${enc(group)}&work=${enc(work)}")
    val arr = o.optJSONArray("tracks") ?: return emptyList()
    val out = mutableListOf<Api.AudioTrack>()
    for (i in 0 until arr.length()) {
        val t = arr.getJSONObject(i)
        val lrc = mutableListOf<Pair<Long, String>>()
        val larr = t.optJSONArray("lrc")
        for (j in 0 until (larr?.length() ?: 0)) {
            val pair = larr!!.getJSONArray(j)
            lrc.add(pair.optLong(0) to pair.optString(1))
        }
        out.add(Api.AudioTrack(t.optString("name"), t.optLong("size"), lrc))
    }
    return out
}


/** 音频轨流式 URL（n = 轨道序号；播放器需带 X-Token 头）。 */
internal fun Api.audioUrl(group: String, work: String, n: Int): String =
    url("/audio?group=${enc(group)}&work=${enc(work)}&n=$n")


/** 最近阅读的作品（继续阅读横排）。 */
internal fun Api.readingResume(limit: Int = 12): List<Api.ResumeItem> {
    val o = getJson("/api/reading/resume?limit=$limit")
    val arr = o.optJSONArray("items") ?: return emptyList()
    val out = mutableListOf<Api.ResumeItem>()
    for (i in 0 until arr.length()) {
        val r = arr.getJSONObject(i)
        out.add(Api.ResumeItem(
            r.optString("key"), r.optInt("last_page"), r.optBoolean("finished"),
            r.optLong("last_read_at"),
            if (r.isNull("group")) null else r.optString("group"),
            if (r.isNull("work")) null else r.optString("work"),
            if (r.isNull("pages")) null else r.optInt("pages"),
            r.optString("circle"),
            r.optJSONArray("personals")?.let { arr ->
                (0 until arr.length()).map { arr.optString(it) }.filter { it.isNotEmpty() }
            } ?: emptyList(),
            r.optJSONArray("originals")?.let { arr ->
                (0 until arr.length()).map { arr.optString(it) }.filter { it.isNotEmpty() }
            } ?: emptyList()))
    }
    return out
}


internal fun Api.statsOverview(): Api.StatsOverview {
    val o = getJson("/api/stats/overview")
    fun pairs(key: String, k: String, v: String): MutableList<Pair<String, Int>> {
        val arr = o.optJSONArray(key) ?: return mutableListOf()
        val out = mutableListOf<Pair<String, Int>>()
        for (i in 0 until arr.length()) {
            val d = arr.getJSONObject(i)
            out.add(d.optString(k) to d.optInt(v))
        }
        return out
    }
    return Api.StatsOverview(
        o.optInt("works"), o.optLong("pages"), o.optInt("finished"), o.optInt("started"),
        o.optInt("favorites"), o.optInt("rated"), o.optInt("circles"),
        pairs("by_day", "day", "count"), pairs("top_authors", "name", "count"))
}


/** 收件箱快照（提案式入库；服务端在访问时自动扫描 _app/_inbox 登记）。 */
internal fun Api.inboxList(): Api.InboxSnapshot {
    val o = getJson("/api/inbox/list")
    val arr = o.optJSONArray("items") ?: return Api.InboxSnapshot(emptyList(), emptyList())
    val out = mutableListOf<Api.InboxItem>()
    for (i in 0 until arr.length()) {
        val it = arr.getJSONObject(i)
        val p = it.optJSONObject("proposal")
        out.add(Api.InboxItem(
            it.optInt("id"), it.optString("name"), it.optLong("size"),
            it.optString("state", "pending"), it.optBoolean("exists"),
            p?.optString("kind") ?: "", p?.optString("circle") ?: "", p?.optString("bare") ?: "",
            p?.optString("new_name") ?: "", p?.optString("confidence") ?: "-",
            p?.optJSONObject("dup")?.optString("name")))
    }
    val parts = mutableListOf<Api.InboxPart>()
    val pa = o.optJSONArray("parts")
    for (i in 0 until (pa?.length() ?: 0)) {
        val p = pa!!.getJSONObject(i)
        parts.add(Api.InboxPart(p.optString("name"), p.optLong("size"), p.optDouble("age_h")))
    }
    return Api.InboxSnapshot(out, parts)
}


/** 确认入库。返回 (ok, message)——内容重复拦截以 400 + message 返回，不算异常。 */
internal fun Api.inboxConfirm(id: Int, circle: String?, force: Boolean): Pair<Boolean, String> {
    val body = JSONObject().put("id", id).put("force", force)
    if (circle != null) body.put("circle", circle)
    val (code, obj) = postJsonRaw("/api/inbox/confirm", body)
    return (code in 200..299) to obj.optString("message", "")
}


internal fun Api.inboxDelete(id: Int): String =
    postJson("/api/inbox/delete", JSONObject().put("id", id)).optString("message", AppI18n.s("已删除"))


/** 清掉 _inbox 里下载中断的半成品（.part/.part.src）——它们不是作品，清了爬虫才会重新下载。 */
internal fun Api.inboxPurgeParts(): String =
    postJson("/api/inbox/purge-parts", JSONObject()).optString("message", AppI18n.s("已清理"))


internal fun Api.inboxConfirmAll(): String =
    postJson("/api/inbox/confirm-all", JSONObject()).optString("message", AppI18n.s("完成"))


/** 画师档案：跨社团作品（按入库时间倒序）+ 别名 + 合作社团聚合 + 关注状态 + 封面。 */
internal fun Api.artistPage(name: String): Api.ArtistPage {
    val o = getJson("/api/artist/${encPath(name)}")
    val carr = o.optJSONArray("circles")
    val circles = mutableListOf<Pair<String, Int>>()
    for (i in 0 until (carr?.length() ?: 0)) {
        val c = carr!!.getJSONObject(i)
        circles.add(c.optString("name") to c.optInt("count"))
    }
    val warr = o.optJSONArray("works")
    val works = mutableListOf<Api.ArtistWork>()
    for (i in 0 until (warr?.length() ?: 0)) {
        val w = warr!!.getJSONObject(i)
        works.add(Api.ArtistWork(w.optString("key"), w.optString("group"), w.optString("work"),
            w.optInt("pages"), w.optLong("added_at"), w.optString("circle"),
            w.optJSONArray("personals")?.let { arr ->
                (0 until arr.length()).map { arr.optString(it) }.filter { it.isNotEmpty() }
            } ?: emptyList(), w.optLong("mtime", 0L),
            w.optJSONArray("originals")?.let { arr ->
                (0 until arr.length()).map { arr.optString(it) }.filter { it.isNotEmpty() }
            } ?: emptyList(), w.optLong("size", 0L)))
    }
    val aarr = o.optJSONArray("aliases")
    val mt = o.optLong("cover_mtime", 0L)
    val coverGroup = if (o.isNull("cover_group")) null else o.optString("cover_group")
    val coverWork = if (o.isNull("cover_work")) null else o.optString("cover_work")
    return Api.ArtistPage(o.optString("author"), o.optBoolean("is_following"),
        (0 until (aarr?.length() ?: 0)).map { aarr!!.optString(it) }.filter { it.isNotEmpty() },
        circles, works, coverGroup, coverWork, mt,
        if (mt > 0) "$mt-${o.optInt("cover_pages", 0)}" else "")
}


/** 全部画师（跨社团去重，按作品数降序）——首页「全部画师」分区数据源。
 *  cover_* = 该画师体积最大作品的首页（作分区封面）；followed = 是否已喜爱。 */
internal fun Api.artists(): List<Api.ArtistItem> {
    val o = getJson("/api/artists")
    val arr = o.optJSONArray("artists") ?: return emptyList()
    val out = mutableListOf<Api.ArtistItem>()
    for (i in 0 until arr.length()) {
        val a = arr.getJSONObject(i)
        val mt = a.optLong("cover_mtime", 0L)
        out.add(Api.ArtistItem(a.optString("name"), a.optInt("works"), a.optLong("latest"),
            if (a.isNull("cover_group")) null else a.optString("cover_group"),
            if (a.isNull("cover_work")) null else a.optString("cover_work"),
            if (mt > 0) "$mt-${a.optInt("cover_pages", 0)}" else "",
            a.optBoolean("followed")))
    }
    return out
}


/** 全部原作分区（type=original 去重，按作品数降序），附最大作品封面。 */
internal fun Api.originals(): List<Api.OriginalItem> {
    val o = getJson("/api/originals")
    val arr = o.optJSONArray("originals") ?: return emptyList()
    val out = mutableListOf<Api.OriginalItem>()
    for (i in 0 until arr.length()) {
        val a = arr.getJSONObject(i)
        val mt = a.optLong("cover_mtime", 0L)
        out.add(Api.OriginalItem(a.optString("name"), a.optInt("works"), a.optLong("latest"),
            if (a.isNull("cover_group")) null else a.optString("cover_group"),
            if (a.isNull("cover_work")) null else a.optString("cover_work"),
            if (mt > 0) "$mt-${a.optInt("cover_pages", 0)}" else ""))
    }
    return out
}


// ---------- 3.6.19「添加原作」：词条 → 预览命中 → 落库成新分区 ----------

/** 预览：词条子串匹配命中的作品（只读，不落库）。
 * 3.6.20 #25：附带宽松匹配的既有分区——添加前明示"将并入该分区"，
 * 杜绝「输入 Fate Grand Order 被静默跳进 FateGrand Order」的困惑。 */
internal fun Api.originalsSearch(term: String): Api.OriginalSearch {
    val o = getJson("/api/originals/search?term=${enc(term)}")
    val similar = mutableListOf<Api.SimilarZone>()
    val arr = o.optJSONArray("similar")
    val n = arr?.length() ?: 0
    for (i in 0 until n) {
        val z = arr!!.getJSONObject(i)
        similar.add(Api.SimilarZone(z.optString("name"), z.optInt("works")))
    }
    return Api.OriginalSearch(parseHits(o.optJSONArray("works")), similar)
}


/** 确认添加：返回 JSON（term/canon/hits/added）。canon = 词条库规范名
 * （变体撞内置名单时归一，zone 名以它为准）。empty=true 仅创建空分区（3.6.36 #34）。 */
internal fun Api.originalsAdd(term: String, empty: Boolean = false): JSONObject =
    postJson("/api/originals/add", JSONObject().put("term", term).put("empty", empty))


/** 分区内手动添加作品（3.6.36 #33）：把指定作品写进该原作分区。
 *  keys 形如 "社团/作品名"（与 _find_work_by_key 同规则）。 */
internal fun Api.originalsAddWorks(zone: String, keys: List<String>): JSONObject =
    postJson("/api/originals/add-works", JSONObject()
        .put("zone", zone)
        .put("keys", org.json.JSONArray(keys)))


/** 移除某原作分区（标签 + 词条库同步删）。 */
internal fun Api.originalsRemove(term: String): JSONObject =
    postJson("/api/originals/remove", JSONObject().put("term", term))


/** 原作分区改名/合并（3.6.21）：原作名不在文件名里，只搬 DB 标签 + config 词条库，
 *  零文件操作（作品位置/进度/收藏不受影响）。新名走宽松归一时自动并入既有分区。
 *  keepAlias=true 顺带把旧名登记为原作别名（旧写法不再单列分区）。 */
internal fun Api.originalsRename(from: String, to: String, keepAlias: Boolean = false): JSONObject =
    postJson("/api/originals/rename",
        JSONObject().put("from", from).put("to", to).put("keep_alias", keepAlias))


private fun Api.parseHits(arr: org.json.JSONArray?): List<Api.WorkHit> {
    val out = mutableListOf<Api.WorkHit>()
    val n = arr?.length() ?: 0
    for (i in 0 until n) {
        val it0 = arr!!.getJSONObject(i)
        val w = parseWork(it0.getJSONObject("work"))
        rememberVer(it0.getString("group"), w.name, w.ver)
        out.add(Api.WorkHit(it0.getString("group"), w))
    }
    return out
}


/** 喜爱清单（新作品多在前），附最大作品封面。 */
internal fun Api.follows(): List<Api.FollowItem> {
    val o = getJson("/api/follows")
    val arr = o.optJSONArray("follows") ?: return emptyList()
    val out = mutableListOf<Api.FollowItem>()
    for (i in 0 until arr.length()) {
        val f = arr.getJSONObject(i)
        val mt = f.optLong("cover_mtime", 0L)
        out.add(Api.FollowItem(f.optString("author"), f.optInt("works"), f.optInt("new"),
            if (f.isNull("cover_group")) null else f.optString("cover_group"),
            if (f.isNull("cover_work")) null else f.optString("cover_work"),
            if (mt > 0) "$mt-${f.optInt("cover_pages", 0)}" else ""))
    }
    return out
}


internal fun Api.follow(author: String): String =
    postJson("/api/follow", JSONObject().put("author", author)).optString("message", AppI18n.s("已喜爱"))


internal fun Api.unfollow(author: String): String =
    postJson("/api/follow/unfollow", JSONObject().put("author", author))
        .optString("message", AppI18n.s("已取消喜爱"))


// ---------- 3.5.0 阅读角标（网页消费端对称：已读✓ / 读n / 新入库） ----------

/** 盖「最后访问时间」戳，返回上一次的基线（新作品 = added_at > 基线；首轮≈0 不标亮全库）。 */
internal fun Api.markSeen(): Double {
    val o = postJson("/api/reading/mark-seen", JSONObject())
    return o.optDouble("previous", 0.0)
}


internal fun Api.readingSummary(since: Double): Api.ReadingSummary {
    val o = getJson("/api/reading/summary?since=${since.toLong()}")
    val st = mutableMapOf<String, Pair<Int, Boolean>>()
    val so = o.optJSONObject("states")
    if (so != null) for (k in so.keys()) {
        val v = so.optJSONObject(k) ?: continue
        st[k] = v.optInt("p") to v.optBoolean("f")
    }
    val nk = mutableSetOf<String>()
    val na = o.optJSONArray("new_keys")
    for (i in 0 until (na?.length() ?: 0)) nk.add(na!!.optString(i))
    return Api.ReadingSummary(st, nk)
}
