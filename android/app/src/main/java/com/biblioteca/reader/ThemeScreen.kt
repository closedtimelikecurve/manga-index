package com.biblioteca.reader

import android.content.Context
import android.content.SharedPreferences
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage

/* ================================================================
   3.7.74：🎨 主题二级界面（用户要求：语言、主题各自独立成页，
   不再挤在抽屉里）。配色 + 取色器 + 背景图库入口。
   3.7.80：加「自定义」档——预设档主副色只读展示，只有自定义档能调色。
   ================================================================ */

private val SEC_LINE = Color(0x24FFFFFF)
private const val CUSTOM_ID = "custom"

@Composable
internal fun ThemeScreen(onBack: () -> Unit, onOpenGallery: () -> Unit = {}) {
    val ctx = LocalContext.current
    val prefs = remember { ThemeActions.prefs(ctx) }
    var picker by remember { mutableStateOf("") }          // "" | "accent" | "accent2"
    BackHandlerOn(onBack)                                  // 3.6.124：系统返回键不再退出 App
    val custom = ThemePrefs.preset == CUSTOM_ID
    Column(Modifier.fillMaxSize()) {
        TopBar("🎨 " + AppI18n.s("主题"), onBack)
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp)) {
            SectionTitle(AppI18n.s("主题色"))
            PresetRow(prefs)
            if (custom) {
                ColorRow(AppI18n.s("主色"), ThemePrefs.accent) { picker = "accent" }
                ColorRow(AppI18n.s("副色"), ThemePrefs.accent2) { picker = "accent2" }
            } else {
                ColorRowReadOnly(AppI18n.s("主色"), ThemePrefs.accent)
                ColorRowReadOnly(AppI18n.s("副色"), ThemePrefs.accent2)
            }
            Text(if (custom) AppI18n.s("拖动色块调整主色与副色，选完立即生效")
                           else AppI18n.s("预设配色不可单独调整，选择「自定义」后可微调"),
                color = MUTED, fontSize = 11.sp, lineHeight = 16.sp,
                modifier = Modifier.padding(top = 6.dp))
            Spacer(Modifier.height(18.dp))
            // 3.7.76：图库升三级界面（§4.6 对齐网页），主题页只留入口 + 当前背景预览
            Row(Modifier.fillMaxWidth()
                .clip(RoundedCornerShape(12.dp))
                .background(CARD_BG2)
                .clickable { onOpenGallery() }
                .padding(horizontal = 14.dp, vertical = 13.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text("🖼 " + AppI18n.s("打开图库"), color = TXT, fontSize = 14.sp,
                    modifier = Modifier.weight(1f))
                Text("›", color = MUTED, fontSize = 16.sp)
            }
            Spacer(Modifier.height(10.dp))
            BgPreview(ctx)
            AlphaRow(prefs)
            Spacer(Modifier.height(28.dp))
        }
    }
    if (picker.isNotEmpty()) ColorPickerFor(picker, prefs) { picker = "" }
}

/** 取色器弹窗：选中的是主色还是副色由 [target] 决定，确认即写偏好（改色一律归入自定义档）。 */
@Composable
private fun ColorPickerFor(target: String, prefs: SharedPreferences, onClose: () -> Unit) {
    val isMain = target == "accent"
    HsvColorDialog(
        initial = if (isMain) ThemePrefs.accent else ThemePrefs.accent2,
        title = AppI18n.s(if (isMain) "主色" else "副色"),
        onDismiss = onClose,
        onPick = { c ->
            if (isMain) ThemePrefs.accent = c else ThemePrefs.accent2 = c
            ThemePrefs.saveColors(prefs)
            ThemePrefs.savePreset(prefs, CUSTOM_ID)
            onClose()
        })
}

@Composable
internal fun SectionTitle(text: String) {
    Text(text, color = MUTED, fontSize = 12.sp,
        modifier = Modifier.padding(top = 8.dp, bottom = 8.dp))
}

/** 预设配色：6 套 + 「自定义」，点一下换档（预设同时把主副色一起换）。 */
@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
private fun PresetRow(prefs: SharedPreferences) {
    FlowRowCompat(horizontalArrangement = Arrangement.spacedBy(12.dp),
                  verticalArrangement = Arrangement.spacedBy(8.dp)) {
        THEME_PRESETS.forEach { p ->
            val c1 = parseHexColor(p.accent) ?: return@forEach
            val c2 = parseHexColor(p.accent2) ?: return@forEach
            PresetDot(p.name, ThemePrefs.preset == p.id, onClick = {
                ThemePrefs.accent = c1
                ThemePrefs.accent2 = c2
                ThemePrefs.saveColors(prefs)
                ThemePrefs.savePreset(prefs, p.id)
            }, content = { PresetSwatch(c1, c2) })
        }
        // 自定义：彩虹环 = "自己调"；点它保留当前颜色，只把档位切到 custom
        PresetDot("自定义", ThemePrefs.preset == CUSTOM_ID, onClick = {   // i18n:data key 定义
            ThemePrefs.savePreset(prefs, CUSTOM_ID)
        }, content = { CustomRing() })
    }
}

/** 一个预设卡（圆点 + 完整名称）：名称用 i18n key，选中态用主色高亮。 */
@Composable
private fun PresetDot(name: String, on: Boolean, onClick: () -> Unit,
                      content: @Composable () -> Unit) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Box(Modifier.size(34.dp).clip(CircleShape)
            .border(2.dp, if (on) TXT else SEC_LINE, CircleShape)
            .clickable { onClick() }, contentAlignment = Alignment.Center) { content() }
        Text(AppI18n.s(name), color = if (on) ACCENT else MUTED, fontSize = 9.sp, maxLines = 1)
    }
}

@Composable
private fun PresetSwatch(c1: Color, c2: Color) {
    Box(Modifier.size(34.dp).clip(CircleShape)
        .background(Brush.linearGradient(listOf(c1, c2))))
}

@Composable
private fun CustomRing() {
    Box(Modifier.size(34.dp).clip(CircleShape).background(Brush.sweepGradient(listOf(
        Color(0xFFFF3DF2), Color(0xFF4DC9FF), Color(0xFF3DFFB8),
        Color(0xFFFFB347), Color(0xFFFF3DF2)))), contentAlignment = Alignment.Center) {
        Box(Modifier.size(20.dp).clip(CircleShape).background(BG))
    }
}

/** 自定义档：整行可点，打开取色器。 */
@Composable
private fun ColorRow(label: String, cur: Color, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(top = 9.dp).clip(RoundedCornerShape(12.dp))
        .background(CARD_BG2).border(1.dp, SEC_LINE, RoundedCornerShape(12.dp))
        .clickable { onClick() }.padding(12.dp),
        verticalAlignment = Alignment.CenterVertically) {
        ColorChip(cur)
        Text(label, color = TXT, fontSize = 14.sp,
            modifier = Modifier.padding(start = 12.dp).weight(1f))
        Text("#" + hexOf(cur), color = MUTED, fontSize = 12.sp)
        Text("🎨", fontSize = 15.sp, modifier = Modifier.padding(start = 8.dp))
    }
}

/** 预设档：同样的视觉，但**不可点、没有取色器**（预设就是预设）。 */
@Composable
private fun ColorRowReadOnly(label: String, cur: Color) {
    Row(Modifier.fillMaxWidth().padding(top = 9.dp).clip(RoundedCornerShape(12.dp))
        .background(CARD_BG2).border(1.dp, SEC_LINE, RoundedCornerShape(12.dp)).padding(12.dp),
        verticalAlignment = Alignment.CenterVertically) {
        ColorChip(cur)
        Text(label, color = TXT, fontSize = 14.sp,
            modifier = Modifier.padding(start = 12.dp).weight(1f))
        Text("#" + hexOf(cur), color = MUTED, fontSize = 12.sp)
    }
}

@Composable
private fun ColorChip(cur: Color) {
    Box(Modifier.size(30.dp).clip(RoundedCornerShape(9.dp)).background(cur)
        .border(1.dp, SEC_LINE, RoundedCornerShape(9.dp)))
}

/** 背景图预览（当前启用的一张 / 默认图），图库网格在 ThemeGalleryScreen.kt。 */
@Composable
internal fun BgPreview(ctx: Context, height: Int = 96) {
    val file = ThemeActions.localBg(ctx)
    val active = ThemePrefs.bgMode != "default" && file.exists()
    Box(Modifier.fillMaxWidth().height(height.dp).clip(RoundedCornerShape(12.dp))
        .background(CARD_BG2).border(1.dp, SEC_LINE, RoundedCornerShape(12.dp))) {
        if (active) {
            AsyncImage(model = file, contentDescription = null,
                contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        } else {
            Image(painterResource(R.drawable.settings_bg), contentDescription = null,
                contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        }
        Text(if (active) AppI18n.s("使用中") else AppI18n.s("默认背景图"),
            color = TXT, fontSize = 10.sp,
            modifier = Modifier.align(Alignment.BottomStart).padding(6.dp)
                .clip(RoundedCornerShape(999.dp)).background(Color(0xB3060411))
                .padding(horizontal = 8.dp, vertical = 3.dp))
    }
}

/** 背景图不透明度（3.7.85 用户需求①）：**拖动时实时生效**。
 *
 *  拖动中只写内存状态（`ThemePrefs.bgAlpha` 是 snapshot 状态，根容器的
 *  `ThemeBackground` 立即重组重绘，所见即所得）；松手才落盘，避免每帧写一次
 *  SharedPreferences。0% = 只要纯底色，100% = 原图。 */
@Composable
private fun AlphaRow(prefs: SharedPreferences) {
    val v = ThemePrefs.bgAlpha
    Column(Modifier.fillMaxWidth().padding(top = 8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(AppI18n.s("背景不透明度"), color = TXT, fontSize = 13.sp,
                modifier = Modifier.weight(1f))
            Text("%d%%".format(Math.round(v * 100)), color = ACCENT, fontSize = 12.sp)
        }
        Slider(
            value = v,
            onValueChange = { ThemePrefs.bgAlpha = it },          // 实时预览，不落盘
            onValueChangeFinished = { ThemePrefs.setBgAlpha(prefs, ThemePrefs.bgAlpha) },
            valueRange = 0f..1f,
            colors = SliderDefaults.colors(thumbColor = ACCENT, activeTrackColor = ACCENT),
            modifier = Modifier.fillMaxWidth())
        Text(if (ThemePrefs.bgName == BLACK_ITEM) AppI18n.s("当前是「纯黑」背景，不透明度不生效")
             else AppI18n.s("0% 只留底色，100% 显示原图"),
            color = MUTED, fontSize = 10.5.sp, lineHeight = 15.sp)
    }
}
