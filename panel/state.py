# -*- coding: utf-8 -*-
"""panel/state.py —— 进程内唯一的可变状态持有者（3.6.49 结构重构 Stage 5）。

为什么要有它：扫描/索引状态原先散落在 `app.py` 的模块级全局里（`_INDEX`/`_INDEX_LOADED`/
`_INDEX_KEYS` …），任何函数都能 `global` 赋值、测试也只能靠"打模块属性"隔离。
这带来两个老问题：
  1. **打桩面跟着文件漂移**：代码搬进新模块后，`monkeypatch.setattr(app, ...)` 不再生效；
  2. **状态可能分叉**：两处各自赋值 = 两份状态，症状是"改了没生效 / 重启后打回原形"。

现在把状态收进本对象，`app.py` 只持有**一个**实例（`state = LibraryState()`）。
调用方一律 `state.index` / `state.index_keys` 访问；测试打桩打在**对象属性**上，不随文件搬迁漂移。
这是路由拆分（Blueprint）的前置条件：拆出去的路由模块只要拿到同一个 state 实例即可。

纪律（`docs/engineering-discipline.md` §4.3）：
  * 本对象**只允许** `app.py` 创建一次，任何模块不得再赋值 `state` 本身；
  * 新增进程级可变状态一律加在这里，不再往模块级全局里塞；
  * 本模块不 import app.py，也不做任何 I/O（纯数据容器，便于单测）。

字段对应关系（迁移期对照，便于检索旧名）：
  `_INDEX`        → `state.index`
  `_INDEX_LOADED` → `state.index_loaded`
  `_INDEX_KEYS`   → `state.index_keys`
  `ORIGINALS`     → `state.originals`
  `NORM_TO_CANON` → `state.norm_to_canon`（注意：`djc_parse.NORM_TO_CANON` 是解析引擎自己的映射，由 app 同步）
  `LIB`           → `state.lib`
  `SCAN_STATE`    → `state.scan_state`
  `_RESCAN`       → `state.rescan`
  `REGION_COVERS` → `state.region_covers`
  `_OWNER_INDEX`  → `state.owner_index`
  `_TERMS`        → `state.terms`
  `_KNOWN`        → `state.known`
  `_UNFILED_PATHS`→ `state.unfiled_paths`
"""
# 身份归一逻辑版本：make_work 的 circle/bare 归一规则一旦变动就 bump 它，
# 让 library_index.json 里的 works 缓存整表作废重算（否则旧 circle 会被缓存住、长期不收敛）。
# 3.6.151：作品多了一个 size 字段（按文件大小排序用）——旧缓存没有它，必须整表重算一次。
# 3.6.166：归并逻辑改了（孤词条回头认库内画师/社团、按主社团归区）——旧 circle 不可信。
NORM_LOGIC_VERSION = "3.6.166"

# 「最近入库」时间的初始化基准版本（3.6.151 起由"档案创建时间"改为"作品文件最新 ctime"）。
# 不符则清空 groups 记录，让每个社团按新基准重新初始化一次。
# 不这么做的话，已存在的 742 条记录会一直保留旧基准（at == created_at），修了初始化也白修。
# 3.6.166：基准改成"取 DB added_at 作下限"——旧记录是按"数量增加才推进"算的，
# 已被卡在过期时间上（实测こけもも停 09-06 而库内最新入库是 10-22），必须整批重算。
# 3.6.169：`added_at == 文件 mtime`（首建库回填的近似）时改用「分区首次登记时间」兜底。
# 三个 10-29 新建的分区当时卡在 10-22，排在 10-25 的 WASABI 后面（用户报障），
# 旧记录里存的就是那个错值，不升版本就永远修不好。
ARRIVAL_VERSION = "3.6.169"

INDEX_SCHEMA_V = 3          # library_index.json 的 v：v3 = 作者多值 personals + 笔名归一


class LibraryState:
    """扫描缓存与索引的持有者。

    字段语义与旧全局完全一致（迁移是"换容器"，不是"改行为"）：
      index         索引文档（dict）：{"v", "originals_hash", "works", "norm_v", "groups"…}
      index_loaded  是否已尝试从磁盘载入（True 后不再重复读盘，即使读失败）
      index_keys    本轮扫描仍然有效的键集合（保存时清理已删除作品的旧条目）
      originals     原作词条名单（来自 config + 内置名单）
      norm_to_canon 归一化后的词条 → 规范名映射（含用户登记的别名链）
      lib           当前库数据缓存：{"data": 扫描结果或 None, "rev": 修订号, "stale": 是否有旧数据可服务}
      scan_state    扫描进度：{"running", "done", "total"}（前端轮询显示）
      rescan        后台重扫 single-flight 标记：{"pending"}
      region_covers 区域封面覆盖（三角色分桶；None = 尚未从磁盘载入）
      owner_index   (group/work) → 库内键 的反查索引缓存 {"src", "map"}
      terms         待定词条印证索引（TTL 缓存）{"at", "circles", "authors", "ac", "main"}
      known         已知词条表（社团/个人/主词条）{"ready", "circles", "pc"}
      unfiled_paths 扫描发现的无归属作品路径（交给收件箱同步搬运）
    """

    __slots__ = ("index", "index_loaded", "index_keys", "originals", "norm_to_canon",
                 "lib", "scan_state", "rescan", "region_covers", "owner_index",
                 "terms", "known", "unfiled_paths")

    def __init__(self, norm_logic_version=NORM_LOGIC_VERSION):
        self.index = {
            "v": INDEX_SCHEMA_V,
            "originals_hash": "",
            "works": {},
            "norm_v": norm_logic_version,
            # 3.6.151：入库时间的初始化基准版本。**必须在新建时就写上**——否则
            # "首次建索引 → 存盘 → 重启"会被判成需要迁移，每次重启都把 groups 清空重算。
            "arrival_v": ARRIVAL_VERSION,
        }
        self.index_loaded = False
        self.index_keys = set()
        self.originals = []
        self.norm_to_canon = {}
        self.lib = {"data": None, "rev": 0}
        self.scan_state = {"running": False, "done": 0, "total": 0}
        self.rescan = {"pending": False}
        self.region_covers = None
        self.owner_index = {"src": None, "map": {}}
        self.terms = {"at": 0.0, "circles": {}, "authors": {}, "ac": {}, "main": {}}
        self.known = {"ready": False, "circles": set(), "pc": {}}
        self.unfiled_paths = set()

    def reset_index(self, norm_logic_version=NORM_LOGIC_VERSION):
        """把索引恢复成"空但可用"的初始态（读盘失败 / 词条库变化时使用）。
        与旧实现一致：**不**改动 index_loaded（是否已载入由调用方决定）。"""
        self.index = {
            "v": INDEX_SCHEMA_V,
            "originals_hash": "",
            "works": {},
            "norm_v": norm_logic_version,
            # 3.6.151：入库时间的初始化基准版本。**必须在新建时就写上**——否则
            # "首次建索引 → 存盘 → 重启"会被判成需要迁移，每次重启都把 groups 清空重算。
            "arrival_v": ARRIVAL_VERSION,
        }

    def index_works(self):
        """当前索引里的作品缓存（只读访问用；写入请走原有锁）。"""
        return self.index.get("works") or {}

    def snapshot(self):
        """调试/诊断用的浅快照（不含锁，不用于并发写路径）。"""
        return {
            "loaded": self.index_loaded,
            "works": len(self.index.get("works") or {}),
            "keys": len(self.index_keys),
            "schema": self.index.get("v"),
            "groups": len(self.index.get("groups") or {}),
        }


__all__ = ["LibraryState", "NORM_LOGIC_VERSION", "INDEX_SCHEMA_V"]
