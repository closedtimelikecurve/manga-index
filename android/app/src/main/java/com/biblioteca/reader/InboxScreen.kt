package com.biblioteca.reader

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.ExperimentalFoundationApi
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
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/* ================================================================
   APP 3.1.0：收件箱（提案式入库确认）
   3.7.43 从 Screens31.kt 拆出（原 InboxScreen 232 行 / cc 29）：
   屏壳（状态+动作）/ 内容（页头+下拉刷新）/ 半成品横幅 / 列表 /
   收件项长条 / 操作区 / 确认弹窗 各自独立；协程助手提为模块级。
   ================================================================ */

private fun confLabel(c: String): String = when (c) {
    "high" -> AppI18n.s("高置信"); "mid" -> AppI18n.s("中置信"); "low" -> AppI18n.s("低置信")
    "-" -> AppI18n.s("不支持的类型"); else -> c
}

@Composable
@OptIn(ExperimentalFoundationApi::class, androidx.compose.material3.ExperimentalMaterial3Api::class)
fun InboxScreen(offline: Boolean, onOpenInfo: (String) -> Unit = {},
                onOpenReader: (String, String) -> Unit = { _, _ -> },
                onBack: () -> Unit = {},
                // 3.7.12 滚动位置跨返回保留
                listState: LazyListState = LazyListState()) {
    BackHandler { onBack() }
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var items by remember { mutableStateOf<List<Api.InboxItem>>(emptyList()) }
    var parts by remember { mutableStateOf<List<Api.InboxPart>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var busyId by remember { mutableIntStateOf(-1) }
    var purging by remember { mutableStateOf(false) }
    var askConfirm by remember { mutableStateOf<Api.InboxItem?>(null) }
    var confirmCircle by remember { mutableStateOf("") }

    fun reload() {
        loading = true
        loadInbox(scope) { a, b -> items = a; parts = b; loading = false }
    }
    fun act(id: Int, block: suspend () -> String) {
        busyId = id
        inboxAct(scope, ctx, block) { busyId = -1; reload() }
    }
    LaunchedEffect(Unit) { reload() }

    InboxContent(
        offline = offline, items = items, parts = parts, loading = loading,
        busyId = busyId, purging = purging,
        listState = listState,
        onBack = onBack, onOpenReader = onOpenReader, onOpenInfo = onOpenInfo,
        onRefresh = { reload() },
        onConfirmAll = { act(-2) { Api.inboxConfirmAll() } },
        onPurgeParts = { purging = true; purgeInboxParts(scope, ctx) { purging = false; reload() } },
        onAskConfirm = { askConfirm = it; confirmCircle = it.circle },
        onDelete = { act(it.id) { Api.inboxDelete(it.id) } },
        askConfirm = askConfirm, confirmCircle = confirmCircle,
        onCircleChange = { confirmCircle = it },
        onConfirmDismiss = { askConfirm = null },
        onConfirmItem = { item ->
            askConfirm = null
            act(item.id) {
                val (ok, msg) = Api.inboxConfirm(item.id, confirmCircle.trim().ifEmpty { null },
                    force = item.dupName != null)
                msg.ifEmpty { if (ok) AppI18n.s("已入库") else AppI18n.s("已跳过") }
            }
        })
}

/** 收件箱内容：页头 + 离线提示 + 下拉刷新 + 列表/空态 + 确认入库弹窗。 */
@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
private fun InboxContent(offline: Boolean, items: List<Api.InboxItem>, parts: List<Api.InboxPart>,
                         loading: Boolean, busyId: Int, purging: Boolean,
                         listState: LazyListState,
                         onBack: () -> Unit, onOpenReader: (String, String) -> Unit,
                         onOpenInfo: (String) -> Unit, onRefresh: () -> Unit,
                         onConfirmAll: () -> Unit, onPurgeParts: () -> Unit,
                         onAskConfirm: (Api.InboxItem) -> Unit, onDelete: (Api.InboxItem) -> Unit,
                         askConfirm: Api.InboxItem?, confirmCircle: String,
                         onCircleChange: (String) -> Unit, onConfirmDismiss: () -> Unit,
                         onConfirmItem: (Api.InboxItem) -> Unit) {
    // 3.7.12 下拉刷新：任何界面都能下拉（收件箱此前只有操作后隐式刷新）；
    //  spinner 与"数据到达即收尾"同在一处，屏幕只提供 onRefresh。
    //  3.7.66 复位只挂 loading 翻转：每轮 reload 必 true→false，原 LaunchedEffect(items, parts,
    //  loading) 在数据结构相等时不重跑会卡箭头，且 loading=true 那一拍会把刚拉起的箭头立刻藏掉
    var refreshing by remember { mutableStateOf(false) }
    LaunchedEffect(loading) { if (!loading) refreshing = false }
    Column(Modifier.fillMaxSize()) {
        InboxHeader(items.count { it.pending }, loading, offline, onBack, onConfirmAll)
        if (offline) {
            Text(AppI18n.s("📴 离线模式：收件箱操作需要连接服务器"), color = Color(0xFFFFC86B), fontSize = 12.sp,
                modifier = Modifier.padding(horizontal = 14.dp).padding(bottom = 6.dp))
        }
        // 3.7.12 下拉刷新：列表顶部下拉重新拉取收件箱
        androidx.compose.material3.pulltorefresh.PullToRefreshBox(
            isRefreshing = refreshing,
            onRefresh = { refreshing = true; onRefresh() },
            modifier = Modifier.fillMaxSize()
        ) {
            if (items.isEmpty() && !loading) {
                InboxEmptyState()
            } else {
                InboxList(items, parts, loading, offline, busyId, purging, listState,
                    onOpenReader, onOpenInfo, onAskConfirm, onDelete, onPurgeParts)
            }
        }
    }
    askConfirm?.let { item ->
        InboxConfirmDialog(item, confirmCircle, onCircleChange, onConfirmDismiss, onConfirmItem)
    }
}

/** 页头：返回 + 标题 + 「⚡ 一键入库(N)」（离线/加载中/无待定时不可点）。 */
@Composable
private fun InboxHeader(pendingN: Int, loading: Boolean, offline: Boolean,
                        onBack: () -> Unit, onConfirmAll: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("←", color = Color(0xFFF2EEFA), fontSize = 20.sp,
            modifier = Modifier.clickable { onBack() }.padding(end = 10.dp))
        Text(AppI18n.s("📮 收件箱"), color = Color(0xFFF2EEFA), fontSize = 18.sp, modifier = Modifier.weight(1f))
        Text(if (loading) "…" else AppI18n.sf("⚡ 一键入库(%1)", pendingN), color = ACCENT2, fontSize = 13.sp,
            modifier = Modifier.clickable(enabled = !offline && !loading && pendingN > 0) {
                onConfirmAll()
            }.padding(start = 8.dp))
    }
}

/** 空态：收件箱是空的（含来源说明）。 */
@Composable
private fun InboxEmptyState() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text("📮", fontSize = 34.sp)
            Text(AppI18n.s("收件箱是空的——爬虫落盘、手动放入 _app/_inbox/、文库里识别不出词条的作品，\n以及被解散社团的作品都会汇到这里，补全词条后可一键入库。"),
                color = Color(0xFF9A8FB8), fontSize = 12.sp, lineHeight = 18.sp,
                modifier = Modifier.padding(top = 10.dp))
        }
    }
}

/** 列表：半成品横幅 + 收件项长条（3.6.3 起待入库项与被解散作品共用一套流程）。 */
@Composable
private fun InboxList(items: List<Api.InboxItem>, parts: List<Api.InboxPart>, loading: Boolean,
                      offline: Boolean, busyId: Int, purging: Boolean, listState: LazyListState,
                      onOpenReader: (String, String) -> Unit, onOpenInfo: (String) -> Unit,
                      onAskConfirm: (Api.InboxItem) -> Unit, onDelete: (Api.InboxItem) -> Unit,
                      onPurgeParts: () -> Unit) {
    LazyColumn(Modifier.fillMaxSize(), state = listState, contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        // ---- 下载中断的半成品：不是作品、不进收件列表，但堆着会挡住重爬 ----
        if (parts.isNotEmpty()) {
            item(key = "parts-banner") { InboxPartsBanner(parts, purging, offline, onPurgeParts) }
        }
        // 3.6.3「未分类」已取消：待入库项与「文库里识别不出词条/被解散踢出」的作品
        // 汇在同一个 _app/_inbox 里，共用下面这一套待确认列表 + 提案式入库流程。
        if (items.isEmpty() && !loading) {
            item(key = "inbox-empty") {
                Text(AppI18n.s("收件箱是空的"), color = Color(0xFF9A8FB8), fontSize = 12.sp)
            }
        }
        items(items, key = { it.id }) { it ->
            // E 站式长条：左封面缩略图 + 右上信息 + 右下操作
            InboxItemRow(it, offline, busyId, onOpenReader, onOpenInfo, onAskConfirm, onDelete)
        }
    }
}

/** 下载中断半成品横幅：计数 + 清理入口 + 前 3 个文件名（不参与入库判定）。 */
@Composable
private fun InboxPartsBanner(parts: List<Api.InboxPart>, purging: Boolean, offline: Boolean,
                             onPurge: () -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
        .background(Color(0xFF140F22))
        .border(1.dp, Color(0x33FFC86B), RoundedCornerShape(12.dp))
        .padding(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(AppI18n.sf("🧹 %1 个下载中断的半成品", parts.size), color = Color(0xFFF2EEFA),
                fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f))
            Text(if (purging) AppI18n.s("清理中…") else AppI18n.s("清理"), color = Color(0xFFFF6B8B),
                fontSize = 13.sp,
                modifier = Modifier.clickable(enabled = !offline && !purging) { onPurge() })
        }
        Text(AppI18n.sf("共 %1 · 最新 %2 小时前 · 不参与入库判定，清理后爬虫会重新下载",
            fmtBytesShelf(parts.sumOf { it.size }), String.format("%.1f", parts.first().ageH)),
            color = Color(0xFF6E6787), fontSize = 11.sp, lineHeight = 15.sp,
            modifier = Modifier.padding(top = 4.dp))
        parts.take(3).forEach {
            Text(it.name, color = Color(0xFF9A8FB8), fontSize = 10.sp,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}

/**
 * 收件项长条（E 站式）：左封面缩略图 + 右上信息 + 右下操作。
 * 3.7.43 从 InboxScreen 的 items() lambda 拆出（原函数 232 行的最大一块）。
 */
@Composable
private fun InboxItemRow(it: Api.InboxItem, offline: Boolean, busyId: Int,
                         onOpenReader: (String, String) -> Unit, onOpenInfo: (String) -> Unit,
                         onAskConfirm: (Api.InboxItem) -> Unit, onDelete: (Api.InboxItem) -> Unit) {
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
        .background(Color(0xFF140F22)).padding(10.dp)) {
        Box(Modifier.width(92.dp).aspectRatio(3f / 4f)
            .clip(RoundedCornerShape(8.dp)).background(Color(0xFF1C1433)),
            contentAlignment = Alignment.Center) {
            if (it.exists && it.kind == "archive") {
                AsyncImage(model = Api.coverUrl("收件箱", it.id.toString()),   // i18n:data 收件箱=真实社团名
                    contentDescription = it.name, contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize())
            } else Text("📄", fontSize = 22.sp)
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(it.name, color = Color(0xFFF2EEFA), fontSize = 13.sp,
                fontWeight = FontWeight.SemiBold, maxLines = 3,
                overflow = TextOverflow.Ellipsis)
            Row(Modifier.padding(top = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text(fmtBytesShelf(it.size) + " · " + confLabel(it.confidence),
                    color = Color(0xFF9A8FB8), fontSize = 10.sp)
                if (it.dupName != null)
                    Text(AppI18n.s("⚠ 疑似重复"), color = Color(0xFFFF6B8B), fontSize = 10.sp)
                if (it.state == "confirmed")
                    Text(AppI18n.s("已入库"), color = Color(0xFF9A8FB8), fontSize = 10.sp)
                if (!it.exists)
                    Text(AppI18n.s("文件已消失"), color = Color(0xFFFFC86B), fontSize = 10.sp)
            }
            if (it.kind == "archive") {
                val dest = when {
                    it.circle.isNotEmpty() -> AppI18n.sf("归档到「%1」", it.circle)
                    it.bare.isNotEmpty() -> AppI18n.sf("按待定词条「%1」新建档案", it.bare)
                    else -> AppI18n.s("未识别出社团，需人工指定")
                }
                Text(dest +
                        if (it.newName.isNotEmpty() && it.newName != it.name) AppI18n.sf(" · 规范化名：%1", it.newName) else "",
                    color = Color(0xFF6E6787), fontSize = 11.sp, lineHeight = 15.sp,
                    modifier = Modifier.padding(top = 4.dp))
            }
            if (it.pending && it.kind == "archive" && !offline) {
                InboxItemActions(it, busyId, offline, onOpenReader, onOpenInfo, onAskConfirm, onDelete)
            }
        }
    }
}

/** 收件项操作区：📖 阅读 / ✏ 增补信息 / ✓ 确认入库（仍要入库）/ 🗑 删除。 */
@Composable
private fun InboxItemActions(it: Api.InboxItem, busyId: Int, offline: Boolean,
                             onOpenReader: (String, String) -> Unit, onOpenInfo: (String) -> Unit,
                             onAskConfirm: (Api.InboxItem) -> Unit, onDelete: (Api.InboxItem) -> Unit) {
    Row(Modifier.padding(top = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        // 3.4.2 先读后入库：阅读器打开收件项（伪社团「收件箱」/ 收件项id）
        Text(AppI18n.s("📖 阅读"), color = Color(0xFF8FD0F2), fontSize = 12.sp,
            modifier = Modifier.clip(RoundedCornerShape(999.dp))
                .background(Color(0x1AFFFFFF))
                .clickable(enabled = !offline) { onOpenReader("收件箱", it.id.toString()) }   // i18n:data 收件箱=真实社团名
                .padding(horizontal = 12.dp, vertical = 6.dp))
        // 补全词条：名字不可识别时用它把 [社团 (画师)] 补上，再确认入库
        Text(AppI18n.s("✏ 增补信息"), color = Color(0xFFC9A6FF), fontSize = 12.sp,
            modifier = Modifier.clip(RoundedCornerShape(999.dp))
                .background(Color(0x1AFFFFFF))
                .clickable(enabled = !offline) { onOpenInfo(it.id.toString()) }
                .padding(horizontal = 12.dp, vertical = 6.dp))
    }
    Row(Modifier.padding(top = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(if (it.dupName != null) AppI18n.s("仍要入库") else AppI18n.s("✓ 确认入库"),
            color = Color(0xFF1C1433), fontSize = 12.sp,
            modifier = Modifier.clip(RoundedCornerShape(999.dp))
                .background(ACCENT2)
                .clickable(enabled = busyId < 0) { onAskConfirm(it) }
                .padding(horizontal = 12.dp, vertical = 6.dp))
        Text(AppI18n.s("🗑 删除"), color = Color(0xFFFF6B8B), fontSize = 12.sp,
            modifier = Modifier.clip(RoundedCornerShape(999.dp))
                .background(Color(0x1AFFFFFF))
                .clickable(enabled = busyId < 0) { onDelete(it) }
                .padding(horizontal = 12.dp, vertical = 6.dp))
    }
}

/** 确认入库弹窗：显示候选名/重复警示 + 目标社团输入（识别不出词条时必填）。 */
@Composable
private fun InboxConfirmDialog(item: Api.InboxItem, circle: String,
                               onCircleChange: (String) -> Unit,
                               onDismiss: () -> Unit, onConfirm: (Api.InboxItem) -> Unit) {
    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(AppI18n.s("确认入库")) },
        text = {
            Column {
                Text(item.name, fontSize = 12.sp, color = Color(0xFF9A8FB8),
                    modifier = Modifier.padding(bottom = 8.dp))
                if (item.dupName != null) {
                    Text(AppI18n.sf("⚠ 库内/队列已有同内容：%1", item.dupName), color = Color(0xFFFF6B8B),
                        fontSize = 11.sp, modifier = Modifier.padding(bottom = 8.dp))
                }
                OutlinedTextField(circle, onCircleChange, singleLine = true,
                    label = { Text(AppI18n.s("目标社团（可改；识别不出词条时必填）")) })
            }
        },
        confirmButton = {
            androidx.compose.material3.TextButton(onClick = { onConfirm(item) }) {
                Text(AppI18n.s("确认"), color = ACCENT2)
            }
        },
        dismissButton = {
            androidx.compose.material3.TextButton(onClick = onDismiss) { Text(AppI18n.s("取消")) }
        }
    )
}

/** 拉取收件箱快照（3.7.43 提为模块级，原 InboxScreen 局部函数 reload 的主体）。 */
private fun loadInbox(scope: CoroutineScope,
                      onLoaded: (List<Api.InboxItem>, List<Api.InboxPart>) -> Unit) {
    scope.launch {
        val snap = try { withContext(Dispatchers.IO) { Api.inboxList() } } catch (_: Exception) { null }
        onLoaded(snap?.items ?: emptyList(), snap?.parts ?: emptyList())
    }
}

/** 清理下载中断半成品（toast 结果后回调重载）。 */
private fun purgeInboxParts(scope: CoroutineScope, ctx: android.content.Context, onDone: () -> Unit) {
    scope.launch {
        val msg = try { withContext(Dispatchers.IO) { Api.inboxPurgeParts() } }
                  catch (e: Exception) { AppI18n.sf("清理失败：%1", e.message ?: "") }
        android.widget.Toast.makeText(ctx, msg, android.widget.Toast.LENGTH_SHORT).show()
        onDone()
    }
}

/** 收件箱动作通用外壳：跑 suspend 块 → toast 结果 → 回调收尾（busyId 由调用方管）。 */
private fun inboxAct(scope: CoroutineScope, ctx: android.content.Context,
                     block: suspend () -> String, onDone: () -> Unit) {
    scope.launch {
        val msg = try { withContext(Dispatchers.IO) { block() } }
                  catch (e: Exception) { AppI18n.sf("失败：%1", e.message) }
        android.widget.Toast.makeText(ctx, msg, android.widget.Toast.LENGTH_SHORT).show()
        onDone()
    }
}
