# -*- coding: utf-8 -*-
"""services/theme_store.py —— 主题槽位 / 图库的**纯原语**（无 Flask、无 app 依赖）。

为什么单独成模块：`routes/` 只薄薄一层 HTTP（纪律 §五），而"文件名白名单、魔数判型、
副本读写、active 记录、图库枚举"属于规则本体。3.6.121 从 `routes/theme.py` 原样搬出，
**行为零变化**（纯搬移提交，唯一验收标准是既有测试不改一行全绿）。

关键约定：**本模块不持有任何全局路径**。目录/基准名一律由调用方（`routes/theme.py`）
作为参数传入——那边的模块级路径常量正是测试的打桩面（纪律 §4.1），搬进本模块会让
`monkeypatch.setattr(routes.theme, "_GALLERY_DIR", …)` 静默失效、写穿真实 `_state/`。
"""
import os
import re
import shutil
import threading
import uuid
from datetime import datetime

IMG_EXTS = (".jpg", ".png", ".webp")
EXT_MIME = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
# 图库文件名白名单：只认时间戳/内置前缀 + 短随机这一种形状。禁止 `/`、`\\`、`%` 与 `:`，
# 因此 `../..`、绝对路径、URL 编码绕过都进不来（第一道闸；第二道是 basename 比对）。
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.(?:jpg|png|webp)$")
MAX_BYTES = 8 * 1024 * 1024

# 3.6.122 内置基础图库：文件在 static/img/gallery/，注册表顺序 = 列表里永远排在最前的顺序
# （固定顺序，不随 mtime 抖动）。标题即 i18n key（双端都过 t()/AppI18n.s()）。
# 内置图**不可删除**：它们是新装用户的起点，删了图库就空了。
BUILTIN_ITEMS = (
    ("b00_black.jpg", "纯黑"),
    ("b01_default_bg.jpg", "默认背景图"),
    ("b02_default_hero.jpg", "默认横幅"),
    ("b03_unsplash_fjord.jpg", "峡湾"),
    ("b04_unsplash_mist.jpg", "雾林"),
    ("b05_unsplash_jelly.jpg", "水母"),
    ("b06_draw_neon.jpg", "霓虹网格"),
    ("b07_draw_jade.jpg", "翡翠涟漪"),
    ("b08_draw_dusk.jpg", "暮色条纹"),
    ("b09_default_mobile.jpg", "默认背景图（手机）"),
)
_BUILTIN_NAMES = frozenset(name for name, _title in BUILTIN_ITEMS)


def name_ok(name):
    """图库文件名白名单：仅 [A-Za-z0-9_.-]，必以 .jpg/.png/.webp 结尾。

    正则本身已排除目录分隔符；再叠一层 os.path.basename 比对，防的是"正则日后被人
    放宽后悄悄放行 `../x.png`"——两道闸都只接受纯文件名。"""
    if not isinstance(name, str) or not NAME_RE.match(name):
        return False
    return os.path.basename(name) == name


def path_in(dir_, name):
    """该目录中此文件的可读路径；名字不合法或文件不存在返回 None（穿越在此被挡）。"""
    if not name_ok(name):
        return None
    path = os.path.join(dir_, name)
    return path if os.path.isfile(path) else None


def ext_of(path):
    return os.path.splitext(path)[1]


def mime_of(path):
    return EXT_MIME.get(ext_of(path), "image/jpeg")


def sniff_ext(data):
    """按文件魔数判定扩展名；非 jpg/png/webp 返回 None。"""
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def copy_path(base, exts=IMG_EXTS):
    """某槽位副本的实际路径（`base` + 扩展探测）；没有返回 None。"""
    for ext in exts:
        p = base + ext
        if os.path.exists(p):
            return p
    return None


def write_copy(base, data, ext, exts=IMG_EXTS):
    """写槽位副本 `base<ext>`，顺带清掉其它扩展的旧副本（同一槽位只留一份）。"""
    ensure_dir(os.path.dirname(base))
    for old in exts:
        p = base + old
        if p != base + ext and os.path.exists(p):
            os.remove(p)
    with open(base + ext, "wb") as f:
        f.write(data)


def clear_copy(base, exts=IMG_EXTS):
    """删掉槽位副本（可能在任一支持的扩展名下）；文件不存在时无操作。"""
    for ext in exts:
        p = base + ext
        if os.path.exists(p):
            os.remove(p)


def ensure_dir(path):
    """建目录（`path` 为空串时无操作——`_app` 根目录已存在）。"""
    if path:
        os.makedirs(path, exist_ok=True)


def read_active(path):
    """active 记录里的文件名；无记录或记录非法（被外部改坏）返回空串。"""
    if not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        name = f.read().strip()
    return name if name_ok(name) else ""


def write_active(path, name):
    """写 active 记录（一行文件名）；写失败直接抛给调用方，不静默。"""
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        f.write(name + "\n")


def clear_active(path):
    """清 active 记录（无记录时无操作；图库文件一律不动）。"""
    if os.path.exists(path):
        os.remove(path)


def new_name(ext, now=None):
    """新图库文件名：t_<YYYYmmdd_HHMMSS>_<4 位随机><ext>（时间戳 + 短随机防撞名）。"""
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return "t_%s_%s%s" % (stamp, uuid.uuid4().hex[:4], ext)


def save_image(dir_, data, ext, now=None):
    """图片字节落盘到图库，返回文件名（是否设为 active 由调用方决定）。"""
    ensure_dir(dir_)
    name = new_name(ext, now)
    with open(os.path.join(dir_, name), "wb") as f:
        f.write(data)
    return name


def list_items(dir_):
    """图库条目列表（name/size/mtime），按 mtime 倒序；非白名单条目跳过。"""
    if not os.path.isdir(dir_):
        return []
    items = []
    for name in os.listdir(dir_):
        path = path_in(dir_, name)
        if path:
            st = os.stat(path)
            items.append({"name": name, "size": st.st_size, "mtime": st.st_mtime})
    items.sort(key=lambda it: it["mtime"], reverse=True)
    return items


# ---------- 3.6.122 内置图 ----------

def is_builtin(name):
    """是否内置图（内置图不可删除，也不接受同名用户覆盖写入之外的删除）。"""
    return name in _BUILTIN_NAMES


def builtin_items(dir_):
    """内置图条目（注册表顺序在前），缺文件则跳过——守卫测试会逐项断言文件存在。"""
    items = []
    for name, title in BUILTIN_ITEMS:
        path = os.path.join(dir_, name)
        if not os.path.isfile(path):
            continue
        st = os.stat(path)
        items.append({"name": name, "size": st.st_size, "mtime": st.st_mtime,
                      "builtin": True, "title": title})
    return items


def find_image(user_dir, builtin_dir, name):
    """图库取图：用户目录优先（同名用户图可覆盖显示），其次内置目录。"""
    return path_in(user_dir, name) or path_in(builtin_dir, name)


# ---------- 3.6.122 旧全局槽位 → 按端槽位的一次性迁移 ----------

_MIGRATE_LOCK = threading.Lock()
_MIGRATED = set()


def migrate_legacy(state_dir, clients):
    """把 3.6.121 及以前的**全局**选用（theme_active.txt + theme_bg.<ext>）复制到每个端槽位。

    * 幂等：`_MIGRATED` 按 state_dir 短路；进程重启后重跑也只补缺的端。
    * 断电安全：先把每个端的 active 与副本都写好，**最后才删旧文件**。
    * 失败不静默也不阻断：`OSError` 保留旧文件，读路径仍会兜底读旧副本
      （用户可见后果 = 继续显示升级前那张图，而不是图丢了），下次请求再重试。
    """
    with _MIGRATE_LOCK:
        if state_dir in _MIGRATED:
            return
        legacy_active = os.path.join(state_dir, "theme_active.txt")
        legacy_base = os.path.join(state_dir, "theme_bg")
        name = read_active(legacy_active)
        src = copy_path(legacy_base)
        try:
            for client in clients:
                dst_active = os.path.join(state_dir, "theme_active_%s.txt" % client)
                if name and not os.path.exists(dst_active):
                    write_active(dst_active, name)
                dst_base = os.path.join(state_dir, "theme_bg_%s" % client)
                if src and not copy_path(dst_base):
                    shutil.copyfile(src, dst_base + ext_of(src))
            ready = all(os.path.exists(os.path.join(state_dir, "theme_active_%s.txt" % c))
                        for c in clients)
            if ready or not name:
                clear_active(legacy_active)
                clear_copy(legacy_base)
        except OSError:
            return                     # 旧文件留给下轮重试；读路径有兜底，不改变用户所见
        _MIGRATED.add(state_dir)

