package com.biblioteca.reader

import android.content.SharedPreferences
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import java.util.Locale

/** 3.7.73：多语言框架（§4.6 双端对齐，对齐网页 i18n.js）。
 *
 *  key = 简体中文原文（基准语言，缺译回退 key 本身）；各译语包在 StringsLangs.kt。
 *  [lang] 是 snapshot state——组合期经 [s] 读到它的 Text 在切换语言时自动重组，
 *  全 APP 即时生效，无需重建 Activity。语言偏好存 SharedPreferences 的 "lang" 键，
 *  首次启动按系统 Locale 预填（非库内语言 → en）。 */
object AppI18n {
    /** 支持的语言（label 用各自语言显示），与网页 i18n.js 同表。 */
    val LANGS = listOf(
        "zh-CN" to "简体中文",
        "zh-Hant" to "繁體中文",
        "en" to "English",
        "ja" to "日本語",
        "ko" to "한국어",
        "ru" to "Русский",
        "th" to "ไทย",
        "vi" to "Tiếng Việt",
    )

    var lang by mutableStateOf("zh-CN")

    /** 启动时调用：恢复用户偏好，无偏好按系统语言预填。 */
    fun load(prefs: SharedPreferences) {
        val saved = prefs.getString("lang", null)
        lang = saved ?: detect()
    }

    fun setLang(code: String, prefs: SharedPreferences) {
        lang = code
        prefs.edit().putString("lang", code).apply()
    }

    /** 语言包分层（3.7.87：由写死的 `?:` 链改成列表）。
     *
     *  每个分批新增一个 `I18N_EXTRA<n>` 文件，此前加一批要**同时**改这里的一串 `?:`，
     *  漏一处就是"译文写进了包、界面查不到"（与网页 3.6.135 拆片时踩的坑同型）。
     *  现在新批次只需在列表末尾加一个名字；查找顺序 = 列表顺序，先命中先返回。 */
    private val LAYERS = listOf(
        I18N_PACKS, I18N_EXTRA, I18N_EXTRA2, I18N_EXTRA3, I18N_EXTRA4, I18N_EXTRA5, I18N_EXTRA6,
        I18N_EXTRA7, I18N_EXTRA8, I18N_EXTRA9, I18N_EXTRA10, I18N_EXTRA11, I18N_EXTRA12, I18N_EXTRA13, I18N_EXTRA14, I18N_EXTRA15, I18N_EXTRA16,
        I18N_EXTRA17,
    )

    /** 简中原文 → 当前语言译文（缺译/空译回退原文）。组合期调用可自动重组。
     *  3.7.75：空字符串视同缺译——`?.get()` 对空串不触发 ?:，会让按钮文字整体消失。 */
    fun s(zh: String): String {
        if (lang == "zh-CN") return zh
        for (pack in LAYERS) {
            val v = pack[lang]?.get(zh)
            if (!v.isNullOrEmpty()) return v
        }
        return zh
    }

    /** 3.7.78 模板句翻译：译文里 %1..%9 按序替换成实参（缺译回退中文原文，占位仍在）。 */
    fun sf(fmt: String, vararg args: Any?): String {
        var out = s(fmt)
        args.forEachIndexed { i, a ->
            out = out.replace("%" + (i + 1), a?.toString() ?: "-")
        }
        return out
    }

    private fun detect(): String {
        val loc = Locale.getDefault()
        val lang2 = loc.language.lowercase()
        if (lang2 == "zh") {
            val region = loc.country.lowercase()
            return if (region in setOf("tw", "hk", "mo") || loc.toString().contains("Hant", true)) {
                "zh-Hant"
            } else "zh-CN"
        }
        for (pre in listOf("ja", "ko", "ru", "th", "vi", "en")) {
            if (lang2 == pre) return pre
        }
        return "en"                        // 非库内语言 → 英语
    }
}
