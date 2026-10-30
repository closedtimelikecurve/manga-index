# -*- coding: utf-8 -*-
"""services/server_identity.py —— 服务器身份与挑战-响应（3.6.146）。

## 它解决什么

`docs/pair-security-2026-10-27.md` 的 R3：**二维码可被伪造**——攻击者造一张
`{"i":"http://他的服务器","p":"x"}` 让用户扫，APP 就老老实实连过去。

## 为什么不是"比对指纹字符串"

最直觉的做法是让 APP 记住服务器指纹、下次比对。**但那不成立**：指纹只是
`/api/pair/info` 里的一个字符串，假服务器照抄一遍就能骗过比对。真正要拦下的，
是"这台机器到底是不是上次那台"，必须有**只有真服务器才回答得出的东西**。

所以这里用对称挑战-响应：

1. 服务器在 `_state/server_identity.json` 生成一次 32 字节 `secret`（此后不变）；
2. APP 首次配对（claim）时把 `secret` 交给它，存在手机上；
3. 以后每次配对前，APP 发随机 `nonce` → `POST /api/pair/attest` → 服务器回
   `HMAC-SHA256(secret, nonce)`；APP 用记住的 `secret` 验证；
4. 假服务器不知道 `secret`，答不出正确证明 → 被拦。

**局限（必须承认）**：首次配对时 APP 手里没有 secret，无法判断对面真假——这是所有
TOFU 方案的固有边界。本模块防的是"**配对过一次之后**被换成另一台服务器"，
不防"第一次就扫到假码"。

## 与"主令牌/设备令牌"的关系

`secret` 不是访问凭据，**不能用来读数据**，它只用于证明身份。泄露它的后果是"攻击者能
冒充这台服务器的身份去骗已配对的 APP"，因此它随 claim 一起下发（此时设备令牌也已经
下发，危害同级），且**不会**出现在二维码、info、日志里。

纯函数、无 Flask；目录由调用方传入。
"""
import hashlib
import hmac
import json
import os
import secrets
import time

_FILE = "server_identity.json"


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
    """原子写（3.6.168：临时名带 pid，双实例各写各的，详见 `pair_devices._save`）。"""
    os.makedirs(state_dir, exist_ok=True)
    path = _path(state_dir)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def secret(state_dir):
    """取（必要时生成）服务器 secret。**只在 claim 下发时用**，别回显到任何 GET 接口。"""
    data = _load(state_dir)
    got = data.get("secret")
    if isinstance(got, str) and len(got) >= 32:
        return got
    got = secrets.token_hex(32)               # 64 位十六进制 = 256 bit
    _save(state_dir, {"secret": got, "created": time.time()})
    return got


def fingerprint(state_dir):
    """给人核对的短指纹：`sha256(secret)` 前 16 位按 4 位分组。

    它**只是显示用**（让用户能一眼看出"还是那台机器"），真正的认证是 [attest]。
    注意别把它当成认证凭据——字符串谁都能照着写一份。
    """
    raw = hashlib.sha256(secret(state_dir).encode("utf-8")).hexdigest()[:16].upper()
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def attest(state_dir, nonce):
    """挑战-响应：`HMAC-SHA256(secret, nonce)`。

    nonce 由调用方（APP）生成、一次性使用；服务端不保存 nonce——重放的价值为零，
    因为攻击者拿到旧证明也没法用于新 nonce。
    """
    key = secret(state_dir).encode("utf-8")
    msg = str(nonce or "").encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def verify(state_dir, nonce, proof):
    """服务端侧自检用（测试里用得多）：比对常量时间。"""
    return hmac.compare_digest(attest(state_dir, nonce), str(proof or "").lower())
