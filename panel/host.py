# -*- coding: utf-8 -*-
"""panel/host.py —— 取"当前真正在跑的应用模块"（3.6.55 从 routes/host.py 下沉）。

`services/*` 与 `routes/*` 都不能在模块级 `import app`：
`python app.py` 时本模块是 `__main__`，再 import 会二次执行 app.py（双 Flask 实例 / 两份状态）。

但也**不能**在启动时按值捕获 app 里的函数：测试大量 `monkeypatch.setattr(app, "find_work", ...)`，
按值捕获会让打桩静默失效（`test_crawl_parallel` 打的是 `app.subprocess.Popen`，
失效会让测试真的拉起爬虫）。因此统一 `h().xxx` —— 每次调用按名重新解析。
"""
import sys


def h():
    """返回当前进程里真正在跑的应用模块（pytest → `app`；`python app.py` → `__main__`）。"""
    mod = sys.modules.get("app")
    return mod if mod is not None else sys.modules["__main__"]


__all__ = ["h"]
