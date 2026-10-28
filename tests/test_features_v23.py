# -*- coding: utf-8 -*-
"""v2.3 新端点回归测试：解散社团、全局搜索、版本派发。
（本机路径导入 /api/import-path + /api/import-commit 于 3.5.4 整体移除，其用例已删）"""
import json
import os
import sys
import zipfile

from pathlib import Path

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    circ = root / "社团V"
    circ.mkdir(parents=True)
    with zipfile.ZipFile(str(circ / "[社团V] 作品V.zip"), "w") as z:
        z.writestr("01.jpg", b"\xff\xd8 fake")
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    app.state.index_loaded = False
    app.state.index = {"v": 2, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    deleted = []
    import shutil as _sh

    def fake_delete(p):
        deleted.append(os.path.abspath(p))
        try:                                  # 模拟真实语义：文件/目录消失（现在直接删除，不再进回收站）
            if os.path.isdir(p):
                _sh.rmtree(p)
            else:
                os.remove(p)
        except OSError:
            pass
        return True

    monkeypatch.setattr(app, "_delete", fake_delete)
    yield {"root": root, "deleted": deleted, "src_zip": circ / "[社团V] 作品V.zip",
           "circ": circ}
    app.state.index_keys.clear()


def test_dissolve_circle_moves_to_uncat(lib_env):
    app.get_library(force=True)
    c = app.app.test_client()
    r = c.post("/api/dissolve-circle", json={"group": "社团V"})
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] is True and j["moved"] == 1
    assert not lib_env["src_zip"].exists()               # 原位置已空
    uncat = Path(app._inbox_dir())          # 3.6.3 解散目标 = 程序目录内的 _inbox
    assert (uncat / "[社团V] 作品V.zip").exists()         # 移入收件箱且文件名不变


def test_dissolve_circle_purges_original_dir(lib_env):
    """解散后原社团目录整棵直接删除：根目录不留空文件夹（含非作品残留）。"""
    (lib_env["circ"] / "说明.txt").write_text("readme", encoding="utf-8")
    (lib_env["circ"] / "空容器").mkdir()                  # 空的嵌套目录同样应被清掉
    app.get_library(force=True)
    c = app.app.test_client()
    j = c.post("/api/dissolve-circle", json={"group": "社团V"}).get_json()
    assert j["ok"] is True and j["dir_cleared"] is True
    assert j["message"].endswith("原目录已清除")
    assert not lib_env["circ"].exists()                   # 原目录已彻底清除
    circ_abs = os.path.abspath(str(lib_env["circ"]))
    assert circ_abs in lib_env["deleted"]                # 走的是直接删除（不可还原）
    assert (Path(app._inbox_dir()) / "[社团V] 作品V.zip").exists()


def test_dissolve_keeps_dir_when_work_stuck(lib_env, monkeypatch):
    """只要还有作品没搬出来就绝不动原目录；解锁后重试即可清除。"""
    stuck = lib_env["circ"] / "[社团V] 作品B.zip"
    with zipfile.ZipFile(str(stuck), "w") as z:
        z.writestr("01.jpg", b"\xff\xd8 fake")
    app.get_library(force=True)
    real_pir = app._path_in_root
    blocked = {"on": True}

    def fake_pir(p):
        if blocked["on"] and os.path.abspath(str(p)) == os.path.abspath(str(stuck)):
            return False                                  # 模拟该作品移动失败
        return real_pir(p)

    monkeypatch.setattr(app, "_path_in_root", fake_pir)
    c = app.app.test_client()
    j = c.post("/api/dissolve-circle", json={"group": "社团V"}).get_json()
    assert j["ok"] is False and j["failed"][0].startswith("[社团V] 作品B.zip（")   # 失败项带原因
    assert j["dir_cleared"] is False
    assert lib_env["circ"].is_dir() and stuck.exists()     # 原目录原样保留
    assert os.path.abspath(str(lib_env["circ"])) not in lib_env["deleted"]

    blocked["on"] = False                                 # 解锁后重试：作品搬出 + 目录清除
    j = c.post("/api/dissolve-circle", json={"group": "社团V"}).get_json()
    assert j["ok"] is True and j["dir_cleared"] is True
    assert not lib_env["circ"].exists()
    assert (Path(app._inbox_dir()) / "[社团V] 作品B.zip").exists()


def test_dissolve_virtual_circle_has_no_dir(lib_env):
    """根目录散包构成的虚拟社团没有目录，解散不应误删同名目录。"""
    loose = lib_env["root"] / "[社团W] 作品W.zip"
    with zipfile.ZipFile(str(loose), "w") as z:
        z.writestr("01.jpg", b"\xff\xd8 fake")
    app.get_library(force=True)
    c = app.app.test_client()
    j = c.post("/api/dissolve-circle", json={"group": "社团W"}).get_json()
    assert j["ok"] is True and j["moved"] == 1
    assert j["dir_cleared"] is False                      # 本就没有目录可清
    assert not loose.exists()
    assert (Path(app._inbox_dir()) / "[社团W] 作品W.zip").exists()
    assert lib_env["circ"].is_dir()                       # 其他社团目录毫发无损


def test_dissolve_rejects_inbox(lib_env):
    app.get_library(force=True)
    c = app.app.test_client()
    r = c.post("/api/dissolve-circle", json={"group": "收件箱"})
    assert r.status_code == 400


def test_search(lib_env):
    lib = app.get_library(force=True)
    c = app.app.test_client()
    j = c.get("/api/search?q=社团V").get_json()
    assert j["ok"] is True
    assert len(j["groups"]) == 1 and len(j["works"]) == 1
    assert j["works"][0]["group"] == "社团V"
    j = c.get("/api/search?q=").get_json()
    assert j["works"] == [] and j["groups"] == []


def test_app_version_dispatch(lib_env, monkeypatch):
    rel = lib_env["root"].parent / "releases"
    rel.mkdir(exist_ok=True)
    monkeypatch.setattr(app, "APP_RELEASES_DIR", str(rel))
    (rel / "Index-v2.3.0-4.apk").write_bytes(b"PK fake apk")
    (rel / "readme.txt").write_text("not apk")
    c = app.app.test_client()
    j = c.get("/api/app-version").get_json()
    assert j["ok"] is True
    assert j["latest"]["versionCode"] == 4
    assert j["latest"]["versionName"] == "2.3.0"
    assert j["latest"]["apkUrl"] == "/app-releases/Index-v2.3.0-4.apk"
    # 下载路由：apk 放行、非 apk 拒绝
    r = c.get("/app-releases/Index-v2.3.0-4.apk")
    assert r.status_code == 200 and r.data.startswith(b"PK")
    assert c.get("/app-releases/readme.txt").status_code == 400
    assert c.get("/app-releases/../config.json").status_code in (400, 404)


def test_config_exposes_version_axes(lib_env):
    """分轴版号：/api/config 同时给出面板号与接口级，旧字段 version 继续可用。

    APP 侧靠 panelVersion / apiLevel / minAppApi 做机器兼容判定（Api.kt 的 APP_API_LEVEL），
    所以这几个字段一旦丢失，手机端就会静默失去兼容性提示——用测试钉住。"""
    c = app.app.test_client()
    j = c.get("/api/config").get_json()
    assert j["panelVersion"] == app.PANEL_VERSION
    assert j["version"] == app.PANEL_VERSION          # 兼容旧字段
    assert j["apiLevel"] == app.SERVER_API_LEVEL
    assert j["minAppApi"] == app.MIN_APP_API
    # 面板号与 APP 号是两根独立的轴：VERSION 文件只跟面板轴走
    with open(os.path.join(PROG_DIR, "VERSION"), "r", encoding="utf-8") as f:
        assert f.read().strip() == app.PANEL_VERSION
