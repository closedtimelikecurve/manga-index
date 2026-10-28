# -*- coding: utf-8 -*-
"""panel/terms.py —— 原作词条名单与加载（3.6.64 从 djc_parse.py 拆出）。

只依赖 `json` + `panel.text._norm`，不读业务状态：
  * `DEFAULT_ORIGINALS`：内置常见原作名单（可被 config.json 的 originals 扩展）；
  * `load_originals(config_path)`：返回 (名单, 归一键→规范名映射)；
  * `_skip_term`：该括号是否该跳过（汉化组/無修正/语言标记/带"禁漫"）。

`djc_parse` 再导出这三个名字，历史调用点不变。
"""
import json
import logging

log = logging.getLogger(__name__)

from panel.text import _norm

GROUP_KEYWORDS = ["汉化", "漢化", "中国翻訳", "中国語", "搬運", "搬运", "個人", "个人"]


def is_group_term(s):
    """判断是否为汉化组词条（含关键词则视为汉化组，不作社团/个人名）。"""
    return any(k in s for k in GROUP_KEYWORDS)


DEFAULT_ORIGINALS = [
    # 常见原作名单（可扩展：在 config.json 的 "originals" 数组追加，自动去重合并）
    "東方Project", "東方",
    "ブルーアーカイブ", "ブルアカ", "Blue Archive",
    "オリジナル", "原神",
    "Fate", "Fate／Grand Order", "FateGrand Order", "FGO",
    "艦これ", "艦隊これくしょん -艦これ-",
    "アズールレーン", "ローゼンメイデン", "不思議の国のアリス",
    "フラワーナイトガール", "グランブルーファンタジー", "五等分の花嫁",
    "アイドルマスター", "アイドルマスター シンデレラガールズ", "デレマス", "シャニマス",
    "ご注文はうさぎですか",
    "ポケットモンスター", "ウマ娘", "ホロライブ",
    "推しの子", "メイドインアビス", "鬼滅の刃", "呪術廻戦",
    "リコリス・リコイル", "プリコネ", "公主連結", "バンドリ", "ラブライブ",
    "ダンまち", "NIKKE", "ゼンゼロ", "雀魂", "ブルーロック",
    "ぼっち・ざ・ろっく", "孤独摇滚", "シュタインズゲート", "Steins;Gate",
    "干物妹! うまるちゃん", "干物妹！小埋", "エロマンガ先生", "情色漫画老师",
    "かぐや様は告らせたい", "輝夜大小姐", "その着せ替え人形は恋をする", "更衣人偶坠入爱河",
    "プリンセスコネクト", "プリンセスコネクト!Re_Dive", "プリコネ", "公主连结",
]


def load_originals(config_path=None):
    """默认原作名单 + config.json 追加项，返回 (列表, 归一化→规范名映射)。"""
    norm_to_canon = {}
    for x in DEFAULT_ORIGINALS:
        norm_to_canon.setdefault(_norm(x), x)
    if config_path:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            extra = data.get("originals") or []
            if isinstance(extra, list):
                for x in extra:
                    x = str(x).strip()
                    if x:
                        norm_to_canon.setdefault(_norm(x), x)
        except (OSError, ValueError, AttributeError):
            # config.json 缺失/损坏时继续用内置名单（首启动即这个状态）。
            # 不用 `except Exception: pass`：吞掉一切会让"名单被写坏"完全不可见。
            log.debug("读取 config.json 的 originals 失败，本轮只用内置名单", exc_info=True)
    return list(norm_to_canon.values()), norm_to_canon


def _skip_term(b):
    """该括号是否应跳过（汉化组 / 无修正 / 语言标记 / 带"禁漫"字样的词条）。"""
    if is_group_term(b) or "無修正" in b or b in ("中国翻訳", "中国語"):
        return True
    if "禁漫" in b:      # 用户规则：带"禁漫"二字的词条不视为社团名/作者名（如 禁漫汉化组）
        return True
    return False
