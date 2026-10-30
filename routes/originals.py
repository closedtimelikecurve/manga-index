# -*- coding: utf-8 -*-
"""routes/originals.py —— originals 域路由（3.6.53 Stage6 从 app.py 抽出）。

规矩：
  * **不在本模块 import app**（`python app.py` 会造成二次导入 / 双 Flask 实例）；
    一律 `h().xxx` 按名解析，保证 monkeypatch 仍然生效。
  * 端点函数保持模块级；ROUTES 与 register() 放在文件末尾。
"""
import json
import os
import subprocess
import sys
import time

from flask import g, jsonify, request, send_file, send_from_directory

import common
import djc_parse as _dp
import meta_store as meta

from common import APP_DIR, ensure_dir
from panel.http import mutating
from routes.host import h


def api_originals():
    """全部原作分区（type=original 去重，按作品数降序），附最大作品封面；
    用户设过分区封面的按覆盖显示（3.6.19，机制同画师/社团）。

    3.6.36 #34 空分区：config 词条库里**用户显式添加**但库内暂无作品的分区
    也一并展示（0 部）——「允许添加空原作区，作品通过手动添加来补齐」。
    只合并 CFG["originals"]（用户显式维护的词条库），**不合并内置名单**
    （DEFAULT_ORIGINALS 是解析器 fallback，合并会让首页冒出几十个空分区），
    **不合并已登记为别名的写法**（别名不是规范名——并入后旧写法不得以空分区复活）。"""
    originals = meta.originals_all()
    names = {z["name"] for z in originals}
    alias_names = set(meta.original_aliases())      # 别名 → 规范名 的键
    for name in (str(x).strip() for x in (h().CFG.get("originals") or [])):
        if name and name not in names and name not in alias_names:
            names.add(name)
            originals.append({"name": name, "works": 0, "latest": 0,
                              "cover_group": None, "cover_work": None,
                              "cover_mtime": 0, "cover_pages": 0})
    # 3.6.38 #37 排序：config 词条库里的位置越靠后（越晚创建）越靠前——
    # 新创建/新手动归类的分区置顶（更新原则）；不在词条库的分区（纯解析产出）
    # 排其后，再按作品数降序、同名按名字。
    cfg_index = {}
    for i, name in enumerate(str(x).strip() for x in (h().CFG.get("originals") or [])):
        if name and name not in cfg_index:
            cfg_index[name] = i
    # 3.6.42 #45：**创建次序**改为按"分区首次出现时间"（最早一部作品的入库时刻），
    # 空分区（刚手动创建、还没有作品）视为最新。此前用 config 词条库的位置：
    # 解析器产出的分区根本不在词条库里（東方Project 81 部、五等分の花嫁…），
    # cfg_index 一律 -1 → 集体沉底，而最近才加进词条的 1~2 部分区顶在最前，
    # 用户看到的就是"次序明显错乱"。
    # 次要键仍是词条库次序（多个空分区之间，越晚创建的越靠前），最后按名字稳定排序。
    _now = time.time()
    originals.sort(key=lambda z: (
        -(_now if not z.get("works") else (z.get("first_added") or 0)),
        -cfg_index.get(z["name"], -1),
        z["name"]))
    for o in originals:
        h()._apply_original_cover(o, o["name"])
    return jsonify({"ok": True, "originals": originals})


def api_originals_search():
    """「添加原作」预览：词条子串匹配命中的作品（只读，不落库）。
    3.6.20 #25：附带宽松匹配的既有分区——添加前明示"将并入该分区"，
    杜绝「输入 Fate Grand Order 被静默跳进 FateGrand Order」的困惑。"""
    term = str(request.args.get("term", "")).strip()
    if not term:
        return jsonify({"ok": False, "message": "词条为空"}), 400
    hits = meta.originals_search(term)
    nlt = h()._loose_term(term)
    similar = [{"name": z["name"], "works": z["works"]}
               for z in meta.originals_all() if nlt and h()._loose_term(z["name"]) == nlt]
    return jsonify({"ok": True, "term": term, "works": hits, "similar": similar})


def api_originals_add():
    """「添加原作」：词条 → 子串搜索命中作品 → 写 original 标签 → 新分区。
    词条同时进 config 词条库（幂等）：后续重扫/新入库作品由解析器产出同一标签，
    与手动写入殊路同归。

    **3.6.27 用户需求：创建分区不做宽松归一**——用户输入什么就建什么分区名
    （宽松归一属「文件名 → 归入分区」的归档路径）。写法相近的既有分区只在预览里
    提示（见 /api/originals/search 的 similar），不再自动并入、也不改用户输入的名字。
    若确实想并成一个分区，走「分区改名」——它会把旧写法自动登记为别名。"""
    body = request.get_json(silent=True) or {}
    term = str(body.get("term", "")).strip()
    empty = bool(body.get("empty"))      # 3.6.36 #34：仅创建空分区
    if not term:
        return jsonify({"ok": False, "message": "分区名不能为空"}), 400
    canon = term
    cur = [str(x).strip() for x in (h().CFG.get("originals") or []) if str(x).strip()]
    # existed：与既有分区**字面**同名（同名即并入）；必须在 originals_add 之前算。
    # 3.6.170：还要看词条库——**空分区**（只在 config 落名、没有作品挂标签）不在
    # `originals_all()` 里，否则重复建同名空分区会被判成"新建"，前端提示跟着说谎。
    existed = any(z["name"] == canon for z in meta.originals_all()) or canon in cur
    if canon not in cur:
        h().CFG["originals"] = cur + [canon]
        h().save_config(h().CFG)
        h()._reload_originals()
    if empty:
        # 3.6.36 #34：空分区——不搜作品、不写标签；词条库落名即持久
        # （api_originals 合并展示），作品之后经分区内「＋ 添加作品」手动补齐
        return jsonify({"ok": True, "term": term, "canon": canon, "existed": existed,
                        "hits": 0, "added": 0, "empty": True})
    hits = meta.originals_search(term)
    added = meta.originals_add(canon, [h["key"] for h in hits])
    return jsonify({"ok": True, "term": term, "canon": canon, "existed": existed,
                    "hits": len(hits), "added": added})


def api_originals_add_works():
    """分区内手动添加作品（3.6.36 #33）：把指定作品写进某原作分区的 original 标签。
    作品有明确原作、但文件名没有对应词条导致解析器识别不了时，用户在分区内
    搜索库内作品、勾选后手动挂进来。

    body: {zone: 分区名, keys: [作品key...]}
    - 分区名原样作为规范名（与「添加原作」同纪律：不归一）
    - 分区不在 config 词条库时顺带落名（重扫/新作品由解析器产出同一标签）
    - 只写标签不碰文件：作品位置/进度/收藏不受影响；写后 _lib_touch 触发重扫刷新"""
    body = request.get_json(silent=True) or {}
    zone = str(body.get("zone", "")).strip()
    keys = [str(k).strip() for k in (body.get("keys") or []) if str(k).strip()]
    if not zone:
        return jsonify({"ok": False, "message": "分区名不能为空"}), 400
    if not keys:
        return jsonify({"ok": False, "message": "未选择作品"}), 400
    _zone_ensure_registered(zone)
    # 3.6.41：前端传的 key 是「展示群组名/作品名」，而落库 key 的 group 段是归档目录名，
    # 两者不一定相等（归一后的圈子名、合作社团交叉引用）→ 直接拼 key 会写出悬空标签，
    # 表现为"返回成功、分区里没有新卡片"。这里统一解析成真实 key，解析不到就跳过。
    resolved, skipped = _resolve_zone_keys(keys)
    if not resolved:
        return jsonify({"ok": False, "zone": zone, "skipped": len(skipped),
                        "message": f"没有找到可添加的作品（{len(skipped)} 个未匹配）"}), 404
    added = meta.originals_add(zone, resolved)
    # 3.6.41：同步 force 重扫。原来只 _lib_touch()（异步），前端 onAdded 立刻刷新时
    # state.lib 还是旧缓存、_merge_manual_originals 也还没跑 → 新卡片看不到，用户以为失败。
    h().get_library(force=True)
    return jsonify({"ok": True, "zone": zone, "added": added,
                    "requested": len(keys), "skipped": len(skipped),
                    "message": _zone_added_message(added, len(resolved), len(skipped))})


def _zone_ensure_registered(zone):
    """分区不在 config 词条库时顺带落名（重扫/新作品由解析器产出同一标签）。"""
    cur = [str(x).strip() for x in (h().CFG.get("originals") or []) if str(x).strip()]
    if zone in cur:
        return
    h().CFG["originals"] = cur + [zone]
    h().save_config(h().CFG)
    h()._reload_originals()


def _resolve_zone_keys(keys):
    """展示 key（群组名/作品名）→ 落库 key；解析不到的放进 skipped。"""
    resolved, skipped = [], []
    for k in keys:
        g, _, w = k.partition("/")
        rk = meta.resolve_work_key(g, w)
        (resolved if rk else skipped).append(rk or k)
    return resolved, skipped


def _zone_added_message(added, requested_n, skipped_n):
    msg = f"已添加 {added} 部"
    if requested_n > added:
        msg += f"，{requested_n - added} 部已在本区"
    if skipped_n:
        msg += f"，{skipped_n} 部未匹配"
    return msg


def api_originals_remove():
    """移除某原作分区（3.6.19）：删库内 manual original 标签 + 词条库删词条
    （否则下次重扫解析器又把标签产出来，分区复活）。按宽松归一匹配，
    用户传规范名或任意变体均可。"""
    body = request.get_json(silent=True) or {}
    term = str(body.get("term", "")).strip()
    if not term:
        return jsonify({"ok": False, "message": "词条为空"}), 400
    nlt = h()._loose_term(term)
    removed = 0
    # 分区名 = 规范名：把宽松归一相同的全部候选名都清一遍（用户可能传变体）
    cands = {term} | {z["name"] for z in meta.originals_all() if h()._loose_term(z["name"]) == nlt}
    for cand in cands:
        removed += meta.originals_remove(cand)
        # 分区没了，它的封面覆盖记录也没意义：留着会在同名分区重建时被意外继承
        h()._region_cover_set("original", cand, "", "")
    h()._originals_config_set(drop=cands)
    return jsonify({"ok": True, "term": term, "removed": removed})


def api_originals_rename():
    """原作分区改名 / 合并（**零文件操作**：只搬 DB 标签 + config 词条库，作品零影响）。

    **3.6.27 用户需求：改名不做宽松归一**——用户输入什么，分区就叫什么（宽松归一只能
    出现在「文件名 → 归入分区」的归档路径；否则「FateGrandOrder」会被判成"写法相同"，
    用户根本改不动自己的分区名）。目标名只做**别名链折叠**，并：
    - 与既有分区**字面相同** → 真合并（不按宽松串自动并区）；
    - **仅写法不同** → 自动把旧名登记为别名，否则重扫时旧写法找不到词条，集体丢标签。

    keep_alias=true 可显式要求留别名；"仅写法不同"时自动打开。
    3.6.68/3.7.43 结构：别名决策 `_originals_alias_flags`、登记与刷新
    `_originals_alias_apply`，本函数只做编排。
    """
    body = request.get_json(silent=True) or {}
    old = str(body.get("from", "")).strip()
    new_raw = str(body.get("to", "")).strip()
    if not old:
        return jsonify({"ok": False, "message": "缺少原分区名"}), 400
    if not new_raw:
        return jsonify({"ok": False, "message": "新分区名为空"}), 400
    # 目标名只做**别名链折叠**（沿用户显式登记的原作别名折叠到规范名），不做宽松归一。
    # 3.6.27 用户需求：创建/改名分区时，用户输入什么，分区就叫什么。
    new = h()._canon_original_name(new_raw) or new_raw
    if new == old:
        return jsonify({"ok": True, "from": old, "to": new, "moved": 0,
                        "merged": False, "message": "名称未变化"})
    # 只有目标名与既有分区**字面完全相同**才算"并入"（不再按宽松串自动并区）。
    merged = any(z["name"] == new for z in meta.originals_all())
    flags = _originals_alias_flags(body, old, new)
    try:
        meta.snapshot(f"同人分区改名 {old}→{new}")     # 备份时间机器（与画师/社团改名同纪律）
    except Exception:
        h().log.exception("同人分区改名：快照失败，本次操作没有回滚点")
    moved = meta.work_tags_rename(old, new)
    _originals_alias_after_move(flags, moved, old)
    relinked = _originals_relink_aliases(old, new)
    _originals_alias_keep_for_builtin(flags, moved, old)
    _originals_alias_apply(flags, moved, old, new, relinked)
    # 分区封面交接（3.6.31 起统一走 _region_cover_migrate）：不搬的话用户刚设好的
    # 封面在改名后凭空消失；并入既有分区时以**目标分区自己的覆盖**为准（正名优先）。
    h()._region_cover_migrate("original", old, new)
    # 同步重扫：分区列表直查 DB，但「分区详情页」读的是索引里的标签（/api/works?type=original），
    # 不重扫的话刚改完名进旧分区页会看到空/旧名（3.6.21；与别名端点同手法）
    h().get_library(force=True)
    return jsonify({"ok": True, "from": old, "to": new, "moved": moved, "merged": merged,
                    "keep_alias": flags["keep"],
                    "message": _originals_rename_message(old, new, moved, merged, flags)})


def _originals_alias_apply(flags, moved, old, new, relinked):
    """词条库与别名收尾（3.7.43 从 api_originals_rename 抽出）：词条库增删 + 别名登记 + 映射刷新。

    词条库：旧名必须删（不删 → 重扫又把旧分区产出来）；新名加进去（重扫产出同名标签）。
    例外：既没搬到标签（moved=0，旧分区本来就是空的）又没要求留别名时，新名不进词条库——
    用户只是在删一个误建的空分区，不该因此多出一个词条。
    keep_alias=true 或接链改指向时：登记旧名为别名 + 重载 originals 映射，
    否则重扫时解析器按 `_norm` 精确匹配词条库会找不到旧写法。
    """
    h()._originals_config_set(drop=[old], add=[new] if (moved > 0 or flags["keep"]) else [])
    if flags["keep"]:
        try:
            meta.upsert_alias(old, new, "original")
        except Exception:
            h().log.exception("登记同人别名失败（别名未生效）")
    if flags["keep"] or relinked:
        # 显式接住返回值（与裸调用等价，_reload_originals 自带 global 副作用），
        # 让"别名已登记/改指向 → 解析映射已刷新"的依赖一目了然。
        h()._reload_originals()


def _originals_alias_flags(body, old, new):
    """别名的三个状态位：keep=是否登记旧名为别名、auto=是否因"仅写法不同"自动打开、
    requested=用户是否显式传了 keep_alias。**顺序敏感**，三步分别在改名前后推进。"""
    raw = body.get("keep_alias")
    # 3.6.41 用户需求：**旧名登记为别名设为默认**——改名后文件名里的旧写法仍会
    # 被解析器产出，不留别名就会把旧分区重新长出来（用户反复报障的根因之一）。
    flags = {"keep": True if raw is None else bool(raw), "auto": False,
             "requested": raw is not None, "moved": 0}
    if flags["keep"] or not _originals_spelling_differs(old, new):
        return flags
    # 3.6.27：仅写法不同的改名（如 FateGrandOrder → Fate Grand Order）→ 自动留别名。
    flags["keep"] = flags["auto"] = True
    return flags


def _originals_spelling_differs(old, new):
    """新旧名的宽松串是否相同（相同 = 只是写法不同，重扫会互相还原）。"""
    loose_old = h()._loose_term(old)
    return bool(loose_old) and loose_old == h()._loose_term(new)


def _originals_alias_after_move(flags, moved, old):
    """空分区改名（本质是删一个误建的空分区）：没有文件写法需要兜底，
    未显式要求时不留别名，免得凭空多出一条别名 + 词条。"""
    flags["moved"] = moved
    if not flags["requested"] and moved == 0:
        flags["keep"] = False


def _originals_relink_aliases(old, new):
    """3.6.39：old 若是**别的别名的正名**（A → old），必须把这些别名改指向 new。
    否则 A 的解析映射仍指向已消失的 old：重扫时含 A 写法的作品产回旧名标签，
    旧分区当场复活、作品也进不了改名后的分区——与"A→B→C 链只叠一层"同源。"""
    relinked = 0
    try:
        for a, c in meta.original_aliases().items():
            if c == old and a != old:
                meta.upsert_alias(a, new, "original")
                relinked += 1
    except Exception:
        h().log.exception("同人分区改名：别名改指向失败（旧写法可能仍落到旧名）")
    return relinked


def _originals_alias_keep_for_builtin(flags, moved, old):
    """3.6.28 报障修复（「分区归一后旧分区未被删除」）：旧名若仍会被解析器产出
    （config 词条库或 **djc_parse 内置名单**，后者不随词条库删除），而本次又不留别名，
    重扫会把文件名里的旧写法经内置词条重新产出，刚并走的旧分区当场复活。

    修法：这种情况下必须留别名——DB 别名叠加优先于名单（_reload_originals）。
    仅在 moved>0 时判定：moved==0 即空分区删除，重扫不会凭空长出来。
    """
    if flags["keep"] or moved <= 0:
        return
    if h().state.norm_to_canon.get(_dp._norm(old)) == old:
        flags["keep"] = True


def _originals_rename_message(old, new, moved, merged, flags):
    """回包文案（并入 / 改名 / 删空分区 + 别名说明）。"""
    if moved == 0 and not merged:
        return f"已移除空分区「{old}」（没有作品挂着该标签）"
    msg = (f"已并入：「{old}」→「{new}」，{moved} 部作品改挂新分区" if merged
           else f"已改名：「{old}」→「{new}」，{moved} 部作品跟随")
    if flags["keep"]:
        msg += (f"；「{old}」已自动登记为别名（写法差异不影响文件归区）" if flags["auto"]
                else f"；「{old}」已登记为别名（该写法不再单列分区）")
    return msg

ROUTES = [
    ('get', '/api/originals', api_originals, False),
    ('get', '/api/originals/search', api_originals_search, False),
    ('post', '/api/originals/add', api_originals_add, False),
    ('post', '/api/originals/add-works', api_originals_add_works, False),
    ('post', '/api/originals/remove', api_originals_remove, False),
    ('post', '/api/originals/rename', api_originals_rename, False),
]


def register(app):
    for method, rule, fn, is_mut in ROUTES:
        if is_mut:
            fn = mutating(fn)
        getattr(app, method)(rule)(fn)
