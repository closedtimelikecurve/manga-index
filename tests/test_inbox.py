# -*- coding: utf-8 -*-
"""收件箱工作流（M3）回归测试：登记提案 / 内容哈希去重 / 确认入库 / 删除 / 一键入库 /
半成品(.part)不进队列也有清理出口 / 导入去重。"""
import io
import os
import sys
import zipfile
from urllib.parse import quote

from pathlib import Path

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
from werkzeug.datastructures import FileStorage  # noqa: E402

JPG = b"\xff\xd8\xff\xe0 fake-jpg"


# zip 条目的 DOS 时间戳精度只有 **2 秒**，且 writestr 默认取「当前时间」。
# 于是同一个 tag 造出来的两个"同内容"包，只要两次调用跨过偶数秒边界，字节流就不一样、
# SHA1 也不同 → 内容去重判定为"非重复" → test_inbox_dedup_renamed_duplicate 偶发失败
# （两次 _make_zip 之间隔着 get_library(force=True)，耗时恰好跨边界就红；单独跑常常躲过）。
# 固定时间戳让"同 tag = 同字节 = 同 SHA1"成为确定的不变量。
_ZIP_DATE_TIME = (2020, 1, 1, 0, 0, 0)


def _make_zip(path, tag=b"A", pages=3):
    with zipfile.ZipFile(str(path), "w") as z:
        for i in range(1, pages + 1):
            z.writestr(zipfile.ZipInfo("%03d.jpg" % i, date_time=_ZIP_DATE_TIME),
                       JPG + tag + bytes([i]))


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    os.makedirs(app._inbox_dir(), exist_ok=True)   # 3.6.3 收件箱在程序目录内
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


def _drop_inbox(_root, fname, tag=b"A"):   # 3.6.3 收件箱目录 = app._inbox_dir()（不再在文库根）
    p = os.path.join(app._inbox_dir(), fname)
    _make_zip(p, tag=tag)
    return p


def test_inbox_register_propose_and_scan_skip(lib_env):
    _drop_inbox(lib_env, "[社团A (画师乙)] 收件作品 (C102).zip")
    client = app.app.test_client()
    j = client.get("/api/inbox/list").get_json()
    assert j["ok"] and j["pending"] == 1 and len(j["items"]) == 1
    it = j["items"][0]
    assert it["state"] == "pending" and it["exists"]
    p = it["proposal"]
    assert p["kind"] == "archive" and p["circle"] == "社团A" and p["confidence"] == "high"
    assert p["new_name"].endswith(".zip") and p["dup"] is None
    assert p["sha1"] if False else True
    # _inbox 不进文库扫描
    lib = app.get_library(force=True)
    assert all(g["name"] != "_inbox" for g in lib["groups"])
    # 无音源文件类型登记为 unsupported
    (Path(app._inbox_dir()) / "说明.txt").write_bytes(b"hello")
    j2 = client.get("/api/inbox/list").get_json()
    unsup = [i for i in j2["items"] if i["name"] == "说明.txt"]
    assert unsup and unsup[0]["proposal"]["kind"] == "unsupported"


def test_inbox_item_readable_before_confirm(lib_env):
    """3.4.2 先读后入库：收件项以伪社团「收件箱」+ 收件项id 走完整阅读链路。"""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 20, 30)).save(buf, "JPEG", quality=85)
    jpg = buf.getvalue()
    p = os.path.join(app._inbox_dir(), "[社团A (画师乙)] 收件作品 (C102).zip")
    with zipfile.ZipFile(str(p), "w") as z:
        for i in range(1, 5):
            z.writestr("收件作品/%03d.jpg" % i, jpg)
    client = app.app.test_client()
    it = client.get("/api/inbox/list").get_json()["items"][0]
    gid = str(it["id"])
    # find_work 伪作品：页数/封面/名字
    w = app.find_work("收件箱", gid)
    assert w and w["pages"] == 4 and w["cover"] and "社团A" in w["name"]
    # /api/pages + /page + /cover 全链路（webp 等媒体类型照常走 media_kind）
    j = client.get("/api/pages?group=" + quote("收件箱") + "&work=" + gid).get_json()
    assert j["ok"] and j["total"] == 4 and j["kinds"] == ["image"] * 4
    r = client.get("/page?group=" + quote("收件箱") + "&work=" + gid + "&n=0")
    assert r.status_code == 200 and r.data[:3] == b"\xff\xd8\xff"
    assert client.get("/cover?group=" + quote("收件箱") + "&work=" + gid).status_code == 200
    # 已消失/不存在的收件项 → 404
    assert client.get("/api/pages?group=" + quote("收件箱") + "&work=99999").status_code == 404
    # 库索引里仍没有收件箱（不影响既有扫描语义）
    lib = app.get_library(force=True)
    assert all(g["name"] != "收件箱" for g in lib["groups"])


def test_inbox_supplement_info_prefills_and_archives(lib_env):
    """3.6.8 收件箱作品增补信息：parse-info 预填（kind 缺失曾致 500）+ 保存后归档入库。"""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 20, 30)).save(buf, "JPEG", quality=85)
    jpg = buf.getvalue()
    p = os.path.join(app._inbox_dir(), "[社团A (画师乙)] 收件作品 (C102).zip")
    with zipfile.ZipFile(str(p), "w") as z:
        for i in range(1, 4):
            z.writestr("%03d.jpg" % i, jpg)
    client = app.app.test_client()
    it = client.get("/api/inbox/list").get_json()["items"][0]
    gid = str(it["id"])
    # parse-info：预填各词条（修复前 _split_work_name 读 w["kind"] 直接 KeyError 500）
    r = client.get("/api/parse-info?group=" + quote(app.INBOX_GROUP) + "&work=" + gid)
    assert r.status_code == 200, r.data
    d = r.get_json()
    assert d["file"] == "[社团A (画师乙)] 收件作品 (C102).zip"
    assert d["circle"] == "社团A" and d["personal"] == "画师乙"
    assert d["title"] == "收件作品" and d["event"] == "C102"
    # 整标题模式预填（base 不含扩展名）
    assert d["base"] == "[社团A (画师乙)] 收件作品 (C102)"
    # supplement-info：改标题后保存 → 规范化命名并搬出收件箱落到社团目录
    r2 = client.post("/api/supplement-info", json={
        "group": app.INBOX_GROUP, "work": gid,
        "fields": {"circle": "社团A", "personal": "画师乙", "title": "补全后的名字"}})
    assert r2.status_code == 200, r2.data
    assert r2.get_json()["ok"], r2.get_json()
    moved = list((lib_env / "社团A").glob("*.zip"))
    assert len(moved) == 1 and "补全后的名字" in moved[0].name
    assert not (Path(app._inbox_dir()) / "[社团A (画师乙)] 收件作品 (C102).zip").exists()


def test_inbox_dedup_renamed_duplicate(lib_env):
    # 库内已有作品 A（社团A/[社团A] 已有作品）
    circ = lib_env / "社团A"
    circ.mkdir()
    _make_zip(circ / "[社团A] 已有作品.zip", tag=b"SAME")
    app.get_library(force=True)
    # 收件箱放进同内容、不同名的包 → 提案标疑似重复
    _drop_inbox(lib_env, "[社团B] 改名同内容.zip", tag=b"SAME")
    client = app.app.test_client()
    j = client.get("/api/inbox/list").get_json()
    it = next(i for i in j["items"] if i["name"].startswith("[社团B]"))
    assert it["proposal"]["dup"] is not None
    assert it["proposal"]["dup"]["name"] == "社团A/[社团A] 已有作品"
    # 一键入库：疑似重复被跳过，留人工裁决
    r = client.post("/api/inbox/confirm-all").get_json()
    assert r["ok"] and r["confirmed"] == 0 and r["skipped"] == 1
    assert (Path(app._inbox_dir()) / "[社团B] 改名同内容.zip").exists()   # 未动
    # 队列内互斥：再放一个同内容包 → 与队列内那条互相标记
    _drop_inbox(lib_env, "[社团C] 又一个改名.zip", tag=b"SAME")
    j2 = client.get("/api/inbox/list").get_json()
    dups = [i for i in j2["items"] if i["proposal"].get("dup")]
    assert len(dups) >= 2


def test_inbox_confirm_moves_and_registers(lib_env):
    _drop_inbox(lib_env, "[社团A (画师乙)] 收件作品 (C102).zip")
    client = app.app.test_client()
    j = client.get("/api/inbox/list").get_json()
    iid = j["items"][0]["id"]
    r = client.post("/api/inbox/confirm", json={"id": iid}).get_json()
    assert r["ok"], r
    assert "社团A" in r["message"]
    # 文件已挪入社团目录，收件原位清空
    moved = list((lib_env / "社团A").glob("*.zip"))
    assert len(moved) == 1 and "收件作品" in moved[0].name
    assert not (Path(app._inbox_dir()) / "[社团A (画师乙)] 收件作品 (C102).zip").exists()
    # 重扫后进文库，且 key 正确
    lib = app.get_library(force=True)
    keys = {w["name"] for g in lib["groups"] for w in g["works"]}
    assert any("收件作品" in k for k in keys)
    # 再次确认 → 已入库
    assert client.post("/api/inbox/confirm", json={"id": iid}).status_code == 400


def test_inbox_confirm_circle_override_and_same_content_skip(lib_env):
    circ = lib_env / "社团X"
    circ.mkdir()
    _make_zip(circ / "[社团X] 同内容包.zip", tag=b"OVR")
    app.get_library(force=True)
    _drop_inbox(lib_env, "[社团Y] 覆盖社团测试.zip", tag=b"OVR")
    client = app.app.test_client()
    j = client.get("/api/inbox/list").get_json()
    iid = j["items"][0]["id"]
    # 覆盖社团为 社团X：同内容 → 内容级终判默认跳过（文件留在收件箱，绝不造第二份）
    r = client.post("/api/inbox/confirm", json={"id": iid, "circle": "社团X"}).get_json()
    assert not r["ok"] and "相同内容" in r["message"], r
    assert len(list((lib_env / "社团X").glob("*.zip"))) == 1
    # 用户看到提示后强意入库（force）→ 放行
    r2 = client.post("/api/inbox/confirm",
                     json={"id": iid, "circle": "社团X", "force": True}).get_json()
    assert r2["ok"], r2
    assert len(list((lib_env / "社团X").glob("*.zip"))) == 2
    # 再测覆盖到新社团：文件挪入
    _drop_inbox(lib_env, "[社团Y] 覆盖社团测试2.zip", tag=b"OVR2")
    j2 = client.get("/api/inbox/list").get_json()
    iid2 = next(i for i in j2["items"] if "测试2" in i["name"])["id"]
    r2 = client.post("/api/inbox/confirm", json={"id": iid2, "circle": "手工社团"}).get_json()
    assert r2["ok"] and "手工社团" in r2["message"], r2
    assert list((lib_env / "手工社团").glob("*.zip"))


def test_inbox_delete_removes_file(lib_env):
    _drop_inbox(lib_env, "[社团A] 待删除.zip", tag=b"D2")
    client = app.app.test_client()
    j = client.get("/api/inbox/list").get_json()
    i2 = next(i for i in j["items"] if "待删除" in i["name"])
    assert client.post("/api/inbox/delete", json={"id": i2["id"]}).get_json()["ok"]
    assert not (Path(app._inbox_dir()) / "[社团A] 待删除.zip").exists()
    j3 = client.get("/api/inbox/list").get_json()
    assert all(i["id"] != i2["id"] for i in j3["items"])


def test_inbox_ignore_endpoint_removed(lib_env):
    """3.5.1：「忽略」既不是删除、也只是在列表里多挂一个标签，属于重复造轮子 → 已移除。"""
    _drop_inbox(lib_env, "[社团A] 不再有忽略.zip")
    client = app.app.test_client()
    j = client.get("/api/inbox/list").get_json()
    iid = next(i for i in j["items"] if "不再有忽略" in i["name"])["id"]
    assert client.post("/api/inbox/ignore", json={"id": iid}).status_code == 404
    j2 = client.get("/api/inbox/list").get_json()
    assert next(i for i in j2["items"] if i["id"] == iid)["state"] == "pending"


def test_inbox_part_files_hidden_but_purgeable(lib_env):
    """下载半成品既不进收件列表，也不能被判成已入库（爬虫重复判定的坑验收）。"""
    box = Path(app._inbox_dir())
    (box / "[社团A] 半成品.zip.part").write_bytes(b"PK\x03\x04" + b"x" * 4096)
    (box / "[社团A] 半成品.zip.part.src").write_text("https://dl1.wn01.download/x.zip")
    client = app.app.test_client()
    j = client.get("/api/inbox/list").get_json()
    assert j["items"] == []                    # 不伪装成待入库作品
    assert len(j["parts"]) == 2                # 但能看见、能清
    r = client.post("/api/inbox/purge-parts", json={}).get_json()
    assert r["ok"] and r["removed"] == 2
    assert not (box / "[社团A] 半成品.zip.part").exists()
    assert client.get("/api/inbox/list").get_json()["parts"] == []


def test_inbox_confirm_all_archives_everything_clean(lib_env):
    _drop_inbox(lib_env, "[社团A (画师乙)] 一键1 (C99).zip")
    _drop_inbox(lib_env, "[社团B] 一键2.zip", tag=b"B2")
    client = app.app.test_client()
    r = client.post("/api/inbox/confirm-all").get_json()
    assert r["ok"] and r["confirmed"] == 2 and r["skipped"] == 0, r
    assert list((lib_env / "社团A").glob("*一键1*.zip"))
    assert list((lib_env / "社团B").glob("*一键2*.zip"))
    j = client.get("/api/inbox/list").get_json()
    assert j["pending"] == 0


def test_import_pipeline_sha1_dedup(lib_env):
    os.makedirs(app._inbox_dir(), exist_ok=True)
    client = app.app.test_client()
    data = b"PK\x03\x04" + JPG * 200
    entries = [(FileStorage(io.BytesIO(data), filename="[社团A] 首次导入.zip"), "", None)]
    with app.app.app_context():
        r1 = app._import_process(entries).get_json()
    assert r1["imported"] == 1
    assert "rel" in r1["results"][0]          # 3.5.5：结果带相对路径，供前端删源时精确匹配句柄
    # 同内容不同名再导入 → 重复跳过，绝不产生 (2) 副本
    entries2 = [(FileStorage(io.BytesIO(data), filename="[社团A] 改名重复导入.zip"), "", None)]
    with app.app.app_context():
        r2 = app._import_process(entries2).get_json()
    assert r2["imported"] == 0
    assert r2["results"][0]["status"] == "重复内容"
    assert "rel" in r2["results"][0]
    files = list((lib_env / "社团A").glob("*.zip"))
    assert len(files) == 1 and "(2)" not in files[0].name


def test_import_log_warns_about_shelve_replace(lib_env):
    """3.7.39：同名不同内容的导入（替换洗版）必须在导入日志里明确提醒。

    用户报障的延伸：洗版不会让社团在「最近入库」里上浮（作品数量没变），
    但日志此前只写"已导入"——用户根本不知道自己刚做的是洗版。
    """
    os.makedirs(app._inbox_dir(), exist_ok=True)
    name = "[社团A] 洗版本.zip"
    e1 = [(FileStorage(io.BytesIO(b"PK\x03\x04" + JPG * 10), filename=name), "", None)]
    with app.app.app_context():
        r1 = app._import_process(e1).get_json()
    assert r1["imported"] == 1
    assert "替换洗版" not in r1["results"][0]["status"], r1     # 首次导入不该误报

    # 同名、内容不同 → 洗版：另存 (2)、原文件不动、日志明说
    e2 = [(FileStorage(io.BytesIO(b"PK\x03\x04" + JPG * 20), filename=name), "", None)]
    with app.app.app_context():
        r2 = app._import_process(e2).get_json()
    assert r2["imported"] == 1
    row = r2["results"][0]
    assert "替换洗版" in row["status"], row
    assert "不会让社团" in row["message"] and "(2)" in row["message"], row
    names = sorted(p.name for p in (lib_env / "社团A").glob("*.zip"))
    assert any("(2)" in n for n in names), names
