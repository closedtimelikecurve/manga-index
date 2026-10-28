# -*- coding: utf-8 -*-
"""音声作品（APP 3.0.1 音画同步）回归测试：音频检测 / lrc 解析 / manifest / 流式端点。"""
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

MP3 = b"ID3" + b"\x00" * 64          # 假 mp3 字节（服务端只透传）
WAV = b"RIFF" + b"\x00" * 32


def _make_zip(path):
    with zipfile.ZipFile(str(path), "w") as z:
        z.writestr("01.jpg", b"\xff\xd8\xff\xe0 fake-jpg")
        z.writestr("02.jpg", b"\xff\xd8\xff\xe0 fake-jpg")
        # 主轨 mp3 + GBK 编码 lrc（RJ 包惯例：同名不同目录）
        z.writestr("mp3/1-01 主音声.mp3", MP3)
        z.writestr("mp3/1-02 回想.mp3", MP3 + b"x")
        z.writestr("lrc/1-01 主音声.lrc", "[00:01.00]大哥哥，我进来了哟\n"
                                        "[00:04.95]大哥哥…\n".encode("gbk"))
        z.writestr("lrc/1-02 回想.lrc", b"\xef\xbb\xbf" + "[00:02.09]（回忆）utf8-line\n".encode("utf-8"))
        z.writestr("read me.txt", b"notes")            # 非媒体文件：不参与


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    app.state.index_loaded = False
    app.state.index = {"v": 3, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    yield root
    app.state.index_keys.clear()


def test_zip_audio_manifest_and_pages_flag(lib_env):
    circ = lib_env / "社团A"
    circ.mkdir()
    _make_zip(circ / "[社团A] 音声作品.zip")
    app.get_library(force=True)
    client = app.app.test_client()
    # /api/pages 带音频标记
    pages = client.get("/api/pages?group=" + quote("社团A") + "&work=" + quote("[社团A] 音声作品")).get_json()
    assert pages["ok"] and pages["audio"] is True and pages["total"] == 2
    # manifest：2 轨 natural 序；主轨 lrc 按 GBK 解析
    m = client.get("/api/audio/manifest?group=" + quote("社团A") + "&work=" + quote("[社团A] 音声作品")).get_json()
    assert m["ok"] and m["total"] == 2
    t0, t1 = m["tracks"]
    assert t0["name"].endswith("1-01 主音声.mp3") and t0["size"] == len(MP3)
    assert t0["lrc"][:2] == [[1000, "大哥哥，我进来了哟"], [4950, "大哥哥…"]]
    assert t1["lrc"] == [[2090, "（回忆）utf8-line"]]     # utf-8 BOM 行亦可解析
    # 无音声作品：无 audio 标记、manifest 空轨
    (circ / "[社团A] 普通作品.zip").write_bytes(b"PK\x03\x04")   # 空包 = 无页无音频
    app.get_library(force=True)
    pages2 = client.get("/api/pages?group=" + quote("社团A") + "&work=" + quote("[社团A] 普通作品")).get_json()
    assert "audio" not in pages2 or pages2.get("ok") is False   # 空包无页：404/ok=False 均可
    mf2 = client.get("/api/audio/manifest?group=" + quote("社团A") + "&work=" + quote("[社团A] 普通作品")).get_json()
    assert mf2["ok"] and mf2["tracks"] == []


def test_audio_streaming_range(lib_env):
    circ = lib_env / "社团A"
    circ.mkdir()
    _make_zip(circ / "[社团A] 音声作品.zip")
    app.get_library(force=True)
    client = app.app.test_client()
    u = "/audio?group=" + quote("社团A") + "&work=" + quote("[社团A] 音声作品")
    r = client.get(u + "&n=0")
    assert r.status_code == 200 and r.data == MP3
    assert r.headers["Content-Type"].startswith("audio/mpeg")
    rr = client.get(u + "&n=0", headers={"Range": "bytes=0-9"})
    assert rr.status_code == 206 and len(rr.data) == 10
    # 越界轨道 404
    assert client.get(u + "&n=9").status_code == 404


def test_folder_audio_work(lib_env):
    circ = lib_env / "社团B"
    d = circ / "音声文件夹"
    d.mkdir(parents=True)
    (d / "01.jpg").write_bytes(b"\xff\xd8\xff\xe0 fake-jpg")
    (d / "track.wav").write_bytes(WAV)
    (d / "track.lrc").write_bytes("[00:10.0]フォルダ版".encode("utf-8"))
    app.get_library(force=True)
    client = app.app.test_client()
    m = client.get("/api/audio/manifest?group=" + quote("社团B") + "&work=" + quote("音声文件夹")).get_json()
    assert m["ok"] and len(m["tracks"]) == 1
    assert m["tracks"][0]["lrc"] == [[10000, "フォルダ版"]]
    r = client.get("/audio?group=" + quote("社团B") + "&work=" + quote("音声文件夹") + "&n=0")
    assert r.status_code == 200 and r.data == WAV


def test_lrc_parse_offset_and_multitimestamp():
    data = "[ti:元数据行应被跳过]\n[offset:500]\n[00:01.00]第一句\n[00:05.50][00:09.00]第二句\n\n[00:12.3]第三句".encode("utf-8")
    lrc = app._parse_lrc_bytes(data)
    # offset +500 → 时间整体前移 500ms
    assert lrc == [[500, "第一句"], [5000, "第二句"], [8500, "第二句"], [11800, "第三句"]]
    # 空输入安全
    assert app._parse_lrc_bytes(b"") == []
    assert app._parse_lrc_bytes("纯文本无时间戳".encode("utf-8")) == []
