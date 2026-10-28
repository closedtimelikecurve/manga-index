# -*- coding: utf-8 -*-
"""panel/naming.py 单测（3.6.45 Stage4）。

为什么单独建文件：这块规则原先埋在 `app.api_supplement_info` 的请求处理里，只能靠
「起 Flask + 造文献库 + 打 HTTP」间接覆盖；抽成纯函数后可以逐条钉死命名契约
（README「文件名规范格式」）。**本文件不 import app**，不触发扫描/DB/配置副作用。
"""
import djc_parse
from panel import naming


def _analyzed(base=""):
    """解析结果夹具：只喂命名函数真正会读的键，避免依赖 analyze 的全部字段。"""
    return djc_parse.analyze_filename(base)


def test_full_fields_produce_canonical_layout():
    got = naming.canonical_from_fields(
        {"uncensored": True, "event": "C100", "circle": "Part K", "personal": "羊羽忍",
         "title": "タイトル", "original": "原神", "translator": "【兔司姬漢化組】"},
        _analyzed())
    assert got == "[無修正] (C100) [Part K (羊羽忍)] タイトル 【兔司姬漢化組】 (原神)"


def test_blank_form_field_falls_back_to_parsed_value():
    """表单留空 = 沿用解析值（历史行为：空串不等于"清空"）。"""
    a = _analyzed("(C102) [蜂巢 (Apoidea)] 美食殿堂 (プリンセスコネクト!Re_Dive)")
    got = naming.canonical_from_fields({"title": ""}, a)
    assert got == "(C102) [蜂巢 (Apoidea)] 美食殿堂 (プリンセスコネクト!Re_Dive)"


def test_underscore_becomes_space_but_original_term_kept():
    """自由文本 `_` → 空格；原作名走词条规范名，不做替换。"""
    got = naming.canonical_from_fields(
        {"circle": "Part_K", "personal": "矢澤_おけ", "title": "a_b", "original": "Re_Dive"},
        _analyzed())
    assert got == "[Part K (矢澤 おけ)] a b (Re_Dive)"


def test_other_info_drops_terms_already_taken_by_other_columns():
    # 注意：other_info 按空白切词，多词词条（如 "Part K"）会被切成两段而与社团名对不上——
    # 这是历史行为（老客户端的整标题兜底就按空格拆分），此处只钉「单词词条去重」。
    got = naming.canonical_from_fields(
        {"circle": "CircleX", "personal": "A", "title": "T", "other_info": "CircleX C102 T A"},
        _analyzed())
    assert got == "[CircleX (A)] T [C102]"


def test_other_info_keeps_paren_form_when_original_was_paren():
    """(DL版) 回填回 (DL版)，不得被悄悄改成 [DL版]。"""
    a = _analyzed("[社团 (画师)] 标题 (DL版)")
    got = naming.canonical_from_fields({"other_info": "DL版"}, a)
    assert "(DL版)" in got and "[DL版]" not in got


def test_legacy_client_without_other_info_keeps_leftover_brackets():
    """没提交 other_info 栏（老客户端）→ 隐式兜底把剩余词条原样带过来。"""
    a = _analyzed("[社团 (画师)] 标题 [中国語] (DL版)")
    got = naming.canonical_from_fields({"title": "标题"}, a)
    assert got == "[社团 (画师)] 标题 [中国語] (DL版)"


def test_multi_author_uses_injected_canonicalizer():
    calls = []

    def canon(name):
        calls.append(name)
        return name.upper()

    got = naming.canonical_from_fields(
        {"circle": "Duo", "personal": "alice & bob", "title": "t"}, _analyzed(), canon_author=canon)
    assert got == "[Duo (ALICE & BOB)] t"
    assert calls == ["alice", "bob"]


def test_bare_term_preserved_when_no_circle():
    a = _analyzed("[原崎] タイトル")
    got = naming.canonical_from_fields({"circle": "", "personal": ""}, a)
    assert got.startswith("[原崎]")


def test_nothing_to_build_returns_empty():
    """无标题/无词条 → 空串，端点据此回 400（"至少填写名称"）。"""
    assert naming.canonical_from_fields({}, _analyzed()) == ""
