# -*- coding: utf-8 -*-
"""services/pair_tickets.py —— 一次性配对票据（3.6.144）。

## 为什么要有这一层

二维码里原先直接编**长期主令牌**（`config.json` 的 `token`）：拍一张照就等于永久拿到
整个文库的读写权，而且没有过期、没法吊销（`docs/pair-security-2026-10-27.md` 的 R1/R2）。

现在二维码里只放**票据**，它有三个性质：

* **短时效**：默认 120 秒（`config.json` 的 `pair_ticket_ttl` 可调，夹在 30~600）；
* **一次性**：被 `claim` 消费后立即作废，重放返回 `used`；
* **不含任何长期凭据**：APP 拿票据去换**设备令牌**（`pair_devices`），那才是长期凭据。

## 为什么要落盘（不能只存内存）

本项目**双实例运行**：本地 `8765` 只绑 `127.0.0.1`、远程 `8766` 绑 `0.0.0.0`。
从 `127.0.0.1:8765` 页面生成的码，会被手机拿去 `8766` 验证——票据只存进程内存的话
必然验不过。所以票据落 `_state/pair_tickets.json`，两个实例读同一份。

## 「一次性」怎么做到跨进程原子

不靠读改写（两个进程同时 claim 会双通过），而是用一个**独占创建的标记文件**：
`_state/pair_used/<ticket>.lock` 用 `O_CREAT | O_EXCL` 打开，谁先成功谁独占，
另一个进程必然拿到 `FileExistsError` → `used`。这在 Windows 与 POSIX 上都是原子的。

## 来源 IP

只**记录**不**校验**：网页在电脑上生成票据（源 IP 是电脑），APP 用票据时源 IP 是手机，
两者本来就不同——拿它做绑定校验会让配对必然失败。它只用于事后审计。

纯函数、无 Flask；目录由调用方传入（与 `services/theme_store.py` 同规矩）。
"""
import json
import os
import secrets
import time

# 票据默认有效期（秒）。首次扫码要「开相机 → 授权 → 对准」，60 秒偏紧。
DEFAULT_TTL = 120
MIN_TTL = 30
MAX_TTL = 600

_STORE = "pair_tickets.json"
_USED_DIR = "pair_used"
# 表的最多保留条数：纯防御，正常使用每条 120 秒就过期，purge 会清掉。
_MAX_ENTRIES = 200


def clamp_ttl(raw, default=DEFAULT_TTL):
    """把配置里的 ttl 夹进合理区间；非法值一律回默认。"""
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default
    return v if MIN_TTL <= v <= MAX_TTL else default


def _store_path(state_dir):
    return os.path.join(state_dir, _STORE)


def _load(state_dir):
    try:
        with open(_store_path(state_dir), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(state_dir, data):
    """原子写：先写 .tmp 再 os.replace，避免另一个实例读到半个文件。"""
    os.makedirs(state_dir, exist_ok=True)
    path = _store_path(state_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def purge(state_dir, now=None):
    """清掉过期票据与过期标记文件；返回清掉的票据条数。"""
    now = time.time() if now is None else now
    data = _load(state_dir)
    keep = {k: v for k, v in data.items() if float(v.get("exp", 0)) > now}
    removed = len(data) - len(keep)
    if removed:
        _save(state_dir, keep)
    used_dir = os.path.join(state_dir, _USED_DIR)
    if os.path.isdir(used_dir):
        for name in os.listdir(used_dir):
            path = os.path.join(used_dir, name)
            try:
                if os.path.getmtime(path) < now - MAX_TTL * 2:
                    os.remove(path)
            except OSError:
                continue                      # 另一个进程刚删掉，忽略
    return removed


def issue(state_dir, ttl=DEFAULT_TTL, ip="", now=None):
    """签发一张新票据。返回 {ticket, expiresIn, expiresAt}。"""
    now = time.time() if now is None else now
    ttl = clamp_ttl(ttl)
    purge(state_dir, now)
    data = _load(state_dir)
    if len(data) >= _MAX_ENTRIES:            # 兜底：表满了先丢最旧的
        for key in sorted(data, key=lambda k: float(data[k].get("exp", 0)))[:
                len(data) - _MAX_ENTRIES + 1]:
            data.pop(key, None)
    ticket = secrets.token_hex(16)            # 32 位十六进制，128 bit 随机
    data[ticket] = {"exp": now + ttl, "created": now, "ip": ip or ""}
    _save(state_dir, data)
    return {"ticket": ticket, "expiresIn": ttl, "expiresAt": now + ttl}


def _take_marker(state_dir, ticket):
    """独占创建标记文件；成功返回 True（本次是第一个消费者）。"""
    used_dir = os.path.join(state_dir, _USED_DIR)
    os.makedirs(used_dir, exist_ok=True)
    path = os.path.join(used_dir, ticket + ".lock")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except (FileExistsError, OSError):
        return False
    os.close(fd)
    return True


def _has_marker(state_dir, ticket):
    return os.path.exists(os.path.join(state_dir, _USED_DIR, ticket + ".lock"))


def claim(state_dir, ticket, ip="", now=None):
    """消费票据。返回 (status, record)。

    status：`ok` / `expired` / `used` / `unknown`
    **成功即作废**——同一个票据第二次调用一定拿 `used`，无论是否在有效期内。
    """
    now = time.time() if now is None else now
    if not ticket:
        return "unknown", {}
    data = _load(state_dir)
    rec = data.get(ticket)
    if not rec:
        # 表里没有：已用过（标记文件还在）或从来不存在
        return ("used" if _has_marker(state_dir, ticket) else "unknown"), {}
    if float(rec.get("exp", 0)) <= now:
        return "expired", rec
    if not _take_marker(state_dir, ticket):
        return "used", rec
    rec = dict(rec)
    rec["claimed"] = now
    rec["claimIp"] = ip or ""
    data[ticket] = rec
    _save(state_dir, data)
    return "ok", rec
