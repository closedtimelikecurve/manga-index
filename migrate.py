#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate.py —— 【高风险】文库整理脚本
====================================
模式一：1区 → 社团目录迁移（默认）
  扫描 根目录/1区 下的作品，按文件名提取社团名移动到对应社团目录；
  完成后若 1区 已空，询问是否删除。

模式二：解散汉化目录（--dissolve-hanhua）
  根目录下所有名字含“汉化/漢化”的目录视为汉化组目录，予以解散：
  其内部作品按最新规则（跳过汉化组词条）重新归入社团目录、按待定词条新建档或 未分类，
  清空的目录询问后删除。

模式三：批量规范化文件名（--normalize-names）
  把所有作品文件名规范为统一格式：
    [無修正] (展会) [社团名 (个人名)] 标题 【汉化组名】 (原作名) [其他词条]
  仅在同目录内重命名（不移动），目标重名时自动加 (2)/(3)… 后缀。

用法：
  python migrate.py                       # 模式一，交互确认
  python migrate.py --dissolve-hanhua     # 模式二
  python migrate.py --normalize-names     # 模式三
  python migrate.py --dry-run             # 任意模式：只预览，不改动
  python migrate.py --yes                 # 跳过所有确认
  python migrate.py --root "D:\同人志" --source "D:\同人志区"

注意：本脚本绝不覆盖已存在文件；正式执行前请先 --dry-run 预览。
程序与文库分目录：本脚本位于 <文库根>/_app/ 内，默认文库根 = _app 的上级目录；
迁移/整理日志一律写入 _app/（不再落在文库根目录，保持文库整洁）。
"""
import argparse
import os
import sys

sys.dont_write_bytecode = True

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

from migrations.base import DEFAULT_LIB_ROOT                                   # noqa: E402
from migrations.migrator import Migrator                                       # noqa: E402
from migrations.modes import dissolve_hanhua, normalize_names, reorganize_dirs  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="文库整理脚本（1区迁移 / 解散汉化目录 / 规范化命名）")
    ap.add_argument("--root", default=None, help="文库根目录（默认: 脚本所在目录）")
    ap.add_argument("--source", default=None, help="模式一源目录（默认: 根目录/1区）")
    ap.add_argument("--dissolve-hanhua", action="store_true", help="模式二：解散名字含 汉化/漢化 的目录")
    ap.add_argument("--normalize-names", action="store_true", help="模式三：批量规范化所有文件名")
    ap.add_argument("--reorganize", action="store_true", help="模式四：按新标准(社团名=[]减())更新目录")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不做任何改动")
    ap.add_argument("--yes", action="store_true", help="跳过所有确认")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    root = os.path.abspath(args.root) if args.root else DEFAULT_LIB_ROOT

    if args.dissolve_hanhua:
        return 0 if dissolve_hanhua(root, dry_run=args.dry_run, auto_yes=args.yes) else 1
    if args.normalize_names:
        return 0 if normalize_names(root, dry_run=args.dry_run, auto_yes=args.yes) else 1
    if args.reorganize:
        return 0 if reorganize_dirs(root, dry_run=args.dry_run, auto_yes=args.yes) else 1

    source = os.path.abspath(args.source) if args.source else os.path.join(root, "1区")
    if not os.path.isdir(source):
        print(f"[错误] 源目录不存在：{source}")
        print("提示：可指定 --source 或 --root 后再试。")
        return 1
    return 0 if Migrator(root, source, dry_run=args.dry_run, auto_yes=args.yes).run() else 1


if __name__ == "__main__":
    sys.exit(main())
