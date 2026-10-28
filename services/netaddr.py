# -*- coding: utf-8 -*-
"""services/netaddr.py —— 真实客户端地址判定（3.6.148，安全关键）。

## 为什么需要这个模块

远程访问改由 **Tailscale serve** 终结 TLS 后，tailscaled 恒从 `127.0.0.1` 反代到
`127.0.0.1:8766`。于是 Werkzeug 看到的 `request.remote_addr` 对**任何**进入 443 的请求
都是回环——而 `app._token_gate` 正是拿"回环"当"本机免鉴权"的依据。

实测后果（未修前）：

```
curl https://<节点>.ts.net/api/library          # 不带任何令牌
→ 200，554 KB 全量库数据
```

即 tailnet 内任何设备都能读整个文库，而且这条路径**比加 HTTPS 之前更宽**：
以前直连 `http://100.x:8766` 时 `remote_addr` 是真实的 100.x（非回环）→ 要令牌；
套上 serve 之后反而全部降级成"本机"。

## 信任规则（顺序不能改）

1. `remote_addr` **不是回环** → 直接采用它，**完全无视** `X-Forwarded-For`。
   8766 仍绑 `0.0.0.0`，局域网直连者可以随手伪造 `X-Forwarded-For: 127.0.0.1` 冒充本机，
   只有"根本不看这个头"才挡得住。
2. `remote_addr` **是回环** → 请求来自本机反代（Tailscale serve / nginx），
   取 `X-Forwarded-For` 里**第一个非回环地址**当真实客户端。

第 2 条用"第一个非回环"而不是"最左"，是为了同时兼容两种代理行为：

* tailscaled **替换**该头（实测：客户端自称 `127.0.0.1` 也照样被改成真实地址）——
  只有一个值，取谁都一样；
* nginx 类代理**追加**该头（`真实客户端, 上一跳代理`）——链里出现的回环地址都是代理自身，
  跳过它们才不会把客户端误判成本机。

全部为回环时（本机浏览器经反代访问自己的面板）→ 仍判回环，免鉴权行为与直连一致。
"""
import ipaddress

# 字面量兜底：ipaddress 对部分 IPv4-mapped 写法解析结果与 Werkzeug 给的字符串不完全一致
LOOPBACK_LITERALS = frozenset(("127.0.0.1", "::1", "::ffff:127.0.0.1"))


def is_loopback(addr):
    """这个地址是不是本机回环。解析失败（空串、异常格式）一律**不当作**回环——
    宁可多要一次令牌，也不能把看不懂的东西当成本机放行。"""
    text = (addr or "").strip().rsplit("%", 1)[0]
    if not text:
        return False
    if text in LOOPBACK_LITERALS:
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def real_client(remote_addr, forwarded_for=""):
    """真实客户端地址。`forwarded_for` 传整个 `X-Forwarded-For` 头（可为空）。

    返回值只用于**判回环 / 记录来源**，不参与令牌比对。
    """
    addr = (remote_addr or "").strip().rsplit("%", 1)[0]
    if not is_loopback(addr):
        return addr                          # 直连：remote_addr 就是真相，别信转发头
    for item in str(forwarded_for or "").split(","):
        cand = item.strip().rsplit("%", 1)[0]
        if cand and not is_loopback(cand):
            return cand
    return addr


def is_local(remote_addr, forwarded_for=""):
    """这次请求是不是**真的**来自本机（本机浏览器直连，或经本机反代且客户端也是本机）。"""
    return is_loopback(real_client(remote_addr, forwarded_for))
