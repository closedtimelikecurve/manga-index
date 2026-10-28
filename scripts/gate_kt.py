#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/gate_kt.py —— Kotlin 函数级测量（quality_gate.py 的 .kt 专用模块）。

为什么单独一个模块：Kotlin 无 `ast`，函数两维（50 行 / cc 15）靠括号平衡扫描器近似，
逻辑量足够单开一块；拆开后 `quality_gate.py` 本体守住 800/400 的文件预算。

口径（比 radon 粗，**烟报器不是精算仪**，临界 case 以 review 为准）：
  * 先掩码注释与字符串（Kotlin 块注释**可嵌套**，须深度计数；三引号字符串按整体掩码）；
  * 函数体 = `fun` 关键字后第一个 `{...}`（括号配对），或 `=` 表达式体
    （括号归零后，下一非空行以声明起点/`}` 开头即结束——Kotlin 无语句结束符）；
  * 圈复杂度：基线 1 + `if`/`while`/`for`/`catch`/`&&`/`||`/`?:` 各 1 + `when` 每分支 1；
  * 嵌套 fun 是独立单元，不计入父函数（与 Python 侧 `_cc` 口径一致）；
  * 无体声明（抽象/接口方法）不是函数；`fun interface`（SAM）不是函数。

回归：tests/test_gate_kt_scan.py。
"""
import re

_KT_FUN = re.compile(r"(?<![\w.])fun\s+(?:<[^\n{}]*>\s*)?(?:[\w.]+(?:<[^\n{}]*>)?\.)?(\w+)\s*[(<]")
_KT_DECL_START = re.compile(r"^(?:fun|val|var|class|object|interface|enum|data|sealed|"
                            r"abstract|open|const|typealias|suspend|override|companion|"
                            r"init|private|internal|public|protected|@|import|package)\b")


def kt_functions(src):
    """扫描 Kotlin 源码，返回 [(函数名, 行数, 近似cc)]（含局部/嵌套 fun，各自独立计）。"""
    masked = _mask_kt(src)
    starts = _line_index(masked)
    spans = []
    for m in _KT_FUN.finditer(masked):
        r = _kt_body_end(masked, m.start(), starts)
        if r:
            spans.append((m.group(1), r[0], r[1]))
    return [(name, e - s + 1, _kt_cc(masked, s, e, spans))
            for name, s, e in spans]


# --------------------------------------------------------------------------
# 掩码：注释与字符串内容替换为空格（保留换行 → 行号不变）
# --------------------------------------------------------------------------

def _mask_kt(src):
    """逐字符扫描：注释/字符串内容换成空格，其余原样保留（行结构不变）。"""
    out = []
    i, n, depth = 0, len(src), 0
    while i < n:
        if depth:                                   # 块注释内（可嵌套）
            if src.startswith("/*", i):
                depth += 1
                out.append("  ")
                i += 2
            elif src.startswith("*/", i):
                depth -= 1
                out.append("  ")
                i += 2
            else:
                out.append("\n" if src[i] == "\n" else " ")
                i += 1
            continue
        if src.startswith("/*", i):
            depth = 1
            out.append("  ")
            i += 2
        elif src.startswith("//", i):               # 行注释掩到行尾
            j = _line_end(src, i, n)
            out.append(" " * (j - i))
            i = j
        elif src[i] == '"':                          # 字符串（含三引号）
            j = _string_end(src, i, n)
            out.append(" " * (j - i))
            i = j
        elif src[i] == "'":                          # 字符字面量
            j = _char_end(src, i, n)
            out.append(" " * (j - i))
            i = j
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


def _line_end(src, i, n):
    j = src.find("\n", i)
    return n if j < 0 else j


def _string_end(src, i, n):
    """字符串结束下标（开引号在后）：三引号整体掩码，普通串遇到未转义引号/行尾止。"""
    if src.startswith('"""', i):
        j = i + 3
        while j < n and not src.startswith('"""', j):
            j += 1
        return min(j + 3, n)
    j = i + 1
    while j < n and src[j] not in '"\n':
        j += 2 if src[j] == "\\" else 1
    return min(j + 1, n)


def _char_end(src, i, n):
    j = i + 1
    while j < n and src[j] not in "'\n":
        j += 2 if src[j] == "\\" else 1
    return min(j + 1, n)


# --------------------------------------------------------------------------
# 函数体定位
# --------------------------------------------------------------------------

def _line_index(masked):
    """每行起始字符下标表（配合 line_of 把字符下标换成 1-based 行号）。"""
    starts, off = [], 0
    for ln in masked.split("\n"):
        starts.append(off)
        off += len(ln) + 1
    return starts


def _line_of(starts, idx):
    """字符下标 → 1-based 行号。"""
    lo, hi = 0, len(starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if starts[mid] <= idx:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1


def _kt_brace_end(masked, open_idx):
    """open_idx 处 `{` 的配对 `}` 字符下标（未闭合返回 None）。"""
    d, j, n = 0, open_idx, len(masked)
    while j < n:
        if masked[j] == "{":
            d += 1
        elif masked[j] == "}":
            d -= 1
            if d == 0:
                return j
        j += 1
    return None


def _kt_body_end(masked, pos, starts):
    """从 `fun` 关键字起找函数体范围，返回 (起始行, 结束行, 是否花括号体)。

    无体声明（抽象/接口方法）返回 None。
    """
    n = len(masked)
    depth, i = 0, pos
    while i < n:
        c = masked[i]
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == "{" and depth == 0:               # 参数表之后第一个 { = 函数体
            close = _kt_brace_end(masked, i)
            if close is None:
                return None
            return _line_of(starts, pos), _line_of(starts, close), True
        elif c == "=" and depth == 0:               # 表达式体（默认参数值在括号内，depth>0）
            return _line_of(starts, pos), _kt_expr_end(masked, i, starts), False
        elif c == ";" and depth == 0:               # Kotlin 1.x 旧式声明分隔
            return None
        elif c == "\n" and depth == 0 and i > pos and _starts_new_decl(masked, i, n):
            return None                             # 无体声明（接口方法/abstract fun）
        i += 1
    return None


def _starts_new_decl(masked, nl_idx, n):
    """换行后的下一个非空行是否以声明起点/右括号开头。"""
    k = nl_idx + 1
    while k < n and masked[k] in " \t\r":
        k += 1
    if k >= n or masked[k] == "\n":
        return False
    eol = _line_end(masked, k, n)
    head = masked[k:eol].strip()
    return head.startswith(("}", ")")) or bool(_KT_DECL_START.match(head))


def _kt_expr_end(masked, eq_idx, starts):
    """表达式体（`= expr`）的结束行（1-based）。

    括号深度归零后，若下一非空行以声明起点/`}` 开头，则表达式在上一代码行结束。
    """
    n = len(masked)
    d, j, end = 0, eq_idx, _line_of(starts, eq_idx)
    while j < n:
        c = masked[j]
        if c in "([{":
            d += 1
        elif c in ")]}":
            if d == 0:
                break                               # 撞到外层块的 } —— 表达式体结束
            d -= 1
        elif c == "\n" and d <= 0 and _starts_new_decl(masked, j, n):
            break
        if not c.isspace():
            end = _line_of(starts, j)
        j += 1
    return end


# --------------------------------------------------------------------------
# 圈复杂度（近似）
# --------------------------------------------------------------------------

def _kt_cc(masked, start_line, end_line, spans):
    """近似圈复杂度：1 + if/while/for/catch/&&/||/?: 各 1 + when 每个分支 1。

    `spans` 为全部 fun 的 (名, 起, 止)；嵌在本函数内的 fun 不计入（独立单元）。
    """
    lines = masked.split("\n")
    nested = [(s, e) for _n, s, e in spans if start_line < s and e <= end_line]
    keep = [ln for idx, ln in enumerate(lines[start_line - 1:end_line], start_line)
            if not any(s <= idx < e for s, e in nested)]
    body = "\n".join(keep)
    n = 1
    n += len(re.findall(r"(?<![\w.])if(?![\w])", body))
    n += len(re.findall(r"(?<![\w.])while(?![\w])", body))
    n += len(re.findall(r"(?<![\w.])for(?![\w])", body))
    n += len(re.findall(r"(?<![\w.])catch(?![\w])", body))
    n += body.count("&&") + body.count("||") + body.count("?:")
    return n + _kt_when_branches(body)


def _kt_when_branches(body):
    """when 分支数：每个 `->` 1 分；嵌套 when 的箭头递归扣除（避免重复计数）。"""
    total = 0
    for m in re.finditer(r"(?<![\w.])when(?![\w])", body):
        blk = _brace_block(body, m.end())
        if blk is None:
            continue
        inner = body[blk[0]:blk[1]]
        total += inner.count("->") - _kt_when_branches(inner)
    return total


def _brace_block(text, pos):
    """从 pos 起找第一个花括号块的 (内容起, 内容止)（半开区间，按字符下标）。"""
    i = text.find("{", pos)
    if i < 0:
        return None
    d, j = 0, i
    while j < len(text):
        if text[j] == "{":
            d += 1
        elif text[j] == "}":
            d -= 1
            if d == 0:
                return i + 1, j
        j += 1
    return None
