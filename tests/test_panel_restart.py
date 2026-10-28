# -*- coding: utf-8 -*-
"""面板"代码已更新但没重启"的检测与一键重启回归测试。

背景：Python 只在启动时加载代码，改完 app.py 不重启就不生效 —— 用户两次遇到"改了却没生效"
（最近一次是收件箱空目录仍报 404）。这里钉住三件事：
  1. 检测逻辑：本进程启动时刻 vs 关键文件 mtime；
  2. /api/config 暴露 needsRestart / diskVersion（网页据此提示）；
  3. 一键重启接口的三条分支：无需重启 / 自检失败拒绝 / 正常调度重启。
注意：测试里**绝不能**真的执行重启（会把 pytest 进程替换掉），所以 _schedule_exec 一律打桩。
"""
import os
import sys
import time

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402


def test_disk_version_matches_panel_version():
    """磁盘 VERSION 与本进程 PANEL_VERSION 必须一致（不一致正说明代码更新了没重启）。"""
    with open(os.path.join(PROG_DIR, "VERSION"), "r", encoding="utf-8") as f:
        assert f.read().strip() == app.PANEL_VERSION
    assert app._disk_panel_version() == app.PANEL_VERSION


def test_needs_restart_detection(monkeypatch):
    """进程启动时刻晚于文件 mtime → 不需要重启；反之 → 需要（这就是"改了没重启"的判据）。"""
    monkeypatch.setattr(app, "_PROC_START", time.time() + 3600)      # 假装进程刚起来
    assert app._panel_needs_restart() is False
    monkeypatch.setattr(app, "_PROC_START", 0)                       # 假装进程很老
    assert app._panel_needs_restart() is True


def test_config_exposes_restart_state(monkeypatch):
    c = app.app.test_client()
    j = c.get("/api/config").get_json()
    assert "needsRestart" in j and "diskVersion" in j
    assert j["diskVersion"] == app.PANEL_VERSION

    monkeypatch.setattr(app, "_PROC_START", 0)                       # 模拟"代码已更新未重启"
    j2 = c.get("/api/config").get_json()
    assert j2["needsRestart"] is True
    assert c.get("/api/library/meta").get_json()["needsRestart"] is True


def test_restart_noop_when_up_to_date(monkeypatch):
    """已经是最新代码 → 直接返回"无需重启"，不触发任何重启动作。"""
    monkeypatch.setattr(app, "_PROC_START", time.time() + 3600)
    called = []
    monkeypatch.setattr(app, "_schedule_exec", lambda d=0.8: called.append(d))
    c = app.app.test_client()
    j = c.post("/api/panel/restart").get_json()
    assert j["ok"] is True and "无需重启" in j["message"]
    assert called == []


def test_restart_refused_when_new_code_broken(monkeypatch):
    """新代码自检不过 → 拒绝重启（否则会重启成一个起不来的进程）。"""
    monkeypatch.setattr(app, "_PROC_START", 0)
    monkeypatch.setattr(app, "_validate_fresh_code", lambda timeout=120: (False, "SyntaxError: boom"))
    called = []
    monkeypatch.setattr(app, "_schedule_exec", lambda d=0.8: called.append(d))
    c = app.app.test_client()
    r = c.post("/api/panel/restart")
    assert r.status_code == 500
    j = r.get_json()
    assert j["ok"] is False and "SyntaxError: boom" in j["message"]
    assert called == []


def test_restart_schedules_when_stale_and_valid(monkeypatch):
    """代码已更新且自检通过 → 调度一次重启（测试里打桩，绝不真的 execv）。"""
    monkeypatch.setattr(app, "_PROC_START", 0)
    monkeypatch.setattr(app, "_validate_fresh_code", lambda timeout=120: (True, ""))
    called = []
    monkeypatch.setattr(app, "_schedule_exec", lambda d=0.8: called.append(d))
    c = app.app.test_client()
    j = c.post("/api/panel/restart").get_json()
    assert j["ok"] is True and "重启" in j["message"]
    assert len(called) == 1 and called[0] <= 1.0


def test_validate_fresh_code_rejects_broken_module(tmp_path, monkeypatch):
    """自检真的会跑子进程 import：坏代码必须被抓住、好代码必须放行。"""
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "app.py").write_text("def f(:\n", encoding="utf-8")
    monkeypatch.setattr(app, "APP_DIR", str(broken))
    ok, err = app._validate_fresh_code()
    assert ok is False and err

    good = tmp_path / "good"
    good.mkdir()
    (good / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(app, "APP_DIR", str(good))
    ok2, err2 = app._validate_fresh_code()
    assert ok2 is True and err2 == ""
