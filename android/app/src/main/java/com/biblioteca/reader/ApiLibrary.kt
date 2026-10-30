package com.biblioteca.reader

import org.json.JSONObject
import java.io.File

/* 文库查询族（3.7.43 从 Api.kt 拆出）：library/circle/pages/search/tagWorks + 删除/封面。 */


/**
 * 社团排序（与服务端 sort_groups() 语义一致，本地排序、切换即时生效）：
 *   mode = "updated"（最近入库新作品，默认）/ "created"（档案创建时间）/ "count"（作品数量）；
 *   3.6.166：**"size" 档已删除**（用户要求大小排序只在分区内部按作品排），传进来按 updated 处理。
 *   asc = false → **由新到旧 / 由多到少 / 由大到小**（默认降序）；asc = true → 由旧到新 / 由少到多 / 由小到大。
 * 同值时按名称升序补位，列表不会在刷新之间跳动。
 *
 * 3.6.151：**删掉 touched（最近更新）档**——它与 updated 只差"洗版算不算入库"，
 * 两档并排让人分不清哪个才是"我刚下载的排在前面"。存量偏好里存着 touched 的，
 * 调用方在 AppState 里已回落成 updated。
 */
internal fun Api.sortCircles(list: List<Api.Group>, mode: String, asc: Boolean): List<Api.Group> {
    // 3.6.154：时间档取整到整秒——首扫同一批新社团的「最近入库」只差几微秒，
    // 不取整的话下面"同值按名字"的补位永远不生效，顺序会随扫描顺序抖。
    val key = { g: Api.Group ->
        when (mode) {
            "created" -> Math.round(g.createdAt).toDouble()
            "count" -> g.workCount.toDouble()
            else -> Math.round(g.updatedAt).toDouble()      // 含已删除的 "size"
        }
    }
    val cmp = Comparator<Api.Group> { a, b ->
        val ka = key(a)
        val kb = key(b)
        var r = when {
            ka < kb -> -1
            ka > kb -> 1
            else -> 0
        }
        // 3.6.152：`ka < kb → -1` 本身就已经是**升序**，所以只有「要降序」时才取反。
        // 旧代码写成 `if (asc) r = -r`，等于默认升序、切换后降序——与排序条文案整好相反
        // （用户报障：「逆序键的文本和实际排序全部搞反了」）。
        if (!asc) r = -r
        if (r != 0) r else a.name.compareTo(b.name)
    }
    return list.sortedWith(cmp)
}


internal fun Api.parseWork(o: JSONObject): Api.Work = Api.Work(
    o.getString("name"), o.optInt("pages"), o.optBoolean("hasCover"),
    o.optString("personal"), o.optString("bare"), o.optString("ver"),
    o.optJSONArray("personals")?.let { arr ->
        (0 until arr.length()).map { arr.optString(it) }.filter { it.isNotEmpty() }
    } ?: emptyList(),
    o.optString("circle"),
    o.optJSONArray("tags")?.let { arr ->
        (0 until arr.length()).map {
            val t = arr.getJSONObject(it)
            t.optString("type") to t.optString("name")
        }.filter { it.first.isNotEmpty() && it.second.isNotEmpty() }
    } ?: emptyList(),
    o.optDouble("mtime", 0.0),         // 3.7.40：旧排序键，3.7.69 起仅作 addedAt 兜底
    o.optDouble("added_at", 0.0),      // 3.7.69：首次入库时间，分区内"新→旧"排序键
    o.optLong("size", 0L)              // 3.6.151：文件大小，按大小排序查重用
)


private fun Api.parseGroups(arr: org.json.JSONArray?): List<Api.Group> {
    val out = mutableListOf<Api.Group>()
    val a = arr ?: return out
    for (i in 0 until a.length()) {
        val g = a.getJSONObject(i)
        val grp = Api.Group(
            g.getString("name"), g.optInt("workCount"), g.optBoolean("hasCover"),
            g.optString("coverWork"), g.optLong("coverMtime"), g.optString("coverVer"),
            g.optDouble("createdAt", 0.0),
            g.optDouble("updatedAt", g.optLong("coverMtime").toDouble()),
            g.optLong("totalBytes", 0L),    // 3.6.151：社团占用空间（社团排序已不用，留作兼容）
            g.optString("coverGroup").ifEmpty { g.getString("name") }   // 3.6.166：封面作品所在社团
        )
        // 社团封面图的缓存键：登记在 (**封面作品所在社团**, 封面作品) 上——
        // 与 coverUrl 的入参一致，否则跨社团封面查不到版本号，换封面后缓存不失效。
        rememberVer(grp.coverGroup.ifEmpty { grp.name }, grp.coverWork, grp.coverVer)
        out.add(grp)
    }
    return out
}


internal fun Api.library(refresh: Boolean = false): Api.Library {
    val o = getJson("/api/library" + if (refresh) "?refresh=1" else "")
    if (o.optString("status") == "scanning") throw ApiException(AppI18n.s("服务正在扫描文库，请稍后刷新"))
    val recs = mutableListOf<Api.Rec>()
    val rarr = o.optJSONArray("recommendations")
    for (i in 0 until (rarr?.length() ?: 0)) {
        val r = rarr.getJSONObject(i)
        recs.add(Api.Rec(r.getString("group"), r.getString("work"), r.optInt("pages")))
    }
    val tags = mutableMapOf<String, List<Api.TagItem>>()
    val tobj = o.optJSONObject("tags")
    if (tobj != null) {
        for (key in tobj.keys()) {
            val tarr = tobj.optJSONArray(key) ?: continue
            val items = mutableListOf<Api.TagItem>()
            for (i in 0 until tarr.length()) {
                val t = tarr.getJSONObject(i)
                items.add(Api.TagItem(t.getString("name"), t.optInt("count")))
            }
            tags[key] = items
        }
    }
    return Api.Library(parseGroups(o.optJSONArray("groups")), recs, tags)
}


internal fun Api.circle(name: String, refresh: Boolean = false): Triple<List<Api.Work>, List<Api.TagItem>, Api.CircleCover> {
    val o = getJson("/api/circle/${encPath(name)}" + if (refresh) "?refresh=1" else "")
    val arr = o.getJSONArray("works")
    val out = mutableListOf<Api.Work>()
    for (i in 0 until arr.length()) {
        val w = parseWork(arr.getJSONObject(i))
        rememberVer(name, w.name, w.ver)          // 登记内容版本 → 封面/页面 URL 自动带 v=
        out.add(w)
    }
    // 3.2.1 社团内作者聚合（画师档案直达入口用）
    val authors = mutableListOf<Api.TagItem>()
    val aarr = o.optJSONArray("authors")
    for (i in 0 until (aarr?.length() ?: 0)) {
        val a = aarr!!.getJSONObject(i)
        authors.add(Api.TagItem(a.optString("name"), a.optInt("count")))
    }
    val cg = if (o.isNull("coverGroup")) null else o.optString("coverGroup")
    val cw = if (o.isNull("coverWork")) null else o.optString("coverWork")
    return Triple(out, authors, Api.CircleCover(cg, cw, o.optString("coverVer")))
}


/** 页面元信息:总页数 + 每页媒体类型(image|gif|video) + 内容版本键 + 多版本分组 */
internal fun Api.pages(group: String, work: String): Api.PagesInfo {
    val o = getJson("/api/pages?group=${enc(group)}&work=${enc(work)}" + imgParam())
    val total = o.getInt("total")
    val kinds = mutableListOf<String>()
    val arr = o.optJSONArray("kinds")
    for (i in 0 until (arr?.length() ?: 0)) kinds.add(arr?.getString(i) ?: "image")
    val ver = o.optString("ver")
    rememberVer(group, work, ver)                 // 阅读器页 URL 也带上缓存键
    val versions = mutableListOf<Pair<String, List<Int>>>()
    val varr = o.optJSONArray("versions")
    for (i in 0 until (varr?.length() ?: 0)) {
        val v = varr!!.getJSONObject(i)
        val iarr = v.optJSONArray("idx")
        val idx = (0 until (iarr?.length() ?: 0)).map { iarr!!.optInt(it) }
        versions.add(v.optString("name") to idx)
    }
    return Api.PagesInfo(total, kinds, ver, versions)
}


// ---------- v2.3 新增：搜索 / 标签检索 / 删除 / 导入 / 共享文档 / 自动更新 ----------

/** 全局搜索：返回 (命中的社团, 命中的作品[带所属社团], 命中的画师[带作品数]) */
internal fun Api.search(q: String): Triple<List<Api.Group>, List<Api.WorkHit>, List<Api.TagItem>> {
    val o = getJson("/api/search?q=${enc(q)}")
    val works = mutableListOf<Api.WorkHit>()
    val warr = o.optJSONArray("works")
    for (i in 0 until (warr?.length() ?: 0)) {
        val it0 = warr.getJSONObject(i)
        val w = parseWork(it0.getJSONObject("work"))
        rememberVer(it0.getString("group"), w.name, w.ver)   // 搜索结果封面也带缓存键
        works.add(Api.WorkHit(it0.getString("group"), w))
    }
    val authors = mutableListOf<Api.TagItem>()
    val aarr = o.optJSONArray("authors")
    for (i in 0 until (aarr?.length() ?: 0)) {
        val a = aarr.getJSONObject(i)
        authors.add(Api.TagItem(a.optString("name"), a.optInt("count"),
            if (a.isNull("cover_group")) null else a.optString("cover_group"),
            if (a.isNull("cover_work")) null else a.optString("cover_work")))
    }
    return Triple(parseGroups(o.optJSONArray("groups")), works, authors)
}


/** 标签全局检索：跨社团返回含该标签的作品 */
internal fun Api.tagWorks(type: String, tag: String): List<Api.WorkHit> {
    val o = getJson("/api/works?type=${enc(type)}&tag=${enc(tag)}")
    val out = mutableListOf<Api.WorkHit>()
    val arr = o.optJSONArray("works") ?: return out
    for (i in 0 until arr.length()) {
        val it0 = arr.getJSONObject(i)
        val w = parseWork(it0.getJSONObject("work"))
        rememberVer(it0.getString("group"), w.name, w.ver)   // 标签检索封面也带缓存键
        out.add(Api.WorkHit(it0.getString("group"), w))
    }
    return out
}


internal fun Api.deleteWork(group: String, work: String): String =
    postJson("/api/delete",
        JSONObject().put("group", group).put("work", work)).optString("message", AppI18n.s("已删除"))


internal fun Api.deleteCircle(group: String): String =
    postJson("/api/delete-circle",
        JSONObject().put("group", group)).optString("message", AppI18n.s("已删除"))


internal fun Api.dissolveCircle(group: String): String =
    postJson("/api/dissolve-circle",
        JSONObject().put("group", group)).optString("message", AppI18n.s("已解散"))


internal fun Api.deleteCover(group: String, work: String): String =
    postJson("/api/delete-cover",
        JSONObject().put("group", group).put("work", work)).optString("message", AppI18n.s("已删除首页图片"))


// 设为区域封面：所在位置决定归属（社团页 → scope=circle；画师页 → scope=artist）。
// group 用作品在该视图下的归属社团，find_work 均可命中（含交叉引用）。
internal fun Api.setCover(scope: String, name: String, group: String, work: String): String =
    postJson("/api/set-cover",
        JSONObject().put("scope", scope).put("name", name)
            .put("group", group).put("work", work)).optString("message", AppI18n.s("已设为封面"))


internal fun Api.clearCover(scope: String, name: String): String =
    postJson("/api/clear-cover",
        JSONObject().put("scope", scope).put("name", name)).optString("message", AppI18n.s("已清除封面覆盖"))
