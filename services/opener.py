# -*- coding: utf-8 -*-
"""services/opener.py —— 用系统默认程序打开作品/封面（3.6.61 Stage7 从 app.py 抽出）。

三平台分支（Windows startfile / macOS open / Linux xdg-open）；压缩包内的封面先解到临时文件，
打开后延迟删除（系统查看器还在读时删不掉，_delayed_unlink 会重试）。
"""
import os
import subprocess
import sys
import tempfile
import threading
import time

from panel.host import h


def _delayed_unlink(path, delay=20.0, retries=5):
    """延迟删除临时文件（给系统查看器留出读取时间；被占用时重试）。"""
    def _try():
        for _ in range(retries):
            try:
                os.unlink(path)
                return
            except OSError:
                time.sleep(2)
    t = threading.Timer(delay, _try)
    t.daemon = True
    t.start()

def open_path(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)            # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False

def open_work_folder(work):
    ok = h().open_path(work["path"])
    label = "压缩包" if work["kind"] != "folder" else "文件夹"
    if ok:
        return True, f"已打开作品{label}：{work['name']}"
    return False, "打开失败（系统没有关联程序）"

def open_work_image(work):
    cover = work.get("cover")
    if not cover:
        return False, "该作品没有可打开的图片"
    if cover[0] == "file":
        if h().open_path(cover[1]):
            return True, "已用默认图片查看器打开首张图片"
        return False, "打开失败（系统没有关联程序）"
    data, _mime = h().read_cover(work)
    if not data:
        return False, "无法从压缩包读取图片"
    ext = ".jpg" if _mime == "image/jpeg" else os.path.splitext(cover[2])[1] or ".img"
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix="djc_", suffix=ext)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if h().open_path(tmp):
            h()._delayed_unlink(tmp)
            return True, "已用默认图片查看器打开首张图片（临时解压）"
        return False, "打开失败（系统没有关联程序）"
    except Exception:
        if tmp:
            try:
                os.unlink(tmp)
            except Exception:
                pass
        return False, "打开失败"
