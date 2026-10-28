package com.biblioteca.reader

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import java.io.File

/* ================================================================
   下载管理（3.7.13 并发队列；3.6.9 断点续下语义重构）
   * 顶部汇总：进行中 / 排队 / 完成 / 暂停 / 失败；一键全部暂停、清除已完成
   * 列表项：封面 + 社团·作品 + 进度条 + 状态；单项可暂停 / 继续 / 删除
   * 3.6.9：暂停保留断点（.part），网络中断自动断点，点「继续」续下；
     「删除」= 移除下载项目并清掉 .part 残存文件（已完成项只移出列表，
     作品文件在本地书架，删作品请到书架长按）
   * 入口：本地书架顶部「⬇ 下载」（原「检查更新」位置；更新检查移到这里）

   3.7.43 结构：汇总行 / 空态 / 列表项四段各自独立（原 DownloadsScreen 56 行、
   DlRow 80 行，按"页头—汇总—空态—列表"与"卡片—状态—进度—明细"两级拆）。
   ================================================================ */

@Composable
fun DownloadsScreen(onBack: () -> Unit, onCheckUpdates: () -> Unit, checking: Boolean) {
    val ctx = LocalContext.current
    BackHandlerOn(onBack)                                  // 3.6.124：系统返回键不再退出 App
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("←", color = Color(0xFFF2EEFA), fontSize = 20.sp,
                modifier = Modifier.clickable { onBack() }.padding(end = 10.dp))
            Text(AppI18n.s("⬇ 下载管理"), color = Color(0xFFF2EEFA), fontSize = 18.sp, modifier = Modifier.weight(1f))
            Text(if (checking) AppI18n.s("检查中…") else AppI18n.s("⟳ 检查更新"), color = ACCENT2, fontSize = 13.sp,
                modifier = Modifier.clickable(enabled = !checking) { onCheckUpdates() }
                    .padding(start = 8.dp))
        }
        DlSummaryRow()
        Text(AppI18n.sf("最多 %1 个同时下载，超出自动排队；暂停只断连接、保留断点，网络中断也会自动断点，点「继续」接着续下；删除会连同没下完的残存文件一并清掉。", DownloadManager.MAX_CONCURRENT),
            color = Color(0xFF6E6787), fontSize = 10.sp, lineHeight = 14.sp,
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 4.dp))
        val items = DownloadManager.items
        if (items.isEmpty()) {
            DlEmptyHint()
        } else {
            LazyColumn(Modifier.fillMaxSize(),
                contentPadding = PaddingValues(start = 12.dp, end = 12.dp, top = 8.dp, bottom = 96.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)) {
                items(items, key = { it.key }) { it ->
                    DlRow(it, ctx)
                }
            }
        }
    }
}

/** 汇总行：五态计数 + 一键全部暂停 / 清除已完成（无对应任务时不显示该按钮）。 */
@Composable
private fun DlSummaryRow() {
    val running = DownloadManager.runningCount()
    val queued = DownloadManager.queuedCount()
    val done = DownloadManager.doneCount()
    val paused = DownloadManager.pausedCount()
    val bad = DownloadManager.failedCount()
    Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(AppI18n.sf("进行中 %1 · 排队 %2 · 完成 %3 · 暂停 %4 · 失败 %5", running, queued, done, paused, bad),
            color = Color(0xFF9A8FB8), fontSize = 11.sp, modifier = Modifier.weight(1f))
        if (running + queued > 0) {
            Text(AppI18n.s("⏸ 全部暂停"), color = Color(0xFFFFC86B), fontSize = 12.sp,
                modifier = Modifier.clickable { DownloadManager.pauseAll() })
        }
        if (done > 0) {
            Text(AppI18n.s("🧹 清除已完成"), color = Color(0xFF9A8FB8), fontSize = 12.sp,
                modifier = Modifier.clickable { DownloadManager.clearFinished() })
        }
    }
}

/** 空态：没有下载任务时的引导文案（入口在作品卡/社团/画师菜单）。 */
@Composable
private fun DlEmptyHint() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text("⬇", fontSize = 34.sp)
            Text(AppI18n.s("没有下载任务"), color = Color(0xFF9A8FB8), fontSize = 13.sp,
                modifier = Modifier.padding(top = 10.dp))
            Text(AppI18n.s("在作品卡片或社团/画师菜单里选「下载到本地 / 下载全部」"),
                color = Color(0xFF6E6787), fontSize = 11.sp,
                modifier = Modifier.padding(top = 4.dp))
        }
    }
}

/**
 * 下载列表项（3.7.43 拆为四段：卡片框 + 头部行 / 状态 pill / 进度条 / 明细行）。
 *
 * 封面：已下载的用本地快照，否则拉服务端（下载中也照常显示原封面）。
 */
@Composable
private fun DlRow(it: DlItem, ctx: android.content.Context) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
        .background(Color(0xFF140F22))
        .border(1.dp, Color(0x22FFFFFF), RoundedCornerShape(12.dp))
        .padding(10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            val coverFile: File? = LibraryStore.coverFile(ctx, it.group, it.work)
                .takeIf { f -> f.exists() }
            Box(Modifier.size(46.dp, 62.dp).clip(RoundedCornerShape(6.dp))
                .background(Color(0xFF1C1433))) {
                AsyncImage(
                    model = coverFile ?: Api.coverUrl(it.group, it.work),
                    contentDescription = it.work, contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize())
            }
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(it.work, color = Color(0xFFF2EEFA), fontSize = 13.sp,
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text("🏢 " + it.group, color = Color(0xFF9A8FB8), fontSize = 10.sp,
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Spacer(Modifier.width(8.dp))
            DlStatePill(it)
        }
        DlProgressBar(it)
        DlDetailRow(it)
    }
}

/** 状态 pill：排队 / 进行中（百分比，total 未知时退化为已下字节）/ 完成 / 失败 / 暂停。 */
@Composable
private fun DlStatePill(it: DlItem) {
    when (it.state) {
        DlState.QUEUED -> Text(AppI18n.s("排队中"), color = Color(0xFF9A8FB8), fontSize = 11.sp)
        DlState.RUNNING -> {
            val pct = if (it.total > 0) (it.done * 100 / it.total).coerceIn(0, 100) else -1
            Text(if (pct >= 0) "$pct%" else fmtBytesShelf(it.done),
                color = ACCENT2, fontSize = 11.sp)
        }
        DlState.DONE -> Text("✓ " + AppI18n.s("已完成"), color = Color(0xFF7BE0A8), fontSize = 11.sp)
        DlState.FAILED -> Text("✗ " + AppI18n.s("失败"), color = Color(0xFFFF7B8A), fontSize = 11.sp)
        DlState.PAUSED -> Text("⏸ " + AppI18n.s("已暂停"), color = Color(0xFFFFC86B), fontSize = 11.sp)
    }
}

/** 进度条（total 未知时按已下载字节做不确定态：条走满 + 显示字节）；0 不画。 */
@Composable
private fun DlProgressBar(it: DlItem) {
    val fraction = if (it.total > 0) (it.done.toFloat() / it.total.toFloat()).coerceIn(0f, 1f)
                   else if (it.state == DlState.RUNNING) 1f else 0f
    Box(Modifier.fillMaxWidth().height(4.dp).padding(top = 8.dp)
        .clip(RoundedCornerShape(2.dp)).background(Color(0xFF241B3D))) {
        if (fraction > 0f) {
            Box(Modifier.fillMaxWidth(fraction).fillMaxHeight()
                .clip(RoundedCornerShape(2.dp))
                .background(when (it.state) {
                    DlState.DONE -> Color(0xFF7BE0A8)
                    DlState.FAILED -> Color(0xFFFF7B8A)
                    DlState.PAUSED -> Color(0xFFFFC86B)
                    else -> ACCENT2
                }))
        }
    }
}

/** 明细行：字节进度 / 错误原因 + 操作（在跑可暂停；暂停/失败可继续；都可删除）。 */
@Composable
private fun DlDetailRow(it: DlItem) {
    Row(Modifier.fillMaxWidth().padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        val detail = when {
            it.state == DlState.FAILED -> it.error.ifEmpty { AppI18n.s("下载失败") }
            it.state == DlState.PAUSED ->
                (it.error.ifEmpty { AppI18n.s("已暂停") }) + AppI18n.s("（断点保留，点「继续」接着下）")
            it.total > 0 -> "${fmtBytesShelf(it.done)} / ${fmtBytesShelf(it.total)}"
            else -> fmtBytesShelf(it.done) + if (it.state == DlState.RUNNING) AppI18n.s("（大小未知）") else ""
        }
        Text(detail, color = Color(0xFF6E6787), fontSize = 10.sp,
            maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
        if (it.active) {
            Text(AppI18n.s("⏸ 暂停"), color = Color(0xFFFFC86B), fontSize = 12.sp,
                modifier = Modifier.clickable { DownloadManager.pause(it.key) }
                    .padding(start = 10.dp))
        } else {
            if (it.state == DlState.PAUSED || it.state == DlState.FAILED) {
                Text(AppI18n.s("▶ 继续"), color = ACCENT2, fontSize = 12.sp,
                    modifier = Modifier.clickable { DownloadManager.resume(it.key) }
                        .padding(start = 10.dp))
            }
            Text(AppI18n.s("🗑 删除"), color = Color(0xFF6E6787), fontSize = 12.sp,
                modifier = Modifier.clickable { DownloadManager.remove(it.key) }
                    .padding(start = 10.dp))
        }
    }
}
