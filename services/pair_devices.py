# -*- coding: utf-8 -*-
"""services/pair_devices.py —— 配对后的长期设备令牌（3.6.144）。

扫码换来的不是主令牌，而是一台设备专属的令牌（`dev-` + 32 位十六进制）。
理由：一次性票据只能用一次，APP 之后每次连接都需要一个**长期**凭据；
同时希望"哪台设备泄露就吊销哪台"，而不是只能改 `config.json` 的主令牌、把所有设备一起踢掉。

## 存储

`_state/pair_devices.json`：`{deviceId: {"h": sha256(token), "name", "created", "last"}}`
**只存哈希，不存明文明文**——文件被看到也拿不到可用令牌（明文只在签发那一刻返回一次）。

## 校验与缓存

`verify()` 每次请求都会调用，所以不能每次读盘：按文件 `mtime` 做一层内存缓存，
文件没变就直接用内存里的哈希表。双实例各自缓存，`mtime` 变化会自然失效。

## 与主令牌的关系

主令牌仍然有效（网页本机回环本来就免鉴权，远程网页用主令牌）。设备令牌是**并列**的
第二种凭据，见 `app.py:_token_gate`：主令牌匹配 或 任一设备令牌匹配 即放行。

纯函数、无 Flask；目录由调用方传入。
"""
import hashlib
import json
import os
import secrets
import time

_FILE = "pair_devices.json"
PREFIX = "dev-"
_MAX_NAME = 48

# 缓存：{"path": 文件路径, "mtime": 取值, "map": {hash: deviceId}}
_cache = {"path": None, "mtime": None, "map": {}}


def _path(state_dir):
    return os.path.join(state_dir, _FILE)


def _load(state_dir):
    try:
        with open(_path(state_dir), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(state_dir, data):
    os.makedirs(state_dir, exist_ok=True)
    path = _path(state_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    _cache["mtime"] = None                   # 自己写的，让缓存失效


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hash_map(state_dir):
    """{hash: deviceId}，按 mtime 缓存（每个请求都会走到这里）。"""
    path = _path(state_dir)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = -1.0
    if _cache["path"] == path and _cache["mtime"] == mtime:
        return _cache["map"]
    data = _load(state_dir)
    mapping = {v.get("h"): did for did, v in data.items() if isinstance(v, dict) and v.get("h")}
    _cache.update({"path": path, "mtime": mtime, "map": mapping})
    return mapping


def issue(state_dir, name="", now=None):
    """签发一台设备的令牌。**明文只在返回值里出现一次**，落盘的只有哈希。"""
    now = time.time() if now is None else now
    token = PREFIX + secrets.token_hex(16)   # 4 + 32 = 36 字符
    device_id = secrets.token_hex(6)
    data = _load(state_dir)
    data[device_id] = {
        "h": _hash(token),
        "name": (name or "").strip()[:_MAX_NAME],
        "created": now,
        "last": 0,
    }
    _save(state_dir, data)
    return {"deviceId": device_id, "token": token, "name": data[device_id]["name"]}


def verify(state_dir, token):
    """令牌有效 → 返回 deviceId；否则 None。"""
    if not token or not token.startswith(PREFIX):
        return None                          # 主令牌不会被误当成设备令牌
    return _hash_map(state_dir).get(_hash(token))


def list_devices(state_dir):
    """设备列表（不含哈希），最近使用在前；从未用过的排在最后。"""
    data = _load(state_dir)
    out = [{"deviceId": did,
            "name": (v.get("name") or "") or "未命名设备",
            "created": float(v.get("created") or 0),
            "last": float(v.get("last") or 0)}
           for did, v in data.items() if isinstance(v, dict)]
    out.sort(key=lambda it: (it["last"] or it["created"]), reverse=True)
    return out


def revoke(state_dir, device_id):
    """吊销一台设备。返回是否真的删掉了。"""
    data = _load(state_dir)
    if device_id not in data:
        return False
    data.pop(device_id, None)
    _save(state_dir, data)
    return True


def touch(state_dir, device_id, now=None):
    """记录"最近使用时间"，按 5 分钟节流——否则每个请求都写盘。"""
    now = time.time() if now is None else now
    data = _load(state_dir)
    rec = data.get(device_id)
    if not isinstance(rec, dict):
        return
    if now - float(rec.get("last") or 0) < 300:
        return
    rec["last"] = now
    data[device_id] = rec
    try:
        _save(state_dir, data)
    except OSError:
        return                            # 只读环境/短暂占用：不影响鉴权
