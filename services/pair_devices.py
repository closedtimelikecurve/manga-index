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
import logging
import os
import secrets
import time

log = logging.getLogger(__name__)

_FILE = "pair_devices.json"
PREFIX = "dev-"
_MAX_NAME = 48

# 缓存：{"path": 文件路径, "mtime": 取值, "map": {hash: deviceId}}
_cache = {"path": None, "mtime": None, "map": {}}


def _path(state_dir):
    return os.path.join(state_dir, _FILE)


def _load(state_dir):
    """读设备表。**坏文件不许静默变成空表**（3.6.168）。

    旧版这里是 `except (OSError, ValueError): return {}`——一旦文件被写坏，函数安静地
    返回空表，于是"手机令牌明明还在、服务端却一台设备都不认"：所有设备恒定 401，
    而日志里**一个字都没有**，只能靠人猜到 `_state` 里翻文件。2026-10-29 实测就是
    这个形状（`_state/pair_devices.json` 尾部多出一个 `}`，`json.load` 抛 Extra data）。

    现在分三档：读得出 → 直接用；读不出但能抢救 → 抢救 + 写回规范 JSON 自愈 + WARNING；
    抢救不出 → 空表 + ERROR（至少留下可查的痕迹）。
    """
    path = _path(state_dir)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}                            # 还没配过设备：正常，不记为异常
    except (OSError, ValueError) as exc:
        saved = _salvage(path)
        if saved is None:
            log.error("设备表损坏且无法抢救，按空表处理（所有设备令牌将失效）：%s（%s）",
                      path, exc)
            return {}
        log.warning("设备表损坏，已抢救出 %d 台设备并重写：%s（%s）", len(saved), path, exc)
        try:
            _save(state_dir, saved)          # 自愈：修好落盘，后续请求走正常路径
        except OSError:
            pass                             # 只读/占用：内存里这份仍可用于本次鉴权
        return saved


def _salvage(path):
    """从坏文件里抢救**第一个完整的 JSON 对象**（尾部多余字符、追加脏数据都能救）。

    返回 dict；救不出（截断在对象中间、根本不是 JSON）返回 None。
    `raw_decode` 只解析开头那个值、不要求吃完整串，正是为这种"前面好好的、后面多了点"
    的场景准备的。
    """
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return None
    try:
        obj, _end = json.JSONDecoder().raw_decode(raw.lstrip())
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _save(state_dir, data):
    """原子写：先写**本进程独占**的临时文件，再 `os.replace` 换上去。

    3.6.168：临时文件名带上 pid。从前固定叫 `pair_devices.json.tmp`，而 8765/8766
    是**两个进程**、`touch()` 每个设备每 5 分钟写一次盘：两边同时写同一个 tmp 时，
    先 close 的那个会把另一个**还没写完**的半截内容 rename 成正式文件——
    设备表当场损坏，所有远程设备一起 401（与 `_load` 那条一起构成这次故障的两面）。
    pid 后缀让两边各写各的，`os.replace` 本身仍是原子的。
    """
    os.makedirs(state_dir, exist_ok=True)
    path = _path(state_dir)
    tmp = "%s.%d.tmp" % (path, os.getpid())
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


def _hash_machine(machine):
    """机器码只存哈希。

    机器码是设备指纹（安卓的 `ANDROID_ID`），不是凭据，但也没必要以明文躺在 `_state` 里。
    加 `m:` 前缀是为了和 token 哈希区分：两者都走 SHA-256，虽然撞上几乎不可能，
    但"这台设备的机器码哈希"和"某个令牌的哈希"本来就该是两个命名空间。
    """
    return hashlib.sha256(("m:" + machine).encode("utf-8")).hexdigest()


def issue(state_dir, name="", now=None, machine="", known_token=""):
    """签发或**复用**一台设备的令牌。明文只在返回值里出现（新建/轮换时）。

    3.6.162 起按**机器码**识别设备，避免同一台手机反复扫码就在列表里堆出一堆记录：

    * 机器码已登记 + 带来的旧 token 对得上 → **原样返回**（不加设备、也不换 token）；
    * 机器码已登记但没有/对不上旧 token（APP 重装、清了数据）→ 复用同一个 deviceId，
      **轮换** token（旧的立刻失效）。设备数不增加，符合"不生成新设备"；
    * 机器码未登记（或调用方没给）→ 新建，行为与旧版一致。

    为什么不为了"永久复用"而存明文 token：那等于把长期凭据明文放进 state，
    文件一旦泄露所有设备一起失守。只存哈希是 3.6.144 定下的底线。
    """
    now = time.time() if now is None else now
    data = _load(state_dir)
    mh = _hash_machine(machine) if machine else ""
    if mh:
        for device_id in sorted(data):
            rec = data[device_id]
            if isinstance(rec, dict) and rec.get("m") == mh:
                return _reuse(device_id, rec, data, state_dir, name, now, known_token)
        claimed = _claim_loose(name, data, mh)
        if claimed:
            return _reuse(claimed, data[claimed], data, state_dir, name, now, known_token)
    token = PREFIX + secrets.token_hex(16)   # 4 + 32 = 36 字符
    device_id = secrets.token_hex(6)
    rec = {
        "h": _hash(token),
        "name": (name or "").strip()[:_MAX_NAME],
        "created": now,
        "last": 0,
    }
    if mh:
        rec["m"] = mh
    data[device_id] = rec
    _save(state_dir, data)
    return {"deviceId": device_id, "token": token, "name": rec["name"], "reused": False}


def _claim_loose(name, data, mh):
    """把一条「没有机器码的同名旧记录」认领为这台设备，返回它的 deviceId。

    3.6.162 之前签发的记录没有 `m` 字段。升级后第一次扫码若直接新建，用户会看到
    "同一台手机凭空多出一台"——所以名称完全一致、且**只有一条**时，把机器码补给旧记录。

    同名多条说明无法确定是哪台（可能是两台同型号手机），宁可新建也不猜——
    猜错等于把别人的令牌给了这台设备。
    """
    clean = (name or "").strip()
    if not clean:
        return None
    hits = [did for did in sorted(data)
            if isinstance(data[did], dict) and not data[did].get("m")
            and (data[did].get("name") or "").strip() == clean]
    if len(hits) != 1:
        return None
    data[hits[0]]["m"] = mh
    return hits[0]


def _reuse(device_id, rec, data, state_dir, name, now, known_token):
    """已登记设备再绑定：token 对得上就完全不动，否则只换 token、不动 deviceId。"""
    clean = (name or "").strip()[:_MAX_NAME]
    if known_token and rec.get("h") == _hash(known_token):
        rec["last"] = now
        if clean:
            rec["name"] = clean
        data[device_id] = rec
        _save(state_dir, data)
        return {"deviceId": device_id, "token": known_token,
                "name": rec.get("name") or "", "reused": True}
    token = PREFIX + secrets.token_hex(16)
    rec["h"] = _hash(token)
    rec["last"] = now
    if clean:
        rec["name"] = clean
    data[device_id] = rec
    _save(state_dir, data)
    return {"deviceId": device_id, "token": token,
            "name": rec.get("name") or "", "reused": False}


def verify(state_dir, token):
    """令牌有效 → 返回 deviceId；否则 None。"""
    if not token or not token.startswith(PREFIX):
        return None                          # 主令牌不会被误当成设备令牌
    return _hash_map(state_dir).get(_hash(token))


def list_devices(state_dir):
    """设备列表（不含哈希），最近使用在前；从未用过的排在最后。

    `bound` 表示这条记录是否绑定了机器码：面板据此区分"按机器码识别、重扫不会新增"
    与"早期按票据逐次新建"的旧记录。
    """
    data = _load(state_dir)
    out = [{"deviceId": did,
            "name": (v.get("name") or "") or "未命名设备",
            "created": float(v.get("created") or 0),
            "last": float(v.get("last") or 0),
            "bound": bool(v.get("m"))}
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
