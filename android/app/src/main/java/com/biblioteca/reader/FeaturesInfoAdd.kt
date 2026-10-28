package com.biblioteca.reader

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
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
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.DialogProperties
import coil.compose.AsyncImage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/* ================================================================
   信息与表单族（3.7.43 从 Features.kt 拆出）：
   AddWorksDialog（分区内添加作品）/ BlacklistScreen（词条黑名单）/
   InfoScreen（增补信息）。
   ================================================================ */

/** 作品 key（与后端 _find_work_by_key 同规则："社团/作品名"）。 */
private fun workKey(h: Api.WorkHit): String = h.group + "/" + h.work.name

/**
 * 3.6.36 #33：分区内手动添加作品对话框。
 * 作品有明确原作、但文件名没有对应词条导致解析器识别不了时，在此搜索库内作品
 * （全局搜索：名称/社团/标签），勾选后写进该分区的 original 标签。
 */
@Composable
fun AddWorksDialog(zone: String, onDismiss: () -> Unit, onAdded: () -> Unit) {
    val scope = rememberCoroutineScope()
    var selected by remember { mutableStateOf<Set<String>>(emptySet()) }
    var saving by remember { mutableStateOf(false) }
    var msg by remember { mutableStateOf("") }

    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        // 3.6.39 #33：放宽对话框——横条卡片需要宽度；默认 280dp 只能挤成一列文字
        properties = DialogProperties(usePlatformDefaultWidth = false),
        modifier = Modifier.fillMaxWidth(0.94f),
        title = { Text(AppI18n.sf("添加到「%1」", zone), color = TXT, fontSize = 16.sp) },
        text = {
            Column {
                Text(AppI18n.s("搜索库内作品（名称/社团/标签），勾选后加入本分区。")
                    + AppI18n.s("只写标签，不移动文件、不影响进度与收藏。"),
                    color = MUTED, fontSize = 10.sp, lineHeight = 14.sp)
                AddWorksSearch(zone, selected, msg, onMsg = { msg = it }) { k ->
                    selected = if (k in selected) selected - k else selected + k
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                if (selected.isEmpty()) { msg = AppI18n.s("先勾选作品"); return@TextButton }
                saving = true
                scope.launch {
                    try {
                        val r = withContext(Dispatchers.IO) { Api.originalsAddWorks(zone, selected.toList()) }
                        if (r.optBoolean("ok")) onAdded()
                        else { msg = r.optString("message").ifEmpty { AppI18n.s("添加失败") }; saving = false }
                    } catch (e: Exception) {
                        msg = AppI18n.sf("添加失败：%1", e.message); saving = false
                    }
                }
            }, enabled = !saving && selected.isNotEmpty()) {
                Text(AppI18n.sf("添加（%1）", selected.size), color = ACCENT2)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(AppI18n.s("取消"), color = MUTED) }
        }
    )
}

/**
 * 添加作品对话框的搜索区（3.7.43 从 AddWorksDialog 拆出）：
 * 自有 q/results/searching/inZone 状态；msg 由父级持有（确认按钮的报错也显示在这里）。
 */
@Composable
private fun AddWorksSearch(zone: String, selected: Set<String>, msg: String,
                           onMsg: (String) -> Unit, onToggle: (String) -> Unit) {
    var q by remember { mutableStateOf("") }
    var results by remember { mutableStateOf<List<Api.WorkHit>>(emptyList()) }
    var searching by remember { mutableStateOf(false) }
    // 3.6.41：已经在**本分区**的作品不该再出现在候选里（用户报障"明明已在区内的
    // 作品也在名单内部"）。打开对话框时先拉一次本区作品，按同一 key 规则排除。
    var inZone by remember { mutableStateOf<Set<String>?>(null) }
    LaunchedEffect(zone) {
        inZone = try {
            withContext(Dispatchers.IO) { Api.tagWorks("original", zone) }
                .map { workKey(it) }.toSet()
        } catch (_: Exception) { emptySet() }
    }
    // 防抖搜索（400ms）：全局搜索 → 作品候选（排除已在本区的）
    LaunchedEffect(q, inZone) {
        if (q.isBlank()) { results = emptyList(); return@LaunchedEffect }
        searching = true
        searchWorksToAdd(q.trim(), inZone.orEmpty()) { ws, m ->
            results = ws; onMsg(m); searching = false
        }
    }
    OutlinedTextField(value = q, onValueChange = { q = it },
        label = { Text(AppI18n.s("搜索作品")) }, singleLine = true,
        colors = appFieldColors(),
        modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
    if (msg.isNotEmpty()) {
        Text(msg, color = ERR, fontSize = 11.sp,
            modifier = Modifier.padding(top = 4.dp))
    }
    if (searching) {
        CircularProgressIndicator(color = ACCENT, strokeWidth = 2.dp,
            modifier = Modifier.padding(top = 10.dp).width(18.dp).height(18.dp))
    }
    // 3.6.39 #33：改成收件箱(InboxScreen)那种横条卡片——左封面缩略图 + 右信息。
    // 此前是纯文字勾选行，只看得到作品名和社团，用户反馈"只能显示一小半信息、
    // 而且基本都是作者信息"。卡片比收件箱更小（封面 42dp），一屏能看 5~6 部。
    LazyColumn(Modifier.fillMaxWidth().heightIn(max = 400.dp).padding(top = 8.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp)) {
        items(results, key = { workKey(it) }) { h ->
            val k = workKey(h)
            AddWorksRow(h, k in selected) { onToggle(k) }
        }
    }
}

/**
 * 防抖搜索库内作品候选项（3.7.43 提为模块级 suspend 函数）：
 * 400ms 防抖 + 排除已在本区作品 + 结果文案（全部已在本区时给提示）。
 */
private suspend fun searchWorksToAdd(q: String, inZone: Set<String>,
                                     onResults: (List<Api.WorkHit>, String) -> Unit) {
    delay(400)
    try {
        val (_g, works, _a) = withContext(Dispatchers.IO) { Api.search(q) }
        val filtered = works.filter { workKey(it) !in inZone }
        val msg = if (works.isNotEmpty() && filtered.isEmpty())
            AppI18n.sf("搜到的 %1 部都已在本分区内", works.size) else ""
        onResults(filtered, msg)
    } catch (e: Exception) {
        onResults(emptyList(), AppI18n.sf("搜索失败：%1", e.message))
    }
}

/** 添加作品候选行（3.7.43 拆出）：左封面缩略图 + 右信息 + 勾选框。 */
@Composable
private fun AddWorksRow(h: Api.WorkHit, on: Boolean, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth()
        .clip(RoundedCornerShape(10.dp))
        .background(if (on) ACCENT.copy(alpha = 0x22 / 255f) else CARD_BG2)
        .border(1.dp, if (on) ACCENT else Color(0x1FFFFFFF),
            RoundedCornerShape(10.dp))
        .clickable { onClick() }
        .padding(6.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.width(42.dp).aspectRatio(3f / 4f)
            .clip(RoundedCornerShape(6.dp)).background(Color(0xFF1C1433)),
            contentAlignment = Alignment.Center) {
            if (h.work.hasCover) {
                AsyncImage(
                    model = Api.coverUrl(h.group, h.work.name, h.work.ver),
                    contentDescription = h.work.name,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize())
            } else Text("📄", fontSize = 14.sp)
        }
        Spacer(Modifier.width(8.dp))
        Column(Modifier.weight(1f)) {
            Text(h.work.name.dispWorkName(), color = TXT, fontSize = 11.sp,
                lineHeight = 14.sp, maxLines = 2,
                overflow = TextOverflow.Ellipsis)
            Row(Modifier.padding(top = 2.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text("🏢 " + h.group.ifEmpty {
                    h.work.circle.ifEmpty { AppI18n.s("未知社团") }
                }, color = MUTED, fontSize = 9.sp, maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false))
                h.work.authors.firstOrNull()?.let { a ->
                    Text("👤 " + a, color = ACCENT2,
                        fontSize = 9.sp, maxLines = 1,
                        overflow = TextOverflow.Ellipsis)
                }
            }
            h.work.originals.firstOrNull()?.let { o ->
                Text("🎴 " + o, color = Color(0xFFC9A6FF), fontSize = 9.sp,
                    maxLines = 1, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 2.dp))
            }
        }
        Text(if (on) "☑" else "☐",
            color = if (on) ACCENT else MUTED, fontSize = 15.sp,
            modifier = Modifier.padding(start = 6.dp, end = 2.dp))
    }
}