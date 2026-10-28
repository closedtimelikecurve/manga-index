"""index_launcher 的导入烟测与纯函数回归（3.6.84）。

为什么补这一层：启动面板曾是 **零测试** 模块（本文件就是为它补的网），却是用户双击的第一入口（Index.exe）；
它同时持有模块级状态（ST/PROC/PORT）与 tkinter UI，改动前必须先有一张能立刻变红的网。
这里只测「不起窗口也能判对错」的部分：配置兜底、配色推导、端口让位、netstat 解析、
Tailscale 状态映射、token 生成。UI 绘制用假 canvas 验证"图元必须带 tag"这一条。
"""
import pytest

pytest.importorskip("tkinter")          # 无 tk 的精简 Python 下跳过（面板本体在 Windows 桌面跑）

import index_launcher as L              # noqa: E402
import launcher_core as C
import launcher_proc as P


class FakeCanvas:
    """只记录调用：UI 图元必须带 tag，否则 draw_card 删不干净（面板越用越卡）。"""

    def __init__(self):
        self.calls = []

    def create_polygon(self, *a, **kw):
        self.calls.append(("polygon", kw))
        return 1

    def create_rectangle(self, *a, **kw):
        self.calls.append(("rect", kw))

    def create_line(self, *a, **kw):
        self.calls.append(("line", kw))

    def create_oval(self, *a, **kw):
        self.calls.append(("oval", kw))

    def create_text(self, *a, **kw):
        self.calls.append(("text", kw))

    def create_arc(self, *a, **kw):
        self.calls.append(("arc", kw))


def test_panel_height_grows_with_cards():
    assert L._panel_height(0) < L._panel_height(1) < L._panel_height(6)
    assert L.H == L._panel_height(len(L.CARDS))


def test_cards_have_required_fields():
    for c in L.CARDS:
        assert c["id"] and c["title"]
        assert c.get("special") in (None, "remote", "restart", "stop")
        if not c.get("special"):
            assert c.get("args"), c["id"]


def test_theme_from_color_and_bad_input():
    th = L._theme_from("#5b7cff")
    assert th["acc"] == "#5b7cff" and th["ring"] == "#5b7cff"
    bad = L._theme_from("not-a-color")
    assert bad["acc"] == "#5b7cff"


def test_load_panel_config_falls_back_to_builtin(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "APP_DIR", str(tmp_path))
    cfg = L.load_panel_config()
    assert cfg["title"] == "Index"
    assert [c["id"] for c in cfg["cards"]] == [c["id"] for c in L._BUILTIN_CARDS]
    assert cfg["window_title"].startswith("Index v")


def test_load_panel_config_overrides(monkeypatch, tmp_path):
    import json
    (tmp_path / "panel_config.json").write_text(json.dumps({
        "version": "9.9.9", "title": "自定义标题", "subtitle": "副标题",
        "cards": [
            {"id": "a", "title": "卡 A", "args": ["--import-only"], "color": "#123456"},
            {"title": "无参数卡"},                      # 既无 args 也无 special → 丢弃
            {"title": "远程", "special": "remote"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(C, "APP_DIR", str(tmp_path))
    cfg = L.load_panel_config()
    assert cfg["version"] == "9.9.9"
    assert cfg["title"] == "自定义标题"
    assert [c["title"] for c in cfg["cards"]] == ["卡 A", "远程"]
    assert cfg["cards"][0]["color"] == "#123456"
    assert cfg["window_title"] == "Index v9.9.9 · 启动面板"


def test_local_port_yields_remote_port(monkeypatch):
    monkeypatch.setattr(C, "load_port", lambda: L.REMOTE_PORT)
    assert L.local_port() == 8765
    monkeypatch.setattr(C, "load_port", lambda: 9001)
    assert L.local_port() == 9001


def test_netstat_local_addr_parsing():
    ok = "  TCP    127.0.0.1:8765         0.0.0.0:0              LISTENING       4321"
    ext = "  TCP    127.0.0.1:8765         127.0.0.1:51000        ESTABLISHED     4321"
    assert L._netstat_local_addr(ok) == "127.0.0.1:8765"
    assert L._netstat_local_addr(ext) is None
    assert L._netstat_local_addr("") is None


def test_ts_state_missing(monkeypatch):
    monkeypatch.setattr(C, "TS_EXE", None)
    assert L.ts_state() == ("missing", "", "Tailscale 未安装")


def test_ts_state_running(monkeypatch):
    monkeypatch.setattr(C, "TS_EXE", "tailscale.exe")
    monkeypatch.setattr(P, "run_ts", lambda args, timeout=15: (
        0, '{"BackendState": "Running", "Self": {"TailscaleIPs": ["100.64.0.7", "fd7a::1"]}}'))
    assert L.ts_state() == ("running", "100.64.0.7", "Tailscale 已连接")


def test_ts_state_needs_login(monkeypatch):
    monkeypatch.setattr(C, "TS_EXE", "tailscale.exe")
    monkeypatch.setattr(P, "run_ts", lambda args, timeout=15: (
        0, '{"BackendState": "NeedsLogin", "Self": {}}'))
    state, ip, msg = L.ts_state()
    assert state == "needs-login" and ip == "" and "登录" in msg


def test_ensure_remote_token_writes_config(monkeypatch, tmp_path):
    import json
    cfg = tmp_path / "config.json"
    cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(C, "APP_DIR", str(tmp_path))
    monkeypatch.setattr(C, "load_token", lambda: "")
    tk, generated = L.ensure_remote_token()
    assert generated and tk.startswith("bks-")
    assert json.loads(cfg.read_text(encoding="utf-8"))["token"] == tk


def test_draw_icon_tags_every_shape():
    cv = FakeCanvas()
    for kind in L._DEFAULT_ICONS:
        L._draw_icon(cv, kind, 20, 20, "#ffffff", "card0")
    assert cv.calls, "图标未绘制任何图元"
    assert all(c[1].get("tags") == "card0" for c in cv.calls), "有图元缺 tag，会导致删不干净"


def test_rr_rounds_within_bounds():
    cv = FakeCanvas()
    L._rr(cv, 0, 0, 100, 50, 999)          # 半径超过半高，必须被夹紧而不是画飞
    assert cv.calls and cv.calls[0][0] == "polygon"
