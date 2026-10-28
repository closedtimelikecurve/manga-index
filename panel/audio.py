# -*- coding: utf-8 -*-
"""音声作品支持：音频轨清单 + lrc 歌词解析 —— 3.7 结构重构：从 app.py 抽出。

APP 3.0.1 音画同步用。纯函数（只读作品 dict 与磁盘/压缩包），无业务状态。
app.py 以 `from panel.audio import (...)` 再导出，保持 `app._parse_lrc_bytes` 等命名面。
"""
import os
import re
import zipfile

from panel.paths import natural_key

AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma"}
LRC_EXTS = {".lrc"}
_AUDIO_MIME = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac",
               ".wav": "audio/wav", ".flac": "audio/flac", ".ogg": "audio/ogg",
               ".opus": "audio/ogg", ".wma": "audio/x-ms-wma"}
_RE_LRC_TIME = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_RE_LRC_OFFSET = re.compile(r"^\[offset:\s*([+-]?\d+)\s*\]", re.IGNORECASE)


def _work_audio_entries(w):
    """作品的音频轨：[(定位符, 条目名, 大小)]。定位符 = 绝对路径（文件夹作品）或
    zip 内条目名（压缩包作品）。natural 排序（1-01 < 1-02 < …）。"""
    path = w.get("path") or ""
    out = []
    if w.get("kind") == "archive" and os.path.splitext(path)[1].lower() in (".zip", ".cbz"):
        try:
            with zipfile.ZipFile(path) as z:
                for i in z.infolist():
                    if i.is_dir():
                        continue
                    if os.path.splitext(i.filename)[1].lower() in AUDIO_EXTS:
                        out.append((i.filename, i.filename, i.file_size))
        except Exception:
            return []
    elif w.get("kind") == "folder" and os.path.isdir(path):
        for dp, _dn, fns in os.walk(path):
            for fn in fns:
                if os.path.splitext(fn)[1].lower() in AUDIO_EXTS:
                    fp = os.path.join(dp, fn)
                    try:
                        out.append((fp, os.path.relpath(fp, path), os.path.getsize(fp)))
                    except OSError:
                        continue
    out.sort(key=lambda x: natural_key(x[1]))
    return out


def _decode_text_bytes(data):
    """lrc 文本解码：utf-8(带 BOM) 严格 → gb18030（简中音声汉化常态）→ big5 → latin-1 兜底。"""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1"):
        try:
            return data.decode(enc).lstrip("\ufeff"), enc
        except (UnicodeDecodeError, ValueError):
            continue
    return data.decode("utf-8", "replace").lstrip("\ufeff"), "utf-8"


def _parse_lrc_bytes(data):
    """lrc → [[毫秒, 文本], ...]（按时间排序）。支持多时间戳行与 [offset:±ms] 修正；
    纯元数据标签行（[ti:]…）跳过；带时间戳的空文本行保留（用作清屏）。"""
    text, _enc = _decode_text_bytes(data)
    offset_ms = 0
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _RE_LRC_OFFSET.match(line)
        if m:
            try:
                offset_ms = int(m.group(1))
            except ValueError:
                pass
            continue
        times = []
        pos = 0
        while True:
            t = _RE_LRC_TIME.match(line, pos)
            if not t:
                break
            mm, ss, frac = int(t.group(1)), int(t.group(2)), t.group(3) or "0"
            ms = mm * 60000 + ss * 1000 + int(frac.ljust(3, "0")[:3])
            times.append(ms)
            pos = t.end()
        if not times:
            continue                        # [ti:]/[ar:] 等元数据行
        body = line[pos:].strip()
        for ms in times:
            out.append([max(0, ms - offset_ms), body])
    out.sort(key=lambda x: x[0])
    return out


def _audio_lrc_for(w, track_name):
    """按同名 stem 找轨道的 lrc（RJ 包惯例：mp3 与 lrc 文件名一致、目录不同）。"""
    stem = os.path.splitext(os.path.basename(track_name))[0]
    path = w.get("path") or ""
    try:
        if w.get("kind") == "archive" and os.path.splitext(path)[1].lower() in (".zip", ".cbz"):
            with zipfile.ZipFile(path) as z:
                for i in z.infolist():
                    if i.is_dir() or os.path.splitext(i.filename)[1].lower() not in LRC_EXTS:
                        continue
                    if os.path.splitext(os.path.basename(i.filename))[0] == stem:
                        return _parse_lrc_bytes(z.read(i.filename))
        elif w.get("kind") == "folder" and os.path.isdir(path):
            for dp, _dn, fns in os.walk(path):
                for fn in fns:
                    if os.path.splitext(fn)[1].lower() not in LRC_EXTS:
                        continue
                    if os.path.splitext(fn)[0] == stem:
                        with open(os.path.join(dp, fn), "rb") as f:
                            return _parse_lrc_bytes(f.read())
    except Exception:
        return []
    return []
