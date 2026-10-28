# -*- coding: utf-8 -*-
"""
common.py —— app.py 与爬虫脚本共用的基础工具
==============================================
设计目标（P2-8）：爬虫/重试脚本只 import 本模块，不再 import app（避免触发
Flask 实例化等副作用）；app.py 也从这里取配置，保证单一来源。

包含：
  * 配置区常量与 config.json 的加载/保存（load_config / save_config / CFG）
  * unique_path：目标已存在时自动加 (2)/(3)… 后缀，绝不覆盖
  * existing_archive_dir：档案目录名沿用规则（同名/规范名一致则沿用）
本模块导入无任何副作用（不启动 Flask、不扫描文库）。
"""
import json
import logging
import os
import sys
import tempfile
import time

sys.dont_write_bytecode = True

log = logging.getLogger(__name__)      # 走 root handler（services/appenv.setup_logging 挂 panel.log）

# ===================== 配置区（可修改） =====================
ROOT_DIR = r""          # 文库根目录；留空 = _app 的上级目录（文库根）
PORT = 8765             # 网页端口
LIBRARY_NAME = "禁书目录 Index"
# ===========================================================

APP_DIR = os.path.dirname(os.path.abspath(__file__))
# 程序与文库分目录存放：本程序位于 <文库根>/_app/ 内，默认文库根 = 程序目录的上级
DEFAULT_LIB_ROOT = os.path.dirname(APP_DIR)
CONFIG_FILE = os.path.join(APP_DIR, "config.json")   # 网页“设置”写入此文件

# ===== 运行时产物目录（2026-10-18 结构重构 Stage3）=====
# 程序目录只放代码与用户配置（config.json/panel_config.json/用户清单）；日志、断点
# 状态、缓存转码一律归入下划线前缀的功能性目录（`_` 前缀 = 功能目录，与 _app/_inbox
# 同规）。文库扫描会跳过整个 _app（app.IGNORE_DIRS 加入 APP_DIR 基名），故这些目录
# 不会被当成作品——但目录必须由写入方按需创建（本模块导入无副作用，见文件头）。
LOG_DIR = os.path.join(APP_DIR, "_logs")     # panel.log / crawl_log*.txt / *.log
STATE_DIR = os.path.join(APP_DIR, "_state")  # library_index.json / region_covers.json / crawl_state*.json
CACHE_DIR = os.path.join(APP_DIR, "_cache")  # 缩略图 / 低带宽转码 / 上传分块 / 直连整本临时目录


def ensure_dir(path):
    """确保目录存在（幂等、无导入期副作用）。返回 path 便于串联：
    `tempfile.mkstemp(dir=ensure_dir(STATE_DIR))`——临时文件必须与 os.replace
    目标同目录（跨盘 replace 在 Windows 直接 WinError 17）。失败静默，真正的
    写失败由各自调用方的 try/except 记日志兜底。"""
    if path:
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            pass
    return path


# ---------------------------------------------------------------
# 站点无关的爬虫日志 / 控制台工具（3.6.156 从 crawlers/wnacg_base.py 下沉）。
# 为什么放这里：services 层 6 个文件此前顶层 `from crawlers.wnacg_base import log`，
# 导致公开发行版（不含 wnacg 站点适配）连 Flask 都起不来。下沉后 services 只依赖
# common；wnacg_base re-export 这两个名字，crawlers/ 内部与测试零改动。
# ---------------------------------------------------------------
CRAWL_LOG_FILE = os.path.join(LOG_DIR, "crawl_log.txt")
_crawl_log_fp = None


def _crawl_log_rotate():
    """爬虫日志超 5MB 轮转为 .old（原 wnacg_base._log_rotate）。"""
    try:
        if os.path.exists(CRAWL_LOG_FILE) and os.path.getsize(CRAWL_LOG_FILE) > 5 * 1024 * 1024:
            old = CRAWL_LOG_FILE + ".old"
            if os.path.exists(old):
                os.unlink(old)
            os.replace(CRAWL_LOG_FILE, old)
    except OSError:
        pass


def crawl_log(msg):
    """爬虫共用日志：控制台 + _logs/crawl_log.txt（原 wnacg_base.log）。"""
    global _crawl_log_fp
    line = time.strftime("[%H:%M:%S] ") + msg
    print(line, flush=True)
    try:
        if _crawl_log_fp is None:
            _crawl_log_rotate()
            ensure_dir(os.path.dirname(CRAWL_LOG_FILE) or APP_DIR)
            _crawl_log_fp = open(CRAWL_LOG_FILE, "a", encoding="utf-8")
        _crawl_log_fp.write(line + "\n")
        _crawl_log_fp.flush()
    except Exception:
        logging.getLogger(__name__).debug("crawl_log 写盘失败（不影响爬取）", exc_info=True)


def utf8_console():
    """把控制台切到 UTF-8；**没有控制台就跳过**（原 wnacg_base.utf8_console）。

    爬虫脚本以前在模块级无条件 `sys.stdout.reconfigure(...)`。面板用 pythonw /
    Index.exe 启动时 `sys.stdout` 是 None，那一行就抛
    `AttributeError: 'NoneType' object has no attribute 'reconfigure'` ——
    发生在**导入阶段**，于是面板里"导入即失败"。`print()` 在 sys.stdout 为
    None 时是安全的空操作，所以这里只改编码、不做别的事。
    """
    for fp in (sys.stdout, sys.stderr):
        if fp is None:                                  # 无控制台（GUI 启动）：保持原样
            continue
        try:
            fp.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):             # 已被替换成不可重配置的流
            continue


def display_name(s):
    """展示名解码（3.6.139）：Windows 文件名禁 `|`，旧库把它编码成字面 `&#124;` 存盘
    （works.name 现存 6 部；作者/社团/标签名实测无实体）。只用于 JSON 里**纯展示字段**
    （如 /api/pages 的 name）；work/group/key 等标识符字段必须保持原始名，否则查不到库。"""
    return str(s).replace("&#124;", "|")


def load_config():
    """读 config.json（缺失/损坏时用内置默认），返回内存配置字典。"""
    cfg = {"root": ROOT_DIR or DEFAULT_LIB_ROOT, "port": PORT, "name": LIBRARY_NAME,
           "originals": None, "ignore_files": [], "token": "", "artist_circles": {},
           # 2026-10-15 需求5：测试启动模式——为 true 时不自动弹出浏览器（其他与本地网页模式一致）
           "no_browser": False,
           # 2026-10-15 手机端占用排查：封面缩略图磁盘缓存上限（默认 200MB，防纯本地 APP 膨胀）
           "thumb_max_bytes": 200 * 1024 * 1024,
           # 3.6.148：扫码配对的两个配置项。默认 None = 不写盘，行为同"没配"。
           # pair_url 是手写的远程可达地址（内网穿透域名只能这么给），TLS 入口也靠它；
           # pair_ticket_ttl 是票据有效期（秒），非法值由 pair_tickets.clamp_ttl 兜到 120。
           "pair_url": None, "pair_ticket_ttl": None,
           # 3.6.155：外接下载器工具表 [{name, cmd, timeout}]——{url}/{dest} 占位符
           # 由 crawl_fetch.dl_ext 替换；空表 = 功能未配置（面板给出引导文案）。
           "ext_downloaders": [],
           # 3.6.161：内测模式——所有封面统一换成占位角色图（截图给别人看时不暴露文库内容）。
           # 与启动参数 --safe-images 的区别：后者是进程内内存标志、连内页一起盖成灰度图，
           # 只能启动时定；本项可双端抽屉随时开关、只盖封面、重启后保留。
           "safe_covers": False}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return cfg
    if isinstance(data, dict):
        _apply_config(cfg, data)
    return cfg


def _apply_config(cfg, data):
    """把磁盘配置叠加到默认值上（**只覆盖存在且非空的键**，避免抹掉已有配置）。

    3.6.73 结构：标量 / 列表 / 画师映射 / 两个独立开关各自成函数（cc 16→3）。
    """
    _apply_scalars(cfg, data)
    _apply_lists(cfg, data)
    _apply_ext_downloaders(cfg, data)
    _apply_artist_circles(cfg, data)
    # 测试模式：bool 化（config.json 写成 true/false 或 1/0 皆可）
    if "no_browser" in data:
        cfg["no_browser"] = bool(data["no_browser"])
    # 3.6.161 内测模式：同样 bool 化，手写 "false" 字符串也当假（避免误开）
    if "safe_covers" in data:
        cfg["safe_covers"] = _truthy(data["safe_covers"])
    _apply_thumb_max(cfg, data)


def _truthy(v):
    """宽松真假判定：bool 原样，字符串只认 true/1/yes/on（其余一律假）。"""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    return str(v).strip().lower() in ("true", "1", "yes", "on")


def _apply_scalars(cfg, data):
    """root / port / name / token / pair_url / pair_ticket_ttl：存在且非空才覆盖。

    **白名单漏项 = 配置静默失效**：`routes/pair.py` 早就在读 `pair_url` 与
    `pair_ticket_ttl`，但两者一直不在这个白名单里，于是"config.json 里写了也当没写"
    （3.6.129 引入 pair_url 起就存在，3.6.148 排查 HTTPS 时才暴露）。新增配置项时
    务必同步这里，否则读的一方永远拿到 None。
    """
    for k in ("root", "port", "name", "token", "pair_url", "pair_ticket_ttl"):
        if k in data and data[k] not in (None, ""):
            cfg[k] = data[k]


def _apply_lists(cfg, data):
    """originals / ignore_files 读回内存：保证 save_config(CFG) 不会抹掉已有配置。"""
    for k in ("originals", "ignore_files"):
        if isinstance(data.get(k), list):
            cfg[k] = [str(x) for x in data[k] if str(x).strip()]


def _apply_ext_downloaders(cfg, data):
    """3.6.155：外接下载器工具表读回内存（dict 列表，name/cmd 必有，timeout 可选）。

    校验从宽：坏项丢弃但保留好项——用户手写 JSON 打错一个逗号不至于整表消失。
    """
    raw = data.get("ext_downloaders")
    if not isinstance(raw, list):
        return
    out = []
    for t in raw:
        if not isinstance(t, dict):
            continue
        name, cmd = str(t.get("name") or "").strip(), str(t.get("cmd") or "").strip()
        if not name or not cmd or "{url}" not in cmd:
            continue
        try:
            timeout = max(0, int(t.get("timeout") or 0))
        except (TypeError, ValueError):
            timeout = 0
        out.append({"name": name, "cmd": cmd, "timeout": timeout})
    cfg["ext_downloaders"] = out


def _apply_artist_circles(cfg, data):
    """画师→社团 映射（导入学习成果，跨重启保留）。"""
    if not isinstance(data.get("artist_circles"), dict):
        return
    cfg["artist_circles"] = {
        str(a): [str(c) for c in cs if str(c).strip()]
        for a, cs in data["artist_circles"].items() if isinstance(cs, list)}


def _apply_thumb_max(cfg, data):
    """缩略图缓存上限（字节）：config.json 可覆盖默认 200MB。"""
    if not data.get("thumb_max_bytes"):
        return
    try:
        cfg["thumb_max_bytes"] = int(data["thumb_max_bytes"])
    except Exception:
        pass


def save_config(cfg):
    # 原子写：临时文件 + os.replace。临时文件必须与目标**同目录**——os.replace
    # 跨盘符/跨文件系统直接抛错（测试把 CONFIG_FILE 指向 C 盘 tmp 时曾被静默吞掉）。
    try:
        data = {k: v for k, v in cfg.items() if v is not None}
        dst_dir = os.path.dirname(os.path.abspath(CONFIG_FILE)) or APP_DIR
        fd, tmp = tempfile.mkstemp(prefix="config_", suffix=".json", dir=dst_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, CONFIG_FILE)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception:
        # 保存失败绝不能静默：面板会提示"已保存"，而重启后设置全丢（跨盘符 os.replace 曾栽在这）
        log.exception("保存 config.json 失败（本次设置未落盘）：%s", CONFIG_FILE)


CFG = load_config()


def unique_path(path, taken=()):
    """目标已存在（或已被本轮计划占用）→ 追加 (2)/(3)… 后缀，绝不覆盖。"""
    if not os.path.exists(path) and path not in taken:
        return path
    stem, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f"{stem} ({i}){ext}") or f"{stem} ({i}){ext}" in taken:
        i += 1
    return f"{stem} ({i}){ext}"


def clean_term(term):
    """档案目录/词条名规范化：_ 一律按空格处理（与文件名规范化一致）；
    符号一并归一（全角括号→半角、顿号→半角逗号），使「A、B」与「A,B」归为同一档案名。
    依赖 djc_parse（纯解析模块，无副作用），导入失败时退化为内置规则。"""
    try:
        import djc_parse as _dp
        return _dp.normalize_symbols(_dp.clean_spaces(term))
    except Exception:
        return str(term or "").replace("_", " ").strip()


_SYM_DIR_CACHE = {"root": None, "ts": 0.0, "map": {}}


def _symbol_dir_map(root):
    """顶层档案目录的「符号归一 → 实际存在的目录名」映射（1 秒缓存，避免反复 scandir）。"""
    import time
    now = time.time()
    if _SYM_DIR_CACHE["root"] == root and now - _SYM_DIR_CACHE["ts"] < 1.0:
        return _SYM_DIR_CACHE["map"]
    m = {}
    try:
        import djc_parse as _dp
        for e in os.scandir(root):
            if e.is_dir():
                m.setdefault(_dp.normalize_symbols(e.name), e.name)
    except Exception:
        pass
    _SYM_DIR_CACHE.update({"root": root, "ts": now, "map": m})
    return m


def existing_archive_dir(term, root=None):
    """若根目录已有同名/规范名（_→空格、符号归一）一致的档案夹则沿用，否则返回规范名。
    app.py 的导入归档与爬虫归档共用此规则。
    符号变体命中：磁盘上已存在「A、B」而待落位名是「A,B」时沿用前者，
    不再另建一个仅符号不同的兄弟目录（真实库里 きのこのみ 那对目录即因此分裂）。"""
    root = root if root is not None else CFG.get("root", "")
    clean = clean_term(term)
    if not root:
        return clean
    for c in (term, clean):
        if c and os.path.isdir(os.path.abspath(os.path.join(root, c))):
            return c
    hit = _symbol_dir_map(os.path.abspath(root)).get(clean)
    if hit:
        return hit
    return clean or "未分类"


def merge_pip_common():
    """jm 系脚本（crawl_jm_ids / crawl_jm_direct）import jmcomic 前必须调用。
    jmcomic 自带顶层工具包 `common`（time_stamp/field_cache/ProxyBuilder…），
    会被本文件（项目同名模块，脚本目录恒在 sys.path[0]）遮蔽——这里从
    site-packages 加载 pip 版，把公开 API 合并进本模块，两包共用一个模块名。
    本文件自己的公开名不被覆盖；jmcomic 的公开名仅在本文件没有同名时并入。"""
    import importlib.util
    src_spec = None
    for sp in list(sys.path):
        if not sp or 'site-packages' not in sp.replace(os.sep, '/').lower():
            continue
        for cand in (os.path.join(sp, 'common', '__init__.py'),
                     os.path.join(sp, 'common.py')):
            if os.path.isfile(cand):
                src_spec = importlib.util.spec_from_file_location('common', cand)
                break
        if src_spec is not None:
            break
    if src_spec is None:
        return False
    pip_mod = importlib.util.module_from_spec(src_spec)
    saved = sys.modules.get('common')
    sys.modules['common'] = pip_mod        # pip common 内部的绝对自导入需解析到自己
    try:
        src_spec.loader.exec_module(pip_mod)
    except Exception:
        return False
    finally:
        sys.modules['common'] = saved
    for name in dir(pip_mod):
        if not name.startswith('_') and name not in globals():
            globals()[name] = getattr(pip_mod, name)
    return True
