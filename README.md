# Index — 本地漫画文库管理面板

[**中文**](README.md) · [English](README.en.md) · [日本語](README.ja.md)

<p align="center">
  <img src="docs/screenshots/web-home.jpg" width="620" alt="网页端首页">
  <img src="docs/screenshots/app-home.jpg" width="215" alt="Android 端首页">
</p>

按**社团**浏览、自动打**标签**（展会 / 原作 / 画师）、**全局标签检索**、收件箱确权入库、
阅读进度跨端同步，自带 Android 阅读器。纯本地运行，Flask API + 原生 HTML/JS，不需要任何云服务。

> **仅供本地、个人使用。本项目不提供、不托管、不分发任何受版权保护的内容文件，
> 也不内置任何站点凭据。使用者需自行遵守所在地区法律与目标网站的服务条款。**
>
> 截图中的封面与作品信息已统一替换为占位图。

## 功能

- **文库扫描**：读 `<社团>/<作品>.zip|cbz|rar|cbr` 或 `<社团>/<作品名>/图片…`，按文件名解析
  `(C100) [社团 (画师)] 标题 (原作) [汉化]` 这一套命名约定，认不出词条的自动归入待定档案夹
- **元数据层**：`meta.db`（SQLite）是唯一事实源——标签、阅读进度、评分、别名、喜爱画师都在这里，
  不是散在文件名里的"猜"
- **收件箱**：下载产物统一落 `_inbox/`，人工确认后入库（sha1 去重、自动改名、自动归区）
- **阅读服务**：网页阅读器 + Android APP（离线包、进度双向同步、扫码配对、图片质量三档）
- **外接下载器**：用命令模板接任意 CLI 下载器（gallery-dl 等），产物打包进收件箱
- **内测模式**：抽屉里一键把所有封面换成占位图，截图 / 录屏给别人看时不暴露文库内容

## 环境要求

| | |
|---|---|
| 系统 | Windows 10 / 11（主目标平台；启动面板、进程管理、局域网配对都按 Windows 实现，Linux / macOS 未验证） |
| Python | 3.10+（CI 跑 3.12 / 3.13） |
| 可选 | [UnRAR](https://www.rarlab.com/rar_add.htm) 或 WinRAR —— 只有要读 `.rar` / `.cbr` 时才需要，把 `unrar.exe` 所在目录加进 `PATH`；不装则 rar 类作品的封面与页列表不可用，其它格式不受影响 |

## 快速开始

```bat
pip install -r requirements.txt
copy config.example.json config.json
python app.py            :: 默认 http://127.0.0.1:8765
```

程序与文库**分目录**存放：本程序位于文库根的 `_app/` 子目录，文库根默认为其上级目录
（可在网页「设置」里改）。

```
D:\my-library\          ← 文库根
├── 社团A (画师名)\
│   ├── (C100) [社团A (画师名)] 标题 (原作).zip
│   └── 作品文件夹\图片…
└── _app\               ← 本程序
    ├── app.py
    ├── config.json     ← 本机配置（主令牌 / 文库路径），已列入 .gitignore，不要提交
    ├── meta.db         ← 元数据（勿删）
    ├── _inbox\         ← 待确认的作品
    └── _cache\ _logs\ _state\   ← 运行时产物，可随时删除重建
```

## 外接下载器

不绑定任何站点，用命令模板接你已经在用的下载器。`config.json`：

```json
"ext_downloaders": [
  { "name": "gallery-dl", "cmd": "gallery-dl -d \"{dest}\" {url}", "timeout": 1800 }
]
```

网页「清单下载器」→「外接下载器」：每行贴一个 URL（原样作为 `{url}`），`{dest}` 是本次暂存目录，
产物打包 zip 落进收件箱，确认后入库。

## 内置站点适配

本仓库只随附 **JM 直连**（`crawlers/crawl_jm_direct.py`，依赖公开的
[jmcomic](https://github.com/hect0x7/JMComic-Crawler-Python) 库，需 `pip install jmcomic`）。
其余适配不随本仓库分发；面板会按实际可用的任务自动收窄界面。

## 开发

- 工程纪律与量化预算：[`docs/engineering-discipline.md`](docs/engineering-discipline.md)
  —— 文件行数、函数行数与圈复杂度都是**机器判定**的，由 `scripts/quality_gate.py` + 测试执行
- 结构地图：[`docs/architecture.md`](docs/architecture.md)
- 发布历史：[`CHANGELOG.md`](CHANGELOG.md)

```bat
pip install -r requirements.txt -r requirements-dev.txt
python scripts/quality_gate.py     :: 工程纪律闸门
python -m pytest tests/ -q         :: 回归测试
python -m ruff check .             :: 静态检查（辅助提示）
git config core.hooksPath .githooks  :: 可选：提交前自动跑闸门
```

## 已知限制

- **单用户**设计：没有账号体系，令牌只用于远程访问门禁（本机回环免令牌）
- 手机端需与电脑同局域网，或处于同一虚拟组网（Tailscale / ZeroTier 等）
- 首次扫描大文库较慢，缩略图按需生成
- `meta.db` 是唯一事实源，升级前建议自行备份

## 安全

发现安全问题请按 [`SECURITY.md`](SECURITY.md) 私下报告，不要开公开 issue。
威胁模型（令牌门禁 / 局域网暴露 / 扫码配对 / 路径穿越 / 外接下载器）在那份文件里列了表。

## License

[GPL-3.0](LICENSE) · Copyright (C) 2026 Index contributors
