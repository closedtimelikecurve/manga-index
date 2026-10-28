# -*- coding: utf-8 -*-
"""launcher_ui.py —— 启动面板的 tkinter 视图与交互（3.6.84 从 index_launcher.py 拆出）。

面板是「一块 Canvas 画出来的黑底白卡」，没有控件树：
  * `build()` 一次性建窗口/字体/画布/品牌区/卡片，返回 root；
  * `draw_card(i, state)` 每次状态变化就整张重画（按 tag 删旧图元）；
  * `poll_tick` 每 3 秒在后台线程探测两个端口，结果经 `core.ui()` 回主线程渲染。

**所有图元必须带 tag**：draw_card 靠 `cv.delete(tag)` 清理，漏 tag 会让图元永久堆积
（面板越用越卡，是 3.6.26 修过的老 bug）。三秒轮询**不能**在读状态时碰 tk 对象，
必须 `root.after` 回主线程 —— 否则 Tcl 会随机崩。

业务动作（启停/重启/Tailscale）全在 launcher_proc，这里只负责调用与展示。
"""
import os
import queue
import threading
import tkinter as tk
import traceback
from tkinter import font as tkfont

import launcher_core as core
import launcher_proc as proc

_UI = {"cv": None, "f": None, "bounds": [], "hovered": -1, "pressed": -1}


# ================= 基础图元 =================
def _rr(cv, x1, y1, x2, y2, r, **kw):
    """圆角矩形（Canvas 图元）。3.6.26 自 main() 提取——原本嵌在 393 行的 main 里，
    只依赖 cv，提取后 main 少一层嵌套。"""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
           x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


def _draw_icon(cv, kind, cx, cy, col, tag):
    """图标图元必须带 tag：draw_card 按 tag 删旧图元，缺 tag 会导致图元永久堆积（面板越用越卡）。"""
    w = 3
    if kind == "book":
        cv.create_rectangle(cx - 15, cy - 13, cx - 3, cy + 13,
                            outline=col, width=w, tags=tag)
        cv.create_rectangle(cx + 3, cy - 13, cx + 15, cy + 13,
                            outline=col, width=w, tags=tag)
        cv.create_line(cx, cy - 13, cx, cy + 13, fill=col, width=w, tags=tag)
    elif kind == "down":
        cv.create_line(cx, cy - 11, cx, cy + 9, fill=col, width=w, tags=tag)
        cv.create_line(cx - 9, cy + 1, cx, cy + 10, fill=col, width=w, tags=tag)
        cv.create_line(cx + 9, cy + 1, cx, cy + 10, fill=col, width=w, tags=tag)
        cv.create_line(cx - 12, cy + 13, cx + 12, cy + 13, fill=col, width=w, tags=tag)
    elif kind == "globe":
        cv.create_oval(cx - 13, cy - 13, cx + 13, cy + 13, outline=col, width=w, tags=tag)
        cv.create_line(cx - 13, cy, cx + 13, cy, fill=col, width=2, tags=tag)
        cv.create_oval(cx - 6, cy - 13, cx + 6, cy + 13, outline=col, width=2, tags=tag)
    elif kind == "wifi":
        cv.create_arc(cx - 13, cy - 6, cx + 13, cy + 20, start=20, extent=140,
                      style="arc", outline=col, width=w, tags=tag)
        cv.create_arc(cx - 8, cy - 1, cx + 8, cy + 15, start=20, extent=140,
                      style="arc", outline=col, width=w, tags=tag)
        cv.create_oval(cx - 2, cy + 9, cx + 2, cy + 13, fill=col, outline="", tags=tag)
    elif kind == "restart":
        cv.create_arc(cx - 13, cy - 13, cx + 13, cy + 13, start=40, extent=290,
                      style="arc", outline=col, width=w, tags=tag)
        cv.create_polygon(cx + 4, cy - 16, cx + 15, cy - 11, cx + 3, cy - 5,
                          fill=col, outline="", tags=tag)
    else:                                        # stop
        cv.create_rectangle(cx - 11, cy - 11, cx + 11, cy + 11,
                            outline=col, width=w, tags=tag)
        cv.create_line(cx - 6, cy - 6, cx + 6, cy + 6, fill=col, width=w, tags=tag)
        cv.create_line(cx - 6, cy + 6, cx + 6, cy - 6, fill=col, width=w, tags=tag)


# ================= 窗口与静态层 =================
def _init_window():
    root = tk.Tk()
    root.title(core.PANEL["window_title"])
    root.geometry(f"{core.W}x{core.H}")
    root.resizable(False, False)
    root.configure(bg=core.BLACK)
    try:
        root.iconbitmap(os.path.join(core.APP_DIR, "index.ico"))
    except Exception:
        pass
    _dark_titlebar(root)
    return root


def _dark_titlebar(root):
    """Windows 10/11 标题栏暗色。"""
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetAncestor(root.winfo_id(), 2)
        v = ctypes.c_int(1)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(v), ctypes.sizeof(v)) == 0:
                break
    except Exception:
        pass


def _make_fonts(root):
    """黑底白卡，用粗黑高清字体。"""
    fam = "Microsoft YaHei UI"
    try:
        tkfont.Font(root=root, family=fam, size=9)
    except Exception:
        fam = "Microsoft YaHei"
    return {
        "brand": tkfont.Font(root=root, family=fam, size=26, weight="bold"),
        "sub": tkfont.Font(root=root, family=fam, size=11),
        "head": tkfont.Font(root=root, family=fam, size=13, weight="bold"),
        "card": tkfont.Font(root=root, family=fam, size=16, weight="bold"),
        "card_sub": tkfont.Font(root=root, family=fam, size=10),
        "status": tkfont.Font(root=root, family=fam, size=10, weight="bold"),
        "arrow": tkfont.Font(root=root, family=fam, size=22, weight="bold"),
        "small": tkfont.Font(root=root, family=fam, size=9),
    }


def _make_canvas(root):
    cv = tk.Canvas(root, width=core.W, height=core.H, bg=core.BLACK, highlightthickness=0)
    cv.pack()
    _paint_backdrop(cv)
    return cv


def _paint_backdrop(cv):
    """纯黑（带极浅微渐变，避免刺眼）；PIL 缺席时退回纯色矩形。"""
    try:
        from PIL import Image as _Im
        from PIL import ImageTk as _ImTk
        col = _Im.new("RGB", (1, core.H))
        px = col.load()
        for y in range(core.H):
            v = int(0 + (y / float(core.H - 1)) * 20)  # 0 → 20 深灰黑
            px[0, y] = (v, v, v)
        bg = _ImTk.PhotoImage(col.zoom(core.W, 1))
        cv.create_image(0, 0, image=bg, anchor="nw")
        cv._bg_keep = [bg]
    except Exception:
        cv.create_rectangle(0, 0, core.W, core.H, fill=core.BLACK, outline="")


def _draw_brand(cv, f):
    """品牌区（黑底白字，文案来自 panel_config.json 可覆写）。"""
    y1 = core.HEAD_Y
    y2 = y1 + core.HEAD_H
    _rr(cv, 24, y1, core.W - 24, y2, 20, fill=core.BLACK2, outline=core.GRAY_EDGE, width=1)
    mid = (24 + core.W - 24) / 2
    cv.create_text(mid, y1 + 46, text=core.PANEL["title"], fill=core.WHITE, font=f["brand"])
    cv.create_text(mid, y1 + 92, text=core.PANEL["subtitle"], fill=core.GRAY, font=f["sub"])
    cv.create_text(mid, y1 + 122, text="○  正在检测服务…", fill=core.WHITE_SOFT,
                   font=f["head"], tags="st_main")
    cv.create_text(mid, y1 + 140, text="", fill=core.GRAY, font=f["small"], tags="st_remote")


def _card_bounds(n):
    gw = core.W - 48
    gh, gap = core.CARD_H, core.CARD_GAP
    gx = 24
    gy = core.HEAD_Y + core.HEAD_H + core.GAP_HEAD
    return [(gx, gy + i * (gh + gap), gx + gw, gy + i * (gh + gap) + gh) for i in range(n)]


def _draw_footer(cv, f, last_bottom):
    fy = last_bottom + 18
    _rr(cv, 24, fy, core.W - 24, fy + 50, 14, fill=core.BLACK2, outline=core.GRAY_EDGE, width=1)
    cv.create_text(core.W / 2, fy + 18, text="关闭窗口不会停止服务",
                   fill=core.GRAY, font=f["card_sub"])
    cv.create_text(core.W / 2, fy + 37, text="可用下方「停止服务」卡片结束后台进程",
                   fill=core.GRAY_D, font=f["small"])


# ================= 卡片绘制 =================
def _card_paint(state, th):
    """状态 → (底色, 描边色, 描边宽)。"""
    if state == "on":
        return th["press"], th["ring"], 3
    if state == "hover":
        return th["tint"], th["ring"], 3
    if state == "press":
        return th["press"], "#000000", 2
    return core.CARD, core.GRAY_EDGE, 1


def draw_card(i, state):
    cv, f = _UI["cv"], _UI["f"]
    x1, y1, x2, y2 = _UI["bounds"][i]
    card = core.CARDS[i]
    th = core.THEME_MAP[card["id"]]
    acc = th["acc"]
    tag = f"card{i}"
    cv.delete(tag)
    is_remote = (card.get("special") == "remote")
    # 远程运行中也像“开启的开关”：整卡保持高亮并显示运行信息
    if is_remote and core.ST["remote"]:
        state = "on"
    fill, line, linew = _card_paint(state, th)
    # 卡片底（白 / 主题泛色），下方叠加主题色左缘竖带、图标、文字
    _rr(cv, x1, y1, x2, y2, 18, fill=fill, outline=line, width=linew, tags=tag)
    # 左侧主题色竖带（比描边更醒目，作为该选项卡的主色标识）
    cv.create_rectangle(x1 + 2, y1 + 14, x1 + 8, y2 - 14, fill=acc, outline="", tags=tag)
    _draw_card_body(cv, f, card, x1, y1, acc, tag)
    _draw_card_tail(cv, f, x1, x2, y1, y2, th, tag, is_remote, state)


def _draw_card_body(cv, f, card, x1, y1, acc, tag):
    """图标（主题色）+ 标题（黑高清字）+ 说明，并肩放在图标右侧、卡片竖直居中偏上。"""
    ty = y1 + 46
    _draw_icon(cv, card["icon"], x1 + 66, ty, acc, tag)
    tx = x1 + 120
    cv.create_text(tx, y1 + 36, text=card["title"], anchor="w",
                   fill=core.TEXT, font=f["card"], tags=tag)
    cv.create_text(tx, y1 + 64, text=card["subtitle"], anchor="w",
                   fill=core.SUB_TEXT, font=f["card_sub"], tags=tag)


def _draw_card_tail(cv, f, x1, x2, y1, y2, th, tag, is_remote, state):
    """右侧开关药丸（远程卡）/ 箭头，以及悬停时的操作提示。"""
    ty = y1 + 46
    pill_x2 = x2 - 22
    if is_remote:
        on_now = core.ST["remote"]
        cv.create_rectangle(pill_x2 - 42, ty - 13, pill_x2, ty + 13,
                            fill=th["press"] if on_now else core.BLACK2,
                            outline=th["ring"] if on_now else core.GRAY_D, width=2,
                            tags=tag)
        cv.create_text(pill_x2 - 21, ty, text="开" if on_now else "关",
                       fill=(th["ring"] if on_now else "#b0b0b0"),
                       font=f["status"], tags=tag)
        if state in ("hover", "on"):
            cv.create_text(x1 + 30, y2 - 14,
                           text=("点击关闭远程服务" if core.ST["remote"] else "点击开启远程服务"),
                           anchor="w", fill=core.GRAY_D, font=f["small"], tags=tag)
    else:
        # 右侧箭头（主题色），表示“点按进入”
        cv.create_text(pill_x2, ty, text="›", fill=th["acc"], font=f["arrow"], tags=tag)


def sync():
    for i in range(len(core.CARDS)):
        state = ("press" if i == _UI["pressed"]
                 else ("hover" if i == _UI["hovered"] else "normal"))
        draw_card(i, state)


def hit(x, y):
    for i, (x1, y1, x2, y2) in enumerate(_UI["bounds"]):
        if x1 <= x <= x2 and y1 <= y <= y2:
            return i
    return -1


# ================= 交互 =================
def on_motion(e):
    if core.ST["busy"]:
        return
    h = hit(e.x, e.y)
    if h != _UI["hovered"]:
        _UI["hovered"] = h
        sync()


def on_leave(_e):
    _UI["hovered"] = -1
    sync()


def on_press(e):
    _UI["pressed"] = hit(e.x, e.y)
    sync()


def on_release(e):
    i = hit(e.x, e.y)
    _UI["pressed"] = -1
    _UI["hovered"] = i
    sync()
    if i < 0 or core.ST["busy"]:
        return
    _dispatch(core.CARDS[i])


def _dispatch(card):
    special = card.get("special")
    if special == "stop":
        stop_async()
    elif special == "restart":
        start_async(proc.restart_service, "正在重启服务…")
    elif special == "remote":
        if core.ST["remote"]:
            start_async(proc.remote_off, "正在关闭远程服务…")
        else:
            start_async(proc.remote_launch, "正在检测 Tailscale…")
    else:
        args = list(card.get("args") or [])
        start_async(lambda a=args: proc.local_launch(a), "正在启动「%s」…" % card["title"])


def set_note_impl(text):
    """品牌区次行提示（注入 core.set_note，供 Tailscale 等待授权时用）。"""
    cv = _UI["cv"]
    try:
        cv.itemconfig("st_remote", text=text or "", fill=core.GRAY)
    except Exception:
        core.log_error(traceback.format_exc())


def install_set_note():
    """把本层的提示实现注入 core —— 模块级函数（core.set_note）只认 core._set_note_fn。"""
    core._set_note_fn = set_note_impl


def set_busy(b, note=""):
    core.ST["busy"] = b
    core.ST["note"] = note
    core._recheck.set()
    cv = _UI["cv"]
    if b:
        cv.itemconfig("st_main", text="◎  " + (note or "处理中…"), fill=core.STATUS_BUSY)
        cv.itemconfig("st_remote", text="", fill=core.GRAY)
    sync()


def task_done(ok, msg):
    set_busy(False, msg if not ok else "")
    core._recheck.set()


def start_async(fn, note):
    if core.ST["busy"]:
        return
    set_busy(True, note)

    def work():
        try:
            ok, msg = fn()
        except Exception:
            core.log_error(traceback.format_exc())
            ok, msg = False, "内部错误（已记录 _logs/Index_error.log）"
        core.log_error("start_async: done ok=%s msg=%s" % (ok, msg))
        core.ui(lambda: task_done(ok, msg))

    threading.Thread(target=work, daemon=True).start()


def stop_async():
    if core.ST["busy"]:
        return
    set_busy(True, "正在停止服务…")

    def work():
        killed = proc.stop_service()
        core.ui(lambda: task_done(True, "服务已停止" if killed else "服务未在运行"))

    threading.Thread(target=work, daemon=True).start()


# ================= 状态渲染与轮询 =================
def render_state(local_on, remote_on):
    cv = _UI["cv"]
    if local_on and remote_on:
        # 双进程并行：主行精简防溢出，远程完整地址放次行
        cv.itemconfig("st_main",
                      text="●  服务运行中　本地 :%d　｜　远程 :%d" % (core.PORT, core.REMOTE_PORT),
                      fill=core.STATUS_ON)
        cv.itemconfig("st_remote",
                      text=("远程访问　" + core.ST["ts_url"]) if core.ST["ts_url"]
                      else "远程服务已就绪（端口 %d）" % core.REMOTE_PORT,
                      fill=core.GRAY)
    elif local_on:
        cv.itemconfig("st_main",
                      text="●  服务运行中　http://127.0.0.1:%d/" % core.PORT, fill=core.STATUS_ON)
        cv.itemconfig("st_remote", text="", fill=core.GRAY)
    elif remote_on:
        ts = core.ST["ts_url"] or ("http://%s:%d/" % (core.ST["tail_ip"], core.REMOTE_PORT)
                                   if core.ST["tail_ip"] else "")
        cv.itemconfig("st_main",
                      text="●  服务运行中（仅远程）:%d" % core.REMOTE_PORT, fill=core.STATUS_ON)
        cv.itemconfig("st_remote",
                      text=("远程访问　" + ts if ts else "本地服务未启动，可用「完整模式」开启"),
                      fill=core.GRAY)
    else:
        note = core.ST["note"] or ""
        cv.itemconfig("st_main",
                      text="○  服务未运行" + (("　· " + note) if note else ""),
                      fill=core.STATUS_OFF)
        cv.itemconfig("st_remote", text="", fill=core.GRAY)
    sync()


def _probe():
    core.PORT = core.local_port()             # 每轮重读（8766 恒为远程专用，本地固定让位 8765）
    local_on = proc.port_open(port=core.PORT)
    remote_on = proc.port_open(port=core.REMOTE_PORT)
    _ts_st, ip, _msg = proc.ts_state()
    return local_on, remote_on, ip


def _apply(probe_res):
    local_on, remote_on, ip = probe_res["v"]
    if ip and ip != core.ST["tail_ip"]:
        core.ST["tail_ip"] = ip
        core.ST["ts_url"] = "http://%s:%d/" % (ip, core.REMOTE_PORT)
    core.ST["remote"] = remote_on
    render_state(local_on, remote_on)


def drain(root):
    """单链排空 UI 队列：后台线程只 put，真正碰 tk 的调用都在这里执行。

    任何异常都不能打断 `root.after` 链（否则状态栏永久冻结），但也**不能凭空消失**：
    队列空是正常出口（精确捕 `queue.Empty`），任务本身的异常单独立即记盘。"""
    try:
        while True:
            try:
                fn = core.UI_QUEUE.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                core.log_error(traceback.format_exc())
    finally:
        root.after(50, lambda: drain(root))


def poll_tick(root):
    if core.ST["busy"]:
        _UI["cv"].itemconfig("st_main", text="◎  " + (core.ST["note"] or "处理中…"),
                             fill=core.STATUS_BUSY)
        _UI["cv"].itemconfig("st_remote", text="", fill=core.GRAY)
        sync()
        root.after(300, lambda: poll_tick(root))
        return
    probe_res = {"v": (None, None)}
    _start_probe_thread(probe_res)
    wait = 300 if core._recheck.is_set() else 3000
    core._recheck.clear()
    root.after(wait, lambda: poll_tick(root))


def _start_probe_thread(probe_res):
    def probe_thread():
        try:
            probe_res["v"] = _probe()
        except Exception:
            core.log_error(traceback.format_exc())
        core.ui(lambda: _apply(probe_res))

    threading.Thread(target=probe_thread, daemon=True).start()


# ================= 组装 =================
def build():
    """建窗口 → 静态层 → 卡片 → 绑事件，返回 root。"""
    root = _init_window()
    _UI["f"] = _make_fonts(root)
    _UI["cv"] = _make_canvas(root)
    _draw_brand(_UI["cv"], _UI["f"])
    _UI["bounds"] = _card_bounds(len(core.CARDS))
    install_set_note()
    for i in range(len(core.CARDS)):
        draw_card(i, "normal")
    cv = _UI["cv"]
    cv.bind("<Motion>", on_motion)
    cv.bind("<Leave>", on_leave)
    cv.bind("<ButtonPress-1>", on_press)
    cv.bind("<ButtonRelease-1>", on_release)
    _draw_footer(cv, _UI["f"], _UI["bounds"][-1][3])
    drain(root)
    poll_tick(root)
    return root
