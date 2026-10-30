#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
禁书目录 Index (Index) —— 本地同人志文库 Web 系统（Flask 版）
====================================
功能：
  * 按“社团”组织浏览：首页展示所有社团，封面取该社团下修改日期最晚作品的首页图
  * 社团详情页：展示其下全部作品，封面正下方用 Tag 显示 (个人名)
  * 自动标签：从文件名 () 提取并分类 —— 展会(C97/C100…)、原作(原神/Fate…)、画师
  * 标签云（二级界面）：按类别浏览全部标签，点击任意标签展示所有社团中含该标签的作品
  * 规范化命名时自由文本 "_" 自动替换为空格（原作词条等规范名除外）
  * 待定词条（裸 [a]）：能匹配社团/个人 → 归入对应档案；否则以词条本身建立新档
  * 阅读器支持 webm 动态/视频页（图片页与 webm 页可同部混排）
  * 点击封面/标题直接调用系统默认图片查看器 / 文件管理器打开

目录结构（建议先运行 migrate.py 把 1区 迁移为社团目录）：
  根目录/(社团名)/(作品).zip|.rar…         ← 压缩包即作品
  根目录/(社团名)/(作品名)/图片…            ← 文件夹作品（支持章节子目录）
  根目录/(个人词条)/…                      ← 待定词条建立的新档
  _app/_inbox/…                           ← 收件箱：无可识别词条 / 被解散社团的作品（面板提案式入库）
  根目录/_app/…                           ← 本程序（app.py/static/config.json 等），扫描时自动跳过
  ※ 程序与文库分目录：app.py 必须位于 <文库根>/_app/ 内，默认文库根 = _app 的上级目录

命名解析（详见 djc_parse.py）：
  * 社团名 = 文件名最外层 [] 内全部内容
  * 个人名 = [] 内第一个 () 的内容
  * 标签 = 文件名中所有 ()，自动分类为 展会/原作/画师/其他

用法：
  pip install -r requirements.txt
  python app.py                （或双击 Index.exe 用启动面板）
  python app.py --root "D:\同人志" --port 9000
  python app.py --no-browser  （测试/脚本用：起服务但不弹浏览器）

启动开浏览器行为（3.6.21，用户定调"测试进程别弹、正式进程要弹"）：
  * 默认：启动 1 秒后用系统默认浏览器打开面板（正式进程就该看得见）。
  * --no-browser：本次启动不弹（测试进程/静默部署用）。
  * INDEX_NO_BROWSER=1：环境变量同效（我的后台测试任务用这个，忘了带参数也不弹）。
  * config.json 的 "no_browser": true 同样抑制，但该字段会影响所有启动方式——
    只建议给"整机都不要弹"的场景，日常别设。
  * --open-browser：3.6.18 引入的显式开关，现已是默认行为，保留仅为兼容旧脚本/旧卡片。
  * 3.6.18~3.6.20 的"默认不弹 + 唤 WorkBuddy 前台"已撤销：workbuddy:// 深链无法把
    内置浏览器导到面板地址，结果就是正式进程哪里都弹不出来（用户报障）。
"""
import argparse
import hashlib
import io
import json
import logging
import os
import random
import re
import unicodedata
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
import zipfile
from collections import OrderedDict
from logging.handlers import RotatingFileHandler

from werkzeug.datastructures import FileStorage

from flask import Flask, g, jsonify, request, send_file, send_from_directory

sys.dont_write_bytecode = True

# ---------------------------------------------------------------
# 版号三轴（2026-09-21 起「分轴版号」；2026-09-22 起废止全部"延迟升号"约定）
#   ① 面板轴 PANEL_VERSION：服务端 + 网页（同进程部署，永远一起走）。改面板/网页就升这里
#      （修 bug → patch，新功能 → minor），**不必等安卓 APP 发版**；部署 = 重启面板。
#   ② APP 轴：安卓自己的 versionName + versionCode，只写在 android/app/build.gradle.kts，
#      **每次改动当场升号并派发**（不攒批、不分 beta/正式；versionCode 必须单调递增）。
#   ③ 接口轴 SERVER_API_LEVEL / MIN_APP_API：APP 与面板之间唯一需要"对齐"的东西，
#      连上后面板与 APP 各自用它做**机器可判**的兼容性检查。只在破坏性接口改动时 +1
#      （新增字段不算）。
# VERSION 文件与本常量同源（面板版本），启动器标题读它。
# ---------------------------------------------------------------
PANEL_VERSION = "3.6.175"
APP_VERSION = PANEL_VERSION      # 历史名兼容（曾用于"全系统一个号"，现仅代表面板版本）
SERVER_API_LEVEL = 1
MIN_APP_API = 1
_PROC_START = time.time()        # 本进程启动时刻：用来发现"代码改过但没重启"
# 扫描时忽略的目录（程序自身文件/缓存/迁移源目录；程序目录名按实际位置动态加入，改名免改代码）
IGNORE_DIRS = {"static", "templates", "__pycache__", ".git", ".idea", "node_modules", "venv",
               ".thumb_cache", "1区", "_inbox",   # _inbox：历史遗留位置（文库根/_inbox）；
               "_logs", "_state", "_cache"}       # 3.7 Stage3：运行时产物目录（正常在 _app 内，
               # 此处登记仅为「ROOT 被直接指向 _app」时也不当作作品扫描）
               # 3.6.3 起收件箱已迁到 _app/_inbox —— 留这条是为了让旧升级上来的残留目录不参与扫描

APP_DIR = os.path.dirname(os.path.abspath(__file__))
IGNORE_DIRS.add(os.path.basename(APP_DIR))
# 配置区常量（ROOT_DIR/PORT/LIBRARY_NAME）与 config.json 读写已抽至 common.py（P2-8，与爬虫共用）
sys.path.insert(0, APP_DIR)
import common                  # 词条库重载须按 common.CONFIG_FILE 取径（conftest 隔离的是它）
from common import (ROOT_DIR, PORT, LIBRARY_NAME, DEFAULT_LIB_ROOT, CONFIG_FILE,   # noqa: E402
                    CFG, load_config, save_config, unique_path,
                    LOG_DIR, STATE_DIR, CACHE_DIR, ensure_dir,
                    clean_term as _clean_term, existing_archive_dir as _existing_archive_dir)
import meta_store as meta   # noqa: E402   3.0 元数据层（SQLite 唯一事实源）

# ---- waitress 探测（3.3.0：生产 WSGI 服务器；缺失时回退 werkzeug dev server）----
try:
    from waitress.server import create_server as _waitress_create
    _WAITRESS_OK = True
except ImportError:
    _waitress_create = None
    _WAITRESS_OK = False


sys.path.insert(0, APP_DIR)
import djc_parse as _dp  # noqa: E402
from djc_parse import (parse_filename, load_originals, normalize_filename, analyze_filename,
                         primary_bracket_info, bare_of, personal_of,
                         strip_wrappers, repair_name)  # noqa: E402

# 模块日志器（统一入口）：3.3.0 就搭好了日志设施，但此后 6233 行里只有 5 处日志调用、
# 43 处 except 把异常静默吞掉——设施成了摆设，故障无从排查。3.6.24 起，凡是"本该
# 可见的失败"一律经此记录（资源清理类失败仍保持静默，避免制造噪音）。
log = logging.getLogger(__name__)

# ---- 可选依赖探测（Pillow / rarfile）已抽至 panel/deps.py（3.7 结构重构）----
from panel.deps import PIL_OK, PILImage, RAR_AVAILABLE, rarfile            # noqa: E402,F401

# ---- 路径 / 媒体名工具与常量（抽至 panel/paths.py）----
from panel.paths import (                                                  # noqa: E402
    IMAGE_EXTS, VIDEO_EXTS, ANIM_EXTS, PAGE_EXTS, ARCHIVE_EXTS, MAX_DEPTH,
    natural_key, media_kind, is_image_name, scan_images_and_archives, _entry_size,
    list_zip_images, list_rar_images, work_mtime, _archive_page_entries, _cached_size,
    page_media_name, mime_for, _is_root_loose)

# ---- 压缩包句柄 / 页缓存 / 视频临时文件（抽至 panel/archive.py）----
from panel.archive import (                                                # noqa: E402
    ARCHIVE_OPEN_MAX, PAGE_CACHE_MAX_ITEMS, PAGE_CACHE_MAX_BYTES,
    _archive_handles, _page_cache, _page_cache_bytes, _archive_lock,
    _page_cache_lock, _path_locks, _path_lock, _archive_handle, _archive_forget,
    _archive_forget_tree, _archive_quiesce, _rename_with_retry, _move_with_retry,
    _path_size, _archive_read, _page_cache_get, _page_cache_put, page_source,
    VIDEO_TMP_DIR, VIDEO_TMP_MAX, purge_video_tmp, _video_tmp_file)

# ---- 封面 / 缩略图 / 低带宽图（抽至 panel/images.py）----
from panel.images import (                                                 # noqa: E402
    cover_cache, COVER_CACHE_MAX, COVER_CACHE_MAX_BYTES, _cover_cache_bytes,
    COVER_LOCK, THUMB_DIR, THUMB_MAX_BYTES, LOW_DIR, LOW_MAX_BYTES,
    LOW_PAGE_SIDE, LOW_ANIM_SIDE, LOW_ANIM_FRAMES, LOW_ANIM_COLORS,
    LOW_QUALITY, LOW_KEEP_RATIO, _TS_PATH_CACHE, _tailnet_direct_map,
    _is_tailnet_ip, client_wants_low, _low_cache_path, _low_disk_key,
    _frame_durations, lowres_image, _low_cache_write, prune_low_cache,
    make_thumbnail, _thumb_disk_key, _cover_disk_write, _cover_cache_put,
    cover_payload, read_cover, prune_thumb_cache)

# ---- 纯文件内容工具（补入 panel/paths.py）----
from panel.paths import _sniff_ext, _sha1_file, _is_part_name                # noqa: E402

# ---- 音声作品：音频轨 / lrc（抽至 panel/audio.py）----
from panel.audio import (                                                    # noqa: E402
    AUDIO_EXTS, LRC_EXTS, _AUDIO_MIME, _RE_LRC_TIME, _RE_LRC_OFFSET,
    _work_audio_entries, _decode_text_bytes, _parse_lrc_bytes, _audio_lrc_for)

# ---- 页面组织工具（抽至 panel/pages.py）----
from panel.pages import _RE_VERSION_EXT, _page_versions                      # noqa: E402

# ---- 进程内唯一可变状态（3.6.49 Stage5；原 `_INDEX` / `_INDEX_LOADED` / `_INDEX_KEYS`）----
from panel.state import LibraryState, NORM_LOGIC_VERSION, ARRIVAL_VERSION       # noqa: E402

# 进程内唯一可变状态实例（唯一持有者；任何模块都不得再赋值 state 本身）
state = LibraryState()

# ---- 「增补信息 → 规范文件名」纯函数（抽至 panel/naming.py，3.6.45 Stage4）----
from panel import naming as _naming                                         # noqa: E402


# ---------------------------------------------------------------
# 配置（load_config / save_config / CFG 见 common.py，与爬虫脚本共享单一来源）
# ---------------------------------------------------------------
def _fold_alias_chain(name, aliases):
    """沿别名表折叠到终点（visited 防环）。

    3.6.39：**别名链必须折叠到终点，不能只叠一层**。用户场景：
    ブルーアーカイブ → Blue Archive 已登记；随后把 Blue Archive 分区改名为「蔚蓝档案」，
    再登记 Blue Archive → 蔚蓝档案。此时 A→B→C 成链，若解析映射只写 A→B，
    重新导入含 ブルーアーカイブ 的作品会产回旧名 B 的标签——作品进不了改名后的
    分区，已改名的旧分区还被复活（已用回归测试复现：{蔚蓝档案:1, Blue Archive:2}）。
    单一实现：_reload_originals（解析映射）与 _canon_original_name（端点归一）共用，
    避免两处逻辑漂移。"""
    cur = (name or "").strip()
    seen = set()
    while cur in aliases and cur not in seen:
        seen.add(cur)
        cur = aliases[cur]
    return cur


def _reload_originals():
    """重载原作词条库（3.6.19）：config 名单 + DB 原作别名（变体 → 规范名）。
    别名后叠加、优先于词条名单——用户显式登记的归并意图最强。
    3.6.39：别名的正名侧沿链折叠到终点（A→B、B→C 时 A 映射到 C，不是 B）。
    返回 (originals, 映射)，并同步 djc_parse 模块映射。
    3.6.49 Stage5-2：落点从模块级全局改为 `state.originals` / `state.norm_to_canon`
    （唯一状态持有者，见 panel/state.py）。"""
    originals, mapping = load_originals(common.CONFIG_FILE)
    try:
        aliases = meta.original_aliases()
        for alias, canon in aliases.items():
            mapping[_dp._norm(alias)] = _fold_alias_chain(canon, aliases)
    except Exception:
        log.exception("加载原作别名失败（别名归并可能不生效）")
    state.originals = originals
    state.norm_to_canon = mapping
    _dp.NORM_TO_CANON = mapping      # 同步给规范化引擎（normalize_filename）
    return originals, mapping


_reload_originals()

# 仅导入模式（--import-only）：只开放 首页+静态资源 / 配置 / 导入 / 爬虫 四个入口，
# 其余浏览/阅读 API 一律返回 403，前端只渲染「导入文件」与「爬虫管理」两个界面。
IMPORT_ONLY = False
# 3.6.118 测试模式（--safe-images）：封面/页面/探针封面一律回占位图（截图审查防护）
SAFE_IMAGES = False


# ---------------------------------------------------------------
# 扫描
# ---------------------------------------------------------------


# 3.6.151：删 touched（最近更新）档、加 size（占用空间，查重用）。
# 本表必须与 services/group_order.sort_groups 的分支一一对应——不在表里的 sort 参数
# 会被路由**静默**当成 updated（前端点了「文件大小」，拿到的却是入库时间排序）。
GROUP_SORTS = ("updated", "created", "count")   # 3.6.166：size 档已删（大小只在分区内按作品排）


# ---------------------------------------------------------------
# 文库缓存
# ---------------------------------------------------------------
# 3.6.51 Stage5-3：库数据缓存迁入 state.lib（原 `LIB`），扫描进度迁入 state.scan_state（原 `SCAN_STATE`），
# 后台重扫 single-flight 迁入 state.rescan（原 `_RESCAN`）。模块级不再保留同名全局，避免两份状态。
LIB_LOCK = threading.Lock()
SCAN_LOCK = threading.RLock()    # 3.3.0 RLock：变更型端点整个请求期持锁，内部嵌套 get_library 需可重入
# 扫描时发现的「无归属」作品（根目录无任何词条的散包、遗留「未分类」目录里的作品）——
# 它们不该进文库，由 _inbox_sync 搬到 _app/_inbox 变成待确认项。
# 扫描本身不做移动（避免 IO 副作用进热路径），只登记，同步时统一处理。


# ---------------------------------------------------------------
# 增量扫描持久化索引（library_index.json）
# 键 → 作品元数据。命中即跳过打开压缩包枚举页名（扫描耗时大头）：
#   * 压缩包作品键：a|mtime_ns|size|绝对路径 —— 文件任何变动都会改变键
#   * 文件夹作品键：f|sha1(全树 (相对名, mtime_ns) 签名)|绝对路径 —— 树内任何
#     新增/删除/改名/修改都会改变签名（目录枚举本身廉价，每次都做）
# originals 词条库变化 → 解析结果可能不同 → 整个索引作废，全量重扫。
# 索引损坏/不合法 → 忽略，等同全量重扫。缓存内为 JSON 形态（cover/tags 为
# list），命中时转换回内部形态（tuple），保证与实时扫描结果逐字段一致。
# ---------------------------------------------------------------
INDEX_FILE = os.path.join(STATE_DIR, "library_index.json")   # 3.7 Stage3：运行时状态归入 _app/_state/
# 3.6.49 Stage5：扫描缓存收进状态对象（唯一持有者，见 panel/state.py）。
# 旧全局 → 新字段：`_INDEX` → state.index、`_INDEX_LOADED` → state.index_loaded、
# `_INDEX_KEYS` → state.index_keys（测试打桩点同步迁到对象属性）。
# 不要在本文件或其他模块再赋值 state 本身（那会分叉成两份状态）。
INDEX_LOCK = threading.Lock()


# ---------------------------------------------------------------
# 区域封面覆盖（社团/画师）：用户在社团页/画师页把某作品首图设为该区域封面。
# 存作品 (group, work)，渲染时按其首图动态取封面 —— 首图删除后自动跟随新首图，
# 作品删除则覆盖失效、回退到派生封面。与扫描缓存解耦，单独落盘，避免原点库变动丢失。
# ---------------------------------------------------------------
REGION_COVERS_FILE = os.path.join(STATE_DIR, "region_covers.json")
# ---- 区域封面（3.6.55 Stage7 抽至 services/covers.py；此处再导出保持 app.* 命名面）----
from services.covers import (                                             # noqa: E402
    _valid_cov, _region_covers_load, _region_covers_save, _region_cover_get,
    _region_cover_set, _region_cover_migrate, _resolve_region_cover,
    _apply_artist_cover, _apply_original_cover,
)
   # 3.7 Stage3：归入 _app/_state/
REGION_COVERS_LOCK = threading.Lock()


# 区域封面覆盖的分桶（3.6.19 新增 original：原作分区也可"设为封面"）
_COVER_BUCKETS = {"circle": "circles", "artist": "artists", "original": "originals"}


INBOX_GROUP = "收件箱"      # **伪**社团名：收件项在阅读器/增补信息中以「收件箱/<收件项id>」打开。
                           # 它不是文库里的社团（磁盘上没有这个目录），文件实体在 _app/_inbox 里。


# 3.6.13：作品 key 的 owner 反查索引。分组改按圈子名后，作品的展示群组名（circle）
# 可能≠其 key 的 owner（真实目录 _group，如「富士やま」目录归入 TOZAN_BU 圈子）；
# 画师页/续读/收藏按「目录名+作品名」寻址时 find_group 会落空，用这里兜底——既让作品
# 打得开，又保证阅读上报键（group/name）与 DB key 一致、进度不脱节。缓存随 groups 身份失效。


# ---------------------------------------------------------------
# 封面/缩略图/低带宽图、压缩包页缓存、路径与媒体工具 已抽至 panel/ 包
# （3.7 结构重构）。此处通过顶部 import 再导出，保持 app.* 命名面不变。
# ---------------------------------------------------------------


# ---------------------------------------------------------------
# API 投影 / 标签 / 推荐
# ---------------------------------------------------------------


# ---------------------------------------------------------------
# 打开本地文件 / 文件夹
# ---------------------------------------------------------------


# ---------------------------------------------------------------
# 未分类整理：重命名 + 自动归档
# ---------------------------------------------------------------


# ---------------------------------------------------------------
# Flask 应用
# ---------------------------------------------------------------
app = Flask(__name__, static_folder="static", static_url_path="/static")

# ---- 日志设施（3.3.0）：此前服务端零日志、65 处 except 静默吞错，出问题无从排查 ----
# RotatingFileHandler 写 _app/_logs/panel.log（2MB×3 轮转）；只在 main() 里初始化，
# 测试（conftest 直接用 test_client，不经 main）不产生文件句柄。
LOG_FILE = os.path.join(LOG_DIR, "panel.log")   # 3.7 Stage3：日志归入 _app/_logs/


@app.errorhandler(Exception)
def _on_unhandled(e):
    """全局异常兜底：记录完整堆栈到 panel.log，API 请求返回统一 JSON（不再静默 500）。"""
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    app.logger.exception("未处理异常 %s %s", request.method, request.path)
    return jsonify({"ok": False, "message": "服务器内部错误，详情见 panel.log：" + str(e)}), 500

# token 开启后无需鉴权的入口：首页/静态资源只含页面壳（无数据），数据类接口一律校验
# 主题背景图与图库图片公开：<img> 标签带不了 X-Token 头，图库列表等数据接口仍要令牌
PUBLIC_ENDPOINTS = {"index", "static", "api_theme_bg_get", "api_theme_gallery_image",
                    "api_theme_hero_get",
                    # 3.6.144 扫码配对：新手机还没有任何令牌，claim 只能靠票据本身鉴权
                    # （128 bit 随机 + 120 秒 + 一次性）。不放进来的话"第一次绑定"永远调不通。
                    "api_pair_claim", "api_pair_attest"}

# ---- 3.3.0 文件变更操作与扫描互斥 ----
# SWR 之后重扫在后台线程跑；若与写端点的文件操作（移动/删除/解压）并发，扫描器枚举
# 页名时打开压缩包的句柄会让 _move_with_retry 撞 WinError 32。旧设计靠 data=None 迫使
# 下一个请求同步过 SCAN_LOCK 隐式串行；现在显式化：变更型端点（凡直接或间接调用
# _lib_touch 的）整个请求期持有 SCAN_LOCK，后台重扫与 force 重扫同样在其上排队——
# 文件操作与扫描永远不重叠。
#
# 3.6.45（审计 P1-3）：清单原先是**手工维护的字面量集合**，正确性依赖"新增写端点的人
# 记得回来改 45 行外的另一个 set"——它已经腐坏过（api_supplement_info/title 各写两遍，
# 另有 3.6.36 加的端点因自锁风险被迫删掉）。现在改为**定义处登记**：给端点函数加
# `@mutating`，清单由装饰器填充，遗漏在导入期即暴露。测试
# tests/test_v330_swr_cache.py::test_mutation_gate_covers_all_lib_touch_endpoints 仍按
# 调用图闭包反查，双向对账（漏登记 / 登记了却不再写）都报错 —— 该测试是这条不变量的守门人。
# 登记表与装饰器已抽到 panel/http.py（路由拆分后 routes/*.py 也要用同一个对象）。
# 这里用 **别名** 再导出：门禁与测试仍读 app._MUTATING_ENDPOINTS（同一 set 对象）。
from panel.http import MUTATING_ENDPOINTS as _MUTATING_ENDPOINTS, mutating   # noqa: E402,F401


@app.before_request
def _mutate_gate_begin():
    if request.endpoint in _MUTATING_ENDPOINTS:
        SCAN_LOCK.acquire()
        g._mutate_gate = True


@app.teardown_request
def _mutate_gate_end(exc):
    if g.pop("_mutate_gate", False):
        SCAN_LOCK.release()


_AUTH_401_AT = 0.0       # 401 诊断日志的节流时钟（60 秒最多一条，免得图片请求刷屏）


def _auth_reject(given):
    """鉴权失败时留一条可查的痕迹（3.6.168）。

    2026-10-29 的故障是"设备令牌明明还在手机里、所有设备却恒定 401"，而日志里
    **一个字都没有**——拒绝请求走得完全安静，人只能靠猜。这里记下"谁、要什么、
    有没有带令牌、像不像设备令牌"，下次一眼能分出两种完全不同的病因：
    链路根本没带令牌（`无`）／服务端设备表认不出（`设备令牌` 却仍被拒）。
    """
    global _AUTH_401_AT
    now = time.time()
    if now - _AUTH_401_AT < 60:
        return
    _AUTH_401_AT = now
    from services import netaddr
    who = netaddr.real_client(request.remote_addr, request.headers.get("X-Forwarded-For"))
    kind = "无" if not given else ("设备令牌" if given.startswith("dev-") else "非设备令牌")
    log.warning("鉴权拒绝：%s %s ← %s（携带：%s）", request.method, request.path, who, kind)


@app.before_request
def _token_gate():
    """远程访问鉴权：主令牌 **或** 设备令牌，其余一律拒绝。

    **fail-closed（3.6.147）**：旧版在主令牌为空时直接 `return None`，等于"删掉主令牌
    = 远程端口裸奔"。现在主令牌可以不存在（只用扫码配对），但鉴权不能因此消失——
    没有主令牌时只接受设备令牌，两者都没有就 401。

    令牌只为本机之外的访问设防（Tailscale/局域网手机端）。
    token 存在时，除页面壳外所有接口须携带 X-Token 请求头或 ?token= 查询参数
    （<img>/<video> 标签无法带自定义头，走 query）；本机访问一律免门禁——
    远程进程虽监听 0.0.0.0:8766，但只有本机能走 127.0.0.1，外部设备到不了回环。

    **"本机"必须按真实客户端判，不能直接看 `request.remote_addr`（3.6.148 修）**：
    远程访问改由 Tailscale serve 终结 TLS 后，tailscaled 恒从 127.0.0.1 反代，
    照旧判会把**tailnet 内所有设备**当成本机放行——实测无令牌 `GET /api/library`
    返回 200 与全量数据，比加 HTTPS 之前更宽。判定规则见 `services/netaddr.py`。
    """
    from services import netaddr
    token = CFG.get("token") or ""
    if netaddr.is_local(request.remote_addr, request.headers.get("X-Forwarded-For")):
        return None
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    given = request.headers.get("X-Token") or request.args.get("token") or ""
    # 恒时比较，避免时序侧信道泄露 token 前缀。
    # `token and` 不能省：两边都为空时 compare_digest("", "") 返回 True —— 那等于放行一切。
    if token and secrets.compare_digest(given.encode("utf-8"), token.encode("utf-8")):
        return None
    # 3.6.144：设备令牌（扫码配对用一次性票据换来的长期凭据，`dev-` 前缀）。
    # 它与主令牌**并列**有效：某台手机泄露时只吊销那一台，不必改主令牌把所有设备一起踢下线。
    from services import pair_devices
    device_id = pair_devices.verify(common.STATE_DIR, given)
    if device_id:
        pair_devices.touch(common.STATE_DIR, device_id)   # 最近使用时间，5 分钟节流写盘
        return None
    _auth_reject(given)
    return jsonify({"ok": False, "message": "需要访问令牌（X-Token）或已配对设备"}), 401


CFG_PORT_BIND = None     # 显式 --port 启动时的绑定端口（仅显示用，不落盘 config.json）


# ---------------------------------------------------------------
# 面板自重启（2026-09-22）：Python 只在启动时加载代码，改完 app.py 必须重启才生效 ——
# 这个坑已经让"改了却没生效"发生过两次。现在面板自己知道"代码已更新"，网页顶部提示 + 一键重启。
# ---------------------------------------------------------------
_WATCH_FILES = ("app.py", "djc_parse.py", "common.py", "meta_store.py", "index_launcher.py", "VERSION")
# 3.7 结构重构：panel/ 包内模块同样是面板代码，改动后也须重启才生效。
# 3.7.55：services/ routes/ crawlers/ 同理——此前只盯 app.py 与 panel/，
# 改这三处的代码**不会**触发"代码已更新"提示，也不会让一键重启真的重启
# （_panel_needs_restart 判否 → 端点直接回"无需重启"），
# 表现为"改完测试接口还是老行为"，排查过很久。
for _pkg in ("panel", "services", "routes", "crawlers"):
    try:
        _WATCH_FILES += tuple(_pkg + "/" + _n
                              for _n in sorted(os.listdir(os.path.join(APP_DIR, _pkg)))
                              if _n.endswith(".py"))
    except OSError:
        continue                      # 目录不存在（精简部署）→ 跳过，不影响其它包


# ---- 面板自重启（3.6.56 Stage7 抽至 services/panel_admin.py；再导出保持 app.* 命名面）----
# ---- 原作分区归一（3.6.56 Stage7 抽至 services/originals.py；再导出保持 app.* 命名面）----
# ---- 词条身份归一（3.6.57 Stage7 抽至 services/identity.py；再导出保持 app.* 命名面）----
# ---- 删除/改名/合并（3.6.58 Stage7 抽至 services/manage.py；再导出保持 app.* 命名面）----
# ---- inbox（Stage7 抽至 services/inbox.py；再导出保持 app.* 命名面）----
from services.inbox import (  # noqa: E402
    _inbox_pseudo_work, _find_work_by_key, _inbox_dir, _inbox_parts, _find_content_dup,
    _inbox_propose, _unfiled_collect, _inbox_sync, _inbox_repair_states, _inbox_confirm_one,
)
# ---- 导入流水线（3.6.80 从 inbox.py 拆至 services/inbox_import.py；再导出保持 app.* 命名面）----
from services.inbox_import import (  # noqa: E402
    _circle_authors, _other_info_of, _sanitize_note, _safe_subpaths, _import_status,
    _import_resolve_and_name, _import_process, _import_sort, _import_sniff_ext,
    _find_batch_dup, _import_archive, _import_single, _import_resolve_folder, _import_group,
)
# ---- library（Stage7 抽至 services/library.py；再导出保持 app.* 命名面）----
# ---- scan / coop（3.6.60 Stage7 / 3.6.69；再导出保持 app.* 命名面）----
from services.scan import (  # noqa: E402
    _normalize_identity, _reresolve_cached_work, make_work, collect_works_in_dir,
    build_group, _work_belongs, _archive_dest_dir, _merge_alias_circles, scan_groups,
)
# 3.6.151：社团「入库时间记账 + 排序」拆到 services/group_order.py（scan.py 顶到 400 行预算）；
# 旧名字在这里做别名，`h()._group_arrival(...)` / `app.sort_groups(...)` 的调用面不变。
from services.group_order import (  # noqa: E402
    group_arrival as _group_arrival, groups_prune as _groups_prune, sort_groups,
)
from services.coop import _coop_primary, _work_coop_circles, _build_coop_groups  # noqa: E402
# ---- index_cache（3.6.60 Stage7；再导出保持 app.* 命名面）----
from services.index_cache import (  # noqa: E402
    _lib_touch, _scan_ctx, _ctx_stale,
    _kick_rescan, _originals_hash, _index_load, _prime_known_registry,
    _index_save, _work_to_cache, _work_from_cache,
    _index_get_work, _index_put_work, _merge_manual_originals,
    _do_scan, get_library,
)
# ---- queries（3.6.60 Stage7；再导出保持 app.* 命名面）----
from services.queries import (  # noqa: E402
    find_group, _work_by_owner_key, find_work,
    _work_key, _group_physical_dir, _work_ver,
    public_work, public_group, tags_index,
    _work_authors, search_authors, daily_recommendations,
)
# ---- opener（Stage7 抽至 services/opener.py；再导出保持 app.* 命名面）----
from services.opener import (  # noqa: E402
    _delayed_unlink, open_path, open_work_folder,
    open_work_image,
)
# ---- appenv（Stage7 抽至 services/appenv.py；再导出保持 app.* 命名面）----
from services.appenv import (  # noqa: E402
    setup_logging, config_payload, _browser_open_suppressed, client_scope,
)
# ---- server（Stage7 抽至 services/server.py；再导出保持 app.* 命名面）----
from services.server import (  # noqa: E402
    main,
)
from services.manage import (  # noqa: E402
    _delete, _delete_once, _invalidate_after_delete,
    _path_in_root, _path_same_or_under, _purge_circle_dir,
    _split_work_name, _work_group_name, _resolve_archive_term,
    _apply_rename, _merge_circle_into, _clean_empty_dirs,
    _same_path, _same_size_file, _same_content,
)
from services.identity import (  # noqa: E402
    _canon_circle, _registry_from_lib, _term_key, _term_index,
    _main_circle_of, _canon_circle_resolved, _resolve_bare, _author_aliases,
    _circle_aliases, _original_aliases, _canon_circle_name, _canon_author,
    _canon_author_resolved,
    _ensure_known_registry, _known_learn, _dissolved_circles, _term_whitelist,
    _term_blacklist, _term_blacklisted,
    _pixiv_title, _rescue_candidates, _rescue_personal, _merge_orphan_terms,
    _author_has_circle,
    _skip_like_term,
    resolve_bare_term,
)
from services.originals import (                                          # noqa: E402
    _loose_term, _canon_original, _canon_original_name, _originals_config_set,
)
from services.panel_admin import (                                        # noqa: E402
    _disk_panel_version, _panel_needs_restart, _validate_fresh_code,
    _exec_self, _schedule_exec,
)


# 进程级常驻词条库：初始由全库扫描 + config.artist_circles 构建，
# 导入/改名解析出 [C (P)] 时即时学习 —— 修复「同批导入中，先落盘的映射对后续文件不可见」
# 导致待定词条新建重复目录（つかこ/くりもも 案例）。


# 待定词条印证索引（3.6.12）：每轮扫描刷新一次，扫描期内复用（DB 只查两条，毫秒级）。
#   circles: 归一键 -> 社团规范名   —— **只认 works.circle**（文件名里确实解析出
#            [社团 (画师)] / [社团] 结构）。目录名（circles 表 / group_name）一概不算：
#            文库里大量目录其实是画师名（如「富士やま」），把它们当社团会把画师反判成社团。
#   authors: 归一键 -> 画师规范名（work_authors ∪ artist_circles 的 author）
#   ac:      画师 -> 其社团候选（artist_circles ∪ config 旧值，已剔除"画师→自己"的脏条目）
_TERMS_TTL = 900.0


# 词条黑名单：命中（子串、不区分大小写）的词条不视为社团名/个人名/待定词条。
# 内置规则 + config.json 的 term_blacklist 可自行追加（如 ["某词"]）。
_TERM_BLACKLIST_BUILTIN = ["重嵌", "digital", "無邪気", "dl版", "風的工房", "pixiv"]
# 豁免名单：命中豁免词的词条即使撞上黑名单也照常采纳（如真实社团 Digital Lover
# 含 "digital" 子串）。config.json 的 term_whitelist 可自行追加。
_TERM_BLACKLIST_EXEMPT = ["digital lover"]


# ---------------- 别名登记（Hydrus siblings）：多名归并到正名 ----------------
# 3.6.11 起同一套接口服务两种对象：**笔名（画师）** 与 **社团名**——
#   * kind=author（默认）：老行为，作品的作者字段/标签归并到正名画师；
#   * kind=circle（新增）：被登记为别名的社团不再单列，其作品并入正名社团（见
#     _merge_alias_circles；作品 path 与 key 不变，随时可撤销）。
_ALIAS_KINDS = ("author", "circle", "original")


UPLOAD_TMP = os.path.join(CACHE_DIR, "upload")   # 3.7 Stage3：上传分块临时目录归入 _app/_cache/


# ---------------------------------------------------------------
# 多版本作品检测已抽至 panel/pages.py（3.7 结构重构）。
# ---------------------------------------------------------------


# ---------------------------------------------------------------
# 音声作品（音频轨 / lrc 解析）已抽至 panel/audio.py（3.7 结构重构），
# 端点保留在此。
# ---------------------------------------------------------------


# ---------------------------------------------------------------
# 删除作品 / 社团（右键菜单）—— 一律直接删除，不再经由系统回收站（不可还原）
# ---------------------------------------------------------------


# ---------------------------------------------------------------
# （3.2.1 共享文档功能已按用户要求整体移除——原 /api/doc 读写与 doc-to-crawl 识别）
# ---------------------------------------------------------------

# ---------------------------------------------------------------
# 爬虫管理：subprocess 拉起独立脚本（保持「爬虫不 import app」的既有边界）。
# 3.6.7：三个任务（wnacg 主爬 / JM索引 / JM直连）可同时独立运行，各自一个子进程、
# 一份断点 state、一个日志文件、一套清单；互不排斥也互不污染。
# 断点进度：wnacg 用 crawl_state.json（清单级），jmdl 用 crawl_state_jmdl.json；
# jm 索引模式无断点概念（每次全量重跑，结果落 jm_id_map.txt）。
# 日志：wnacg 脚本自写 crawl_log.txt；jm/jmdl 只 print，stdout 由本模块分别接进
# crawl_log_jm.txt / crawl_log_jmdl.txt（否则三任务并发时日志会交错成乱码）。
# ---------------------------------------------------------------
# ---- 爬虫状态/清单/日志已拆到 services/crawl.py（3.6.25）----
from services.crawl import (                                   # noqa: E402
    _CRAWL_LIST_WNACG, _CRAWL_LIST_JM, _CRAWL_LIST_JMDL_T, _CRAWL_LIST_JMDL_I,
    _CRAWL_LIST_NH, _CRAWL_LIST_NHDL, _CRAWL_LIST_EH, _CRAWL_LIST_INDEX,
    _CRAWL_LIST_EXT,
    _CRAWL_STATE_FILE, _CRAWL_STATE_FILE_JMDL, _CRAWL_STATE_FILE_EH, _CRAWL_LOG_FILE,
    _CRAWL_LOG_FILE_JM, _CRAWL_LOG_FILE_JMDL,
    _CRAWL_LOG_FILE_NH, _CRAWL_LOG_FILE_NHDL, _CRAWL_LOG_FILE_EH, _CRAWL_LOG_FILE_EXT,
    _CRAWL_TASKS, _CRAWL_LOCK, _CRAWL_KINDS,
    _CRAWL_LOG_TAIL_LINES, _CRAWL_LOG_READ_MAX,
    _crawl_state_file, _crawl_log_file, _crawl_proc,
    _crawl_log_append, _crawl_log_tail, _crawl_log_since,
    _crawl_state_counts, _crawl_write_list, _crawl_list_count,
    _crawl_task_snapshot,
    crawl_log_cursor, crawl_mark_log_start, crawl_clear_log_cursor,
    crawl_script_path, available_kinds,
)

# ---- 全爬虫域的两段式任务引擎（3.7.58）----
# 五个爬取任务改为「先锁定作品 → 再集中爬取」，进度由本进程任务快照对外，
# 面板/APP 不再靠日志文本反推。挂到 app 上供 routes/crawl.py 用 h() 取。
from services.crawl_run import (                               # noqa: E402
    start as crawl_run_start, cancel as crawl_run_cancel,
    status as crawl_run_status, status_all as crawl_run_status_all,
    read_entries as crawl_run_entries, KIND_LABELS as crawl_kind_labels,
)

# ---- 「按作者/社团/原作爬取」（3.7.54）：探测 + 勾选下载 ----
# 探测层只读站点（搜索/封面）；勾选层在本进程线程里下载并入库，
# 所以两者的命名面都要挂在 app 上，供 routes/probe.py 用 h() 取。
from services.crawl_probe import (                             # noqa: E402
    probe_search, probe_cover, KIND_HINTS,
)
from services.crawl_pick import (                              # noqa: E402
    pick_start, pick_status, pick_cancel,
)


# 注：原「/api/uncat/archive-all」（未分类一键归档）已于 3.6.3 移除——
# 「未分类」不再是文库里的一个组，待整理的作品统一收进 _app/_inbox 成为待确认项，
# 归档动作由收件箱自身的「一键入库」（/api/inbox/confirm-all）承担：
# 它同样会按文件名解析社团、规范化命名，识别不出词条的保持待确认等待人工处理。


# ---------------------------------------------------------------
# 3.0 元数据层端点（API 1 纯新增）：作品元数据 / 评分收藏 / 收藏集 / FTS 检索
# ---------------------------------------------------------------


# ---------------------------------------------------------------
# 3.0 阅读状态与个人统计（M1 API / M2+UI 消费端）
# ---------------------------------------------------------------


# ---------------------------------------------------------------
# M4 人物志与关注：画师档案页 + 关注机制（新作品计数按 last_seen_at 基准）
# ---------------------------------------------------------------


# ---------------------------------------------------------------
# 3.0 备份时间机器（单人收藏是不可再生数据）
# ---------------------------------------------------------------


# ---------------------------------------------------------------
# 3.0 导出与离线阅读（面板端点；APP 本地书架为消费端）
# ---------------------------------------------------------------
_EXPORT_MIME = {".zip": "application/zip", ".cbz": "application/zip",
                ".rar": "application/vnd.rar", ".cbr": "application/vnd.rar"}


# ---------------------------------------------------------------
# ---------------------------------------------------------------
# 收件箱（M3 提案式入库）：_inbox/ 目录发现 → 解析提案 + 内容哈希去重 → 确认归档
# 目录位置：**程序目录内部** _app/_inbox（3.6.3 起；此前在 文库根/_inbox）。
#   理由：下划线前缀的功能性目录与「作品类目录」天然区分；放进 _app 后文库根只剩真实社团目录，
#   不再出现任何功能性/中文目录，也不会被误当成作品 dir 参与扫描。
# 四个来源进同一队列：爬虫落盘（crawl_wnacg 的 STAGING_DIR）、手动放入 _app/_inbox、
# **文库根下无法识别词条/无归属的作品**（由本文件自动收进来）、被解散社团踢出的作品。
# 同步时机：收件箱端点被访问时 + 启动后台扫描后（避免在扫描锁内做整文件哈希）。
# ---------------------------------------------------------------


_INBOX_STATE_FIXED = False


# ---------------------------------------------------------------
# 安卓 APK 自动更新：把新版 APK 放入 _app/app_releases/ 即可派发
# ---------------------------------------------------------------
APP_RELEASES_DIR = os.path.join(APP_DIR, "app_releases")
_APK_VER_RE = re.compile(r"(?i)index[-_]?v?(\d+)\.(\d+)\.(\d+)(?:.*?(\d+))?\.apk$")


# ---------------------------------------------------------------
# 入口
# ---------------------------------------------------------------


# ---------------------------------------------------------------
# 路由注册（3.6.53 Stage6）：按域拆到 routes/，逐批迁移。
# 新域名在这里 register(app)；routes/*.py 一律 h() 取值，不 import app。
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# 路由注册（3.6.53 Stage6）：按域拆到 routes/，逐域独立提交。
# routes/*.py 一律 h() 取值，不 import app（避免 __main__ 双实例）。
# ---------------------------------------------------------------
import routes.admin as _routes_admin                                          # noqa: E402
import routes.authors as _routes_authors                                      # noqa: E402
import routes.crawl as _routes_crawl                                          # noqa: E402
import routes.inbox as _routes_inbox                                          # noqa: E402
import routes.library as _routes_library                                      # noqa: E402
import routes.manage as _routes_manage                                        # noqa: E402
import routes.manage_circle as _routes_manage_circle                          # noqa: E402
import routes.media as _routes_media                                          # noqa: E402
import routes.meta as _routes_meta                                            # noqa: E402
import routes.originals as _routes_originals                                  # noqa: E402
import routes.probe as _routes_probe                                          # noqa: E402
import routes.theme as _routes_theme                                        # noqa: E402
import routes.pair as _routes_pair                                        # noqa: E402
import routes.remote as _routes_remote                                    # noqa: E402

for _m in (_routes_library, _routes_media, _routes_authors, _routes_meta,
           _routes_originals, _routes_crawl, _routes_inbox, _routes_manage,
           _routes_manage_circle, _routes_admin, _routes_probe,
           _routes_theme, _routes_pair, _routes_remote):
    _m.register(app)


if __name__ == "__main__":
    main()
