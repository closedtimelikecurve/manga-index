# -*- coding: utf-8 -*-
"""「最近入库」排序语义回归测试：只有**新增作品**才让社团排上来。

用户报告：只改了社团里某个作品的文件内容，那个社团就跑到列表最上面 —— 因为旧实现把
"更新时间"取成了「作品内容的 max mtime」。现在改用「作品数量是否增加」作判据：
  * 改内容 / 整包重写（删首页图片那种临时文件替换）/ 删作品 / 改名 → 不涨 → 时间不动
  * 任何途径新增一部作品 → 数量上涨 → 时间 = 现在
"""
import os
import sqlite3
import sys
import time
import zipfile

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
import meta_store  # noqa: E402

OLD = 1_600_000_000.0        # 用来当"很久以前入库"的锚点


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """两个社团：甲社 1 部、乙社 2 部。"""
    root = tmp_path / "lib"
    root.mkdir()

    def mkgroup(name, n):
        d = root / name
        d.mkdir()
        for i in range(1, n + 1):
            with zipfile.ZipFile(str(d / f"[{name}] 作品{i}.zip"), "w") as z:
                z.writestr("01.jpg", b"\xff\xd8 fake")
        return d

    mkgroup("甲社", 1)
    mkgroup("乙社", 2)
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    monkeypatch.setitem(app.CFG, "dissolved_circles", [])
    app.state.index_loaded = False
    app.state.index = {"v": 2, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    yield {"root": root, "甲社": root / "甲社", "乙社": root / "乙社"}
    app.state.index_keys.clear()


def _groups(c):
    return {g["name"]: g for g in c.get("/api/library").get_json()["groups"]}


def _bump_mtime(p, secs=100):
    """把 mtime 明确推后（不用 os.utime(p, None)：Windows 文件时间戳有 ~15.6ms tick 粒度）。"""
    st = os.stat(str(p))
    os.utime(str(p), (st.st_atime, st.st_mtime + secs))


def _age_circles(*names):
    """把这些分区的「首次登记时间」也回拨到 OLD —— 让"老分区 + 老入库记录"这个前提自洽。

    3.6.169 起「最近入库」会用 `circles.created_at` 纠正"回填形状"（`added_at == mtime`）
    的历史错值：分区今天才成立、记录却停在文件时间，就该记今天。本文件里这些用例
    只把索引的 `at` 设成 OLD，却让 `created_at` 留在"刚才首扫"的当下 —— 测试凭空造出
    "分区 1 秒前才登记、却说它很久以前入库"这种真实世界不存在的状态，于是纠正分支
    把 `at` 顶到现在。

    这一步**跨不跨秒**决定成败：回填的 mtime 与 `created_at` 落在同一整秒时纠正不触发、
    测试变绿，跨一秒就红。2026-10-30 公共仓库 CI 上 3.12 / 3.13 两个 job 一红一绿、
    本地连跑 5 次 2 绿 3 红，就是这么来的。回拨之后断言与实现口径一致，不再看运气。
    """
    if not names:
        return
    with sqlite3.connect(meta_store.DB_PATH) as db:
        db.executemany("UPDATE circles SET created_at=? WHERE name=?",
                       [(int(OLD), n) for n in names])
        db.commit()


def test_content_edit_does_not_bump(env):
    """只改作品文件内容（含"临时文件 + os.replace"整包重写，即删首页图片那种机制）→ 排序不动。"""
    app.get_library(force=True)
    c = app.app.test_client()
    before = _groups(c)["甲社"]
    before_at, before_content = before["updatedAt"], before["coverMtime"]

    zp = env["甲社"] / "[甲社] 作品1.zip"
    tmp = env["甲社"] / "rewrite.zip.tmp"
    with zipfile.ZipFile(str(tmp), "w") as z:          # 换掉内容、多一页（页数也变了）
        z.writestr("01.jpg", b"\xff\xd8 changed")
        z.writestr("02.jpg", b"\xff\xd8 extra")
    os.replace(str(tmp), str(zp))
    _bump_mtime(zp)                                     # 内容时间明显变新
    app.get_library(force=True)

    after = _groups(c)["甲社"]
    assert after["updatedAt"] == before_at, "只改作品内容不该改动入库时间"
    # 反证：内容时间确实变了（说明上一条不是"什么都没测到"）
    assert after["coverMtime"] > before_content
    assert after["workCount"] == 1


def test_new_work_bumps_and_sorts_first(env):
    """新增一部作品 → 入库时间前进到现在，并且按「最近入库」排序排到最前。"""
    app.get_library(force=True)
    c = app.app.test_client()
    n = _groups(c)["甲社"]["workCount"]
    # 3.6.154：社团排序的时间档按整秒比较，所以这里把**所有**社团都摆成很久以前入库，
    # 否则同一秒内新建的社团会按名称补位，"新增作品排第一"就测不出来了（真实场景里
    # 一次下载与上一次全量扫描至少差好几秒）。
    idx_groups = app.state.index.setdefault("groups", {})
    for name, cnt in ((k, v["workCount"]) for k, v in _groups(c).items()):
        idx_groups[name] = {"n": cnt, "at": OLD}
    _age_circles(*[k for k, v in _groups(c).items()])      # 分区成立时间也是"很久以前"
    app.get_library(force=True)
    assert _groups(c)["甲社"]["updatedAt"] == OLD                       # 数量没变 → 保持

    with zipfile.ZipFile(str(env["甲社"] / "[甲社] 新作品.zip"), "w") as z:
        z.writestr("01.jpg", b"\xff\xd8 fake")
    app.get_library(force=True)

    g = _groups(c)["甲社"]
    assert g["workCount"] == n + 1
    assert g["updatedAt"] > OLD + 3600, "新增作品必须把入库时间推到当前"
    assert abs(g["updatedAt"] - time.time()) < 600
    names = [x["name"] for x in c.get("/api/library?sort=updated&order=desc").get_json()["groups"]]
    assert names[0] == "甲社"


def test_delete_does_not_bump(env):
    """删掉一部作品（数量下降）→ 入库时间不动。"""
    app.get_library(force=True)
    c = app.app.test_client()
    n = _groups(c)["乙社"]["workCount"]
    app.state.index.setdefault("groups", {})["乙社"] = {"n": n, "at": OLD}
    _age_circles("乙社")
    app.get_library(force=True)
    os.unlink(str(env["乙社"] / "[乙社] 作品1.zip"))
    app.get_library(force=True)
    assert _groups(c)["乙社"]["updatedAt"] == OLD


def test_rename_does_not_bump(env):
    """改名（数量不变）→ 入库时间不动。"""
    app.get_library(force=True)
    c = app.app.test_client()
    n = _groups(c)["乙社"]["workCount"]
    app.state.index.setdefault("groups", {})["乙社"] = {"n": n, "at": OLD}
    _age_circles("乙社")
    app.get_library(force=True)
    os.rename(str(env["乙社"] / "[乙社] 作品1.zip"), str(env["乙社"] / "[乙社] 作品一（改名）.zip"))
    app.get_library(force=True)
    g = _groups(c)["乙社"]
    assert g["workCount"] == n and g["updatedAt"] == OLD


def test_first_scan_seeds_from_work_time_not_dir(env):
    """首次见到该社团（DB 里还没有 added_at）→ 初始化退回**作品内容时间**，不凭空跳到现在。

    历史：3.6.111 起用档案创建时间初始化，导致 updatedAt 与 createdAt 恒等，
    「最近入库」与「创建时间」排出来一模一样（3.6.151 改为优先取 DB 的 added_at，
    DB 里没有记录时才走这条退路）。"""
    # 首扫 = "首次建库回填"：清掉标记，让 db_sync 按历史近似（文件 mtime）写 added_at。
    # 不这么做的话，同一个测试库里前面的用例已经打过标，新作品会按"首次见到时刻"记，
    # 这条就测不到回填分支了。
    with sqlite3.connect(meta_store.DB_PATH) as db:
        db.execute("CREATE TABLE IF NOT EXISTS meta_kv(k TEXT PRIMARY KEY, v TEXT)")
        db.execute("DELETE FROM meta_kv WHERE k='backfill_done'")
        db.commit()
    app.state.index["works"] = {}
    app.state.index["groups"] = {}
    app.get_library(force=True)
    c = app.app.test_client()
    for g in _groups(c).values():
        # DB 里的 added_at 是整秒，coverMtime 是浮点——按整秒比
        assert int(g["updatedAt"]) == int(g["coverMtime"]), (g["name"], g["updatedAt"], g["coverMtime"])
    assert "groups" in app.state.index and set(app.state.index["groups"]) >= {"甲社", "乙社"}


def test_seed_uses_db_added_at_not_dir_created(env):
    """初始化基准必须是 DB 里该社团最新作品的 added_at，而不是档案（目录）创建时间。

    事故（2026-10-27 用户报障「最近入库的排序绝对出问题了」）：旧实现在索引记录缺失时
    用目录 ctime 播种，而导入新作品根本不推进目录 ctime —— 结果 742/742 个社团的
    updatedAt 恒等于 createdAt，「最近入库」和「创建时间」排出来一模一样，
    刚导入过作品的社团（实测 きのこのみ 有 10-27 的新作品）仍沉在第 654 位。
    """
    app.get_library(force=True)                       # 首扫：把 added_at 写进 DB
    c = app.app.test_client()
    # 把甲社的入库时间改成"很久以前"，再清掉索引记录（模拟升级迁移 / 换库后重来）
    with sqlite3.connect(meta_store.DB_PATH) as db:
        db.execute("UPDATE works SET added_at=? WHERE group_name='甲社'", (int(OLD),))
        db.commit()
    app.state.index["groups"] = {}
    app.get_library(force=True)

    g = _groups(c)["甲社"]
    assert g["updatedAt"] == OLD, "初始化没走 DB 的 added_at"
    assert g["updatedAt"] != g["createdAt"], "又退回成档案创建时间了（这正是用户报的那个 bug）"
    # 乙社没被改动：取它自己在 DB 里的最新 added_at（首扫回填 = 文件 mtime，接近现在）
    assert _groups(c)["乙社"]["updatedAt"] > OLD


def test_state_survives_index_reload(env):
    """入库记录要持久化：重载索引后再扫描，不能把已记录的时间重置掉。"""
    app.get_library(force=True)
    c = app.app.test_client()
    n = _groups(c)["甲社"]["workCount"]
    app.state.index.setdefault("groups", {})["甲社"] = {"n": n, "at": OLD}
    _age_circles("甲社")
    app.get_library(force=True)                        # 这一步把状态写进 library_index.json

    app.state.index_loaded = False                          # 模拟面板重启后重新加载索引
    app.state.index_keys.clear()
    app.get_library(force=True)
    assert _groups(c)["甲社"]["updatedAt"] == OLD, "重载索引后入库时间被重置了"


def test_prune_drops_vanished_circles(env):
    """社团消失后其入库记录要被清掉，不留垃圾状态。"""
    app.get_library(force=True)
    assert "乙社" in app.state.index.get("groups", {})
    for p in env["乙社"].glob("*.zip"):
        os.unlink(str(p))
    os.rmdir(str(env["乙社"]))
    app.get_library(force=True)
    assert "乙社" not in app.state.index.get("groups", {})

def test_new_circle_sorts_first(env):
    """新作品建出一个**全新分区** → 必须排到「最近入库」最前面（用户报障场景）。"""
    app.get_library(force=True)
    c = app.app.test_client()
    d = env["root"] / "丙社"
    d.mkdir()
    with zipfile.ZipFile(str(d / "[丙社] 新作品.zip"), "w") as z:
        z.writestr("01.jpg", b"fake-image-bytes")
    app.get_library(force=True)
    names = [x["name"] for x in c.get("/api/library?sort=updated&order=desc").get_json()["groups"]]
    assert names[0] == "丙社", names[:3]


def test_new_circle_with_old_file_time_still_sorts_first(env):
    """文件 mtime 是**旧的**（从别处复制/下载工具保留服务器时间），但它确实是刚入库的。

    「最近入库」认的必须是**入库时间**而不是文件时间——文件时间只说明"这个文件的
    内容是什么时候生成的"，说明不了"它什么时候进的库"。
    """
    app.get_library(force=True)
    c = app.app.test_client()
    d = env["root"] / "丁社"
    d.mkdir()
    zp = d / "[丁社] 老文件新入库.zip"
    with zipfile.ZipFile(str(zp), "w") as z:
        z.writestr("01.jpg", b"fake-image-bytes")
    os.utime(str(zp), (OLD, OLD))          # 文件名时间回拨到"很久以前"
    app.get_library(force=True)
    names = [x["name"] for x in c.get("/api/library?sort=updated&order=desc").get_json()["groups"]]
    assert names[0] == "丁社", names[:3]


def test_new_partition_with_backfilled_added_at_uses_partition_birth(env):
    """新分区 + 从别处移进来的老作品：`added_at == 文件 mtime` 时它不可信，要用分区成立时间。

    事故（2026-10-29 用户报障「WASABI 能排那么靠前，今天才设的三个分区却在后面」）：
    首建库回填把文件 mtime 直接抄进了 `added_at`，之后把老作品移进新目录
    （`_adopt_work_path` 保留 added_at），三个 10-29 新建的分区就卡在 10-22，
    排在 10-25 的 WASABI 后面。

    这里复刻那个形状：分区刚建（`circles.created_at` = 现在），作品是老文件
    （mtime 与 added_at 都是 OLD，两值相等 = 回填的记号）。
    """
    app.get_library(force=True)                       # 首扫：circles 记下分区成立时间
    c = app.app.test_client()
    d = env["root"] / "戊社"
    d.mkdir()
    zp = d / "[戊社] 老作品新分区.zip"
    with zipfile.ZipFile(str(zp), "w") as z:
        z.writestr("01.jpg", b"fake-image-bytes")
    app.get_library(force=True)

    # 把作品时间整体回拨成"很久以前"，added_at 与 mtime 同时改成同一个值（回填形状）
    os.utime(str(zp), (OLD, OLD))
    with sqlite3.connect(meta_store.DB_PATH) as db:
        db.execute("UPDATE works SET added_at=?, mtime=? WHERE group_name='戊社'",
                   (int(OLD), int(OLD)))
        db.commit()
    app.state.index["works"] = {}                     # 索引缓存也要重算（否则沿用旧 mtime）
    app.state.index["groups"] = {}                    # 模拟"这个分区索引里还没有"→ 走初始化分支
    # 其余分区都摆成很久以前入库（3.6.154：时间档按整秒比较，同秒会按名称补位，
    # 不这么做"新分区排第一"就测不出来）
    for name, cnt in ((k, v["workCount"]) for k, v in _groups(c).items() if k != "戊社"):
        app.state.index.setdefault("groups", {})[name] = {"n": cnt, "at": OLD}
    app.get_library(force=True)

    g = _groups(c)["戊社"]
    assert g["updatedAt"] > OLD + 86400, "回填的 added_at（=文件时间）被当成入库时间了"
    assert abs(g["updatedAt"] - time.time()) < 600, "应当取分区成立时间（刚建）"
    names = [x["name"] for x in c.get("/api/library?sort=updated&order=desc").get_json()["groups"]]
    assert names[0] == "戊社", names[:3]

