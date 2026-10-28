# -*- coding: utf-8 -*-
"""画师改名/合并（3.6.5）回归测试：文件名词条替换 + 文件本体迁移 + DB 联动。

核心设计约束：作者名编码在作品文件名的词条括号里（[社团(作者)] / [作者]），
只改数据库的话下一轮扫描就会从文件名把旧名解析回来——所以必须连文件一起改名，
且改完后重扫不得回流旧名。
"""
import os
import sys
import zipfile

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
import djc_parse as dp  # noqa: E402
import meta_store  # noqa: E402

JPG = b"\xff\xd8\xff\xe0 fake-jpg"


def _make_zip(path, tag=b"A", pages=3):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(path), "w") as z:
        for i in range(1, pages + 1):
            z.writestr("%03d.jpg" % i, JPG + tag + bytes([i]))


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


def _scan(client):
    return client.get("/api/library?refresh=1").get_json()


# --------------------------------------------------------------- 纯函数：词条替换

def test_rename_personal_in_name_variants():
    assert dp.rename_personal_in_name("[社团A (旧名)] 标题.zip", "旧名", "新名") \
        == "[社团A (新名)] 标题.zip"
    # 全角括号（文件名原样输出，不归一）
    assert dp.rename_personal_in_name("[社团A（旧名）] 标题.zip", "旧名", "新名") \
        == "[社团A（新名）] 标题.zip"
    # 裸词条（无社团）
    assert dp.rename_personal_in_name("[旧名] 标题.zip", "旧名", "新名") == "[新名] 标题.zip"
    # 合作作品只换命中那段，分隔符样式保留
    assert dp.rename_personal_in_name("[社团A (甲 & 乙)] t.zip", "甲", "甲甲") \
        == "[社团A (甲甲 & 乙)] t.zip"
    assert dp.rename_personal_in_name("[社团A (甲 x 乙)] t.zip", "乙", "乙乙") \
        == "[社团A (甲 x 乙乙)] t.zip"
    # 标题里的同名文本绝不被误伤
    assert dp.rename_personal_in_name("[社团A (甲)] 甲的作品.zip", "甲", "乙") \
        == "[社团A (乙)] 甲的作品.zip"
    # 整词匹配：Rex 不会被子串 Re 替换
    assert dp.rename_personal_in_name("[社团A (Rex)] t.zip", "Re", "乙") \
        == "[社团A (Rex)] t.zip"
    # 社团名恰好含作者名：只动 () 内
    assert dp.rename_personal_in_name("[甲社团 (甲)] t.zip", "甲", "乙") \
        == "[甲社团 (乙)] t.zip"


# --------------------------------------------------------------- 接口：改名

def test_rename_artist_moves_files_records_and_survives_rescan(lib_env):
    (lib_env / "社团A").mkdir()
    _make_zip(lib_env / "社团A" / "[社团A (旧名)] 作品一.zip")
    _make_zip(lib_env / "社团A" / "[社团A (旧名)] 作品二.zip")
    client = app.app.test_client()
    _scan(client)
    # 改名前写一条阅读进度：key 迁移后必须还在（DB 作品名口径不含扩展名）
    meta_store.reading_set("社团A/[社团A (旧名)] 作品一", 2)

    j = client.post("/api/artist/rename",
                    json={"from": "旧名", "to": "新名"}).get_json()
    assert j["ok"] and j["renamed"] == 2 and j["merged"] is False
    assert (lib_env / "社团A" / "[社团A (新名)] 作品一.zip").exists()
    assert (lib_env / "社团A" / "[社团A (新名)] 作品二.zip").exists()
    assert not (lib_env / "社团A" / "[社团A (旧名)] 作品一.zip").exists()

    # DB 联动：作者迁移、旧名降级为别名、进度按新 key 保留
    assert len(meta_store.author_work_paths("新名")) == 2
    assert not meta_store.author_work_paths("旧名")
    assert "旧名" in meta_store.aliases_of("新名")
    rd = meta_store.reading_get("社团A/[社团A (新名)] 作品一")
    assert rd and rd["last_page"] == 2

    # 关键回归：强制重扫后作者不得回流成旧名（文件名已改 → 解析出新名）
    lib = app.get_library(force=True)
    g = next(g for g in lib["groups"] if g["name"] == "社团A")
    names = sorted(w["name"] for w in g["works"])
    assert names == ["[社团A (新名)] 作品一", "[社团A (新名)] 作品二"]
    assert all("新名" in (w.get("personals") or []) for w in g["works"])


def test_rename_artist_merges_when_target_exists(lib_env):
    (lib_env / "社团A").mkdir()
    (lib_env / "社团B").mkdir()
    _make_zip(lib_env / "社团A" / "[社团A (甲)] 甲一.zip")
    _make_zip(lib_env / "社团B" / "[社团B (乙)] 乙一.zip")
    client = app.app.test_client()
    _scan(client)
    meta_store.follow_add("甲")
    meta_store.follow_add("乙")

    j = client.post("/api/artist/rename", json={"from": "甲", "to": "乙"}).get_json()
    assert j["ok"] and j["merged"] is True and j["renamed"] == 1
    assert (lib_env / "社团A" / "[社团A (乙)] 甲一.zip").exists()
    assert (lib_env / "社团B" / "[社团B (乙)] 乙一.zip").exists()

    # 合并后：两部作品都归乙；甲降级为乙的别名；喜爱清单并入且不重复
    assert len(meta_store.author_work_paths("乙")) == 2
    assert not meta_store.author_work_paths("甲")
    assert "甲" in meta_store.aliases_of("乙")
    follows = [f["author"] for f in meta_store.follows_list()]
    assert follows.count("乙") == 1 and "甲" not in follows

    # 重扫不回流
    lib = app.get_library(force=True)
    works = {w["name"] for g in lib["groups"] for w in g["works"]}
    assert "[社团A (乙)] 甲一" in works


def test_rename_artist_pure_case_change(lib_env):
    """3.6.6 回归：纯大小写改名（someartist→SomeArtist）不得被「目标已存在」误判。

    Windows 文件系统大小写不敏感：new_path 与旧文件只差大小写时 exists() 误报为真、
    lower() 相等判断又会整批 skip——症状是 DB 改了名、文件原地不动，下一轮扫描
    还会把旧名从文件名解析回来。NTFS 不允许两个仅大小写不同的文件共存，故
    normcase 相等即同一文件，必须放行 rename。"""
    (lib_env / "someartist").mkdir()
    _make_zip(lib_env / "someartist" / "[someartist] 作品一.zip")
    _make_zip(lib_env / "someartist" / "[someartist] 作品二.zip")
    client = app.app.test_client()
    _scan(client)

    j = client.post("/api/artist/rename",
                    json={"from": "someartist", "to": "SomeArtist"}).get_json()
    assert j["ok"], j
    assert j["renamed"] == 2, j
    # os.listdir 返回目录项**真实大小写**（exists() 在 Windows 上大小写不敏感，会误判）
    listing = os.listdir(lib_env / "someartist")
    assert "[SomeArtist] 作品一.zip" in listing
    assert "[SomeArtist] 作品二.zip" in listing
    assert "[someartist] 作品一.zip" not in listing

    # 重扫不回流旧名（文件名已真正更改）
    lib = app.get_library(force=True)
    names = sorted(w["name"] for g in lib["groups"] for w in g["works"])
    assert names == ["[SomeArtist] 作品一", "[SomeArtist] 作品二"]


def test_rename_artist_rejects_bad_input(lib_env):
    (lib_env / "社团A").mkdir()
    _make_zip(lib_env / "社团A" / "[社团A (甲)] 甲一.zip")
    client = app.app.test_client()
    _scan(client)
    assert client.post("/api/artist/rename",
                       json={"from": "不存在的人", "to": "乙"}).status_code == 404
    assert client.post("/api/artist/rename",
                       json={"from": "甲", "to": ""}).status_code == 400
    assert client.post("/api/artist/rename",
                       json={"from": "甲", "to": "收件箱"}).status_code == 400
    # 同名：直接幂等返回，不碰文件
    j = client.post("/api/artist/rename", json={"from": "甲", "to": "甲"}).get_json()
    assert j["ok"] and j["renamed"] == 0
    assert (lib_env / "社团A" / "[社团A (甲)] 甲一.zip").exists()
