package com.biblioteca.reader

import android.content.Context
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import coil.compose.AsyncImage
import coil.request.ImageRequest

/** 内置「纯黑」条目名（与 services/theme_store.py 的 BUILTIN_ITEMS 第一项一致）。 */
internal const val BLACK_ITEM = "b00_black.jpg"

/** 根容器主题背景图（3.7.73 建；3.7.74 主题模块拆页后从 DrawerExtras.kt 迁到本文件）。
 *
 *  panel = 主题图库里选用的一张（字节缓存到 filesDir 的同一个 `theme_bg.img`）；
 *  default = 内置资源。
 *
 *  3.7.81 修复「手机上背景图根本不显示」：各屏根容器的 `.background(BG)` 把这一层盖住了。
 *
 *  3.7.82 修复「背景只能切一次」：Coil 的缓存键默认是文件**路径**，而换图是覆盖写同一个
 *  `theme_bg.img` —— 第二次起命中内存缓存，画面不动。这里显式用
 *  `theme-bg-<mode>-<bgVer>` 作内存/磁盘缓存键，`bgVer` 每次选用/恢复都会变（snapshot 状态），
 *  于是既会重组、也不会再命中旧图。 */
@Composable
internal fun ThemeBackground(ctx: Context) {
    val mode = ThemePrefs.bgMode
    val ver = ThemePrefs.bgVer                       // 读 snapshot state：换图即重组
    // 3.7.82（用户需求①）：内置「纯黑」不是一张"要透出来的背景图"，而是"不要背景图"。
    // 按 panel 走 0.30 的叠层会变成"黑图半透"，底下的东西还在，看着不像纯黑。
    if (ThemePrefs.bgName == BLACK_ITEM) {
        Box(Modifier.fillMaxSize().background(Color.Black))
        return
    }
    // 3.7.85：不透明度改为主题页滑条实时可调（snapshot 状态，拖动即重组）
    val alpha = ThemePrefs.bgAlpha
    val file = ThemePrefs.bgPath(ctx).takeIf { mode != "default" && it.exists() }
    if (file == null) {
        Image(painterResource(R.drawable.settings_bg), contentDescription = null,
            contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxSize(), alpha = alpha)
        return
    }
    val model = ImageRequest.Builder(ctx)
        .data(file)
        .memoryCacheKey("theme-bg-" + mode + "-" + ver)
        .diskCacheKey("theme-bg-" + mode + "-" + ver)
        .build()
    AsyncImage(model = model, contentDescription = null,
        contentScale = ContentScale.Crop,
        modifier = Modifier.fillMaxSize(), alpha = alpha)
}
