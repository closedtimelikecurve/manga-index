# 内置主题图库 · 来源与许可

本目录 9 张图是「主题 → 图库」里永远排在最前的**内置图**（不可删除）。
注册表在 `services/theme_store.py` 的 `BUILTIN_ITEMS`，顺序即列表顺序。

| 文件 | 标题（i18n key） | 来源 | 许可 | 处理 |
|---|---|---|---|---|
| `b01_default_bg.jpg` | 默认背景图 | 项目原有 `static/img/bg.jpg` | 项目自带资源 | 重编码 JPEG q72，未缩放、未裁切 |
| `b02_default_hero.jpg` | 默认横幅 | 项目原有 `static/img/hero.jpg` | 项目自带资源 | 重编码 JPEG q72，未缩放、未裁切 |
| `b03_unsplash_fjord.jpg` | 峡湾 | Alexey Topolyanskiy · <https://unsplash.com/photos/-oWyJoSqBRM>（经 Lorem Picsum id 1015 取图） | [Unsplash License](https://unsplash.com/license)（可免费商用，无需署名；此处署名以示尊重） | 1600×1000 cover 裁切，JPEG q82 |
| `b04_unsplash_mist.jpg` | 雾林 | Steve Carter · <https://unsplash.com/photos/Ixp4YhCKZkI>（经 Lorem Picsum id 1044 取图） | 同上 | 1600×1000 cover 裁切，JPEG q76 |
| `b05_unsplash_jelly.jpg` | 水母 | Marat Gilyadzinov · <https://unsplash.com/photos/wpTWYBll4_w>（经 Lorem Picsum id 1069 取图） | 同上 | 1600×1000 cover 裁切，JPEG q82 |
| `b06_draw_neon.jpg` | 霓虹网格 | 本仓库脚本生成 | 项目自有（程序生成，无第三方权利） | `python scripts/gen_theme_gallery.py --draw`（seed 20261026） |
| `b07_draw_jade.jpg` | 翡翠涟漪 | 同上 | 同上 | 同上 |
| `b08_draw_dusk.jpg` | 暮色条纹 | 同上 | 同上 | 同上 |
| `b09_default_mobile.jpg` | 默认背景图（手机） | 项目原有 `static/img/side.jpg`（APP `R.drawable.settings_bg` 的源图，3.6.127 补进图库） | 项目自带资源 | 重编码 JPEG q72，未缩放、未裁切 |

说明：

1. 三张手绘图由 `scripts/gen_theme_gallery.py` **确定性生成**（固定随机种子），
   改样式就改脚本再重跑，产物与脚本必须一起提交。
2. 网络图只在开发期下载一次并重编码，**构建/运行时都不联网**。
   如需替换，保持文件名不变（注册表引用文件名），并同步更新本表。
3. 所有图均做过内容检查：无人物、无文字、无敏感内容，适合作为应用背景。
