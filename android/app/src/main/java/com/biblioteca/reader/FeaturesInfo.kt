package com.biblioteca.reader

import android.content.Context
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



/* ---------------- 增补信息页（表单 → /api/supplement-info 重组文件名并归档） ---------------- */
/** 解析出的增补信息（3.7.46 改为单状态对象，避免 InfoScreen 内 11 个独立 var 撑爆行数）。 */
private data class InfoData(val file: String = "", val base: String = "",
                            val uncensored: Boolean = false, val event: String = "",
                            val circle: String = "", val personal: String = "",
                            val title: String = "", val original: String = "",
                            val translator: String = "", val otherInfo: String = "")

@Composable
fun InfoScreen(group: String, work: String, onBack: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var loading by remember { mutableStateOf(true) }
    var saving by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf("") }
    var info by remember { mutableStateOf(InfoData()) }   // 解析出的词条（单状态）
    var mode by remember { mutableStateOf("fields") }     // 'fields' 逐字段 | 'title' 整标题
    var fullTitle by remember { mutableStateOf("") }

    LaunchedEffect(group, work) {
        try {
            val i = withContext(Dispatchers.IO) { Api.parseInfo(group, work) }
            info = InfoData(i.file, i.base, i.uncensored, i.event, i.circle,
                i.personal, i.title, i.original, i.translator, i.otherInfo)
            fullTitle = i.base.ifEmpty { i.file }     // 整标题模式：预填当前文件名（不含扩展名）
        } catch (e: Exception) {
            error = AppI18n.sf("解析失败：%1", e.message)
        }
        loading = false
    }

    BackHandlerOn(onBack)
    Column(Modifier.fillMaxSize()) {
        TopBar(AppI18n.s("✏ 增补信息"), onBack)
        if (loading) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = ACCENT)
            }
        } else {
            InfoForm(mode, fullTitle, error, saving, info.file,
                fields = InfoFields(info.uncensored, info.event, info.circle, info.personal,
                    info.title, info.original, info.translator, info.otherInfo),
                onMode = { mode = it; error = "" },
                onFullTitle = { fullTitle = it },
                onFields = { f -> info = info.copy(uncensored = f.uncensored, event = f.event,
                    circle = f.circle, personal = f.personal, title = f.title,
                    original = f.original, translator = f.translator, otherInfo = f.otherInfo) },
                onSave = { doInfoSave(scope, ctx, group, work, mode, fullTitle, info,
                    { saving = it }, { error = it }, onBack) })
        }
    }
}

/** 增补信息保存（3.7.46 从 InfoScreen 抽出的嵌套 save）：整标题走服务端解析，逐字段走词条重组。 */
private fun doInfoSave(scope: CoroutineScope, ctx: android.content.Context,
                       group: String, work: String, mode: String, fullTitle: String,
                       info: InfoData, onSaving: (Boolean) -> Unit,
                       onError: (String) -> Unit, onBack: () -> Unit) {
    if (mode == "title") {                       // 整标题：整串交给服务端解析 → 规范化 → 归档
        if (fullTitle.isBlank()) { onError(AppI18n.s("请输入完整标题")); return }
        onSaving(true); onError("")
        saveByTitle(scope, ctx, group, work, fullTitle.trim(), onBack, onError)
        return
    }
    if (info.title.isBlank()) { onError(AppI18n.s("请至少填写名称")); return }
    onSaving(true); onError("")
    saveByFields(scope, ctx, group, work,
        Api.SupplementFields(info.uncensored, info.event, info.circle, info.personal,
            info.title, info.original, info.translator, info.otherInfo),
        onBack, onError)
}

/** 增补信息表单状态（3.7.43：逐字段模式的九个字段打包，避免十八个参数）。 */
private data class InfoFields(val uncensored: Boolean, val event: String, val circle: String,
                              val personal: String, val title: String, val original: String,
                              val translator: String, val otherInfo: String)

/**
 * 增补信息表单（3.7.43 从 InfoScreen 拆出）：模式切换 + 逐字段/整标题两种录入 +
 * 错误 + 保存按钮。
 */
@Composable
private fun InfoForm(mode: String, fullTitle: String, error: String, saving: Boolean,
                     curFile: String, fields: InfoFields, onMode: (String) -> Unit,
                     onFullTitle: (String) -> Unit, onFields: (InfoFields) -> Unit,
                     onSave: () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp)) {
        Text(AppI18n.sf("当前文件：%1", curFile), color = MUTED, fontSize = 11.sp,
            modifier = Modifier.padding(bottom = 10.dp))
        // ---- 模式切换：逐字段 ↔ 整标题 ----
        InfoModeChips(mode, onMode)
        if (mode == "fields") {
            InfoFieldList(fields, onFields)
        } else {
            InfoTitleMode(fullTitle, onFullTitle)
        }
        if (error.isNotEmpty()) {
            Text(error, color = ERR, fontSize = 12.sp,
                modifier = Modifier.padding(top = 8.dp))
        }
        Text(if (mode == "title")
            AppI18n.s("整标题模式：整串粘贴完整标题，程序自动判定各部分词条并归档到对应社团。")
            else AppI18n.s("留空的字段自动沿用文件名解析值；保存后按词条重组文件名并归档到对应社团。"),
            color = MUTED, fontSize = 11.sp, modifier = Modifier.padding(top = 10.dp))
        Button(onClick = onSave, enabled = !saving,
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp)) {
            Text(if (saving) "保存中…" else if (mode == "title") AppI18n.s(AppI18n.s(AppI18n.s(AppI18n.s(AppI18n.s(AppI18n.s("解析并归档")))))) else AppI18n.s(AppI18n.s(AppI18n.s(AppI18n.s(AppI18n.s(AppI18n.s("保存并归档")))))))
        }
    }
}

/** 模式切换 chips（逐字段 ↔ 整标题）。 */
@Composable
private fun InfoModeChips(mode: String, onMode: (String) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(bottom = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        listOf("fields" to AppI18n.s("逐字段"), "title" to AppI18n.s("整标题")).forEach { (m, label) ->
            val selected = mode == m
            Text(label, color = if (selected) TXT else MUTED, fontSize = 12.sp,
                textAlign = TextAlign.Center,
                modifier = Modifier.weight(1f)
                    .clip(RoundedCornerShape(999.dp))
                    .background(if (selected) ACCENT.copy(alpha = 0x33 / 255f) else CARD_BG2)
                    .border(1.dp, if (selected) ACCENT else Color(0x24FFFFFF),
                        RoundedCornerShape(999.dp))
                    .clickable { onMode(m) }
                    .padding(horizontal = 10.dp, vertical = 8.dp))
        }
    }
}

/** 逐字段录入区（3.7.43 拆出）：無修正勾选 + 八个词条字段。 */
@Composable
private fun InfoFieldList(f: InfoFields, onFields: (InfoFields) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Checkbox(checked = f.uncensored, onCheckedChange = { onFields(f.copy(uncensored = it)) },
            colors = CheckboxDefaults.colors(checkedColor = ACCENT,
                checkmarkColor = Color(0xFF140F22)))
        Text(AppI18n.s("無修正（无修正）"), color = TXT, fontSize = 14.sp)
    }
    InfoField(AppI18n.s("展会（如 C102）"), f.event) { onFields(f.copy(event = it)) }
    InfoField(AppI18n.s("社团名"), f.circle) { onFields(f.copy(circle = it)) }
    InfoField(AppI18n.s("个人名"), f.personal) { onFields(f.copy(personal = it)) }
    InfoField(AppI18n.s("名称（必填）"), f.title) { onFields(f.copy(title = it)) }
    InfoField(AppI18n.s("同人名"), f.original) { onFields(f.copy(original = it)) }
    InfoField(AppI18n.s("汉化组（多个用空格分隔）"), f.translator) { onFields(f.copy(translator = it)) }
    InfoField(AppI18n.s("其他信息（整标题里其余内容，空格分隔）"), f.otherInfo) { onFields(f.copy(otherInfo = it)) }
}

/** 整标题录入区（3.7.43 拆出）：整串粘贴 + 词条规则说明。 */
@Composable
private fun InfoTitleMode(fullTitle: String, onFullTitle: (String) -> Unit) {
    OutlinedTextField(fullTitle, onFullTitle,
        label = { Text(AppI18n.s("完整标题（整串粘贴，程序自动判定词条）")) },
        colors = appFieldColors(),
        textStyle = TextStyle(
            color = TXT, fontSize = 13.sp, lineHeight = 19.sp),
        modifier = Modifier.fillMaxWidth().height(130.dp))
    Text(AppI18n.s("例：[社团 (画师)] 作品名 (C102) (同人) 【汉化组】\n") +
        AppI18n.s("程序自动拆出 社团 / 画师 / 展会 / 同人 / 汉化组 / 待定词条 各段，") +
        AppI18n.s("标准化命名后自动归档到解析出的社团（识别不出社团则按规范名留在收件箱）；") +
        AppI18n.s("括号会自动纠错：嵌套 [[…]]、重复词条、空括号都会被收敛。"),
        color = MUTED, fontSize = 11.sp, lineHeight = 17.sp,
        modifier = Modifier.padding(top = 8.dp))
}

/** 整标题模式保存（3.7.43 提为模块级）：整串交给服务端解析 → 规范化 → 归档。 */
private fun saveByTitle(scope: CoroutineScope, ctx: android.content.Context,
                        group: String, work: String, fullTitle: String,
                        onBack: () -> Unit, onError: (String) -> Unit) {
    scope.launch {
        try {
            val msg = withContext(Dispatchers.IO) { Api.supplementTitle(group, work, fullTitle) }
            android.widget.Toast.makeText(ctx, msg, android.widget.Toast.LENGTH_LONG).show()
            onBack()
        } catch (e: Exception) {
            onError(AppI18n.sf("归档失败：%1", e.message))
        }
    }
}

/** 逐字段模式保存（3.7.43 提为模块级）：按词条重组文件名并归档。 */
private fun saveByFields(scope: CoroutineScope, ctx: android.content.Context,
                         group: String, work: String, f: Api.SupplementFields,
                         onBack: () -> Unit, onError: (String) -> Unit) {
    scope.launch {
        try {
            val msg = withContext(Dispatchers.IO) { Api.supplementInfo(group, work, f) }
            android.widget.Toast.makeText(ctx, msg, android.widget.Toast.LENGTH_SHORT).show()
            onBack()
        } catch (e: Exception) {
            onError(AppI18n.sf("保存失败：%1", e.message))
        }
    }
}

@Composable
private fun InfoField(label: String, value: String, onChange: (String) -> Unit) {
    OutlinedTextField(value, onChange, label = { Text(label) }, singleLine = true,
        colors = appFieldColors(),
        modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp))
}

/* ---------------- 词条黑名单页 ---------------- */
@Composable
fun BlacklistScreen(onBack: () -> Unit, onSaved: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var loading by remember { mutableStateOf(true) }
    var saving by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf("") }
    var builtin by remember { mutableStateOf(listOf<String>()) }
    var custom by remember { mutableStateOf("") }
    var exempt by remember { mutableStateOf("") }

    LaunchedEffect(Unit) {
        try {
            val (b, c, e) = withContext(Dispatchers.IO) { Api.blacklistGet() }
            builtin = b; custom = c.joinToString("\n"); exempt = e.joinToString("\n")
        } catch (e: Exception) {
            error = e.message ?: e.toString()
        }
        loading = false
    }

    BackHandlerOn(onBack)
    Column(Modifier.fillMaxSize()) {
        TopBar(AppI18n.s("🚫 词条黑名单"), onBack)
        when {
            loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = ACCENT2)
            }
            error.isNotEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(AppI18n.sf("加载失败：%1", error), color = Color(0xFFFF5ED0), fontSize = 13.sp)
            }
            else -> BlacklistForm(builtin, custom, exempt, saving,
                onCustom = { custom = it }, onExempt = { exempt = it },
                onSave = { saveBlacklist(scope, ctx, custom, exempt, { saving = it }, onSaved) })
        }
    }
}

/** 黑名单表单（3.7.43 从 BlacklistScreen 拆出）：内置展示 + 两个多行输入 + 保存。 */
@Composable
private fun BlacklistForm(builtin: List<String>, custom: String, exempt: String,
                          saving: Boolean, onCustom: (String) -> Unit, onExempt: (String) -> Unit,
                          onSave: () -> Unit) {
    Column(Modifier.fillMaxSize()
        .verticalScroll(rememberScrollState())
        .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Text(AppI18n.s("内置（不可删）：") + builtin.joinToString("、"),
            color = Color(0xFF9A8FB8), fontSize = 12.sp)
        Text(AppI18n.s("自定义黑名单（每行一条，子串命中、不区分大小写）"),
            color = Color(0xFFF2EEFA), fontSize = 13.sp)
        OutlinedTextField(custom, onCustom, modifier = Modifier.fillMaxWidth(),
            minLines = 4, colors = appFieldColors(),
            placeholder = { Text(AppI18n.s("每行一条"), color = Color(0xFF6B5F8A)) })
        Text(AppI18n.s("豁免名单（命中豁免的词条即使撞上黑名单也照常采纳，如 Digital Lover）"),
            color = Color(0xFFF2EEFA), fontSize = 13.sp)
        OutlinedTextField(exempt, onExempt, modifier = Modifier.fillMaxWidth(),
            minLines = 3, colors = appFieldColors(),
            placeholder = { Text(AppI18n.s("每行一条"), color = Color(0xFF6B5F8A)) })
        Button(onClick = onSave, enabled = !saving, modifier = Modifier.fillMaxWidth()) {
            Text(if (saving) AppI18n.s("保存中…") else AppI18n.s("保存（保存后自动重扫生效）"))
        }
    }
}

/** 保存词条黑名单（3.7.48 从 BlacklistScreen 的 onSave 抽出）。 */
private fun saveBlacklist(scope: CoroutineScope, ctx: Context, custom: String, exempt: String,
                          onSaving: (Boolean) -> Unit, onSaved: () -> Unit) {
    onSaving(true)
    scope.launch {
        try {
            val cList = custom.split("\n").map { it.trim() }.filter { it.isNotBlank() }
            val eList = exempt.split("\n").map { it.trim() }.filter { it.isNotBlank() }
            val msg = withContext(Dispatchers.IO) { Api.blacklistSave(cList, eList) }
            android.widget.Toast.makeText(ctx, msg, android.widget.Toast.LENGTH_SHORT).show()
            onSaved()
        } catch (e: Exception) {
            android.widget.Toast.makeText(ctx, AppI18n.sf("保存失败：%1", e.message), android.widget.Toast.LENGTH_SHORT).show()
        }
        onSaving(false)
    }
}
