# -*- coding: utf-8 -*-
"""即时性 + 增补信息「整标题」模式回归测试。

覆盖：
  * 括号自动纠错（字段剥壳 / 成品名去嵌套去重复）
  * 增补信息逐字段模式：粘带括号的字段不再产出嵌套括号
  * 新增「整标题」模式：解析 → 规范化 → 按解析出的社团归档
  * /api/library/meta 的 rev：任何文库变动都要让安卓端能发现
  * /api/crawl/status 增量日志（since 游标）
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


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """文库：根/社团V（1 部作品）+ 根/待整理（1 部待整理的乱名作品）。"""
    root = tmp_path / "lib"
    circ = root / "社团V"
    circ.mkdir(parents=True)
    with zipfile.ZipFile(str(circ / "[社团V (画师名)] 已有作品.zip"), "w") as z:
        z.writestr("01.jpg", b"\xff\xd8 fake")
        z.writestr("02.jpg", b"\xff\xd8 fake")     # 两页：便于测「删首页图片」
    uncat = root / "待整理"
    uncat.mkdir()
    with zipfile.ZipFile(str(uncat / "乱标题.zip"), "w") as z:
        z.writestr("01.jpg", b"\xff\xd8 fake")
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    # 同进程里别的测试（解散社团）会把社团名写进共享的 CFG["dissolved_circles"]，
    # 这里清空以免本文件用到的「社团V」被当成已解散社团而降级
    monkeypatch.setitem(app.CFG, "dissolved_circles", [])
    app.state.index_loaded = False
    app.state.index = {"v": 2, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    yield {"root": root, "circ": circ, "uncat": uncat}
    app.state.index_keys.clear()


# ---------------------------------------------------------------- 括号自动纠错

def test_strip_wrappers_field_level():
    """字段层：粘进来的整段带括号值要剥壳，但不能剥掉内部括号或不成对的括号。"""
    assert dp.strip_wrappers("[蜂巢 (Apoidea)]") == "蜂巢 (Apoidea)"
    assert dp.strip_wrappers("((C102))") == "C102"
    assert dp.strip_wrappers("【汉化组】") == "汉化组"
    assert dp.strip_wrappers("[[x]]") == "x"
    assert dp.strip_wrappers("蜂巢 (Apoidea)") == "蜂巢 (Apoidea)"     # 本来就没壳
    assert dp.strip_wrappers("[a) 作品") == "[a) 作品"                 # 不成对 → 不动
    assert dp.strip_wrappers("[社团] [b]") == "[社团] [b]"             # 不是整段包裹 → 不动


def test_repair_name_no_nesting_no_dupes():
    assert dp.repair_name("[[蜂巢 (Apoidea)]]") == "[蜂巢 (Apoidea)]"
    assert dp.repair_name("((C102)) 作品") == "(C102) 作品"
    assert dp.repair_name("[社团 (个人)] 作品 (个人)") == "[社团 (个人)] 作品"
    assert dp.repair_name("[a (b) (b)] 标题") == "[a (b)] 标题"
    assert dp.repair_name("[汉化组] 作品 [汉化组]") == "[汉化组] 作品"
    assert dp.repair_name("[] 作品") == "作品"
    # 不误伤：两个社团各带同一画师是合法写法
    assert dp.repair_name("[社团A (画师)] [社团B (画师)] 作品") == "[社团A (画师)] [社团B (画师)] 作品"
    # 规范名过一遍纠错应保持不变（纠错对良好输入是恒等变换）
    good = "[無修正] (C102) [社团 (画师)] 作品 【汉化组】 (オリジナル)"
    assert dp.repair_name(good) == good
    assert dp.normalize_filename(good) == good


def test_supplement_info_never_nests(env):
    """逐字段模式：字段里粘带括号的值，产出的文件名不得出现嵌套/重复。"""
    app.get_library(force=True)
    c = app.app.test_client()
    j = c.post("/api/supplement-info", json={
        "group": "待整理", "work": "乱标题",
        "fields": {"event": "(C102)", "circle": "[社团W (画师W)]", "personal": "画师W",
                   "title": "作品名", "other_info": "[汉化组A] [汉化组A]"},
    }).get_json()
    assert j["ok"] is True, j
    name = j["newName"]
    assert "[[" not in name and "]]" not in name and "((" not in name, name
    assert name.count("(画师W)") == 1 and name.count("[汉化组A]") == 1, name
    assert "[社团W (画师W)]" in name and "(C102)" in name, name
    # 归档到解析出的社团目录
    assert (env["root"] / "社团W").is_dir(), os.listdir(env["root"])


# ---------------------------------------------------------------- 整标题模式

def test_supplement_title_parses_and_archives(env):
    """新模式：只给一整串完整标题 → 自动判定各部分词条 → 规范化 → 归档到社团。"""
    app.get_library(force=True)
    c = app.app.test_client()
    j = c.post("/api/supplement-title", json={
        "group": "待整理", "work": "乱标题",
        "title": "[社团V (画师名)] 新作品名 (C102) (オリジナル) 【汉化组】",
    }).get_json()
    assert j["ok"] is True, j
    assert j["circle"] == "社团V"
    name = j["newName"]
    assert "[[" not in name and "((" not in name, name
    assert "[社团V (画师名)]" in name and "新作品名" in name, name
    dest = env["circ"] / name
    assert dest.exists(), sorted(os.listdir(env["circ"]))
    assert not (env["uncat"] / "乱标题.zip").exists()          # 已搬走
    assert j["message"].startswith("「"), j["message"]          # 消息里带标准化结果


def test_supplement_title_unknown_circle_stays_uncat(env):
    """标题里没有社团括号 → 规范化后留在原社团（不擅自建档）。"""
    app.get_library(force=True)
    c = app.app.test_client()
    j = c.post("/api/supplement-title", json={
        "group": "待整理", "work": "乱标题", "title": "(C102) 只有标题的作品",
    }).get_json()
    assert j["ok"] is True, j
    assert j["circle"] == ""
    assert (env["uncat"] / j["newName"]).exists(), sorted(os.listdir(env["uncat"]))


def test_supplement_title_accepts_filename_with_ext(env):
    """允许直接粘贴带扩展名的完整文件名（不会被拼成 xxx.zip.zip）。"""
    app.get_library(force=True)
    c = app.app.test_client()
    j = c.post("/api/supplement-title", json={
        "group": "待整理", "work": "乱标题",
        "title": "[社团V (画师名)] 带扩展名.zip",
    }).get_json()
    assert j["ok"] is True, j
    assert j["newName"].endswith(".zip") and ".zip.zip" not in j["newName"], j["newName"]
    assert (env["circ"] / j["newName"]).exists()


# ---------------------------------------------------------------- 即时性：rev 与增量日志

def test_library_meta_rev_bumps_on_mutation(env):
    """任何文库变动都要递增 rev —— 安卓端靠它自动发现面板侧改动（不必手动下拉）。"""
    app.get_library(force=True)
    c = app.app.test_client()
    before = c.get("/api/library/meta").get_json()
    assert before["ok"] is True and isinstance(before["rev"], int)

    j = c.post("/api/supplement-title", json={
        "group": "待整理", "work": "乱标题", "title": "[社团V (画师名)] 变动测试",
    }).get_json()
    assert j["ok"] is True, j

    after = c.get("/api/library/meta").get_json()
    assert after["rev"] > before["rev"], (before, after)
    # 探针必须轻量：不返回社团数据
    assert "groups" not in after


def test_cover_version_changes_after_delete_cover(env, monkeypatch):
    """封面/页面缓存键（ver/coverVer）在删首页图片后必须变化，否则 APP 永远显示旧图。"""
    app.get_library(force=True)
    c = app.app.test_client()
    lib = c.get("/api/library").get_json()
    g = [x for x in lib["groups"] if x["name"] == "社团V"][0]
    ver_before = g["coverVer"]
    assert ver_before
    j = c.post("/api/delete-cover", json={
        "group": "社团V", "work": "[社团V (画师名)] 已有作品",
    }).get_json()
    if not j["ok"]:
        pytest.skip("当前环境无法重写压缩包：" + j.get("message", ""))
    lib2 = c.get("/api/library?refresh=1").get_json()
    g2 = [x for x in lib2["groups"] if x["name"] == "社团V"][0]
    assert g2["coverVer"] != ver_before


def test_crawl_status_incremental_log(tmp_path, monkeypatch):
    """3.6.38 #35：日志区只回传**本次运行**产生的行（历史不再展示）；
    since 游标只回传新行；日志被轮转/截断时游标自动归零重来。"""
    log = tmp_path / "crawl_log.txt"
    # 3.6.25：爬虫路径常量已拆到 services/crawl.py（字符串不可变），两个模块都要打桩
    import services.crawl as crawl_svc
    for mod in (app, crawl_svc):
        monkeypatch.setattr(mod, "_CRAWL_LOG_FILE", str(log))
        monkeypatch.setattr(mod, "_CRAWL_STATE_FILE", str(tmp_path / "nope.json"))
    # 历史内容：本次任务开始前就在文件里——3.6.38 起不得出现在前端日志区
    log.write_text("[09:00:00] 历史旧行\n", encoding="utf-8")
    c = app.app.test_client()

    # ① 任务未运行 → 不回传任何日志（历史也不给）
    j0 = c.get("/api/crawl/status").get_json()
    assert j0["logTail"] == [] and j0["logLines"] == []

    # ② 模拟任务运行中：假进程 + 记录本次起点（落在历史之后）
    class _Alive:
        pid = 4242
        def poll(self): return None
    monkeypatch.setitem(crawl_svc._CRAWL_TASKS["wnacg"], "proc", _Alive())
    monkeypatch.setitem(crawl_svc._CRAWL_TASKS["wnacg"], "startedAt", 1.0)
    monkeypatch.setitem(crawl_svc._CRAWL_TASKS["wnacg"], "log_cursor", os.path.getsize(log))
    with open(log, "a", encoding="utf-8") as f:
        f.write("[10:00:00] 第一行\n[10:00:01] 第二行\n")

    j = c.get("/api/crawl/status").get_json()
    assert j["logTail"] == ["[10:00:00] 第一行", "[10:00:01] 第二行"]    # 不含历史
    cursor = j["logCursor"]
    assert cursor == os.path.getsize(log)

    with open(log, "a", encoding="utf-8") as f:
        f.write("[10:00:02] 第三行\n")
    j2 = c.get(f"/api/crawl/status?since={cursor}").get_json()
    assert j2["logLines"] == ["[10:00:02] 第三行"]        # 只有新行
    assert j2["logCursor"] > cursor

    # 半行（还没写完）不计入
    with open(log, "a", encoding="utf-8") as f:
        f.write("[10:00:03] 半")
    j3 = c.get(f"/api/crawl/status?since={j2['logCursor']}").get_json()
    assert j3["logLines"] == [] and j3["logCursor"] == j2["logCursor"]

    # 日志被截断（轮转）→ 游标归零，从头重读
    log.write_text("[10:01:00] 新日志\n", encoding="utf-8")
    j4 = c.get(f"/api/crawl/status?since={j2['logCursor']}").get_json()
    assert j4["logLines"] == ["[10:01:00] 新日志"]


# ---------------------------------------------------------------- 3.6.11 逐字段模式：整标题内容全量入表 + 汉化组独立成栏

_FULL = ("[社团Y (画师Y)] 作品名 (C102) (オリジナル) 【汉化组Y】 "
         "[中国翻訳] [附加词条] (DL版)")


def _seed_full_title_work(env):
    d = env["root"] / "社团Y"
    d.mkdir(exist_ok=True)
    with zipfile.ZipFile(str(d / (_FULL + ".zip")), "w") as z:
        z.writestr("01.jpg", b"\xff\xd8 fake")
        z.writestr("02.jpg", b"\xff\xd8 fake")
    app.get_library(force=True)
    return "社团Y", _FULL


def test_parse_info_translator_and_full_other_info(env):
    """逐字段模式：汉化组单独成栏，「其他信息」必须含整标题里其余**全部**有效内容。
    3.6.11 前 other_info 只有待定词条，语言标记/其他括号都看不见也改不了。"""
    g, w = _seed_full_title_work(env)
    c = app.app.test_client()
    j = c.get("/api/parse-info", query_string={"group": g, "work": w}).get_json()
    assert j["ok"] is True, j
    assert j["translator"] == "汉化组Y", j
    for term in ("中国翻訳", "附加词条", "DL版"):
        assert term in (j["other_info"] or ""), f"「{term}」没进其他信息栏：{j['other_info']}"


def test_supplement_info_roundtrip_keeps_every_term(env):
    """原样提交（不动任何一栏）→ 整标题的每个有效段都还在，(DL版) 保持圆括号。"""
    g, w = _seed_full_title_work(env)
    c = app.app.test_client()
    info = c.get("/api/parse-info", query_string={"group": g, "work": w}).get_json()
    j = c.post("/api/supplement-info", json={
        "group": g, "work": w,
        "fields": {"event": info["event"], "circle": info["circle"],
                   "personal": info["personal"], "title": info["title"],
                   "original": info["original"], "translator": info["translator"],
                   "other_info": info["other_info"]},
    }).get_json()
    assert j["ok"] is True, j
    name = j["newName"]
    assert "[社团Y (画师Y)]" in name and "作品名" in name and "(C102)" in name
    assert "【汉化组Y】" in name, name
    assert "[中国翻訳]" in name, name
    assert "(DL版)" in name, name          # 原形态回填：圆括号不被改成方括号
    assert "[附加词条]" in name, name


def test_supplement_info_translator_editable(env):
    """汉化组可编辑：填新值即以新值为准（不再沿用自动解析的旧值）。"""
    g, w = _seed_full_title_work(env)
    c = app.app.test_client()
    info = c.get("/api/parse-info", query_string={"group": g, "work": w}).get_json()
    j = c.post("/api/supplement-info", json={
        "group": g, "work": w,
        "fields": {"title": info["title"], "translator": "新汉化组",
                   "other_info": info["other_info"]},
    }).get_json()
    assert j["ok"] is True, j
    assert "【新汉化组】" in j["newName"] and "【汉化组Y】" not in j["newName"], j["newName"]


# ---------------------------------------------------------------- 3.6.11 逐字段模式：整标题内容全量入表 + 汉化组独立成栏

_FULL = ("[社团Y (画师Y)] 作品名 (C102) (オリジナル) 【汉化组Y】 "
         "[中国翻訳] [附加词条] (DL版)")


def _seed_full_title_work(env):
    d = env["root"] / "社团Y"
    d.mkdir(exist_ok=True)
    with zipfile.ZipFile(str(d / (_FULL + ".zip")), "w") as z:
        z.writestr("01.jpg", b"\xff\xd8 fake")
        z.writestr("02.jpg", b"\xff\xd8 fake")
    app.get_library(force=True)
    return "社团Y", _FULL


def test_parse_info_translator_and_full_other_info(env):
    """逐字段模式：汉化组单独成栏，「其他信息」必须含整标题里其余**全部**有效内容。
    3.6.11 前 other_info 只有待定词条，语言标记/其他括号都看不见也改不了。"""
    g, w = _seed_full_title_work(env)
    c = app.app.test_client()
    j = c.get("/api/parse-info", query_string={"group": g, "work": w}).get_json()
    assert j["ok"] is True, j
    assert j["translator"] == "汉化组Y", j
    for term in ("中国翻訳", "附加词条", "DL版"):
        assert term in (j["other_info"] or ""), f"「{term}」没进其他信息栏：{j['other_info']}"


def test_supplement_info_roundtrip_keeps_every_term(env):
    """原样提交（不动任何一栏）→ 整标题的每个有效段都还在，(DL版) 保持圆括号。"""
    g, w = _seed_full_title_work(env)
    c = app.app.test_client()
    info = c.get("/api/parse-info", query_string={"group": g, "work": w}).get_json()
    j = c.post("/api/supplement-info", json={
        "group": g, "work": w,
        "fields": {"event": info["event"], "circle": info["circle"],
                   "personal": info["personal"], "title": info["title"],
                   "original": info["original"], "translator": info["translator"],
                   "other_info": info["other_info"]},
    }).get_json()
    assert j["ok"] is True, j
    name = j["newName"]
    assert "[社团Y (画师Y)]" in name and "作品名" in name and "(C102)" in name
    assert "【汉化组Y】" in name, name
    assert "[中国翻訳]" in name, name
    assert "(DL版)" in name, name          # 原形态回填：圆括号不被改成方括号
    assert "[附加词条]" in name, name


def test_supplement_info_translator_editable(env):
    """汉化组可编辑：填新值即以新值为准（不再沿用自动解析的旧值）。"""
    g, w = _seed_full_title_work(env)
    c = app.app.test_client()
    info = c.get("/api/parse-info", query_string={"group": g, "work": w}).get_json()
    j = c.post("/api/supplement-info", json={
        "group": g, "work": w,
        "fields": {"title": info["title"], "translator": "新汉化组",
                   "other_info": info["other_info"]},
    }).get_json()
    assert j["ok"] is True, j
    assert "【新汉化组】" in j["newName"] and "【汉化组Y】" not in j["newName"], j["newName"]
