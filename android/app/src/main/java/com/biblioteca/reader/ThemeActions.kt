package com.biblioteca.reader

import android.content.Context
import android.content.SharedPreferences
import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/** 主题页动作层（3.7.74）：网络与落盘集中在这里，Compose 侧只负责点按与提示。
 *
 *  约定：返回空串 = 成功；非空 = 给用户看的失败原因——业务失败绝不静默（纪律 §4.4）。
 *  3.7.80 起「图库共用、选用按端」：本端读写的都是 `client=app` 槽位
 *  （面板 `_state/theme_bg_app.*` / `theme_active_app.txt`），电脑上换图不会覆盖手机的选择。 */
internal object ThemeActions {
    /** 服务端图库入库上限（services/theme_store.py 同值：8MB）。 */
    private const val MAX_BYTES = 8 * 1024 * 1024

    fun prefs(ctx: Context): SharedPreferences =
        ctx.getSharedPreferences("biblioteca", Context.MODE_PRIVATE)

    /** 拉列表 + 跟随**本端**背景槽位（名字变了才重下字节，省流量）+ 全局横幅角标。 */
    suspend fun refresh(ctx: Context): String = withContext(Dispatchers.IO) {
        try {
            val (items, active, heroActive) = Api.themeGallery()
            ThemePrefs.gallery = items.sortedWith(
                compareByDescending<ThemeGalleryItem> { it.builtin }.thenByDescending { it.mtime })
            ThemePrefs.galleryHero = heroActive
            when {
                active.isEmpty() && ThemePrefs.bgMode != "default" -> clearLocal(ctx)
                active.isNotEmpty() && active != ThemePrefs.bgName -> applyFromServer(ctx, active)
            }
            ""
        } catch (e: Exception) { fail(e) }
    }

    /** 启动时静默同步本端槽位（用户 3.6.122 需求：换图/换设备后手机冷启动就该是那张）。
     *  失败不弹提示——离线启动是常态，进主题/图库页会显式重试并把原因显示出来。 */
    suspend fun syncOnStart(ctx: Context) {
        refresh(ctx)
    }

    /** 相册选图 → 进图库 → 立即选用当前槽位（"自己添加"的就是这一条路）。
     *  [hero] = true 时选入全局横幅槽位（3.7.94）。 */
    suspend fun add(ctx: Context, uri: Uri, hero: Boolean = false): String = withContext(Dispatchers.IO) {
        try {
            val bytes = readBounded(ctx, uri, MAX_BYTES)
            val mime = ctx.contentResolver.getType(uri) ?: "image/jpeg"
            val name = Api.themeGalleryAdd(bytes, mime)
            if (name.isEmpty()) return@withContext AppI18n.s("服务端没有返回文件名")
            if (hero) selectHero(name) else select(ctx, name)
        } catch (e: Exception) { fail(e) }
    }

    /** 选用图库里的一张：先让服务端切过去（双端同步），再把字节拉到本机铺底。 */
    suspend fun select(ctx: Context, name: String): String = withContext(Dispatchers.IO) {
        try {
            Api.themeBgSelect(name)
            applyFromServer(ctx, name)
            ""
        } catch (e: Exception) { fail(e) }
    }

    /** 选用图库里的一张为首页横幅（3.7.94）：全局槽位，改的是网页首页横幅；
     *  APP 首页横幅是打包资源不渲染它，只记名字做「使用中」角标。 */
    suspend fun selectHero(name: String): String = withContext(Dispatchers.IO) {
        try {
            Api.themeHeroSelect(name)
            ThemePrefs.galleryHero = name
            ""
        } catch (e: Exception) { fail(e) }
    }

    /** 删除图库中的一张；删的若是当前启用那张，服务端会恢复默认，本地跟着清。 */
    suspend fun remove(ctx: Context, name: String): String = withContext(Dispatchers.IO) {
        try {
            Api.themeGalleryDelete(name)
            if (ThemePrefs.bgName == name) clearLocal(ctx)
            ThemePrefs.gallery = ThemePrefs.gallery.filterNot { it.name == name }
            ""
        } catch (e: Exception) { fail(e) }
    }

    /** 恢复默认背景（图库文件不动，只是不再启用）。 */
    suspend fun reset(ctx: Context): String = withContext(Dispatchers.IO) {
        try {
            Api.themeBgReset()
            clearLocal(ctx)
            ""
        } catch (e: Exception) { fail(e) }
    }

    /** 把本端当前背景拉到本机并记为启用；返回版本键（破 Coil 缓存用）。 */
    private suspend fun applyFromServer(ctx: Context, name: String) {
        Api.downloadTo("/api/theme/bg?client=" + CLIENT_APP + "&v=" + System.currentTimeMillis(),
            ThemePrefs.bgPath(ctx))
        ThemePrefs.saveBg(prefs(ctx), "panel", name, System.currentTimeMillis())
    }

    private fun clearLocal(ctx: Context) {
        ThemePrefs.bgPath(ctx).delete()
        ThemePrefs.saveBg(prefs(ctx), "default", "", 0L)
    }

    /** SAF 读图：先按上限截断判断，避免超大图把内存打爆（服务端也会再校验一次）。 */
    private fun readBounded(ctx: Context, uri: Uri, max: Int): ByteArray {
        val ins = ctx.contentResolver.openInputStream(uri) ?: throw ApiException(AppI18n.s(AppI18n.s(AppI18n.s("打不开这张图"))))
        ins.use { stream ->
            val buf = ByteArray(max + 1)
            var off = 0
            while (off < buf.size) {
                val n = stream.read(buf, off, buf.size - off)
                if (n <= 0) break
                off += n
            }
            if (off > max) throw ApiException(AppI18n.s(AppI18n.s(AppI18n.s("图片超过 8MB，请先压缩"))))
            return buf.copyOf(off)
        }
    }

    private fun fail(e: Exception): String = when (e) {
        is AuthException -> AppI18n.s(AppI18n.s(AppI18n.s("需要访问令牌")))
        else -> e.message ?: AppI18n.s(AppI18n.s(AppI18n.s("操作失败")))
    }

    /** 主题背景图本地缓存的绝对路径（预览/铺底都用它，避免重复下载）。 */
    fun localBg(ctx: Context): File = ThemePrefs.bgPath(ctx)
}