package com.biblioteca.reader

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * 3.7.52：别名树（一组 = 若干别名 ↳ 同一个正名）。
 *
 * 历史：3.7.41 用的是「左侧别名 / 右侧正名 + 曲线汇集」的横向树，行高与列宽全是定值
 * （左列 46%、正名列 34%、每行 46dp），文字只能单行省略——长笔名、长原作名永远看不全。
 * 用户要求"必须把词条完全展开显示"，而定值行高与"展开"天然冲突，于是改成**纵向树**：
 * 正名在上（胶囊，占满宽度、可换行），别名逐条缩进挂在下面（`↳` 分支符号，同样可换行）。
 * 归属关系由"同一张卡 + 分支符号"表达，不再依赖曲线。
 *
 * 交互（3.7.52 同时落地）：
 *  * **点正名** = 给这个正名添加别名（唤起弹窗，正名已预填）；
 *  * **长按正名 / 别名** = 复制该词条（与全站标签一致，走 `tagClickable` / `tagCopy`）；
 *  * **✕** = 解除该条别名登记（本页是别名管理页，撤销入口必须有出口）。
 *
 * 3.7.53：**原作正名 = 原作分区名**（`canRenameCanon`）。原作名不在文件名里，分区名就是
 * DB 里的 original 标签，所以"改正名"等价于"改同人区名"——一键进入改名弹窗；服务端改名时
 * 会把旧正名自动登记为别名，本页的别名树随即以新正名为根、旧正名作为一条别名出现。
 */
@Composable
fun AliasTree(groups: Map<String, List<String>>, onDelete: (String) -> Unit,
              onCanonClick: (String) -> Unit = {},
              canRenameCanon: Boolean = false, onRenameCanon: (String) -> Unit = {}) {
    groups.forEach { (canon, aliases) ->
        AliasGroupCard(canon, aliases, onDelete, onCanonClick, canRenameCanon, onRenameCanon)
    }
}

/** 一个正名 + 它名下的全部别名（3.7.52：整组包一张卡，视觉上是一棵树的一支）。 */
@Composable
private fun AliasGroupCard(canon: String, aliases: List<String>,
                           onDelete: (String) -> Unit, onCanonClick: (String) -> Unit,
                           canRenameCanon: Boolean, onRenameCanon: (String) -> Unit) {
    Column(Modifier.fillMaxWidth().padding(vertical = 5.dp)
        .clip(RoundedCornerShape(12.dp)).background(CARD_BG)
        .border(1.dp, Color(0x1AFFFFFF), RoundedCornerShape(12.dp))
        .padding(10.dp)) {
        CanonHeader(canon, canRenameCanon, onRenameCanon)
        CanonChip(canon, onCanonClick)
        aliases.forEach { AliasNode(it, onDelete) }
    }
}

/** 正名行头：左边是操作提示，右边（仅原作）是「改区名」入口（3.7.53）。 */
@Composable
private fun CanonHeader(canon: String, canRename: Boolean, onRename: (String) -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(AppI18n.s("正名 · 点按添加别名"), color = MUTED, fontSize = 10.sp,
            modifier = Modifier.weight(1f))
        if (canRename) {
            Text(AppI18n.s("✏ 改区名"), color = ACCENT, fontSize = 10.sp,
                modifier = Modifier.clip(RoundedCornerShape(999.dp))
                    .background(ACCENT.copy(alpha = 0x22 / 255f))
                    .clickable { onRename(canon) }
                    .padding(horizontal = 8.dp, vertical = 3.dp))
        }
    }
}

/** 正名胶囊：**不设 maxLines**——词条必须完整显示（点击加别名、长按复制）。 */
@Composable
private fun CanonChip(canon: String, onCanonClick: (String) -> Unit) {
    Text(canon, color = ACCENT, fontSize = 13.sp, lineHeight = 18.sp,
        modifier = Modifier.fillMaxWidth().padding(top = 3.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(ACCENT.copy(alpha = 0x26 / 255f))
            .border(1.dp, ACCENT, RoundedCornerShape(10.dp))
            .tagClickable(canon) { onCanonClick(canon) }
            .padding(horizontal = 12.dp, vertical = 8.dp))
}

/** 一条别名：`↳` 分支 + 完整词条（长按复制）+ ✕ 解除登记。 */
@Composable
private fun AliasNode(alias: String, onDelete: (String) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(top = 6.dp), verticalAlignment = Alignment.Top) {
        Text("↳", color = ACCENT.copy(alpha = 0x99 / 255f), fontSize = 13.sp,
            modifier = Modifier.padding(top = 4.dp))
        Text(alias, color = TXT, fontSize = 12.sp, lineHeight = 17.sp,
            modifier = Modifier.weight(1f).padding(start = 4.dp)
                .clip(RoundedCornerShape(8.dp))
                .background(CARD_BG2)
                .tagCopy(alias)
                .padding(horizontal = 10.dp, vertical = 6.dp))
        Text("✕", color = Color(0x88FF6B8B), fontSize = 13.sp,
            modifier = Modifier.clickable { onDelete(alias) }
                .padding(horizontal = 8.dp, vertical = 6.dp))
    }
}
