# -*- coding: utf-8 -*-
"""migrations/ —— 文库整理脚本（migrate.py）的实现包（3.6.78 从单体拆出）。

    base.py      常量 / APP_DIR / 共享工具（ask、unique_path、learn_registry…）
    migrator.py  模式一：1区 → 社团目录的执行器
    modes.py     模式二/三/三'：解散汉化目录、规范化文件名、按归属重组

`migrate.py` 只是 CLI：解析参数 → 调这里三个入口 → 返回码。
**工程纪律**：这里的函数会真实移动/删除用户文件，任何改动都必须：
  ① 先 `--dry-run` 在真实库上预览；② 不引入模块级可变开关（全部走参数）；
  ③ 新增模式要同步 README 用法段与 CHANGELOG。
"""
