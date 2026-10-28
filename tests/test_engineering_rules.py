# -*- coding: utf-8 -*-
"""工程纪律闸门（3.6.47）。

把 `scripts/quality_gate.py` 接进全量测试：**测试红 = 不合格**。
规则与豁免流程见 `docs/engineering-discipline.md`；预算表在 `docs/quality-budget.json`。

为什么用测试而不是 CI：本项目无远端 CI，纪律的执行点一直是"测试通过才提交"，
把闸门挂进 pytest 就不需要任何人记得多跑一条命令。
"""
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.path.join(ROOT, "scripts", "quality_gate.py")


def _load_gate():
    spec = importlib.util.spec_from_file_location("_quality_gate_under_test", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_quality_gate_passes(capsys):
    """文件/函数行数与圈复杂度、静默异常、结构性规则全部在预算内。"""
    gate = _load_gate()
    rc = gate.main([])
    out = capsys.readouterr().out
    assert rc == 0, "工程纪律检查未通过：\n" + out


def test_every_budget_debt_has_a_target():
    """存量债务必须写拆分目标（docs/engineering-discipline.md §3.2）。

    没有目标值的债务 = 永久豁免；这条测试防止"登记完就当没事了"。
    """
    gate = _load_gate()
    budget = gate.load_budget()
    assert budget, "缺少 docs/quality-budget.json（跑 scripts/quality_gate.py --init）"
    missing = [p for p, e in budget["files"].items() if not e.get("target")]
    assert not missing, "这些文件登记了行数债务但没有拆分目标 target：%s" % missing


def test_blank_run_check_ignores_multiline_strings():
    """F104 只拦"排版空行"，不拦跨行字符串里的空行（那是内容）。

    误报会让规则被当成噪音：模板、期望输出里本来就有连续空行。
    """
    gate = _load_gate()
    src = 'x = """a\n\n\n\nb"""\n\n\n\ny = 1\n'
    # 字符串内 3 行空（第 2~4 行）不算；字符串之后第 6~8 行 3 行空要算
    assert gate.long_blank_runs(src) == [(6, 3)]


def test_crawler_scripts_are_import_safe():
    """爬虫脚本必须能安全 import（有 main 守卫），否则 `--help` 会被无视而直接开爬。

    事故：2026-10-18 冒烟 `python crawlers/retry_all_failed.py --help`，
    该脚本当时没有 main()，--help 被忽略、直接开始真实爬取。
    """
    import ast

    bad = []
    cdir = os.path.join(ROOT, "crawlers")
    for name in sorted(os.listdir(cdir)):
        if not name.endswith(".py") or name == "__init__.py":
            continue
        path = os.path.join(cdir, name)
        tree = ast.parse(open(path, encoding="utf-8").read())
        has_main = any(isinstance(n, ast.FunctionDef) and n.name == "main" for n in tree.body)
        if not has_main:
            continue            # 纯库模块（如 ids_common）没有入口，import 无副作用
        guarded = any(
            isinstance(n, ast.If)
            and "__main__" in ast.unparse(n.test)
            for n in tree.body)
        if not (has_main and guarded):
            bad.append(name)
    assert not bad, "这些爬虫脚本缺少 main() 或 __main__ 守卫：%s" % bad
