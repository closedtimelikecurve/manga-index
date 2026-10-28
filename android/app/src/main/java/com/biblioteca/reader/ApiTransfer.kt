package com.biblioteca.reader

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.File

/* 传输族（3.7.43 从 Api.kt 拆出）：分片上传/导入/导出下载/断点续传。 */


/** 分块上传单块:原始字节 body,失败由调用方重试。每块独立连接(Connection: close)。 */
internal fun Api.uploadChunk(uploadId: String, fid: Int, idx: Int, bytes: ByteArray): JSONObject {
    val req = req("/api/upload-chunk?upload_id=$uploadId&fid=$fid&idx=$idx")
        .header("Connection", "close")
        .post(bytes.toRequestBody("application/octet-stream".toMediaType()))
        .build()
    val resp = uploadHttp.newCall(req).execute()
    resp.use {
        if (it.code == 401) throw AuthException()
        val text = it.body?.string() ?: ""
        val obj = try { JSONObject(text) } catch (_: Exception) { JSONObject() }
        if (!it.isSuccessful) throw ApiException(obj.optString("message").ifEmpty { "HTTP ${it.code}" })
        return obj
    }
}


/** 分块上传收尾:拼接+导入,返回与 /api/import 相同结构 */
internal fun Api.uploadCommit(uploadId: String, files: List<org.json.JSONObject>): JSONObject {
    val arr = org.json.JSONArray()
    for (f in files) arr.put(f)
    val body = JSONObject().put("upload_id", uploadId).put("files", arr)
    val (code, obj) = postJsonRaw("/api/upload-commit", body)
    if (code == 401) throw AuthException()
    if (code !in 200..299) throw ApiException(obj.optString("message").ifEmpty { "HTTP $code" })
    return obj
}


/** multipart 导入上传（请求体由调用方构建：安卓端 SAF 流式读取，不整包进内存） */
internal fun Api.importUpload(files: List<Triple<String, String, ByteArray>>): JSONObject {
    val mp = MultipartBody.Builder().setType(MultipartBody.FORM)
    for ((name, rel, bytes) in files) {
        mp.addFormDataPart("files", name, bytes.toRequestBody(BIN_MEDIA))
        mp.addFormDataPart("paths", rel)
    }
    val resp = http.newCall(req("/api/import").post(mp.build()).build()).execute()
    resp.use {
        val text = it.body?.string() ?: ""
        if (it.code == 401) throw AuthException()
        val obj = if (text.isNotEmpty()) {
            try { JSONObject(text) } catch (_: Exception) { JSONObject() }
        } else JSONObject()
        if (!it.isSuccessful) throw ApiException(obj.optString("message").ifEmpty { "HTTP ${it.code}" })
        return obj
    }
}


/** multipart 导入上传（请求体由调用方构建：安卓端 SAF 流式读取，不整包进内存） */
internal fun Api.importUploadBody(body: MultipartBody): JSONObject {
val resp = http.newCall(req("/api/import").post(body).build()).execute()
resp.use {
    val text = it.body?.string() ?: ""
    if (it.code == 401) throw AuthException()
    val obj = if (text.isNotEmpty()) {
        try { JSONObject(text) } catch (_: Exception) { JSONObject() }
    } else JSONObject()
    if (!it.isSuccessful) throw ApiException(obj.optString("message").ifEmpty { "HTTP ${it.code}" })
    return obj
}
}


/** 流式下载（带 token 头），用于 APK 自动更新 */
internal fun Api.downloadTo(urlPath: String, dest: File) {
    val resp = http.newCall(req(urlPath).get().build()).execute()
    resp.use {
        if (it.code == 401) throw AuthException()
        if (!it.isSuccessful) throw ApiException("HTTP ${it.code}")
        val ins = it.body?.byteStream() ?: throw ApiException(AppI18n.s("空响应"))
        dest.outputStream().use { outs -> ins.copyTo(outs) }
    }
}


/** 导出清单：下载前取元数据与大小（磁盘空间预检、更新检测基准）。 */
internal fun Api.exportManifest(group: String, work: String): Api.ExportManifest {
    val o = getJson("/api/export/manifest?group=${enc(group)}&work=${enc(work)}")
    val arr = o.optJSONArray("personals")
    val tarr = o.optJSONArray("tags")
    val tags = mutableListOf<Pair<String, String>>()
    for (i in 0 until (tarr?.length() ?: 0)) {
        val t = tarr!!.getJSONObject(i)
        tags.add(t.optString("type") to t.optString("name"))
    }
    return Api.ExportManifest(
        o.optString("name"), o.optString("group"), o.optString("work"),
        o.optString("file"), o.optLong("size"), o.optDouble("mtime", 0.0),
        o.optInt("pages"), o.optString("kind"), o.optString("circle"),
        (0 until (arr?.length() ?: 0)).map { arr!!.optString(it) }.filter { it.isNotEmpty() },
        o.optString("bare"), tags, o.optBoolean("downloadable"))
}


/** 本机路径导入第一阶段（复制入库），确认删源时拿 stashId 调 importCommit。 */
internal fun Api.importPath(sourceDir: String): Api.ImportPathResult {
    val o = postJson("/api/import-path", JSONObject().put("source_dir", sourceDir))
    val arr = o.optJSONArray("results")
    val sb = StringBuilder(AppI18n.sf("导入结果：%1 个成功\n", o.optInt("imported")))
    for (i in 0 until (arr?.length() ?: 0)) {
        val r = arr!!.getJSONObject(i)
        sb.append(r.optString("file")).append(" → ").append(r.optString("status"))
        if (r.has("message")) sb.append("（").append(r.optString("message")).append("）")
        sb.append('\n')
    }
    return Api.ImportPathResult(o.optInt("imported"), o.optInt("source_count"),
        o.optString("stash_id"), sb.toString().trimEnd())
}


/** 本机路径导入第二阶段：把 stash 里的源文件直接删除（不进回收站，不可还原）。 */
internal fun Api.importCommit(stashId: String): String =
    postJson("/api/import-commit", JSONObject().put("stash_id", stashId))
        .optString("message", AppI18n.s("已删除源文件"))


/**
 * 断点续传下载（APP 3.0 本地书架）—— 重试外壳（3.7.43 拆出，原 69 行 / cc 33）：
 *   * 先写 `<dest>.part`，成功后原子 rename 到目标 —— 中途崩溃/断链绝不留半个包冒充成品；
 *   * 每轮失败从断点继续（退避 800ms×轮次），最多 maxTries 轮；
 *   * AuthException / DownloadStoppedException（用户点「停止」）直接穿透上抛，
 *     不被当成断流重试 maxTries 轮（否则停止要好几分钟才生效）。
 * 单连接长传经 Tailscale 中继被实测证伪（CHANGELOG 2.14.1/2.14.2），这里断点续传
 * 等价于"变长分块"，每轮失败都从断点继续而不是推倒重来。
 */
internal fun Api.downloadResumable(
    urlPath: String, dest: File, maxTries: Int = 8,
    progress: (done: Long, total: Long) -> Unit = { _, _ -> },
) {
    val part = File(dest.parentFile, dest.name + ".part")
    dest.parentFile?.mkdirs()
    if (dest.exists()) dest.delete()
    var total = -1L
    var attempt = 0
    while (true) {
        attempt++
        try {
            total = downloadOnce(urlPath, part, progress)
            finalizeDownload(part, dest)
            return
        } catch (e: Exception) {
            if (e is AuthException || e is DownloadStoppedException) throw e
            if (attempt >= maxTries) {
                if (part.exists() && total > 0 && part.length() >= total) {
                    // 数据其实已齐：最后一次 rename 收尾
                    if (part.renameTo(dest)) return
                }
                throw e
            }
            try { Thread.sleep(800L * attempt) } catch (_: InterruptedException) {}
        }
    }
}

/**
 * 单轮续传尝试（3.7.43 从 downloadResumable 抽出）：Range 续传 / 服务器不支持 Range
 * 时丢弃重下 / 416 起点越界（源包变小）丢弃重下；读到 EOF 时已知总长却不完整 → 断流重试。
 * 返回已知总长（-1 = 未知）。
 */
private fun Api.downloadOnce(urlPath: String, part: File,
                             progress: (done: Long, total: Long) -> Unit): Long {
    val start = if (part.exists()) part.length() else 0L
    val rb = req(urlPath).get()
    if (start > 0) rb.header("Range", "bytes=$start-")
    val resp = http.newCall(rb.build()).execute()
    var total = -1L
    resp.use { r ->
        if (r.code == 401) throw AuthException()
        // 206 续传 / 200 服务器不支持 Range → 丢弃重下 / 416 起点越界（源包变小）→ 丢弃重下
        var truncate = start == 0L
        when {
            r.code == 206 -> total = contentRangeTotal(r)
            r.code == 200 -> {
                if (start > 0) truncate = true
                total = r.body?.contentLength() ?: -1L
            }
            r.code == 416 -> truncate = true
            else -> throw ApiException("HTTP ${r.code}")
        }
        if (truncate && part.exists()) part.delete()
        copyStream(r, part, if (truncate) 0L else part.length(), !truncate, progress, total)
        // 读到 EOF：若已知总长且不完整 → 当作断流重试
        val now = part.length()
        if (total > 0 && now < total) throw java.io.IOException(AppI18n.sf("传输中断 %1/%2", now, total))
    }
    return total
}

/** Content-Range 头里的总长（bytes=start-end/total）；缺失/不可解析给 -1。 */
private fun contentRangeTotal(r: okhttp3.Response): Long {
    val cr = r.header("Content-Range") ?: ""
    return cr.substringAfterLast('/', "").toLongOrNull() ?: -1L
}

/** 流式拷贝响应体到 .part（from = 续传起点；append=false 为截断重写）。 */
private fun copyStream(r: okhttp3.Response, part: File, from: Long, append: Boolean,
                       progress: (done: Long, total: Long) -> Unit, total: Long) {
    val ins = r.body?.byteStream() ?: throw ApiException(AppI18n.s("空响应"))
    java.io.FileOutputStream(part, append).use { outs ->
        val buf = ByteArray(64 * 1024)
        var done = from
        while (true) {
            val n = ins.read(buf)
            if (n < 0) break
            outs.write(buf, 0, n)
            done += n
            progress(done, total)
        }
    }
}

/** 收尾：.part 改名成正式文件（rename 失败退拷贝后删半成品）。 */
private fun finalizeDownload(part: File, dest: File) {
    if (!part.renameTo(dest)) {
        part.copyTo(dest, overwrite = true)
        part.delete()
    }
}
