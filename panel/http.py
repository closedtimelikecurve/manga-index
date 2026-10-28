# -*- coding: utf-8 -*-
"""panel/http.py —— HTTP 门禁的共享登记表（3.6.53 路由拆分前抽出）。

为什么单独成模块：`@mutating` 装饰器现在要同时被 `app.py` 与 `routes/*.py` 使用。
若留在 app.py，routes 只能 `h().mutating` 或 `from app import mutating`（后者是
`__main__` 陷阱的入口），所以把"登记表 + 装饰器"抽到这个零依赖模块，两边 import 同一对象。

**登记表只在原对象上 add，绝不允许整体重新赋值**（`app._MUTATING_ENDPOINTS` 是
同一对象的别名，重新赋值会让门禁读不到新登记项）。
"""
# 变更型端点：整个请求期持有 SCAN_LOCK（见 app._mutate_gate_begin）
MUTATING_ENDPOINTS = set()


def mutating(fn):
    """标记「变更型端点」：整个请求期持有 SCAN_LOCK。

    只对**会搬/改/删文件**的端点使用（调用链上有 `_lib_touch` 的端点）。
    纯 DB 写端点不要加：它们不碰文件，加了反而与内部 `get_library(force=True)` 的加锁自锁
    （普通 Lock 不可重入，3.6.36 #33 踩过）。
    """
    MUTATING_ENDPOINTS.add(fn.__name__)
    return fn


__all__ = ["MUTATING_ENDPOINTS", "mutating"]
