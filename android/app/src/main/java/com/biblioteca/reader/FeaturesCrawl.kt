package com.biblioteca.reader

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.CoroutineScope

/**
 * 清单爬虫（3.7.59：与「分区爬虫」彻底分开，各自独立运行）。
 *
 * 页面只剩三块：**监控面板**（逐部作品卡，带封面）+ **任务胶囊**（运行中文字变绿）
 * + **清单与启停**。原来的"状态灯"面板与运行日志都已移除。
 */
@Composable
fun CrawlScreen(onBack: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val ui = remember { CrawlScreenState() }

    LaunchedEffect(Unit) {
        refreshBuiltinKinds()   // 3.7.109：公开版只显示可用任务的胶囊
        if (crawlKinds().none { it.first == ui.kind }) {
            crawlKinds().firstOrNull()?.let { ui.kind = it.first }   // 默认任务回退到第一个可用项
        }
        crawlPollLoop(scope, ui, onLists = { ui.applyLists(it) },
            onListsError = { ui.msg = it })
    }
    LaunchedEffect(ui.listWnacg, ui.listIndex, ui.listJmdlT, ui.listJmdlI, ui.listNhdl, ui.listEh, ui.listExt) {
        // 清单编辑自动保存（1.2 秒防抖），退出重进不丢
        if (!ui.listsLoaded) return@LaunchedEffect
        autoSaveCrawlLists(scope, ui, ui.listWnacg, ui.listIndex, ui.listJmdlT,
            ui.listJmdlI, ui.listNhdl, ui.listEh, ui.listExt)
    }
    BackHandlerOn(onBack)
    Column(Modifier.fillMaxSize()) {
        TopBar("🕷 " + AppI18n.s("清单下载器"), onBack)
        Column(Modifier.fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(12.dp, 4.dp)) {
            CrawlMonitorCard(ui) { stopCrawlTask(scope, ui, ui.kind, ctx) }
            CrawlKindRow(ui) { k ->
                if (k == ui.kind) return@CrawlKindRow
                ui.kind = k
                ui.job = null            // 切任务：先回到空闲，再拉这个任务的快照
                ui.sawRunning = false
                refreshCrawlNow(scope, ui)
            }
            CrawlOptionRow(AppI18n.s("档位："), crawlModes(), ui.mode, ui.busy) { ui.mode = it }
            CrawlStartRow(ui,
                onStart = { startCrawlTask(scope, ui, ctx) },
                onStop = { stopCrawlTask(scope, ui, ui.kind, ctx) })
            CrawlListSection(ui)
            CrawlCopyRow(ui, ctx)
            Spacer(Modifier.height(20.dp))
        }
    }
}

/**
 * 任务胶囊行（3.7.59 起）：七枚胶囊，**运行中的那枚文字变绿**——原先的"状态灯"面板已删除。
 * 横滚以适配窄屏。
 */
@Composable
private fun CrawlKindRow(ui: CrawlScreenState, onKind: (String) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(top = 12.dp)
        .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        crawlKinds().forEach { (k, label) ->
            val selected = ui.kind == k
            val running = ui.runningKinds.contains(k)
            Text(label, color = if (running) Color(0xFF43C6A8) else if (selected) TXT else MUTED,
                fontSize = 11.sp, maxLines = 1,
                modifier = Modifier
                    .clip(RoundedCornerShape(999.dp))
                    .background(if (selected) ACCENT.copy(alpha = 0x33 / 255f) else CARD_BG2)
                    .border(1.dp,
                        if (running) Color(0xFF43C6A8) else if (selected) ACCENT else Color(0x24FFFFFF),
                        RoundedCornerShape(999.dp))
                    .clickable(enabled = !ui.busy) { onKind(k) }
                    .padding(horizontal = 10.dp, vertical = 6.dp))
        }
    }
}

/** 通用 chip 选项行（匹配档位）。 */
@Composable
private fun CrawlOptionRow(label: String, options: List<Pair<String, String>>,
                           current: String, busy: Boolean, onPick: (String) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(top = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(label, color = MUTED, fontSize = 11.sp)
        options.forEach { (v, text) ->
            val selected = current == v
            Text(text, color = if (selected) TXT else MUTED, fontSize = 11.sp,
                maxLines = 1,
                modifier = Modifier
                    .clip(RoundedCornerShape(999.dp))
                    .background(if (selected) ACCENT.copy(alpha = 0x33 / 255f) else CARD_BG2)
                    .border(1.dp, if (selected) ACCENT else Color(0x24FFFFFF),
                        RoundedCornerShape(999.dp))
                    .clickable(enabled = !busy) { onPick(v) }
                    .padding(horizontal = 10.dp, vertical = 6.dp))
        }
    }
}

/** 上限输入 + 启动/停止行（只挡住「同一任务重复启动」）。 */
@Composable
private fun CrawlStartRow(ui: CrawlScreenState, onStart: () -> Unit, onStop: () -> Unit) {
    val running = ui.job?.running == true || ui.runningKinds.contains(ui.kind)
    Row(Modifier.fillMaxWidth().padding(top = 10.dp),
        verticalAlignment = Alignment.CenterVertically) {
        OutlinedTextField(ui.limit, { ui.limit = it.filter { c -> c.isDigit() }.take(5) },
            label = { Text(AppI18n.s("单次上限")) }, singleLine = true,
            colors = appFieldColors(),
            modifier = Modifier.width(110.dp))
        Spacer(Modifier.weight(1f))
        Button(onClick = onStart, enabled = !ui.busy && !running) { Text(AppI18n.s("▶ 启动")) }
        Spacer(Modifier.width(8.dp))
        Button(onClick = onStop, enabled = !ui.busy && running) { Text(AppI18n.s("■ 停止")) }
    }
}

/** 清单编辑区：按当前任务显示对应清单（JM/N站索引共享一个）。 */
@Composable
private fun CrawlListSection(ui: CrawlScreenState) {
    // 清单标题 = **面板侧的文件名**（用户要在电脑上找到同名 .txt 编辑），所以文件名不译，
    // 只译括号里的写法提示；文件名字面量用 `i18n:data` 标给缺口报表，见 docs/i18n-gap §七。
    if (ui.kind == "wnacg") {
        CrawlListFieldTitle("pending_wnacg" + AppI18n.s("（每行一个词条）"))   // i18n:data
        CrawlListField(ui.listWnacg, { ui.listWnacg = it }, 140)
    }
    if (ui.kind == "jm" || ui.kind == "nh") {
        CrawlListFieldTitle("pending_index" +                                     // i18n:data
            AppI18n.s("（JM/N站共享；每行一个数字 ID，N站还支持罗马音/日文词条）"))
        CrawlListField(ui.listIndex, { ui.listIndex = it }, 100)
        Text(AppI18n.s("JM：车号 → jmcomic 标题 → wnacg 转载。N站：ID 直接用，词条搜索裁决出 ID。") +
            AppI18n.s("跑完自动清除已完成条目。"),
            color = MUTED, fontSize = 10.sp,
            modifier = Modifier.padding(top = 2.dp, bottom = 4.dp))
    }
    if (ui.kind == "jmdl") {
        CrawlListFieldTitle("pending_jmdl_titles" + AppI18n.s("（每行一个标题词条，走 JM 站内搜索）"))  // i18n:data
        CrawlListField(ui.listJmdlT, { ui.listJmdlT = it }, 110)
        CrawlListFieldTitle("pending_jmdl_ids" + AppI18n.s("（每行一个数字车号，直接下载）"))       // i18n:data
        CrawlListField(ui.listJmdlI, { ui.listJmdlI = it }, 80)
    }
    if (ui.kind == "nhdl") {
        CrawlListFieldTitle("pending_nhdl" + AppI18n.s("（每行一个数字 ID 或罗马音/日文词条）"))  // i18n:data
        CrawlListField(ui.listNhdl, { ui.listNhdl = it }, 100)
        Text(AppI18n.s("ID 直接用；词条搜索出 ID → 日文名作文件名 → 官方 ZIP 或图片 CDN 自建。"),
            color = MUTED, fontSize = 10.sp,
            modifier = Modifier.padding(top = 2.dp, bottom = 4.dp))
    }
    if (ui.kind == "eh") {
        CrawlListFieldTitle("pending_ehdl" + AppI18n.s("（每行一个画廊 URL 或标题词条）"))   // i18n:data
        CrawlListField(ui.listEh, { ui.listEh = it }, 100)
        Text(AppI18n.s("URL 直接下（最稳）；词条走引号短语搜索匹配 → 日文原名作文件名 → ") +
            AppI18n.s("种子优先（需 aria2c）/ 逐页兜底。强制走代理。"),
            color = MUTED, fontSize = 10.sp,
            modifier = Modifier.padding(top = 2.dp, bottom = 4.dp))
    }
    if (ui.kind == "ext") {
        CrawlListFieldTitle("pending_ext" +                                       // i18n:data
            AppI18n.s("（每行一个 URL 或参数行，原样交给外接工具；# 开头为注释）"))
        CrawlListField(ui.listExt, { ui.listExt = it }, 100)
        Text(AppI18n.s("外接下载器：清单行原样交给配置的命令行工具（{url}=行内容、{dest}=暂存目录），产物打包 zip 落收件箱。") +
            AppI18n.s("工具用面板 config.json 里配置的第一个（网页端可选）。"),
            color = MUTED, fontSize = 10.sp,
            modifier = Modifier.padding(top = 2.dp, bottom = 4.dp))
    }
}

@Composable
private fun CrawlListFieldTitle(text: String) {
    Text(text, color = MUTED, fontSize = 12.sp,
        modifier = Modifier.padding(top = 14.dp, bottom = 4.dp))
}

/** 复制词条行：跟随当前任务，直连任务两份清单一起复制。 */
@Composable
private fun CrawlCopyRow(ui: CrawlScreenState, ctx: android.content.Context) {
    Row(Modifier.fillMaxWidth().padding(top = 8.dp),
        verticalAlignment = Alignment.CenterVertically) {
        TextButton(onClick = {
            val text: String
            val label: String
            // label 只用来说「哪份清单」，而清单的名字就是磁盘上的文件名 → 不译（i18n:data）；
            // 只有直连那一支是"描述"而不是文件名，才走 s()。
            when (ui.kind) {
                "wnacg" -> { text = ui.listWnacg; label = "pending_wnacg" }              // i18n:data
                "jm" -> { text = ui.listIndex; label = "pending_index（JM）" }            // i18n:data
                "nh" -> { text = ui.listIndex; label = "pending_index（N站）" }           // i18n:data
                "nhdl" -> { text = ui.listNhdl; label = "pending_nhdl" }           // i18n:data
                "eh" -> { text = ui.listEh; label = "pending_ehdl" }              // i18n:data
                "ext" -> { text = ui.listExt; label = "pending_ext" }             // i18n:data
                else -> {
                    val t = ui.listJmdlT.trim()
                    val i = ui.listJmdlI.trim()
                    text = buildString {
                        if (t.isNotEmpty()) append("【直连词条】\n$t")               // i18n:data 粘贴小标题=格式记号
                        if (t.isNotEmpty() && i.isNotEmpty()) append("\n\n")
                        if (i.isNotEmpty()) append("【直连车号】\n$i")               // i18n:data
                    }
                    label = AppI18n.s("直连清单（词条+车号）")
                }
            }
            if (text.isBlank()) { toast(ctx, AppI18n.sf("%1 为空", label)); return@TextButton }
            val cmb = ctx.getSystemService(android.content.Context.CLIPBOARD_SERVICE)
                    as android.content.ClipboardManager
            cmb.setPrimaryClip(android.content.ClipData.newPlainText("crawl_list", text))
            toast(ctx, AppI18n.sf("%1 已复制", label))
        }) { Text(AppI18n.s("📋 复制词条")) }
        Spacer(Modifier.width(10.dp))
        Text(ui.msg, color = MUTED, fontSize = 11.sp, maxLines = 2)
    }
}

/** 爬虫清单编辑框（等宽字体，与网页端 doc-editor 观感一致） */
@Composable
private fun CrawlListField(value: String, onValue: (String) -> Unit, height: Int) {
    OutlinedTextField(value, onValue,
        modifier = Modifier.fillMaxWidth().height(height.dp),
        colors = appFieldColors(),
        textStyle = androidx.compose.ui.text.TextStyle(
            color = TXT, fontSize = 12.sp, lineHeight = 17.sp,
            fontFamily = FontFamily.Monospace))
}
