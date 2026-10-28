@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class, androidx.compose.foundation.ExperimentalFoundationApi::class)
package com.biblioteca.reader

import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyGridState
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items as lazyRowItems
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.TextButton
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import coil.Coil
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.CoroutineScope

@Composable
internal fun AppBottomCapsule(s: AppState) {
    val sc = s.screen
    if (sc is Screen.Home || sc is Screen.Resume || sc is Screen.Favorites || sc is Screen.Shelf) {
        Box(Modifier.fillMaxSize().navigationBarsPadding(), contentAlignment = Alignment.BottomCenter) {
            BottomCapsule(active = when (sc) {
                is Screen.Resume -> "resume"; is Screen.Favorites -> "favorites"
                is Screen.Shelf -> "shelf"; else -> "home"
            },
            onHome = { if (sc !is Screen.Home) s.goTab(Screen.Home) },
            onResume = { if (sc !is Screen.Resume) s.goTab(Screen.Resume) },
            onFavorites = { if (sc !is Screen.Favorites) s.goTab(Screen.Favorites) },
            onShelf = { if (sc !is Screen.Shelf) s.goTab(Screen.Shelf) },
            modifier = Modifier.padding(bottom = 10.dp))
        }
    }
}

@Composable
internal fun AppCircleMenu(s: AppState) {
    s.delCircle?.let { (cname, anchor) ->
        val canManage = cname != "收件箱"   // i18n:data 收件箱=真实社团名
        CardActionPopup(card = anchor, showInfo = false, onDismiss = { s.delCircle = null },
            onInfo = {}, onDelCover = null,
            onRename = if (canManage) ({ s.delCircle = null; s.renameInput = cname; s.renameCircleName = cname }) else null,
            onDissolve = if (canManage) ({ s.delCircle = null; s.dissolveCircleName = cname }) else null,
            onDownloadAll = if (s.online != false && canManage) ({ s.delCircle = null
                s.scope.launch {
                    val works = try { withContext(Dispatchers.IO) { Api.circle(cname) }.first }
                    catch (e: Exception) { s.appToast(AppI18n.sf("获取作品列表失败：%1", e.message)); emptyList() }
                    s.downloadAll(works.map { cname to it.name }, AppI18n.sf("社团「%1」", cname))
                } }) else null) {
            s.delCircle = null
            s.scope.launch {
                try {
                    val msg = withContext(Dispatchers.IO) { Api.deleteCircle(cname) }
                    s.invalidateHome(); s.invalidateCircle(cname)
                    android.widget.Toast.makeText(s.ctx, msg, android.widget.Toast.LENGTH_SHORT).show()
                } catch (e: Exception) {
                    android.widget.Toast.makeText(s.ctx, AppI18n.sf("删除失败：%1", e.message), android.widget.Toast.LENGTH_SHORT).show()
                }
            }
        }
    }
}

@Composable
internal fun AppRenameCircleDialog(s: AppState) {
    s.renameCircleName?.let { oldName ->
        AlertDialog(onDismissRequest = { s.renameCircleName = null }, title = { Text(AppI18n.s("重命名社团")) },
            text = {
                Column {
                    Text(AppI18n.s("若新社团名已存在，两社将合并为一：作品并入已有社团，文件名不变、绝不覆盖，源目录随后清除。"),
                        color = Color(0xFF9A8FB8), fontSize = 11.sp, lineHeight = 15.sp)
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(value = s.renameInput, onValueChange = { s.renameInput = it },
                        singleLine = true, label = { Text(AppI18n.s("新社团名")) })
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    val nn = s.renameInput.trim()
                    if (nn.isEmpty() || nn == oldName) { s.renameCircleName = null; return@TextButton }
                    s.renameCircleName = null
                    s.scope.launch {
                        try {
                            val (msg, _) = withContext(Dispatchers.IO) { Api.renameCircle(oldName, nn) }
                            android.widget.Toast.makeText(s.ctx, msg, android.widget.Toast.LENGTH_SHORT).show()
                            s.refreshAfterStructureChange(); s.goTab(Screen.Home)
                        } catch (e: Exception) {
                            android.widget.Toast.makeText(s.ctx, AppI18n.sf("改名失败：%1", e.message), android.widget.Toast.LENGTH_SHORT).show()
                        }
                    }
                }) { Text(AppI18n.s("改名"), color = ACCENT2) }
            },
            dismissButton = { TextButton(onClick = { s.renameCircleName = null }) { Text(AppI18n.s("取消")) } })
    }
}

@Composable
internal fun AppDissolveDialog(s: AppState) {
    s.dissolveCircleName?.let { cname ->
        AlertDialog(onDismissRequest = { s.dissolveCircleName = null }, title = { Text(AppI18n.s("解散社团")) },
            text = { Text(AppI18n.sf("确定解散社团「%1」？\n\n内部作品将移动到「收件箱」（文件名不变、绝不覆盖）。\n原社团目录随后整棵直接删除，不留空文件夹（残留文件不可还原）。\n待定词条作品随后可在「增补信息」中整理。", cname)) },
            confirmButton = {
                TextButton(onClick = {
                    s.dissolveCircleName = null
                    s.scope.launch {
                        try {
                            val msg = withContext(Dispatchers.IO) { Api.dissolveCircle(cname) }
                            android.widget.Toast.makeText(s.ctx, msg, android.widget.Toast.LENGTH_SHORT).show()
                            s.refreshAfterStructureChange(); s.goTab(Screen.Home)
                        } catch (e: Exception) {
                            android.widget.Toast.makeText(s.ctx, AppI18n.sf("解散失败：%1", e.message), android.widget.Toast.LENGTH_SHORT).show()
                        }
                    }
                }) { Text(AppI18n.s("解散"), color = Color(0xFFFFC86B)) }
            },
            dismissButton = { TextButton(onClick = { s.dissolveCircleName = null }) { Text(AppI18n.s("取消")) } })
    }
}

@Composable
internal fun AppArtistMenu(s: AppState) {
    s.delArtist?.let { (aname, anchor) ->
        CardActionPopup(card = anchor, showInfo = false, onDismiss = { s.delArtist = null },
            onInfo = {}, onDelCover = null, onDownload = null, onSetCover = null, onDissolve = null, onDelete = null,
            onDownloadAll = if (s.online != false) ({ s.delArtist = null
                s.scope.launch {
                    val works = try { withContext(Dispatchers.IO) { Api.artistPage(aname) }.works }
                    catch (e: Exception) { s.appToast(AppI18n.sf("获取作品列表失败：%1", e.message)); emptyList() }
                    s.downloadAll(works.map { it.group to it.work }, AppI18n.sf("画师「%1」", aname))
                } }) else null,
            onRename = { s.delArtist = null; s.artistRenameName = aname; s.renameInput = aname })
    }
}

@Composable
internal fun AppOriginalMenu(s: AppState) {
    s.origMenu?.let { (zname, anchor) ->
        CardActionPopup(card = anchor, showInfo = false, onDismiss = { s.origMenu = null },
            onInfo = {}, onDelCover = null, onDownload = null, onSetCover = null, onDissolve = null, onDelete = null,
            onRename = { s.origMenu = null; s.renameInput = zname; s.origRenameKeepAlias = true
                s.origRenameName = zname },
            onRemoveZone = { s.origMenu = null; removeOriginalTarget = zname })
    }
}

@Composable
internal fun AppOriginalRenameDialog(s: AppState) {
    s.origRenameName?.let { oldName ->
        AlertDialog(onDismissRequest = { s.origRenameName = null }, title = { Text(AppI18n.s("分区改名")) },
            text = {
                Column {
                    Text(AppI18n.s("只改分区标签，作品文件一律不动（位置/进度/收藏不受影响）。新名按你输入的来、不做归一；旧名默认登记为别名（文件名里的旧写法仍归到新名）。"),
                        color = Color(0xFF9A8FB8), fontSize = 11.sp, lineHeight = 15.sp)
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(value = s.renameInput, onValueChange = { s.renameInput = it },
                        singleLine = true, label = { Text(AppI18n.s("新分区名")) },
                        trailingIcon = {
                            if (s.renameInput.isNotEmpty()) {
                                Text("✕", color = Color(0xFF9A8FB8), fontSize = 15.sp,
                                    modifier = Modifier.clip(RoundedCornerShape(999.dp))
                                        .clickable { s.renameInput = "" }
                                        .padding(horizontal = 10.dp, vertical = 6.dp))
                            }
                        })
                    Spacer(Modifier.height(6.dp))
                    Row(verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.clickable { s.origRenameKeepAlias = !s.origRenameKeepAlias }) {
                        Checkbox(checked = s.origRenameKeepAlias, onCheckedChange = { s.origRenameKeepAlias = it })
                        Text(AppI18n.s("把旧名登记为别名（旧写法不再单列分区）"), color = Color(0xFF9A8FB8), fontSize = 11.sp)
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { s.doOriginalRename(oldName) }) { Text(AppI18n.s("改名"), color = ACCENT2) }
            },
            dismissButton = { TextButton(onClick = { s.origRenameName = null }) { Text(AppI18n.s("取消")) } })
    }
}

@Composable
internal fun AppArtistRenameDialog(s: AppState) {
    s.artistRenameName?.let { oldName ->
        AlertDialog(onDismissRequest = { s.artistRenameName = null }, title = { Text(AppI18n.s("重命名画师")) },
            text = {
                Column {
                    Text(AppI18n.s("名下全部作品的文件名与记录会一起跟随改名。若新名字与库中已有画师重合，两位将合并：作品并入该画师，旧名降级为别名（仍可按旧名检索）。"),
                        color = Color(0xFF9A8FB8), fontSize = 11.sp, lineHeight = 15.sp)
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(value = s.renameInput, onValueChange = { s.renameInput = it },
                        singleLine = true, label = { Text(AppI18n.s("新画师名")) })
                }
            },
            confirmButton = {
                TextButton(onClick = { s.doArtistRename(oldName) }) { Text(AppI18n.s("改名"), color = ACCENT2) }
            },
            dismissButton = { TextButton(onClick = { s.artistRenameName = null }) { Text(AppI18n.s("取消")) } })
    }
}

@Composable
internal fun AppWorkMenu(s: AppState) {
    s.delWork?.let { (wgroup, wname, anchor) ->
        val sc = s.delWorkScope; val rg = s.delWorkRegion
        CardActionPopup(card = anchor, showInfo = true, compact = s.delWorkCompact,
            onDismiss = { s.delWork = null; s.delWorkScope = null; s.delWorkRegion = null; s.delWorkCompact = false },
            onInfo = { s.delWork = null; s.delWorkScope = null; s.delWorkRegion = null
                s.nav(Screen.Info(wgroup, wname)) },
            onDelCover = { s.askDelCover = true },
            onSetCover = if (sc != null && rg != null) ({ s.setCoverAndReload(sc, rg, wgroup, wname) }) else null,
            onDownload = if (s.online != false) ({ s.delWork = null; s.delWorkScope = null; s.delWorkRegion = null
                if (!DownloadManager.enqueue(wgroup, wname)) s.appToast(AppI18n.s("该作品已在下载列表中")) }) else null) {
            s.deleteWorkAndReload(wgroup, wname)
        }
    }
}

@Composable
internal fun AppAddOriginalDialog(s: AppState) {
    if (!addOriginalOpen) return
    var term by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    val preview = s.addOriginalPreview; val dlgMsg = s.addOriginalMsg
    AlertDialog(onDismissRequest = { addOriginalOpen = false }, title = { Text(AppI18n.s("添加同人")) },
        text = {
            Column {
                Text(AppI18n.s("输入同人词条：系统搜索作品名 / 社团名 / 标签中含有该词条的作品，归并成为一个新的同人分区。分区名就是你输入的词条（不做归一）。"),
                    color = Color(0xFF9A8FB8), fontSize = 11.sp, lineHeight = 15.sp)
                OutlinedTextField(value = term, onValueChange = { term = it }, label = { Text(AppI18n.s("同人词条")) },
                    singleLine = true, colors = appFieldColors(),
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                preview?.let { AppAddOriginalPreview(it, term) }
                if (dlgMsg.isNotEmpty()) {
                    Text(dlgMsg, color = Color(0xFFFF5ED0), fontSize = 11.sp, modifier = Modifier.padding(top = 6.dp))
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                if (term.isBlank()) { s.addOriginalMsg = AppI18n.s("词条不能为空"); return@TextButton }
                busy = true
                s.scope.launch {
                    try { s.doAddOriginal(term.trim()) } catch (e: Exception) { s.addOriginalMsg = AppI18n.sf("添加失败：%1", e.message) }
                    busy = false
                }
            }, enabled = !busy) { Text(AppI18n.s("添加并进入分区"), color = ACCENT2) }
        },
        dismissButton = {
            Row(verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = {
                    if (term.isBlank()) { addOriginalOpen = false; return@TextButton }
                    busy = true
                    s.scope.launch {
                        try { s.previewOriginal(term.trim()) } catch (e: Exception) { s.addOriginalMsg = AppI18n.sf("预览失败：%1", e.message) }
                        busy = false
                    }
                }, enabled = !busy) { Text(if (preview == null) AppI18n.s("预览命中") else AppI18n.s("重新预览")) }
                TextButton(onClick = {
                    if (term.isBlank()) { s.addOriginalMsg = AppI18n.s("分区名不能为空"); return@TextButton }
                    busy = true
                    s.scope.launch {
                        try { s.createEmptyOriginal(term.trim()) } catch (e: Exception) { s.addOriginalMsg = AppI18n.sf("创建失败：%1", e.message) }
                        busy = false
                    }
                }, enabled = !busy) { Text(AppI18n.s("仅建空分区"), color = Color(0xFF9A8FB8)) }
            }
        })
}

@Composable
private fun AppAddOriginalPreview(p: Api.OriginalSearch, term: String) {
    Text(AppI18n.sf("命中 %1 部", p.hits.size) + (if (p.hits.isEmpty()) AppI18n.s("（换个词条试试；或点「仅建空分区」先建分区再手动添加作品）") else
        "：" + p.hits.take(3).joinToString("、") { it.work.name.dispWorkName() } + if (p.hits.size > 3) AppI18n.s(" 等") else ""),
        color = Color(0xFF9A8FB8), fontSize = 11.sp, modifier = Modifier.padding(top = 8.dp))
    if (p.similar.isNotEmpty()) {
        Text(AppI18n.s("⚠ 已存在写法相近的分区：") + p.similar.joinToString("、") { AppI18n.sf("「%1」（%2 部）", it.name, it.works) }
            + AppI18n.sf("\n本次会另建「%1」分区。", term.trim()) + AppI18n.s("若想合成一个，请到该分区的「分区改名」把旧名改成本名。"),
            color = Color(0xFFFFC86B), fontSize = 11.sp, lineHeight = 15.sp, modifier = Modifier.padding(top = 6.dp))
    }
}

@Composable
internal fun AppRemoveOriginalDialog(s: AppState) {
    removeOriginalTarget?.let { tname ->
        AlertDialog(onDismissRequest = { removeOriginalTarget = null }, title = { Text(AppI18n.s("移除同人分区")) },
            text = { Text(AppI18n.sf("确定移除同人分区「%1」？\n\n该分区的 original 标签会被清除，作品本身不受影响（仍在原社团/画师页可见）；词条库中的对应词条一并删除。", tname)) },
            confirmButton = {
                TextButton(onClick = {
                    removeOriginalTarget = null
                    s.scope.launch {
                        try {
                            withContext(Dispatchers.IO) { Api.originalsRemove(tname) }
                            s.appToast(AppI18n.sf("已移除同人分区「%1」", tname))
                            s.homeOriginals = try { withContext(Dispatchers.IO) { Api.originals() } } catch (_: Exception) { null }
                            s.invalidateHome()
                        } catch (e: Exception) { s.appToast(AppI18n.sf("移除失败：%1", e.message)) }
                    }
                }) { Text(AppI18n.s("移除"), color = Color(0xFFFF6B8B)) }
            },
            dismissButton = { TextButton(onClick = { removeOriginalTarget = null }) { Text(AppI18n.s("取消")) } })
    }
}

@Composable
internal fun AppDelCoverDialog(s: AppState) {
    if (s.askDelCover && s.delWork != null) {
        val (dcGroup, dcWork, _) = s.delWork!!
        AlertDialog(onDismissRequest = { s.askDelCover = false; s.delWork = null },
            title = { Text(AppI18n.s("删除首页图片")) },
            text = { Text(AppI18n.sf("确定删除作品「%1」的首页图片？\n\n将从压缩包内物理移除封面页（不可恢复），重扫后首页变为原第二页。", dcWork)) },
            confirmButton = {
                TextButton(onClick = { s.askDelCover = false; s.delWork = null; s.doDeleteCover(dcGroup, dcWork) }) {
                    Text(AppI18n.s("删除"), color = Color(0xFFFF6B8B))
                }
            },
            dismissButton = { TextButton(onClick = { s.askDelCover = false; s.delWork = null }) { Text(AppI18n.s("取消")) } })
    }
}

@Composable
internal fun AppDownloadBanner(s: AppState) {
    if (DownloadManager.autoPopup) {
        val running = DownloadManager.runningCount()
        val queued = DownloadManager.queuedCount()
        val cur = DownloadManager.items.firstOrNull { it.state == DlState.RUNNING }
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) {
            Row(Modifier.padding(bottom = 48.dp).clip(RoundedCornerShape(999.dp))
                .background(Color(0xF21C1433)).border(1.dp, ACCENT.copy(alpha = 0x44 / 255f), RoundedCornerShape(999.dp))
                .clickable { s.nav(Screen.Downloads) }.padding(horizontal = 16.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text(bannerText(running, queued, cur), color = Color(0xFFF2EEFA), fontSize = 12.sp,
                    maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                Text(AppI18n.s("查看"), color = ACCENT2, fontSize = 12.sp, modifier = Modifier.padding(start = 10.dp))
            }
        }
    }
}

private fun bannerText(running: Int, queued: Int, cur: DlItem?): String {
    val head = AppI18n.sf("⬇ %1 个进行中", running) + (if (queued > 0) AppI18n.sf(" · %1 排队", queued) else "")
    val curTxt = if (cur != null) {
        val pct = if (cur.total > 0) " ${(cur.done * 100 / cur.total).coerceIn(0, 100)}%"
                  else " " + fmtBytesShelf(cur.done)
        "　「${cur.work}」$pct"
    } else ""
    return head + curTxt
}

@Composable
internal fun AppCompatDialog(s: AppState) {
    if (s.compatMsg.isNotEmpty()) {
        AlertDialog(onDismissRequest = { s.compatMsg = "" }, title = { Text(s.compatTitle) },
            text = { Text(s.compatMsg) },
            confirmButton = { TextButton(onClick = { s.compatMsg = "" }) { Text(AppI18n.s("知道了")) } })
    }
}

@Composable
internal fun AppUpdateDialog(s: AppState) {
    s.updateInfo?.let { v ->
        AlertDialog(onDismissRequest = { s.updateInfo = null },
            title = { Text(AppI18n.sf("发现新版本 v%1", v.versionName)) },
            text = { Text(if (s.updateMsg.isEmpty())
                AppI18n.sf("检测到服务器派发的新版 App（%1 MB），当前版本较旧。\n是否下载并安装？", v.size / 1048576)
                else s.updateMsg) },
            confirmButton = { TextButton(onClick = { s.doUpdate(v) }) { Text(AppI18n.s("立即更新")) } },
            dismissButton = {
                TextButton(onClick = {
                    s.prefs.edit().putInt("dismissed_version", v.versionCode).apply()
                    s.dismissedVersion.intValue = v.versionCode; s.updateInfo = null
                }) { Text(AppI18n.s("暂不更新")) }
            })
    }
}
