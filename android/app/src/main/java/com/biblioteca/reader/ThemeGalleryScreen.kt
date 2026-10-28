package com.biblioteca.reader

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import coil.compose.AsyncImage
import kotlinx.coroutines.launch

/* ================================================================
   3.7.76：主题图库三级界面（抽屉 → 主题 → 图库；§4.6 对齐网页 #/theme/gallery）。
   自由增删改查：点击选用（当前槽位：背景图）、长按删除、＋从相册添加。
   网格数据与动作全复用 ThemeActions（面板 /api/theme/gallery 同一份）。
   ================================================================ */

@Composable
internal fun ThemeGalleryScreen(onBack: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var err by remember { mutableStateOf("") }
    var delTarget by remember { mutableStateOf<String?>(null) }
    var slot by remember { mutableStateOf("bg") }      // bg = 设为背景图；hero = 设为首页横幅
    BackHandlerOn(onBack)                                  // 3.6.124：系统返回键回主题页
    LaunchedEffect(Unit) { err = ThemeActions.refresh(ctx) }
    val items = ThemePrefs.gallery

    val pick = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument()) { uri ->
        val hero = slot == "hero"
        if (uri != null) scope.launch {
            val m = ThemeActions.add(ctx, uri, hero)
            if (m.isEmpty()) {
                toast(ctx, if (hero) AppI18n.s("已设为首页横幅") else AppI18n.s("已加入图库并选用"))
                err = ThemeActions.refresh(ctx)
            }
            else toast(ctx, m)
        }
    }

    Column(Modifier.fillMaxSize()) {
        TopBar("🖼 " + AppI18n.s("图库"), onBack)
        GalleryHead(items.size, slot, onSlot = { slot = it }, onAdd = { pick.launch(arrayOf("image/*")) })
        // 3.7.80：高亮直接读 ThemePrefs.bgName（snapshot state）——原先 remember 初值
        // 一旦 refresh 把服务端的选择拉回来就过期了，表现为"换了图，角标还停在旧那张"。
        GalleryGrid(err, items, if (slot == "hero") ThemePrefs.galleryHero else ThemePrefs.bgName,
            onPick = { name -> scope.launch {
                val m = if (slot == "hero") ThemeActions.selectHero(name) else ThemeActions.select(ctx, name)
                if (m.isEmpty()) toast(ctx, AppI18n.s("完成")) else toast(ctx, m)
            } },
            onAskDelete = { delTarget = it })
    }
    delTarget?.let { name ->
        AlertDialog(onDismissRequest = { delTarget = null },
            title = { Text(AppI18n.s("删除图片")) },
            text = { Text(AppI18n.s("要从图库删掉这张图吗？") + "\n" + name) },
            confirmButton = { TextButton(onClick = {
                delTarget = null
                scope.launch {
                    val m = ThemeActions.remove(ctx, name)
                    if (m.isEmpty()) toast(ctx, AppI18n.s("完成")) else toast(ctx, m)
                    err = ThemeActions.refresh(ctx)
                }
            }) { Text(AppI18n.s("删除"), color = ERR) } },
            dismissButton = { TextButton(onClick = { delTarget = null }) { Text(AppI18n.s("取消")) } })
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun GalleryCell(item: ThemeGalleryItem, active: Boolean,
                        onClick: () -> Unit, onLongPress: () -> Unit) {
    Box(Modifier.aspectRatio(0.7f).clip(RoundedCornerShape(10.dp))
        .border(2.dp, if (active) ACCENT else CARD_BG2, RoundedCornerShape(10.dp))
        .combinedClickable(onClick = onClick,
            onLongClick = if (item.builtin) null else onLongPress)) {
        AsyncImage(model = Api.themeGalleryImageUrl(item.name, item.mtime),
            contentDescription = item.title.ifEmpty { null },
            contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        if (item.builtin) Text(AppI18n.s("内置"), color = MUTED, fontSize = 9.sp,
            modifier = Modifier.align(Alignment.TopStart)
                .padding(4.dp)
                .background(Color(0xCC1C1433), RoundedCornerShape(6.dp))
                .padding(horizontal = 5.dp, vertical = 2.dp))
        if (active) Text(AppI18n.s("使用中"), color = TXT, fontSize = 10.sp,
            modifier = Modifier.align(Alignment.BottomStart)
                .padding(4.dp)
                .background(Color(0xCC1C1433), RoundedCornerShape(6.dp))
                .padding(horizontal = 5.dp, vertical = 2.dp))
    }
}

/** 网格区块：空态 / 错误条 / LazyVerticalGrid（点击选用、长按删除、使用中角标）。
 *  内置图不接受长按删除（服务端也会 400），避免用户以为是"删不掉"的 bug。 */
@Composable
private fun GalleryGrid(err: String, items: List<ThemeGalleryItem>, activeName: String,
                        onPick: (String) -> Unit, onAskDelete: (String) -> Unit) {
    if (err.isNotEmpty()) {
        Text(AppI18n.s("加载失败") + "：" + err, color = ERR, fontSize = 11.sp,
            modifier = Modifier.padding(horizontal = 14.dp))
    }
    if (items.isEmpty()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text(AppI18n.s("图库还是空的：点「添加图片」把电脑上的图存进来"),
                color = MUTED, fontSize = 12.sp)
        }
        return
    }
    LazyVerticalGrid(
        columns = GridCells.Adaptive(104.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(14.dp),
        modifier = Modifier.fillMaxSize()) {
        items(items.size) { i ->
            val it = items[i]
            GalleryCell(it, it.name == activeName,
                onClick = { onPick(it.name) },
                onLongPress = { onAskDelete(it.name) })
        }
    }
}

/** 顶栏下操作行：槽位切换 chips（背景图 / 首页横幅）+ 计数 + 「上传图片」。 */
@Composable
private fun GalleryHead(count: Int, slot: String, onSlot: (String) -> Unit, onAdd: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically) {
        GallerySlotChip(AppI18n.s("背景图"), slot == "bg") { onSlot("bg") }
        GallerySlotChip(AppI18n.s("首页横幅"), slot == "hero") { onSlot("hero") }
        Text(AppI18n.s("点击图片将其设为当前选中槽位") + "（" + count + "）",
            color = MUTED, fontSize = 11.sp, maxLines = 1,
            overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f).padding(start = 8.dp))
        Text("＋ " + AppI18n.s("上传图片"), color = ACCENT, fontSize = 12.sp,
            modifier = Modifier.clip(RoundedCornerShape(999.dp))
                .background(ACCENT.copy(alpha = 0.15f))
                .clickable { onAdd() }
                .padding(horizontal = 12.dp, vertical = 6.dp))
    }
}

/** 槽位切换小胶囊（与别名页 chips 同形态）。 */
@Composable
private fun GallerySlotChip(label: String, on: Boolean, onClick: () -> Unit) {
    Text(label, color = if (on) Color(0xFF1C1433) else TXT, fontSize = 12.sp, maxLines = 1,
        modifier = Modifier.clip(RoundedCornerShape(999.dp))
            .background(if (on) ACCENT else Color(0x24FFFFFF))
            .clickable { onClick() }
            .padding(horizontal = 12.dp, vertical = 6.dp))
}
