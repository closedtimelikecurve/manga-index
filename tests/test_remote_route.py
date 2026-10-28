# -*- coding: utf-8 -*-
"""远程服务启停端点（3.6.151）：/api/remote/state|start|stop 的分支与返回码。

真正起/杀进程的那一步在 `_spawn_detached` / `threading.Timer` 后面，测试里全部替换掉——
不允许在跑测试的机器上真的去拉起 8766 或把它杀掉。

两个必须钉住的语义：
  * 前端按返回的 `code` 翻 7 种语言，所以 code 是契约，别再改回只给中文 message；
  * `start` 在本进程就是 8766 时**必须拒绝**（code=self），否则用户会在远程页面上
    得到一个"点了没反应"的按钮（自启动等于自杀）。
"""
import pytest

import routes.remote as R


@pytest.fixture()
def spy(monkeypatch):
    """把监听探测 / 自身端口 / 起进程 / 延迟执行全部换成可控假件。

    Timer 只登记不执行：测试要能看到"动手"发生在那一次延迟回调里，而不是请求线程里。
    """
    st = {"listening": False, "selfPort": 8765, "spawn": [], "spawn_ok": True,
          "pending": []}

    def fake_spawn(code):
        st["spawn"].append(code)
        return st["spawn_ok"]

    class FakeTimer:
        """只记下 (delay, fn)，start() 不执行 fn——由测试自己调 fire()。"""

        def __init__(self, delay, fn):
            self.delay, self.fn = delay, fn
            st["pending"].append(self)

        def start(self):
            return None

    monkeypatch.setattr(R, "_listening", lambda port, host="127.0.0.1": st["listening"])
    monkeypatch.setattr(R, "_self_port", lambda: st["selfPort"])
    monkeypatch.setattr(R, "_spawn_detached", fake_spawn)
    monkeypatch.setattr(R.threading, "Timer", FakeTimer)
    return st


def _client():
    import app
    return app.app.test_client()


def test_state_reports_port_and_self_flag(spy):
    spy["listening"], spy["selfPort"] = True, 8766
    d = _client().get("/api/remote/state").get_json()
    assert d["ok"] and d["port"] == R.REMOTE_PORT
    assert d["running"] is True and d["isSelf"] is True and d["selfPort"] == 8766


def test_start_refuses_when_this_process_is_the_remote(spy):
    spy["selfPort"] = R.REMOTE_PORT
    r = _client().post("/api/remote/start")
    assert r.status_code == 400
    assert r.get_json()["code"] == "self"
    assert not spy["spawn"], "本进程就是 8766 时不该再起子进程"


def test_start_says_already_running_without_spawning(spy):
    spy["listening"] = True
    d = _client().post("/api/remote/start").get_json()
    assert d["code"] == "already_running" and not spy["spawn"]


def test_start_spawns_detached_remote_instance(spy):
    d = _client().post("/api/remote/start").get_json()
    assert d["code"] == "starting"
    assert len(spy["spawn"]) == 1
    code = spy["spawn"][0]
    assert "launcher_proc" in code and str(R.REMOTE_PORT) in code, code


def test_start_reports_spawn_failure(spy):
    spy["spawn_ok"] = False
    r = _client().post("/api/remote/start")
    assert r.status_code == 500 and r.get_json()["code"] == "spawn_failed"


def test_stop_when_not_running_is_a_noop(spy):
    d = _client().post("/api/remote/stop").get_json()
    assert d["code"] == "already_stopped" and not spy["spawn"] and not spy["pending"]


def test_stop_returns_first_then_kills_later(spy):
    """停止必须"先回包、后动手"：响应里带 delay，动手在 Timer 里。"""
    spy["listening"] = True
    d = _client().post("/api/remote/stop").get_json()
    assert d["code"] == "stopping" and d["delay"] >= 1
    assert not spy["spawn"], "不能在请求线程里直接杀进程（响应会发不出去）"
    assert len(spy["pending"]) == 1, "没有安排延迟执行"
    timer = spy["pending"][0]
    assert timer.delay >= 1
    timer.fn()                      # 触发那一次延迟动作
    assert "stop_remote" in spy["spawn"][0]