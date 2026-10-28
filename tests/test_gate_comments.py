"""F007 的回归：注释里反引号点名的文件必须真实存在。

规则存在的理由：拆分/改名后注释不跟着改，IDE 与 import 都不会报错，
只有读者会照着注释去找一个已经不在的文件（2026-10-20 的审计扫出 8 处）。
口径保守——只认反引号包裹的文件名、只扫注释、三级路径解析，宁可漏报不可误报。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import gate_comments  # noqa: E402


def _write(root, rel, text):
    p = os.path.join(root, rel)
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def _refs(tmp_path, rel, src):
    gate_comments._CACHE.clear()
    return gate_comments.missing_refs(rel, src, str(tmp_path))


def test_existing_file_by_relative_dir(tmp_path):
    _write(tmp_path, "sub/bar.py", "")
    assert _refs(tmp_path, "root_mod.py", "# 见 `sub/bar.py`") == []


def test_existing_file_by_project_root(tmp_path):
    _write(tmp_path, "top.py", "")
    assert _refs(tmp_path, "deep/nested/mod.py", "# 见 `top.py`") == []


def test_existing_file_by_basename_anywhere(tmp_path):
    _write(tmp_path, "a/b/target.py", "")
    # 从别的目录用短名引用（项目里大量这种写法）
    assert _refs(tmp_path, "x/y.py", "# 拆分见 `target.py`") == []


def test_missing_file_reported(tmp_path):
    _write(tmp_path, "mod.py", "")
    got = _refs(tmp_path, "mod.py", "# 见 `gone.py`")
    assert got == [(1, "gone.py")]


def test_runtime_paths_are_ignored(tmp_path):
    _write(tmp_path, "mod.py", "")
    src = "# 落盘到 `_state/crawl_state.json`，配置在 `config.json`，库是 `meta.db`"
    assert _refs(tmp_path, "mod.py", src) == []


def test_noqa_escapes(tmp_path):
    _write(tmp_path, "mod.py", "")
    assert _refs(tmp_path, "mod.py", "# 旧文件 `gone.py` 已删  # noqa: F007") == []


def test_docstring_is_scanned(tmp_path):
    _write(tmp_path, "mod.py", "")
    got = _refs(tmp_path, "mod.py", '"""迁移到 `gone.py`。"""\nX = 1\n')
    assert got == [(1, "gone.py")]


def test_code_strings_are_not_scanned(tmp_path):
    _write(tmp_path, "mod.py", "")
    assert _refs(tmp_path, "mod.py", 'S = "`gone.py`"\n') == []


def test_js_and_kotlin_line_comments(tmp_path):
    _write(tmp_path, "a.js", "")
    _write(tmp_path, "b.kt", "")
    assert _refs(tmp_path, "a.js", "// 见 `gone.js`\n") == [(1, "gone.js")]
    assert _refs(tmp_path, "b.kt", "/* 见 `gone.kt` */\n") == [(1, "gone.kt")]


def test_both_dims_reported_once_per_line(tmp_path):
    _write(tmp_path, "mod.py", "")
    got = _refs(tmp_path, "mod.py", "# `a_gone.py` 与 `b_gone.py`\n")
    assert [r for _, r in got] == ["a_gone.py", "b_gone.py"]
