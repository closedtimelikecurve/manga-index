package com.biblioteca.reader

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage

/* ================================================================
   清单爬虫的监控面板（3.7.58 立，3.7.59 重做）
   * 作品卡与「分区爬虫」查询结果同款：左 84×112 封面、右标题四行 + 状态行；
   * 不再显示状态灯面板与运行日志；
   * 离开界面后回来，上一次的"已结束"回到空闲（见 refreshCrawlJob 的 sawRunning）。
   ================================================================ */

/* 3.7.73：状态词走 AppI18n.s（key=简中原文）——语言切换即时重组（原 map 常量
   初始化时固化，无法跟随语言）；"爬取中/集中爬取中"顺手统一为"获取中/集中获取中"。 */
internal fun CRAWL_JOB_STATES(state: String): String = when (state) {
    "queued" -> AppI18n.s("待锁定")
    "locking" -> AppI18n.s("锁定中")
    "locked" -> AppI18n.s("已锁定")
    "downloading" -> AppI18n.s("获取中")
    "importing" -> AppI18n.s("入库中")
    "ok" -> AppI18n.s("完成")
    "fail" -> AppI18n.s("失败")
    "unmatched" -> AppI18n.s("未匹配")
    "skip" -> AppI18n.s("跳过")
    else -> state
}

internal fun CRAWL_PHASE_TEXT(phase: String): String = when (phase) {
    "idle" -> AppI18n.s("空闲")
    "lock" -> AppI18n.s("锁定作品中")
    "cover" -> AppI18n.s("准备封面")
    "download" -> AppI18n.s("集中获取中")
    else -> AppI18n.s("已结束")
}

/** 手机上最多画这么多张卡片，再多拖慢滚动（其余给汇总行）。两套看板共用。 */
internal const val CRAWL_CARDS = 6

/** 面板主体；没跑过任务时不占地方。 */
@Composable
internal fun CrawlMonitorCard(ui: CrawlScreenState, onCancel: () -> Unit) {
    val job = ui.job ?: return
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
        .background(CARD_BG).border(1.dp, ACCENT.copy(alpha = 0x44 / 255f), RoundedCornerShape(12.dp))
        .padding(12.dp)) {
        CrawlMonitorHead(job, onCancel)
        CrawlMonitorBar(job)
        Text(crawlJobStats(job), color = MUTED, fontSize = 11.sp,
            modifier = Modifier.padding(top = 6.dp, bottom = 8.dp))
        // 与分区爬虫结果一致：单列竖排，每张卡横板（封面在左、标题在右）
        crawlJobPicks(job).forEach { it ->
            CrawlItemCard(it, Modifier.fillMaxWidth().padding(bottom = 8.dp))
        }
        if (job.total > CRAWL_CARDS) {
            Text(AppI18n.sf("另有 %1 部未显示（完整卡片见网页端「清单下载器」）", job.total - CRAWL_CARDS),
                color = MUTED, fontSize = 10.sp)
        }
    }
}

@Composable
private fun CrawlMonitorHead(job: Api.CrawlJob, onCancel: () -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(if (job.running) "🎯 " + (CRAWL_PHASE_TEXT(job.phase)) else AppI18n.s("已结束"),
            color = TXT, fontSize = 13.sp)
        Text("　${job.label} · ${fmtCrawlElapsed(job)}", color = MUTED, fontSize = 10.sp,
            maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
        Text("${job.done}/${job.total}", color = ACCENT, fontSize = 13.sp)
        if (job.running) {
            Text("  ■ " + AppI18n.s("停止"), color = Color(0xFFFFC86B), fontSize = 11.sp,
                modifier = Modifier.clickable { onCancel() }.padding(start = 6.dp))
        }
    }
}

private fun fmtCrawlElapsed(job: Api.CrawlJob): String {
    val s = job.elapsed
    val m = s / 60
    val t = if (m > 0) AppI18n.sf("%1 分 %2 秒", m, s % 60) else AppI18n.sf("%1 秒", s)
    return (if (job.running) AppI18n.sf("已运行 %1", t) else AppI18n.sf("耗时 %1", t)) +
        if (job.current.isNotEmpty() && job.running) " · ${job.current.take(16)}" else ""
}

@Composable
private fun CrawlMonitorBar(job: Api.CrawlJob) {
    val pct = crawlJobPct(job)
    Box(Modifier.fillMaxWidth().padding(top = 8.dp).height(5.dp)
        .clip(RoundedCornerShape(999.dp)).background(CARD_BG2)) {
        Box(Modifier.fillMaxWidth(pct).height(5.dp).background(ACCENT))
    }
}

/** 百分比：锁定阶段看已锁定，爬取阶段看已处理（与网页端同一口径）。 */
private fun crawlJobPct(job: Api.CrawlJob): Float {
    if (job.total <= 0) return 0f
    val n = if (job.phase == "lock") job.locked else job.done + job.failed
    return (n.toFloat() / job.total).coerceIn(0f, 1f)
}

private fun crawlJobStats(job: Api.CrawlJob): String = buildString {
    append(AppI18n.s("已锁定") + " ${job.locked} · " + AppI18n.s("完成") + " ${job.done} · " + AppI18n.s("失败") + " ${job.failed}")
    if (job.skipped > 0) append(" · " + AppI18n.s("跳过") + " ${job.skipped}")
    if (job.message.isNotEmpty()) append("　${job.message.take(24)}")
}

/** 取"最该看的"卡片：进行中优先，其次已锁定，最后其余（最多 CRAWL_CARDS 张）。 */
private fun crawlJobPicks(job: Api.CrawlJob): List<Api.CrawlItem> {
    val order = listOf("downloading", "locking", "locked", "queued", "fail", "unmatched", "ok", "skip")
    val rank = order.withIndex().associate { it.value to it.index }
    return job.items.sortedBy { rank[it.state] ?: 99 }.take(CRAWL_CARDS)
}

/** 单部作品卡片（薄包装）：字段从 CrawlItem 取。 */
@Composable
private fun CrawlItemCard(it: Api.CrawlItem, modifier: Modifier) {
    MonitorWorkCard(it.title.ifEmpty { it.entry }, it.cover, it.state,
        CRAWL_JOB_STATES(it.state), crawlItemNote(it), modifier)
}

/**
 * 单部作品卡片本体（3.7.69 从 CrawlItemCard 抽出）：清单爬虫与分区爬取的监控看板共用
 * ——与分区爬虫查询结果同款（84×112 封面 + 标题四行 + 状态徽标 + note）。
 */
@Composable
internal fun MonitorWorkCard(title: String, cover: String, state: String,
                             stateText: String, note: String, modifier: Modifier = Modifier) {
    Row(modifier.clip(RoundedCornerShape(12.dp))
        .background(if (state == "downloading") ACCENT2.copy(alpha = 0x1F / 255f) else CARD_BG2)
        .border(1.dp, crawlStateColor(state), RoundedCornerShape(12.dp))
        .padding(8.dp), verticalAlignment = Alignment.Top) {
        CrawlItemCover(cover)
        Column(Modifier.weight(1f).padding(start = 8.dp)) {
            Text(title, color = TXT, fontSize = 12.sp,
                lineHeight = 17.sp, maxLines = 4, overflow = TextOverflow.Ellipsis)
            Row(Modifier.padding(top = 5.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(stateText, color = crawlStateColor(state), fontSize = 10.sp)
                if (note.isNotEmpty()) {
                    Text(note, color = MUTED, fontSize = 10.sp,
                        maxLines = 1, overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.padding(start = 6.dp))
                }
            }
        }
    }
}

@Composable
private fun CrawlItemCover(url: String) {
    Box(Modifier.size(84.dp, 112.dp).clip(RoundedCornerShape(8.dp))
        .background(CARD_BG2), contentAlignment = Alignment.Center) {
        if (url.isEmpty()) {
            Text("🎴", fontSize = 20.sp)
        } else {
            AsyncImage(model = Api.probeCoverUrl(url), contentDescription = null,
                contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        }
    }
}

/** 状态→颜色：清单与分区爬取监控卡共用（3.7.69 起 internal）。 */
internal fun crawlStateColor(state: String): Color = when (state) {
    "ok", "importing" -> Color(0xFF43C6A8)
    "fail", "unmatched" -> Color(0xFFFF6B8B)
    "downloading", "locking" -> ACCENT
    else -> Color(0x33FFFFFF)
}

private fun crawlItemNote(it: Api.CrawlItem): String = when {
    it.state == "downloading" && it.bytes > 0 ->
        fmtJobBytes(it.bytes) + if (it.bytesTotal > 0) " / " + fmtJobBytes(it.bytesTotal) else ""
    it.state == "downloading" -> AppI18n.s("连接中…")
    it.state == "fail" || it.state == "unmatched" || it.state == "skip" -> it.msg.take(40)
    it.state == "ok" -> it.msg.take(40)
    it.aid.isNotEmpty() -> "aid ${it.aid}" + if (it.pages > 0) " · " + AppI18n.sf("%1 页", it.pages) else ""
    else -> it.msg.take(40)
}

private fun fmtJobBytes(n: Long): String = when {
    n >= 1048576 -> String.format("%.1f MB", n / 1048576.0)
    n >= 1024 -> String.format("%.0f KB", n / 1024.0)
    else -> "$n B"
}
