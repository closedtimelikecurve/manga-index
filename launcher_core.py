# -*- coding: utf-8 -*-
"""launcher_core.py —— 启动面板的配置、常量、日志与全局状态（3.6.84 从 index_launcher.py 拆出）。

`index_launcher.py` 是 Index.exe 的第一入口（双击即开）。拆分前它是一个 1094 行的单文件：
配置/端口/Tailscale/进程启停/tkinter UI 全挤在一起，改 UI 也得读进程代码（3.6.84 拆成四个
模块，本模块是**最底层**——其余三个都 `import launcher_core as core`，不反向依赖）。

**APP_DIR 取 sys.argv[0] 而不是 `__file__`**：PyInstaller 冻结后 `__file__` 指向
_MEIPASS 临时解包目录，只有 argv[0] 才是 exe 真实所在目录（config.json / VERSION /
index.ico / app.py 都在那儿）。这一条是踩过的坑，不要"顺手改成 common.APP_DIR"。

全局状态（ST / PROC / UI_QUEUE / _recheck / PORT）只在这里定义；其它模块一律
`core.ST[...]`、`core.PORT = ...` 地读写，保证单点真源。
"""
import json
import os
import queue
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback

APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))

FROZEN = getattr(sys, "frozen", False)
CREATE_NO_WINDOW = 0x08000000

# ---------- 尺寸 ----------
W = 460
CARD_H, CARD_GAP = 92, 16
HEAD_H, HEAD_Y, GAP_HEAD, FOOT_H, FOOT_GAP, FOOT_MARGIN = 150, 20, 28, 50, 18, 16


def _panel_height(n_cards):
    return HEAD_Y + HEAD_H + GAP_HEAD + n_cards * (CARD_H + CARD_GAP) - CARD_GAP \
        + FOOT_GAP + FOOT_H + FOOT_MARGIN


# ---------- 基色（黑底白卡之高对比底） ----------
BLACK = "#000000"
BLACK2 = "#0b0b0b"
BLACK3 = "#161616"
WHITE = "#ffffff"
WHITE_SOFT = "#f4f4f4"
GRAY = "#cfcfcf"
GRAY_D = "#8f8f8f"
GRAY_EDGE = "#3a3a3a"
CARD = "#ffffff"          # 白色功能卡
TEXT = "#000000"          # 卡片内黑字
SUB_TEXT = "#4d4d4d"

# 品牌区状态文字（黑底上）：
STATUS_ON = "#6cff9b"     # 服务运行中（绿）
STATUS_OFF = "#e9e9e9"    # 服务未运行（亮灰白）
STATUS_BUSY = "#ffd600"   # 处理中 / 等待状态（小面积强调）

# ================= 可覆写面板配置（panel_config.json） =================
# 字段：
#   version       面板显示版本（缺省读同目录 VERSION 文件）
#   title/subtitle 品牌区两行文字
#   window_title  窗口标题
#   cards[]       卡片：id/title/subtitle/color(主题色)/icon(book|down|globe|wifi|restart|stop)
#                 args(传给 app.py 的命令行参数) 或 special("remote"=Tailscale 引导开关 |
#                 "restart"=重启正在运行的服务进程 | "stop"=停止服务)
_BUILTIN_CARDS = [
    dict(id="full", title="完整模式", subtitle="浏览文库 · 阅读器 · 全功能管理（启动即开浏览器）",
         color="#5b7cff", icon="book", args=["--host", "127.0.0.1"]),
    dict(id="test", title="测试模式",
         subtitle="完整本地服务，不自动打开浏览器；封面/页面图替换为占位符（截图审查防护）",
         color="#7c5bff", icon="wifi",
         args=["--host", "127.0.0.1", "--no-browser", "--safe-images"]),
    dict(id="import", title="仅导入模式", subtitle="只投递文件入文库，不开放浏览 / 阅读",
         color="#00a884", icon="down", args=["--import-only"]),
    dict(id="remote", title="远程访问模式", subtitle="局域网 / Tailscale 远程访问",
         color="#2f7cff", icon="globe", special="remote"),
    dict(id="restart", title="重启服务",
         subtitle="重启后台服务进程（改动后立即生效）",
         color="#f2a33c", icon="restart", special="restart"),
    dict(id="stop", title="停止服务", subtitle="结束后台运行的 Flask 服务",
         color="#e8515c", icon="stop", special="stop"),
]
_DEFAULT_ICONS = ["book", "down", "globe", "wifi", "restart", "stop"]
_DEFAULT_COLORS = ["#5b7cff", "#00a884", "#2f7cff", "#7c5bff", "#f2a33c", "#e8515c"]


def log_error(msg):
    # 3.7 Stage3：错误日志归入 _app/_logs/（此处 APP_DIR 取 sys.argv[0]，与打包路径一致，
    # 不能复用 common.APP_DIR——冻结后 common.__file__ 指向 _MEIPASS 而非 exe 目录）
    path = os.path.join(APP_DIR, "_logs", "Index_error.log")
    try:
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError:
        pass
    try:
        # 超 2MB 轮转为 .old（P3-5：此前只追加无限增长）
        if os.path.exists(path) and os.path.getsize(path) > 2 * 1024 * 1024:
            old = path + ".old"
            if os.path.exists(old):
                os.unlink(old)
            os.replace(path, old)
    except OSError:
        pass
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg.rstrip() + "\n")
    except Exception:
        pass


def _read_version_file():
    """面板版本（面板轴）：VERSION 文件为准，缺文件时用下面的兜底号（同步 app.py 的 PANEL_VERSION）。"""
    try:
        with open(os.path.join(APP_DIR, "VERSION"), "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "2.6.0"


def _theme_from(acc):
    """由主题色推导悬停/按下泛色（向白色混合），ring 用主题色本身。"""
    try:
        acc = acc if acc.startswith("#") else "#5b7cff"
        r, g, b = int(acc[1:3], 16), int(acc[3:5], 16), int(acc[5:7], 16)

        def mix(t):
            return "#%02x%02x%02x" % (int(r + (255 - r) * t),
                                      int(g + (255 - g) * t),
                                      int(b + (255 - b) * t))
        return dict(acc=acc, tint=mix(0.90), press=mix(0.78), ring=acc)
    except Exception:
        return dict(acc="#5b7cff", tint="#eef1ff", press="#dde3ff", ring="#5b7cff")


def _valid_card(c, i):
    """解析单张自定义卡：标题必填；special 与 args 至少有一个，否则这张卡点了没反应。"""
    if not isinstance(c, dict):
        return None
    title = str(c.get("title", "")).strip()
    if not title:
        return None
    special = c.get("special")
    special = special if special in ("remote", "restart", "stop") else None
    args = c.get("args")
    args = [str(x) for x in args] if isinstance(args, list) else []
    if not special and not args:
        return None
    return {"id": str(c.get("id") or title), "title": title,
            "subtitle": str(c.get("subtitle", "")).strip(),
            "color": str(c.get("color") or _DEFAULT_COLORS[i % len(_DEFAULT_COLORS)]),
            "icon": str(c.get("icon") or _DEFAULT_ICONS[i % len(_DEFAULT_ICONS)]),
            "args": args, "special": special}


def load_panel_config():
    """读 panel_config.json（可简单覆写）：合法字段覆盖内置默认，整卡无效则跳过。
    文件不存在 = 正常（用内置默认）；文件存在但解析失败 = 记一条日志再回退，
    否则用户"改了配置没生效"时只会看到卡片还是旧的，却不知道是自己写坏了 JSON。"""
    cards = [dict(c) for c in _BUILTIN_CARDS]
    cfg = {"version": _read_version_file(), "title": "Index",
           "subtitle": "本地同人志文库 · 服务控制台", "window_title": "", "cards": cards}
    path = os.path.join(APP_DIR, "panel_config.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _apply_strings(cfg, data)
                raw = data.get("cards")
                if isinstance(raw, list) and raw:
                    parsed = [x for x in (_valid_card(c, i) for i, c in enumerate(raw)) if x]
                    if parsed:
                        cfg["cards"] = parsed
        except Exception:
            log_error("panel_config.json 解析失败，已回退内置默认：\n" + traceback.format_exc())
    if not cfg["window_title"]:
        cfg["window_title"] = "Index v%s · 启动面板" % cfg["version"]
    return cfg


def _apply_strings(cfg, data):
    for k in ("version", "title", "subtitle", "window_title"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            cfg[k] = v.strip()


PANEL = load_panel_config()
CARDS = PANEL["cards"]
H = _panel_height(len(CARDS))

THEME_MAP = {c["id"]: _theme_from(c["color"]) for c in CARDS}


# ---------- 逻辑 ----------
def find_python():
    if not FROZEN:
        return sys.executable
    for name in ("pythonw.exe", "python.exe"):
        p = shutil.which(name)
        if p:
            return p
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("PROGRAMFILES", "")):
        if base:
            for name in ("pythonw.exe", "python.exe"):
                p = os.path.join(base, "Python", name)
                if os.path.exists(p):
                    return p
    return None


PY = find_python()


def load_port():
    try:
        with open(os.path.join(APP_DIR, "config.json"), "r", encoding="utf-8") as f:
            p = int(json.load(f).get("port", 8765))
            if 0 < p < 65536:
                return p
    except Exception:
        pass
    return 8765


REMOTE_PORT = 8766          # 远程服务专用端口（独立进程，与本地并行互不影响）


def local_port():
    """本地服务端口：8766 为远程专用，本地固定让位（config 漂移时指回 8765）。"""
    p = load_port()
    return 8765 if p == REMOTE_PORT else p


PORT = local_port()         # 本地服务端口（显示与本地启停检测均用此端口）


def load_token():
    try:
        with open(os.path.join(APP_DIR, "config.json"), "r", encoding="utf-8") as f:
            return str(json.load(f).get("token", "") or "").strip()
    except Exception:
        return ""


def _has_paired_devices():
    """`_state/pair_devices.json` 是否有设备记录（主令牌为空时用它决定要不要兜底生成）。"""
    try:
        with open(os.path.join(APP_DIR, "_state", "pair_devices.json"), encoding="utf-8") as f:
            data = json.load(f)
        return isinstance(data, dict) and bool(data)
    except Exception:
        return False


def ensure_remote_token():
    """远程模式启动前保证 config.json 已设置 token（P1-1）：为空则自动生成并写回。
    返回 (token, 是否新生成)。写入失败不阻塞 —— app.py 侧对 --host 0.0.0.0 仍有兜底。"""
    tk = load_token()
    if tk:
        return tk, False
    # 3.6.147：已有扫码配对的设备就能鉴权，不必再强制生成主令牌
    if _has_paired_devices():
        return "", False
    tk = "bks-" + secrets.token_hex(12)
    try:
        path = os.path.join(APP_DIR, "config.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if not isinstance(cfg, dict):
                cfg = {}
        except Exception:
            cfg = {}
        cfg["token"] = tk
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        # 写不进去 = app.py 起远程实例时读不到 token → 手机端会拿旧口令或空口令
        log_error("远程访问令牌写入 config.json 失败（本次令牌仅存在于内存）：\n"
                  + traceback.format_exc())
    return tk, True


TS_EXE = None
for _p in (r"C:/Program Files/Tailscale/tailscale.exe", shutil.which("tailscale")):
    if _p and os.path.exists(_p):
        TS_EXE = _p
        break

ST = {
    "remote": False,
    "tail_ip": "",
    "ts_url": "",
    "busy": False,
    "note": "",
}
PROC = {"local": None, "remote": None}   # 本地 / 远程 两个独立服务进程
UI_QUEUE = queue.Queue()
_recheck = threading.Event()


def ui(fn):
    UI_QUEUE.put(fn)


# 品牌区提示实现由 UI 层注入（canvas 创建后）；remote_launch 等后台线程经 set_note() 间接调用
_set_note_fn = None


def set_note(text):
    """远程等待授权等过程在品牌区显示提示（模块级入口，UI 线程内执行）。"""
    fn = _set_note_fn
    if fn is not None:
        try:
            fn(text or "")
        except Exception:
            log_error(traceback.format_exc())
