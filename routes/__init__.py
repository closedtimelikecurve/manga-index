# -*- coding: utf-8 -*-
"""routes —— HTTP 端点薄层（3.6.53 Stage6 起从 `app.py` 逐域迁出）。

设计约束（改这里之前必读）
  1. **禁止 `import app`**：`python app.py` 运行时应用模块是 `__main__`，再导入会二次执行
     app.py → 第二个 Flask 实例 + 第二份状态。一律用 `from routes.host import h` 后 `h().xxx`。
  2. **按名取值而不是按值捕获**：测试大量 `monkeypatch.setattr(app, "find_work", ...)`；
     若在启动时把函数对象存进命名空间，打桩会**静默失效**（`test_crawl_parallel` 打的是
     `app.subprocess.Popen`，失效会让测试真的拉起爬虫进程）。`h()` 每次调用重新解析。
  3. **端点函数保持模块级**：静态检查（如 `test_mutation_gate`）按函数名定位；注册集中在
     文件末尾的 `ROUTES` 表 + `register(app)`。
  4. **搬迁 = 纯搬移**：不改逻辑、不改注释、不改打桩目标。搬完跑全量测试 + `quality_gate --prune`
     （重建债务表，避免"函数换文件"被误判为新增超预算）。

当前域（74 个端点已全部迁出 app.py）
  library.py    首页壳/config/library(+meta)/circle/works/parse-info/增补信息/search（10）
  media.py      pages/page/cover/audio(+manifest)/open（6）
  authors.py    作者别名增删查（3）
  meta.py       作品元数据、评分、收藏、阅读进度、画师、关注（17）
  originals.py  原作分区列表/检索/增删改名（6）
  crawl.py      爬虫任务状态/启停/清单（5）
  inbox.py      收件箱列表/确认/清理/删除/一键入库（5）
  manage.py     删作品/封面、画师改名、黑名单、设置/清除封面（7）
  manage_circle.py  删社团、社团改名、社团解散（3）
  admin.py      面板重启、导入、上传、备份/导出、APP 版本派发、配置保存（12）

下一步（Stage 7）：`app.py` 剩下的业务 helper（scan/index/import/inbox）按域下沉到 `services/`。
纪律：每次搬迁跑全量测试 + `quality_gate --prune`；带 `@mutating` 的端点搬走后，
`test_mutation_gate` 仍会通过 routes 的 ROUTES 表 + `h().xxx` 调用图核对。
"""
