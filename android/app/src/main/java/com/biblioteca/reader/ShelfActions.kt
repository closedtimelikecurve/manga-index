package com.biblioteca.reader

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/* ================================================================
   书架的读写动作（3.7.60 从 AppState 拆出）
   * AppState.kt 有效代码已顶到 500 行上限，书架这两件事职责独立、搬走最干净；
   * 用扩展函数而不是新类：状态（shelfEntries）仍归 AppState，
     拆的只是"动作"，避免为了行数再造一层间接。
   ================================================================ */

internal fun AppState.refreshShelf() { shelfEntries = LibraryStore.entries() }

/**
 * 3.7.60：从设备找回已下载作品。
 *
 * 书架"空了"通常是索引（library.json）丢了，作品包一直在
 * `getExternalFilesDir(null)/library/works/`；清缓存只动 cacheDir，不会删它们。
 * 找回按文件名反推（目录名 = 社团，文件名 = 作品名），页数重新读 zip。
 */
internal fun AppState.recoverShelf() {
    kotlinx.coroutines.CoroutineScope(Dispatchers.IO).launch {
        val n = try { LibraryStore.recoverOrphans(ctx) } catch (e: Exception) {
            withContext(Dispatchers.Main) { appToast(AppI18n.sf("找回失败：%1", e.message)) }
            return@launch
        }
        withContext(Dispatchers.Main) {
            refreshShelf()
            appToast(if (n > 0) AppI18n.sf("已找回 %1 部作品", n) else AppI18n.s(AppI18n.s(AppI18n.s("设备上没有可找回的作品文件"))))
        }
    }
}
