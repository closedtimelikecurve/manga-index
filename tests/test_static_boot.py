# -*- coding: utf-8 -*-
"""前端启动链回归（3.6.22，3.6.84 起适配 app.js 分片）。

事故：3.6.15 删「全局长按复制」时，把 static/app.js（当时还是单文件）**末尾的 `init();` 一起删掉了**
（要删的是 `initLongPressCopy()`，`init` 是被误伤）。此后面板彻底不引导：页面壳能出来，
但状态栏永远停在 HTML 里写死的「加载中…」，一个请求都不发（用 DOM 垫片跑 app.js 实测：
零请求、零渲染）。这类"函数定义了、没人调用"的断裂 CI 完全看不见，所以立成测试。

3.6.84：app.js（3103 行）按顶层区块拆成 `static/js/*.js` 13 片，仍是 classic script，
**顺序加载、共享同一个全局词法环境**。于是本文件多守两条：
  * 分片清单必须与 index.html 的 <script> 引用**逐项一致且顺序相同**（漏一片就是白屏）；
  * 每片都必须自带 'use strict'（原来整份文件是 strict，拆开后不能悄悄退化成 sloppy）。

纯文本/结构断言，不需要浏览器，也不会碰真实文库。
"""
import os
import re

PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(PROG_DIR, "static", "js")
INDEX_HTML = os.path.join(PROG_DIR, "static", "index.html")

# 加载顺序（= 原 app.js 的顶层区块顺序，不可随意调整：后者用到前者的 const）
# 3.6.116：i18n_langs.js（382 行，已顶到 .js 代码行预算）按语言拆片，
# 7 个 i18n_lang_*.js 占原位，i18n_langs.js 退化为收尾片（包尾再次 i18nApplyDom）。
# 3.6.135：每批新译文再 +100 行，7 个包各到 446 行（上限 400）→ 每个包再拆第 2 片
# `i18n_lang_<x>_2.js`（纯搬移，前半留原文件、后半搬 _2），新条目往后加在末片。
JS_ORDER = ["core", "alias", "i18n",
            "i18n_lang_zh_hant", "i18n_lang_en", "i18n_lang_ja", "i18n_lang_ko",
            "i18n_lang_ru", "i18n_lang_th", "i18n_lang_vi",
            "i18n_lang_zh_hant_2", "i18n_lang_zh_hant_3", "i18n_lang_en_2", "i18n_lang_en_3", "i18n_lang_ja_2", "i18n_lang_ja_3", "i18n_lang_ko_2", "i18n_lang_ko_3",
            "i18n_lang_ru_2", "i18n_lang_ru_3", "i18n_lang_th_2", "i18n_lang_th_3", "i18n_lang_vi_2", "i18n_lang_vi_3",
            # 3.6.151：第 4 片（远程服务开关 + 排序档位），七语一次性新增
            "i18n_lang_zh_hant_4", "i18n_lang_en_4", "i18n_lang_ja_4", "i18n_lang_ko_4",
            "i18n_lang_ru_4", "i18n_lang_th_4", "i18n_lang_vi_4", "i18n_langs",
            "router", "home", "search", "detail", "inbox",
            "import", "crawl", "crawlmon", "probe", "probecards", "probeclock", "probejob",
            "drawer", "theme", "tag", "reader", "panel", "menu", "ctxmenu"]


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _js_src(name):
    return _read(os.path.join(JS_DIR, name + ".js"))


def _all_src():
    return "\n".join(_js_src(n) for n in JS_ORDER)


def test_all_shards_exist_and_are_strict():
    for n in JS_ORDER:
        path = os.path.join(JS_DIR, n + ".js")
        assert os.path.isfile(path), "缺少分片 static/js/%s.js" % n
        assert re.search(r"(?m)^'use strict';", _js_src(n)), \
            "static/js/%s.js 丢了 'use strict'（拆分后默认是宽松模式，行为会变）" % n


def test_index_references_exactly_the_shards_in_order():
    html = _read(INDEX_HTML)
    refs = re.findall(r'<script src="/static/js/([A-Za-z0-9_\-]+)\.js\?v=[^"]+"></script>', html)
    assert refs == JS_ORDER, "index.html 的 <script> 顺序/清单与约定不符：%r" % (refs,)
    on_disk = sorted(p[:-3] for p in os.listdir(JS_DIR) if p.endswith(".js"))
    assert on_disk == sorted(JS_ORDER), "static/js 下有未被 index.html 引用的分片：%r" % (on_disk,)


def test_init_defined_and_called_at_toplevel():
    """核心断言：必须有一处"顶格（0 缩进）的 init();"调用。

    只认顶格写法——缩进的 init() 只可能是定义体内或别处的局部调用，
    起不到"页面加载即引导"的作用（这正是 3.6.15~3.6.21 的故障形态）。"""
    src = _all_src()
    assert re.search(r"\basync\s+function\s+init\s*\(", src), "init() 定义不见了"
    assert re.findall(r"(?m)^init\(\);\s*$", src), \
        "定义了 init() 却从未在顶层调用它 —— 面板会永久停在「加载中…」"


def test_init_is_in_the_last_shard():
    """启动调用必须在最后一片：分片按序执行，提前调用会撞上后面才声明的 const（TDZ）。"""
    assert re.findall(r"(?m)^init\(\);\s*$", _js_src(JS_ORDER[-1])), \
        "init() 调用不在最后一片，前面的分片还没执行完"


def test_feed_partition_uses_zone_endpoint():
    """3.6.30 回归：首页「原作分区」视图的数据源必须是 /api/originals。

    3.3.0 加「喜爱画师」分区时把 renderFeedPartition 的请求统一成 /api/artists
    （喜爱只需画师列表 + followed 过滤），顺手把原作分区的数据源也砍了 ——
    此后分区视图一直在拿**画师列表**当分区渲染（卡片写着"点击进入原作分区"，
    点进去却是画师名 → 空分区）。3.2.6 原本是对的。纯文本断言，防止再被"统一"掉。
    """
    src = _js_src("home")
    m = re.search(r"function\s+renderFeedPartition\s*\([^)]*\)\s*\{.*?\n\}", src, re.S)
    assert m, "home.js 里找不到 renderFeedPartition"
    body = m.group(0)
    assert "'/api/originals'" in body, \
        "首页分区视图必须能取到 /api/originals（原作分区的数据源被统一掉了）"
    assert "d.originals" in body, \
        "mode==='originals' 时应取 d.originals，而不是画师列表 d.artists"


def test_recs_rendered_before_partition_branch():
    """3.6.93 回归：首页「全部画师 / 原作分区」视图里每日推荐必须照常显示。

    事故：renderHome 先把 #recSection 按"有没有搜索词"切成隐藏，紧接着
    `fm !== 'circles'` 提前 return 去渲染分区 —— renderRecs(lib) 永远轮不到，
    于是切到画师/原作分区，推荐区就消失了（只有"全部社团"视图有）。

    判据：renderRecs 的调用必须在分区 early-return 之前；且那句"按搜索词预先隐藏"
    的写法不许回来（它会无条件把分区视图的推荐区藏掉）。
    """
    src = _js_src("home")
    m = re.search(r"function\s+renderHome\s*\(\)\s*\{.*?\n\}", src, re.S)
    assert m, "home.js 里找不到 renderHome"
    body = m.group(0)
    call = body.find("renderRecs(lib)")
    early = body.find("renderFeedPartition(fm)")
    assert call >= 0, "renderHome 不再调用 renderRecs —— 首页不会有每日推荐"
    assert early >= 0, "renderHome 不再分流到 renderFeedPartition"
    assert call < early, "renderRecs 在分区 early-return 之后 —— 画师/原作分区会没有每日推荐"
    assert "toggle('hidden', !state.filter.trim())" not in body, \
        "renderHome 又按搜索词预先隐藏推荐区了 —— 分区视图会永久看不到每日推荐"


def test_probe_progress_is_watched_globally():
    """3.7.56 回归：分区爬取的进度必须由**全局看护**驱动，不能只绑在探针页上。

    事故：轮询写在 `renderProbe/离开视图即停`，用户一退出探针页就再也看不到任务状态
    （任务其实还在服务端线程里跑）。判据：
      ① index.html 有右下角浮标节点；
      ② core.js 的 init() 会启动看护（任何视图都在轮询）；
      ③ probe.js 里存在全局看护循环，且**不再**有"离开视图就停"的老函数。
    """
    html = _read(INDEX_HTML)
    assert 'id="probeTicker"' in html, "缺少全局进度浮标节点 #probeTicker"
    core = _js_src("core")
    assert "probeWatchStart()" in core, "init() 没有启动全局进度看护"
    probe = _js_src("probe")
    assert "function probeWatchTick" in probe and "probeWatchApply" in probe, "probe.js 缺少全局看护循环"
    assert "probeWatch.busy" in probe, "看护循环没有单飞保护（init/进页/起任务会叠出多条轮询）"
    for dead in ("probePoll(", "probeStopPolling", "probeResumeRunning"):
        assert dead not in probe, "旧的页面级轮询 %s 又回来了（离开视图会失联）" % dead


def test_probe_progress_panel_and_crawl_page_is_independent():
    """3.7.56/3.7.57/3.7.59：探针面板完整，且清单爬虫页不再挂分区爬虫入口。"""
    probe = _js_src("probe")
    assert 'class="probe-monitor' in probe, "探针页缺少常驻进度面板（不能藏在结果列表底部）"
    assert "probeBytesText" in probe and "bytes_total" in probe, "面板没有接字节进度"
    assert "function probeRenderJob" not in probe, "3.6.111 起看板渲染已迁至 probejob.js，probe.js 只留调用点"
    # 3.6.141 站点表函数化 probeSites()（切语言跟随）——查的仍是"顶部有目标站点切换"这件事
    assert "probeSites" in probe and 'data-site="' in probe, "顶部没有目标站点切换"
    assert "if (probe.term) probeSearch()" not in probe, "进入页面又自动搜索了（必须点搜索）"
    assert "完成前隐藏搜索结果" not in _js_src("probecards"), \
        "3.6.112 起运行中不再隐藏搜索结果（封面卡墙照常显示，看板在页面头部）"
    # 3.7.59：两个爬虫彻底分开——清单爬虫页不再出现分区爬虫的入口/任务卡
    crawl = _js_src("crawl")
    assert "crawlRenderPick" not in crawl and "crawlPickCard" not in crawl, "清单爬虫页又挂回了分区爬虫的任务卡"
    assert "#/probe" not in crawl, "清单爬虫页又出现了分区爬虫入口"
    assert 'class="crawl-kind' in crawl and "crawlRefreshChips" in crawl, "清单爬虫页缺少任务胶囊（运行中变绿）"


def test_probe_job_board_uses_crawl_monitor_style():
    """3.6.111：分区爬取看板与清单爬虫监控同款——cj 外壳 + 封面卡 + 指纹更新防封面闪现。"""
    pj = _js_src("probejob")
    assert "probeRenderJob" in pj and "probeJobSig" in pj, "分区爬取看板缺指纹更新机制（封面会闪现即消失）"
    assert "cj-grid" in pj and "probe-cover" in pj, "分区爬取看板未对齐清单爬虫的封面作品卡"
    assert "probeJobElapsed" in pj, "看板丢了 #probeJobElapsed（probeclock 本地计时依赖）"


def test_app_probe_progress_is_aligned():
    """3.7.56/3.7.57 双端对齐：APP 消费进度字段，并有全局看护。"""
    root = os.path.join(PROG_DIR, "android", "app", "src", "main", "java",
                        "com", "biblioteca", "reader")

    def src(name):
        with open(os.path.join(root, name), "r", encoding="utf-8") as f:
            return f.read()

    api = src("ApiProbe.kt")
    for field in ('optLong("bytes")', 'optLong("bytes_total")', 'optInt("elapsed")',
                  'optString("current_state")', 'optInt("queue")', 'optString("site"'):
        assert field in api, "APP 没解析进度/站点字段 %s" % field
    watch = src("ProbeWatch.kt")
    assert "suspend fun tick" in watch and "fun AppState.cancelProbePick" in watch, \
        "APP 缺少全局看护/cancel 入口"
    main = src("MainActivity.kt")
    assert "AppProbeWatchEffect(s)" in main and "AppProbeTicker(s)" in main, \
        "APP 没有启动全局看护或悬浮条"


def test_app_probe_sites_and_running_layout():
    """3.7.57：APP 顶部站点切换、运行中隐藏结果、计时器本地化、搜索必须点按。"""
    root = os.path.join(PROG_DIR, "android", "app", "src", "main", "java",
                        "com", "biblioteca", "reader")

    def src(name):
        with open(os.path.join(root, name), "r", encoding="utf-8") as f:
            return f.read()

    probe = src("ProbeScreen.kt")
    assert "fun AppProbeTicker" in probe, "APP 缺少分区爬虫的悬浮条"
    assert "fun ProbeCrawlCard" not in probe, "分区爬虫的任务卡已无消费方，应删除"
    # 3.7.91：站点/词条种类标签由顶层 val 改成函数（val 里调 s() 会把语言冻住），
    # 断言锚点跟着换成函数名——查的仍是"站点切换存在"这一件事。
    assert "fun probeSites()" in probe and "rememberJobElapsed" in probe, \
        "APP 缺少站点切换/本地计时器"
    assert "if (ps.term.isNotBlank()" not in probe, "APP 进页又自动搜索了（必须点搜索）"
    assert "val running = job?.running == true" in probe and "if (running)" in probe, \
        "APP 运行中没有隐藏搜索结果"
    assert "s.job =" not in probe and "probePoll(" not in probe, \
        "APP 探针页又回到页面级轮询（离开页面会失联）"
    assert "val site: String = \"wnacg\"" in src("AppShared.kt"), "APP 路由没有携带站点"
    assert "job: ProbeJob?" not in src("FeaturesCrawl.kt"), "APP 清单爬虫页又要求分区爬虫的任务卡入参（两者应独立）"
    assert "ProbeCrawlCard" not in src("ProbeScreen.kt"), "分区爬虫的任务卡已无消费方，应删除"


def test_index_assets_cache_busted():
    """静态资源必须带版本查询串：否则浏览器可能一直用旧的脚本，
    修好了也看不到（3.6.21 的修复曾被这一条掩盖：磁盘代码已坏/已好，页面还是旧行为）。"""
    html = _read(INDEX_HTML)
    with open(os.path.join(PROG_DIR, "VERSION"), "r", encoding="utf-8") as f:
        ver = f.read().strip()
    assets = ["/static/js/%s.js" % n for n in JS_ORDER] + ["/static/style.css"]
    for asset in assets:
        m = re.search(re.escape(asset) + r"\?v=([0-9][0-9A-Za-z.\-]*)", html)
        assert m, "%s 的引用缺少 ?v=<版本> 缓存击穿参数" % asset
        assert m.group(1) == ver, ("%s 的缓存版本 %s 与 VERSION(%s) 不一致"
                                   % (asset, m.group(1), ver))


def test_crawl_monitor_panel_replaces_log_only_view():
    """3.7.58/3.7.59：清单爬虫的主视图是监控面板（同款作品卡 + 封面），日志已移除。

    3.7.59 又改了三处：卡片与分区爬虫一致（probe-card/probe-cover）、
    运行中用胶囊变绿代替状态灯、离开界面后"已完成"回到空闲。
    """
    html = _read(INDEX_HTML)
    assert 'id="crawlTicker"' in html, "缺少全局爬取浮标 #crawlTicker"
    crawl = _js_src("crawl")
    assert 'id="crawlMonitor"' in crawl, "清单爬虫页缺少监控面板容器 #crawlMonitor"
    assert "crawlRefreshJob(" in crawl, "启动/轮询没有刷新任务快照"
    assert 'id="crawlLog"' not in crawl and "crawl-log-wrap" not in crawl, "运行日志面板应已移除"
    mon = _js_src("crawlmon")
    assert "probe-cover" in mon and "/api/crawl/probe/cover" in mon, "监控卡片没有用分区爬虫同款封面卡"
    # 3.6.140 状态表函数化 crawlJobStates()（切语言跟随）——查的仍是"监控面板有状态文案渲染"这件事
    assert "crawlJobStates" in mon and "crawlJobCard" in mon, "监控面板缺少卡片渲染"
    assert "sawRunning" in mon, "离开界面后没有把\"已结束\"重置为空闲"
    css = open(os.path.join(PROG_DIR, "static", "style.css"), encoding="utf-8").read()
    assert ".crawl-kind.run" in css and "#43c6a8" in css, "运行中的任务胶囊没有变绿"


def test_frontend_copy_says_tongren_not_genzaku():
    """3.7.59：前端（网页 + APP）面向用户的「原作」表述统一改为「同人」。

    内部标识一律不动：API 的 `kind=original`、DB 的 `type='original'`、
    解析器的 `original` 词条类型——所以只检查**字符串字面量**，注释里的
    "original 标签" 属于开发说明，不受影响。
    """
    import glob
    q = re.compile(r"""'([^'\n]*)'|"([^"\n]*)"|`([^`]*)`""")
    bad = []
    for path in glob.glob(os.path.join(PROG_DIR, "static", "js", "*.js")):
        with open(path, encoding="utf-8") as f:
            for m in q.finditer(f.read()):
                txt = next(g for g in m.groups() if g is not None)
                if "原作" in txt:
                    bad.append(os.path.basename(path) + ": " + txt[:40])
    kt_dir = os.path.join(PROG_DIR, "android", "app", "src", "main", "java",
                          "com", "biblioteca", "reader")
    for path in glob.glob(os.path.join(kt_dir, "*.kt")):
        with open(path, encoding="utf-8") as f:
            for m in re.finditer(r'"([^"\n]*)"', f.read()):
                if "原作" in m.group(1):
                    bad.append(os.path.basename(path) + ": " + m.group(1)[:40])
    assert not bad, "仍有「原作」文案：%r" % bad[:5]


def test_cover_nodes_survive_incremental_updates():
    """3.7.61：封面「出现两秒后消失」的根因是**整块重画**。

    分区爬虫补全剩余结果、清单爬虫按 rev 刷新，都在 2 秒内重画一次 grid ——
    每张 <img> 被销毁重建，第二轮请求一旦失败就被 onerror 隐藏。修法：
      * probe.js：补全/继续加载改走 probeAppendCards（只追加新卡片）；
      * crawlmon.js：只在"卡片集合指纹"变化时重建，其余帧只改文本/类名。
    """
    probe = _js_src("probe")
    cards = _js_src("probecards")
    assert "function probeAppendCards" in cards and "function probePaint" in cards, \
        "分区爬虫没有增量追加渲染"
    assert "probePaint()" in probe, "补全/继续加载没有走增量绘制"
    mon = _js_src("crawlmon")
    assert "crawlJobSig" in mon and "crawlState.sig !== sig" in mon, \
        "监控面板仍按 rev 全量重建（图片会被反复销毁重建）"


def test_probe_marks_duplicates_like_inbox():
    """3.7.61：搜索结果要标出库里已有的作品，文案与收件箱一致。"""
    cards = _js_src("probecards")
    assert "probe-dup" in cards and "疑似重复：与「" in cards, "结果卡没有重复徽标"
    assert "is-dup" in cards
    assert "filter(w => !w.dup)" in cards, "「全选」没有跳过疑似重复"


def test_data_i18n_attributes_have_explicit_values():
    """3.6.117 回归钉：`data-i18n` 布尔简写（无值）会让 i18nApplyDom 首帧把文字清空——
    用户报障"抽屉功能键都不显示字"的真凶（14 处静态标注全被清成空串）。
    所有标注必须带显式 key；i18n.js 同时须有空属性防御（双保险）。"""
    import re as _re
    html = _read(INDEX_HTML)
    bare = _re.findall(r'data-i18n(?:\s[^=]|>)', html)
    assert not bare, "index.html 存在无值 data-i18n（会清空文字）：%r" % bare[:3]
    js = _js_src("i18n")
    assert "getAttribute('data-i18n') || el.textContent.trim()" in js, \
        "i18nApplyDom 缺空属性防御（应回退用元素自身文字当 key）"


def test_grid_delegation_dispatches_by_card_kind():
    """`#grid` 的点击委托必须按卡类型分派（3.6.170）。

    事故：分区视图（全部画师 / 同人分区 / 喜爱）的卡片**复用** `.circle-card` 样式，
    但没有 `dataset.group`，而委托无条件 `location.hash = '#/circle/' + enc(group)`
    → `#/circle/undefined`，前端找不到该社团、踢回首页，表现就是
    「网页端画师页和同人分区点不进去」。APP 是原生渲染，所以只有网页端坏、长期没被发现。
    """
    src = _js_src("menu")
    assert "circle.dataset.artist" in src, "委托没处理画师卡"
    assert "circle.dataset.original" in src, "委托没处理同人分区卡"
    assert not re.search(r"if \(circle\)\s*\{\s*location\.hash = '#/circle/'", src), \
        "委托又变回「任何 .circle-card 都当社团卡」了"
    # 逐卡绑定与委托并存时会互相覆盖 hash（谁最后写谁说话），只留委托一处
    assert "querySelectorAll('.circle-card').forEach" not in _js_src("home"), \
        "home.js 又给分区卡逐卡绑了跳转，会和 #grid 委托打架"


def test_originals_view_has_new_zone_card_on_top():
    """同人分区视图首位必须有「新建分区」卡（3.6.170，用户要求：作品卡片形状、中间加号、下面文字）。"""
    home = _js_src("home")
    assert "function newOriginalCard" in home
    assert "grid2.appendChild(newOriginalCard())" in home
    assert "empty: true" in home, "没用后端「只建空分区」那条分支（会顺手把命中的作品全打上标签）"
    # 置顶：加号卡必须在渲染数据卡之前追加
    i_add = home.index("grid2.appendChild(newOriginalCard())")
    i_loop = home.index("for (const a of sorted)")
    assert i_add < i_loop, "「新建分区」卡没有排在首位"
