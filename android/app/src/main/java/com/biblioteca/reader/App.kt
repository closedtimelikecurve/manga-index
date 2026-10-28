package com.biblioteca.reader

import android.app.Application
import android.os.Build
import coil.ImageLoader
import coil.ImageLoaderFactory
import coil.decode.GifDecoder
import coil.decode.ImageDecoderDecoder
import coil.disk.DiskCache
import java.io.File

/** 全局 ImageLoader：Coil 2.x 必须手动注册动图解码器，否则 GIF/动图 WebP 只渲染第一帧；
 * 3.0 追加本地书架 zip 直读 Fetcher（LocalPage → 按条目名读流，不逐页解压落盘）。
 * 2026-10-15 手机端占用排查：磁盘缓存**不再设自动大小上限**（用户嫌 200MB 硬顶不友好，
 * 自动 LRU 淘汰会反复重下图），改由全局菜单抽屉的「🧹 清缓存」键手动清理。目录固定为
 * cacheDir/image_cache 以便精准清除；maxSizeBytes 传极大值仅为关闭 LRU 自动淘汰。 */
class IndexApp : Application(), ImageLoaderFactory {
    override fun newImageLoader(): ImageLoader {
        val diskCache = DiskCache.Builder()
            .directory(File(cacheDir, "image_cache"))
            .maxSizeBytes(IMAGE_DISK_CACHE_MAX)
            .build()
        return ImageLoader.Builder(this)
            .components {
                if (Build.VERSION.SDK_INT >= 28) add(ImageDecoderDecoder.Factory())
                else add(GifDecoder.Factory())
                add(LocalPageFetcher.Factory())
            }
            .diskCache(diskCache)
            .build()
    }

    companion object {
        /** 磁盘缓存"上限"：实为关闭 LRU 自动淘汰所用的极大值（100GB，手机装不满），
         * 并非真实配额；缓存由抽屉「清缓存」键手动管理。 */
        const val IMAGE_DISK_CACHE_MAX: Long = 100L * 1024 * 1024 * 1024
    }
}
