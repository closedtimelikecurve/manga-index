# -*- coding: utf-8 -*-
"""services/manage.py —— 删除 / 改名 / 合并归档（3.6.58 Stage7 从 app.py 抽出）。

为什么连组内互调也走 `h()`：测试大量 `monkeypatch.setattr(app, "_delete", ...)`
（`test_delete_api` / `test_features_v23`）；组内直呼模块函数会绕过桩、真删文件。
"""
import os
import shutil
import sys
import time

import djc_parse as _dp
import meta_store as meta

from panel.host import h

def _delete(path):
    """直接删除文件/目录（不再经由系统回收站，不可还原）。
    被占用（WinError 32/33 级瞬态冲突）时先排空在读线程再重试 3 次。"""
    for i in range(3):
        h()._archive_quiesce([path])   # 关缓存句柄 + 等在读线程排空（比单次 forget 更彻底）
        if h()._delete_once(path):
            return True
        if i < 2:
            time.sleep(0.4 * (i + 1))
    return False

def _delete_once(path):
    """执行一次直接删除（文件 os.unlink，目录 shutil.rmtree）。"""
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.unlink(path)
        return True
    except Exception:
        return False

def _invalidate_after_delete(path):
    """删除后失效与该路径相关的各层缓存（索引/压缩包句柄/页面与封面缓存随重扫重建）。"""
    p = os.path.abspath(path)
    with h()._archive_lock:
        for k in [k for k in h()._archive_handles if k.lower() == p.lower()]:
            h()._archive_handles.pop(k, None)
    h()._lib_touch()        # 下次请求触发重扫（增量索引下很快）

def _path_in_root(path):
    """路径必须位于文库根内且不等于根本身。"""
    root_real = os.path.realpath(h().CFG.get("root", ""))
    p_real = os.path.realpath(str(path))
    return p_real.lower().startswith(root_real.lower() + os.sep)

def _path_same_or_under(path, dir_path):
    """path 是否等于 dir_path 或位于其内部（真路径比较，大小写不敏感）。"""
    d = os.path.realpath(str(dir_path)).lower().rstrip("\\/")
    p = os.path.realpath(str(path)).lower().rstrip("\\/")
    return p == d or p.startswith(d + os.sep)

def _purge_circle_dir(dir_path):
    """解散社团后清除原目录：整棵目录树直接删除（不可还原），
    不留空文件夹；目录内未搬走的残留文件（非作品）一并直接删除。
    返回 True 表示原目录已不存在（已清除或本来就没有）。"""
    try:
        if not os.path.isdir(dir_path):
            return True
        h()._archive_forget_tree(dir_path)
        return bool(h()._delete(dir_path))
    except Exception:
        return False

def _split_work_name(w):
    if w["kind"] == "archive":
        return os.path.splitext(os.path.basename(w["path"]))
    return os.path.basename(w["path"]), ""

def _work_group_name(w):
    """作品当前所属社团名（取自最近一次扫描缓存；找不到返回 ""）。
    3.0 元数据 key 迁移的基准：改名/归档落位后据此把 DB 里的 key 一并迁移。"""
    try:
        p = os.path.abspath(str(w.get("path") or ""))
        for g in h().get_library()["groups"]:
            for x in g["works"]:
                if os.path.abspath(str(x.get("path") or "")) == p:
                    return g["name"]
    except Exception:
        h().log.exception("解析作品归属社团失败")
    return ""

def _resolve_archive_term(parsed, full_name, current):
    """判定「这部作品该归入哪个档案夹」——`_apply_rename` 的决策核心（3.6.45 拆出）。

    原先这段判断连同改名/移动/落库混在同一个 120 行函数里（圈复杂度 46），
    但它其实是**独立的一条业务规则**：文件名解析结果 → 档案目录词条。

    返回 (parsed, term, dissolved_hit)：
      * term 非空 = 归档到该词条的档案夹；空 = 留在收件箱；
      * dissolved_hit = 命中的已解散社团名（仅用于给用户一句准确的提示）。
    优先级（顺序即语义，改动前先看 MEMORY「寻址」章）：
      ① 文件名的社团名；
      ② 主词条不可用（无/黑名单/已解散）时做**词条救援**：从后续括号里找词条库已收录的
         个人名，命中则按该个人名归档；
      ③ 裸 [词条] → 以词条本身建个人档（2026-09-25 起不再反查社团名）；
      ④ 黑名单/已解散 → 降级，作品留在收件箱（文件名里的括号原样保留）。

    3.6.71 结构：学习 / 救援 / 降级各成函数（cc 20→5）。
    """
    _learn_personals(parsed)
    term = parsed["circle"] or ""
    if _needs_rescue(term, parsed):
        parsed = _rescue_bare_term(parsed, full_name, current)
    if not term and parsed["bare"]:
        # 裸 [词条] 作品：按词条本身建个人目录（2026-09-25 作废"自动补社团名"——
        # 不再反查词条库把待定词条改写为 [社团 (个人)] 并归入该社团）。
        # 陌生词条照常学习（个人名→个人目录），供增补信息预填与后续归档参考。
        term = parsed["bare"]
        h()._known_learn(parsed["bare"], parsed["bare"])
    if not term:
        term = parsed["bare"] or ""
    term, dissolved_hit = _degrade_term(term)
    return parsed, term, dissolved_hit


def _learn_personals(parsed):
    """合作作品逐位学习（每人都进词条库）。"""
    for a in (parsed.get("personals") or ([parsed["personal"]] if parsed["personal"] else [])):
        h()._known_learn(parsed["circle"], a)


def _needs_rescue(term, parsed):
    """主词条不可用（无 / 黑名单 / 已解散）时才做词条救援。"""
    if term:
        return False
    bare = parsed["bare"]
    return not bare or h()._term_blacklisted(bare) or bare in h()._dissolved_circles()


def _rescue_bare_term(parsed, full_name, current):
    """从后续括号里找词条库已收录的个人名，命中则按该个人名归档。
    例：…【無邪気漢化組】 [玉砂糖] → 銀糖製菓 (玉砂糖)。"""
    rescued = h()._rescue_personal(full_name if full_name != current else current)
    if rescued and rescued != parsed["bare"]:
        return dict(parsed, bare=rescued, personals=[rescued])
    return parsed


def _degrade_term(term):
    """黑名单 / 已解散词条降级 → (term, dissolved_hit)；降级后 term 为空（作品留在收件箱）。"""
    if term and h()._term_blacklisted(term):
        # 词条黑名单（含"重嵌"/"Digital"等）：不作为社团名，作品留未分类
        return "", ""
    if term and term in h()._dissolved_circles():
        # 已解散的社团：词条降级不再作社团，作品留在未分类；
        # 文件名里的括号与已有其他词条原样保留（不会互相顶替）
        return "", term
    return term, ""

def _apply_rename(w, new_full_name, group_hint=""):
    """重命名作品文件/文件夹，并按解析出的社团（或待定词条）自动建档归档。
    无词条（无社团也无待定词条）的作品保留原位（未分类）。
    group_hint：调用方已知的作品当前社团名（批量调用传入可避免逐部回扫定位）。

    3.6.71 结构：改名 `_rename_in_place`、归档 `_archive_into`、DB key 迁移 `_meta_moved`
    （cc 25→6）。**顺序即语义**：先原地改名，再搬档案夹，key 跟着最终落点走。
    """
    h()._archive_quiesce([w.get("path", "")])   # 关缓存句柄 + 等在读线程排空（WinError 32 防御）
    old_group = group_hint or h()._work_group_name(w)
    try:
        h().meta.snapshot("改名/归档前")         # 备份时间机器：结构变更前快照（60s 节流）
    except Exception:
        h().log.exception("批量改名：快照失败，本次操作没有回滚点")

    new_full_name = _sanitize_full_name(new_full_name)
    parent = os.path.dirname(w["path"])
    current = os.path.basename(w["path"])
    parsed = h().parse_filename(new_full_name if new_full_name != current else current,
                                h().state.originals, h().state.norm_to_canon)
    parsed, term, dissolved_hit = h()._resolve_archive_term(parsed, new_full_name, current)

    dest_dir = None
    if term:
        dest_name = h()._existing_archive_dir(h()._coop_primary(term))
        dest_dir = os.path.abspath(os.path.join(h().CFG.get("root", ""), dest_name))
        if dest_dir == os.path.abspath(parent) and new_full_name == current:
            return True, "文件名无需修改（已在对应档案夹内）"
    if not term and new_full_name == current:
        if dissolved_hit:
            return True, f"社团「{dissolved_hit}」已解散，词条降级保留在收件箱"
        return True, "文件名无需修改"

    dst, err = _rename_in_place(w["path"], new_full_name, current, parent)
    if err:
        return False, err
    filed, early = _archive_into(dst, dest_dir, parent, old_group, w["name"])
    if early is not None:
        return early
    h()._lib_touch()
    if filed:
        return True, f"已规范化并归档到社团「{filed}」"
    if term:
        return True, f"已规范化（作品位于社团「{term}」内）"
    if dissolved_hit:
        return True, f"已规范化（社团「{dissolved_hit}」已解散，保留在收件箱）"
    return True, "已规范化（未识别出社团，保留在收件箱）"


def _sanitize_full_name(new_full_name):
    """Windows 非法字符兜底清洗（保留扩展名）。"""
    base, ext = os.path.splitext(new_full_name)
    safe = h()._dp.sanitize_windows_name(base)
    return (safe + ext) if safe else new_full_name


def _rename_in_place(path, new_full_name, current, parent):
    """原名没变就不动；否则在**同目录**内改成新名。返回 (dst, 错误文案)。"""
    if new_full_name == current:
        return path, ""
    try:
        dst = h().unique_path(os.path.join(parent, new_full_name))
        ok, err = h()._rename_with_retry(path, dst)
        if not ok:
            return None, "重命名失败：" + err
        return dst, ""
    except Exception as e:
        return None, "重命名失败：" + str(e)


def _archive_into(dst, dest_dir, parent, old_group, wname):
    """把已改好名的作品搬进目标档案夹。返回 (filed, 提前返回的结果|None)。

    重复守卫：目标里已有同名同大小作品（部分成功/重复下载所致）→ 直接删掉手上这份，
    **绝不造 "(2)" 第二份**。
    """
    if not dest_dir or os.path.abspath(dest_dir) == os.path.abspath(parent):
        _meta_moved(old_group, wname, dst)      # 仅改名未挪目录（或目标即当前目录）
        return "", None
    try:
        os.makedirs(dest_dir, exist_ok=True)
        pre = os.path.join(dest_dir, os.path.basename(dst))
        if _same_size_file(pre, dst):
            h()._archive_quiesce([dst])
            if h()._delete(dst):
                h()._lib_touch()
                return "", (True, "已存在相同作品，已清理收件箱重复项"
                                  f"（社团「{os.path.basename(dest_dir)}」）")
        final = h().unique_path(pre)
        ok, err = h()._rename_with_retry(dst, final)
        if not ok:
            _meta_moved(old_group, wname, dst)  # 原地改名成功、归档移动失败：key 仍要跟着走
            h()._lib_touch()
            return "", (True, f"已规范化，但归档移动失败：{err}")
        _meta_moved(old_group, wname, final)
        return os.path.basename(dest_dir), None
    except Exception as e:
        _meta_moved(old_group, wname, dst)
        h()._lib_touch()
        return "", (True, f"已规范化，但归档移动失败：{e}")


def _same_size_file(pre, dst):
    """目标里已有同名同大小的非空文件（判重复用）。"""
    if not os.path.exists(pre):
        return False
    size = h()._path_size(dst)
    return size > 0 and h()._path_size(pre) == size


def _meta_moved(old_group, wname, new_path):
    """3.0：落位成功后把元数据库里的 key（含阅读/评分/收藏关联）迁到新 key。
    根目录散包（虚拟社团）key 由解析决定，留给下轮扫描对账，这里跳过。"""
    try:
        if not old_group:
            return
        d = os.path.dirname(os.path.abspath(new_path))
        if d == os.path.abspath(h().CFG.get("root", "")):
            return
        ng = os.path.basename(d)
        if ng:
            h().meta.rename_work_key(old_group + "/" + wname,
                                     ng + "/" + os.path.splitext(os.path.basename(new_path))[0])
    except Exception:
        h().log.exception("迁移作品元数据失败（阅读进度/评分可能错位）")

def _merge_circle_into(g, gname, new_name, src, dst):
    """社团合并：目标社团已存在时，把源社团全部作品逐部搬进去（文件名不变、绝不覆盖），
    源目录搬空后整棵删除；元数据库的作品 key / 画师→社团映射随之迁到目标社团。

    与「解散」的区别：解散是把作品丢进「未分类」，合并是并入另一个已有社团（两社合一），
    作品本身的存储结构与文件名一概不动，只是换了一层父目录。

    3.6.71 结构：搬作品 `_move_circle_works`、搬残留 `_move_circle_leftovers`、
    清源目录 `_merge_cleanup_dir`（cc 24→6）。
    """
    moved, failed = _move_circle_works(g["works"], dst)
    if moved == 0 and failed:
        return h().jsonify({"ok": False,
                        "message": "没有作品可合并（" + (failed[0][:80] if failed else "目录可能被占用") + "）"}), 500
    for w in g["works"]:                      # 失效旧路径的句柄/页面缓存
        h()._invalidate_after_delete(w["path"])
    # 非作品的残留条目（如同目录下的说明文件）也一并搬走，才好把空目录连根摘掉
    leftovers = _move_circle_leftovers(src, dst)
    dir_cleared, dir_note = _merge_cleanup_dir(src, failed)
    try:
        h().meta.merge_circles(gname, new_name)   # 元数据库：档案与映射迁到目标社团
    except Exception:
        h().log.exception("合并社团元数据失败")
    # 3.6.31：作品已搬进目标目录 → 旧社团名下的封面坐标失效，重定向到正名社团。
    # 目标社团自己设过封面时保留那份（"合并后的新区，其封面继承自正名社团"）。
    h()._region_cover_migrate("circle", gname, new_name, retarget=True)
    h()._lib_touch()
    cleaned = h()._clean_empty_dirs()
    msg = f"已合并：「{gname}」→「{new_name}」（目标社团已存在，{moved} 部作品并入"
    if leftovers:
        msg += f"，另有 {leftovers} 个残留条目一并搬入"
    msg += "）"
    if dir_cleared:
        msg += "，源目录已清除"
    if failed:
        msg += f"，{len(failed)} 部移动失败"
    if cleaned:
        msg += f"，自动清理 {len(cleaned)} 个空文件夹"
    msg += dir_note
    return h().jsonify({"ok": not failed and not dir_note, "merged": True, "moved": moved,
                    "failed": failed, "cleaned_dirs": len(cleaned), "message": msg})


def _move_circle_works(works, dst):
    """把源社团的作品逐个搬进目标社团（重名让位、绝不覆盖）。返回 (moved, failed)。"""
    moved, failed = 0, []
    for w in works:
        p = w["path"]
        if not h()._path_in_root(p) or not os.path.exists(p):
            failed.append(os.path.basename(p) + "（文件不存在）")
            continue
        h()._archive_quiesce([p])      # 关缓存句柄 + 等在读线程排空（WinError 32 防御）
        try:
            base = os.path.basename(p if w["kind"] == "archive" else p.rstrip("\\/"))
            dest = h().unique_path(os.path.join(dst, base))
            ok, err = h()._move_with_retry(p, dest)
            if not ok:
                failed.append(os.path.basename(p) + "（" + err[:60] + "）")
                continue
            moved += 1
        except Exception as e:
            failed.append(os.path.basename(p) + "（" + str(e)[:60] + "）")
    return moved, failed


def _move_circle_leftovers(src, dst):
    """把源目录里非作品的残留条目也搬进目标社团，好让空目录能被连根删掉。"""
    leftovers = 0
    try:
        for nm in sorted(os.listdir(src)):
            sp = os.path.join(src, nm)
            if not h()._path_in_root(sp):
                continue
            try:
                h()._archive_quiesce([sp])
                h()._move_with_retry(sp, h().unique_path(os.path.join(dst, nm)))
                leftovers += 1
            except Exception:
                h().log.exception("移动社团残留文件失败（源目录可能无法清除）")
    except OSError:
        pass
    return leftovers


def _merge_cleanup_dir(src, failed):
    """源目录处理：仍有作品没搬走就保留；否则整棵清除。返回 (是否已清除, 附注文案)。"""
    if not h()._path_in_root(src):
        return False, "；源目录不在文库根内，已跳过清除"
    if failed:
        return False, "；源目录保留（仍有作品未搬出）"
    if not h()._purge_circle_dir(src):
        return False, "；源目录清除失败（可能被占用），请手动删除"
    h()._invalidate_after_delete(src)
    return True, ""

def _clean_empty_dirs():
    """清扫文库内空文件夹（无任何文件的目录链自底向上逐层删除）；
    返回删除的相对路径列表。供解散/删除社团后自动调用。"""
    root = os.path.abspath(h().CFG.get("root", ""))
    if not os.path.isdir(root):
        return []
    protect = {root, os.path.join(h().APP_DIR, "_inbox")}
    dirs_all = []
    for dirpath, dirnames, _f in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in h().IGNORE_DIRS and not d.startswith(".")]
        for d in dirnames:
            dirs_all.append(os.path.join(dirpath, d))
    dirs_all.sort(key=lambda x: x.count(os.sep), reverse=True)
    removed = []
    for x in dirs_all:
        ax = os.path.abspath(x)
        if ax in protect or os.path.islink(ax):
            continue
        try:
            if not os.listdir(ax):
                os.rmdir(ax)
                removed.append(ax)
        except OSError:
            pass
    return [os.path.relpath(x, root) for x in removed]
