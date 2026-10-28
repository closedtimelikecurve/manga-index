# 贡献指南

这个项目的代码风格和结构有比较硬的约束，**动手前请先读
[`docs/engineering-discipline.md`](docs/engineering-discipline.md)** —— 那不是建议，
是由脚本和测试自动判定的闸门。结构地图见 [`docs/architecture.md`](docs/architecture.md)。

## 环境

```bat
pip install -r requirements.txt -r requirements-dev.txt
git config core.hooksPath .githooks      :: 提交前自动跑工程纪律闸门（约 1 秒）
```

## 提交前自检

```bat
python scripts/quality_gate.py     :: 文件/函数预算、注释规则、双端对齐
python -m ruff check .
python -m pytest tests/ -q
```

三条全绿再提 PR。CI 跑的是同一套，红了会挡住合并。

## 硬约束（摘要，细则以纪律文档为准）

- 单文件行数：Python / JS 400、Kotlin 500；单函数 50 行、圈复杂度 ≤ 15
- 双端对齐：网页与 Android 的功能改动要成对出现，或明确说明为什么只改一端
- 新增依赖要先讨论：主程序只接受 flask / pillow / waitress / rarfile 这一层的量级
- 注释写"为什么"，不写"是什么"；禁止无信息量的分节注释
- 中文注释与文档，代码标识符用英文

## 提交信息

沿用现有风格，一行说清改了什么、为什么：

```
fix(crawl): 通道排错队导致反搜无结果；JM 并发 30 压垮代理（3.6.157）
feat(panel): 主题图库支持自定义排序
```

前缀用 `feat / fix / chore / docs / test / refactor`，括号里是模块名。

## PR

- 一个 PR 只做一件事，附上"怎么验证的"（跑了哪些测试、手动点了哪些路径）
- 涉及 UI 的改动请附截图；**截图请用占位图模式**取：
  `python scripts/test_panel.py start` 起的是 8767 端口隔离实例，
  封面与内页一律回占位图，不会把真实文库内容带进公开仓库
- 不要提交 `config.json`、`meta.db`、`_cache/`、`_state/`、`_logs/`、任何作品文件
