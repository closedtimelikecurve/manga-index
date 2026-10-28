# -*- coding: utf-8 -*-
"""压缩包读取优化与封面内存优化的回归测试（P2-2 / P2-3）。

覆盖：
  * page_source：zip 页解压后进入页面字节 LRU，二次请求不再触碰压缩包
  * 源文件 mtime 变化 → 页面缓存键失效，重新解压
  * cover_payload：静图 → bytes 缩略图进内存 LRU；动图（压缩包源）→ 首次写
    _anim 磁盘缓存、后续直接发磁盘文件，原图字节不进内存 LRU
  * 动图（文件源）→ 直接发原文件路径
  * 内存 LRU 字节预算逐出
"""
import io
import os
import sys
import zipfile

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
import panel.archive as _archive  # noqa: E402  压缩包页缓存/句柄已抽至 panel/archive.py

PIL_OK = app.PIL_OK


def _real_jpeg_bytes():
    if not PIL_OK:
        return b"\xff\xd8 fake"
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 20, 30)).save(buf, "JPEG", quality=85)
    return buf.getvalue()


@pytest.fixture()
def zip_lib(tmp_path, monkeypatch):
    """一个社团一部 zip 作品（3 页）+ 一个文件夹作品。"""
    root = tmp_path / "lib"
    root.mkdir()
    circ = root / "社团Z"
    circ.mkdir()
    zp = circ / "作品Z.zip"
    with zipfile.ZipFile(str(zp), "w") as z:
        z.writestr("001.jpg", _real_jpeg_bytes())
        z.writestr("002.jpg", _real_jpeg_bytes())
        z.writestr("003.jpg", _real_jpeg_bytes())
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    app.state.index_loaded = False
    app.state.index = {"v": 1, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app._page_cache.clear()
    app._page_cache_bytes[0] = 0
    with app.COVER_LOCK:
        app.cover_cache.clear()
        app._cover_cache_bytes[0] = 0
    yield {"root": root, "zip": zp, "work": None}
    app.state.index_keys.clear()


def _zip_work(zip_lib):
    lib = app.get_library(force=True)
    for g in lib["groups"]:
        for w in g["works"]:
            if w["kind"] == "archive":
                return w
    raise AssertionError("fixture 库中应有 zip 作品")


def test_page_cache_hit_avoids_reopen(zip_lib, monkeypatch):
    w = _zip_work(zip_lib)
    k1, p1, m1 = app.page_source(w, 0)
    assert k1 == "bytes" and m1 == "image/jpeg" and p1
    # 第二次请求命中页面缓存：底层压缩包读取函数被调用即失败
    # （_archive_read 已抽到 panel/archive.py，打桩须打到真正调用它的模块）
    monkeypatch.setattr(_archive, "_archive_read",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("应命中页面缓存")))
    k2, p2, m2 = app.page_source(w, 0)
    assert (k2, p2, m2) == (k1, p1, m1)


def test_page_cache_invalidated_by_mtime(zip_lib):
    w = _zip_work(zip_lib)
    k1, p1, _ = app.page_source(w, 1)
    assert k1 == "bytes"
    st = os.stat(str(zip_lib["zip"]))
    # 显式推后 mtime：os.utime(path, None) 会受 Windows 文件时间戳 tick（约 15.6ms）粒度影响，
    # "刚建完就设成现在"可能不变，导致这条用例其实没测到失效路径
    os.utime(str(zip_lib["zip"]), (st.st_atime, st.st_mtime + 10))
    monkey_none = None
    k2, p2, _ = app.page_source(w, 1)
    assert k2 == "bytes" and p2 == p1        # 重新解压，内容一致


def test_page_cache_bytes_budget(zip_lib):
    w = _zip_work(zip_lib)
    _archive.PAGE_CACHE_MAX_BYTES  # 常量存在性
    old = _archive.PAGE_CACHE_MAX_BYTES
    try:
        # PAGE_CACHE_MAX_BYTES 已抽到 panel/archive.py：打桩须打到真正读取它的模块
        _archive.PAGE_CACHE_MAX_BYTES = 1         # 强制逐出
        for i in range(3):
            app.page_source(w, i)
        with app._page_cache_lock:
            assert len(app._page_cache) <= 1, "字节预算必须触发逐出"
    finally:
        _archive.PAGE_CACHE_MAX_BYTES = old


def _animated_gif_bytes():
    from PIL import Image
    buf = io.BytesIO()
    f1 = Image.new("RGB", (64, 64), (255, 0, 0))
    f2 = Image.new("RGB", (64, 64), (0, 255, 0))
    f1.save(buf, "GIF", save_all=True, append_images=[f2], duration=100, loop=0)
    return buf.getvalue()


@pytest.mark.skipif(not PIL_OK, reason="需要 pillow")
def test_animated_cover_zip_source_goes_disk(zip_lib):
    """压缩包源动图：首次请求写 _anim 磁盘缓存并直接发文件；不进内存 LRU。"""
    gif = _animated_gif_bytes()
    w = _zip_work(zip_lib)
    # 给 zip 追加一页动图：重建 zip（mtime 变化自动失效缓存键）
    zp = zip_lib["zip"]
    with zipfile.ZipFile(str(zp), "w") as z:
        z.writestr("001.gif", gif)
        z.writestr("002.jpg", b"\xff\xd8 fake")
    app._page_cache.clear()
    w = _zip_work(zip_lib)
    w["cover"] = ("zip", str(zp), "001.gif")   # 强制把封面指向动图页
    k1, p1, m1 = app.cover_payload(w)
    assert k1 == "file" and m1 == "image/gif", "压缩包源动图应通过 _anim 磁盘文件直出"
    assert os.path.exists(p1) and os.path.dirname(os.path.abspath(p1)) == os.path.abspath(app.THUMB_DIR)
    with app.COVER_LOCK:
        assert all(len(v[0]) < len(gif) for v in app.cover_cache.values()), \
            "动图原图字节不得进入内存 LRU"
    # 二次请求仍稳定返回磁盘文件（缓存命中路径）
    k2, p2, m2 = app.cover_payload(w)
    assert k2 == "file" and p2 == p1


@pytest.mark.skipif(not PIL_OK, reason="需要 pillow")
def test_animated_cover_file_source_serves_original(tmp_path, monkeypatch):
    root = tmp_path / "lib2"
    fd = root / "社团F" / "作品F"
    fd.mkdir(parents=True)
    gif_path = fd / "cover.gif"
    gif_path.write_bytes(_animated_gif_bytes())
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    app.state.index_loaded = False
    app.state.index = {"v": 1, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    lib = app.get_library(force=True)
    w = lib["groups"][0]["works"][0]
    k, payload, mime = app.cover_payload(w)
    assert k == "file" and mime == "image/gif"
    assert os.path.abspath(payload) == os.path.abspath(str(gif_path)), "文件源动图应直接发原文件"


@pytest.mark.skipif(not PIL_OK, reason="静态缩略图路径需要 pillow")
def test_static_cover_small_in_memory_lru(zip_lib):
    w = _zip_work(zip_lib)
    k, payload, mime = app.cover_payload(w)
    assert k == "bytes" and mime == "image/jpeg"
    with app.COVER_LOCK:
        assert len(app.cover_cache) == 1, "静图缩略图应进内存 LRU"
