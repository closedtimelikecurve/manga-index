package com.biblioteca.reader

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/* ================================================================
   3.7.74：🌐 语言二级界面（用户要求：语言、主题各自独立成页）。
   8 语言单选，选中即时生效——AppI18n.lang 是 snapshot state，全 APP 重组。
   ================================================================ */

private val LANG_LINE = Color(0x24FFFFFF)

@Composable
internal fun LangScreen(onBack: () -> Unit) {
    val ctx = LocalContext.current
    val prefs = remember { ThemeActions.prefs(ctx) }
    BackHandlerOn(onBack)                                  // 3.6.124：系统返回键不再退出 App
    Column(Modifier.fillMaxSize()) {
        TopBar("🌐 " + AppI18n.s("语言"), onBack)
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp)) {
            Text(AppI18n.s("界面语言说明"), color = MUTED, fontSize = 12.sp, lineHeight = 18.sp,
                modifier = Modifier.padding(top = 8.dp, bottom = 10.dp))
            AppI18n.LANGS.forEach { (code, label) ->
                LangRow(code, label, on = AppI18n.lang == code) { AppI18n.setLang(code, prefs) }
            }
        }
    }
}

/** 一行语言：本语言名 + 语言代码 + 选中勾；点整行即切换（偏好落 SharedPreferences）。 */
@Composable
private fun LangRow(code: String, label: String, on: Boolean, onPick: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(bottom = 8.dp).clip(RoundedCornerShape(12.dp))
        .background(if (on) ACCENT.copy(alpha = 0.14f) else CARD_BG2)
        .border(1.dp, if (on) ACCENT else LANG_LINE, RoundedCornerShape(12.dp))
        .clickable { onPick() }.padding(horizontal = 14.dp, vertical = 13.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(label, color = if (on) ACCENT else TXT, fontSize = 15.sp,
            modifier = Modifier.weight(1f))
        Text(code, color = MUTED, fontSize = 11.sp)
        if (on) Text("✓", color = ACCENT, fontSize = 14.sp, modifier = Modifier.padding(start = 10.dp))
    }
}