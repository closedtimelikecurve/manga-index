# -*- coding: utf-8 -*-
"""migrations/migrator.py —— 模式一（1区 → 社团目录）的执行器（3.6.78 从 migrate.py 拆出）。"""
import datetime
import os
import shutil
from collections import Counter

import common                                   # noqa: E402
from djc_parse import bare_of, circle_of, clean_spaces, primary_bracket_info

from .base import (ARCHIVE_EXTS, IMAGE_EXTS, NO_CIRCLE_DIR, ask, unique_path)


class Migrator:
    def __init__(self, root, source, dry_run=False, auto_yes=False):
        self.root = os.path.abspath(root)
        self.source = os.path.abspath(source)
        self.dry_run = dry_run
        self.auto_yes = auto_yes
        self.plan = []          # [{src, dst, note, is_dir}]
        self.log_lines = []
        self.moved = self.conflicted = self.failed = 0
        self._planned = set()   # 计划中已占用的目标路径

    # ---------- 计划 ----------
    def _archive_dir_name(self, term):
        """档案目录名：已有同名目录（含下划线写法）→ 沿用；否则用规范名（_ → 空格）。"""
        clean = clean_spaces(term)
        for cand in (term, clean):
            p = os.path.join(self.root, cand)
            if os.path.isdir(p) and not cand.startswith("."):
                return cand
        return clean

    def build_plan_item(self, path, is_dir):
        name = os.path.basename(path)
        circle = circle_of(name)
        if not circle and bare_of(name):
            # 待定词条（裸 [a]）无法匹配已知社团/个人 → 直接以其本身建档
            circle = self._archive_dir_name(bare_of(name))
        if not circle:
            circle = NO_CIRCLE_DIR          # 完全没有词条 → 未分类
        target_dir = os.path.join(self.root, circle.strip().rstrip(".") or NO_CIRCLE_DIR)
        target = os.path.join(target_dir, name)
        final = unique_path(target, self._planned)
        self._planned.add(final)
        note = ""
        if final != target:
            note = f"目标已存在，将改名 {os.path.basename(final)}"
            self.conflicted += 1
        self.plan.append({"src": path, "dst": final, "note": note, "is_dir": is_dir})

    def collect_from_dir(self, path, depth=0):
        """
        目录处理规则：
        - 名字含 [] → 整目录作为一部作品迁移
        - 名字无 [] 但里面有图片 → 整目录作为一部作品迁移（归入未分类）
        - 否则把内部压缩包逐个作为作品迁移，子目录递归
        """
        if depth > 8:
            return
        name = os.path.basename(path)
        if primary_bracket_info(name)[0] != "none":
            self.build_plan_item(path, True)
            return
        images, archives, subdirs = [], [], []
        try:
            for e in os.scandir(path):
                if e.is_dir(follow_symlinks=False):
                    subdirs.append(e)
                elif e.is_file(follow_symlinks=False):
                    ext = os.path.splitext(e.name)[1].lower()
                    if ext in IMAGE_EXTS:
                        images.append(e)
                    elif ext in ARCHIVE_EXTS:
                        archives.append(e)
        except OSError:
            return
        if images:
            self.build_plan_item(path, True)
            return
        for e in sorted(archives, key=lambda x: x.name):
            self.build_plan_item(e.path, False)
        for d in sorted(subdirs, key=lambda x: x.name):
            self.collect_from_dir(d.path, depth + 1)

    # ---------- 执行 ----------
    def _log(self, action, src, dst, note=""):
        rel_src = os.path.relpath(src, self.root)
        rel_dst = os.path.relpath(dst, self.root)
        line = f"[{action}] {rel_src} -> {rel_dst}"
        if note:
            line += f"  ({note})"
        self.log_lines.append(line)
        print("  " + line)

    def execute_plan(self):
        for item in self.plan:
            target_dir = os.path.dirname(item["dst"])
            final = unique_path(item["dst"])   # 执行时对磁盘再复查一次，绝不覆盖
            note = item["note"]
            if final != item["dst"]:
                note = note or f"执行时目标已存在，改名 {os.path.basename(final)}"
            try:
                os.makedirs(target_dir, exist_ok=True)
                if item["is_dir"]:
                    shutil.move(item["src"], final)
                else:
                    os.rename(item["src"], final)
                self.moved += 1
                self._log("移动", item["src"], final, note)
            except Exception as e:
                self.failed += 1
                self._log("失败", item["src"], final, str(e))

    def write_log(self):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(common.LOG_DIR, f"migrate_log_{ts}.log")   # 3.7 Stage3：日志写入 _app/_logs/
        common.ensure_dir(common.LOG_DIR)
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"# 迁移日志 {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")
                f.write(f"# 源: {self.source}\n# 根: {self.root}\n\n")
                for line in self.log_lines:
                    f.write(line + "\n")
                f.write(f"\n# 汇总: 移动 {self.moved} / 冲突改名 {self.conflicted} / 失败 {self.failed}\n")
            print(f"\n迁移日志已写入: {log_path}")
        except Exception as e:
            print(f"\n[警告] 日志写入失败: {e}")

    def source_has_files(self):
        for _d, _dnames, fnames in os.walk(self.source):
            if fnames:
                return True
        return False

    def run(self):
        """模式一入口：校验 → 采样 → 预览 → 确认 → 执行 → 清理 1区。"""
        if not self._check_paths():
            return False
        self._print_banner()
        self._scan_source()
        if not self.plan:
            print("\n1区 下没有可迁移的作品（无压缩包/图片作品）。")
            return False

        self._print_plan(40)
        if self.dry_run:
            print("\n[DRY-RUN] 以上仅为预览，未做任何改动。")
            return True
        if not self.auto_yes and not ask(f"\n确认执行以上 {len(self.plan)} 件移动？"):
            print("已取消，未做任何改动。")
            return False

        print("\n开始迁移……")
        self.execute_plan()
        self.write_log()
        self._cleanup_source()
        print("\n完成。")
        return True

    def _check_paths(self):
        """源/根目录基本校验：源必须存在，且不能与根相同（否则会自我搬运）。"""
        if not os.path.isdir(self.source):
            print(f"[错误] 源目录不存在：{self.source}")
            return False
        if os.path.abspath(self.root) == self.source:
            print("[错误] 根目录与源目录不能相同。")
            return False
        return True

    def _print_banner(self):
        print("=" * 64)
        print("  1区 → 社团目录 迁移脚本")
        print(f"  源目录: {self.source}")
        print(f"  根目录: {self.root}")
        print("=" * 64)

    def _scan_source(self):
        """把 1区 里的作品逐条喂进 plan（子目录递归；压缩包按文件收）。"""
        for e in sorted(os.scandir(self.source), key=lambda x: x.name):
            try:
                if e.is_dir(follow_symlinks=False):
                    self.collect_from_dir(e.path)
                elif e.is_file(follow_symlinks=False) and os.path.splitext(e.name)[1].lower() in ARCHIVE_EXTS:
                    self.build_plan_item(e.path, False)
            except OSError:
                continue

    def _print_plan(self, limit):
        """按目标社团汇总 + 前 limit 条预览（完整清单在日志里）。"""
        circles = Counter(os.path.relpath(os.path.dirname(i["dst"]), self.root) for i in self.plan)
        print(f"\n共发现 {len(self.plan)} 件作品，将归入 {len(circles)} 个社团目录：")
        for c, n in circles.most_common():
            print(f"  {n:4d} 件 → {c}")
        print(f"  其中冲突（目标已存在，将自动改名）: {self.conflicted} 件")
        print(f"\n预览（前 {limit} 条，完整见日志）：")
        for i, item in enumerate(self.plan[:limit], 1):
            rel_src = os.path.relpath(item["src"], self.source)
            rel_dst = os.path.relpath(item["dst"], self.root)
            note = f"  ({item['note']})" if item["note"] else ""
            print(f"  {i:3d}. {rel_src}  ->  {rel_dst}{note}")
        if len(self.plan) > limit:
            print(f"  …（其余 {len(self.plan) - limit} 件省略）")

    def _cleanup_source(self):
        """1区 搬空则询问删除；仍有残留就列前 10 个并保留目录。"""
        if not self.source_has_files():
            if self.auto_yes or ask("\n1区 已无任何文件，是否删除 1区 文件夹？"):
                try:
                    shutil.rmtree(self.source)
                    print(f"已删除空目录: {self.source}")
                except Exception as e:
                    print(f"[警告] 删除失败: {e}")
            else:
                print("保留 1区 文件夹（已为空）。")
            return

        remain = [os.path.join(_d, fn)
                  for _d, _dn, fnames in os.walk(self.source) for fn in fnames]
        print(f"\n[提示] 1区 下仍有 {len(remain)} 个文件未迁移，未删除 1区：")
        for p in remain[:10]:
            print(f"  {os.path.relpath(p, self.root)}")
        if len(remain) > 10:
            print(f"  …（其余 {len(remain) - 10} 个省略）")

