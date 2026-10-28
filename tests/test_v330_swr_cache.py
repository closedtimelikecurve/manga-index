# -*- coding: utf-8 -*-
"""3.3.0 新行为回归测试：

  * /page、/cover 字节响应（压缩包抽页）带 ETag，If-None-Match 命中 → 304
    （此前 BytesIO 响应无协商缓存，max-age 过期后整页重传）
  * SWR（stale-while-revalidate）：写操作后旧缓存继续服务 + rev 自增 + 后台重扫静默后数据更新
  * 变更型端点清单 _MUTATING_ENDPOINTS 与 _lib_touch 调用图一致（防新增写端点漏注册竞态门）
"""
import ast
import io
import os
import sys
import zipfile
from urllib.parse import quote

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
from conftest import wait_rescan_quiet  # noqa: E402


def _real_jpeg_bytes():
    if not app.PIL_OK:
        return b"\xff\xd8 fake"
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 20, 30)).save(buf, "JPEG", quality=85)
    return buf.getvalue()


@pytest.fixture()
def zip_lib(tmp_path, monkeypatch):
    """一个社团一部 zip 作品（2 页）。"""
    root = tmp_path / "lib"
    root.mkdir()
    circ = root / "社团Z"
    circ.mkdir()
    zp = circ / "作品Z.zip"
    with zipfile.ZipFile(str(zp), "w") as z:
        z.writestr("001.jpg", _real_jpeg_bytes())
        z.writestr("002.jpg", _real_jpeg_bytes())
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    app.state.index_loaded = False
    app.state.index = {"v": 3, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    with app.COVER_LOCK:
        app.cover_cache.clear()
        app._cover_cache_bytes[0] = 0
    yield {"root": root, "zip": zp, "circ": circ}
    app.state.index_keys.clear()


def test_page_bytes_response_etag_304(zip_lib):
    app.get_library(force=True)
    c = app.app.test_client()
    q = "/page?group=" + quote("社团Z") + "&work=" + quote("作品Z") + "&n=0"
    r1 = c.get(q)
    assert r1.status_code == 200
    etag = r1.headers.get("ETag")
    assert etag, "压缩包抽页的字节响应必须带 ETag"
    r2 = c.get(q, headers={"If-None-Match": etag})
    assert r2.status_code == 304, "If-None-Match 命中必须返回 304"
    # 内容变了（重扫出新 ver）→ ETag 失效，回 200 全量
    r3 = c.get(q, headers={"If-None-Match": '"bogus-0-0"'})
    assert r3.status_code == 200


def test_cover_bytes_response_etag_304(zip_lib):
    app.get_library(force=True)
    c = app.app.test_client()
    q = "/cover?group=" + quote("社团Z") + "&work=" + quote("作品Z")
    r1 = c.get(q)
    assert r1.status_code == 200
    etag = r1.headers.get("ETag")
    assert etag, "封面字节响应必须带 ETag"
    r2 = c.get(q, headers={"If-None-Match": etag})
    assert r2.status_code == 304


def test_swr_stale_serves_and_refreshes(zip_lib):
    """删除作品后：rev 自增、读请求立即（stale）响应、重扫静默后 scanned_at 前移。"""
    lib0 = app.get_library(force=True)
    rev0 = int(app.state.lib.get("rev") or 0)
    c = app.app.test_client()
    r = c.post("/api/delete", json={"group": "社团Z", "work": "作品Z"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert int(app.state.lib.get("rev") or 0) == rev0 + 1
    # stale 窗口内读接口立即响应（不再同步扛整轮扫描）
    r2 = c.get("/api/library/meta")
    assert r2.status_code == 200 and int(r2.get_json()["rev"]) == rev0 + 1
    # 后台重扫静默后数据确实刷新（fixture 的 _delete 真删文件）
    assert wait_rescan_quiet()
    fresh = app.get_library()
    assert fresh["scanned_at"] > lib0["scanned_at"]
    assert all(g["name"] != "社团Z" for g in fresh["groups"])


def _scan_endpoints_and_funcs():
    """收集 app.py + routes/*.py 的顶层函数与端点名（端点两个来源：装饰器 / ROUTES 表）。"""
    files = [os.path.join(PROG_DIR, "app.py")]
    # 3.6.58：业务 helper 已下沉 services/，调用图必须一起扫；panel/ 是资源层
    for sub in ("routes", "services", "panel"):
        d = os.path.join(PROG_DIR, sub)
        files += [os.path.join(d, n) for n in sorted(os.listdir(d))
                  if n.endswith(".py") and n != "__init__.py"]
    funcs, endpoints = {}, set()
    for path in files:
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs[node.name] = node
                for dec in node.decorator_list:
                    if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                            and dec.func.attr in ("route", "get", "post", "put", "delete")):
                        endpoints.add(node.name)
            elif (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "ROUTES"
                    and isinstance(node.value, ast.List)):
                for elt in node.value.elts:
                    if isinstance(elt, ast.Tuple) and len(elt.elts) >= 3:
                        fn = elt.elts[2]
                        if isinstance(fn, ast.Name):
                            endpoints.add(fn.id)
    return funcs, endpoints


def _touched_by_lib_touch(funcs):
    """调用图闭包：哪些函数（直接或间接）调用了 _lib_touch。`h().foo()` 也算调用 foo。"""
    def called_name(call):
        f = call.func
        if isinstance(f, ast.Name):
            return f.id
        return f.attr if isinstance(f, ast.Attribute) else None

    def calls(fn, names):
        return any(isinstance(n, ast.Call) and called_name(n) in names for n in ast.walk(fn))

    touched = {n for n, f in funcs.items() if calls(f, {"_lib_touch"})}
    for _ in range(10):
        grew = False
        for name, fn in funcs.items():
            if name not in touched and calls(fn, touched):
                touched.add(name)
                grew = True
        if not grew:
            break
    return touched


def test_mutation_gate_covers_all_lib_touch_endpoints():
    """凡（直接或间接）调用 _lib_touch 的路由端点必须登记进 _MUTATING_ENDPOINTS，
    否则其文件操作会与后台重扫并发（扫描器句柄 → WinError 32）。

    3.6.54 起扫描范围含 `routes/*.py`，识别 `ROUTES` 注册表与 `h().xxx()` 调用。
    **不要把范围缩回 app.py**，否则搬出去的路由会失去这道保护。
    """
    funcs, endpoints = _scan_endpoints_and_funcs()
    hit = endpoints & _touched_by_lib_touch(funcs)
    missing = hit - app._MUTATING_ENDPOINTS
    stale = app._MUTATING_ENDPOINTS - hit
    assert not missing, "这些端点调用了 _lib_touch 但未进 _MUTATING_ENDPOINTS：%s" % sorted(missing)
    assert not stale, "这些端点已不再调用 _lib_touch，应从清单移除：%s" % sorted(stale)
