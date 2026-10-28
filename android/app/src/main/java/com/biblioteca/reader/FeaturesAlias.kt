package com.biblioteca.reader

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/* ================================================================
   别名登记族（3.7.43 从 Features.kt 拆出）：
   3.6.11 别名登记页——原「🧰 维护」页（备份恢复 / 笔名别名 / 本机路径导入）
   已收窄：**维护只在面板（本地）进行**，移动端只保留别名登记，并**扩展到社团名**：
   * 笔名别名（kind=author）：同一画师的多个笔名归并到正名（作者字段/标签随重扫归并）；
   * 社团别名（kind=circle）：被登记为别名的社团不再单列，其作品并入正名社团——
     文件不移动、作品 key 不变（阅读进度/收藏不受影响），删除别名即可撤销。
   * 原作别名（kind=original，3.7.53）：**正名 = 原作分区名**。原作名不在文件名里，
     分区名就是 DB 里的 original 标签，因此"改正名"直接走 `/api/originals/rename`
     （零文件操作），旧正名由服务端自动并入别名、既有别名改指向新正名。
   登记/删除/改名都会触发服务端重扫 → onChanged 通知外层缓存失效。
   ================================================================ */
@Composable
fun AliasScreen(onBack: () -> Unit, onChanged: () -> Unit) {
    val ctx = LocalContext.current
    var kind by remember { mutableStateOf("author") }   // author 笔名 | circle 社团 | original 原作（3.6.19）

    BackHandlerOn(onBack)
    Column(Modifier.fillMaxSize()) {
        TopBar(AppI18n.s("🔗 别名登记"), onBack)
        AliasKindRow(kind) { kind = it }
        AliasTab(kind, { toast(ctx, it) }, onChanged)
    }
}

/** 别名类型 chips 行（笔名 / 社团 / 原作，3.7.43 拆出）。 */
@Composable
private fun AliasKindRow(kind: String, onKind: (String) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        listOf("author" to AppI18n.s("👤 笔名别名"), "circle" to AppI18n.s("🏢 社团别名"),
               "original" to AppI18n.s("🎴 同人别名"))
            .forEach { (m, label) ->
                val selected = kind == m
                Text(label, color = if (selected) TXT else MUTED, fontSize = 12.sp,
                    maxLines = 1,
                    modifier = Modifier
                        .clip(RoundedCornerShape(999.dp))
                        .background(if (selected) ACCENT.copy(alpha = 0x33 / 255f) else CARD_BG2)
                        .border(1.dp, if (selected) ACCENT else Color(0x24FFFFFF),
                            RoundedCornerShape(999.dp))
                        .clickable { onKind(m) }
                        .padding(horizontal = 10.dp, vertical = 7.dp))
            }
    }
}

/**
 * 别名页的提交与弹窗状态（3.7.53 从 `AliasTab` 抽出）。
 *
 * 为什么是普通类：`AliasTab` 已经在 50 行预算边缘，再塞进"改名"这条链路必然超限；
 * 闸门把嵌套 fun 也算在父函数里，所以把状态与动作放到类里、composable 只做接线。
 * 状态本身仍走 `mutableStateOf`，Compose 读得到（与 `AppState` 同一套做法）。
 */
private class AliasPanel(
    private val scope: CoroutineScope,
    private val kind: String,
    private val toast: (String) -> Unit,
    private val onChanged: () -> Unit,
) {
    var aliases by mutableStateOf<Map<String, String>?>(null)
    var err by mutableStateOf("")
    var busy by mutableStateOf(false)
    var msg by mutableStateOf("")
    var addCanon by mutableStateOf<String?>(null)      // null=关闭；""=登记新正名
    var renameFrom by mutableStateOf<String?>(null)    // null=关闭；否则=要改名的原作正名

    fun reload() {
        scope.launch {
            try {
                aliases = withContext(Dispatchers.IO) { Api.aliasList(kind) }
                err = ""
            } catch (e: Exception) { err = e.message ?: e.toString() }
        }
    }

    fun openAdd(canon: String) { addCanon = canon; msg = "" }

    fun openRename(canon: String) { renameFrom = canon; msg = "" }

    fun dismiss() { addCanon = null; renameFrom = null; msg = "" }

    /** 登记别名（alias → canon），成功后刷新树并通知外层失效缓存。 */
    fun submitAdd(alias: String, canon: String) {
        if (alias.isBlank() || canon.isBlank()) { msg = AppI18n.s("别名与正名都必须非空"); return }
        busy = true
        scope.launch {
            try { finish(withContext(Dispatchers.IO) { Api.aliasAdd(alias, canon, kind) }) }
            catch (e: Exception) { msg = AppI18n.sf("登记失败：%1", e.message) }
            busy = false
        }
    }

    /** 改原作正名 = 改原作区名（3.7.53）：零文件操作，旧正名由服务端自动登记为别名，
     *  既有别名一并改指向新正名（`_originals_relink_aliases`），所以这里固定带 keep_alias。 */
    fun submitRename(to: String) {
        val from = renameFrom ?: return
        if (to.isBlank()) { msg = AppI18n.s("新的同人区名不能为空"); return }
        if (to == from) { dismiss(); return }
        busy = true
        scope.launch {
            try {
                val j = withContext(Dispatchers.IO) { Api.originalsRename(from, to, keepAlias = true) }
                finish(j.optString("message", AppI18n.s("已改名")))
            } catch (e: Exception) { msg = AppI18n.sf("改名失败：%1", e.message) }
            busy = false
        }
    }

    /** 删除一条别名（保留 3.7.43 的重扫与提示行为）。 */
    fun delete(alias: String) {
        scope.launch {
            try { finish(withContext(Dispatchers.IO) { Api.aliasDelete(alias, kind) }) }
            catch (e: Exception) { toast(AppI18n.sf("删除失败：%1", e.message)) }
        }
    }

    private fun finish(message: String) {
        toast(message); dismiss(); reload(); onChanged()
    }
}

@Composable
private fun AliasTab(kind: String, toast: (String) -> Unit, onChanged: () -> Unit) {
    val scope = rememberCoroutineScope()
    val p = remember(kind) { AliasPanel(scope, kind, toast, onChanged) }
    LaunchedEffect(kind) { p.reload() }
    AliasTabBody(kind, p)
    p.addCanon?.let { c ->
        AliasAddDialog(c, kind, p.busy, p.msg, p::dismiss, p::submitAdd)
    }
    p.renameFrom?.let { c ->
        AliasRenameDialog(c, p.busy, p.msg, p::dismiss, p::submitRename)
    }
}

/** 别名页主体（3.7.53 从 AliasTab 抽出）：说明 + 「＋ 添加别名」+ 列表/别名树。 */
@Composable
private fun AliasTabBody(kind: String, p: AliasPanel) {
    Column(Modifier.fillMaxSize()
        .verticalScroll(rememberScrollState())
        .padding(12.dp, 4.dp)) {
        Text(aliasDescText(kind), color = MUTED, fontSize = 11.sp, lineHeight = 16.sp,
            modifier = Modifier.padding(bottom = 8.dp))
        AliasAddButton { p.openAdd("") }
        AliasListOrState(p.err, p.aliases, kind,
            onDelete = { p.delete(it) },
            onCanonClick = { p.openAdd(it) },
            onRenameCanon = { p.openRename(it) })
    }
}

/** 「＋ 添加别名」按钮（3.7.52：取代原来常驻的"别名 + 正名"双输入框）。 */
@Composable
private fun AliasAddButton(onAdd: () -> Unit) {
    Text(AppI18n.s("＋ 添加别名"), color = ACCENT, fontSize = 12.sp, maxLines = 1,
        modifier = Modifier.clip(RoundedCornerShape(999.dp))
            .background(ACCENT.copy(alpha = 0x22 / 255f))
            .border(1.dp, ACCENT, RoundedCornerShape(999.dp))
            .clickable { onAdd() }
            .padding(horizontal = 12.dp, vertical = 7.dp))
}

/** 登记别名弹窗（3.7.52）：正名已由"点按正名"预填；留空即新建一个正名。 */
@Composable
private fun AliasAddDialog(canon0: String, kind: String, busy: Boolean, msg: String,
                           onDismiss: () -> Unit, onConfirm: (String, String) -> Unit) {
    var alias by remember { mutableStateOf("") }
    // 以 canon0 为 key：先关再点另一个正名时，输入框不会残留上一次的正名
    var canon by remember(canon0) { mutableStateOf(canon0) }
    AlertDialog(onDismissRequest = onDismiss,
        title = { Text(if (canon0.isBlank()) AppI18n.s("登记别名") else AppI18n.s("添加别名")) },
        text = {
            Column {
                Text(aliasDialogHint(kind), color = MUTED, fontSize = 11.sp, lineHeight = 15.sp)
                OutlinedTextField(alias, { alias = it }, label = { Text(AppI18n.s("别名（要归并掉的那个写法）")) },
                    singleLine = true, colors = appFieldColors(),
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                OutlinedTextField(canon, { canon = it }, label = { Text(AppI18n.s("正名（归并到这里）")) },
                    singleLine = true, colors = appFieldColors(),
                    modifier = Modifier.fillMaxWidth().padding(top = 6.dp))
                if (msg.isNotEmpty()) {
                    Text(msg, color = ERR, fontSize = 11.sp, modifier = Modifier.padding(top = 6.dp))
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { onConfirm(alias.trim(), canon.trim()) }, enabled = !busy) {
                Text(AppI18n.s("登记"), color = ACCENT)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(AppI18n.s("取消"), color = MUTED) }
        })
}

/**
 * 改原作区名弹窗（3.7.53）：正名与原作分区名是同一个东西。
 *
 * 与服务端约定（`/api/originals/rename`，keep_alias=true）：
 *  * 只是改 DB 里的 original 标签，**零文件操作**，作品/进度/收藏不动；
 *  * 旧正名会被自动登记为别名 → 文件名里的旧写法重扫后仍归到新名，不会长回一个旧分区；
 *  * 新名若与既有分区字面相同 → 两个分区真合并（作品一并挂到目标分区）。
 */
@Composable
private fun AliasRenameDialog(canon0: String, busy: Boolean, msg: String,
                              onDismiss: () -> Unit, onConfirm: (String) -> Unit) {
    var name by remember(canon0) { mutableStateOf(canon0) }
    AlertDialog(onDismissRequest = onDismiss,
        title = { Text(AppI18n.s("改同人区名")) },
        text = {
            Column {
                Text(AppI18n.s("正名就是同人分区名，改名等于改分区名（零文件操作）。") +
                    AppI18n.sf("旧名「%1」会自动并入别名，文件名里的旧写法仍归到新分区；", canon0) +
                    AppI18n.s("若新名已有分区，则两个分区合并。"),
                    color = MUTED, fontSize = 11.sp, lineHeight = 15.sp)
                OutlinedTextField(name, { name = it }, label = { Text(AppI18n.s("新的同人区名")) },
                    singleLine = true, colors = appFieldColors(),
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                if (msg.isNotEmpty()) {
                    Text(msg, color = ERR, fontSize = 11.sp, modifier = Modifier.padding(top = 6.dp))
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { onConfirm(name.trim()) }, enabled = !busy) {
                Text(AppI18n.s("改名"), color = ACCENT)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(AppI18n.s("取消"), color = MUTED) }
        })
}

/** 弹窗内的一句话说明（比页面顶部那段长的更短，避免弹窗被文字挤满）。 */
private fun aliasDialogHint(kind: String): String = when (kind) {
    "circle" -> AppI18n.s("该社团名不再单列，作品并入正名社团（文件不动、进度不受影响）。")
    "original" -> AppI18n.s("文件名括号里出现该写法的作品归入正名分区；已建的分区整体并入。")
    else -> AppI18n.s("同一画师的旧笔名/译名归到正名名下（全库作者字段随重扫归并）。")
}

/** 别名描述文案（3.7.48 从 AliasTab 抽出的 when）。 */
private fun aliasDescText(kind: String): String = when (kind) {
    "circle" -> AppI18n.s("把另一个社团名归并到正名社团名下：该社团不再单列，其作品并入正名社团。文件不会移动、作品记录不变（阅读进度/收藏不受影响），删除别名即可撤销。")
    "original" -> AppI18n.s("把同人名的其他写法归并到规范名名下（如 FGO → FateGrand Order）：文件名括号内出现该写法的作品都会归入同一同人分区。该写法已建立的分区会整体并入正名分区（作品不移动、进度/收藏不受影响）。")
    else -> AppI18n.s("把同一画师的多个笔名归并到正名名下（全库作品作者字段随重扫归并）。删除别名后作品恢复显示原笔名。")
}

/** 别名列表三态（3.7.43 拆出；3.7.52 增加"点正名"回调；3.7.53 原作正名可改名）：
 *  加载失败 / 加载中 / 空 / 别名树。 */
@Composable
private fun AliasListOrState(err: String, aliases: Map<String, String>?, kind: String,
                             onDelete: (String) -> Unit, onCanonClick: (String) -> Unit,
                             onRenameCanon: (String) -> Unit) {
    when {
        err.isNotEmpty() -> Text(AppI18n.sf("加载失败：%1", err), color = ERR, fontSize = 13.sp,
            modifier = Modifier.padding(top = 10.dp))
        aliases == null -> Text(AppI18n.s("加载中…"), color = MUTED, fontSize = 13.sp,
            modifier = Modifier.padding(top = 10.dp))
        aliases.isEmpty() -> Text(AppI18n.s("还没有别名登记。点上方「＋ 添加别名」开始。"), color = MUTED,
            fontSize = 13.sp, modifier = Modifier.padding(top = 10.dp))
        else -> {
            // 3.7.52：条式记录（`别名 → 正名` 一行行）改成**别名树**——多个别名挂在同一个
            // 正名下面，一组一卡，归属关系一眼可见。按正名分组、组内别名排序保证稳定。
            val grouped = aliases.entries
                .groupBy({ it.value }, { it.key })
                .mapValues { (_, v) -> v.sorted() }
                .toSortedMap()
            Text(AppI18n.sf("%1 个正名 · %2 个别名", grouped.size, aliases.size) +
                AppI18n.s("（点正名加别名 · 长按复制 · ✕ 删除别名）"),
                color = MUTED, fontSize = 12.sp,
                modifier = Modifier.padding(top = 12.dp, bottom = 2.dp))
            // 3.7.53：原作正名就是原作分区名——只有原作开「✏ 改区名」（画师/社团改名会搬文件，
            // 不在本页做；它们各自有专门的改名入口）。
            AliasTree(grouped, onDelete, onCanonClick,
                canRenameCanon = kind == "original", onRenameCanon = onRenameCanon)
        }
    }
}
