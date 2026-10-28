# -*- coding: utf-8 -*-
"""services/server.py —— 进程入口：参数解析、端口绑定、启动横幅、服务器主循环（3.6.61 从 app.py 抽出）。

`main()` 只做编排：解析参数 → 覆盖内存里的 CFG（**绝不落盘**，`--root`/`--port` 都只影响本进程）
→ 打印横幅 → 绑端口（waitress，缺失时回退 werkzeug dev server）→ 后台首扫 → serve_forever。

三条铁律（改动前务必读）：
  1. `--root` / `--port` 只改内存：任何后续 save_config 都会把"测试实例的临时目录/远程端口"
     写回 config.json，从而污染正式配置（两次真实故障都出自这里）。
  2. 非本机监听且未设 token 时必须自动生成并持久化 token，杜绝 0.0.0.0 裸奔。
  3. 端口被占用时：显式 --port 直接报错退出（双进程端口必须可预测）；未指定才 +1 漂移并落盘。
"""
import argparse
import os
import secrets
import shutil
import sys
import threading
import webbrowser

from werkzeug.serving import make_server

from panel.host import h


def main():
    """进程入口：日志 → 参数 → 覆盖内存配置 → 横幅 → 绑端口 → 后台首扫 → 主循环。

    3.6.71 结构：六个阶段各自成函数（cc 31→3），顺序即语义——
    **参数先落到内存 CFG，再绑端口，最后才打印"已启动"的 URL**，
    否则页面上给的地址可能指向另一个实例（3.6.21 的真实故障）。
    """
    h().setup_logging()      # 3.3.0：panel.log 轮转日志（未处理异常/扫描/同步失败可见）
    h().log.info("面板 %s 启动（waitress=%s）", h().PANEL_VERSION, h()._WAITRESS_OK)
    # 启动清理：上次会话可能遗留的分块上传临时目录
    shutil.rmtree(h().UPLOAD_TMP, ignore_errors=True)

    args = _build_parser().parse_args()
    token_hint = _apply_cli(args)
    _reset_stdout()
    _print_banner(h().CFG.get("root", ""), token_hint)

    srv, url = _bind_server(args)
    if srv is None:
        return
    _print_ready(url)
    _open_browser(args, url)
    threading.Thread(target=_initial_scan, daemon=True).start()
    _serve(srv)


def _build_parser():
    """命令行参数（--root/--port/--name 只影响本进程内存，不落盘）。"""
    parser = argparse.ArgumentParser(description="禁书目录 Index - 本地同人志文库 Web 系统")
    parser.add_argument("--root", help="文库根目录（覆盖配置文件）")
    parser.add_argument("--port", type=int, help="端口（覆盖配置文件）")
    parser.add_argument("--name", help="文库名称（覆盖配置文件）")
    parser.add_argument("--import-only", action="store_true",
                        help="仅导入模式：只开放 作品导入 / 爬虫管理 界面与功能")
    parser.add_argument("--open-browser", action="store_true",
                        help="[已废弃] 启动后自动打开系统浏览器——3.6.21 起即为默认行为，"
                             "保留仅为兼容旧脚本/旧卡片配置")
    parser.add_argument("--no-browser", action="store_true",
                        help="本次启动不自动打开浏览器（测试进程/静默部署用；环境变量 "
                             "INDEX_NO_BROWSER=1 同效）")
    parser.add_argument("--token", help="远程访问令牌：设置后所有数据接口需携带 X-Token（保存进 config.json）")
    parser.add_argument("--host", default="127.0.0.1",
                        help="监听地址：供手机/远程访问时用 0.0.0.0（务必配合 token 鉴权）")
    parser.add_argument("--safe-images", action="store_true",
                        help="测试模式（3.6.118）：封面/页面/探针封面全部替换为占位图——"
                             "截图/录屏不暴露内容（启动器「测试模式」卡自动携带）")
    return parser


def _apply_cli(args):
    """把命令行覆盖项写进**内存**配置，必要时自动生成远程 token。
    返回自动生成的 token（没有则 None），供横幅提示。"""
    if args.import_only:
        h().IMPORT_ONLY = True          # 3.6.61：标量仍由 app 持有（唯一事实源）
    if args.safe_images:
        h().SAFE_IMAGES = True          # 3.6.118：内存标志，不落 config（只影响本进程）
    if args.token:
        h().CFG["token"] = args.token.strip()
        h().save_config(h().CFG)
    if args.root:
        # 3.6.21 修复：`--root` 与 `--port` 同纪律——只覆盖**本进程内存**，绝不落盘。
        # 以前它会经后续任意 save_config（端口兜底/设置保存/画师映射）写回 config.json，
        # 于是"带 --root 起的测试实例"会把正式配置的文库根改成测试目录。
        h().CFG["root"] = os.path.abspath(os.path.expanduser(str(args.root).strip()))
    if args.port:
        # 显式端口（面板本地/远程进程都传 --port）只记录到内存供 /api/config 显示，
        # 绝不写进 CFG——否则本进程后续任何 save_config 都会把绑定端口写回 config.json。
        h().CFG_PORT_BIND = args.port
    if args.name:
        h().CFG["name"] = args.name
    return _ensure_remote_token(args)


def _paired_devices_exist():
    """`_state/pair_devices.json` 里有没有设备（只看条数，不碰哈希）。"""
    try:
        from common import STATE_DIR
        from services import pair_devices
        return bool(pair_devices.list_devices(STATE_DIR))
    except Exception:
        return False


def _ensure_remote_token(args):
    """远程模式强制鉴权：非本机监听且未设置 token 时，自动生成强随机 token 并持久化，
    杜绝 0.0.0.0 无鉴权裸奔（P1-1）。返回新 token 或 None。"""
    host = str(args.host or "127.0.0.1")
    if host in ("127.0.0.1", "localhost") or (h().CFG.get("token") or "").strip():
        return None
    # 3.6.147：主令牌可以为空（只靠扫码配对的设备令牌鉴权）。若此时仍强行生成，
    # 用户"删掉主令牌"就会被每次启动悄悄恢复——所以先看有没有已配对设备。
    if _paired_devices_exist():
        return None
    h().CFG["token"] = "bks-" + secrets.token_hex(12)
    h().save_config(h().CFG)
    return h().CFG["token"]


def _reset_stdout():
    """控制台编码兜底（pythonw / 非 UTF-8 终端下中文不乱码）。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    # 注：不再用 os.system("title ...") 设控制台标题——pythonw / CREATE_NO_WINDOW
    # 启动时进程没有控制台，os.system 会现场分配一个**可见的 cmd 窗口**（3.2.7 移除）。


def _print_banner(root, token_hint):
    """启动横幅：根目录有效性 / 词条库规模 / 可选依赖 / 远程 token 提示。"""
    print("=" * 58, flush=True)
    print("  禁书目录 Index  (Index)", flush=True)
    print("=" * 58, flush=True)
    if h().IMPORT_ONLY:
        print("  ★ 仅导入模式：开放「作品导入」与「爬虫管理」界面与功能", flush=True)
    print("  根目录 : " + (root or "(未设置)"), flush=True)
    print("  是否有效: " + ("是" if os.path.isdir(root) else "否（可在网页右上角“设置”中修改）"), flush=True)
    print("  原作标签库: " + f"{len(h().state.originals)} 个（可在网页设置或 config.json 扩展）", flush=True)
    print("  pillow : " + ("已安装（封面缩略图）" if h().PIL_OK else "未安装（建议 pip install pillow）"), flush=True)
    print("  rarfile: " + ("已安装" if h().RAR_AVAILABLE else "未安装（.rar/.cbr 封面不可用）"), flush=True)
    if token_hint:
        print("  ★ 远程模式未设置 token，已自动生成并写入 config.json：", flush=True)
        print("    " + token_hint, flush=True)
        print("    请在手机端首次访问时输入此令牌。", flush=True)
    print("-" * 58, flush=True)


def _make_server(port, host):
    """3.3.0：waitress 生产 WSGI 服务器（无连接/线程上限、慢客户端不长期占线程）；
    未安装时回退 werkzeug dev server，行为不变。

    **代理头（3.6.148，安全关键）**：waitress 默认 `clear_untrusted_proxy_headers=True`
    且 `trusted_proxy=None`，会把所有 `X-Forwarded-*` **一律清掉**。远程访问改由
    Tailscale serve 终结 TLS 后，后端因此完全看不到真实客户端，`remote_addr` 恒为
    127.0.0.1 —— 鉴权把它当"本机"直接放行，实测无令牌 `GET /api/library` 返回 200 全量数据。

    这里只信任来源为 **127.0.0.1** 的连接（tailscaled / 本机 nginx 都是这个来源），
    并显式把 `x-forwarded-for` 加入可信头——默认只保留 `x-forwarded-proto`，
    `for` 被清掉的话同样判不出真实客户端。局域网直连者 remote_peer 不是回环，
    其伪造的转发头照旧被清除，无法冒充本机。
    """
    if h()._waitress_create is not None:
        return h()._waitress_create(
            h().app, host=host, port=port, threads=8,
            trusted_proxy="127.0.0.1",
            trusted_proxy_count=1,
            trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto"})
    return make_server(host, port, h().app, threaded=True)


def _bind_one(port, host, strict=False):
    """绑定单个端口；失败返回 None（strict 时打印错误并等回车）。"""
    try:
        return _make_server(port, host)
    except OSError:
        if strict:
            print(f"  [错误] 端口 {port} 被占用，无法启动。", flush=True)
            input("按回车键退出…")
        return None


def _bind_drift(port0, host):
    """未指定端口：从 port0 起最多试 20 个；漂移后**落盘**（面板/启动脚本读的端口要一致）。"""
    for p in range(port0, port0 + 20):
        srv = _bind_one(p, host)
        if srv is None:
            continue
        h().CFG["port"] = p
        if p != port0:
            # 3.6.21 修复：这段兜底只在"没传 --port 的自动漂移"分支里才该跑——
            # 从前它挂在 if/else 之外，凡显式传端口都会进来，无条件 save_config(CFG) 一次：
            # 白写盘，还把本进程的 --root 覆盖顺带写进 config.json。
            h().save_config(h().CFG)
            print(f"  [提示] 端口 {port0} 被占用，已改用 {p} 并写入 config.json", flush=True)
        return srv
    print(f"  [错误] 端口 {port0}-{port0 + 19} 均被占用，无法启动。")
    input("按回车键退出…")
    return None


def _bind_server(args):
    """绑端口并算出访问 URL；失败返回 (None, None)（已提示用户）。

    显式 --port 严格只用该端口（面板远程进程必须可预测，不漂移、不写回 config）；
    未指定才在 +20 范围内漂移。
    """
    port0 = int(args.port or h().CFG.get("port", h().PORT))
    host = str(args.host or "127.0.0.1")
    if args.port is not None:
        srv = _bind_one(port0, host, strict=True)
        if srv is None:
            return None, None
        # 3.6.21：显式端口要回写内存 CFG["port"]——否则页面 URL 与 /api/config 里的
        # port 仍旧读 config.json 的旧值（实测 `--port 8520` 实际绑 8520、打印却是
        # http://127.0.0.1:8765/，会把人指到另一个（可能在跑的）实例上）。只改内存、不落盘。
        h().CFG["port"] = port0
    else:
        srv = _bind_drift(port0, host)
        if srv is None:
            return None, None
    return srv, _access_url(host)


def _access_url(host):
    """访问地址（本机 / 远程两种文案；仅导入模式追加 #/import）。"""
    port = h().CFG["port"]
    if host in ("127.0.0.1", "localhost"):
        url = f"http://127.0.0.1:{port}/"
    else:
        url = (f"http://127.0.0.1:{port}/（本机）｜ "
               f"局域网/虚拟网访问 http://<本机IP>:{port}/")
    return url + ("#/import" if h().IMPORT_ONLY else "")


def _print_ready(url):
    """服务已绑定的提示（这三行之后就是阻塞的主循环）。"""
    print(f"  已启动：{url}", flush=True)
    print("  首次打开会先扫描文库（作品多时约需 10~60 秒），页面会显示进度", flush=True)
    print("  按 Ctrl+C 停止服务", flush=True)
    print("=" * 58, flush=True)


def _initial_scan():
    """后台首扫：清缓存 → 同步收件箱 → 全量扫描。任一步失败只记日志，不打断服务。"""
    try:
        h().purge_video_tmp()
        h().prune_thumb_cache()
        h().prune_low_cache()
    except Exception:
        h().log.exception("启动清理缓存失败")
    try:
        h()._inbox_sync()     # 3.1：启动即发现 _inbox/ 内待确认作品（含爬虫落盘）
    except Exception:
        h().log.exception("收件箱同步失败（_inbox 内的待确认作品可能未登记）")
    try:
        lib = h().get_library(force=True)
        n_g = len(lib["groups"])
        n_w = sum(len(g["works"]) for g in lib["groups"])
        print(f"  扫描完成：{n_g} 个社团 / {n_w} 部作品（{lib['scan_ms']} ms）", flush=True)
    except Exception as e:
        print(f"  扫描出错：{e}", flush=True)


def _open_browser(args, url):
    """按三条抑制规则决定是否自动弹浏览器（测试/静默部署一律不弹）。"""
    if h()._browser_open_suppressed(args):
        # 测试进程/静默部署：一个浏览器窗口都不许弹（3.6.21 起这是"被显式抑制"的路径，
        # 不是默认路径——3.6.18~3.6.20 把它当默认，害得正式进程哪里都弹不出来）
        print("  [提示] 已抑制自动打开浏览器（--no-browser / INDEX_NO_BROWSER / config.no_browser）；"
              "请手动访问上面的地址", flush=True)
        return
    # 正式进程默认行为：启动 1 秒后用系统默认浏览器打开面板（3.6.21 恢复）
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print("  [提示] 启动后自动打开系统浏览器（要静默启动请加 --no-browser 或设 INDEX_NO_BROWSER=1）",
          flush=True)


def _serve(srv):
    """主循环（阻塞至 Ctrl+C）：waitress 走 run()，werkzeug 回退走 serve_forever()。"""
    try:
        if hasattr(srv, "serve_forever"):
            srv.serve_forever()        # werkzeug 回退路径
        else:
            srv.run()                  # waitress：asyncore 主循环
    except KeyboardInterrupt:
        print("\n  已停止。")
    finally:
        try:
            srv.server_close()
        except Exception:
            pass
