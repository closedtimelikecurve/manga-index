package com.biblioteca.reader

import android.content.Context
import android.net.Uri
import androidx.compose.foundation.background
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MultipartBody
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody
import okio.BufferedSink
import okio.source

/* ================================================================
   导入族（3.7.43 从 Features.kt 拆出）：
   ImportScreen（SAF 多选 → 分块上传 → 删源确认）+ UiUpload（上传实现）。
   ================================================================ */

@Composable
fun ImportScreen(onBack: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var uris by remember { mutableStateOf<List<android.net.Uri>>(emptyList()) }
    var uploading by remember { mutableStateOf(false) }
    var resultText by remember { mutableStateOf("") }
    var importedOk by remember { mutableStateOf(false) }
    var lastUploaded by remember { mutableStateOf<List<android.net.Uri>>(emptyList()) }
    var askDelete by remember { mutableStateOf(false) }

    val picker = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenMultipleDocuments()) { picked ->
        if (picked.isNotEmpty()) { uris = picked; resultText = ""; importedOk = false }
    }

    BackHandlerOn(onBack)
    Column(Modifier.fillMaxSize()) {
        TopBar("📥 " + AppI18n.s("导入文件"), onBack)
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp)) {
            Text(AppI18n.s("选择本机文件（可多选）上传入库：压缩包每包一部作品；\n识别出社团/个人的自动建档，待定词条按词条建档，无法识别进「收件箱」。"),
                color = MUTED, fontSize = 12.sp, modifier = Modifier.padding(bottom = 12.dp))
            Button(onClick = { picker.launch(arrayOf("*/*")) },
                   modifier = Modifier.fillMaxWidth()) { Text(AppI18n.s("📁 选择文件")) }
            if (uris.isNotEmpty()) {
                Text(AppI18n.sf("已选 %1 个文件", uris.size), color = TXT, fontSize = 13.sp,
                     modifier = Modifier.padding(top = 12.dp))
                Button(onClick = { startImport(scope, ctx, uris, { uploading = it },
                        { resultText = it }, { importedOk = it }, { lastUploaded = it }, { askDelete = it }) },
                    enabled = !uploading, modifier = Modifier.fillMaxWidth().padding(top = 8.dp)) {
                    Text(if (uploading) AppI18n.s("上传中…") else "⬆ " + AppI18n.s("上传入库"))
                }
            }
            if (resultText.isNotEmpty()) {
                Text(resultText, color = if (importedOk) TXT else ERR, fontSize = 12.sp,
                     modifier = Modifier.padding(top = 12.dp))
            }
        }
    }
    if (askDelete) {
        ImportDeleteDialog(ctx, scope, lastUploaded,
            onDismiss = { askDelete = false },
            onDeleted = { ok ->
                askDelete = false
                resultText += "\n\n" + AppI18n.sf("源文件：已删除 %1 个", ok)
            })
    }
}

/** 上传结果文案（3.7.43 提为纯函数）：总数 + 每文件状态/消息。 */
private fun formatImportResult(resp: org.json.JSONObject): String {
    val sb = StringBuilder(AppI18n.sf("导入结果：%1 个成功", resp.optInt("imported")) + "\n")
    val arr = resp.optJSONArray("results")
    for (i in 0 until (arr?.length() ?: 0)) {
        val r0 = arr!!.getJSONObject(i)
        sb.append("${r0.optString("file")} → ${r0.optString("status")}")
        if (r0.has("message")) sb.append("（${r0.optString("message")}）")
        sb.append('\n')
    }
    return sb.toString().trimEnd()
}

/** 执行导入上传（3.7.43 提为模块级）：分块上传 → 结果/异常/收尾分别回调。 */
private fun runImport(scope: CoroutineScope, ctx: Context, uris: List<android.net.Uri>,
                      onProgress: (Int, Int) -> Unit,
                      onResult: (org.json.JSONObject) -> Unit,
                      onError: (String) -> Unit, onFinally: () -> Unit) {
    scope.launch {
        try {
            val resp = withContext(Dispatchers.IO) {
                UiUpload.uploadChunked(ctx, uris) { done, total -> onProgress(done, total) }
            }
            onResult(resp)
        } catch (e: Exception) {
            onError(e.message ?: e.toString())
        }
        onFinally()
    }
}

/** 删源确认弹窗（3.7.43 从 ImportScreen 拆出）：逐文件 DocumentsContract 删除。 */
@Composable
private fun ImportDeleteDialog(ctx: Context, scope: CoroutineScope,
                               lastUploaded: List<android.net.Uri>,
                               onDismiss: () -> Unit, onDeleted: (Int) -> Unit) {
    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(AppI18n.s("删除源文件？")) },
        text = { Text(AppI18n.sf("已成功导入 %1 个文件。\n是否删除手机上的源文件？（不可恢复）", lastUploaded.size)) },
        confirmButton = {
            TextButton(onClick = {
                onDismiss()
                scope.launch {
                    var ok = 0
                    for (u in lastUploaded) {
                        try {
                            if (android.provider.DocumentsContract.deleteDocument(ctx.contentResolver, u)) ok++
                        } catch (e: Exception) { }
                    }
                    onDeleted(ok)
                }
            }) { Text(AppI18n.s("删除"), color = ERR) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(AppI18n.s("保留源文件")) } }
    )
}

/** 触发导入上传（3.7.48 从 ImportScreen 抽出，集中映射进度/结果/异常到界面状态）。 */
private fun startImport(scope: CoroutineScope, ctx: Context, uris: List<Uri>,
                        onUploading: (Boolean) -> Unit, onResultText: (String) -> Unit,
                        onImportedOk: (Boolean) -> Unit, onLastUploaded: (List<Uri>) -> Unit,
                        onAskDelete: (Boolean) -> Unit) {
    onUploading(true); onResultText(AppI18n.s("上传中…"))
    runImport(scope, ctx, uris,
        onProgress = { d, t -> onResultText(AppI18n.sf("上传中… %1 / %2 块", d, t)) },
        onResult = { resp ->
            onImportedOk(resp.optBoolean("ok"))
            onLastUploaded(uris.toList())
            onResultText(formatImportResult(resp))
            if (resp.optBoolean("ok") && uris.isNotEmpty()) onAskDelete(true)
        },
        onError = { onResultText(AppI18n.sf("上传失败：%1", it)); onImportedOk(false) },
        onFinally = { onUploading(false) })
}

/** SAF 多选上传的请求体构建（流式读取，不整包进内存） */
object UiUpload {
    fun buildBody(ctx: android.content.Context, uris: List<android.net.Uri>): MultipartBody {
        val mp = MultipartBody.Builder().setType(MultipartBody.FORM)
        for ((i, uri) in uris.withIndex()) {
            val name = queryName(ctx, uri) ?: "file_${i + 1}"
            val size = querySize(ctx, uri) ?: -1L
            val resolver = ctx.contentResolver
            val body = object : RequestBody() {
                override fun contentType() = "application/octet-stream".toMediaType()
                override fun contentLength() = size
                override fun writeTo(sink: BufferedSink) {
                    resolver.openInputStream(uri)?.use { ins ->
                        sink.writeAll(ins.source())
                    } ?: throw java.io.IOException(AppI18n.sf("无法读取：%1", name))
                }
            }
            mp.addFormDataPart("files", name, body)
            mp.addFormDataPart("paths", name)
        }
        return mp.build()
    }

    /**
     * 分块上传（救不可靠中继链路）：每文件按 8MB 切块顺序上传,单块失败重试 3 次
     * （每次新连接,失败只损失当前块）,全部完成后 commit 拼接+导入。
     * onProgress(done, total) 用于界面进度显示。
     */
    suspend fun uploadChunked(
        ctx: android.content.Context,
        uris: List<android.net.Uri>,
        onProgress: (Int, Int) -> Unit
    ): org.json.JSONObject {
        val uploadId = java.util.UUID.randomUUID().toString().replace("-", "").take(32)
        val chunkSize = 8 * 1024 * 1024
        val filesMeta = mutableListOf<org.json.JSONObject>()
        val totalChunks = uris.sumOf { u ->
            val sz = querySize(ctx, u) ?: -1L
            if (sz <= 0) 1L else (sz + chunkSize - 1) / chunkSize
        }.toInt()
        var done = 0
        for ((fid, uri) in uris.withIndex()) {
            filesMeta.add(uploadOneFile(ctx, uri, uploadId, fid, chunkSize) {
                done++
                onProgress(done, totalChunks)
            })
        }
        return Api.uploadCommit(uploadId, filesMeta)
    }

    /**
     * 单文件分块上传（3.7.43 从 uploadChunked 拆出；3.7.46 再把"单块发送 + 重试"
     * 提成 [sendOneChunk]，本函数只管切块与收尾）。流跨块复用，失败重开流跳到
     * 本块偏移重试（最多 3 次）；返回该文件的 meta JSON。
     */
    private suspend fun uploadOneFile(
        ctx: android.content.Context, uri: android.net.Uri,
        uploadId: String, fid: Int, chunkSize: Int,
        onChunkDone: () -> Unit
    ): org.json.JSONObject {
        val name = queryName(ctx, uri) ?: "file_${fid + 1}"
        val size = querySize(ctx, uri) ?: -1L
        val chunks = if (size <= 0) 1 else ((size + chunkSize - 1) / chunkSize).toInt()
        var stream: java.io.InputStream? = null
        for (idx in 0 until chunks) {
            val len = if (size > 0) {
                minOf(chunkSize.toLong(), size - idx.toLong() * chunkSize).toInt()
            } else chunkSize
            stream = sendOneChunk(ctx, uri, uploadId, fid, idx, chunkSize,
                ByteArray(len), name, stream, chunks)
            onChunkDone()
        }
        try { stream?.close() } catch (_: Exception) {}
        return org.json.JSONObject()
            .put("name", name)
            .put("rel", name)
            .put("chunks", chunks)
    }

    /**
     * 发送单块：失败就关流重开、跳回本块偏移重试，最多 3 次；返回（可能新开的）流。
     * 3.7.46 从 uploadOneFile 拆出——原函数 53 行 / cc 17，重试逻辑是复杂度的全部来源。
     */
    private suspend fun sendOneChunk(
        ctx: android.content.Context, uri: android.net.Uri,
        uploadId: String, fid: Int, idx: Int, chunkSize: Int,
        buf: ByteArray, name: String, streamIn: java.io.InputStream?, chunks: Int
    ): java.io.InputStream {
        var stream = streamIn
        var skipLeft = 0L                 // 仅重试后需要重新跳偏移
        var attempt = 0
        while (true) {
            try {
                if (stream == null) stream = openAt(ctx, uri, name, skipLeft)
                readFully(stream, buf, name)
                Api.uploadChunk(uploadId, fid, idx, buf)
                return stream
            } catch (e: Exception) {
                attempt++
                try { stream?.close() } catch (_: Exception) {}
                stream = null
                if (attempt >= 3) throw java.io.IOException(
                    AppI18n.sf("%1 第 %2/%3 块上传失败：%4", name, idx + 1, chunks, e.message))
                kotlinx.coroutines.delay(1000L * attempt)
                skipLeft = idx.toLong() * chunkSize   // 重开流后重新跳到本块偏移
            }
        }
    }

    /** 打开流并跳到指定偏移（skip=0 表示从开头读）。 */
    private fun openAt(ctx: android.content.Context, uri: android.net.Uri,
                       name: String, skip: Long): java.io.InputStream {
        val s = ctx.contentResolver.openInputStream(uri)
            ?: throw java.io.IOException(AppI18n.sf("无法读取：%1", name))
        var left = skip
        while (left > 0) {
            val n = s.skip(left)
            if (n <= 0) throw java.io.IOException(AppI18n.sf("定位失败：%1", name))
            left -= n
        }
        return s
    }

    /** 把缓冲区读满（流比预期短即视为损坏）。 */
    private fun readFully(s: java.io.InputStream, buf: ByteArray, name: String) {
        var off = 0
        while (off < buf.size) {
            val n = s.read(buf, off, buf.size - off)
            if (n < 0) throw java.io.IOException(AppI18n.sf("文件比预期短：%1", name))
            off += n
        }
    }

    private fun queryName(ctx: android.content.Context, uri: android.net.Uri): String? {
        ctx.contentResolver.query(uri, null, null, null, null)?.use { c ->
            val idx = c.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
            if (idx >= 0 && c.moveToFirst()) return c.getString(idx)
        }
        return uri.lastPathSegment
    }

    private fun querySize(ctx: android.content.Context, uri: android.net.Uri): Long? {
        ctx.contentResolver.query(uri, null, null, null, null)?.use { c ->
            val idx = c.getColumnIndex(android.provider.OpenableColumns.SIZE)
            if (idx >= 0 && c.moveToFirst()) return c.getLong(idx)
        }
        return null
    }
}
