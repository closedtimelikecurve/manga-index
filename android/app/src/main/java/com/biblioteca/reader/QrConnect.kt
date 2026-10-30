package com.biblioteca.reader

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.MultiFormatReader
import com.google.zxing.RGBLuminanceSource
import com.google.zxing.common.HybridBinarizer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/* ================================================================
   3.7.77 扫码配对（§用户需求：新手机免输网址与 token）：
   面板展示 {i: url, t: token} 的 QR；手机端扫码后自动填入并连接。
   3.7.81 主按钮改为「打开相机」，但那版是**拍一张照片再识图**。
   3.7.83（用户需求③）改为 **CameraX 实时取景 + 逐帧识别**（见 QrScannerScreen.kt）：
   码进入取景框即自动连接，不用按快门；相册入口保留，截图仍然能扫。
   token 不手抄、不经过剪贴板。
   ================================================================ */

/** 配对二维码内容。
 *
 *  3.6.144 起码里是 `{"i":"http://…","p":"<一次性票据>"}`；
 *  旧版（≤3.7.100）生成的是 `{"i","t":"<长期令牌>"}`，仍能识别（legacyToken）。
 *
 *  **票据不是令牌**：它默认 120 秒过期、用一次即作废，必须拿去 /api/pair/claim
 *  换设备令牌——那才是长期凭据。 */
internal data class PairTarget(val url: String, val ticket: String, val legacyToken: String)

/** 解析配对二维码；不是这个格式返回 null。 */
internal fun parsePairPayload(text: String): PairTarget? = try {
    val obj = JSONObject(text)
    val url = obj.optString("i")
    if (url.startsWith("http")) {
        PairTarget(url, obj.optString("p"), obj.optString("t"))
    } else null
} catch (_: Exception) {
    null                       // 扫到的是别人的码 / 非 JSON：交给调用方提示
}

/** 解码位图里的二维码 → {"i","t"}；四个方向都试一遍（截图可能被旋转过）。 */
private fun decodeBitmap(src: Bitmap): PairTarget? {
    for (degree in intArrayOf(0, 90, 180, 270)) {
        val bmp = if (degree == 0) src else rotate(src, degree)
        val pair = decodeOnce(bmp)
        if (degree != 0) bmp.recycle()
        if (pair != null) return pair
    }
    return null
}

private fun decodeOnce(bmp: Bitmap): PairTarget? {
    val w = bmp.width
    val h = bmp.height
    if (w <= 0 || h <= 0) return null
    val px = IntArray(w * h)
    bmp.getPixels(px, 0, w, 0, 0, w, h)
    val reader = MultiFormatReader().apply {
        setHints(mapOf(DecodeHintType.TRY_HARDER to true))
    }
    val text = try {
        reader.decodeWithState(BinaryBitmap(HybridBinarizer(RGBLuminanceSource(w, h, px))))?.text
    } catch (_: Exception) {
        null
    } finally {
        reader.reset()
    } ?: return null
    return parsePairPayload(text)
}

private fun rotate(src: Bitmap, degree: Int): Bitmap {
    val m = Matrix().apply { postRotate(degree.toFloat()) }
    return Bitmap.createBitmap(src, 0, 0, src.width, src.height, m, true)
}

/** 解码相册选中的图片（截图通常已足够清晰）。 */
internal fun decodePairQr(ctx: Context, uri: Uri): PairTarget? {
    val bmp = ctx.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it) }
        ?: return null
    val pair = decodeBitmap(bmp)
    bmp.recycle()
    return pair
}

/** 扫码入口：主按钮 = 实时取景扫码，次按钮 = 从相册选截图。
 *
 *  3.6.144：扫到的**票据不能当令牌用**，要先 claim 换设备令牌——
 *  票据是一次性的、默认 120 秒过期；换回来的 `dev-` 令牌才是长期凭据（可单台吊销）。 */
@Composable
internal fun QrConnectRow(onDecoded: (url: String, token: String) -> Unit,
                          onFail: (String) -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var scanning by remember { mutableStateOf(false) }
    var claiming by remember { mutableStateOf(false) }

    /** 票据 → 设备令牌。旧版码（带 t 无 p）直接沿用，不做转换。 */
    fun finish(target: PairTarget) {
        if (target.ticket.isEmpty()) {
            if (target.legacyToken.isNotEmpty()) onDecoded(target.url, target.legacyToken)
            else onFail(AppI18n.s("这不是配对二维码（内容格式不对）"))
            return
        }
        if (claiming) return
        claiming = true
        scope.launch {
            val (token, err) = exchangeTicket(ctx, target)
            claiming = false
            if (err.isNotEmpty()) onFail(err) else onDecoded(target.url, token)
        }
    }

    fun handle(target: PairTarget?) {
        if (target == null) onFail(AppI18n.s("二维码识别失败")) else finish(target)
    }

    val pick = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        handle(try { decodePairQr(ctx, uri) } catch (_: Exception) { null })
    }

    // 全屏取景层：Dialog 的窗口铺满（usePlatformDefaultWidth=false），关掉即解绑相机
    if (scanning) {
        Dialog(onDismissRequest = { scanning = false },
            properties = DialogProperties(usePlatformDefaultWidth = false)) {
            Box(Modifier.fillMaxSize()) {
                QrScanScreen(
                    onDecoded = { target -> scanning = false; finish(target) },
                    onClose = { scanning = false })
            }
        }
    }
    ScanButtons(onScan = { scanning = true }, onPick = { pick.launch(arrayOf("image/*")) })
}

/** 票据 → 设备令牌：**先验身份再 claim**，成功后记住服务器 secret。
 *
 *  顺序不能反：先 claim 就等于"先把设备令牌交给对面，再问它是谁"。
 *  返回 `(token, 错误说明)`，两者只有一个非空。 */
private suspend fun exchangeTicket(ctx: Context, target: PairTarget): Pair<String, String> =
    withContext(Dispatchers.IO) {
        verifyServerIdentity(ctx, target.url)?.let { return@withContext "" to it }
        val (code, body) = claimDeviceToken(ctx, target)
        val token = body.optString("token")
        if (code != 200 || token.isEmpty()) return@withContext "" to pairClaimError(code, body)
        saveServerIdentity(ctx, target.url, body.optString("sk"))
        token to ""
    }

/** 设备机器码：`ANDROID_ID` 在同一台设备上稳定（恢复出厂/换 ROM 才变），
 *  足够让服务端认出"还是这台手机"。取不到返回空串——服务端会退化成旧行为（每次新建），
 *  不会因此配对失败。 */
private fun machineCode(ctx: Context): String =
    try {
        Settings.Secure.getString(ctx.contentResolver, Settings.Secure.ANDROID_ID) ?: ""
    } catch (_: Exception) {
        ""
    }

/** claim 的网络调用（IO 里执行，异常折成 -1，让调用方统一走错误提示）。
 *
 *  3.7.111：把机器码与本机已有令牌一并递上去——服务端靠它判断"这台手机登记过没有"，
 *  登记过就不再新增设备、也不换 token（本地令牌还有效时原样复用）。 */
private suspend fun claimDeviceToken(ctx: Context, target: PairTarget): Pair<Int, JSONObject> =
    withContext(Dispatchers.IO) {
        try {
            Api.claimPair(target.url, target.ticket, android.os.Build.MODEL ?: "",
                          machine = machineCode(ctx), knownToken = Api.token)
        } catch (e: Exception) {
            -1 to JSONObject().put("message", e.message ?: "")
        }
    }

/** claim 失败码 → 面向用户的说明（服务端只给 reason/HTTP 码，文案留在客户端才好翻译）。 */
private fun pairClaimError(code: Int, body: JSONObject): String = when (code) {
    410 -> AppI18n.s("二维码已过期，请在电脑上点刷新重新生成")
    409 -> AppI18n.s("该二维码已被使用，请重新生成")
    400 -> AppI18n.s("二维码无效，请重新生成")
    else -> AppI18n.sf("换取设备令牌失败：%1",
        body.optString("message").ifEmpty { "HTTP $code" })
}

/** 两个入口按钮（抽出：QrConnectRow 有 50 行预算）。 */
@Composable
private fun ScanButtons(onScan: () -> Unit, onPick: () -> Unit) {
    Column(Modifier.fillMaxWidth()) {
        Text("📷 " + AppI18n.s("扫码连接"), color = ACCENT, fontSize = 14.sp,
            modifier = Modifier.fillMaxWidth()
                .clip(RoundedCornerShape(10.dp))
                .background(ACCENT.copy(alpha = 0x22 / 255f))
                .border(1.dp, ACCENT, RoundedCornerShape(10.dp))
                .clickable { onScan() }
                .padding(horizontal = 14.dp, vertical = 12.dp))
        Text(AppI18n.s("从相册选择二维码截图"), color = MUTED, fontSize = 12.sp,
            modifier = Modifier.padding(top = 8.dp, start = 2.dp)
                .clickable { onPick() }
                .padding(vertical = 4.dp))
    }
}
