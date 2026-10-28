#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""index_launcher.py —— Index 启动面板（Index.exe 的入口，只留组装与主循环）。

3.6.84 起按职责拆成四个模块（此前是 1094 行单文件，配置/端口/进程/UI 全挤在一起）：
  * `launcher_core`  配置、常量、日志、全局状态（ST/PROC/PORT/UI_QUEUE）
  * `launcher_proc`  netstat/端口探测、Tailscale、Popen 启停与重启
  * `launcher_ui`    tkinter 画布：品牌区、功能卡、事件、状态轮询
  * 本文件           再导出上述名字（保持 `index_launcher.xxx` 调用面）+ main()

**端口约定**：本地 8765、远程 8766（Tailscale，绑 0.0.0.0）。两者是独立进程，
可并行；「停止服务」会连本地带远程一起收，并兜底清扫命令行带 app.py 的残留进程。

**改 `PORT`/`TS_EXE`/`APP_DIR` 请改 `launcher_core`**：本文件的同名变量只是导入期的
快照（Python 的 `from x import y` 不共享变量），运行期真值以 `launcher_core` 为准。
"""
import sys
import traceback

import launcher_core as core                                        # noqa: F401
import launcher_ui as ui
from launcher_core import (                                        # noqa: F401
    APP_DIR, FROZEN, CREATE_NO_WINDOW,
    W, CARD_H, CARD_GAP, HEAD_H, HEAD_Y, GAP_HEAD, FOOT_H, FOOT_GAP, FOOT_MARGIN,
    BLACK, BLACK2, BLACK3, WHITE, WHITE_SOFT, GRAY, GRAY_D, GRAY_EDGE,
    CARD, TEXT, SUB_TEXT, STATUS_ON, STATUS_OFF, STATUS_BUSY,
    _BUILTIN_CARDS, _DEFAULT_ICONS, _DEFAULT_COLORS,
    _panel_height, _read_version_file, _theme_from, load_panel_config,
    PANEL, CARDS, H, THEME_MAP,
    log_error, find_python, PY, load_port, REMOTE_PORT, local_port, PORT,
    load_token, ensure_remote_token, TS_EXE,
    ST, PROC, UI_QUEUE, _recheck, ui as ui_queue, set_note, _set_note_fn,
)
from launcher_proc import (                                        # noqa: F401
    run_cmd, run_ts, ts_state, open_ts_login,
    _port_now, _netstat_local_addr, listening_pids, server_listen_state, port_open,
    _stop_proc, stop_local, stop_remote, _kill_stray_panel_procs, stop_service,
    wait_port_ready, _spawn, local_launch, remote_launch, remote_off,
    http_restart, restart_service,
)
from launcher_ui import (                                          # noqa: F401
    _rr, _draw_icon, draw_card, sync, hit, set_busy, start_async, stop_async, render_state,
)


def main():
    """建窗口并进入事件循环。关闭窗口不会停止服务（服务是独立进程）。"""
    root = ui.build()
    root.mainloop()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log_error(traceback.format_exc())
        raise
