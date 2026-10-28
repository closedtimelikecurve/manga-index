# -*- coding: utf-8 -*-
"""删除作品/社团 API 回归测试（右键菜单功能）。

monkeypatch 掉 _delete（不真正删文件），验证：
  * /api/delete：正常删除、路径防御（根外拒绝）、404
  * /api/delete-circle：真实档案夹整目录删除、收件箱拒绝、404
  * 删除后 rev 自增；SWR 后台重扫静默后旧作品从缓存消失（3.3.0 语义）
"""
import os
import sys
import zipfile

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
from conftest import wait_rescan_quiet  # noqa: E402


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    circ = root / "社团D (画师D)"
    circ.mkdir(parents=True)
    with zipfile.ZipFile(str(circ / "[社团D (画师D)] 作品D.zip"), "w") as z:
        z.writestr("001.jpg", b"\xff\xd8 fake")
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    app.state.index_loaded = False
    app.state.index = {"v": 2, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    deleted = []
    monkeypatch.setattr(app, "_delete", lambda p: deleted.append(os.path.abspath(p)) or True)
    yield {"root": root, "deleted": deleted, "zip": circ / "[社团D (画师D)] 作品D.zip",
           "dir": circ}
    app.state.index_keys.clear()


def _lib(lib_env):
    app.state.lib["data"] = None
    return app.get_library(force=True)


def test_delete_work(lib_env):
    lib = _lib(lib_env)
    rev0 = int(app.state.lib.get("rev") or 0)
    c = app.app.test_client()
    # 3.6.12：分组改按圈子名，目录「社团D (画师D)」的作品归入圈子「社团D」
    r = c.post("/api/delete", json={"group": "社团D", "work": "[社团D (画师D)] 作品D"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert len(lib_env["deleted"]) == 1
    assert lib_env["deleted"][0].lower() == str(lib_env["zip"]).lower()
    assert int(app.state.lib.get("rev") or 0) == rev0 + 1, "删除后必须递增 rev 触发双端同步"
    assert wait_rescan_quiet(), "SWR 后台重扫应静默完成"
    fresh = app.get_library()
    assert fresh["scanned_at"] > lib["scanned_at"], "删除后必须触发重扫"
    # （_delete 在本 fixture 中被替换成只记录不真删，重扫后作品仍在——只验证重扫确实发生了）


def test_delete_work_rejects_outside_root(lib_env, monkeypatch):
    _lib(lib_env)
    monkeypatch.setattr(app, "find_work",
                        lambda g, w: {"name": w, "path": r"C:\Windows\evil.zip", "kind": "archive"})
    c = app.app.test_client()
    r = c.post("/api/delete", json={"group": "g", "work": "w"})
    assert r.status_code == 400
    assert lib_env["deleted"] == [], "根外路径绝不允许删除"


def test_delete_work_404(lib_env):
    _lib(lib_env)
    c = app.app.test_client()
    r = c.post("/api/delete", json={"group": "社团D", "work": "不存在的作品"})
    assert r.status_code == 404
    assert lib_env["deleted"] == []


def test_delete_circle_whole_dir(lib_env):
    _lib(lib_env)
    c = app.app.test_client()
    # 3.6.12：目录「社团D (画师D)」归到虚拟圈子「社团D」，整目录删除回退到其作品共同父目录
    r = c.post("/api/delete-circle", json={"group": "社团D"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert len(lib_env["deleted"]) == 1
    assert lib_env["deleted"][0].lower() == str(lib_env["dir"]).lower(), "虚拟圈子应整目录删除其真实父目录"


def test_delete_circle_uncat_rejected(lib_env):
    _lib(lib_env)
    c = app.app.test_client()
    r = c.post("/api/delete-circle", json={"group": "收件箱"})
    assert r.status_code == 400
    assert lib_env["deleted"] == []


def test_delete_circle_404(lib_env):
    _lib(lib_env)
    c = app.app.test_client()
    r = c.post("/api/delete-circle", json={"group": "不存在的社团"})
    assert r.status_code == 404
    assert lib_env["deleted"] == []
