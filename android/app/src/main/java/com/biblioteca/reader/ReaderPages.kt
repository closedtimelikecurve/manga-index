package com.biblioteca.reader

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView
import coil.compose.AsyncImage
import coil.imageLoader
import coil.request.CachePolicy
import coil.request.ImageRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/* ================================================================
   阅读器公共层（3.7.43 从 ReaderScreen.kt 拆出）：
   页面媒体类型判定 / 视口与解码盒子 / 图片请求统一构造 /
   未载入与失败占位 / 视频页（本地解压 or 远程直链）。
   ================================================================ */

/* ---------------- 页面媒体类型判定（服务端 /api/pages 的 kinds：image | gif | video） ----------------
   动图（gif）与静态图的内存代价差一个量级：一张 712×1150、65 帧的 GIF 解码约 200MB，
   所以动图页既不在预读范围，解码尺寸也要再收一档、且不留在 Coil 内存缓存里。 */
fun isVideoAt(kinds: List<String>?, p: Int): Boolean =
    kinds != null && p < kinds.size && kinds[p] == "video"

fun isAnimAt(kinds: List<String>?, p: Int): Boolean =
    kinds != null && p < kinds.size && kinds[p] == "gif"

/** 视口像素尺寸（屏幕宽高）：作为图片解码盒子的上限，杜绝"按原图解码" */
@Composable
fun viewportPx(): Pair<Int, Int> {
    val d = LocalDensity.current
    val c = LocalConfiguration.current
    return with(d) { c.screenWidthDp.dp.roundToPx() } to
           with(d) { c.screenHeightDp.dp.roundToPx() }
}

/** 动图解码盒子：屏幕与 1200 取小（帧数 × 像素 双重放大内存，宁小勿大；不放大原图） */
private fun animBox(vpW: Int, vpH: Int): Pair<Int, Int> =
    minOf(vpW, 1200).coerceAtLeast(1) to minOf(vpH, 1200).coerceAtLeast(1)

/**
 * 阅读器图片请求统一构造（**必须显式给 size**）：
 * Coil 在"没有 size 也没有 ViewTarget"时按原图解码 —— 那是动图作品崩溃的直接原因。
 *   * 静态页：盒子 = 屏宽 × 屏高×2（FIT 缩放）。高度给两倍是为了不让"长条页"被压到
 *     比屏窄而变糊（滚动模式按屏宽铺满显示）；同时仍能挡住 3000×9000 这种超大原图。
 *   * 动图页（anim）：盒子收到 1200 以内，并关掉内存缓存 —— 动图内存 = 帧数 × 像素，
 *     几十帧的大动图是全分辨率解码的致命点，宁小勿大；磁盘缓存照旧（重看不重下）。
 * model：远程 = 页面 URL 字符串；本地书架 = LocalPage（自定义 Fetcher zip 直读）。
 */
fun pageRequest(ctx: Context, model: Any, retry: Int, vpW: Int, vpH: Int,
                anim: Boolean, crossfade: Boolean): ImageRequest {
    val (w, h) = if (anim) animBox(vpW, vpH) else vpW to vpH * 2
    val b = ImageRequest.Builder(ctx)
        .data(model)
        .addHeader("X-Token", Api.token)
        .crossfade(crossfade)
        .setParameter("retry", retry)
        .memoryCacheKey(
            when (model) {
                is LocalPage -> "${model.cacheKey}#$retry"
                else -> "$model#$retry"
            })
        .size(w.coerceAtLeast(1), h.coerceAtLeast(1))
    if (anim) b.memoryCachePolicy(CachePolicy.DISABLED)
    return b.build()
}

/* ---- 未加载/加载失败占位条（对齐官方文案）：矮条不占屏，页码状态一眼可见；
   配合「预读后续 5 页」，正常阅读时几乎看不到占位 ---- */
@Composable
fun PagePlaceholder(no: Int, total: Int, fill: Boolean) {
    Box(Modifier.then(if (fill) Modifier.fillMaxSize() else Modifier.fillMaxWidth().height(64.dp))
        .background(Color(0xFF12101F)), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            CircularProgressIndicator(color = ACCENT2, strokeWidth = 2.dp,
                modifier = Modifier.size(18.dp))
            Spacer(Modifier.height(4.dp))
            Text(if (total > 0) AppI18n.sf("第 %1 / %2 页 · 载入中…", no, total) else AppI18n.sf("第 %1 页 · 载入中…", no),
                color = Color(0xFF9A8FB8), fontSize = 10.sp)
        }
    }
}

@Composable
fun PageLoadFailed(no: Int, fill: Boolean, onRetry: () -> Unit) {
    Box(Modifier.then(if (fill) Modifier.fillMaxSize() else Modifier.fillMaxWidth().height(64.dp))
        .background(Color(0xFF12101F)), contentAlignment = Alignment.Center) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(AppI18n.sf("第 %1 页 载入失败", no), color = Color(0xFFFF5ED0), fontSize = 11.sp)
            Text(AppI18n.s("⟳ 点击重试"), color = Color(0xFF9A8FB8), fontSize = 11.sp,
                modifier = Modifier.padding(start = 10.dp).clickable { onRetry() })
        }
    }
}

/** 视频页统一入口：本地来源先把 webm 条目解压到缓存（file://），远程直接用页面 URL。
 * 播放器 DataSource 按协议路由（file → 本地文件；http(s) → 带 X-Token 的 HTTP）。 */
@Composable
fun VideoPageAsync(source: ReaderSource, n: Int, modifier: Modifier = Modifier) {
    var uri by remember(source, n) { mutableStateOf<String?>(null) }
    var err by remember(source, n) { mutableStateOf("") }
    LaunchedEffect(source, n) {
        try { uri = withContext(Dispatchers.IO) { source.videoUri(n) } }
        catch (e: Exception) { err = e.message ?: e.toString() }
    }
    if (uri != null) {
        VideoPage(uri!!, Api.token, modifier)
    } else {
        Box(modifier.background(Color.Black), contentAlignment = Alignment.Center) {
            Text(if (err.isEmpty()) AppI18n.s("视频载入中…") else AppI18n.sf("视频载入失败：%1", err),
                color = if (err.isEmpty()) Color(0xFF9A8FB8) else Color(0xFFFF5ED0), fontSize = 11.sp)
        }
    }
}

@Composable
fun VideoPage(url: String, token: String, modifier: Modifier = Modifier) {
    val ctx = LocalContext.current
    val exo = remember(url) {
        val httpDs = DefaultHttpDataSource.Factory()
            .setDefaultRequestProperties(mapOf("X-Token" to token))
            .setAllowCrossProtocolRedirects(true)
        // DefaultDataSource 按协议路由：file:// → FileDataSource（本地书架视频），http(s) → 上面带 token 的 HTTP
        val ds = androidx.media3.datasource.DefaultDataSource.Factory(ctx, httpDs)
        ExoPlayer.Builder(ctx, DefaultMediaSourceFactory(ds)).build().apply {
            setMediaItem(MediaItem.fromUri(url))
            repeatMode = Player.REPEAT_MODE_ONE
            prepare()
            playWhenReady = true
        }
    }
    DisposableEffect(url) { onDispose { exo.release() } }
    AndroidView(
        factory = { v -> PlayerView(v).apply { player = exo } },
        modifier = modifier.background(Color.Black))
}
