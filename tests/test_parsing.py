# -*- coding: utf-8 -*-
"""djc_parse 文件名解析规则与 common 工具的回归测试（对照 README 文档示例）。

覆盖：
  * parse_filename：社团/个人/汉化组/展会/原作/画师/其他词条、冲突处理、
    待定词条（裸 []）、全汉化组 → 无社团、Windows 保留设备名
  * normalize_filename：README 规范格式、_ → 空格、原作词条规范名保留
  * common.unique_path：绝不覆盖（含 taken 占位）
"""
import os
import sys

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import djc_parse as dp  # noqa: E402
import common  # noqa: E402

ORIGINALS, N2C = dp.load_originals(None)


def parse(name):
    return dp.parse_filename(name, ORIGINALS, N2C)


def tags_of(parsed, t):
    return [n for tt, n in parsed["tags"] if tt == t]


def test_readme_example_full():
    """README 表格示例：(C100) [Part K (羊羽忍)] タイトル (原神) [漢化组].zip"""
    r = parse("(C100) [Part K (羊羽忍)] タイトル (原神) [漢化组].zip")
    assert r["circle"] == "Part K"
    assert r["personal"] == "羊羽忍"
    assert tags_of(r, "event") == ["C100"]
    assert tags_of(r, "personal") == ["羊羽忍"]
    assert tags_of(r, "original") == ["原神"]


def test_bracket_with_author():
    """冲突处理：[] 同时含社团和作者时，以 () 提取的作者为准作为个人名。"""
    r = parse("[社团X (作者Y)] 某作品.zip")
    assert r["circle"] == "社团X"
    assert r["personal"] == "作者Y"


def test_bare_bracket_pending_term():
    """[] 内无 ()：词条本身成为待定词条（bare，与其它社团同级建新档）。"""
    r = parse("[みちきんぐ] 単体作品.zip")
    assert r["circle"] == ""
    assert r["bare"] == "みちきんぐ"


def test_all_group_terms_no_circle():
    """全部 [] 都是汉化组词条 → 无社团（归入收件箱）。"""
    r = parse("[中国翻訳] [某汉化组] 作品.zip")
    assert r["circle"] == "" and r["personal"] == ""


def test_translation_tag_not_circle():
    """词条括号本身是翻译标签 → 不作为社团。"""
    r = parse("[中国翻訳] タイトル.zip")
    assert r["circle"] != "中国翻訳"


def test_event_patterns():
    for ev in ("C101", "FF36", "COMIC1☆15"):
        r = parse(f"({ev}) [社团] 作品.zip")
        assert tags_of(r, "event") == [ev], ev


def test_normalize_readme_example():
    """README 规范格式示例（含 _ → 空格 与原作词条规范名保留）。"""
    out = dp.normalize_filename(
        "[無修正](FF35) [蜂巢 (Apoidea)] 美食殿堂的愉快秘境大探險♡_ 【切嚕系女子個人搬運】 "
        "(プリンセスコネクト!Re_Dive) [中国語] [DL版]", ".zip")
    assert out == ("[無修正] (FF35) [蜂巢 (Apoidea)] 美食殿堂的愉快秘境大探險♡ 【切嚕系女子個人搬運】 "
                   "(プリンセスコネクト!Re_Dive) [中国語] [DL版].zip")


def test_sanitize_windows_reserved_names():
    assert dp.sanitize_windows_name("CON") == "_CON"
    assert dp.sanitize_windows_name("nul.txt") == "_nul.txt"
    assert dp.sanitize_windows_name("LPT9") == "_LPT9"
    assert dp.sanitize_windows_name("COM10") == "COM10"      # COM10 不是保留名
    assert dp.sanitize_windows_name("AUX.") == "_AUX"        # 结尾点先被剥掉再判定
    assert dp.sanitize_windows_name("正常名字") == "正常名字"
    assert dp.sanitize_windows_name('a<b>c:d"e/f\\g|h?i*j') == "a b c d e f g h i j"


def test_unique_path_never_overwrites(tmp_path):
    free = tmp_path / "free.zip"
    assert common.unique_path(str(free)) == str(free)          # 不存在 → 原样
    a = tmp_path / "file.zip"
    a.write_bytes(b"x")
    b = tmp_path / "file (2).zip"
    b.write_bytes(b"y")
    got = common.unique_path(str(a))
    assert got == str(tmp_path / "file (3).zip") and not os.path.exists(got)
    assert common.unique_path(str(a), taken={got}) == str(tmp_path / "file (4).zip")
