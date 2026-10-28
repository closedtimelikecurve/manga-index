# -*- coding: utf-8 -*-
"""服务器身份与挑战-响应（3.6.146）。

守住本次的**核心承诺**：假服务器答不出正确的 proof，所以"配对过一次之后再被换成
另一台机器"会被拦下。

同时守住这些**不能**发生的事：
* `secret` 不能出现在 info / fingerprint 里（它是密钥材料，不是展示值）；
* fingerprint 只是给人核对的短串，**不能**当成认证依据（假服务器照抄就行）；
* nonce 必须真的参与运算（否则重放有效）。
"""
import os

import services.server_identity as si


def test_secret_is_stable_and_created_once(tmp_path):
    d = str(tmp_path)
    first = si.secret(d)
    assert len(first) == 64 and all(c in "0123456789abcdef" for c in first)
    assert si.secret(d) == first, "第二次调用又生成了一次（APP 存的 secret 会失效）"
    assert os.path.exists(os.path.join(d, "server_identity.json"))


def test_secret_differs_between_installations(tmp_path):
    a = si.secret(str(tmp_path / "a"))
    b = si.secret(str(tmp_path / "b"))
    assert a != b, "不同服务器得到同一个 secret（会互相冒充）"


def test_fingerprint_format_and_no_leak(tmp_path):
    d = str(tmp_path)
    fp = si.fingerprint(d)
    parts = fp.split("-")
    assert len(parts) == 4 and all(len(p) == 4 for p in parts), fp
    assert all(c in "0123456789ABCDEF" for p in parts for c in p)
    secret = si.secret(d)
    assert secret not in fp and secret[:8] not in fp.replace("-", ""), "指纹里带出了 secret"


def test_attest_depends_on_nonce(tmp_path):
    d = str(tmp_path)
    p1 = si.attest(d, "nonce-aaaa")
    p2 = si.attest(d, "nonce-bbbb")
    assert p1 != p2, "proof 与 nonce 无关（可重放）"
    assert p1 == si.attest(d, "nonce-aaaa"), "同一 nonce 必须得到同一 proof"
    assert si.verify(d, "nonce-aaaa", p1) is True
    assert si.verify(d, "nonce-bbbb", p1) is False, "旧 proof 能过新 nonce（重放有效）"


def test_wrong_secret_cannot_forge_proof(tmp_path):
    """模拟假服务器：它有自己的 secret，算不出真服务器的 proof。"""
    real = str(tmp_path / "real")
    fake = str(tmp_path / "fake")
    nonce = "3f2a1c9b8e7d6a5f"
    real_proof = si.attest(real, nonce)
    fake_proof = si.attest(fake, nonce)
    assert real_proof != fake_proof
    assert si.verify(real, nonce, fake_proof) is False, "假服务器的 proof 骗过了真服务器校验"
