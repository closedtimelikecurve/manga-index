# -*- coding: utf-8 -*-
"""routes/host.py —— 兼容再导出（实现已下沉到 `panel/host.py`，services 也要用）。"""
from panel.host import h

__all__ = ["h"]
