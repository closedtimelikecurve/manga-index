package com.biblioteca.reader

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

/* 主题域接口（3.7.74，§4.6 双端对齐）：图库列表 / 入库 / 选用 / 删除 / 恢复默认。
   与网页 static/js/theme.js 消费的是同一组端点（面板 3.6.122 起）：
   **图库是一份共用的**（两端看到同一批图），**选用按端各记一份**（电脑与手机可选不同图）。

   本端槽位标识固定 "app"：面板按 `client=app` 读写 `theme_active_app.txt` / `theme_bg_app.*`。 */

/** 本端槽位标识（与网页的 "web" 对称；面板缺省值也是 app，旧版 APK 因此天然落在这里）。 */
internal const val CLIENT_APP = "app"

/** 图库里的一张图。[mtime] 是服务端文件时间（秒），用于按新→旧排序与破缓存。
 *  [builtin] 内置图（默认图 / 基础图，不可删除）；[title] 是它的 i18n key（用户图为空）。 */
data class ThemeGalleryItem(val name: String, val size: Long, val mtime: Double,
                            val builtin: Boolean = false, val title: String = "")

/** 图库列表 + 本端当前启用的文件名（空串 = 用默认图）+ 全局横幅槽位启用名（3.7.94）。 */
internal fun Api.themeGallery(): Triple<List<ThemeGalleryItem>, String, String> {
    val o = getJson("/api/theme/gallery?client=" + CLIENT_APP)
    val arr = o.optJSONArray("items")
    val items = (0 until (arr?.length() ?: 0)).map { i ->
        val it = arr!!.getJSONObject(i)
        ThemeGalleryItem(it.optString("name"), it.optLong("size"), it.optDouble("mtime", 0.0),
            it.optBoolean("builtin", false), it.optString("title"))
    }.filter { it.name.isNotEmpty() }
    return Triple(items, o.optString("active"), o.optString("heroActive"))
}

/** 把一张图加进图库（原始字节；服务端按魔数校验 jpg/png/webp、≤8MB）。返回文件名。 */
internal fun Api.themeGalleryAdd(bytes: ByteArray, mime: String): String {
    val media = mime.ifEmpty { "application/octet-stream" }.toMediaType()
    val resp = http.newCall(req("/api/theme/gallery")
        .post(bytes.toRequestBody(media)).build()).execute()
    resp.use {
        val text = it.body?.string() ?: ""
        if (it.code == 401) throw AuthException()
        val obj = try { JSONObject(text) } catch (_: Exception) { JSONObject() }
        if (!it.isSuccessful) throw ApiException(obj.optString("message").ifEmpty { "HTTP ${it.code}" })
        return obj.optString("name")
    }
}

/** 从图库选用一张：只切**本端**槽位（另一端的选用不受影响）。 */
internal fun Api.themeBgSelect(name: String) {
    postJson("/api/theme/bg?client=" + CLIENT_APP,
        JSONObject().put("name", name).put("client", CLIENT_APP))
}

/** 选用一张为首页横幅（3.7.94）：hero 是全局单份，改的是网页首页的横幅。 */
internal fun Api.themeHeroSelect(name: String) {
    postJson("/api/theme/hero", JSONObject().put("name", name))
}

/** 恢复默认背景：只清本端的"当前背景副本"，图库里的图不动。 */
internal fun Api.themeBgReset() {
    val resp = http.newCall(req("/api/theme/bg?client=" + CLIENT_APP).delete().build()).execute()
    resp.use {
        if (it.code == 401) throw AuthException()
        if (!it.isSuccessful) throw ApiException("HTTP ${it.code}")
    }
}

/** 删除图库中的一张（若删的正是某端启用的那张，服务端会让那一端恢复默认）。
 *  内置图服务端一律 400「内置图片不可删除」。 */
internal fun Api.themeGalleryDelete(name: String) {
    val resp = http.newCall(req("/api/theme/gallery/" + encPath(name)).delete().build()).execute()
    resp.use {
        if (it.code == 401) throw AuthException()
        if (!it.isSuccessful) throw ApiException("HTTP ${it.code}")
    }
}

/** 图库缩略图 URL（图片端点公开 + token 查询串，与 coverUrl 同惯例）。 */
internal fun Api.themeGalleryImageUrl(name: String, ver: Double): String =
    url("/api/theme/gallery/" + encPath(name) + "?v=" + ver.toLong() + tokenQuery())

/** 公开图片端点的 token 查询串（无 token 时为空串）。 */
private fun Api.tokenQuery(): String =
    if (token.isEmpty()) "" else "&token=" + enc(token)
