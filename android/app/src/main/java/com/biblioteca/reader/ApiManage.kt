package com.biblioteca.reader

import org.json.JSONObject
import java.io.File

/* 管理族（3.7.43 从 Api.kt 拆出）：增补信息/改名/黑名单/备份/别名登记。 */


/** 解析当前文件名，供增补信息表单预填 */
internal fun Api.parseInfo(group: String, work: String): Api.ParseInfo {
    val o = getJson("/api/parse-info?group=${enc(group)}&work=${enc(work)}")
    return Api.ParseInfo(
        o.optString("file"),
        o.optString("base"),
        o.optBoolean("uncensored"),
        o.optString("event"),
        o.optString("circle"),
        o.optString("personal"),
        o.optString("bare"),
        o.optString("title"),
        o.optString("original"),
        o.optString("translator"),
        o.optString("other_info"),
    )
}


/**
 * 「整标题」模式：只提交一整串完整标题，服务端自动判定各部分词条 → 规范化命名
 * → 按解析出的社团归档（与导入同一套规则）。返回服务端 message（含标准化结果）。
 */
internal fun Api.supplementTitle(group: String, work: String, title: String): String =
    postJson("/api/supplement-title",
        JSONObject().put("group", group).put("work", work).put("title", title)
    ).optString("message", AppI18n.s("已归档"))


internal fun Api.libraryMeta(): Api.LibraryMeta {
    val o = getJson("/api/library/meta")
    return Api.LibraryMeta(o.optInt("rev"), o.optLong("scanned_at"), o.optBoolean("scanning"))
}


/** 提交增补信息：留空字段服务端自动沿用解析值；返回服务端 message */
internal fun Api.supplementInfo(group: String, work: String, f: Api.SupplementFields): String {
    val fields = JSONObject()
        .put("uncensored", f.uncensored)
        .put("event", f.event)
        .put("circle", f.circle)
        .put("personal", f.personal)
        .put("title", f.title)
        .put("original", f.original)
        .put("translator", f.translator)
        .put("other_info", f.otherInfo)
    return postJson("/api/supplement-info",
        JSONObject().put("group", group).put("work", work).put("fields", fields)
    ).optString("message", AppI18n.s("已保存"))
}


// 注：原「未分类一键归档」接口 /api/uncat/archive-all 已于 3.6.3 移除 ——
// 「未分类」不再是文库里的组，待整理作品收进 _app/_inbox 后由 inboxConfirmAll 统一处理。

/** 社团改名：真实档案夹目录整体重命名，返回结果文案与新名 */
internal fun Api.renameCircle(group: String, newName: String): Pair<String, String> {
    val j = postJson("/api/rename-circle",
        JSONObject().put("group", group).put("new_name", newName))
    return Pair(j.optString("message", AppI18n.s("已改名")), j.optString("new_name"))
}


/** 画师改名/合并（3.6.5）：名下全部作品的文件名作者词条与记录联动迁移，
 *  目标画师已存在时自动合并。返回结果文案。 */
internal fun Api.renameArtist(from: String, to: String): String =
    postJson("/api/artist/rename",
        JSONObject().put("from", from).put("to", to))
        .optString("message", AppI18n.s("已改名"))


/** 词条黑名单 + 豁免名单读取。返回 (builtin, custom, exempt) */
internal fun Api.blacklistGet(): Triple<List<String>, List<String>, List<String>> {
    val j = getJson("/api/blacklist")
    fun arr(key: String): List<String> {
        val a = j.optJSONArray(key) ?: return emptyList()
        return (0 until a.length()).map { a.optString(it) }.filter { it.isNotBlank() }
    }
    return Triple(arr("builtin"), arr("custom"), arr("exempt"))
}


/** 词条黑名单/豁免保存（全量替换自定义与豁免两个名单），返回结果文案 */
internal fun Api.blacklistSave(custom: List<String>, exempt: List<String>): String =
    postJson("/api/blacklist",
        JSONObject().put("custom", org.json.JSONArray(custom))
            .put("exempt", org.json.JSONArray(exempt))).optString("message", AppI18n.s("已保存"))


internal fun Api.backupList(): List<Api.BackupItem> {
    val o = getJson("/api/backup/list")
    val arr = o.optJSONArray("backups") ?: return emptyList()
    val out = mutableListOf<Api.BackupItem>()
    for (i in 0 until arr.length()) {
        val b = arr.getJSONObject(i)
        out.add(Api.BackupItem(b.optString("file"), b.optLong("at"),
            b.optLong("size"), b.optString("note")))
    }
    return out
}


/** 恢复快照（服务端恢复前自动快照当前 + 强制重扫）。 */
internal fun Api.backupRestore(file: String): String =
    postJson("/api/backup/restore", JSONObject().put("file", file))
        .optString("message", AppI18n.s("已恢复"))


/** 别名清单（alias → canonical）。kind: "author" 笔名 | "circle" 社团 | "original" 原作（3.6.19）。 */
internal fun Api.aliasList(kind: String = "author"): Map<String, String> {
    val o = getJson("/api/author-aliases?kind=$kind")
    val a = o.optJSONObject("aliases") ?: return emptyMap()
    val out = mutableMapOf<String, String>()
    for (k in a.keys()) out[k] = a.optString(k)
    return out
}


internal fun Api.aliasAdd(alias: String, canonical: String, kind: String = "author"): String =
    postJson("/api/author-aliases",
        JSONObject().put("alias", alias).put("canonical", canonical).put("kind", kind))
        .optString("message", AppI18n.s("已登记"))


internal fun Api.aliasDelete(alias: String, kind: String = "author"): String =
    postJson("/api/author-aliases/delete",
        JSONObject().put("alias", alias).put("kind", kind))
        .optString("message", AppI18n.s("已删除"))
