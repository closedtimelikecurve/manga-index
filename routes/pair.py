# -*- coding: utf-8 -*-
"""routes/pair.py —— 扫码配对（3.7.77 建；3.6.144 改为一次性票据）。

## 三个端点

| 端点 | 作用 | 鉴权 |
|---|---|---|
| `GET /api/pair/info` | 探测手机可达地址，返回 `canPair / url / reason / ticketTtl …` | 需令牌（本机回环免） |
| `GET /api/pair/qr` | 签发一张票据并编码成 SVG，返回 `{ok, svg, expiresIn, url}` | 需令牌 |
| `POST /api/pair/claim` | **用票据换设备令牌**；票据一次性作废 | **不需要令牌**（票据就是凭据） |

## 为什么改（3.6.144）

原先二维码里编的是 `config.json` 的**长期主令牌**：拍一张照 = 永久拿到整个文库的读写权，
而且没有过期、没法吊销（`docs/pair-security-2026-10-27.md` 的 R1/R2/R5）。

现在二维码里只放**票据**（`{"i": 地址, "p": 票据}`）：

* 默认 120 秒过期（`pair_ticket_ttl` 可调，夹在 30~600）；
* `claim` 消费一次即作废，重放返回 `used`；
* APP 拿到的是**设备专属令牌**（`dev-` 开头），服务端只存哈希，可单台吊销。

`/api/pair/claim` 必须放进 `PUBLIC_ENDPOINTS`：新手机还没有任何令牌，否则永远调不通。
它的安全性由票据本身保证（128 bit 随机 + 120 秒 + 一次性）。

**不再返回主令牌**：`/api/pair/info` 原先把 token 一起吐出来，现在删掉了——网页端的
令牌来自 `localStorage` 的 `djc_token`（用户手填或 URL 带入），不依赖这个字段。

规矩与其它 routes 一致：不 import app，一律 common 按名解析。"""
import io
import json

from flask import jsonify, request

import common
from services import netaddr
from services import pair_devices
from services import pair_target
from services import pair_tickets
from services import server_identity

def _state_dir():
    """票据与设备表的根目录。

    **运行时读 `common.STATE_DIR`**，不缓存成模块常量：鉴权中间件（`app._token_gate`）
    也读同一个值，两者必须指向同一目录，否则"claim 写到 A、鉴权查 B"，设备令牌永远过不了。
    测试只改 `common.STATE_DIR` 一处即可同时隔离两边。"""
    return common.STATE_DIR


def _port():
    """二维码里的端口：当前页面端口只是候选之一，最终由 pair_target 探测决定。"""
    tail = (request.host or "").rsplit(":", 1)[-1]
    if tail.isdigit():
        return int(tail)
    cfg = common.CFG.get("port")
    return int(cfg) if isinstance(cfg, int) and cfg > 0 else 8766


def _from_local_proxy():
    """请求是不是由**本机**反代转进来的（Tailscale serve / nginx 都符合）。

    只采信回环来源的 `X-Forwarded-Proto`：8766 仍绑 0.0.0.0，同网段任何人都能塞这个头，
    若无条件信任，直连者可让页面显示成"已加密"——这不是权限问题（该头只影响文案与
    二维码地址），但属于**谎报安全状态**，比明文更糟。

    注意这里用的是 `remote_addr` 本身（判"谁连的我"），不是 `netaddr.real_client`
    （判"最终用户是谁"）——代理链的入口地址才是决定"该不该信转发头"的依据。"""
    return netaddr.is_loopback(request.remote_addr)


def _scheme():
    """外部真实协议（3.6.148）。

    直连：看 `request.is_secure`（wsgi.url_scheme）。
    反代：看 `X-Forwarded-Proto`，仅当代理连接来自回环（见 `_from_local_proxy`）。
    没装 ProxyFix 是**故意的**——那会把 X-Forwarded-* 的信任范围扩大到整个 Flask app，
    而本项目只有配对地址这一处需要外部协议。"""
    proto = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
    if proto in ("http", "https") and _from_local_proxy():
        return proto
    return "https" if request.is_secure else "http"


def _target():
    # 本地实例 8765 只绑回环，编进二维码手机连不上，所以端口要真探测（config.port → 8766 → 页面端口）。
    return pair_target.detect(_port(), request.host or "",
                              str(common.CFG.get("pair_url") or ""),
                              cfg_port=common.CFG.get("port"),
                              scheme=_scheme())


def _ttl():
    """票据有效期：配置可调，非法值回落默认 120 秒。"""
    return pair_tickets.clamp_ttl(common.CFG.get("pair_ticket_ttl"))


def _client_ip():
    """票据/设备记录里的来源 IP。**用真实客户端**（反代后面 remote_addr 恒是 127.0.0.1，
    照记会让所有配对记录都变成"来自本机"，出事时无从追溯）。"""
    return netaddr.real_client(request.remote_addr,
                               request.headers.get("X-Forwarded-For"))


def _link(target):
    """当前链路怎么加密的（前端要据此给不同级别的提示）。

    判定顺序（3.6.148 起）：**先看二维码里那个地址本身**，再看隧道，最后才看请求——
    因为手机真正要连的是 `target["url"]`，前端警告必须针对它而不是当前这个页面。
    典型场景：本机 8765 页面（http 明文、回环免鉴权）打开配对，而 `pair_url` 给的是
    `https://…ts.net`——此处若按 `request.is_secure` 判，会误报"明文"。

    * `tunnel:*` —— 走隧道的 IP:端口，链路由 WireGuard / 加密 VPN 保护；
    * `https` —— TLS（公共 CA 如 Tailscale serve，或反代/自签）；
    * `http` —— **明文**，同网段可截获令牌，前端必须警告。
    """
    if str(target.get("url") or "").startswith("https://"):
        return "https"
    src = str(target.get("source") or "")
    if src.startswith("tunnel:"):
        return src
    return "https" if _scheme() == "https" else "http"


def api_pair_info():
    target = _target()
    return jsonify({
        "ok": True,
        "url": target["url"],
        # 3.6.144：**不再返回 token** —— 二维码里放一次性票据，长期凭据只在 claim 时签发一次
        "canPair": target["ok"],
        "reason": target["reason"],
        "source": target["source"],
        "tunnels": target["tunnels"],
        "candidates": target["candidates"],
        "ports": target.get("ports") or [],
        "ticketTtl": _ttl(),
        # 主令牌现在是可选的（只用扫码配对也能跑）；前端据此决定按钮是"生成"还是"轮换"
        "hasMainToken": bool(str(common.CFG.get("token") or "").strip()),
        # 3.6.146：服务器身份指纹（给人核对）+ 链路加密级别（前端据此警告明文）
        # 3.6.148：secure 改判"二维码地址是否 TLS"，与 link 同源——反代后面才准
        "fingerprint": server_identity.fingerprint(_state_dir()),
        "secure": str(target.get("url") or "").startswith("https://"),
        "link": _link(target),          # 复用上面已算好的探测结果，别再跑一次 TCP 探测
        # 兼容旧前端：loopback 仍然表示"当前页面地址是本机回环"
        "loopback": pair_target.is_loopback_host(request.host or ""),
    })


def api_pair_qr():
    """签发票据 + 生成 SVG。返回 JSON（前端要用 expiresIn 做倒计时与过期态）。"""
    target = _target()
    if not target["ok"]:
        return jsonify({"ok": False, "reason": target["reason"],
                        "message": "没有手机可达的远程地址，未生成二维码"}), 409
    ticket = pair_tickets.issue(_state_dir(), ttl=_ttl(), ip=_client_ip())
    payload = json.dumps({"i": target["url"], "p": ticket["ticket"]}, separators=(",", ":"))
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        return jsonify({"ok": False,
                        "message": "服务器未安装 qrcode 库（pip install qrcode）"}), 500
    img = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage,
                      box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return jsonify({"ok": True, "svg": buf.getvalue().decode("utf-8"),
                    "expiresIn": ticket["expiresIn"], "url": target["url"]})


def api_pair_claim():
    """票据换设备令牌。**一次性**：同一个票据第二次一定失败。"""
    body = request.get_json(silent=True) or {}
    ticket = str(body.get("p") or body.get("ticket") or "").strip()
    name = str(body.get("n") or body.get("name") or "").strip()
    status, _rec = pair_tickets.claim(_state_dir(), ticket, ip=_client_ip())
    if status == "expired":
        return jsonify({"ok": False, "reason": "expired",
                        "message": "二维码已过期，请在电脑上点刷新重新生成"}), 410
    if status == "used":
        return jsonify({"ok": False, "reason": "used",
                        "message": "该二维码已被使用，请重新生成"}), 409
    if status != "ok":
        return jsonify({"ok": False, "reason": "unknown",
                        "message": "无效的二维码"}), 400
    dev = pair_devices.issue(_state_dir(), name=name)
    return jsonify({"ok": True, "token": dev["token"], "deviceId": dev["deviceId"],
                    "deviceName": dev["name"],
                    # 服务器身份 secret：APP 存下来，以后用它验证"还是这台机器"（见 attest）
                    "sk": server_identity.secret(_state_dir())})


def api_pair_attest():
    """挑战-响应：APP 发随机 nonce，服务器证明"我还是上次那台"。

    为什么是**公开端点**：APP 在 claim 之前调用它，此时还没有任何令牌。
    它不泄露 secret——返回的是 `HMAC(secret, nonce)`，nonce 一次性，无法反推密钥，
    也无法用于下一次挑战（攻击者拿旧 proof 过不了新 nonce）。
    """
    body = request.get_json(silent=True) or {}
    nonce = str(body.get("n") or body.get("nonce") or "").strip()
    if not 8 <= len(nonce) <= 128:
        return jsonify({"ok": False, "reason": "bad_nonce",
                        "message": "nonce 不合法"}), 400
    return jsonify({"ok": True,
                    "proof": server_identity.attest(_state_dir(), nonce),
                    "fingerprint": server_identity.fingerprint(_state_dir())})


def api_pair_devices():
    """已配对设备列表（3.6.145）。只回名称/时间，**不含令牌哈希**。"""
    return jsonify({"ok": True, "devices": pair_devices.list_devices(_state_dir())})


def api_pair_device_revoke(device_id):
    """吊销一台设备：它下次请求立刻 401，**其它设备与网页不受影响**。

    这条是"设备令牌"相对"单一主令牌"的核心收益——旧手机丢了只踢那一台。
    """
    if not pair_devices.revoke(_state_dir(), str(device_id or "")):
        return jsonify({"ok": False, "message": "设备不存在或已被吊销"}), 404
    return jsonify({"ok": True})


ROUTES = [
    ('get', '/api/pair/info', api_pair_info, False),
    ('get', '/api/pair/qr', api_pair_qr, False),
    ('post', '/api/pair/claim', api_pair_claim, False),
    ('post', '/api/pair/attest', api_pair_attest, False),
    ('get', '/api/pair/devices', api_pair_devices, False),
    ('delete', '/api/pair/devices/<device_id>', api_pair_device_revoke, True),
]


def register(app):
    for method, rule, fn, is_mut in ROUTES:
        getattr(app, method)(rule)(fn)
