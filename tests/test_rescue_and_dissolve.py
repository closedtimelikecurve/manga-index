# -*- coding: utf-8 -*-
"""词条救援(后续括号找已知个人名)回归测试。"""
import os
import sys
import zipfile

from pathlib import Path

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402

JPG = b"\xff\xd8\xff\xe0 fake-jpg"


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    monkeypatch.setitem(app.CFG, "dissolved_circles", ["無邪気無修宇宙分組"])
    monkeypatch.setitem(app.CFG, "term_blacklist", [])
    app.state.index_loaded = False
    app.state.index = {"v": 2, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    saved_known = dict(app.state.known)
    app.state.known.clear()
    app.state.known.update({"ready": True, "circles": {"銀糖製菓"},
                       "pc": {"玉砂糖": {"銀糖製菓"}}})
    yield root
    app.state.known.clear()
    app.state.known.update(saved_known)
    app.state.index_keys.clear()


def test_rescue_personal_from_later_bracket(lib_env):
    name = ("[無修正] [無邪気無修宇宙分組] I'm with You 【無邪気漢化組】 [玉砂糖] "
            "[MJK-19-Z1234] (COMIC BAVEL 2019年1月号).zip")
    assert app._rescue_personal(name) == "玉砂糖"


def test_rescue_v2_unknowns_and_filters(lib_env):
    # v2：陌生词条也入候选（用户要求）
    name = "[無修正] [無邪気無修宇宙分組] X 【無邪気漢化組】 [陌生词条] (COMIC).zip"
    assert app._rescue_personal(name) == "陌生词条"
    # 黑名单/展会词条不作候选
    name2 = "[無修正] [無邪気無修宇宙分組] X 【無邪気漢化組】 [Pixiv] (COMIC).zip"
    assert app._rescue_personal(name2) == ""


def test_apply_rename_rescues_to_artist_dir(lib_env):
    root = lib_env
    d = root / "待整理"
    d.mkdir()
    zpath = d / "[無修正] [無邪気無修宇宙分組] I'm with You 【無邪気漢化組】 [玉砂糖] [MJK-19-Z1234] (COMIC BAVEL 2019年1月号).zip"
    with zipfile.ZipFile(str(zpath), "w") as z:
        z.writestr("01.jpg", JPG)
        z.writestr("02.jpg", JPG)
    lib = app.get_library(force=True)
    g = next(g for g in lib["groups"] if g["name"] == "待整理")
    w = next(w for w in g["works"] if "I'm with You" in w["name"])
    ok, msg = app._apply_rename(w, w["name"] + ".zip")
    assert ok and "归档到" in msg, msg
    # 作废"自动补社团名"后：救援出的个人名按画师名自建目录(玉砂糖/),不再归入銀糖製菓
    assert (root / "玉砂糖").exists()
    assert not zpath.exists()                    # 已搬离待整理
    moved = list((root / "玉砂糖").glob("*.zip"))
    assert len(moved) == 1 and "玉砂糖" in moved[0].name


def test_dissolve_moves_works_and_reports(lib_env):
    root = lib_env
    circ = root / "社团甲"
    circ.mkdir(parents=True)
    for i in range(2):
        with zipfile.ZipFile(str(circ / f"[社团甲] 作品{i}.zip"), "w") as z:
            z.writestr("01.jpg", JPG)
    lib = app.get_library(force=True)
    client = app.app.test_client()
    r = client.post("/api/dissolve-circle", json={"group": "社团甲"})
    assert r.status_code == 200, r.get_json()
    assert not circ.exists()                     # 目录整棵清除
    files = list(Path(app._inbox_dir()).glob("*.zip"))
    assert len(files) == 2                       # 作品进收件箱(_app/_inbox)


# ---------- 社团改名 ----------

def test_rename_circle_basic(lib_env):
    root = lib_env
    circ = root / "社团甲"
    circ.mkdir(parents=True)
    with zipfile.ZipFile(str(circ / "[社团甲] 作品.zip"), "w") as z:
        z.writestr("01.jpg", JPG)
    app.get_library(force=True)
    client = app.app.test_client()
    r = client.post("/api/rename-circle", json={"group": "社团甲", "new_name": "社团乙"})
    assert r.status_code == 200, r.get_json()
    assert (root / "社团乙" / "[社团甲] 作品.zip").exists()   # 作品文件不动
    assert not circ.exists()


def test_rename_circle_merges_into_existing(lib_env):
    """3.7.4：改名撞上已存在的社团 → 合并（作品并入，源目录清除），不再是报错拒绝。"""
    root = lib_env
    for c in ("社团A", "社团B"):
        (root / c).mkdir(parents=True)
        with zipfile.ZipFile(str(root / c / f"[{c}] 作品.zip"), "w") as z:
            z.writestr("01.jpg", JPG)       # 空目录不构成社团，需有作品
    app.get_library(force=True)
    client = app.app.test_client()
    r = client.post("/api/rename-circle", json={"group": "社团A", "new_name": "社团B"})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body.get("merged") is True and body.get("moved") == 1
    assert (root / "社团B" / "[社团A] 作品.zip").exists()   # 原文件名不变地搬过去
    assert (root / "社团B" / "[社团B] 作品.zip").exists()   # 目标原有作品不受影响
    assert not (root / "社团A").exists()                    # 源目录已清除
    lib = app.get_library(force=True)
    names = [g["name"] for g in lib["groups"]]
    assert "社团A" not in names and "社团B" in names
    b = next(g for g in lib["groups"] if g["name"] == "社团B")
    assert len(b["works"]) == 2                             # 两社会一
    r2 = client.post("/api/rename-circle", json={"group": "社团B", "new_name": "收件箱"})
    assert r2.status_code == 400


def test_rename_circle_merge_keeps_duplicate_names(lib_env):
    """合并时目标社团里已有同名文件 → 绝不覆盖，另起不冲突的名字。"""
    root = lib_env
    for c in ("社团A", "社团B"):
        (root / c).mkdir(parents=True)
        with zipfile.ZipFile(str(root / c / "同名作品.zip"), "w") as z:
            z.writestr("01.jpg", JPG)
    app.get_library(force=True)
    r = app.app.test_client().post(
        "/api/rename-circle", json={"group": "社团A", "new_name": "社团B"})
    assert r.status_code == 200, r.get_json()
    assert (root / "社团B" / "同名作品.zip").exists()
    assert (root / "社团B" / "同名作品 (2).zip").exists()   # 重名不覆盖


def test_rename_circle_rejects_uncat(lib_env):
    """「收件箱」不接受改名，也不能改名为「收件箱」。"""
    root = lib_env
    (root / "社团A").mkdir(parents=True)
    with zipfile.ZipFile(str(root / "社团A" / "[社团A] 作品.zip"), "w") as z:
        z.writestr("01.jpg", JPG)
    (root / "待整理").mkdir(parents=True)
    with zipfile.ZipFile(str(root / "待整理" / "散包.zip"), "w") as z:
        z.writestr("01.jpg", JPG)
    app.get_library(force=True)
    client = app.app.test_client()
    assert client.post("/api/rename-circle",
                       json={"group": "社团A", "new_name": "收件箱"}).status_code == 400
    assert client.post("/api/rename-circle",
                       json={"group": "收件箱", "new_name": "别的名"}).status_code == 400


def test_rename_circle_rejects_unknown_group(lib_env):
    client = app.app.test_client()
    r = client.post("/api/rename-circle", json={"group": "不存在", "new_name": "X"})
    assert r.status_code == 404


# ---------- 分块上传(救援不可靠链路) ----------

def test_chunked_upload_end_to_end(lib_env):
    root = lib_env
    d = root / "待整理"
    d.mkdir(parents=True)
    payload = JPG * 100                                # 足够分两块的数据
    data = payload + payload                           # 双倍内容
    half = len(data) // 2
    client = app.app.test_client()
    uid = "utest1234567890ab"
    for idx, chunk in enumerate([data[:half], data[half:]]):
        r = client.post(f"/api/upload-chunk?upload_id={uid}&fid=0&idx={idx}", data=chunk)
        assert r.status_code == 200 and r.get_json()["received"] == len(chunk)
    r = client.post("/api/upload-commit", json={
        "upload_id": uid,
        "files": [{"name": "[社团甲] 分块作品.zip", "rel": "", "chunks": 2}]})
    assert r.status_code == 200, r.get_json()
    j = r.get_json()
    assert j["imported"] == 1
    got = list((root / "社团甲").glob("*分块作品*.zip"))   # 文件名带词条 → 归档到社团甲
    assert len(got) == 1
    import hashlib
    assert hashlib.md5(got[0].read_bytes()).hexdigest() == hashlib.md5(data).hexdigest()
    # 会话分块已清理
    import os
    assert not os.path.isdir(os.path.join(app.UPLOAD_TMP, uid))


def test_chunked_upload_missing_part(lib_env):
    (lib_env / "收件箱").mkdir(parents=True)
    client = app.app.test_client()
    uid = "utest0987654321ba"
    client.post(f"/api/upload-chunk?upload_id={uid}&fid=0&idx=0", data=b"AAAA")
    r = client.post("/api/upload-commit", json={
        "upload_id": uid,
        "files": [{"name": "[社团甲] 残缺.zip", "rel": "", "chunks": 2}]})
    assert r.status_code == 400 and "缺少第 2 块" in r.get_json()["message"]


# ---------- 无扩展名文件内容嗅探 ----------

def test_import_sniffs_extensionless_zip(lib_env):
    root = lib_env
    d = root / "待整理"
    d.mkdir(parents=True)
    client = app.app.test_client()
    fn = "[半里バード]_ナマイキお嬢～璃璃編～_(COMIC快楽天ビースト_2020年7月号)_[無邪気漢化組]"
    data = b"PK\x03\x04" + b"\xff\xd8" * 500          # zip 魔数开头
    from werkzeug.datastructures import FileStorage
    import io as _io
    entries = [(FileStorage(_io.BytesIO(data), filename=fn), fn, "")]
    with app.app.app_context():
        resp = app._import_process(entries)
    j = resp.get_json()
    assert j["imported"] == 1, j                        # 嗅探为 zip → 正常导入
    moved = list((root / "半里バード").glob("*.zip"))
    assert len(moved) == 1 and moved[0].name.endswith(".zip")   # 规范化名与原名不同，按目录断言


# ---------- 解散/删除社团后自动清理空文件夹 ----------

def test_dissolve_auto_cleans_empty_dirs(lib_env):
    root = lib_env
    circ = root / "社团甲"
    circ.mkdir(parents=True)
    with zipfile.ZipFile(str(circ / "[社团甲] 作品.zip"), "w") as z:
        z.writestr("01.jpg", JPG)
    (root / "社团乙").mkdir(parents=True)
    with zipfile.ZipFile(str(root / "社团乙" / "[社团乙] 作品.zip"), "w") as z:
        z.writestr("01.jpg", JPG)                  # 有作品的社团不被清
    leftover = root / "社团乙" / "遗留空目录"      # 无关社团下的遗留空目录
    leftover.mkdir(parents=True)
    app.get_library(force=True)
    client = app.app.test_client()
    r = client.post("/api/dissolve-circle", json={"group": "社团甲"})
    j = r.get_json()
    assert r.status_code == 200 and j["cleaned_dirs"] >= 1
    assert "自动清理" in j["message"]
    assert not leftover.exists()
    assert (root / "社团乙").exists()              # 有作品的社团本身保留
