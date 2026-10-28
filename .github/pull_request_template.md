## 改了什么

<!-- 一句话说清。相关 issue：fixes #0 -->

## 为什么这么改

<!-- 根因或动机。如果是修 bug，说清原来的行为错在哪。 -->

## 怎么验证的

- [ ] `python scripts/quality_gate.py` 通过
- [ ] `python -m ruff check .` 通过
- [ ] `python -m pytest tests/ -q` 通过（新增/改动的测试写在这里：）

## 双端对齐

<!-- 网页端与 Android 是否已成对改动？只改一端的话，说明为什么另一端不需要动。 -->

## 检查清单

- [ ] 没有提交 `config.json` / `meta.db` / `_cache/` / `_state/` / `_logs/` / 任何作品文件
- [ ] 提交信息符合 `type(scope): 说明` 格式
- [ ] UI 改动附了截图（用 `python scripts/test_panel.py start` 的占位图模式截的）
