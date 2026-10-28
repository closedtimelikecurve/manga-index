package com.biblioteca.reader

import android.content.Context
import java.io.File

/**
 * 图片缓存（封面 / 页面缩略图）的计量与清理（3.7.59 从 AppState 拆出）。
 *
 * **只允许删 `cacheDir/image_cache`**：本地书架的作品在
 * `getExternalFilesDir(null)/library`，与缓存目录毫无关系。用户反馈
 * "清缓存把下载的作品也清了"，这类事故不可逆，所以这里做硬护栏：
 * 规范化路径后必须是 cacheDir 的直接子目录且名为 image_cache。
 */
internal object ImageCache {
    fun dir(ctx: Context): File = File(ctx.cacheDir, "image_cache")

    /** 图片缓存占用（MB）。 */
    fun sizeMb(ctx: Context): Float {
        val d = dir(ctx)
        if (!d.exists()) return 0f
        var b = 0L
        d.walkTopDown().forEach { if (it.isFile) b += it.length() }
        return b / 1048576f
    }

    /** 清空图片缓存；返回释放的字节数。**不会碰书架里的作品文件**。 */
    @OptIn(coil.annotation.ExperimentalCoilApi::class)
    fun clear(ctx: Context): Long {
        var freed = 0L
        runCatching {
            val cacheRoot = ctx.cacheDir.canonicalFile
            val d = dir(ctx).canonicalFile
            if (d.parentFile == cacheRoot && d.name == "image_cache" && d.exists()) {
                d.walkTopDown().forEach { if (it.isFile) freed += it.length() }
                d.deleteRecursively()
            }
            coil.Coil.imageLoader(ctx).diskCache?.clear()
            coil.Coil.imageLoader(ctx).memoryCache?.clear()
        }
        return freed
    }
}
