# -*- coding: utf-8 -*-
"""M4 人物志与关注回归测试：画师档案页 / 关注与新增作品计数 / 阅读状态汇总。"""
import os
import sys
import time
import zipfile
from urllib.parse import quote

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
import meta_store  # noqa: E402

JPG = b"\xff\xd8\xff\xe0 fake-jpg"


def _make_zip(path, tag=b"A"):
    with zipfile.ZipFile(str(path), "w") as z:
        z.writestr("001.jpg", JPG + tag)


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
    saved_known = dict(app.state.known)
    yield root
    app.state.known.clear()
    app.state.known.update(saved_known)
    app.state.index_keys.clear()


def test_artist_page_cross_circle_aliases_timeline(lib_env):
    for c in ("社团甲", "社团乙"):
        (lib_env / c).mkdir()
    _make_zip(lib_env / "社团甲" / "[社团甲 (hiten)] W1.zip", tag=b"1")
    _make_zip(lib_env / "社团甲" / "[社团甲 (hiten & 搭档)] W2.zip", tag=b"2")
    _make_zip(lib_env / "社团乙" / "[社团乙 (飞天御姐流)] W3.zip", tag=b"3")
    client = app.app.test_client()
    client.post("/api/author-aliases", json={"alias": "飞天御姐流", "canonical": "hiten"})
    app.get_library(force=True)
    # 用别名查询 → 归一到正名 hiten，跨社团 3 部全中
    r = client.get("/api/artist/" + quote("飞天御姐流")).get_json()
    assert r["ok"] and r["author"] == "hiten"
    assert r["total"] == 3
    assert {w["work"] for w in r["works"]} == {
        "[社团甲 (hiten)] W1", "[社团甲 (hiten & 搭档)] W2", "[社团乙 (飞天御姐流)] W3"}
    assert r["circles"] == [{"name": "社团甲", "count": 2}, {"name": "社团乙", "count": 1}]
    assert "飞天御姐流" in r["aliases"]
    # 时间线：added_at 倒序（回填自文件 mtime，这里都是近似值——只验降序）
    added = [w["added_at"] for w in r["works"]]
    assert added == sorted(added, reverse=True)
    # 未关注状态
    assert r["is_following"] is False


def test_follow_flow_and_new_count(lib_env):
    (lib_env / "社团甲").mkdir()
    _make_zip(lib_env / "社团甲" / "[社团甲 (hiten)] W1.zip")
    app.get_library(force=True)
    client = app.app.test_client()
    assert client.post("/api/follow", json={"author": "hiten"}).get_json()["ok"]
    assert client.post("/api/follow", json={"author": "hiten"}).get_json()["ok"]   # 幂等
    f = client.get("/api/follows").get_json()["follows"]
    assert len(f) == 1 and f[0]["author"] == "hiten" and f[0]["works"] == 1
    # 关注后浏览档案页 → 盖 last_seen；随后新增作品 → new=1
    # （added_at 与基线都按秒截断，必须跨过秒边界比较才有意义）
    client.get("/api/artist/hiten")
    time.sleep(1.1)
    _make_zip(lib_env / "社团甲" / "[社团甲 (hiten)] W2.zip", tag=b"2")
    app.get_library(force=True)
    f2 = client.get("/api/follows").get_json()["follows"][0]
    assert f2["works"] == 2 and f2["new"] == 1, f2
    # 再浏览档案页 → 新作品计数清零
    client.get("/api/artist/hiten")
    f3 = client.get("/api/follows").get_json()["follows"][0]
    assert f3["new"] == 0
    # 取消关注
    assert client.post("/api/follow/unfollow", json={"author": "hiten"}).get_json()["ok"]
    assert client.post("/api/follow/unfollow", json={"author": "hiten"}).status_code == 404
    assert client.get("/api/follows").get_json()["follows"] == []


def test_reading_summary_states_and_new_keys(lib_env):
    (lib_env / "社团A").mkdir()
    _make_zip(lib_env / "社团A" / "[社团A] 作品.zip")
    app.get_library(force=True)
    client = app.app.test_client()
    # 首次 mark-seen：previous=0 → 不把全库当新作品（首次访问没有"新"基线）
    assert client.post("/api/reading/mark-seen", json={}).get_json()["previous"] == 0
    time.sleep(1.1)
    # 第二次 mark-seen：previous = 首次时刻（>0，成为可用基线）
    prev = client.post("/api/reading/mark-seen", json={}).get_json()["previous"]
    assert prev > 0
    time.sleep(1.1)
    # 基线之后新增一部作品 + 产生阅读状态
    _make_zip(lib_env / "社团A" / "[社团A] 新作品.zip", tag=b"2")
    app.get_library(force=True)
    client.post("/api/reading/state",
                json={"key": "社团A/[社团A] 作品", "last_page": 3, "finished": True})
    j = client.get("/api/reading/summary?since=" + str(prev)).get_json()
    assert j["ok"]
    assert j["states"]["社团A/[社团A] 作品"] == {"p": 3, "f": True}
    assert j["new_keys"] == ["社团A/[社团A] 新作品"]
    # since=0 → 不把全库当新作品
    j0 = client.get("/api/reading/summary?since=0").get_json()
    assert j0["new_keys"] == []


def test_artists_all_aggregate(lib_env):
    for c in ("社团甲", "社团乙"):
        (lib_env / c).mkdir()
    _make_zip(lib_env / "社团甲" / "[社团甲 (hiten)] W1.zip", tag=b"1")
    _make_zip(lib_env / "社团甲" / "[社团甲 (hiten)] W2.zip", tag=b"2")
    _make_zip(lib_env / "社团乙" / "[社团乙 (搭档)] W3.zip", tag=b"3")
    app.get_library(force=True)
    client = app.app.test_client()
    j = client.get("/api/artists").get_json()
    assert j["ok"]
    names = {a["name"] for a in j["artists"]}
    assert names == {"hiten", "搭档"}
    hiten = next(a for a in j["artists"] if a["name"] == "hiten")
    assert hiten["works"] == 2                                  # 作品数降序在前
    assert j["artists"][0]["name"] == "hiten"

def test_artist_and_resume_expose_original_tags(lib_env):
    """3.7.51：原作标签不能只在原作分区页有——画师页 / 续读页的作品也要带 originals。

    服务端此前只有 public_work 的 tags 带原作信息；画师接口与续读接口都没下发，
    前端那几个卡片想显示也拿不到数据。
    """
    (lib_env / "社团甲").mkdir()
    _make_zip(lib_env / "社团甲" / "[社团甲 (hiten)] W1 (FateGrand Order).zip", tag=b"1")
    client = app.app.test_client()
    app.get_library(force=True)
    key = "社团甲/[社团甲 (hiten)] W1 (FateGrand Order)"
    assert meta_store.originals_of(key) == ["FateGrand Order"]

    j = client.get("/api/artist/" + quote("hiten")).get_json()
    assert j["ok"] and j["works"], j
    assert j["works"][0]["originals"] == ["FateGrand Order"], j["works"][0]

    # 续读：造一条阅读记录后，接口同样要带 originals
    meta_store.reading_set(key, 3, finished=False)
    r = client.get("/api/reading/resume").get_json()
    hit = [x for x in r["items"] if x["key"] == key]
    assert hit and hit[0]["originals"] == ["FateGrand Order"], r
