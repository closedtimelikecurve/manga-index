# -*- coding: utf-8 -*-
"""API 层回归测试：扫描进度非阻塞响应、token 闸门、/api/open 路径防御。"""
import os
import sys

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")     # 隔离真实 config.json 的 token
    app.state.index_loaded = False
    app.state.index = {"v": 1, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    yield root
    app.state.index_keys.clear()


def test_api_library_scanning_progress(lib_env):
    client = app.app.test_client()
    with app.SCAN_LOCK:                       # 模拟后台扫描进行中
        app.state.lib["data"] = None
        app.state.scan_state.update(running=True, done=3, total=10)
        r = client.get("/api/library")
        assert r.status_code == 200
        j = r.get_json()
        assert j["status"] == "scanning"
        assert j["done"] == 3 and j["total"] == 10
        assert "groups" not in j              # 不携带数据，避免前端误渲染
    # 锁释放后恢复正常数据响应（fixture 空库，扫描瞬时完成）
    app.state.scan_state.update(running=False)   # 3.3.0：快速路径改看 SCAN_STATE，模拟状态需复位
    j2 = client.get("/api/library").get_json()
    assert j2.get("ok") is True and "groups" in j2


def test_token_gate(lib_env, monkeypatch):
    monkeypatch.setitem(app.CFG, "token", "bks-unittest-token")
    client = app.app.test_client()
    LOCAL = {"REMOTE_ADDR": "127.0.0.1"}
    REMOTE = {"REMOTE_ADDR": "100.64.0.99"}   # 模拟 Tailscale/局域网远程设备
    # 本机回环访问一律免门禁（token 只为远程访问设防）
    assert client.get("/api/library", environ_base=LOCAL).status_code == 200
    # 远程无令牌/错令牌 → 401；正确令牌（query 或头）→ 200
    assert client.get("/api/library", environ_base=REMOTE).status_code == 401
    assert client.get("/api/library?token=wrong", environ_base=REMOTE).status_code == 401
    assert client.get("/api/library?token=bks-unittest-token",
                      environ_base=REMOTE).status_code == 200
    assert client.get("/api/library", headers={"X-Token": "bks-unittest-token"},
                      environ_base=REMOTE).status_code == 200
    # 页面壳无需 token（PUBLIC_ENDPOINTS）
    assert client.get("/").status_code == 200


def test_api_open_rejects_outside_root(lib_env, monkeypatch):
    monkeypatch.setitem(app.CFG, "token", "")
    inside = str(lib_env / "some.zip")
    monkeypatch.setattr(app, "find_work",
                        lambda g, w: {"name": w, "path": r"C:\Windows\system32\evil.exe",
                                      "kind": "archive"})
    client = app.app.test_client()
    r = client.post("/api/open", json={"group": "g", "work": "w", "target": "folder"})
    assert r.status_code == 400, "文库根之外的路径必须被拒绝"
    monkeypatch.setattr(app, "find_work",
                        lambda g, w: {"name": w, "path": inside, "kind": "archive"})
    r2 = client.post("/api/open", json={"group": "g", "work": "w", "target": "folder"})
    assert r2.status_code == 200              # 根内路径放行（目标不存在 → ok:false，不弹窗）
    assert r2.get_json()["ok"] is False
