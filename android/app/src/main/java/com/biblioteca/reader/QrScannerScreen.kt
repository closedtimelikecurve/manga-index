package com.biblioteca.reader

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Size
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size as GeoSize
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.google.zxing.BarcodeFormat
import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.MultiFormatReader
import com.google.zxing.PlanarYUVLuminanceSource
import com.google.zxing.common.HybridBinarizer
import java.util.concurrent.Executor
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/* ================================================================
   3.7.83 实时扫码（用户需求③）：
   以前是 `ActivityResultContracts.TakePicture` —— 拉起系统相机**拍一张照片**，
   再回头识图。用户的评价很准：那不是现代软件的做法，取景框里明明已经看见码了
   却要多按一次快门，还得等照片落盘。

   现在换成 CameraX：Preview 做实时取景，ImageAnalysis 逐帧（约 8 次/秒）把 Y 平面
   直接喂给 ZXing 的 PlanarYUVLuminanceSource **连续识别**，一识别到就关流回调。
   QR 的定位图案是各向同性的，所以拿到传感器方向的帧也不必旋转（1D 条码才需要）。
   ================================================================ */

/** 相机句柄：只用来在页面销毁时 unbind（否则关掉弹层相机还亮着、灯不灭）。 */
private class CameraHolder {
    var provider: ProcessCameraProvider? = null

    fun unbind() {
        try {
            provider?.unbindAll()
        } catch (_: Exception) {
            // 已经解绑/尚未绑定：关页面时不该因为清理失败闪退
        }
    }
}

/** 扫码取景的全屏层（由 QrConnect 用 Dialog 弹出，铺满整个窗口）。 */
@Composable
internal fun QrScanScreen(onDecoded: (PairTarget) -> Unit, onClose: () -> Unit) {
    val ctx = LocalContext.current
    var granted by remember { mutableStateOf(hasCamera(ctx)) }
    var asked by remember { mutableStateOf(false) }
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        granted = it
        asked = true
    }
    LaunchedEffect(Unit) {
        if (!granted) ask.launch(Manifest.permission.CAMERA)
    }
    Box(Modifier.fillMaxSize().background(Color.Black)) {
        if (granted) CameraLiveView(onDecoded) else PermissionHint(asked) {
            ask.launch(Manifest.permission.CAMERA)
        }
        ScanFrameOverlay(onClose)
    }
}

private fun hasCamera(ctx: Context): Boolean =
    ContextCompat.checkSelfPermission(ctx, Manifest.permission.CAMERA) ==
        PackageManager.PERMISSION_GRANTED

/** 取景框 + 暗角 + 说明 + 关闭；覆盖在预览之上（不挡住解码，只是遮罩）。 */
@Composable
private fun ScanFrameOverlay(onClose: () -> Unit) {
    Box(Modifier.fillMaxSize()) {
        Canvas(Modifier.fillMaxSize()) {
            val side = minOf(size.width, size.height) * 0.70f
            val left = (size.width - side) / 2f
            val top = (size.height - side) / 2f
            val dim = Color(0x73000000)
            drawRect(dim, size = GeoSize(size.width, top))
            drawRect(dim, topLeft = Offset(0f, top + side),
                size = GeoSize(size.width, size.height - top - side))
            drawRect(dim, topLeft = Offset(0f, top), size = GeoSize(left, side))
            drawRect(dim, topLeft = Offset(left + side, top),
                size = GeoSize(size.width - left - side, side))
            val len = side * 0.17f
            val w = 3.dp.toPx()
            listOf(
                Offset(left, top) to Offset(left + len, top),
                Offset(left, top) to Offset(left, top + len),
                Offset(left + side, top) to Offset(left + side - len, top),
                Offset(left + side, top) to Offset(left + side, top + len),
                Offset(left, top + side) to Offset(left + len, top + side),
                Offset(left, top + side) to Offset(left, top + side - len),
                Offset(left + side, top + side) to Offset(left + side - len, top + side),
                Offset(left + side, top + side) to Offset(left + side, top + side - len),
            ).forEach { (a, b) -> drawLine(ACCENT, a, b, strokeWidth = w) }
        }
        Column(Modifier.fillMaxWidth().align(Alignment.TopCenter).padding(top = 90.dp),
            horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("📷 " + AppI18n.s("扫码连接"), color = Color(0xFFF2EEFA), fontSize = 17.sp)
            Text(AppI18n.s("把面板上的二维码对准取景框，识别后会自动连接"),
                color = Color(0xCCF2EEFA), fontSize = 12.sp,
                modifier = Modifier.padding(horizontal = 32.dp))
        }
        Text(AppI18n.s("关闭"), color = Color(0xFFF2EEFA), fontSize = 14.sp,
            modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 54.dp)
                .clip(RoundedCornerShape(999.dp)).background(Color(0x33FFFFFF))
                .border(1.dp, Color(0x55FFFFFF), RoundedCornerShape(999.dp))
                .clickable { onClose() }
                .padding(horizontal = 26.dp, vertical = 10.dp))
    }
}

/** 没给相机权限：说明为什么需要 + 一个重新申请的按钮（拒绝后系统不再弹窗）。 */
@Composable
private fun PermissionHint(denied: Boolean, onAsk: () -> Unit) {
    Column(Modifier.fillMaxSize().padding(28.dp),
        verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
        Text("🔒", fontSize = 30.sp)
        Text(AppI18n.s("需要相机权限才能扫码"), color = Color(0xFFF2EEFA), fontSize = 14.sp,
            modifier = Modifier.padding(top = 12.dp, bottom = 16.dp))
        if (denied) {
            Text(AppI18n.s("授予权限"), color = Color(0xFFF2EEFA), fontSize = 13.sp,
                modifier = Modifier.clip(RoundedCornerShape(999.dp))
                    .background(ACCENT.copy(alpha = 0x33 / 255f))
                    .border(1.dp, ACCENT, RoundedCornerShape(999.dp))
                    .clickable { onAsk() }
                    .padding(horizontal = 20.dp, vertical = 9.dp))
        }
    }
}

/** 预览 + 逐帧分析；页面销毁时解绑相机。 */
@Composable
private fun CameraLiveView(onDecoded: (PairTarget) -> Unit) {
    val ctx = LocalContext.current
    val owner = LocalLifecycleOwner.current
    var err by remember { mutableStateOf("") }
    val holder = remember { CameraHolder() }
    val executor = remember { Executors.newSingleThreadExecutor() }
    val view = remember {
        PreviewView(ctx).apply {
            scaleType = PreviewView.ScaleType.FILL_CENTER
            implementationMode = PreviewView.ImplementationMode.COMPATIBLE
        }
    }
    DisposableEffect(Unit) {
        onDispose {
            holder.unbind()
            executor.shutdown()
        }
    }
    Box(Modifier.fillMaxSize()) {
        androidx.compose.ui.viewinterop.AndroidView(
            factory = { view }, modifier = Modifier.fillMaxSize())
        if (err.isNotEmpty()) {
            Text(AppI18n.s("无法打开相机") + "：" + err, color = Color(0xFFFF8DA1), fontSize = 12.sp,
                modifier = Modifier.align(Alignment.Center).padding(24.dp))
        }
    }
    LaunchedEffect(owner) {
        bindQrCamera(ctx, owner, view, executor, holder, onDecoded) { err = it }
    }
}

/** 绑定 Preview + ImageAnalysis（主线程回调，绑定失败交给调用方提示）。 */
private fun bindQrCamera(ctx: Context, owner: LifecycleOwner, view: PreviewView,
                         executor: Executor, holder: CameraHolder,
                         onDecoded: (PairTarget) -> Unit, onError: (String) -> Unit) {
    val future = ProcessCameraProvider.getInstance(ctx)
    future.addListener({
        val provider = try {
            future.get()
        } catch (e: Exception) {
            onError(e.message ?: "")
            return@addListener
        }
        try {
            val preview = Preview.Builder().build()
                .also { it.setSurfaceProvider(view.surfaceProvider) }
            val analysis = ImageAnalysis.Builder()
                .setResolutionSelector(qrResolver())
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
                .build()
            analysis.setAnalyzer(executor, QrAnalyzer(onDecoded))
            provider.unbindAll()
            provider.bindToLifecycle(owner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis)
            holder.provider = provider
        } catch (e: Exception) {
            onError(e.message ?: "")
        }
    }, ContextCompat.getMainExecutor(ctx))
}

/** 720p 足够解 QR（再高只是更费电），拿不到该档位就取最接近的。 */
private fun qrResolver(): ResolutionSelector =
    ResolutionSelector.Builder()
        .setResolutionStrategy(ResolutionStrategy(Size(1280, 720),
            ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER))
        .build()

/** 逐帧解码器：限流到约 8 次/秒，识别成功后即停（避免回调重复触发）。 */
private class QrAnalyzer(private val onDecoded: (PairTarget) -> Unit) :
    ImageAnalysis.Analyzer {
    private var lastAt = 0L
    private val done = AtomicBoolean(false)

    override fun analyze(image: ImageProxy) {
        if (done.get() || SystemClock.elapsedRealtime() - lastAt < 120L) {
            image.close()
            return
        }
        lastAt = SystemClock.elapsedRealtime()
        val text = try {
            decodeYPlane(image)
        } catch (_: Exception) {
            null
        } finally {
            image.close()
        }
        val pair = text?.let { parsePairPayload(it) } ?: return
        if (done.compareAndSet(false, true)) {
            Handler(Looper.getMainLooper()).post { onDecoded(pair) }
        }
    }
}

/** 直接读 Y 平面（亮度）——比先转 ARGB 位图省一次整帧拷贝；旋转不影响 QR 识别。 */
private fun decodeYPlane(image: ImageProxy): String? {
    val plane = image.planes.firstOrNull() ?: return null
    val width = image.width
    val height = image.height
    val stride = plane.rowStride
    if (width <= 0 || height <= 0 || stride < width) return null
    val buf = plane.buffer.also { it.rewind() }
    val data = ByteArray(stride * height)
    if (buf.remaining() < data.size) return null
    buf.get(data, 0, data.size)
    val source = PlanarYUVLuminanceSource(data, stride, height, 0, 0, width, height, false)
    val reader = MultiFormatReader().apply {
        setHints(mapOf(
            DecodeHintType.POSSIBLE_FORMATS to listOf(BarcodeFormat.QR_CODE),
            DecodeHintType.TRY_HARDER to true))
    }
    return try {
        reader.decode(BinaryBitmap(HybridBinarizer(source)))?.text
    } catch (_: Exception) {
        null                                  // NotFoundException：这一帧没码，继续看下一帧
    } finally {
        reader.reset()
    }
}
