# -*- coding: utf-8 -*-
"""可选依赖探测（Pillow / rarfile）—— 3.7 结构重构：从 app.py 抽出。

app.py 以 `from panel.deps import ...` 再导出，保持 `app.PIL_OK` / `app.RAR_AVAILABLE`
等既有命名面不变（面板状态接口 `/api/config`、启动横幅与测试都读它）。
"""
PIL_OK = False
PILImage = None
try:
    from PIL import Image as PILImage      # type: ignore  # noqa: F401
    PIL_OK = True
except Exception:
    PILImage = None

RAR_AVAILABLE = False
rarfile = None
try:
    import rarfile                        # type: ignore  # noqa: F401
    RAR_AVAILABLE = True
except Exception:
    rarfile = None
