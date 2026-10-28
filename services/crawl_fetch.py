# -*- coding: utf-8 -*-
"""services/crawl_fetch.py —— 爬取任务的第二阶段「集中爬取」（3.7.58）。

锁定阶段已经给出"要下哪一部"（站点 id + 标题），这里只负责把文件拉进收件箱：
  * wnacg / JM 索引 / N站索引 → 落 wnacg 转载（直链 + 断点续传 + 字节回调）；
  * JM 直连 → jmcomic 整本（自动还原图片分割）；
  * N站直连 → 官方 ZIP 或图片 CDN 自建。

  下载完成后**只落收件箱**（与原来一致）：由用户在收件箱确认入库，
  分区分拣、改名、原作标签都走既有的提案流程。
  外接下载器（ext，3.6.155）同样只落收件箱：暂存产物打 zip，由用户确认入库。
"""
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import zipfile

import common

from common import crawl_log as _clog    # 3.6.156：services 层零 crawlers 顶层依赖


def inbox_dir():
    """收件箱 = 程序目录下的 `_inbox`（文库根只留真实社团目录）。"""
    d = os.path.join(common.APP_DIR, "_inbox")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError as e:
        _clog("[爬取] 收件箱目录创建失败：%s" % str(e)[:60])
    return d


def dl_wnacg(it, ctx, rt=None, on_progress=None):
    """wnacg 转载下载（JM/N站索引模式同样落到这里）。返回 (ok, 文案)。"""
    from crawlers.wnacg_download import download_one
    dest, err = download_one(ctx.domain, it["aid"], inbox_dir(),
                             it.get("name") or it["title"], on_progress=on_progress)
    if not dest:
        return False, (err or "下载失败")[:120]
    return True, "已下载 · %s" % os.path.basename(dest)


def dl_jmdl(it, ctx, rt=None, on_progress=None):
    """JM 直连：整本下载（jmcomic 自带 5 次重试与多域名轮换）。
    3.6.113：on_progress 透传（after_image 粒度字节进度）。"""
    import importlib
    JD = importlib.import_module("crawlers.crawl_jm_direct")
    if ctx.client is None:
        from services.crawl_lock import _jm_client
        _jm_client(ctx)
    zpath, pages = JD._download_album(ctx.jm_module, ctx.jm_option, it["aid"],
                                      it["title"] or it["entry"],
                                      on_progress=on_progress)
    if not zpath:
        return False, "JM 下载失败"
    it["pages"] = int(pages or 0)
    return True, "已下载 · %s（%d 页）" % (os.path.basename(zpath), int(pages or 0))


def dl_nhdl(it, ctx, rt=None, on_progress=None):
    """N站直连：官方 ZIP（需凭证）或图片 CDN 自建。"""
    import importlib
    ND = importlib.import_module("crawlers.crawl_nh_direct")
    if ctx.nh_auth is None:
        ctx.nh_auth = ND._nh_credential()
    gid = (rt or {}).get("gid") or it["aid"]
    meta = (rt or {}).get("meta") or {}
    zpath, _pages, reason = ND._fetch_zip(str(gid), meta, it["title"], ctx.nh_auth)
    if not zpath:
        return False, (reason or "N站下载失败")[:120]
    return True, "已下载 · %s" % os.path.basename(zpath)


def dl_eh(it, ctx, rt=None, on_progress=None):
    """E站直连：种子优先（aria2c）/逐页兜底 → zip。token 由锁定阶段带下来。"""
    import importlib
    EH = importlib.import_module("crawlers.crawl_ehentai")
    gid = (rt or {}).get("gid") or str(it["aid"])
    token = (rt or {}).get("token") or ""
    meta = (rt or {}).get("meta") or {}
    if not token:
        return False, "缺画廊 token（锁定阶段未解析出）"
    zpath, pages, reason = EH._fetch_zip(str(gid), str(token), meta,
                                         it["title"] or it["entry"],
                                         on_progress=on_progress)
    if not zpath:
        return False, (reason or "E站下载失败")[:120]
    it["pages"] = int(pages or 0)
    return True, "已下载 · %s（%d 页）" % (os.path.basename(zpath), int(pages or 0))


DOWNLOADERS = {"wnacg": dl_wnacg, "jm": dl_wnacg, "nh": dl_wnacg,
               "jmdl": dl_jmdl, "nhdl": dl_nhdl, "eh": dl_eh}


# ---------------------------------------------------------------
# 3.6.155 外接下载器（ext）：通用命令模板 → 子进程 → zip 落收件箱
# ---------------------------------------------------------------
def ext_tools():
    """config.json 的 ext_downloaders 工具表（load_config 已做形状校验，这里只兜底）。"""
    try:
        tools = common.load_config().get("ext_downloaders") or []
    except Exception:                                   # noqa: BLE001 —— 配置读不到按未配置
        return []
    return [t for t in tools if isinstance(t, dict) and t.get("name") and t.get("cmd")]


def ext_pick_tool(name=""):
    """按名字挑工具；名字为空/未命中时回退第一个。返回 (tool|None, 错误文案)。"""
    tools = ext_tools()
    if not tools:
        return None, "未配置外接下载器：在 config.json 的 ext_downloaders 里添加工具后重启面板"
    for t in tools:
        if t.get("name") == name:
            return t, ""
    return tools[0], ""


def _ext_log(text):
    """外接任务日志（独立文件，面板「运行日志」区可见）。"""
    try:
        from services import crawl as _cstate
        _cstate._crawl_log_append(text, path=_cstate._crawl_log_file("ext"))
    except Exception as e:                              # noqa: BLE001 —— 日志失败不影响下载
        _clog("[外接] 写日志失败：%s" % str(e)[:60])


def _ext_safe_name(entry, limit=120):
    """清单行 → 合法文件名（去 Windows 非法字符/首尾点空格，超长截断）。"""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", entry)
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    return name[:limit] or "ext-%s" % time.strftime("%Y%m%d%H%M%S")


def _ext_unique(path):
    """目标已存在时让位 (2)/(3)…（收件箱确认环节还有 sha1 兜底去重）。"""
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    n = 2
    while os.path.exists("%s(%d)%s" % (root, n, ext)):
        n += 1
    return "%s(%d)%s" % (root, n, ext)


def _ext_zip_stage(stage, dest_zip):
    """把暂存目录里的顶层产物（文件/文件夹）打包成 store 级 zip（图片压不动，只求快）。"""
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
        for top in sorted(os.listdir(stage)):
            src = os.path.join(stage, top)
            if os.path.isfile(src):
                zf.write(src, top)
                continue
            for dirpath, _dirs, files in os.walk(src):
                for fn in files:
                    if fn.endswith(".part"):
                        continue
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, stage)
                    zf.write(full, rel)


def _ext_run(cmd_argv, stage, timeout, is_cancelled=None):
    """起子进程跑外接工具，stdout/stderr 行式节流进任务日志。返回 (exit_code|None)。

    读输出与等退出必须解耦：静默工具（不打印任何行）会让逐行读一直阻塞，
    取消/超时检查永远轮不到——所以输出用泵线程收，主流程按秒轮询三个结束条件。
    """
    import threading

    proc = subprocess.Popen(cmd_argv, cwd=stage, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    buf = []
    pump = threading.Thread(target=lambda: [buf.append(ln) for ln in proc.stdout],
                            daemon=True)
    pump.start()
    deadline = (time.monotonic() + timeout) if timeout > 0 else None
    last_log = 0.0
    sent = 0
    while True:
        now = time.monotonic()
        if now - last_log >= 1.5:                       # 时间节流：高频输出只留最近一条
            for ln in buf[sent:]:
                _ext_log("  | %s" % ln.rstrip()[:160])
            sent = len(buf)
            last_log = now
        if is_cancelled and is_cancelled():
            proc.terminate()
            return None
        if deadline is not None and now >= deadline:
            _ext_log("  | 超时（%d 秒），终止子进程" % timeout)
            proc.terminate()
            return None
        try:
            code = proc.wait(timeout=1.0)
            break
        except subprocess.TimeoutExpired:
            continue
    pump.join(timeout=5)
    for ln in buf[sent:]:                               # 收尾把剩余输出写完
        _ext_log("  | %s" % ln.rstrip()[:160])
    if is_cancelled and is_cancelled():
        return None
    return code


def _ext_make_stage():
    """建本次条目的暂存目录 _inbox/_ext_stage/ext-xxxx。返回 (路径|None, 错误文案)。"""
    try:
        root = os.path.join(inbox_dir(), "_ext_stage")
        os.makedirs(root, exist_ok=True)
        return tempfile.mkdtemp(prefix="ext-", dir=root), ""
    except OSError as e:
        return None, "暂存目录创建失败：%s" % str(e)[:80]


def _ext_argv(cmd, stage, entry):
    """命令模板 → argv：{url}/{dest} 替换后按 shell 词法切分（保留反斜杠、剥成对引号）。"""
    argv = shlex.split(cmd.replace("{dest}", stage).replace("{url}", entry), posix=False)
    return [a[1:-1] if len(a) >= 2 and a[0] == a[-1] and a[0] in "\"'" else a
            for a in argv]                              # posix=False 会保留成对引号，手动剥壳


def _ext_collect(stage, entry):
    """产物打包 zip 落收件箱并清暂存。返回 (ok, 文案)。"""
    if not os.listdir(stage):
        shutil.rmtree(stage, ignore_errors=True)
        return False, "工具没有产出文件（检查命令模板的 {dest} 占位符）"
    dest_zip = _ext_unique(os.path.join(inbox_dir(),
                                        _ext_safe_name(entry) + ".zip"))
    try:
        _ext_zip_stage(stage, dest_zip)
    except Exception as e:                              # noqa: BLE001 —— 打包失败按单条失败处理
        shutil.rmtree(stage, ignore_errors=True)
        return False, "打包失败：%s %s" % (type(e).__name__, str(e)[:80])
    shutil.rmtree(stage, ignore_errors=True)
    _ext_log("  ✓ 已打包：%s（%.1f MB）"
             % (os.path.basename(dest_zip), os.path.getsize(dest_zip) / 1048576))
    return True, "已下载 · %s" % os.path.basename(dest_zip)


def dl_ext(it, ctx, rt=None, on_progress=None):
    """外接下载器：跑命令模板 → 暂存产物打 zip → 落收件箱。返回 (ok, 文案)。

    命令模板里的 {url}=清单行原文、{dest}=本次暂存目录；rt 可带
    cancelled 回调（任务取消时杀子进程）。任何失败都清掉暂存、词条留在清单里待重试。
    """
    rt = rt or {}
    tool, err = ext_pick_tool(rt.get("tool"))
    if tool is None:
        return False, err
    entry = str(it.get("entry") or "").strip()
    if not entry:
        return False, "空条目"
    stage, err = _ext_make_stage()
    if stage is None:
        return False, err
    _ext_log("[外接] %s：%s" % (tool["name"], entry[:80]))
    cancelled = rt.get("cancelled")
    code = _ext_run(_ext_argv(tool["cmd"], stage, entry),
                    stage, int(tool.get("timeout") or 1800), cancelled)
    if code is None:                                    # 超时或取消
        shutil.rmtree(stage, ignore_errors=True)
        if cancelled and cancelled():
            return False, "已取消"
        return False, "%s 超时或被终止（可在工具配置里调大 timeout）" % tool["name"]
    if code != 0:
        _ext_log("  | 退出码 %d" % code)
        shutil.rmtree(stage, ignore_errors=True)
        return False, "%s 退出码 %d（详情见运行日志）" % (tool["name"], code)
    return _ext_collect(stage, entry)


# 3.6.155：外接下载器注册（dl_ext 定义在上方，模块末尾统一挂进分派表）
DOWNLOADERS["ext"] = dl_ext
