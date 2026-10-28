# 系统结构地图 · 架构评估 · 重构路线图

> 面向后续维护者（人 / agent）。目的：**改一处只需读一个文件**。
> 最近更新：2026-10-18（结构重构 Stage 1~7 完成：状态对象化 → 路由分层 → 业务下沉）。
> 历史审计：`docs/code-audit-2026-10-15.md`（那份报告的数字已被本次重构改写，见 §七）。
> 规则（怎么改、预算、豁免）在 **`docs/engineering-discipline.md`**，本文只说"现在长什么样、为什么这样切"。

---

## 一、总览（数据流）

```
作品文件（文库根 D:\<文库根>：社团/作品.zip 或 作品名/图片…）
        │
        │  djc_parse.py（纯解析：文件名 → 社团/画师/标题/原作/汉化…）
        ▼
services/scan.py（扫描 → make_work 作品 → scan_groups 社团）
        │        ▲ 增量签名命中 library_index.json，不重复开包
        ▼
services/index_cache.py（_state/library_index.json 缓存 + SWR 后台重扫）
        │
        ▼
meta_store.py（SQLite `_app/meta.db`：works/tags/author/reading/follows…）
        ▲ 落库 sync_scan（双护栏：_scan_ctx 快照校验 + 骤减闸门）
        │
routes/*.py（80 端点，薄层）──► static/（网页面板）  +  安卓 APP（同一套 API）
```

分层（自下而上，**依赖只能向下**）：

| 层 | 文件 | 性质 | 说明 |
|---|---|---|---|
| 解析层 | `djc_parse.py` | 纯函数 | 文件名 → 结构化词条。无 I/O、无状态。 |
| 工具层 | `common.py`、`panel/{deps,paths,audio,pages}.py` | 纯/无状态 | 路径、配置、媒体名、LRC、页序。 |
| 规则层 | `panel/naming.py` | **纯函数** | 字段 → 规范文件名（用户可见的命名契约）。 |
| 资源层 | `panel/{archive,images}.py` | 有缓存状态 | 压缩包句柄池、页缓存、缩略图、低带宽转码。 |
| 状态层 | `panel/state.py` | **唯一可变状态** | `LibraryState`（`app.state` 唯一实例）。 |
| 数据层 | `meta_store.py` | 有 DB 状态 | SQLite 唯一事实源 + 连接/迁移；扫描落库、检索、收件箱、首启迁移、备份、原作分区、画师档案已拆出七条支线（`services/*`，经 PEP 562 惰性再导出） |
| 服务层 | `services/*.py` | 业务实现 | 扫描、索引、查询、改名、收件箱、身份归一、封面、启动器… |
| 路由层 | `routes/*.py` | 薄层 | 80 端点按域拆 10 份；`h().xxx` 按名取值，**不 import app**。 |
| 装配层 | `app.py` | — | 常量 + Flask 实例 + 请求钩子 + 再导出命名面 + `main()` 调用。 |
| 外壳 | `index_launcher.py` + `launcher_{core,proc,ui}.py` | 独立进程 | tkinter 启动器：入口 58 行，配置/进程/视图三分（13 项烟测）。 |
| 爬虫域 | `crawlers/` | 本进程线程 | 3.7.58 起由 `services/crawl_run.py` 调度（先锁定作品 → 再集中爬取），不再拉子进程；`crawlers/*.py` 仍可单独 `python` 运行。3.7.59 起对外区分为**清单爬虫**（#/crawl，五任务按清单跑）与**分区爬虫**（#/probe，按作者/社团/同人名勾选），两边任务槽完全独立。 |
| 前端 | `static/js/*.js`（15 片） | 全局脚本 | classic script 顺序加载、共享全局词法环境；按视图切片，最长的 `probe.js` 463 行（计时器另拆 `probeclock.js`）。 |

---

## 二、目录地图

`D:\<文库根>\_app\`：

| 路径 | 行数 | 职责 |
|---|---:|---|
| `app.py` | 646（代码 259） | **装配层**：常量 / Flask 实例 / `@app.before_request` 门禁 / 全局错误兜底 / `services.*` 再导出 / `main()` 入口 |
| `common.py` | 241 | `APP_DIR`/`CONFIG_FILE`、config 读写、`LOG_DIR`/`STATE_DIR`/`CACHE_DIR`、`unique_path`、`clean_term` |
| `djc_parse.py` | 527 | 命名解析（纯函数） |
| `meta_store.py` | 516 | 元数据层：连接 / 表结构 / 评分阅读 / 收藏集 / 迁移入口 |
| `services/db_sync.py` | 279 | 扫描落库五阶段（sync_scan） |
| `services/search.py` | 133 | 全文检索（FTS + LIKE） |
| `services/inbox_db.py` | 108 | 收件箱登记 + 内容哈希去重 |
| `services/db_bootstrap.py` | 75 | 首启 config→DB 迁移 |
| `index_launcher.py` | 58 | 启动器入口：再导出 + `main()` |
| `launcher_core.py` | 301 | 面板配置/常量/日志/全局状态（ST/PROC/PORT） |
| `launcher_proc.py` | 420 | netstat/端口探测、Tailscale、Popen 启停与重启 |
| `launcher_ui.py` | 471 | tkinter 画布：品牌区、功能卡、事件、状态轮询 |
| `migrations/` | 712 | 一次性迁移/规范化 CLI（base 112 / migrator 227 / modes 373；`migrate.py` 只剩 80 行入口） |
| `panel/` | ~1180 | 服务端子包（§三） |
| `routes/` | 2280 | 路由层 10 个域（§四） |
| `services/` | 3100 | 业务实现（§五） |
| `crawlers/` | 2960 | 五任务爬虫 + 维护脚本；wnacg 一族已拆 `wnacg_{base,net,match,download,text,search}` + `nh_api`（`python crawlers/x.py` 与 `from crawlers import x` 都成立）；`wnacg_search` 只解析搜索结果（供分区爬取勾选，不做相似度裁决） |
| `static/` | 5300 | `index.html` / `js/`(17 片) / `style.css`(730) |
| `scripts/` | — | `quality_gate.py`（工程闸门）、事故恢复脚本、`dispatch_apk.bat` |
| `tests/` | 53 文件 / **444 项** | pytest；`conftest.py` 负责隔离 |
| `docs/` | — | 本文 + `engineering-discipline.md` + `quality-budget.json` + 历史审计 |

### 运行时产物目录

程序根目录只放**代码与用户配置**；其余归入 `_` 前缀功能目录（均已 `.gitignore`）：

| 目录 | 内容 | 可删？ |
|---|---|---|
| `_logs/` | `panel.log`、`crawl_log*.txt`、`Index_error.log` | 是 |
| `_state/` | `library_index.json`、`region_covers.json`、`crawl_state*.json` | 是（删 → 重扫） |
| `_cache/` | `thumb/`、`low/`、`upload/`、`jm_tmp/`、`nh_tmp/` | 是 |
| `_inbox/` | 收件箱作品实体（**不是缓存**） | 否 |

---

## 三、`panel/` 包（基础设施，无业务决策）

`app.py` 用 `from panel.X import ...` **再导出**，`app.natural_key`、`app._archive_read` 等命名面不变
（大量测试依赖）。`_WATCH_FILES` 自动纳入 `panel/*.py`（改动触发"代码改过没重启"检测）。

| 模块 | 职责 | 打桩点（测试直接改这些名字） |
|---|---|---|
| `panel/deps.py` | 可选依赖探测 `PIL_OK`/`RAR_AVAILABLE` | — |
| `panel/paths.py` | 路径/媒体名工具与常量 | `list_zip_images` |
| `panel/archive.py` | 压缩包句柄池、页缓存、视频临时文件 | `PAGE_CACHE_MAX_BYTES`、`_archive_read` |
| `panel/images.py` | 封面 LRU、缩略图、低带宽转码、Tailscale 判路 | `LOW_DIR`、`_tailnet_direct_map` |
| `panel/audio.py` / `panel/pages.py` | 音频页与页序/版本分组 | — |
| `panel/naming.py` | 规范文件名（纯函数，7 个具名步骤） | — |
| `panel/state.py` | `LibraryState`（唯一可变状态） | 全部经 `app.state.*` |
| `panel/http.py` | `@mutating` + 登记表（app 与 routes 共用同一 set） | `_MUTATING_ENDPOINTS` |
| `panel/host.py` | `h()`：取"当前真正在跑的 app 模块" | — |

---

## 四、`routes/`（87 端点 / 12 个域）

> 端点数按 `app.url_map` 实测（2026-10-25，3.6.116 收口）。3.6.115 新增 `routes/theme.py`
> 时本表漏登记，3.6.116 补上并把 `manage_circle` 从 `manage` 里拆开单列。

| 模块 | 端点数 | 内容 |
|---|---:|---|
| `routes/library.py` | 10 | 首页壳、`/api/config`、library(+meta)、circle、works、parse-info、增补信息/整标题、search |
| `routes/media.py` | 6 | pages / page / cover / audio(+manifest) / open |
| `routes/meta.py` | 17 | 作品元数据、评分、收藏夹、阅读进度/续读/统计、画师、关注、search2 |
| `routes/manage.py` | 7 | 删作品/封面、社团改名、画师改名、解散、黑名单 |
| `routes/manage_circle.py` | 3 | 区域封面读写（社团/画师/原作分区共用） |
| `routes/admin.py` | 12 | 面板重启、导入、上传分块/合并、备份/恢复/导出、APP 版本派发、配置保存 |
| `routes/inbox.py` | 5 | 收件箱列表/确认/清理半成品/删除/一键入库 |
| `routes/crawl.py` | 6 | 爬虫状态/启停/任务快照(`/api/crawl/job`)/清单读写 |
| `routes/originals.py` | 6 | 原作分区列表/检索/新增/加作品/移除/改名 |
| `routes/authors.py` | 3 | 作者别名增删查 |
| `routes/probe.py` | 5 | 分区爬取：搜索 / 封面 / 勾选下载 / 进度 / 取消 |
| `routes/theme.py` | 11 | 主题背景图（按端槽位）：`/api/theme/bg` GET/POST/DELETE（`?client=web\|app`，缺省 app）+ hero 四端点 + 本机图库（列表/入库/取图/删除，内置图禁删）；两处取图端点是 `PUBLIC_ENDPOINTS`（`<img>` 带不了 X-Token） |
| `routes/pair.py` | 4 | 扫码配对（3.6.144 改一次性票据）：`/api/pair/info` 给 `{canPair, url, ticketTtl, reason, tunnels, candidates}`，**不再返回主令牌**；`/api/pair/qr` 返回 `{ok, svg, expiresIn}`，码内 `{"i","p"}`（票据 120 秒）；`POST /api/pair/claim` 票据换设备令牌（410 过期 / 409 已用 / 400 无效，**公开端点**——新手机还没有令牌）；地址由 `services/pair_target.py` 探测，没有可达地址时 409 |

**铁律**：`routes/*.py` 一律 `h().xxx` 按名解析，**不得 `import app`**
（`python app.py` 时本模块是 `__main__`，再 import 会二次执行 → 双 Flask 实例、两份状态），
**也不得按值捕获**（`from app import find_work` 会让 `monkeypatch.setattr(app, "find_work")` 静默失效；
`test_crawl_parallel` 打的是 `app.subprocess.Popen`，失效会真的拉起爬虫进程）。

---

## 五、`services/`（业务实现）

| 模块 | 行数 | 内容 | 关键约束 |
|---|---:|---|---|
| `scan.py` | 599 | 扫描与分组：`collect_works_in_dir`/`make_work`/`scan_groups`/合作社团/别名合并/排序 | 只读，不改文件；由 4 项快照测试兜底 |
| `inbox.py` | 486 | 收件箱 + 导入流水线（`_inbox_sync`/`_import_process`/`_inbox_confirm_one`） | **所有调用含组内互调走 `h()`**：`_inbox_dir` 被 conftest 打桩 |
| `identity.py` | 464 | 词条身份归一、别名体系、黑名单/豁免/已解散、裸词条反查 | 组内互调可直呼（名字都是本模块函数） |
| `manage.py` | 327 | 删除/改名/合并/归档决策/路径守卫/空目录清理 | 组内互调**必须**走 `h()`：测试打桩 `app._delete`、`app._path_in_root` |
| `index_cache.py` | 255 | `library_index.json` 读写、作品级缓存、`_lib_touch`、SWR + 单飞重扫 | `_lib_touch` 是变更门禁的调用图根 |
| `queries.py` | 193 | `find_group/find_work`、`public_*`、`tags_index`、`search_authors`、每日推荐 | 只读 |
| `server.py` | 194 | `main()`：参数解析/端口绑定/启动横幅/主循环 | docstring 顶部三条铁律必须遵守 |
| `covers.py` | 133 | 区域封面覆盖（三角色桶、改名交接） | — |
| `crawl.py` | 236 | 爬虫任务：进程句柄、五任务清单、断点计数、日志、`crawl_script_path` | 3.7.58 起只作存储层（不再拉进程） |
| `crawl_run.py` | 520 | 两段式任务引擎：锁定 → **准备封面（阻塞）** → 集中爬取、任务快照、取消、清单回写 | 五任务各一槽位；封面预算 90s/5 并发 |
| `crawl_lock.py` | 188 | 锁定阶段：词条 → 具体作品（aid / 标题 / 封面），五种任务各一个解析器 | 只用 `crawlers.*`，不出网下载 |
| `crawl_fetch.py` | 69 | 集中爬取：wnacg 直链 / JM 整本 / N站 ZIP，统一落收件箱 | 订阅字节回调供面板显示 |
| `crawl_dup.py` | 190 | 搜索结果的「疑似重复」预判：**只比当前分区**（画师/社团/同人）+ 裸名称相近 + 页数相近（系列新作放行） | 分区索引缓存 60s |
| `originals.py` | 97 | 原作归一/候选选名/词条库增删 | — |
| `crawl_probe.py` | 340 | 分区爬取探测：站点搜索 + 封面转码缓存（域名白名单防 SSRF，含 JM 图床） | — |
| `crawl_probe_sites.py` | 198 | 多站点适配：JM `search_site` / N站 v2 search / 两站整本下载 | 搜索 30s 守护线程上限 |
| `crawl_pick.py` | 268 | 勾选下载 → 收件箱 → 自动入库归区（后台线程，入库持 SCAN_LOCK；进度快照含站点/字节/当前项/版本号） | `_JOB` 单任务槽 |
| `panel_admin.py` | 76 | 自重启与"代码已更新"检测 | `_schedule_exec`/`_validate_fresh_code` 为打桩点 |
| `pair_target.py` | 196 | 配对二维码的远程地址探测：进程白名单（Tailscale/ZeroTier/EasyTier/frp/ngrok…）+ 本机非回环 IPv4 分类（CGNAT `100.64/10` 归 Tailscale）+ **端口 TCP 探测**（本地 8765 只绑回环，绝不能编进码里）+ 决策（config `pair_url` > 页面 host > 隧道进程）；无地址/无监听时 `ok=False`，**绝不回落到 127.0.0.1** | **纯函数、无 Flask**；`interfaces`/`procs`/`probe` 可注入，测试不碰真机环境 |
| `pair_tickets.py` | 158 | 一次性配对票据：签发 / 消费 / 清理。默认 120 秒（`pair_ticket_ttl` 可调，夹 30~600）；**一次性用独占标记文件**（`O_CREAT\|O_EXCL`）实现跨进程原子；落 `_state/` 以便 8765/8766 双实例都能验；来源 IP 只记录不校验（网页在电脑、APP 在手机，源 IP 天然不同） | **纯函数、无 Flask**；目录由调用方传入 |
| `pair_devices.py` | 140 | 设备令牌：`dev-` + 32 hex，**只存 sha256**；按文件 mtime 缓存哈希表（每个请求都会查）；支持单台吊销与"最近使用"5 分钟节流写盘 | **纯函数、无 Flask**；与主令牌并列，见 `app._token_gate` |
| `theme_store.py` | 231 | 主题槽位/图库原语：白名单、魔数、槽位副本、按端 active、内置图注册表、旧全局槽位迁移 | **纯函数、无 Flask**；路径由 `routes/theme.py` 传入（那里才是打桩面） |
| `opener.py` | 66 | 系统默认程序打开作品/封面 | — |
| `appenv.py` | 67 | 日志、`config_payload`、启动行为开关 | — |

**再导出规则**：上面每个模块都在 `app.py` 里有一行 `from services.X import (...)`，
让 `app.find_work`、`app.scan_groups` 等命名面继续成立（测试与 routes 都靠它）。
**不要删这些再导出块**，除非同步改掉所有 `app.X` 引用与测试打桩点。

---

## 六、搬迁手册（搬代码前必读）

### 6.1 为什么用 `h()` 而不是 import

`python app.py` 时本模块是 `__main__`；任何 `import app` 都会**再执行一遍** app.py，
得到第二个 Flask 实例和两份状态。`panel/host.py::h()` 取 `sys.modules["app"]`（pytest 下）
或 `sys.modules["__main__"]`（直接运行时），每次调用**按名重新解析**，
所以 `monkeypatch.setattr(app, "X", ...)` 始终生效。

### 6.2 六个已踩过的坑（每个都真实炸过）

1. **局部变量不能叫 `h`**：`for h in (fd, tmp)` 会让整个函数里的 `h()` 变成未绑定局部变量 → `UnboundLocalError`。
2. **lambda 形参不是"局部名"**：`key=lambda g: g.get(...)` 的 `g` 若在改写集合里会变成 `lambda h().g:`（语法错）。
   提取器的局部名集合必须包含 `Lambda` 的形参。
3. **`global` 标量不能跟着函数走**：`global _INBOX_STATE_FIXED` 搬走后会变成新模块自己的全局。
   做法：`h()._INBOX_STATE_FIXED = True`（读写都走 `h()`），删掉 `global`。
4. **try/except 里定义的常量不算顶层 Assign**：`_WAITRESS_OK`、`_waitress_create` 会漏改，需手工补 `h().`。
5. **新模块必须自带 import**：`tempfile`/`logging`/`RotatingFileHandler` 这类"原文件已导入"的名字，
   提取器会当作已满足 → 只在调用时 `NameError`。**导入期看不出来，必须跑该域全量测试**。
6. **按名打桩会静默打空**：`monkeypatch.setattr(app, "ORIGINALS", x)` 在改名后不报错、只是不生效。
   迁移时同时 grep `app.X` 与 `setattr(app, "X"` 两种形态。

### 6.3 标准流程

1. `tests/` 里先有覆盖（没有就先补快照：固定输入 → 断言输出结构）；
2. AST 找目标函数与装饰器 → tokenize 只重写 **NAME token**（正则会把字符串里 `"index"` 改成 `"h().index"`）；
3. 新模块结构：docstring（为什么切、依赖方向）→ imports → 函数 → `ROUTES`+`register(app)`（仅 routes）；
4. 从 app.py 删段 → 在再导出区加 `from services.X import (...)`；
5. `pytest tests/ -q` → `python scripts/quality_gate.py --prune` → 独立提交；
6. 改了 `app.py` 必须重启面板（网页顶部会提示）。

---

## 七、体检（2026-10-18，AST 实测）

| 指标 | 10-15 审计 | 重构前 | 现在 |
|---|---:|---:|---:|
| `app.py` 行数（总 / 代码） | 6233 / — | 5413 / — | **643 / 314** |
| `app.py` 顶层函数 | 264 | 202 | **13** |
| 路由定义在 `app.py` | 74 | 74 | **0**（74 全在 `routes/`） |
| 模块级可变状态容器 | 16 | 16 | **0**（1 个 `state`） |
| `global` 声明 | 9 | 9 | **3**（标量开关） |
| `services/` 模块数 | 1 | 1 | **13** |
| 测试 | 255 | 337 | **341** |
| 函数债务（超 80 行 / cc15） | — | 80 | **29** |
| 静默异常 `except: pass` | 43 | 45 | **43** |
| 最高 cc | `api_supplement_info` 90 | `scan_groups` 46 | `migrate.reorganize_dirs` 37 / `crawl_wnacg.download_one` 36（仅剩一次性 CLI 与爬虫脚本） |

---

## 八、剩余债务与阻塞理由（下一批从这里继续）

**当前账本（2026-10-19，`docs/quality-budget.json` 为准）**：
函数债务 **18** 项 / 超限文件 **6** 个（判据：物理行 >800 **或** 有效代码行 >400）/ 静默异常 **41** 处。

### 8.1 一条硬约束：**"到顶"的文件里不能原地拆函数**

`scripts/quality_gate.py` 的棘轮把每个超标文件的 cap 冻结在"当时的值"。拆一个函数必然
多出几行（函数签名 + 空行），于是**在已到顶的文件里原地拆函数 = 文件立刻超限**。
实测两次：`meta_store.search2`（cc 26）拆完 1626 → 1648；在此之后 `_scan_*` 拆分又撞过一次。

**规则**：在这些文件里降函数复杂度，必须**同时把一个簇搬出去**（照 `scan.py` 拆 `coop.py`、
`meta_store` 拆 `search/inbox_db/db_sync/bootstrap` 的做法），用搬走的行数支付拆分的开销。
否则只是把红灯从"函数"格子挪到"文件"格子。

**搬出去之后怎么保持调用面不变**：`meta_store` 用的是 **PEP 562 `__getattr__` 惰性再导出**
（见 `_LAZY_MODULES`）。这样 `meta.inbox_list()` / `from meta_store import sync_scan` /
`monkeypatch.setattr(meta_store, "DB_PATH", ...)` 全部照旧；被迁模块导入期反向引用 `meta_store`
也不会撞"半初始化模块"的 ImportError。

| 曾经的"到顶"文件 | 行数（拆分前 → 现在） | 处理方式 |
|---|---|---:|
| `static/app.js` | 3103 → **0**（13 片，最长 339） | 3.6.84 按顶层区块切 classic script |
| `index_launcher.py` | 1094 → **58**（+core/proc/ui 共 1192） | 3.6.84 先补 13 项烟测再拆包 |
| `crawlers/crawl_wnacg.py` | 965 → **309**（+5 个模块） | 3.6.84 按 base/net/match/download/nh_api 拆 |
| `meta_store.py` | 1235 → **516**（+3 条支线） | 3.6.84 拆备份/原作/画师 |
| ~~`tests/test_originals_manual.py`~~ | 902 → 445 | 3.6.83 按主题拆两文件 |
| ~~`migrate.py`~~ | **80** | 3.6.78 拆成 `migrations/` 包 |
| ~~`app.py`~~ | 643 / **259** | 3.6.79 起持续瘦身 |

### 8.2 债务现状（3.6.84 收口）

| 维度 | 数量 | 说明 |
|---|---:|---|
| 文件债（物理行 / 有效代码行） | **0** | 全项目再无文件越过各自语言上限（py/js 800·400，kt 700·500）；最长的业务文件是 `services/scan.py` 586 / 392 |
| 生产代码函数债 | **0** | 全部 ≤ 80 行、cc ≤ 15 |
| 测试函数债 | 10 | 断言密集的多段式用例（`test_meta_store` 3、`test_originals_manual` 2 等）。**刻意保留**：拆开不改变覆盖，只会把"一条完整场景"切碎；这些条目留在 `docs/quality-budget.json` 作为棘轮上限，只降不升 |
| 静默吞异常 | 41 | 冻结额度，只降不升（新文件默认 0，靠 `--prune` 重建时按实测记账） |

**为什么不再拆测试**：它们的复杂度来自"断言多"而不是"分支多"——一个用例顺序验证 5 条
因果关系，拆成 5 个函数后每个都要重建同一套前置状态，覆盖不变、可读性更差。
纪律文件允许这种保留，前提是记账并写清理由（本节即理由）。

**后续新增代码的硬约束**：任何超过 400 行有效代码的新文件，必须在同一个提交里拆开；
不允许用 `--raise` 提额（只在"搬迁中"临时用，且必须带 `--why`）。
