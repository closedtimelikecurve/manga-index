# -*- coding: utf-8 -*-
"""Kotlin 函数级扫描器回归（3.7.43）。

`scripts/quality_gate.py::_kt_functions` 是 Kotlin 函数两维（50 行 / cc 15）的度量口径，
无 AST 全靠括号平衡 + 关键词计数，边界 case 必须钉死：
字符串/注释里的关键字、无体声明、表达式体、嵌套 when、嵌套 fun。

口径契约（与 radon 对齐的 Python 侧保持一致）：
  * 嵌套 fun 是独立单元，不计入父函数圈复杂度；
  * `if`/`while`/`for`/`catch`/`&&`/`||`/`?:` 各 +1，`when` 每分支 +1，基线 1；
  * 无体声明（抽象/接口方法）不出现；
  * 注释与字符串内容一律不计数（块注释可嵌套）。
"""
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE_KT = os.path.join(ROOT, "scripts", "gate_kt.py")


def _load_gate():
    spec = importlib.util.spec_from_file_location("_gate_kt_under_test", GATE_KT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SAMPLE = '''package com.biblioteca.reader

// 行注释里有 fun fake( 和 if 关键字
/* 块注释 /* 嵌套 */ fun nested( */
const val APP_API_LEVEL = 1

class Foo {
    fun small() = 1 + 2

    fun whenBody(k: String): String = when (k) {
        "a" -> "A"
        "b", "c" -> "BC"
        else -> k
    }

    fun stringTpl(name: String): String {
        val s = "hello if while for when { } fun x("
        val t = """
            多行字符串里的 fun y( 和 if
        """
        return "$s $t $name"
    }

    fun longOne(x: Int): Int {
        var r = 0
        if (x > 0) {
            r += 1
        } else if (x < 0) {
            r -= 1
        }
        for (i in 1..10) {
            r += i
        }
        while (r > 100) {
            r -= 10
        }
        try {
            r /= 0
        } catch (e: Exception) {
            r = -1
        }
        if (r > 0 && x > 0) {
            r += 1
        }
        val v = r ?: 0
        return r + v
    }

    fun abstractish(x: Int): String
}

interface Bar {
    fun noBody(x: Int): String
    fun alsoNoBody(): Int
}

private fun <T> List<T>.ext(): List<T> = this

private val lam = { x: Int -> x + 1 }

fun useLambda(items: List<Int>): List<Int> = items.map { it * 2 }

fun interface Click { fun onClick() }
'''


def _scan(src):
    return dict((n, (l, c)) for n, l, c in _load_gate().kt_functions(src))


def test_kt_cc_counts_decision_points():
    """圈复杂度口径：if/else-if/for/while/catch 各 1、`&&` 1、elvis 1，基线 1。"""
    got = _scan(SAMPLE)["longOne"]
    assert got == (24, 9), got


def test_kt_when_branches_counted():
    """when 每个分支（含 else）计 1；表达式体按声明行起算。"""
    got = _scan(SAMPLE)["whenBody"]
    assert got == (5, 4), got


def test_kt_string_and_comment_keywords_not_counted():
    """字符串/注释里的 fun、if、when 既不产生函数也不计复杂度。"""
    got = _scan(SAMPLE)
    assert got["stringTpl"] == (5, 1), got["stringTpl"]
    assert "fake" not in got and "nested" not in got and "y" not in got


def test_kt_bodiless_declarations_skipped():
    """无体声明（抽象/接口方法）不是函数，不进债务表。"""
    got = _scan(SAMPLE)
    assert "abstractish" not in got
    assert "noBody" not in got and "alsoNoBody" not in got


def test_kt_expression_body_one_line():
    """表达式体止于"下一行是新声明"，`fun(...)` 单行体记 1 行。"""
    got = _scan(SAMPLE)
    assert got["small"] == (1, 1), got["small"]
    assert got["ext"] == (1, 1), got["ext"]
    assert got["useLambda"] == (1, 1), got["useLambda"]


def test_kt_fun_interface_not_a_function():
    """`fun interface` 是 SAM 接口，不是函数（正则按名后无参 disqualify）。"""
    assert "Click" not in _scan(SAMPLE)


def test_kt_nested_fun_not_counted_in_parent():
    """嵌套 fun 是独立单元：父函数 cc 不含其内部分支（与 Python 口径一致）。"""
    src = (
        "fun outer(x: Int): Int {\n"
        "    fun inner(y: Int): Int {\n"
        "        if (y > 0) return 1\n"
        "        return 0\n"
        "    }\n"
        "    return inner(x)\n"
        "}\n"
    )
    got = _scan(src)
    assert got["outer"] == (7, 1), got["outer"]      # if 在 inner 里，不计入 outer
    assert got["inner"] == (4, 2), got["inner"]


def test_kt_real_sources_scan_without_crash():
    """冒烟：对全部真实 .kt 跑一遍，函数数与行数合理（不空、不天文数字）。"""
    gate = _load_gate()
    kt_dir = os.path.join(ROOT, "android", "app", "src", "main", "java",
                          "com", "biblioteca", "reader")
    names = [n for n in sorted(os.listdir(kt_dir)) if n.endswith(".kt")]
    assert len(names) >= 10, "源码文件数异常：%s" % names
    for n in names:
        src = open(os.path.join(kt_dir, n), encoding="utf-8").read()
        funcs = gate.kt_functions(src)
        total = len(src.splitlines())
        for name, ln, cc in funcs:
            assert 1 <= ln <= total, f"{n}::{name} 行数 {ln} 越界（文件共 {total} 行）"
            assert cc >= 1, f"{n}::{name} cc {cc} < 1"
