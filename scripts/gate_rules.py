# -*- coding: utf-8 -*-
"""scripts/gate_rules.py —— 闸门的源码级规则（3.6.82 新增 F006）。

F006：**把某个名字当模块用（`X.attr`），但整份文件都没定义/导入过 X**。
针对的是一类"搬家才出现、导入期毫无征兆"的 bug：把函数搬到新模块时漏掉某条 import
（本轮真实发生两次：`djc_parse as _dp`、`json`），只有调用那个端点时才 500。

**为什么只查属性访问的基名**：完整的作用域分析要处理闭包捕获、推导式变量、match 模式绑定，
误报会很多（首版在 29/115 个文件上误报）。"`X.attr` 里的 X 在整份文件里查无此人"
既覆盖了漏 import 这一类，又几乎不误报。
"""
import ast
import builtins


def _def_names(n):
    """定义/导入/形参类绑定。"""
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [n.name]
    if isinstance(n, (ast.Import, ast.ImportFrom)):
        return [a.asname or a.name.split(".")[0] for a in n.names]
    if isinstance(n, ast.arg):
        return [n.arg]
    if isinstance(n, ast.ExceptHandler):
        return [n.name] if n.name else []
    if isinstance(n, ast.Global):
        return list(n.names)
    return []


def _bind_names(n):
    """赋值/解构/match 模式类绑定。"""
    if isinstance(n, ast.Name):
        return [n.id] if isinstance(n.ctx, (ast.Store, ast.Del)) else []
    if isinstance(n, ast.MatchAs):
        return [n.name] if n.name else []
    if isinstance(n, ast.MatchStar):
        return [n.name] if n.name else []
    if isinstance(n, ast.MatchMapping):
        return [n.rest] if n.rest else []
    return []


def _defined_names(tree):
    """整份文件里出现过的绑定名（模块级 + 所有函数内，含 Try 里的导入）。"""
    names = set(dir(builtins))
    for n in ast.walk(tree):
        names.update(_def_names(n))
        names.update(_bind_names(n))
    return names


def undefined_names(src):
    """返回 [(函数名, 基名)] —— 被当模块用却全文件未定义的名字。"""
    if "import *" in src:
        return []
    tree = ast.parse(src)
    defined = _defined_names(tree)
    out = set()
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for x in ast.walk(n):
            base = x.value if isinstance(x, ast.Attribute) else None
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name) and base.id not in defined:
                out.add((n.name, base.id))
    return sorted(out)
