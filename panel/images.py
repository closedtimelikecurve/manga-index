# -*- coding: utf-8 -*-
"""封面读取 / 缩略图 / 低带宽转码 / Tailscale 判路 —— 3.7 结构重构：从 app.py 抽出。

三块：
  * 封面：内存 LRU（静图缩略图）+ 磁盘缓存 `.thumb_cache`（重启不重解码；
    动图保持原字节走磁盘/源文件，不进内存 LRU —— P2-3）
  * 低带宽模式（2026-09-23）：远程走 Tailscale 中继时按需把整页转码成小图
    （静图 ↓5~7×；动图抽帧+缩小 ↓5~12× 且保留动画），转码结果落盘 `.low_cache`
  * 判路：本机/局域网给原图；Tailscale 直连给原图，中继或未知给低带宽版

打桩点提醒（见 test_low_bandwidth）：
  * `LOW_DIR` 是**可重绑定常量**（测试改它换缓存目录）→ 打桩打到**本模块**；
  * `_tailnet_direct_map` 被测试替换为固定映射 → 打桩同样打到**本模块**。
"""
import hashlib
import io
import json
import os
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict

from flask import request

from common import CFG, CACHE_DIR
from panel.archive import _archive_read
from panel.deps import PIL_OK, PILImage, RAR_AVAILABLE
from panel.paths import APP_DIR, mime_for
from services.netaddr import real_client

cover_cache = OrderedDict()
COVER_CACHE_MAX = 1500
COVER_CACHE_MAX_BYTES = 150 * 1024 * 1024    # 内存 LRU 字节预算（静图缩略图 ~50KB/条，正常远达不到）
_cover_cache_bytes = [0]
COVER_LOCK = threading.Lock()
THUMB_DIR = os.path.join(CACHE_DIR, "thumb")        # 3.7 Stage3：缓存归入 _app/_cache/（文库扫描跳过）
THUMB_MAX_BYTES = int(CFG.get("thumb_max_bytes") or 200 * 1024 * 1024)  # 2026-10-15 可配（config.json thumb_max_bytes），默认 200MB
LOW_DIR = os.path.join(CACHE_DIR, "low")            # 远程（低带宽）转码缓存，同在 _app/_cache/ 下
LOW_MAX_BYTES = 600 * 1024 * 1024
LOW_PAGE_SIDE = 1200          # 远程页面长边上限（本机/局域网仍给原图）
LOW_ANIM_SIDE = 480           # 远程动图（GIF）单帧长边上限：帧数 × 像素，压得更狠
LOW_ANIM_FRAMES = 24          # 动图最多保留帧数（超出就抽帧，时长按比例拉长）
LOW_ANIM_COLORS = 64          # 动图调色板色数（GIF 重编码的体积大头在这里）
LOW_QUALITY = 80
LOW_KEEP_RATIO = 0.7          # 转码结果必须小于原体积的这个比例，否则视为"没收益"→ 回退原图


# ---------------------------------------------------------------
# 远程低带宽模式（2026-09-23）：在外面走 Tailscale 中继时（实测 480~677ms 往返、跨境限速），
# 一页原图 9.8MB 根本打不开 —— 这里给"来源是远程且当前走中继"的客户端按需转码成小图。
# 判据（可用 ?img=orig|low 显式覆盖）：
#   本机 / 局域网（同一 LAN，直连很快）      → 原图
#   Tailscale(100.64.0.0/10) 且该对端是直连  → 原图（比如手机在家连上同一网络）
#   Tailscale 且该对端走中继（DERP）          → 低带宽版
#   查不到对端状态（没装 CLI 等）→ 保守按低带宽处理
# ---------------------------------------------------------------
_TS_PATH_CACHE = {"at": 0.0, "direct": {}}


def _tailnet_direct_map(ttl=20.0):
    """{对端 tailnet IP: 是否直连} —— 来自 `tailscale status --json`（缓存 ttl 秒，
    避免每个图片请求都去问一次 CLI；输出写临时文件，不用管道）。"""
    now = time.time()
    with COVER_LOCK:
        if now - _TS_PATH_CACHE["at"] < ttl:
            return _TS_PATH_CACHE["direct"]
    direct = {}
    exe = None
    for cand in (r"C:\Program Files\Tailscale\tailscale.exe",
                 os.path.join(os.environ.get("ProgramFiles", ""), "Tailscale", "tailscale.exe"),
                 "tailscale"):
        if cand == "tailscale" or os.path.exists(cand):
            exe = cand
            break
    if exe:
        fd, out = tempfile.mkstemp(prefix="ts_path_", dir=APP_DIR)
        os.close(fd)
        try:
            with open(out, "w", encoding="utf-8") as fout:
                subprocess.run([exe, "status", "--json"], stdout=fout, stderr=subprocess.DEVNULL,
                               timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            with open(out, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            for peer in (data.get("Peer") or {}).values():
                ips = peer.get("TailscaleIPs") or []
                is_direct = bool(peer.get("CurAddr"))
                for ip in ips:
                    if isinstance(ip, str) and ip.startswith("100."):
                        direct[ip] = is_direct
        except Exception:
            direct = {}
        finally:
            try:
                os.unlink(out)
            except OSError:
                pass
    with COVER_LOCK:
        _TS_PATH_CACHE["at"] = now
        _TS_PATH_CACHE["direct"] = direct
    return direct


def _is_tailnet_ip(ip):
    """Tailscale 网段 100.64.0.0/10。"""
    parts = str(ip or "").split(".")
    if len(parts) != 4:
        return False
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return a == 100 and 64 <= b <= 127


def client_wants_low():
    """本次请求是否要发"低带宽版"图（详见上面注释）。"""
    forced = (request.args.get("img") or "").strip().lower()
    if forced in ("orig", "original", "full"):
        return False
    if forced in ("low", "small", "1", "true"):
        return True
    # 3.6.148：反代（Tailscale serve）后面 remote_addr 恒是 127.0.0.1，
    # 直接拿它判会永远走"本机直连很快"分支 → 手机经中继时也发原图，低带宽优化失效。
    ip = real_client(request.remote_addr, request.headers.get("X-Forwarded-For"))
    if not _is_tailnet_ip(ip):
        return False                     # 本机 / 局域网：直连很快，给原图
    return not _tailnet_direct_map().get(ip, False)   # 中继或未知 → 低带宽


def _low_cache_path(key, ext):
    return os.path.join(LOW_DIR, key + ext)


def _low_disk_key(seed):
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


def _frame_durations(im, n):
    """动图每帧时长（毫秒），取不到就用默认 100ms。"""
    out = []
    for i in range(n):
        try:
            im.seek(i)
            out.append(int(im.info.get("duration") or 100))
        except Exception:
            out.append(100)
    return out


def lowres_image(data, src_name, seed):
    """把一页图转码成"低带宽版"（长边 ≤ LOW_PAGE_SIDE；动图单帧 ≤ LOW_ANIM_SIDE 且保留动画）。
    返回 (bytes, mime) 或 None（未装 Pillow / 转码失败 / 没必要转 → 调用方给原图）。
    结果按 seed（源路径+mtime+页名）落盘缓存，重复观看不再重复转码。

    3.6.71 结构：动图 `_lowres_animated`、静图 `_lowres_still`（cc 20→5）。
    """
    if not PIL_OK or not data:
        return None
    key = _low_disk_key("low1|" + seed)
    try:
        im = PILImage.open(io.BytesIO(data))
        animated = bool(getattr(im, "is_animated", False)) and getattr(im, "n_frames", 1) > 1
    except Exception:
        return None
    if animated:
        return _lowres_animated(im, data, _low_cache_path(key, ".gif"))
    return _lowres_still(data, _low_cache_path(key, ".jpg"))


def _lowres_animated(im, data, p):
    """动图：抽帧 + 缩边 + 减色后重编码为 GIF；压不小就回退原图（返回 None）。"""
    try:
        if os.path.exists(p):
            with open(p, "rb") as f:
                return f.read(), "image/gif"
    except OSError:
        pass
    try:
        n = int(getattr(im, "n_frames", 1))
        loop_val = int(im.info.get("loop") or 0)
        step = max(1, -(-n // LOW_ANIM_FRAMES))          # 抽帧：总数不超过 LOW_ANIM_FRAMES
        frames, durs = [], []
        for i in range(0, n, step):
            im.seek(i)
            fr = im.convert("RGB")
            fr.thumbnail((LOW_ANIM_SIDE, LOW_ANIM_SIDE))
            fr = fr.quantize(colors=LOW_ANIM_COLORS)
            # 关键：清掉源图残留的 info。很多 GIF 带 P 模式 transparency（bytes 形态），
            # 不清掉会让编码器直接抛 "Transparency for P mode should be bytes or int"
            # —— 之前那个 9.8MB 的动图就是这么被整页回退成原图的。
            fr.info = {}
            frames.append(fr)
            durs.append(int(im.info.get("duration") or 100) * step)
        if not frames:
            return None
        out = io.BytesIO()
        frames[0].save(out, "GIF", save_all=True, append_images=frames[1:],
                       duration=durs, loop=loop_val, optimize=True)
        raw = out.getvalue()
        # 实测教训：GIF 重编码（改尺寸/改调色板）可能比原文件**更大**（PIL 的调色板重排
        # + 丢掉原编码器的帧间压缩）。收益不够就回退原图 —— 宁可慢，也别把 6.5MB 变成 11.7MB。
        if len(raw) >= len(data) * LOW_KEEP_RATIO:
            return None
        _low_cache_write(p, raw)
        return raw, "image/gif"
    except Exception:
        return None                      # 转码失败 → 让调用方回退原图


def _lowres_still(data, p):
    """静图 → JPEG（透明通道合白底）；压不小就回退原图（返回 None）。"""
    try:
        if os.path.exists(p):
            with open(p, "rb") as f:
                return f.read(), "image/jpeg"
    except OSError:
        pass
    try:
        im2 = PILImage.open(io.BytesIO(data))
        im2.thumbnail((LOW_PAGE_SIDE, LOW_PAGE_SIDE))
        im2 = _flatten_alpha(im2)
        out = io.BytesIO()
        im2.save(out, "JPEG", quality=LOW_QUALITY, optimize=True)
        raw = out.getvalue()
        if len(raw) >= len(data) * LOW_KEEP_RATIO:
            return None                      # 没压下来（本来就是小图）→ 不折腾
        _low_cache_write(p, raw)
        return raw, "image/jpeg"
    except Exception:
        return None


def _flatten_alpha(im):
    """透明通道合到白底（JPEG 不支持 alpha）；其余模式统一转 RGB。"""
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = PILImage.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        return bg
    if im.mode != "RGB":
        return im.convert("RGB")
    return im


def _low_cache_write(path, raw):
    try:
        os.makedirs(LOW_DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=LOW_DIR, suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        os.replace(tmp, path)
    except OSError:
        pass


def prune_low_cache():
    """低带宽缓存按总量上限清理（最旧的先删），与缩略图缓存同一套思路。"""
    try:
        files = []
        total = 0
        for n in os.listdir(LOW_DIR):
            p = os.path.join(LOW_DIR, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            files.append((st.st_mtime, st.st_size, p))
            total += st.st_size
        if total <= LOW_MAX_BYTES:
            return
        files.sort()
        for _mt, size, p in files:
            if total <= LOW_MAX_BYTES * 0.8:
                break
            try:
                os.unlink(p)
                total -= size
            except OSError:
                pass
    except OSError:
        pass


def make_thumbnail(data, max_side=520):
    """生成 JPEG 缩略图。动图（GIF / 动图 WebP / APNG）返回原始字节以保留动态效果。
    返回 (data, mime)：mime="image/jpeg" 表示已缩略；mime=None 表示未转码（mime 由调用方按源扩展名判断）。"""
    if not PIL_OK:
        return data, None
    try:
        im = PILImage.open(io.BytesIO(data))
        if getattr(im, "is_animated", False):
            return data, None
        im.thumbnail((max_side, max_side))
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = PILImage.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        out = io.BytesIO()
        im.save(out, "JPEG", quality=82)
        return out.getvalue(), "image/jpeg"
    except Exception:
        return data, None


def _thumb_disk_key(cover):
    """缩略图磁盘缓存键：源路径 + mtime + 大小 → sha1（源文件变动自动失效）。扩展名由读写双方决定。"""
    try:
        if cover[0] == "file":
            st = os.stat(cover[1])
            raw = f"file|{os.path.abspath(cover[1])}|{st.st_mtime_ns}|{st.st_size}"
        else:
            st = os.stat(cover[1])
            raw = f"{cover[0]}|{os.path.abspath(cover[1])}|{cover[2]}|{st.st_mtime_ns}"
    except OSError:
        return None
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _cover_disk_write(dkey, data, src_name, anim=False):
    """写封面磁盘缓存：anim=False → `键.jpg`（静态缩略图专用槽位）；
    anim=True → `键_anim+源扩展名`（动图原字节 / 未转码原字节）。"""
    src_ext = os.path.splitext(src_name)[1].lower() or ".img"
    name = (dkey + "_anim" + src_ext) if anim else (dkey + ".jpg")
    try:
        os.makedirs(THUMB_DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=THUMB_DIR, suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, os.path.join(THUMB_DIR, name))
    except OSError:
        pass


def _cover_cache_put(key, val):
    """内存 LRU 只放静图缩略图（动图走磁盘缓存/原文件直接 send_file，见 cover_payload）。
    条数 + 字节预算双限（P2-3）。"""
    with COVER_LOCK:
        if key in cover_cache:
            _cover_cache_bytes[0] -= len(cover_cache.pop(key)[0])
        cover_cache[key] = val
        _cover_cache_bytes[0] += len(val[0])
        while cover_cache and (len(cover_cache) > COVER_CACHE_MAX
                               or _cover_cache_bytes[0] > COVER_CACHE_MAX_BYTES):
            _k, v = cover_cache.popitem(last=False)
            _cover_cache_bytes[0] -= len(v[0])


def cover_payload(work):
    """封面 HTTP 载荷。返回 (kind, payload, mime)：
      kind="bytes" → payload 为字节（静图缩略图，来自内存/磁盘缓存）
      kind="file"  → payload 为磁盘路径（动图：压缩包源 = _anim 磁盘缓存，文件源 = 原文件；
                     直接 send_file，不再把动图原图塞进内存 LRU —— P2-3）
    失败返回 (None, None, None)。

    3.6.71 结构：内存/磁盘缓存命中、源图读取、缩略编码各自成函数（cc 22→4）。
    """
    cover = work.get("cover")
    if not cover:
        return None, None, None
    key = (work["path"], json.dumps(cover, ensure_ascii=False))
    hit = _cover_cache_get(key)
    if hit is not None:
        return "bytes", hit[0], hit[1]

    kind = cover[0]
    src_name = cover[2] if kind != "file" else os.path.basename(cover[1])
    dkey = _thumb_disk_key(cover)
    # 1) 磁盘缓存：`键.jpg` = 静态缩略图（进内存 LRU）；`键_anim.ext` = 动图原字节（只走磁盘）
    cached = _cover_disk_hit(key, dkey, src_name)
    if cached:
        return cached
    # 2) 读源图（文件 / 压缩包内）
    data = _cover_source_bytes(kind, cover)
    if not data:
        return None, None, None
    # 3) 缩略：静图 → JPEG 缩略图；动图 → 保持原字节（不进内存 LRU）
    return _cover_encode(key, dkey, src_name, kind, cover, data)


def _cover_cache_get(key):
    """内存 LRU 命中（命中即刷新 LRU 顺序）；未命中返回 None。"""
    with COVER_LOCK:
        hit = cover_cache.get(key)
        if hit is None:
            return None
        cover_cache.move_to_end(key)
        return hit


def _cover_disk_hit(key, dkey, src_name):
    """磁盘缓存命中：`键.jpg` 读进内存 LRU 后按字节发；`键_anim.ext` 直接发文件。"""
    if not dkey:
        return None
    p_jpg = os.path.join(THUMB_DIR, dkey + ".jpg")
    try:
        with open(p_jpg, "rb") as f:
            data = f.read()
        _cover_cache_put(key, (data, "image/jpeg"))
        return "bytes", data, "image/jpeg"
    except OSError:
        pass
    src_ext = os.path.splitext(src_name)[1].lower()
    if src_ext and src_ext not in (".jpg", ".jpeg"):
        p_anim = os.path.join(THUMB_DIR, dkey + "_anim" + src_ext)
        if os.path.exists(p_anim):
            return "file", p_anim, mime_for(src_name)
    return None


def _cover_source_bytes(kind, cover):
    """读源图字节：文件源直接读，压缩包源走句柄池；读不了返回 None（调用方按 404 处理）。"""
    try:
        if kind == "file":
            with open(cover[1], "rb") as f:
                return f.read()
        if kind == "zip":
            return _archive_read(os.path.abspath(cover[1]), cover[2])
        if kind == "rar" and RAR_AVAILABLE:
            return _archive_read(os.path.abspath(cover[1]), cover[2])
    except Exception:
        return None
    return None


def _cover_encode(key, dkey, src_name, kind, cover, data):
    """缩略编码：静图 → JPEG（写磁盘 + 内存）；动图 → 保持原字节。"""
    data, m2 = make_thumbnail(data)
    if m2 == "image/jpeg":
        if dkey:
            _cover_disk_write(dkey, data, src_name, anim=False)
        _cover_cache_put(key, (data, m2))
        return "bytes", data, m2

    # 动图（或 PIL 不可用/解码失败）：mime 按源扩展名
    mime = mime_for(src_name)
    src_ext = os.path.splitext(src_name)[1].lower()
    if kind == "file":
        # 文件源：本就在磁盘上，直接发原文件
        return "file", cover[1], mime
    if dkey and src_ext and src_ext not in (".jpg", ".jpeg"):
        # 压缩包源：写 _anim 磁盘缓存后直接发文件（重复请求免解压、不占内存）。
        # .jpg/.jpeg 源走到这里意味着解码失败，原字节不可复用，不落盘。
        _cover_disk_write(dkey, data, src_name, anim=True)
        p_anim = os.path.join(THUMB_DIR, dkey + "_anim" + src_ext)
        if os.path.exists(p_anim):
            return "file", p_anim, mime
    return "bytes", data, mime


def read_cover(work):
    """兼容接口（open_work_image 用）：把 cover_payload 归一为 (bytes, mime)。"""
    kind, payload, mime = cover_payload(work)
    if not payload:
        return None, None
    if kind == "file":
        try:
            with open(payload, "rb") as f:
                return f.read(), mime
        except OSError:
            return None, None
    return payload, mime


def prune_thumb_cache():
    """磁盘缩略图缓存超上限时按最旧优先清理。"""
    try:
        entries, total = [], 0
        for n in os.listdir(THUMB_DIR):
            p = os.path.join(THUMB_DIR, n)
            try:
                st = os.stat(p)
                entries.append((st.st_mtime, st.st_size, p))
                total += st.st_size
            except OSError:
                continue
        for _mt, sz, p in sorted(entries):
            if total <= THUMB_MAX_BYTES:
                break
            try:
                os.unlink(p)
                total -= sz
            except OSError:
                pass
    except OSError:
        pass
