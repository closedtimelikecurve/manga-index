# -*- coding: utf-8 -*-
"""crawl_jm_direct.py —— JM直连爬取：词条/车号 → JM 站内解析 → 整本下载 → 收件箱
==========================================================================
与 crawl_jm_ids.py（JM索引爬取：ID→标题→wnacg 搜索下载）互为补充：直连模式
**不经过 wnacg**，wnacg 没有转载也能拿。

吃两个清单（3.6.7 起为直连模式独占，不再与 wnacg/jm 索引模式共用）：
  * pending_jmdl_titles.txt —— 标题词条（与 wnacg 主爬同格式），走 JM 站内搜索匹配后下载
  * pending_jmdl_ids.txt   —— 纯数字车号，直接下载
命令行等价：--titles pending_jmdl_titles.txt --list pending_jmdl_ids.txt（可单独给其一）。

下载：jmcomic 整本（自动还原 JM 图片分割乱码），按「[社团] 标题.zip」落
文库根/_inbox/，由面板收件箱提案式入库。断点状态独立于 wnacg：
crawl_state_jm.json（done 跳过 / failed 记因），键 = 词条原文。

网络事实（2026-10-07 实测）：jmcomic 走禁漫 App 的 API 域名（启动时自动更新），
校园网直连可达、无验证码；出口为中国 IP，不在 JM 的日韩封禁范围。直连存在
间歇性 SSL 握手重置，库内置 5 次重试 + 多域名轮换兜底。脚本不走代理——若将来
必须走代理，节点避开日韩。

用法：
  python crawl_jm_direct.py                                   # 两个清单都读
  python crawl_jm_direct.py --titles 我的词条.txt              # 只给标题
  python crawl_jm_direct.py --list 我的ID清单.txt              # 只给车号
"""
import argparse
import json
import os
import re
import shutil
import sys
import threading
import time
import zipfile

sys.dont_write_bytecode = True
# 3.6.46：脚本收进 crawlers/ 包 —— _app（程序根）供 import common，
# 本目录供兄弟脚本互相 import；两者都要在 sys.path 上（作为包导入 / 直接运行都成立）。
_HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(_HERE)          # <文库根>/_app：config / 清单 / _inbox 的基准
sys.path.insert(0, APP_DIR)
sys.path.insert(0, _HERE)
try:
    from . import crawl_wnacg as C           # 作为包导入（pytest / 面板内调用）
except ImportError:                          # 直接以脚本方式运行
    import crawl_wnacg as C
import common
import djc_parse as dp
from crawlers import ids_common
from crawlers.wnacg_base import utf8_console

utf8_console()

JM_STATE_FILE = os.path.join(common.STATE_DIR, "crawl_state_jmdl.json")   # 3.7 Stage3：归入 _app/_state/
# 3.6.7 兼容继承：直连任务的断点 state 此前叫 crawl_state_jm.json（与面板 jm 索引模式
# 显示口径混用），改名后首次启动把旧文件接过来，避免已下载词条被重下
_JM_STATE_LEGACY = os.path.join(common.STATE_DIR, "crawl_state_jm.json")
if os.path.exists(_JM_STATE_LEGACY) and not os.path.exists(JM_STATE_FILE):
    try:
        common.ensure_dir(common.STATE_DIR)
        os.replace(_JM_STATE_LEGACY, JM_STATE_FILE)
    except OSError:
        pass
TMP_ROOT = os.path.join(common.CACHE_DIR, "jm_tmp")     # 3.7 Stage3：归入 _app/_cache/（文库扫描天然跳过）
IMG_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MATCH_MIN = 0.60                                # 与 wnacg 主爬常规档同一下限


def _load_state():
    try:
        with open(JM_STATE_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("done"), dict):
            d.setdefault("failed", {})
            return d
        print("[警告] 断点文件结构不符合预期，按空状态开始（会重爬）：%%s" % JM_STATE_FILE, flush=True)
    except FileNotFoundError:
        pass                                     # 首次运行：没有断点是正常的
    except Exception as e:
        # 损坏的断点绝不能静默丢弃：用户看到"怎么又从第 1 个开始了"却查不到原因
        print("[警告] 断点文件读取失败，按空状态开始（会重爬）：%%s ｜ %%s: %%s"
              % (JM_STATE_FILE, type(e).__name__, e), flush=True)
    return {"done": {}, "failed": {}}


def _save_state(st):
    try:
        common.ensure_dir(os.path.dirname(JM_STATE_FILE) or APP_DIR)   # _state/ 首次运行需先建
        with open(JM_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"[警告] 状态保存失败: {e}", flush=True)


def load_entries(path):
    """清单文件 → 非注释词条行（文件不存在视为空）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [s.strip() for s in f if s.strip() and not s.strip().startswith("#")]
    except OSError:
        return []


def is_jm_id(text):
    return text.strip().isdigit()


def search_variants(entry):
    """标题词条的搜索词降级链（JM 站内搜索专用）。

    实测：JM 搜索把「中文翻譯」这类通用词当标签，完整标题反而带回几十条噪声；
    核心标题（去括号块）能精确命中。因此顺序为：核心标题 → 全词条 → 逐词去尾，
    每个基底派生出递减前缀链，命中即停（上限 8 次搜索请求）。"""
    bases = []
    if entry.startswith("["):
        depth = 0
        for i, ch in enumerate(entry):
            depth += (ch == "[") - (ch == "]")
            if depth == 0:
                rest = entry[i + 1:].strip()
                if rest:
                    bases.append(rest)
                break
    stripped = re.sub(r"\s*\[[^\]]*\]", " ", entry).strip()
    if stripped and stripped not in bases:
        bases.append(stripped)
    if entry not in bases:
        bases.append(entry)      # 全词条兜底放最后
    ladder = []
    for b in bases:
        words = b.split()
        while words:
            s = " ".join(words)
            if s not in ladder:
                ladder.append(s)
            words.pop()
    return ladder[:8]


def normalize_search_results(page):
    """JmSearchPage.content → [(album_id, name), ...]，容忍各种条目形态。"""
    out = []
    for item in (getattr(page, "content", None) or []):
        if isinstance(item, str):
            m = re.search(r"/album/(\d+)", item) or re.match(r"^(\d+)\b", item)
            if m:
                out.append((m.group(1), item))
        elif isinstance(item, (list, tuple)) and item:
            aid = str(item[0])
            meta = item[1] if len(item) > 1 else {}
            name = meta.get("name", "") if isinstance(meta, dict) else str(meta)
            out.append((aid, name or ""))
    return out


def pick_best(query, results, min_score=None):
    """搜索结果里挑与词条最像的专辑：(aid, name, score) | None（下限 MATCH_MIN，
    调用方可按档位覆盖）。"""
    ek = C._norm_key(query)
    lo = min_score if min_score is not None else MATCH_MIN
    best = None
    for aid, name in results:
        s = C.match_score(ek, name)
        if best is None or s > best[2]:
            best = (str(aid), name, s)
    return best if best and best[2] >= lo else None


def compose_zip_name(title, authors=None):
    """专辑名 → zip 文件名（不含扩展名）。JM 标题多为「[社团 (个人)] 标题」
    原生格式，直接沿用；缺括号时用 authors 字段补；非法字符交给统一净化。"""
    t = (title or "").strip()
    if not t.startswith("["):
        a = ""
        if isinstance(authors, (list, tuple)):
            a = ", ".join(str(x).strip() for x in authors if str(x).strip())
        elif isinstance(authors, str):
            a = authors.strip()
        if a:
            t = f"[{a}] {t}"
    return dp.sanitize_windows_name(t) or "JM未命名"


def _collect_pages(root):
    """收集下载产物，按相对路径排序（章节子目录 + 零填充页码天然有序）。"""
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if os.path.splitext(fn)[1].lower() in IMG_SUFFIXES:
                out.append(os.path.join(dirpath, fn))
    return sorted(out, key=lambda p: os.path.relpath(p, root))


def _zip_pages(pages, zpath, root):
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as z:
        for f in pages:
            z.write(f, arcname=os.path.relpath(f, root))


def _build_progress_downloader_cls(base, on_progress):
    """3.6.113：包一层 JmDownloader，覆写 after_image（每张图落盘时触发）——
    累计落盘字节 → on_progress(累计字节, 0)，供搜索下载器/清单下载器看板实时显示。
    经库 API `download_album(id, option, downloader=类)` 按次注入，不碰全局
    downloader 注册表（并发任务互不串线）。"""
    lock = threading.Lock()
    state = {"got": 0}

    class _ProgressDl(base):
        def after_image(self, image, img_save_path):
            super().after_image(image, img_save_path)
            try:
                size = os.path.getsize(img_save_path)
            except OSError:
                return
            with lock:
                state["got"] += size
                got = state["got"]
            try:
                on_progress(got, 0)
            except Exception as e:  # noqa: BLE001 —— 回调失败不中断下载，但留痕
                print(f"[JM] 进度回调异常（忽略）: {type(e).__name__} {str(e)[:60]}", flush=True)

    return _ProgressDl


def _download_album(jmcomic, JmOption, aid, title, on_progress=None):
    """下载 aid 整本并打包到收件箱，返回 (zip 路径, 页数)。
    3.6.113：on_progress 存在时经库 API 注入进度 downloader（after_image 粒度），
    看板据此实时显示下载量；不传走原路（零开销）。"""
    tmp_dir = os.path.join(TMP_ROOT, str(aid))
    shutil.rmtree(tmp_dir, ignore_errors=True)
    try:
        # 3.6.157：统一配置（并发 6 / 重试 12）。默认 30 并发打本地代理会导致
        # 部分图片连接被丢弃 → PartialDownloadFailedException，整本判失败。
        opt = ids_common.make_jm_option()
        opt.dir_rule.base_dir = tmp_dir
        if on_progress:
            dl_cls = _build_progress_downloader_cls(jmcomic.JmDownloader, on_progress)
            jmcomic.download_album(str(aid), opt, downloader=dl_cls)
        else:
            jmcomic.download_album(str(aid), opt)
        pages = _collect_pages(tmp_dir)
        if not pages:
            raise RuntimeError("下载目录为空（0 张图片）")
        common.ensure_dir(C.STAGING_DIR)   # 收件箱可能还没建（首次使用）
        zpath = common.unique_path(os.path.join(
            C.STAGING_DIR, compose_zip_name(title) + ".zip"))
        _zip_pages(pages, zpath, tmp_dir)
        return zpath, len(pages)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _parse_args(argv=None):
    ap = argparse.ArgumentParser(description="JM直连爬取：词条/车号 → JM 整本下载 → 收件箱")
    ap.add_argument("--list", default=os.path.join(APP_DIR, "pending_jmdl_ids.txt"),
                    help="JM 车号清单（每行一个数字 ID，# 开头为注释）")
    ap.add_argument("--titles", default=os.path.join(APP_DIR, "pending_jmdl_titles.txt"),
                    help="标题词条清单（与 wnacg 主爬同格式；直连模式独占两份，3.6.7 起独立）")
    ap.add_argument("--strict", action="store_true",
                    help="严格档：JM 站内搜索匹配下限 0.80；常规档 0.60")
    return ap.parse_args(argv)


def _collect_jobs(list_path, titles_path):
    """两份清单合并去重：车号清单在前（精确），词条清单在后（靠搜索匹配）。"""
    jobs, seen = [], set()
    for e in load_entries(list_path) + load_entries(titles_path):
        if e not in seen:
            seen.add(e)
            jobs.append(e)
    return jobs


def _resolve_aid(client, entry, match_min, label):
    """条目 → JM 车号。已是车号直接用；否则逐个搜索变体取最佳匹配。返回 (aid, 失败原因)。"""
    if is_jm_id(entry):
        return entry, ""
    for q in search_variants(entry):
        try:
            page = client.search_site(q)
        except Exception as e:                                       # noqa: BLE001
            print(f"    搜索“{q[:36]}”失败: {type(e).__name__} {str(e)[:60]}", flush=True)
            continue
        results = normalize_search_results(page)
        best = pick_best(entry, results, min_score=match_min)
        if best:
            aid, name, score = best
            print(f"    ✓ JM 搜索匹配 {int(score * 100)}% ｜ {name[:52]} (aid={aid})", flush=True)
            return aid, ""
        print(f"    搜索“{q[:36]}”{len(results)} 条，无 ≥{int(MATCH_MIN * 100)}% 匹配", flush=True)
    print(f"{label}: ✗ JM 搜索无匹配", flush=True)
    return None, "JM 搜索无匹配"


def _download_entry(client, jmcomic, JmOption, aid, entry, st, label):
    """拉详情 → 整本下载 → 记 state。返回是否成功（失败原因已写进 state）。"""
    try:
        al = client.get_album_detail(aid)
        title = (al.name or "").strip()
        print(f"{label} JM{aid}: {title[:60]}", flush=True)
        zpath, pages = _download_album(jmcomic, JmOption, aid, title)
        mb = os.path.getsize(zpath) / 1048576
        st["done"][entry] = {"aid": str(aid), "title": title}
        st["failed"].pop(entry, None)
        _save_state(st)
        print(f"    ✓ 已下载 {os.path.basename(zpath)[:56]} ({mb:.1f}MB, {pages} 页) → 收件箱", flush=True)
        return True
    except Exception as e:                                           # noqa: BLE001
        print(f"    ✗ 下载失败: {type(e).__name__} {str(e)[:90]}", flush=True)
        st["failed"][entry] = f"下载: {type(e).__name__} {str(e)[:100]}"
        _save_state(st)
        return False


def _rewrite_lists(paths, done_all):
    """从两份清单里删掉已完成的条目（只留待爬/失败与注释），对齐 wnacg 主爬口径。"""
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
            kept = [ln for ln in lines if not (ln.strip() and ln.strip() in done_all)]
            if kept == lines:
                continue
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(kept).rstrip("\n") + ("\n" if kept else ""))
            print(f"清单已回写：{os.path.basename(path)} 移除已完成词条 "
                  f"{len(lines) - len(kept)} 行，剩余 {len(kept)} 行", flush=True)
        except Exception as e:                                       # noqa: BLE001
            print(f"[警告] 清单回写失败 {path}: {e}", flush=True)


def main(argv=None):
    """两份清单合并后逐条：解析车号 → 整本下载 → 记 state；成功条目从清单移除。"""
    args = _parse_args(argv)
    match_min = 0.80 if args.strict else MATCH_MIN

    common.merge_pip_common()   # jmcomic 自带的顶层 common 包被本项目同名模块遮蔽，先合并
    import jmcomic
    from jmcomic import JmOption

    jobs = _collect_jobs(args.list, args.titles)
    st = _load_state()
    os.makedirs(C.STAGING_DIR, exist_ok=True)
    os.makedirs(TMP_ROOT, exist_ok=True)

    ok = skip = fail = 0
    for i, entry in enumerate(jobs, 1):
        label = f"[{i}/{len(jobs)}] {entry[:44]}"
        if entry in st["done"]:
            print(f"{label}: 已完成，跳过", flush=True)
            skip += 1
            continue
        # 每条一个新 client：长任务下连接更干净（配置同 _download_album，见 ids_common）
        client = ids_common.make_jm_option().new_jm_client()
        aid, reason = _resolve_aid(client, entry, match_min, label)
        if not aid:
            st["failed"][entry] = reason
            _save_state(st)
            fail += 1
            continue
        if _download_entry(client, jmcomic, JmOption, aid, entry, st, label):
            ok += 1
        else:
            fail += 1
        time.sleep(1.0)

    _rewrite_lists((args.list, args.titles), set(st["done"].keys()))
    print(f"==== 结束：下载 {ok} / 跳过 {skip} / 失败 {fail} ====", flush=True)


if __name__ == "__main__":
    main()
