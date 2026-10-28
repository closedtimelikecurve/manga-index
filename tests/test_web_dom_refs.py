# -*- coding: utf-8 -*-
"""网页端 DOM 引用守卫（3.6.125）。

事故：3.7.78 删掉设置弹窗 `#modal`（里面含 `#btnPair`）后，`panel.js` 仍有一行
`$('#btnPair').addEventListener(...)`。`$()` = `document.querySelector`，元素不存在时返回
`null` → 取属性抛 `TypeError` → **同文件后面所有绑定整段不执行**：
顶栏二维码 `#btnPairTop`、别名登记 `#btnSettings` 两个入口一起变哑，用户看到的就是
"图标和二维码重合、两个功能都打不开"。

本守卫只看**未判空的直接属性访问**（`$('#x').xxx`）：
* 这种写法一旦元素不存在就是脚本崩，属于必拦；
* `const el = $('#x'); if (el) …` 是安全的，不在口径内（否则大量动态创建元素的合法写法误报）。

纯文本断言，不需要浏览器。
"""
import glob
import os
import re

PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(PROG_DIR, "static", "js")
HTML = os.path.join(PROG_DIR, "static", "index.html")

ID_ATTR = r'id="([A-Za-z0-9_-]+)"'
ID_ATTR_SQ = r"id='([A-Za-z0-9_-]+)'"
ID_OBJ = r"id:\s*'([A-Za-z0-9_-]+)'"
ID_SET = r"\.id\s*=\s*'([A-Za-z0-9_-]+)'"
REF = r"\$\('#([A-Za-z0-9_-]+)'\)\s*\.|\$\(\"#([A-Za-z0-9_-]+)\"\)\s*\."


def _strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)//[^\n]*$", "", src)


def _js_files():
    return sorted(glob.glob(os.path.join(JS_DIR, "*.js")))


def _known_ids():
    """DOM 里可能出现的 id：静态 HTML + 各分片动态注入（含 id: 'x' 的数据表）。"""
    ids = set(re.findall(ID_ATTR, open(HTML, encoding="utf-8").read()))
    for path in _js_files():
        src = _strip_comments(open(path, encoding="utf-8").read())
        for pat in (ID_ATTR, ID_ATTR_SQ, ID_OBJ, ID_SET):
            ids |= set(re.findall(pat, src))
    return ids


def _unguarded_refs():
    """`$('#x').属性` 形态（未判空）→ {id: [文件名]}。"""
    refs = {}
    for path in _js_files():
        src = _strip_comments(open(path, encoding="utf-8").read())
        for m in re.finditer(REF, src):
            ref = m.group(1) or m.group(2)
            refs.setdefault(ref, set()).add(os.path.basename(path))
    return refs


def test_no_unguarded_access_to_missing_id():
    known = _known_ids()
    bad = {k: sorted(v) for k, v in _unguarded_refs().items() if k not in known}
    assert not bad, (
        "这些 id 在 DOM 里不存在，却被直接取属性（元素一缺就抛 TypeError，"
        "同文件后续绑定全部失效）：\n%s" % "\n".join("  %s ← %s" % (k, v) for k, v in bad.items()))


def test_removed_nodes_are_not_referenced():
    """3.7.78 删掉的节点别再回来（它们只会以"不存在的 id"形态出现）。"""
    known = _known_ids()
    for gone in ("btnPair", "modal", "settingsRoot"):
        assert gone not in known, "%s 已随设置弹窗删除，不该再被创建" % gone


def test_dangerous_bindings_use_null_safe_helper():
    """四个曾被打断的绑定必须走空安全 `on()`；裸 `$().addEventListener` 不许再出现。"""
    core = _strip_comments(open(os.path.join(JS_DIR, "core.js"), encoding="utf-8").read())
    assert "function on(sel, ev, fn)" in core, "缺少空安全绑定工具 on()"
    panel = _strip_comments(open(os.path.join(JS_DIR, "panel.js"), encoding="utf-8").read())
    for sel in ("#btnPairTop", "#pairClose", "#pairModal", "#btnSettings"):
        assert "on('%s', 'click'" % sel in panel, "%s 没有改用空安全绑定" % sel
    assert "$('#btnPair')" not in panel, "又绑了已删除的 #btnPair"


def test_topbar_and_drawer_icons_differ():
    """用户报「别名登记图标与二维码重合」：两处都用 🔗，同屏出现两次。
    现在顶栏扫码 = 📱、抽屉别名 = 🏷，必须不同。"""
    html = open(HTML, encoding="utf-8").read()
    pair = re.search(r'id="btnPairTop"[^>]*>([^<]+)', html)
    alias = re.search(r'id="btnSettings"[^>]*>([^<]+)', html)
    assert pair and alias, "顶栏扫码 / 抽屉别名入口不见了"
    assert pair.group(1).strip() != alias.group(1).strip(), \
        "两个入口又用了同一个图标（%s）" % pair.group(1).strip()
