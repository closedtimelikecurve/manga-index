# -*- coding: utf-8 -*-
"""migrations/modes.py —— 三种整理模式的实现（3.6.78 从 migrate.py 拆出）。

模式二 `dissolve_hanhua`：解散汉化组目录
模式三 `normalize_names`：批量规范化文件名
模式三' `reorganize_dirs`：按作品归属重组目录（collect_all_works 是它的采样阶段）
全部是**高风险文件操作**：只接收 `dry_run` / `auto_yes`，不读模块级开关；
正式执行前必须先 `--dry-run`。
"""
import datetime
import os
import shutil
from collections import Counter, defaultdict

import common                                   # noqa: E402
from djc_parse import normalize_filename, primary_bracket_info

from .base import (ARCHIVE_EXTS, IGNORE_DIRS, IMAGE_EXTS, _iter_group_archives, ask,
                   dir_has_files, learn_registry, resolve_dir_target, unique_path)
from .migrator import Migrator


def dissolve_hanhua(root, dry_run=False, auto_yes=False):
    """根目录下所有名字含 汉化/漢化 的目录 → 解散：内部作品按新规则重新归类。"""
    dirs = _hanhua_dirs(root)
    if dirs is None:
        return False
    if not dirs:
        print("未找到名字含“汉化/漢化”的目录。")
        return True

    print("=" * 64)
    print("  解散汉化目录：内部作品按最新规则重新归入社团 / 未分类")
    for d in dirs:
        print(f"  - {d.name}")
    print("=" * 64)

    m = Migrator(root, root, dry_run=dry_run, auto_yes=auto_yes)
    _collect_dissolve(m, dirs)
    if not m.plan:
        print("这些目录下没有可迁移的作品。")
        return True

    _print_dissolve_plan(m, root)
    if dry_run:
        print("\n[DRY-RUN] 以上仅为预览，未做任何改动。")
        return True
    if not auto_yes and not ask(f"\n确认执行以上 {len(m.plan)} 件移动？"):
        print("已取消。")
        return False

    print("\n开始迁移……")
    m.execute_plan()
    m.write_log()
    _remove_empty_dirs(dirs, auto_yes)
    _warn_remaining(dirs)
    print("\n完成。")
    return True


def _hanhua_dirs(root):
    """根目录下一层里名字含 汉化/漢化 的目录；读不到根目录返回 None（区别于"没有"）。"""
    try:
        return [e for e in sorted(os.scandir(root), key=lambda x: x.name)
                if e.is_dir(follow_symlinks=False) and (("汉化" in e.name) or ("漢化" in e.name))]
    except OSError:
        return None


def _collect_dissolve(m, dirs):
    """把汉化目录里的作品逐条喂给 Migrator（子目录递归、压缩包按文件收）。"""
    for d in dirs:
        try:
            for e in sorted(os.scandir(d.path), key=lambda x: x.name):
                if e.is_dir(follow_symlinks=False):
                    m.collect_from_dir(e.path)
                elif e.is_file(follow_symlinks=False) and os.path.splitext(e.name)[1].lower() in ARCHIVE_EXTS:
                    m.build_plan_item(e.path, False)
        except OSError:
            continue


def _print_dissolve_plan(m, root):
    """按目标社团汇总 + 前 30 条预览（完整清单在日志里）。"""
    circles = Counter(os.path.relpath(os.path.dirname(i["dst"]), root) for i in m.plan)
    print(f"\n共 {len(m.plan)} 件作品将重新归类：")
    for c, n in circles.most_common():
        print(f"  {n:4d} 件 → {c}")
    print(f"  其中冲突（自动改名）: {m.conflicted} 件")
    print("\n预览（前 30 条，完整见日志）：")
    for i, item in enumerate(m.plan[:30], 1):
        note = f"  ({item['note']})" if item["note"] else ""
        print(f"  {i:3d}. {os.path.relpath(item['src'], root)}  ->  {os.path.relpath(item['dst'], root)}{note}")
    if len(m.plan) > 30:
        print(f"  …（其余 {len(m.plan) - 30} 件省略）")


def _remove_empty_dirs(dirs, auto_yes):
    """已搬空的汉化目录：确认后删除（删不掉只告警，绝不中断）。"""
    empty_dirs = [d for d in dirs if not dir_has_files(d.path)]
    if not empty_dirs:
        return
    names = "、".join(d.name for d in empty_dirs)
    if not (auto_yes or ask(f"\n以下目录已无文件，是否删除？\n  {names}\n确认删除这些空目录？")):
        print("保留这些空目录。")
        return
    for d in empty_dirs:
        try:
            shutil.rmtree(d.path)
            print(f"已删除空目录: {d.name}")
        except Exception as e:
            print(f"[警告] 删除失败 {d.name}: {e}")


def _warn_remaining(dirs):
    """仍有文件的目录要明确告诉用户"为什么没删"。"""
    for d in dirs:
        if not dir_has_files(d.path):
            continue
        n = sum(len(fs) for _d, _dn, fs in os.walk(d.path))
        print(f"[提示] {d.name} 下仍有 {n} 个文件未迁移，目录保留。")


def collect_all_works(root):
    """收集根目录下所有作品（压缩包文件 + 一层文件夹作品），返回 [(目录, 名称, 是否文件夹)]。"""
    try:
        entries = sorted(os.scandir(root), key=lambda x: x.name)
    except OSError:
        return []
    works = []
    for top in entries:
        try:
            works.extend(_works_of_top(root, top))
        except OSError:
            continue
    return works


def _works_of_top(root, top):
    """根目录下一项：目录 → 组内作品；压缩包 → 自身；其余忽略。"""
    if top.is_dir(follow_symlinks=False):
        if top.name in IGNORE_DIRS or top.name.startswith("."):
            return []
        return _works_in_group(top.path)
    if top.is_file(follow_symlinks=False) and os.path.splitext(top.name)[1].lower() in ARCHIVE_EXTS:
        return [(root, top.name, False)]
    return []


def _works_in_group(group_path):
    """一个社团目录：所有层级里的压缩包 + 直接子目录里"自己含图"的文件夹作品。"""
    out = []
    for d, _dn, fnames in os.walk(group_path):
        for fn in fnames:
            if os.path.splitext(fn)[1].lower() in ARCHIVE_EXTS:
                out.append((d, fn, False))
    for e in sorted(os.scandir(group_path), key=lambda x: x.name):
        if e.is_dir(follow_symlinks=False) and _dir_has_image(e.path):
            out.append((group_path, e.name, True))
    return out


def _dir_has_image(path):
    """只看直接子项：有图片就认定这是"一部文件夹作品"（不递归，避免把社团目录误判）。"""
    return any(x.is_file(follow_symlinks=False)
               and os.path.splitext(x.name)[1].lower() in IMAGE_EXTS
               for x in os.scandir(path))


def normalize_names(root, dry_run=False, auto_yes=False):
    """把所有作品文件名规范为统一格式（同目录内重命名，不移动位置）。"""
    if not os.path.isdir(root):
        print(f"[错误] 根目录不存在：{root}")
        return False

    plan = _normalize_plan(root)
    if not plan:
        print("所有文件名均已符合规范格式，无需修改。")
        return True

    _print_normalize_plan(plan)
    if dry_run:
        print("\n[DRY-RUN] 以上仅为预览，未做任何改动。")
        return True
    if not auto_yes and not ask(f"\n确认对以上 {len(plan)} 个文件重命名？"):
        print("已取消。")
        return False

    done = _apply_renames(root, plan)
    print(f"\n完成：{done}/{len(plan)} 个文件已规范化。")
    return True


def _normalize_plan(root):
    """按目录分组算目标名；同目录内用 unique_path 去重（避免互相撞名）。"""
    by_dir = defaultdict(list)
    for d, name, is_dir in collect_all_works(root):
        base, ext = (name, "") if is_dir else os.path.splitext(name)
        new = normalize_filename(base, ext)
        if not new or new == name:
            continue
        by_dir[d].append((name, new, is_dir))

    plan = []
    for d, items in sorted(by_dir.items()):
        taken = set()
        for name, new, is_dir in items:
            final = unique_path(os.path.join(d, new), taken)
            taken.add(final)
            plan.append((os.path.join(d, name), final, name, new, is_dir))
    return plan


def _print_normalize_plan(plan):
    print("=" * 64)
    print(f"  批量规范化文件名（共 {len(plan)} 个文件将改名）")
    print("=" * 64)
    print("\n预览（前 30 条，完整见日志）：")
    for i, (src, dst, name, new, _isd) in enumerate(plan[:30], 1):
        print(f"  {i:3d}. {name}")
        print(f"       -> {new}")
    if len(plan) > 30:
        print(f"  …（其余 {len(plan) - 30} 个省略）")


def _apply_renames(root, plan):
    """逐个 os.rename，失败只记一条不中断；返回成功数（日志写 _app/_logs）。"""
    log_lines = []
    done = 0
    for src, dst, name, new, is_dir in plan:
        try:
            os.rename(src, dst)
            done += 1
            log_lines.append(f"[改名] {os.path.relpath(src, root)} -> {os.path.relpath(dst, root)}")
        except Exception as e:
            log_lines.append(f"[失败] {os.path.relpath(src, root)} ({e})")
            print(f"  [失败] {name}: {e}")
    _write_migrate_log("规范化日志", root, log_lines, f"成功 {done} / 计划 {len(plan)}")
    return done


def _write_migrate_log(title, root, log_lines, summary):
    """统一写 _app/_logs/migrate_log_<ts>.log；写失败只告警（不影响已完成的文件操作）。"""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(common.LOG_DIR, f"migrate_log_{ts}.log")
    common.ensure_dir(common.LOG_DIR)
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"# {title} {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n# 根: {root}\n\n")
            f.write("\n".join(log_lines) + f"\n\n# 汇总: {summary}\n")
        print(f"\n日志已写入: {log_path}")
    except Exception as e:
        print(f"[警告] 日志写入失败: {e}")
    return log_path


def reorganize_dirs(root, dry_run=False, auto_yes=False):
    """按新标准（社团名=[]减()）更新顶层目录：改名 / 合并。"""
    if not os.path.isdir(root):
        print("[错误] 根目录不存在：" + root)
        return False
    circles, personal_circles = learn_registry(root)
    print("=" * 64)
    print("  按新标准更新目录（社团名 = []内容 减 ()内容）")
    print(f"  词条库：已知社团 {len(circles)} / 已知个人 {len(personal_circles)}")
    print("=" * 64)

    plan, stats, targets = _reorg_plan(root, circles, personal_circles)
    _print_reorg_plan(plan, targets)
    if dry_run:
        print("\n[DRY-RUN] 以上仅为预览，未做任何改动。")
        return True
    if not auto_yes and not ask(f"\n确认执行以上 {len(plan)} 组目录调整？"):
        print("已取消。")
        return False

    done = _apply_reorg(root, plan)
    print(f"完成：调整 {len(plan)} 组目录，移动 {done} 项。")
    return True


def _reorg_dirs(root):
    """候选顶层目录：跳过程序目录/隐藏目录/未分类。"""
    return [d for d in sorted(os.listdir(root))
            if os.path.isdir(os.path.join(root, d)) and d not in IGNORE_DIRS
            and not d.startswith(".") and d != "未分类"]


def _reorg_plan(root, circles, personal_circles):
    """按目录内 [社团]/[待定] 的票数决定目标名；same/keep/pending/mixed 只计统计不动手。"""
    plan = []   # (src_dir, target_dir, kind, embed_personal)
    stats = {"circle": 0, "personal": 0, "circle-resolved": 0, "pending": 0, "same": 0, "mixed": 0}
    targets = {}
    for d in _reorg_dirs(root):
        circle_count, bare_count = _dir_terms(root, d)
        if not circle_count and not bare_count:
            continue
        total = sum(circle_count.values()) + sum(bare_count.values())
        target, kind, embed = resolve_dir_target(d, circle_count, bare_count, total,
                                                 circles, personal_circles)
        if kind in ("same", "keep", "pending", "mixed"):
            stats["pending" if kind == "pending" else ("mixed" if kind == "mixed" else "same")] += 1
            continue
        plan.append((d, target, kind, embed))
        stats[kind] += 1
        targets.setdefault(target, []).append(d)
    return plan, stats, targets


def _dir_terms(root, d):
    """某目录内所有压缩包的主括号统计：[社团] 票数 / [待定] 票数。"""
    circle_count, bare_count = Counter(), Counter()
    for fp in _iter_group_archives(os.path.join(root, d)):
        n = os.path.splitext(os.path.basename(fp))[0]
        kind, c, _p, b = primary_bracket_info(n)
        if kind == "circle":
            circle_count[c] += 1
        elif kind == "bare":
            bare_count[b] += 1
    return circle_count, bare_count


def _print_reorg_plan(plan, targets):
    """合并的一组打成一行；单目录按 kind 标"改名/印证社团/并入社团"。"""
    print(f"\n将执行 {len(plan)} 次目录调整：")
    for t, srcs in sorted(targets.items()):
        if len(srcs) > 1:
            print(f"  ⛙ 合并 → {t}   ← " + "、".join(srcs))
            continue
        s0 = srcs[0]
        kind = next(k for (d, _, k, _e) in plan if d == s0)
        mark = "并入社团" if kind == "personal" else ("印证社团" if kind == "circle-resolved" else "改名")
        print(f"  {mark}: {s0}  ->  {t}")


def _apply_reorg(root, plan):
    """逐组搬文件：子目录整体 move；个人归档按需把 [待定] 改写为 [社团 (个人)]。"""
    log_lines, done = [], 0
    for src, tgt, kind, embed in plan:
        src_p, tgt_p = os.path.join(root, src), os.path.join(root, tgt)
        os.makedirs(tgt_p, exist_ok=True)
        try:
            items = sorted(os.listdir(src_p))
        except OSError:
            continue
        for it in items:
            sp = os.path.join(src_p, it)
            if os.path.isdir(sp):
                shutil.move(sp, unique_path(os.path.join(tgt_p, it)))
            else:
                np = _reorg_item_name(it, kind, embed, tgt)
                shutil.move(sp, unique_path(os.path.join(tgt_p, np)))
            log_lines.append(f"[移动] {os.path.relpath(sp, root)} -> {tgt}/{it}")
            done += 1
        try:
            os.rmdir(src_p)
            log_lines.append(f"[删除空目录] {src}")
        except OSError:
            pass
    _write_migrate_log("目录更新日志", root, log_lines, f"移动 {done} 项")
    return done


def _reorg_item_name(name, kind, embed, tgt):
    """个人归档（kind=personal 且需嵌个人名）时，把 [待定] 改写成 [社团 (个人)]；其余原样。"""
    if not (kind == "personal" and embed and os.path.splitext(name)[1].lower() in ARCHIVE_EXTS):
        return name
    base, ext = os.path.splitext(name)
    kb, _c, _pp, b = primary_bracket_info(base)
    if kb == "bare" and b == embed:
        return normalize_filename(base, ext, circle=tgt, personal=embed) or name
    return name
