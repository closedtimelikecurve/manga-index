# -*- coding: utf-8 -*-
"""改名归档的路径判重安全网（3.6.175）。

事故（2026-10-30）：四部 777~1036 页的作品在改名后从磁盘上消失，`_delete` 直接
unlink、不进回收站，若不是历史索引备份连"少了几部"都数不出来。

链条只有三行：
  1. 原名 `[AIGenerated] Someartist1.zip` 里的词是 **Someartist**（f 小写），
     而社团目录是 `SomeArtist`；
  2. `existing_archive_dir` 走 `os.path.isdir`，Windows 上大小写不敏感 → 返回 `Someartist`，
     于是 `dest_dir` 与 `parent` **字符串不等**（其实同一个目录），提前返回没触发；
  3. `_archive_into` 把 `pre` 拼成 `dest_dir/同名`，那就是 `dst` 自己 → "同名同大小"
     成立 → 判为重复 → `h()._delete(dst)` → 删掉了刚改好名的作品。
"""
import os
import sys
import zipfile

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402

JPG = b"\xff\xd8\xff\xe0 fake-jpg"
WIN_ONLY = pytest.mark.skipif(os.name != "nt", reason="大小写同名目录只在 Windows 上等价")


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    monkeypatch.setitem(app.CFG, "dissolved_circles", [])
    monkeypatch.setitem(app.CFG, "term_blacklist", [])
    app.state.index_loaded = False
    app.state.index = {"v": 2, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    saved_known = dict(app.state.known)
    yield root
    app.state.known.clear()
    app.state.known.update(saved_known)
    app.state.index_keys.clear()


def test_same_path_ignores_case():
    """`_same_path` 必须认文件系统，不能只比字符串。"""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "SomeArtist"))
        assert app._same_path(os.path.join(d, "SomeArtist"),
                              os.path.join(d, "someartist")) is True
        assert app._same_path(os.path.join(d, "SomeArtist"),
                              os.path.join(d, "Other")) is False
        # 路径还没建出来也不能崩（退回 normcase 比较）
        assert app._same_path(os.path.join(d, "nope", "a"), None) is False


@WIN_ONLY
def test_rename_into_case_variant_dir_keeps_file(lib_env):
    """目标目录名与所在目录只差大小写：必须当"同一目录"，改名后文件还在。

    这里正是四部作品被删的那条路径——从前 `os.path.abspath(dest_dir) == abspath(parent)`
    为 False，于是走进归档判重，`pre` 指向 dst 自己，把人删了。
    """
    d = lib_env / "SomeArtist"
    d.mkdir()
    src = d / "[AIGenerated] Someartist1.zip"
    with zipfile.ZipFile(str(src), "w") as z:
        z.writestr("01.jpg", JPG)
    app.get_library(force=True)
    g = next(g for g in app.get_library(force=True)["groups"] if g["name"] == "SomeArtist")
    w = next(w for w in g["works"] if "Someartist1" in w["name"])

    ok, msg = app._apply_rename(w, "[Someartist] Someartist1.zip")
    assert ok, msg
    assert "清理重复项" not in msg, "又把它判成重复了：" + msg
    assert (d / "[Someartist] Someartist1.zip").exists(), "改名把自己删掉了"


def test_same_size_diff_content_is_not_duplicate(lib_env):
    """同名同大小但内容不同 → 不是重复，两份都要留下（判重的第二道闸）。"""
    a = lib_env / "甲.zip"
    b = lib_env / "乙.zip"
    a.write_bytes(b"A" * 4096)
    b.write_bytes(b"B" * 4096)               # 同样 4096 字节，内容不同

    assert app._same_size_file(str(b), str(a)) is True      # 光看大小确实"像"重复
    assert app._same_content(str(a), str(b)) is False       # 内容校验否决
    b.write_bytes(b"A" * 4096)
    assert app._same_content(str(a), str(b)) is True        # 真的一样才认重复


def test_same_content_survives_unreadable_file(lib_env, monkeypatch):
    """读不出来（被占用/权限）一律当作不同 —— 宁可留一份多余的，也不删。"""
    a = lib_env / "甲.zip"
    b = lib_env / "乙.zip"
    a.write_bytes(b"x" * 128)
    b.write_bytes(b"x" * 128)
    real_open = open

    def fake_open(p, *args, **kw):
        if str(p).endswith("乙.zip"):
            raise OSError("locked")
        return real_open(p, *args, **kw)

    monkeypatch.setattr("builtins.open", fake_open)
    assert app._same_content(str(a), str(b)) is False
