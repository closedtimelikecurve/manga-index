# -*- coding: utf-8 -*-
"""APP 端服务器身份校验（3.6.146）。

这一档真正要防的是"**配对过一次之后**被换成另一台机器"（DNS 劫持、码被替换）。
守三件事：

1. **顺序**：必须先验身份再 claim。反过来就等于"先把设备令牌交给假服务器，再问它是谁"。
2. **方法**：认证靠 HMAC 挑战-响应，不是比对指纹字符串——字符串假服务器照抄就行。
3. **出路**：换服务器后 attest 必然对不上，必须有"清除身份校验"的入口，否则把自己锁死。

首次配对无法判断真假（TOFU 的固有边界），代码里明确放行，不算缺陷。
"""
import os
import re

PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KT_DIR = os.path.join(PROG_DIR, "android", "app", "src", "main", "java", "com", "biblioteca", "reader")


def _kt_code(name):
    with open(os.path.join(KT_DIR, name + ".kt"), encoding="utf-8") as f:
        src = f.read()
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)//[^\n]*$", "", src)


def test_identity_is_verified_before_claim():
    """顺序错了就毫无意义：先把令牌交出去，再问对面是谁。"""
    body = _kt_code("QrConnect")
    entry = body.split("fun finish(target: PairTarget)")[1].split("fun handle")[0]
    assert "exchangeTicket(ctx, target)" in entry, "扫码后没有走「验身份 → claim」的交换流程"
    ex = body.split("fun exchangeTicket")[1].split("fun claimDeviceToken")[0]
    assert "verifyServerIdentity" in ex, "claim 前没有校验服务器身份"
    assert ex.index("verifyServerIdentity") < ex.index("claimDeviceToken"), \
        "先 claim 后验身份（令牌已经交给对面了）"
    assert 'saveServerIdentity(ctx, target.url, body.optString("sk"))' in ex, \
        "claim 成功后没有把服务器 secret 存下来（下次没法验证）"


def test_identity_uses_hmac_challenge_not_string_compare():
    """指纹字符串可以照抄，只有 HMAC(secret, nonce) 是假服务器算不出来的。"""
    ident = _kt_code("PairIdentity")
    assert "HmacSHA256" in ident, "没有用 HMAC"
    assert "hmacSha256Hex" in ident and "pairAttest" in ident, "没有向服务器发起挑战"
    assert "UUID.randomUUID" in ident, "nonce 不是随机的（可被重放）"
    assert "fingerprint" not in ident, "又在比对指纹字符串（可伪造）"


def test_identity_is_recorded_per_server():
    """同一台手机可能连过多台服务器，secret 不能混用。"""
    ident = _kt_code("PairIdentity")
    assert "pair_sk_" in ident and "u.host" in ident, "没有按 host:port 分键"


def test_settings_can_clear_identity():
    """换服务器后 attest 必然对不上，没有清除入口会把自己锁在外面。"""
    main = _kt_code("MainActivity")
    assert "ClearIdentityRow(url)" in main, "设置页没有清除身份校验的入口"
    assert "clearServerIdentity" in main and "hasServerIdentity" in main
    ident = _kt_code("PairIdentity")
    assert "fun clearServerIdentity" in ident and "fun hasServerIdentity" in ident


def test_first_pairing_is_allowed_without_identity():
    """首次配对没有可比的 secret，必须放行（否则新手机永远绑不上）。"""
    ident = _kt_code("PairIdentity")
    assert 'if (known.isEmpty()) return null' in ident, "首次配对被拦住了"
