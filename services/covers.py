# -*- coding: utf-8 -*-
"""services/covers.py —— 区域封面覆盖（3.6.55 Stage7 从 app.py 抽出）。

机制：社团 / 画师 / 原作 三个角色各有一个桶，存 (group, work) 坐标，
渲染时按该作品首图动态取封面——首图删除自动跟随，作品删除则覆盖失效并回退派生封面。
与扫描缓存解耦、单独落盘（`_state/region_covers.json`）。
"""
import json
import os
import tempfile

from common import ensure_dir
from panel.host import h

def _valid_cov(v):
    return isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, str) for x in v)

def _region_covers_load():
    with h().REGION_COVERS_LOCK:
        if h().state.region_covers is not None:
            return
        # 三个桶必须全部解析：3.6.19 起 original 分区（原作）也能设封面，
        # 漏掉 originals 会导致 APP 端设好的分区封面在面板重启后全部丢失（表现为"设了没用"）。
        d = {bucket: {} for bucket in h()._COVER_BUCKETS.values()}
        try:
            with open(h().REGION_COVERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for bucket in h()._COVER_BUCKETS.values():
                    src = data.get(bucket)
                    if isinstance(src, dict):
                        d[bucket] = {k: v for k, v in src.items() if _valid_cov(v)}
        except Exception:
            h().log.exception("读取区域封面配置失败（自定义封面可能丢失）")
        h().state.region_covers = d

def _region_covers_save():
    with h().REGION_COVERS_LOCK:
        d = h().state.region_covers
        if d is None:
            return
        # mkstemp 必须与 os.replace 目标同目录：跨盘 replace 在 Windows 直接
        # WinError 17（save_config 踩过同一个坑）。别再硬编码 APP_DIR。
        fd, tmp = tempfile.mkstemp(prefix="region_covers_", suffix=".json",
                                   dir=ensure_dir(os.path.dirname(h().REGION_COVERS_FILE) or "."))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
            os.replace(tmp, h().REGION_COVERS_FILE)
            tmp = None
        except Exception:
            h().log.exception("写入区域封面配置失败（本次设置未保存）")
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass

def _region_cover_get(scope, name):
    """返回 (group, work) 或 None。"""
    _region_covers_load()
    with h().REGION_COVERS_LOCK:
        d = (h()._COVER_BUCKETS.get(scope) and h().state.region_covers.get(h()._COVER_BUCKETS[scope])) or {}
        v = d.get(name)
        return tuple(v) if _valid_cov(v) else None

def _region_cover_set(scope, name, group, work):
    """group/work 均非空 → 设置；否则清除该区域覆盖。"""
    _region_covers_load()
    with h().REGION_COVERS_LOCK:
        bucket = h()._COVER_BUCKETS.get(scope, "artists")
        d = h().state.region_covers.setdefault(bucket, {})
        if group and work:
            d[name] = [group, work]
        else:
            d.pop(name, None)
    _region_covers_save()

def _region_cover_migrate(scope, old, new, retarget=False, work_renames=None):
    """区域改名 / 合并时的封面交接（3.6.31）。

    - **正名优先**：目标区域若已有自己的封面覆盖，合并后就由它说了算
      （"合并后的新区，其封面继承自正名社团"）；目标没有覆盖时，才把旧区域的
      覆盖搬过去，避免用户设的封面在改名后凭空丢失。
    - **旧名记录一律清掉**：留着会在同名区域重建时被意外继承。
    - `retarget`：作品随合并搬到了新区域（社团改名/合并时作品换父目录），
      旧覆盖里的 group 已失效，坐标必须重定向到 new，否则 find_work 查不到、
      封面静默回退派生。
    - `work_renames`：作品名映射（画师改名会连文件名一起改），命中旧作品名的
      覆盖坐标随之换新名，否则同样失效。
    """
    cov = _region_cover_get(scope, old)
    _region_cover_set(scope, old, "", "")
    if not cov or old == new:
        return
    if _region_cover_get(scope, new):
        return                                  # 正名已有封面 → 继承它，旧的不抢
    g, w = cov
    if work_renames:
        w = work_renames.get(w, w)
    _region_cover_set(scope, new, (new if retarget else g), w)

def _resolve_region_cover(scope, name):
    """覆盖作品存在且有封面 → 返回 {group, work, mtime, pages}，否则 None（回退派生封面）。"""
    cov = _region_cover_get(scope, name)
    if not cov:
        return None
    g, w = cov
    wk = h().find_work(g, w)
    if not wk or not wk.get("cover"):
        return None
    return {"group": g, "work": w, "mtime": wk.get("mtime", 0.0), "pages": wk.get("pages", 0)}

def _apply_artist_cover(rec, name):
    """用画师区域封面覆盖 rec 的 cover_* 字段；无覆盖或无效应则不改动（保留派生封面）。"""
    ov = _resolve_region_cover("artist", name)
    if ov:
        rec["cover_group"] = ov["group"]
        rec["cover_work"] = ov["work"]
        rec["cover_mtime"] = ov["mtime"]
        rec["cover_pages"] = ov["pages"]
    return rec

def _apply_original_cover(rec, name):
    """3.6.19：原作分区封面覆盖（与画师同机制：按 (group, work) 存，跟随首图/作品删除）。"""
    ov = _resolve_region_cover("original", name)
    if ov:
        rec["cover_group"] = ov["group"]
        rec["cover_work"] = ov["work"]
        rec["cover_mtime"] = ov["mtime"]
        rec["cover_pages"] = ov["pages"]
    return rec
