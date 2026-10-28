# -*- coding: utf-8 -*-
"""外接下载器任务（3.6.155 ext）：通用命令模板 → 子进程 → zip 落收件箱。

守住四条契约：
  1. ext 任务**跳过锁定/封面阶段**——条目本身就是命令参数，直接进下载
     （LOCKERS 里没有 "ext" 项：若误走锁定阶段会 KeyError → 任务异常终止，测试即红）；
  2. 产物（文件/文件夹）打包成 store 级 zip 落收件箱，zip 名来自净化后的词条行，
     收件箱同步能把它登记成待确认项；
  3. 失败（退出码非 0 / 超时 / 取消）清掉暂存、词条留在清单里待重试；
  4. 工具表来自 config.json 的 ext_downloaders：坏项丢弃好项保留，未配置给引导文案。
"""
import os
import sys
import time
import zipfile

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import common  # noqa: E402
import app  # noqa: E402
from services import crawl_run, crawl_fetch  # noqa: E402
from services import crawl as crawl_svc  # noqa: E402


def _wait(kind, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        s = crawl_run.status(kind)
        if not s["running"]:
            return s
        time.sleep(0.02)
    raise AssertionError("任务在 %.1fs 内没有结束" % timeout)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """隔离清单/断点/日志/收件箱；工具表 monkeypatch 注入（绝不写真实 config.json）。"""
    lst = tmp_path / "ext_list.txt"
    lst.write_text("", encoding="utf-8")
    for attr in ("_CRAWL_LOG_FILE_EXT", "_CRAWL_LOG_FILE"):
        monkeypatch.setattr(crawl_svc, attr, str(tmp_path / ("log_" + attr + ".txt")))
    monkeypatch.setattr(crawl_run, "_list_paths", lambda kind: [str(lst)])
    monkeypatch.setattr(crawl_run, "_state_path", lambda kind: str(tmp_path / "state.json"))
    monkeypatch.setattr(crawl_run, "_JOBS",
                        {k: crawl_run._blank(k) for k in crawl_run.KINDS})
    # 收件箱指到 conftest 已隔离的 app._inbox_dir()（dl_ext 的 inbox_dir 是独立入口，单独打桩）
    monkeypatch.setattr(crawl_fetch, "inbox_dir", lambda: app._inbox_dir())
    tools = []
    monkeypatch.setattr(crawl_fetch, "ext_tools", lambda: tools)
    return {"list": lst, "tools": tools}


def _add_tool(env, tmp_path, body, name="faketool", timeout=0):
    script = tmp_path / ("fake_tool_%d.py" % len(env["tools"]))
    script.write_text(body, encoding="utf-8")
    env["tools"].append({
        "name": name,
        "cmd": '%s "%s" "{dest}" "{url}"' % (sys.executable, script),
        "timeout": timeout})


_BODY_OK = """\
import os, sys
dest, url = sys.argv[1], sys.argv[2]
sub = os.path.join(dest, "gallery")
os.makedirs(sub, exist_ok=True)
with open(os.path.join(sub, "001.jpg"), "wb") as f:
    f.write(b"FAKE-" + url.encode())
"""
_BODY_FAIL = "import sys; sys.exit(3)"
_BODY_SLOW = "import time; time.sleep(8)"


def _run_ext(env, tmp_path, entry, body=_BODY_OK, timeout=0):
    """加假工具 → 写单行清单 → 启动 ext 任务 → 等结束。"""
    _add_tool(env, tmp_path, body, timeout=timeout)
    env["list"].write_text(entry + "\n", encoding="utf-8")
    assert crawl_run.start("ext")["ok"]
    return _wait("ext")


def test_ext_task_zips_artifact_into_inbox(env, tmp_path):
    """成功链路：跳过锁定 → 工具产出文件夹 → zip 落收件箱 → 清单移除、暂存清空。"""
    s = _run_ext(env, tmp_path, "https://gal.example/g/1/abc/")
    assert s["done"] == 1 and s["failed"] == 0 and s["phase"] == "done", s
    assert s["items"][0]["state"] == "ok"
    zips = [n for n in os.listdir(app._inbox_dir()) if n.endswith(".zip")]
    assert zips == ["https gal.example g 1 abc.zip"], zips     # 词条行净化成 zip 名
    assert env["list"].read_text(encoding="utf-8").strip() == ""
    stage_root = os.path.join(app._inbox_dir(), "_ext_stage")
    assert os.listdir(stage_root) == []                        # 暂存全清（rmtree 后只剩空根）


def test_ext_zip_is_store_level_with_page(env, tmp_path):
    """zip 内容：相对路径保留目录结构、store 级（不压缩）、页面字节完整。"""
    _run_ext(env, tmp_path, "https://gal.example/g/1/abc/")
    path = os.path.join(app._inbox_dir(), "https gal.example g 1 abc.zip")
    with zipfile.ZipFile(path) as zf:
        assert zf.namelist() == ["gallery/001.jpg"]
        assert zf.getinfo("gallery/001.jpg").compress_type == zipfile.ZIP_STORED
        assert zf.read("gallery/001.jpg") == b"FAKE-https://gal.example/g/1/abc/"


def test_zip_registers_into_inbox(env, tmp_path, monkeypatch):
    """落进收件箱的 zip 必须能被既有收件箱同步登记成待确认项（与手动导入同一条管线）。"""
    _run_ext(env, tmp_path, "画廊一号")
    # 与 test_inbox 的 lib_env 同款最小环境：_inbox_sync 里的无归属收集与提案要读库状态
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    monkeypatch.setitem(app.CFG, "root", str(tmp_path / "lib"))
    monkeypatch.setitem(app.CFG, "token", "")
    app.state.index_loaded = False
    app.state.index = {"v": 3, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    monkeypatch.setattr(app, "_unfiled_collect", lambda: None)
    app._inbox_sync()
    rows = list(app.meta.inbox_list())
    assert any(r["name"] == "画廊一号.zip" and r["state"] == "pending" for r in rows), rows


def test_failed_tool_keeps_entry_in_list(env, tmp_path):
    """退出码非 0：单条失败、详情进条目 msg，词条留在清单里待重试。"""
    s = _run_ext(env, tmp_path, "词条X", body=_BODY_FAIL)
    assert s["failed"] == 1 and s["done"] == 0
    assert "退出码 3" in s["items"][0]["msg"]
    assert env["list"].read_text(encoding="utf-8").strip() == "词条X"


def test_tool_timeout_kills_subprocess(env, tmp_path):
    """超时：终止子进程并报"超时"，整条耗时明显小于工具自身的睡眠时长。"""
    t0 = time.time()
    s = _run_ext(env, tmp_path, "slow", body=_BODY_SLOW, timeout=1)
    assert time.time() - t0 < 8
    assert "超时" in s["items"][0]["msg"]


def test_cancel_kills_running_tool(env, tmp_path):
    """取消：rt.cancelled 回调为真时终止子进程（不打出 zip）。"""
    _add_tool(env, tmp_path, _BODY_SLOW, timeout=60)
    t0 = time.time()
    ok, msg = crawl_fetch.dl_ext({"entry": "slow"}, None,
                                 rt={"cancelled": lambda: True})
    assert not ok and msg == "已取消"
    assert time.time() - t0 < 8
    zips = [n for n in os.listdir(app._inbox_dir()) if n.endswith(".zip")]
    assert zips == []


def test_unconfigured_tool_fails_with_hint(env):
    """未配置工具：条目失败并带引导文案（用户知道去 config.json 配什么）。"""
    env["list"].write_text("x\n", encoding="utf-8")
    crawl_run.start("ext")
    s = _wait("ext")
    assert s["failed"] == 1
    assert "未配置外接下载器" in s["items"][0]["msg"]


def test_tool_naming_falls_back_to_first(env):
    """网页端不传工具名 / 传了不存在的名字 → 回退配置里的第一个。"""
    env["tools"].append({"name": "b", "cmd": "b {url}", "timeout": 0})
    env["tools"].append({"name": "a", "cmd": "a {url}", "timeout": 0})
    assert crawl_fetch.ext_pick_tool("")[0]["name"] == "b"
    assert crawl_fetch.ext_pick_tool("不存在")[0]["name"] == "b"
    assert crawl_fetch.ext_pick_tool("a")[0]["name"] == "a"


def test_config_tool_validation():
    """_apply_ext_downloaders：坏项丢弃好项保留；timeout 非法回 0；无 {url} 的命令无效。"""
    cfg: dict = {}
    common._apply_ext_downloaders(cfg, {"ext_downloaders": [
        {"name": "good", "cmd": "tool -d {dest} {url}", "timeout": "30"},
        {"name": "nourl", "cmd": "tool -d {dest}"},          # 缺 {url} → 丢
        {"name": "", "cmd": "tool {url}"},                   # 缺名字 → 丢
        "junk",                                              # 形状不对 → 丢
        {"name": "badtimeout", "cmd": "t {url}", "timeout": "abc"},  # timeout 回 0
    ]})
    out = cfg["ext_downloaders"]
    assert [t["name"] for t in out] == ["good", "badtimeout"]
    assert out[0]["timeout"] == 30 and out[1]["timeout"] == 0


def test_safe_name_and_unique():
    """zip 名净化：Windows 非法字符换空格、首尾点空剥掉；重名让位 (2)。"""
    assert crawl_fetch._ext_safe_name('a<b>:"/\\|?*b') == "a b b"
    assert crawl_fetch._ext_safe_name("  标题... ") == "标题"
    assert crawl_fetch._ext_safe_name("") .startswith("ext-")
    import tempfile
    d = tempfile.mkdtemp()
    p1 = os.path.join(d, "x.zip")
    open(p1, "w").close()
    assert crawl_fetch._ext_unique(p1).endswith("x(2).zip")
