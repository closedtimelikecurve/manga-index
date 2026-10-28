# -*- coding: utf-8 -*-
"""禁书目录 Index · 面板服务端包（2026-10 结构重构起点）。

为什么有这层：`app.py` 曾是 5800+ 行 / 260+ 顶层函数 / 0 个类的巨石文件，
改一处要通读全文、测试无法只测子域。本包按**子系统**切分，逐步把 app.py 掏空，
最终 app.py 只保留「Flask 装配 + 路由注册 + 兼容命名面 + main()」。

迁移纪律（务必遵守，否则坑很痛）：
  1. **app.py 必须继续再导出**本包里的既有名字（`from panel.paths import natural_key`）。
     测试与调用方大量依赖 `app.natural_key`、`app.LOW_DIR`、`app._page_cache` 等命名面。
  2. **模块级可变状态**要么留在 app.py，要么放本包单一模块、且在 app.py 只做
     「同对象再导出」。绝不在两处各自赋值（会分叉成两份状态）。
  3. 若某状态是**可重绑定的**（会被 `X = ...` 整体替换，而非原地改 dict/list），
     不要用 `from ... import X` 共享——那只会拿到快照。放 `panel/state.py` 统一持有，
     调用方用 `state.X` 访问；测试中止旧打桩点一并迁移。
  4. 抽出模块若被测试打桩（`monkeypatch.setattr(app, "...")`），把打桩点同步改到
     本包对应模块（详见各测试文件注释与 .workbuddy/memory/MEMORY.md）。

当前模块（12 个）：
  deps.py     可选依赖探测（Pillow / rarfile）
  paths.py    路径 / 文件名 / 媒体类型工具（无业务状态）
  archive.py  压缩包句柄 LRU + 页面字节 LRU + 页面/视频临时文件
  images.py   封面读取 / 缩略图 / 低带宽转码 / Tailscale 判路
  audio.py    音频页 / lrc 解析
  pages.py    页序 / 版本分组
  naming.py   「增补信息 → 规范文件名」纯函数（3.6.45 Stage4；不 import app）
  text.py     纯文本与括号处理（3.6.64 从 djc_parse 拆出）
  terms.py    原作词条名单与加载（3.6.64 从 djc_parse 拆出）
  state.py    进程内唯一可变状态 LibraryState（3.6.49；__slots__，无 I/O）
  host.py     h()：按名解析"当前真正在跑的应用模块"（3.6.55，避免反向 import app）
  http.py     @mutating 装饰器 + MUTATING_ENDPOINTS（3.6.53，写端点与扫描互斥）
"""
