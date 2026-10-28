#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/quality_gate.py —— 工程纪律的机器兜底（见 docs/engineering-discipline.md）。

零依赖（只用标准库）：不联网、不装包，符合本项目"断网可用、纯本地"的取向。
权威关卡是 tests/test_engineering_rules.py（跑全量测试即执行）；本脚本也可单独跑：

    python scripts/quality_gate.py                 # 检查，违规退出码 1
    python scripts/quality_gate.py --report        # 只报告，不判定
    python scripts/quality_gate.py --init          # 首次生成预算表（禁止抬高既有上限）
    python scripts/quality_gate.py --update        # 把"已降低"的值写回预算表
    python scripts/quality_gate.py --raise app.py 6200 --why "..."   # 显式提额（需写理由）
    python scripts/quality_gate.py --stats         # 看各文件"总行 vs 代码行"（空行会把行数撑虚）

预算表：docs/quality-budget.json
  文件上限     **物理行 800 / 有效代码行 400**；`.kt` 另有口径 **700 / 500**
               （Compose 的 `@Composable` 参数与链式修饰符天然占行，见纪律 §3.1）。
               有效代码 = 非空、非 `#` 注释、非 docstring；已超限的"存量文件"进 files 表，
               cap/cap_code = 当前值（棘轮：只降不升）
  函数上限     50 行 / 圈复杂度 15；存量超标函数进 func_debt 表，同样只降不升
  静默异常     except Exception: pass 每个文件计数，只降不升
"""
import argparse
import ast
import io, json, os, sys  # noqa: E401 —— 闸门自身卡 400 行有效代码，import 合行让位给 sys.path 自足修复
import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUDGET = os.path.join(ROOT, "docs", "quality-budget.json")

# 2026-10-27：gate 子模块与自身同目录，直接跑脚本时 Python 会把 scripts/ 放上 sys.path，
# 但被 tests/test_engineering_rules.py 以 importlib 加载时不会——全量套件里一直靠
# test_gate_comments.py 模块级 sys.path.insert 的收集顺序副作用兜着，单跑该测试文件
# 就 ModuleNotFoundError。闸门自己认自己的兄弟模块，不依赖别人的加载方式。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gate_comments


def _kt_functions(src):
    """.kt 函数两维测量，委托给 scripts/gate_kt.py（Kotlin 无 ast，靠括号平衡扫描）。

    延迟导入：gate_kt 是可选模块，缺了不应让整个闸门起不来（只退化成"不量函数"）。"""
    try:
        import gate_kt
    except ImportError:
        return []
    return gate_kt.kt_functions(src)

# 3.7.42：Android 源码（.kt）纳入闸门；3.7.50 起用 Kotlin 专用口径 700/500（见 KT_LIMITS）。
# 此前整个 android/ 被跳过——等于 Kotlin 代码不受任何文件行纪律约束（MainActivity 2739 行也没人管）。
# 只跳过构建产物与工具链，源码在 android/app/src 下照常扫描。
SKIP_DIRS = {"build", "toolchain", ".gradle", ".idea", "build-tools", "dist",
             "__pycache__", ".git", "backups", "app_releases", "node_modules",
             ".pytest_cache"}
SKIP_PREFIX = ("_", ".")          # _cache / _logs / _state / _inbox 等运行时目录

# 3.6.79 新标准：物理行 800 / 有效代码行 400。
# 为什么是两维：`app.py` 曾有 1008 物理行、其中 483 空行 + 211 注释，实际代码只有 314 行——
# 只判物理行会把"排版糟糕"误判成"结构糟糕"，只判代码行又放过了真正臃肿的文件。
LIMITS = {"file_lines": 800, "code_lines": 400, "func_lines": 50, "func_cc": 15}
KT_LIMITS = (700, 500)     # Kotlin 口径（物理行 / 有效代码行）：Compose 声明天然啰嗦，见纪律 §3.2


def _cc(node):
    """圈复杂度，与 **radon 6.0.1 的 mccabe 实现对齐**（交叉核对见 docs/engineering-discipline.md §3.1）：
      * +1：`if` / `elif` / `for` / `while` / `except` / `assert` / 三元 / `match case`
      * +1：布尔链里**每个多余的 and/or**（`a or b or c` 记 +2）
      * +1：每个推导式，另 +1/每个 `if` 子句
      * **不计** `with`（radon 不计）；函数入口基线为 1
      * **不递归进嵌套函数/类**：嵌套函数是独立单元，否则会重复计数
        （曾因此把 `index_launcher.main` 的 cc 从 10 虚报成 68）
    """
    n = 1
    nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)

    def walk(nd):
        nonlocal n
        for c in ast.iter_child_nodes(nd):
            if isinstance(c, nested):
                continue                      # 独立单元，另算
            if isinstance(c, (ast.If, ast.For, ast.While, ast.AsyncFor, ast.IfExp,
                              ast.ExceptHandler, ast.Assert)):
                n += 1
                # for/while 的 else 子句也是一条独立分支（radon 同样计入）
                if isinstance(c, (ast.For, ast.While, ast.AsyncFor)) and c.orelse:
                    n += 1
            elif isinstance(c, ast.BoolOp):
                n += len(c.values) - 1
            elif isinstance(c, ast.comprehension):
                n += 1 + len(c.ifs)
            elif isinstance(c, ast.Match):
                n += len(c.cases)
            walk(c)

    walk(node)
    return n


def scan_files():
    out = []
    for root, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(SKIP_PREFIX)]
        for n in names:
            if not n.endswith((".py", ".js", ".kt")):
                continue
            p = os.path.relpath(os.path.join(root, n), ROOT).replace("\\", "/")
            # .kt 只认 Android 源码树（构建脚本 build.gradle.kts 不属业务代码）
            if n.endswith(".kt") and not p.startswith("android/app/src/"):
                continue
            out.append(p)
    return sorted(out)


def _doc_rows(tree):
    """模块/函数/类的 docstring 所占行号（1-based）。

    "有效代码行"要排除它们：docstring 是文档，不是逻辑；否则靠堆注释"达标"或
    靠拆注释"减重"都会污染判断（`app.py` 1008 行里 483 行空行 + 211 行注释就是这么来的）。
    """
    rows = set()
    for n in ast.walk(tree):
        if not isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(n, "body", None) or []
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            rows.update(range(body[0].lineno, body[0].end_lineno + 1))
    return rows


def code_lines(src, tree=None):
    """有效代码行：排除空行、`#` 注释行、docstring。"""
    tree = tree if tree is not None else ast.parse(src)
    doc = _doc_rows(tree)
    n = 0
    for i, ln in enumerate(src.split("\n"), 1):
        s = ln.strip()
        if not s or s.startswith("#") or i in doc:
            continue
        n += 1
    return n


def _approx_code_lines(src):
    """近似有效代码行（.js / .kt 无 AST 时用）：排除空行、行注释与块注释。"""
    n = 0
    in_block = False
    for ln in src.splitlines():
        t = ln.strip()
        if in_block:
            if "*/" in t:
                in_block = False
            continue
        if not t or t.startswith(("//", "#", "<!--")):
            continue
        if t.startswith("/*"):
            if "*/" not in t:
                in_block = True
            continue
        n += 1
    return n


def measure(path):
    """返回 (物理行, 有效代码行, [(函数名, 行数, cc)], 静默异常数)。

    3.7.46 起 .kt 也量函数两维（行数 / 近似 cc），走与 Python 相同的 F002/F003 判定。
    此前 .kt 只量文件行——等于 Kotlin 侧"函数多长、多复杂"完全不受纪律约束
    （Step5 三次重构都是靠人肉看行数，闸门一声不吭）。
    """
    full = os.path.join(ROOT, path)
    src = open(full, encoding="utf-8", errors="replace").read()
    lines = len(src.splitlines())
    if path.endswith(".kt"):
        # Kotlin 无 ast：行数与 cc 由 gate_kt 的括号平衡扫描器近似（口径见该模块文档）
        funcs = _kt_functions(src)
        return lines, _approx_code_lines(src), funcs, 0
    if path.endswith(".js"):
        # 无 AST 可解析：按"非空 + 非注释行"近似有效代码行（与 Python 的 code_lines 同口径）
        return lines, _approx_code_lines(src), [], 0
    tree = ast.parse(src)
    funcs = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append((n.name, n.end_lineno - n.lineno + 1, _cc(n)))
    silent = 0
    for n in ast.walk(tree):
        if isinstance(n, ast.ExceptHandler) and len(n.body) == 1 and isinstance(n.body[0], ast.Pass):
            if n.type is None or ast.unparse(n.type) == "Exception":
                silent += 1
    return lines, code_lines(src, tree), funcs, silent


def long_blank_runs(src, min_run=3):
    """连续空行 >= min_run 的位置，返回 [(起始行, 行数)]。

    **跨行字符串里的空行不算**：那是内容（模板/期望输出），不是排版。
    空行不占逻辑，但会把文件行数撑虚，让"这文件多大"判断失真——
    搬迁时按行切片删函数，两侧的分隔空行叠起来，就是大片空白洞。
    """
    protected = set()
    try:
        for tk in tokenize.generate_tokens(io.StringIO(src).readline):
            if tk.type == tokenize.STRING and tk.start[0] != tk.end[0]:
                protected.update(range(tk.start[0], tk.end[0] + 1))
    except (tokenize.TokenError, IndentationError):
        protected = set()       # 非 Python（.js）或语法残缺：按纯文本判，不做保护
    runs, start, n = [], 0, 0
    for i, ln in enumerate(src.split("\n"), 1):
        if ln.strip() or i in protected:
            if n >= min_run:
                runs.append((start, n))
            n = 0
            continue
        if n == 0:
            start = i
        n += 1
    if n >= min_run:
        runs.append((start, n))
    return runs


def whitespace_stats(path):
    """(总行, 空行, 注释行, 有效代码行, 最长空段) —— 与判定口径一致。"""
    src = open(os.path.join(ROOT, path), encoding="utf-8", errors="replace").read()
    lines = src.splitlines()
    blank = sum(1 for ln in lines if not ln.strip())
    comment = sum(1 for ln in lines if ln.strip().startswith("#"))
    worst = max((n for _s, n in long_blank_runs(src, min_run=1)), default=0)
    if path.endswith(".py"):
        try:
            code = code_lines(src)          # 排除 docstring，与服务端判定同一口径
        except SyntaxError:
            code = len(lines) - blank - comment
    else:
        code = len(lines) - blank - comment
    return len(lines), blank, comment, code, worst


def _stats():
    """--stats：按总行数列出前 20 个文件的构成（判断"行数"是否可信）。"""
    rows = [whitespace_stats(p) + (p,) for p in scan_files()]
    print(f"{'文件':<40}{'物理行':>7}{'空行':>6}{'空行%':>6}{'代码行':>7}{'最长空段':>8}")
    print("-" * 76)
    for total, blank, _c, code, worst, p in sorted(rows, reverse=True)[:20]:
        print(f"{p:<40}{total:>7}{blank:>6}{blank * 100 // max(total, 1):>5}%{code:>7}{worst:>8}")
    return 0


def collect():
    data = {"files": {}, "func_debt": {}, "silent_except": {}}
    for p in scan_files():
        lines, code, funcs, silent = measure(p)
        data["files"][p] = {"lines": lines, "code": code}
        for name, ln, cc in funcs:
            if ln > 50 or cc > 15:
                # 同名函数（重载/嵌套）取最大值，避免键冲突后棘轮失效
                key = f"{p}::{name}"
                old = data["func_debt"].get(key)
                data["func_debt"][key] = {"lines": max(ln, old["lines"] if old else 0),
                                          "cc": max(cc, old["cc"] if old else 0)}
        if silent:
            data["silent_except"][p] = silent
    return data


def load_budget():
    if not os.path.exists(BUDGET):
        return None
    with open(BUDGET, encoding="utf-8") as f:
        return json.load(f)


def save_budget(b):
    os.makedirs(os.path.dirname(BUDGET), exist_ok=True)
    with open(BUDGET, "w", encoding="utf-8", newline="\n") as f:
        json.dump(b, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")


def build_baseline(current, old=None):
    """生成/更新预算表：cap 取 max(当前, 旧 cap)——旧 cap 更低时保留旧值（棘轮）。

    3.6.72 结构：文件/函数/静默异常三块各自成函数（cc 17→3）。
    """
    limits = dict(LIMITS)
    old = old or {}
    return {"_doc": "工程纪律量化预算（只降不升）。规则见 docs/engineering-discipline.md §3",
            "generated": current.get("generated", ""), "limits": limits,
            "files": _baseline_files(current["files"], old.get("files", {}), limits),
            "func_debt": _baseline_funcs(current["func_debt"], old.get("func_debt", {})),
            "silent_except": _baseline_silent(current["silent_except"],
                                             old.get("silent_except", {}))}


def _baseline_files(cur_files, old_files, limits):
    """文件额度：两个维度都要登记（物理行 cap / 有效代码行 cap_code），各自取 max(当前, 旧值)。"""
    files = {}
    for p, m in cur_files.items():
        prev = old_files.get(p)
        l1, l2 = KT_LIMITS if p.endswith(".kt") else (limits["file_lines"], limits["code_lines"])
        over = m["lines"] > l1 or m["code"] > l2
        if not over and prev is None:
            continue
        entry = {"cap": m["lines"] if prev is None else max(m["lines"], prev.get("cap", 0)),
                 "cap_code": m["code"] if prev is None else max(m["code"], prev.get("cap_code", 0))}
        for k in ("target", "why"):
            if prev and prev.get(k):
                entry[k] = prev[k]
        files[p] = entry
    return files


def _baseline_funcs(cur_debt, old_debt):
    """函数债务：lines/cc 各自只降不升。"""
    debt = {}
    for key, v in cur_debt.items():
        prev = old_debt.get(key)
        debt[key] = {"lines": max(v["lines"], prev["lines"]) if prev else v["lines"],
                     "cc": max(v["cc"], prev["cc"]) if prev else v["cc"]}
    return debt


def _baseline_silent(cur_silent, old_silent):
    """静默异常计数：只降不升。"""
    return {p: max(n, old_silent.get(p, 0)) for p, n in cur_silent.items()}


def _file_violations(p, m, entry, lim):
    """单个文件的两条维度判定：物理行（F001）/ 有效代码行（F005）。

    两个维度分开判：一个文件可能"物理 800 以内但全是代码"，也可能"物理超了但大半是空行+注释"
    （`app.py` 就曾是 1008 物理 / 314 代码）。只判一个数会得出相反结论。
    """
    out = []
    d1, d2 = KT_LIMITS if p.endswith(".kt") else (lim["file_lines"], lim["code_lines"])
    cap = entry.get("cap", d1) if entry else d1
    cap_code = entry.get("cap_code", d2) if entry else d2
    if m["lines"] > cap:
        hint = "超上限 %d 行（cap=%d）" % (m["lines"] - cap, cap)
        if not entry:
            hint += "；新文件请拆分，或把债务登记进 docs/quality-budget.json"
        elif entry.get("target"):
            hint += "；拆分目标 %s 行" % entry["target"]
        out.append(("F001 物理行过长", f"{p} {m['lines']} 行 · {hint}"))
    if m["code"] > cap_code:
        hint = "有效代码 %d 行 · 超上限 %d（cap_code=%d）" % (
            m["code"], m["code"] - cap_code, cap_code)
        if not entry:
            hint += "；按职责拆模块，或登记债务"
        out.append(("F005 代码行过长", f"{p} · {hint}"))
    return out


def check(budget, current):
    v = []
    lim = budget["limits"]
    for p, m in current["files"].items():
        v.extend(_file_violations(p, m, budget["files"].get(p), lim))
    for key, vals in current["func_debt"].items():
        if key not in budget["func_debt"]:
            v.append(("F002 新增超预算函数",
                      f"{key} · {vals['lines']} 行 / cc {vals['cc']}（上限 {lim['func_lines']} 行 / cc {lim['func_cc']}）"))
            continue
        base = budget["func_debt"][key]
        if vals["lines"] > base["lines"] or vals["cc"] > base["cc"]:
            v.append(("F003 函数预算回升",
                      f"{key} · 现在 {vals['lines']} 行/cc {vals['cc']}，冻结额度 {base['lines']} 行/cc {base['cc']}"))
    for p, n in current["silent_except"].items():
        base = budget["silent_except"].get(p, 0)
        if n > base:
            v.append(("F004 静默吞异常增加",
                      f"{p} · 现在 {n} 处 except: pass（冻结额度 {base}）；业务失败必须 log.exception"))
    v.extend(_rule_checks())
    return v


def _rule_checks():
    """结构性纪律（可在源码层判定的那几条）。逐条拆开，便于单独豁免与定位。"""
    try:
        from scripts.gate_rules import undefined_names
    except ImportError:                       # 直接 `python scripts/quality_gate.py` 运行时
        from gate_rules import undefined_names
    v = []
    for p in scan_files():
        if not p.endswith(".py"):
            continue
        src = open(os.path.join(ROOT, p), encoding="utf-8", errors="replace").read()
        v.extend(_check_entries(p, src, undefined_names))
        v.extend(_check_undefined(p, src, undefined_names))
        v.extend(gate_comments.check(p, src, ROOT, SKIP_DIRS))
        v.extend(_check_blanks(p, src))
    return v


def _check_entries(p, src, _undefined):
    """F101 爬虫脚本必须有 main 守卫；F102 禁止裸导入爬虫模块；F103 路由写法统一。"""
    v = []
    if p.startswith("crawlers/") and not p.endswith("__init__.py"):
        # 只约束"有入口的脚本"：纯库模块（如 ids_common）没有 main()，import 天然无副作用
        if "def main(" in src and 'if __name__ == "__main__":' not in src:
            v.append(("F101 爬虫脚本缺 main 守卫", f"{p} 必须有 if __name__ == \"__main__\": main()"))
    if not p.startswith("crawlers/") and not p.startswith("tests/") and p != "scripts/quality_gate.py":
        for bad in ("import crawl_wnacg", "import crawl_jm_ids", "import crawl_nh_ids",
                    "import crawl_jm_direct", "import crawl_nh_direct"):
            if bad in src:
                v.append(("F102 裸导入爬虫模块", f"{p} 出现 `{bad}`，请改 `from crawlers import ...`"))
    if p == "app.py" and "@app.route(" in src:
        v.append(("F103 路由写法混用", "app.py 新增了 @app.route(...)，请用 @app.get/@app.post"))
    return v


def _check_undefined(p, src, undefined_names):
    """F006：把某名字当模块用（X.attr），但整份文件没 import/定义过 X。"""
    if p == "scripts/gate_rules.py":
        return []                       # 规则表自身含有反例字符串
    return [("F006 未导入的模块名",
             f"{p}::{fn} 用了 `{name}.`，但文件里没有 import/定义；搬模块时最容易漏")
            for fn, name in undefined_names(src)]


def _check_blanks(p, src):
    """F104：连续空行 >2（空行会把文件行数撑虚，干扰"该不该拆"的判断）。"""
    runs = long_blank_runs(src)
    if not runs:
        return []
    start, n = max(runs, key=lambda r: r[1])
    return [("F104 连续空行过多",
             f"{p} 有 {len(runs)} 处 >2 行空白，最长 L{start} 连续 {n} 行；"
             "函数间留 2 行、函数内不留空洞")]


def main(argv=None):
    """闸门入口：调度到 init/update/prune/raise/check 五个动作之一。

    3.6.72 结构：每个动作各自成函数（cc 23→5），本函数只分派。
    """
    args = _gate_parser().parse_args(argv)
    if args.stats:
        return _stats()                 # 只做体检，不需要预算表
    cur = collect()
    budget = load_budget()
    if args.init or args.update:
        return _write_baseline(cur, budget)
    if args.prune:
        return _prune_budget(cur, budget)
    if args.raise_cap or args.raise_code:
        return _raise_cap(args, cur, budget)
    if budget is None:
        print("缺少预算表 docs/quality-budget.json，请先运行 --init")
        return 2
    return _report(cur, budget, args.report)


def _gate_parser():
    ap = argparse.ArgumentParser(description="工程纪律量化闸门（零依赖）")
    ap.add_argument("--report", action="store_true", help="只报告不判定（退出码恒 0）")
    ap.add_argument("--init", action="store_true", help="生成预算表（已存在则合并，禁止抬高上限）")
    ap.add_argument("--update", action="store_true", help="把已降低的值写回预算表")
    ap.add_argument("--raise", nargs=2, dest="raise_cap", metavar=("FILE", "CAP"),
                    help="显式提高某文件物理行上限")
    ap.add_argument("--raise-code", nargs=2, dest="raise_code", metavar=("FILE", "CAP"),
                    help="显式提高某文件有效代码行上限")
    ap.add_argument("--prune", action="store_true",
                    help="重建债务表：删掉已修复/已搬走的条目，按当前值重算（只降不升）")
    ap.add_argument("--stats", action="store_true",
                    help="按总行数列出前 20 个文件的空白构成（判断行数是否可信）")
    ap.add_argument("--why", default="", help="配合 --raise 的理由（会写进预算表）")
    return ap


def _write_baseline(cur, budget):
    """--init / --update：按当前实测生成预算表（旧 cap 更低时保留旧值）。"""
    budget = build_baseline(cur, budget)
    budget["generated"] = __import__("time").strftime("%Y-%m-%d")
    save_budget(budget)
    print("预算表已写入 %s（%d 个文件登记、%d 个函数债务）"
          % (os.path.relpath(BUDGET, ROOT), len(budget["files"]), len(budget["func_debt"])))
    return 0


def _prune_budget(cur, old):
    """--prune：重建债务表。文件降到默认上限以内即**销账**；函数债务以当前实测为准
    （已修好的自动消失、搬家的换到新键、数值只减不增）。"""
    old = old or {}
    lim = dict(LIMITS)                 # 标准升级：一律用当前标准，不沿用旧表里的限额
    files, dropped = _prune_files(old.get("files", {}), cur["files"], lim)
    budget = {
        "_doc": old.get("_doc", "工程纪律量化预算（只降不升）"),
        "generated": __import__("time").strftime("%Y-%m-%d"),
        "limits": lim,
        "files": files,
        "func_debt": cur["func_debt"],
        "silent_except": cur["silent_except"],
    }
    save_budget(budget)
    print("债务表已重建：%d 个文件、%d 个函数债务、%d 处静默异常"
          % (len(files), len(cur["func_debt"]), sum(cur["silent_except"].values())))
    for d in dropped:
        print("  销账（已达标）：" + d)
    return 0


def _prune_files(old_files, cur_files, lim):
    """保留仍超限的文件条目（cap / cap_code 各自只降不升），返回 (条目表, 已销账清单)。"""
    files, dropped = {}, []
    for p, e in old_files.items():
        if p not in cur_files:
            continue                                  # 文件已删除/改名 → 丢条目
        now = cur_files[p]
        entry = dict(e)
        entry["cap"] = min(e.get("cap", now["lines"]), now["lines"])
        entry["cap_code"] = min(e.get("cap_code", now["code"]), now["code"])
        l1, l2 = KT_LIMITS if p.endswith(".kt") else (lim["file_lines"], lim["code_lines"])
        if now["lines"] <= l1 and now["code"] <= l2:
            dropped.append("%s（%d 行 / 代码 %d ≤ %d/%d）" % (p, now["lines"], now["code"], l1, l2))
            continue
        files[p] = entry
    for p, m in cur_files.items():
        if p in files:
            continue
        l1, l2 = KT_LIMITS if p.endswith(".kt") else (lim["file_lines"], lim["code_lines"])
        if m["lines"] > l1 or m["code"] > l2:
            files[p] = {"cap": m["lines"], "cap_code": m["code"]}
    return files, dropped


def _raise_cap(args, cur, budget):
    """--raise / --raise-code：显式提额，**必须**配 --why 留痕。"""
    target, value = (args.raise_code if args.raise_code else args.raise_cap)
    field = "cap_code" if args.raise_code else "cap"
    path, cap = target, int(value)
    if not args.why:
        print("拒绝：--raise 必须配 --why 说明理由（纪律：提额要留痕）")
        return 2
    budget = budget or build_baseline(cur)
    m = cur["files"].get(path) or {"lines": 0, "code": 0}
    entry = budget["files"].setdefault(path, {"cap": m["lines"], "cap_code": m["code"]})
    entry[field] = cap
    entry["why"] = args.why
    save_budget(budget)
    print("已提额 %s %s → %d（理由：%s）"
          % (path, "有效代码行" if field == "cap_code" else "物理行", cap, args.why))
    return 0


def _report(cur, budget, report_only):
    """默认动作：按预算判定，打印违规明细。--report 时退出码恒 0。"""
    violations = check(budget, cur)
    if not violations:
        print("工程纪律检查通过：%d 个文件 / %d 个函数债务在预算内"
              % (len(cur["files"]), len(cur["func_debt"])))
        return 0
    print("工程纪律检查未通过（%d 项）：\n" % len(violations))
    for code, msg in violations:
        print("[%s] %s" % (code, msg))
    print("\n规则与豁免流程见 docs/engineering-discipline.md")
    return 0 if report_only else 1


if __name__ == "__main__":
    sys.exit(main())
