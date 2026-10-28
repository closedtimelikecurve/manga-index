package com.biblioteca.reader

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/* ================================================================
   阅读器 · 顶栏（3.7.43 从 ReaderScreen.kt 拆出）
   悬浮 overlay、可沉浸隐藏：返回 + 标题（可展开）+ 音声开关 + 模式胶囊 + 版本 chips。
   ================================================================ */

@Composable
internal fun ReaderTopBar(source: ReaderSource, ui: ReaderUiState, hasAudio: Boolean, audioOn: Boolean,
                 onAudioToggle: () -> Unit, onExit: () -> Unit, onTitleRect: (IntRect) -> Unit,
                 modifier: Modifier = Modifier) {
    AnimatedVisibility(
        visible = ui.barsVisible,
        enter = fadeIn() + expandVertically(expandFrom = Alignment.Top),
        exit = fadeOut() + shrinkVertically(shrinkTowards = Alignment.Top),
        modifier = modifier
    ) {
        Column(Modifier.fillMaxWidth().background(Color(0x99060411))) {
            Row(Modifier.fillMaxWidth().padding(12.dp, 8.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text("←", color = Color(0xFFF2EEFA), fontSize = 20.sp,
                    modifier = Modifier.clickable { onExit() }.padding(end = 10.dp))
                Text(source.displayTitle, color = Color(0xFFF2EEFA), fontSize = 13.sp,
                    modifier = Modifier.weight(1f)
                        .onGloballyPositioned { p ->
                            onTitleRect(IntRect(
                                p.positionInRoot().x.toInt(), p.positionInRoot().y.toInt(),
                                (p.positionInRoot().x + p.size.width).toInt(),
                                (p.positionInRoot().y + p.size.height).toInt()))
                        }
                        .clickable { ui.titleOpen = true; ui.interact() },
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (hasAudio) {
                    Text("🎧", color = if (audioOn) ACCENT2 else Color(0xFF9A8FB8),
                        fontSize = 15.sp,
                        modifier = Modifier.clickable { onAudioToggle() }
                            .padding(horizontal = 8.dp))
                }
                Row(Modifier.clip(RoundedCornerShape(999.dp)).background(Color(0x1AFFFFFF))) {
                    ModePill("📖", ui.mode == "page") { ui.switchMode("page") }
                    ModePill("📜", ui.mode == "scroll") { ui.switchMode("scroll") }
                }
            }
            // ---- 3.4.0 多版本切换 chips(汉化版/日文原版…),点击即整卷切换该版本 ----
            if (ui.versions.size >= 2) {
                ReaderVersionChips(ui)
            }
        }
    }
}

/** 多版本切换 chips（3.7.43 从顶栏抽出）：当前版本粉底，点击整卷切换。 */
@Composable
private fun ReaderVersionChips(ui: ReaderUiState) {
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())
        .padding(horizontal = 12.dp, vertical = 2.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        ui.versions.forEachIndexed { vi, v ->
            val on = vi == ui.selVersion
            Text(v.name, color = if (on) Color(0xFF1C1433) else Color(0xFF9A8FB8),
                fontSize = 11.sp, maxLines = 1,
                modifier = Modifier.clip(RoundedCornerShape(999.dp))
                    .background(if (on) ACCENT2 else Color(0x1AFFFFFF))
                    .clickable { ui.versionJump(vi) }
                    .padding(horizontal = 10.dp, vertical = 4.dp))
        }
    }
}
