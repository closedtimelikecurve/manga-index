# -*- coding: utf-8 -*-
"""panel/safecover.py —— 内测模式的封面替换（3.6.161）。

为什么单独成层：网页端与 APP 都从 `/api/cover`、`/api/crawl/probe/cover` 取封面字节，
替换必须在这两个出口统一做。前端各自替换一定会漏——网页走 `<img src>`、APP 走
Coil/自绘图片加载器，任何一边漏掉都等于没盖住。

与 `--safe-images`（3.6.118）的分工：

| | `SAFE_IMAGES` | `safe_covers`（本模块） |
|---|---|---|
| 入口 | 启动参数，进程内内存标志 | 双端抽屉开关，写 `config.json`，重启保留 |
| 覆盖范围 | 封面 + 内页 + 探针封面，全盖成灰度图 | 只盖封面（内页仍需真实内容才能验证阅读器） |
| 用途 | 自动化截图（连内页都不能出） | 手动截图 / 录屏时遮挡文库内容 |

发行版**不随附**那张占位角色图（来源不明的素材不该进公开仓库），图缺失时退回
`placeholder.png`：开关照常可用，只是画面变成灰度占位。
"""
import os

from flask import send_file

import common
from panel.host import h

_IMG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "static", "img")
SAFE_COVER_IMG = os.path.join(_IMG_DIR, "safe_cover.jpg")
PLACEHOLDER_IMG = os.path.join(_IMG_DIR, "placeholder.png")


def enabled(scope="web"):
    """某个端的内测模式是否打开（3.6.162 起各端独占）。

    CFG 里可能是旧格式的单个布尔，也可能是新格式的分端字典——统一交给
    `common.safe_covers_on` 归一，调用方不必关心。
    """
    return common.safe_covers_on(h().CFG, scope)


def response(scope="web"):
    """开 → 回占位封面；关 → None，调用方继续走真实封面。

    `Cache-Control: no-cache` 是刻意的：开关一关就得立刻看到真封面。
    配合固定 ETag，切回同一状态时仍是 304，不会反复重传。
    """
    if not enabled(scope):
        return None
    path = SAFE_COVER_IMG if os.path.exists(SAFE_COVER_IMG) else PLACEHOLDER_IMG
    mime = "image/jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "image/png"
    resp = send_file(path, mimetype=mime, etag="safe-covers-%s" % scope, conditional=True)
    resp.headers["Cache-Control"] = "no-cache"
    # 端写进响应头：出问题时一眼能看出"这张占位图是给哪一端切的"
    resp.headers["X-Img-Mode"] = "safe:%s" % scope
    return resp


__all__ = ["SAFE_COVER_IMG", "PLACEHOLDER_IMG", "enabled", "response"]
