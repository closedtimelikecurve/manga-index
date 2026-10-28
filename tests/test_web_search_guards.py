# -*- coding: utf-8 -*-
"""网页端搜索的三条回归守卫（3.6.107）。

用户报障：「即便库里有对应作品，输入到一定字符数之后搜索就失效」。查下来不是限流、
也不是慢，是**前端把输入框里的字吃掉了**：

1. `panel.js` 每敲一次就（防抖 200ms）把 hash 改成 `q=<trim 过的值>`，紧接着
   `router.js` 的 search 分支把输入框 value 重写成同一个 trim 值 —— 刚敲的空格当场消失，
   多点之间的词被粘成一串（「ちんぽ 精灵女王」→「ちんぽ精灵女王」）。后端多词是 AND，
   粘出来的串在库里根本不存在，于是 0 条：越往后输入越对不上，正是"输入一定字符后失效"。
2. 同理，重写 value 会**打断输入法合成**、把光标扔到末尾。
3. 0 条时整块 `hidden`，没有任何提示，用户分不清"没匹配 / 搜索坏了 / 还在转"。
4. 另外 hash 里的 q 做了**双重解码**（URLSearchParams 已经解过一次），查询里只要有字面
   `%`（如「快感100%」）就抛 URIError，route() 整个中断 —— 页面既不渲染也不报错。

这些都在 classic script 里，Python 侧没有运行环境，用源码文本做最小断言。
"""
import os

PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(PROG_DIR, "static", "js")


def _js(name):
    with open(os.path.join(JS_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


def test_search_hash_is_not_double_decoded():
    """URLSearchParams 已解码，不能再套 decodeURIComponent（字面 % 会炸 route）。"""
    src = _js("router.js")
    assert "decodeURIComponent(new URLSearchParams" not in src, \
        "router.js 又对 q 做了双重解码：查询含 `%` 时会抛 URIError，整页不渲染"
    assert "new URLSearchParams(h.slice(_si + 1)).get('q')" in src


def test_typing_does_not_rewrite_search_box():
    """输入框正在编辑时不许回写 value —— 否则空格被吞、输入法被打断。"""
    src = _js("router.js")
    assert "document.activeElement !== $('#search')" in src, \
        "router.js 的 search 分支又无条件 `$('#search').value = _sq`：吃空格 + 断输入法"


def test_empty_result_is_explained():
    """0 条必须给提示（多关键词是 AND），不能静默 hidden。"""
    src = _js("search.js")
    assert "没有匹配的作品" in src, "search.js 空结果时又直接隐藏了，用户看不出是没匹配还是坏了"
    assert "同时包含" in src, "提示里要说明多关键词是 AND 关系"
