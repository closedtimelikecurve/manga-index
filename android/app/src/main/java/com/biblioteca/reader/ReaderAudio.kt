package com.biblioteca.reader

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

/* ================================================================
   阅读器 · 音声面板（v3.0.1，3.7.43 从 ReaderScreen.kt 拆出）
   轨道切换 / 播放控制 / lrc 字幕随播放进度实时同步。
   音频与漫画页相互独立：音频按轨播放、字幕按时间轴走，漫画页由用户照常翻阅 ——
   "音画同步" = 台词字幕与音频严格同步 + 同屏看图。
   ================================================================ */

private fun fmtAudioTime(ms: Long): String {
    val s = (ms / 1000).coerceAtLeast(0)
    return "%d:%02d".format(s / 60, s % 60)
}

/** 音声播放器（3.7.43 提为纯构建函数）：远程流式 / 本地缓存文件按协议路由；uri 未就绪返回 null。 */
private fun buildAudioPlayer(ctx: Context, uri: String?): ExoPlayer? {
    val u = uri ?: return null
    val httpDs = DefaultHttpDataSource.Factory()
        .setDefaultRequestProperties(mapOf("X-Token" to Api.token))
        .setAllowCrossProtocolRedirects(true)
    // DefaultDataSource 按协议路由：file:// → 本地缓存音频；http(s) → 带 token 的 HTTP
    val ds = androidx.media3.datasource.DefaultDataSource.Factory(ctx, httpDs)
    return ExoPlayer.Builder(ctx, DefaultMediaSourceFactory(ds)).build().apply {
        setMediaItem(MediaItem.fromUri(u))
        repeatMode = Player.REPEAT_MODE_OFF
        prepare()
        playWhenReady = true
    }
}

/** 音声面板挂件（3.7.43 从 ReaderScreen 抽出）：有轨且开启时才渲染（贴底 overlay）。 */
@Composable
fun ReaderAudioPanel(source: ReaderSource, tracks: List<Api.AudioTrack>, on: Boolean,
                     modifier: Modifier = Modifier) {
    if (!on || tracks.isEmpty()) return
    AudioPanel(source = source, tracks = tracks, modifier = modifier)
}

@Composable
fun AudioPanel(source: ReaderSource, tracks: List<Api.AudioTrack>, modifier: Modifier = Modifier) {
    val ctx = LocalContext.current
    var trackIdx by remember(source) { mutableIntStateOf(0) }
    var posMs by remember { mutableLongStateOf(0L) }
    var durMs by remember { mutableLongStateOf(0L) }
    var playing by remember { mutableStateOf(false) }
    var uri by remember(trackIdx) { mutableStateOf<String?>(null) }
    var err by remember(trackIdx) { mutableStateOf("") }

    // 解析可播 URI（远程 = 流式 URL；本地 = 整轨解压到缓存，65MB 级首次有几秒等待）
    LaunchedEffect(source, trackIdx) {
        uri = null; err = ""
        try { uri = withContext(Dispatchers.IO) { source.audioUri(trackIdx) } }
        catch (e: Exception) { err = e.message ?: e.toString() }
    }

    val exo = remember(trackIdx, uri) { buildAudioPlayer(ctx, uri) }
    // 位置轮询：字幕同步 + 进度条 + 播完自动切下一轨
    LaunchedEffect(exo) {
        if (exo == null) { playing = false; return@LaunchedEffect }
        while (true) {
            posMs = exo.currentPosition.coerceAtLeast(0)
            exo.duration.takeIf { it > 0 }?.let { durMs = it }
            playing = exo.isPlaying
            if (exo.playbackState == Player.STATE_ENDED && trackIdx < tracks.size - 1) trackIdx += 1
            delay(250)
        }
    }
    DisposableEffect(exo) { onDispose { exo?.release() } }

    val lrc = tracks.getOrNull(trackIdx)?.lrc ?: emptyList()
    val curIdx = lrc.indexOfLast { it.first <= posMs }        // 最后一条 <= 当前进度
    val cur = if (curIdx >= 0) lrc[curIdx] else null
    val next = if (curIdx + 1 < lrc.size) lrc[curIdx + 1] else null
    var dragFrac by remember { mutableStateOf<Float?>(null) }

    Column(modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
        .background(Color(0xF20E0B1B))
        .border(1.dp, ACCENT.copy(alpha = 0x44 / 255f), RoundedCornerShape(12.dp))
        .padding(horizontal = 14.dp, vertical = 8.dp)) {
        AudioLrcBand(err, uri != null, cur?.second, next?.second)
        AudioProgressRow(posMs, durMs, dragFrac, onDrag = { dragFrac = it }, exo)
        AudioControlsRow(tracks, trackIdx, playing, exo, onTrack = { trackIdx = it })
    }
}

/** 字幕带：当前句（大）+ 下一句（小，预览）。 */
@Composable
private fun AudioLrcBand(err: String, loaded: Boolean, cur: String?, next: String?) {
    Column(Modifier.fillMaxWidth().heightIn(min = 46.dp)) {
        Text(
            when {
                err.isNotEmpty() -> AppI18n.sf("音声载入失败：%1", err)
                !loaded -> AppI18n.s("音声载入中…")
                cur == null -> AppI18n.s("▶ 待播放")
                else -> cur.ifEmpty { "…" }
            },
            color = if (err.isNotEmpty()) Color(0xFFFF5ED0) else Color(0xFFF2EEFA),
            fontSize = 14.sp, lineHeight = 19.sp)
        if (err.isEmpty() && next != null && next.isNotEmpty()) {
            Text(next, color = Color(0xFF9A8FB8), fontSize = 11.sp,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(top = 3.dp))
        }
    }
}

/** 进度行：已播/总时长 + 可拖动定位的滑轨（拖动值经 onDrag 回传，松手才 seek）。 */
@Composable
private fun AudioProgressRow(posMs: Long, durMs: Long, dragFrac: Float?,
                             onDrag: (Float?) -> Unit, exo: ExoPlayer?) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(fmtAudioTime(posMs), color = Color(0xFF9A8FB8), fontSize = 10.sp)
        Slider(
            value = dragFrac ?: (if (durMs > 0) (posMs.toFloat() / durMs).coerceIn(0f, 1f) else 0f),
            onValueChange = { onDrag(it.coerceIn(0f, 1f)) },
            onValueChangeFinished = {
                dragFrac?.let { f -> exo?.seekTo((f * durMs).toLong()) }
                onDrag(null)
            },
            colors = SliderDefaults.colors(
                thumbColor = ACCENT2, activeTrackColor = ACCENT2,
                inactiveTrackColor = Color(0x59FFFFFF)),
            modifier = Modifier.weight(1f).padding(horizontal = 10.dp).height(22.dp))
        Text(fmtAudioTime(durMs), color = Color(0xFF9A8FB8), fontSize = 10.sp)
    }
}

/** 控制行：上一轨 / 播放暂停 / 下一轨 + 轨道 chips（横向滚动）。 */
@Composable
private fun AudioControlsRow(tracks: List<Api.AudioTrack>, trackIdx: Int, playing: Boolean,
                             exo: ExoPlayer?, onTrack: (Int) -> Unit) {
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("⏮", color = Color(0xFFF2EEFA), fontSize = 15.sp,
            modifier = Modifier.clickable(enabled = tracks.size > 1) {
                onTrack((trackIdx - 1 + tracks.size) % tracks.size)
            }.padding(horizontal = 6.dp))
        Text(if (playing) "⏸" else "▶️", color = ACCENT2, fontSize = 19.sp,
            modifier = Modifier.clickable {
                exo?.let { if (it.isPlaying) it.pause() else it.play() }
            }.padding(horizontal = 8.dp))
        Text("⏭", color = Color(0xFFF2EEFA), fontSize = 15.sp,
            modifier = Modifier.clickable(enabled = tracks.size > 1) {
                onTrack((trackIdx + 1) % tracks.size)
            }.padding(horizontal = 6.dp))
        Spacer(Modifier.width(4.dp))
        tracks.forEachIndexed { i, t ->
            val on = i == trackIdx
            Text(t.shortName, color = if (on) Color(0xFF1C1433) else Color(0xFF9A8FB8),
                fontSize = 11.sp, maxLines = 1,
                modifier = Modifier.clip(RoundedCornerShape(999.dp))
                    .background(if (on) ACCENT2 else Color(0x1AFFFFFF))
                    .clickable { onTrack(i) }
                    .padding(horizontal = 10.dp, vertical = 5.dp))
        }
    }
}
