package com.biblioteca.reader

import android.content.Context
import android.content.SharedPreferences
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import java.io.File

/** 一套预设配色。[id] 是持久化的档位标识，[name] 同时是 i18n key（与网页 THEME_PRESETS 同表同色）。 */
internal data class ThemePreset(
    val id: String, val name: String, val accent: String, val accent2: String
)

/** 六套预设（3.7.80 抽到偏好层：档位推断与界面渲染共用一份，避免两处表各自漂移）。 */
internal val THEME_PRESETS = listOf(   // i18n:data 预设名是 key，显示处统一 AppI18n.s
    ThemePreset("neon", "霓虹粉", "#ff3df2", "#b06bff"),   // i18n:data key 定义，显示处统一 AppI18n.s
    ThemePreset("cyber", "赛博蓝", "#4dc9ff", "#7f9cff"),   // i18n:data key 定义，显示处统一 AppI18n.s
    ThemePreset("jade", "翡翠绿", "#3dffb8", "#43c6a8"),   // i18n:data key 定义，显示处统一 AppI18n.s
    ThemePreset("amber", "暖橙", "#ffb347", "#ff8a5f"),   // i18n:data key 定义，显示处统一 AppI18n.s
    ThemePreset("crimson", "绯红", "#ff5e7e", "#ff3d6e"),   // i18n:data key 定义，显示处统一 AppI18n.s
    ThemePreset("violet", "紫罗兰", "#b06bff", "#7f5cff"),   // i18n:data key 定义，显示处统一 AppI18n.s
)

/** 主题偏好（3.7.73 建；3.7.74 并入图库语义；3.7.80 加「档位」）。
 *
 *  颜色经 mutableStateOf 暴露——组合期读 ACCENT/ACCENT2 的地方在切换时自动重组。
 *  [preset] 只记"当前是哪一档"（6 个预设之一 / "custom"），**颜色真值仍只有
 *  ACCENT/ACCENT2 一份**：预设档下色行只读，改色一律归入 custom。
 *  背景图两态：default（内置资源）/ panel（从面板主题图库里选用的一张，
 *  字节缓存于 filesDir/theme_bg.img，[bgName] 记住是哪一张、[bgVer] 是破缓存用的版本键）。
 *  持久化 SharedPreferences "biblioteca"：theme_accent / theme_accent2 / theme_preset /
 *  theme_bg / theme_bg_name / theme_bg_ver。 */
/** 背景图默认不透明度——与 3.7.81 起的固定值 0.30 一致（不改变存量观感）。 */
internal const val DEFAULT_BG_ALPHA = 0.30f

object ThemePrefs {
    /** 主色/副色：**唯一状态在 `FeaturesCommon.ACCENT/ACCENT2`**（全 App 五十多个读点都在
     *  那里），这里只做主题域的读写门面。
     *
     *  3.7.74 事故修复：3.7.73 里这里是两份独立的 mutableStateOf，主题页只写自己那份，
     *  全局 ACCENT/ACCENT2 **一次都没被写过**——选完配色，整个 App 纹丝不动，
     *  用户看到的"主题功能在手机上表现非常不理想"正是这个。两份状态 = 改了没生效，
     *  是纪律 §4.3 明令禁止的形态，故改为同源。 */
    var accent: Color
        get() = ACCENT
        set(v) { ACCENT = v }

    var accent2: Color
        get() = ACCENT2
        set(v) { ACCENT2 = v }

    var preset by mutableStateOf("neon")               // 6 个预设 id 之一 / "custom"
    var bgMode by mutableStateOf("default")            // default | panel
    var bgName by mutableStateOf("")                   // 选用中的图库文件名（空 = 默认图）
    var bgVer by mutableStateOf(0L)                    // 背景图版本键（换图后破 Coil 缓存）
    /** 首页横幅槽位（3.7.94）：hero 是**全局单份**（网页首页在用），APP 只记服务端
     *  当前启用的图库文件名做「使用中」角标——APP 不渲染横幅，无需本地字节。 */
    var galleryHero by mutableStateOf("")
    /** 背景图不透明度 0..1（3.7.85 用户需求：主题里用滑条实时调）。
     *  是 snapshot 状态——拖动时 `ThemeBackground` 直接重组重绘，所见即所得。 */
    var bgAlpha by mutableStateOf(DEFAULT_BG_ALPHA)
    var gallery by mutableStateOf<List<ThemeGalleryItem>>(emptyList())

    fun bgPath(ctx: Context): File = File(ctx.filesDir, "theme_bg.img")

    fun load(prefs: SharedPreferences) {
        accent = parseHexColor(prefs.getString("theme_accent", "")) ?: Color(0xFFFF3DF2)
        accent2 = parseHexColor(prefs.getString("theme_accent2", "")) ?: Color(0xFFB06BFF)
        // 存量兼容：3.7.79 及以前没有 theme_preset，按"色对是否等于某预设"推断
        preset = prefs.getString("theme_preset", "")?.takeIf { it.isNotEmpty() }
            ?: inferPreset(accent, accent2)
        // 3.7.74：历史值 "custom"（相册直选）并入 "panel"——相册图现在先进图库再选用，
        // 已下载的那张仍留在 theme_bg.img 里，照常铺底。
        bgMode = if (prefs.getString("theme_bg", "default") == "default") "default" else "panel"
        bgName = prefs.getString("theme_bg_name", "") ?: ""
        bgVer = prefs.getLong("theme_bg_ver", 0L)
        bgAlpha = prefs.getFloat("theme_bg_alpha", DEFAULT_BG_ALPHA).coerceIn(0f, 1f)
    }

    /** 拖滑条：立即改内存状态（背景实时变），并把值落盘（拖动中也会写，值很小）。 */
    fun setBgAlpha(prefs: SharedPreferences, v: Float) {
        bgAlpha = v.coerceIn(0f, 1f)
        prefs.edit().putFloat("theme_bg_alpha", bgAlpha).apply()
    }

    fun saveColors(prefs: SharedPreferences) {
        prefs.edit()
            .putString("theme_accent", hexOf(accent))
            .putString("theme_accent2", hexOf(accent2))
            .apply()
    }

    /** 记档位（与 saveColors 分开：写色不等于换档，换档也不等于改色）。 */
    fun savePreset(prefs: SharedPreferences, id: String) {
        preset = id
        prefs.edit().putString("theme_preset", id).apply()
    }

    /** 颜色对撞上哪个预设；都不像 → custom（用户以前手动调过的颜色不会被误判成预设）。 */
    fun inferPreset(a: Color, a2: Color): String {
        val h1 = hexOf(a).lowercase()
        val h2 = hexOf(a2).lowercase()
        val hit = THEME_PRESETS.firstOrNull {
            it.accent.removePrefix("#").lowercase() == h1 &&
                it.accent2.removePrefix("#").lowercase() == h2
        }
        return hit?.id ?: "custom"
    }

    /** 记录"当前背景是哪一张"：三件事必须同时落盘，否则重启后版本键与图对不上。 */
    fun saveBg(prefs: SharedPreferences, mode: String, name: String, ver: Long) {
        bgMode = mode
        bgName = name
        bgVer = ver
        prefs.edit().putString("theme_bg", mode).putString("theme_bg_name", name)
            .putLong("theme_bg_ver", ver).apply()
    }
}

/**
 * 十六进制颜色解析（6 位 RGB 或 8 位 ARGB）——**必须补上 alpha**。
 *
 * 3.7.74 事故修复：3.7.73 的预设/自定义色走的是 `Color(hex.toLong(16).toInt())`，
 * 6 位值 `0xFF3DF2` 的 alpha 段是 0，于是选完颜色 ACCENT/ACCENT2 全变**全透明**：
 * 抽屉里选中的语言胶囊（字色 = ACCENT）看不见、主题预设圆点（底色 = ACCENT2）整排消失、
 * 底部胶囊高亮 tab 的深色字压在透明指示条上 → 用户报的"各个功能键都不显示字 / 黑底黑字"。
 * 解析失败返回 null（调用方回退默认色），绝不把坏值写进状态。
 */
internal fun parseHexColor(s: String?): Color? {
    val h = (s ?: "").trim().removePrefix("#").removePrefix("0x").removePrefix("0X")
    if (h.length != 6 && h.length != 8) return null
    val v = h.toLongOrNull(16) ?: return null
    val argb = if (h.length == 6) (0xFF000000L or v) else v
    return Color(argb.toInt())
}

/** Color → 6 位 RGB 十六进制（丢掉 alpha 段；配色表与偏好都用这个写法）。 */
internal fun hexOf(c: Color): String =
    Integer.toHexString(c.toArgb()).let { if (it.length == 8) it else it.padStart(8, '0') }
        .substring(2)