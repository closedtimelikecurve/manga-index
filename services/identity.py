# -*- coding: utf-8 -*-
"""services/identity.py —— 词条身份归一与别名体系（3.6.57 Stage7 从 app.py 抽出）。

负责「文件名里的词条 → 库里的社团/画师/分区」这段收敛：
  * 词条键与印证索引（`_term_key` / `_term_index`）；
  * 别名体系（作者 / 社团 / 分区）与已知词条学习（`_known_learn`）；
  * 社团名归一、主社团判定、裸词条反查与词条救援（`resolve_bare_term`）；
  * 黑名单/豁免名单与已解散社团。
跨域依赖一律 `h().xxx`（状态在 `app.state`，词条库在 `h().state.originals`）。
"""
import json
import os
import re
import time
import unicodedata

import djc_parse as _dp
import meta_store as meta

from flask import request

from panel.host import h

def _canon_circle(c):
    """社团名规范化：剥掉结尾的下划线变体。
    站点源标题会带来『HeartBreak_』『林檎のなる木_』这类带尾巴的写法，
    与真实社团『HeartBreak』『林檎のなる木』是同一社团，词条学习/解析一律折叠。"""
    c = str(c or "").strip()
    canon = re.sub(r"_+\s*$", "", c).strip()
    return canon or c

def _registry_from_lib():
    """从当前扫描结果构建词条库：
    circles: 已知社团名；personal_circles: 作者 -> 其所属社团集合。
    合作作品逐位拆开登记（A & B 各自归入该社团）；笔名别名折叠到正名。"""
    circles, personal_circles = set(), {}
    for g in h().get_library()["groups"]:
        for w in g["works"]:
            if w.get("circle"):
                circles.add(w["circle"])
                for a in (w.get("personals") or
                          ([w["personal"]] if w.get("personal") else [])):
                    if a:
                        personal_circles.setdefault(_canon_author(a), set()).add(w["circle"])
    return circles, personal_circles

def _term_key(s):
    """词条比较键（3.6.12）：**只用于查表比对**，绝不改写展示/落盘名。

    折叠分隔符差异（- _ — ：: , ， 、 . ・ 空格）与大小写、尾部下划线。
    同一个社团在站点/爬虫/各汉化组手里会写出一整串变体——本项目实例：
      TOZANBU / TOZAN_BU / TOZAN：BU / TOZAN BU / TOZAN-BU / TOZAN:BU
    （爬虫日志可证：搜索词条 `[TOZAN:BU (Fujiyama)…]`、落盘 `[TOZAN BU (Fujiyama)…]`、
      站内还有 `[TOZAN：BU (富士やま)]…`）。肉眼同源，字符串上却是六个互不相认的陌生人——
    旧的 `_canon_circle` 只剥**结尾**下划线，对上述变体一律无感，词条库因此碎成一地，
    新出现的写法永远"不认识"，只能停在待定词条。"""
    s = _canon_circle(str(s or "").strip())
    return re.sub(r"[\s_\-—－:：,，、.・]+", "", s).lower()

def _term_index(force=False):
    """待定词条印证索引（TTL 缓存）：circles / authors 归一键→规范名、
    ac 画师→社团列表、main 画师→主社团（按作品数取证）。

    3.6.65 结构：DB 取证在 `_terms_from_db`，画师-社团合并（DB ∪ config）在
    `_artist_circle_lists`。**注意这里的 main 是"画师→主社团"字典，不是进程入口**——
    早前搬迁时它被误写成 `h().main`，会把 `app.main` 覆盖成 dict，本轮已修。
    """
    cached = h().state.terms
    if cached["circles"] and not force and (time.time() - cached["at"]) < h()._TERMS_TTL:
        return cached
    circles, authors, main_map = _terms_from_db()
    ac = _artist_circle_lists(authors)
    cached.clear()
    cached.update({"at": time.time(), "circles": circles, "authors": authors,
                   "ac": ac, "main": main_map})
    return cached


def _terms_from_db():
    """从 DB 取「作品实证」的词条：circles / authors 归一键→规范名、main 画师→主社团。

    失败时返回已收集到的部分（并记日志），不抛——扫描热路径不能因为索引失败而中断。
    """
    circles, authors, main_map = {}, {}, {}      # 失败时保留已收集部分（下面 except 不抛）
    try:
        con = meta._connect()
        for (c,) in con.execute("SELECT DISTINCT circle FROM works WHERE circle<>''"):
            c = str(c or "").strip()
            if c and not _term_blacklisted(c):
                circles.setdefault(_term_key(c), c)
        for (a,) in con.execute("SELECT DISTINCT author FROM work_authors"):
            a = str(a or "").strip()
            if a and not _term_blacklisted(a):
                authors.setdefault(_term_key(a), a)
        # 画师 → 主社团（**作品实证**：该画师名下作品实际落在哪个社团，按作品数降序）
        # 比 artist_circles 更可靠——后者只在导入/改名时学，扫描期不写，且历史上有脏条目。
        main_map = _pick_main_circles(con.execute(
            "SELECT a.author, w.circle, COUNT(*) FROM work_authors a"
            " JOIN works w ON w.key = a.key WHERE w.circle <> '' GROUP BY a.author, w.circle"))
    except Exception:
        h().log.exception("构建词条索引失败")
    return circles, authors, main_map


def _pick_main_circles(rows):
    """(画师, 社团, 计数) 行 → 画师→主社团。

    取作品数最多者；同数按社团名升序，保证多轮扫描结果一致（不会来回抖）。
    """
    best = {}
    for a, c, n in rows:
        a, c = str(a or "").strip(), str(c or "").strip()
        if not a or not c or _term_key(a) == _term_key(c):
            continue                      # 自我映射（脏数据）不计
        cur = best.get(a)
        if cur is None or n > cur[1] or (n == cur[1] and c < cur[0]):
            best[a] = (c, n)
    return {a: c for a, (c, _n) in best.items()}


def _artist_circle_lists(authors):
    """画师 → 社团列表（DB 权威 ∪ config 旧值）。
    顺带把只出现在 artist_circles 里的画师补进 authors（否则印记不到他）。"""
    ac = {}
    try:
        for a, cs in meta.artist_circles().items():
            a = str(a or "").strip()
            if not a:
                continue
            authors.setdefault(_term_key(a), a)
            for c in cs:
                ac.setdefault(a, []).append(str(c))
    except Exception:
        h().log.exception("归并画师-社团关系失败")
    for a, cs in (h().CFG.get("artist_circles") or {}).items():
        if not isinstance(cs, list):
            continue
        a = str(a or "").strip()
        if not a:
            continue
        authors.setdefault(_term_key(a), a)
        ac.setdefault(a, []).extend(str(c) for c in cs if str(c).strip())
    return ac

def _main_circle_of(author):
    """画师的主社团（3.6.12）。取法按可信度递减，保证跨轮次稳定、不会每轮乱跳：
      1. **作品实证**：该画师名下作品实际落在哪个社团（作品数最多，同数按名称序）——最可信；
      2. artist_circles 里**确实在已知社团集合中存在的**候选；
      3. artist_circles 里第一个非自我映射的候选。
     全程剔除"画师→自己"的脏条目（归一后同名）。"""
    idx = _term_index()
    c = idx["main"].get(author)
    if c:
        return c
    ak = _term_key(author)
    out = ""
    for cand in (idx["ac"].get(author) or []):
        cand = str(cand or "").strip()
        if not cand or _term_key(cand) == ak:
            continue
        if _term_key(cand) in idx["circles"]:
            return cand
        if not out:
            out = cand
    return out

def _canon_circle_resolved(circle):
    """圈子规范名（3.6.12）：折叠分隔符变体后取词条库里的**首见规范名**。

    与 `_term_key` 配套——`_term_key` 只用于查表比对，这里把"查到的规范名"回填成
    展示/落盘名，使 TOZAN_BU / TOZAN：BU / TOZANBU / TOZAN-BU / TOZAN-BU 这整串变体
    在任何地方都统一成一个社团，不再各算各的、把画师目录反判成"未定社团"。"""
    circle = _canon_circle(circle)
    if not circle:
        return ""
    idx = _term_index()
    c = idx["circles"].get(_term_key(circle))
    return c if c else circle

def _resolve_bare(bare):
    """待定词条印证（3.6.12）：裸 [a] 词条到底是谁？
    返回 None（维持待定）/ {"as": "circle", "name": 社团规范名}
         / {"as": "personal", "circle": 主社团（可能为空）}。
    顺序很关键：**先判社团、再判画师**——一个名字若两种身份都沾边，宁可当社团，
    因为"社团名被当成画师"正是本次要修的错（TOZAN-BU 被列进画师名单）。"""
    idx = _term_index()
    k = _term_key(bare)
    if not k:
        return None
    c = idx["circles"].get(k)
    if c:
        return {"as": "circle", "name": c}
    if k in idx["authors"]:
        return {"as": "personal", "circle": _main_circle_of(idx["authors"][k]) or ""}
    return None

def _author_aliases():
    """笔名别名表：DB 权威 ∪ config 旧值（3.0 迁移后 config 对应键只读不再写回，
    合并视图保证双轨兼容——测试/旧配置直接喂 CFG 的条目依然生效）。
    作者多名归并（Hydrus siblings）——hiten 与 飛天御姐流 是同一人时，别名一律折叠到正名上。"""
    try:
        db = meta.author_aliases()
    except Exception:
        db = {}
    raw = h().CFG.get("author_aliases")
    legacy = {}
    if isinstance(raw, dict):
        legacy = {str(k).strip(): str(v).strip() for k, v in raw.items()
                  if str(k).strip() and str(v).strip()}
    out = dict(legacy)
    out.update(db)          # DB 权威：同别名冲突时以 DB 为准
    return out

def _circle_aliases():
    """3.6.11 社团别名表（DB 权威 ∪ config 旧值，与笔名别名同一套双轨合并视图）。"""
    try:
        db = meta.circle_aliases()
    except Exception:
        db = {}
    raw = h().CFG.get("circle_aliases")
    legacy = {}
    if isinstance(raw, dict):
        legacy = {str(k).strip(): str(v).strip() for k, v in raw.items()
                  if str(k).strip() and str(v).strip()}
    out = dict(legacy)
    out.update(db)
    return out

def _original_aliases():
    """3.6.19 原作别名表（DB 权威 ∪ config 旧值，同笔名/社团的双轨合并视图）。
    原作名写法多样（Fate／Grand Order / FGO…）：别名折叠到规范名，
    解析器据此把变体括号归入同一原作分区。"""
    try:
        db = meta.original_aliases()
    except Exception:
        db = {}
    raw = h().CFG.get("original_aliases")
    legacy = {}
    if isinstance(raw, dict):
        legacy = {str(k).strip(): str(v).strip() for k, v in raw.items()
                  if str(k).strip() and str(v).strip()}
    out = dict(legacy)
    out.update(db)
    return out

def _canon_circle_name(name):
    """社团名归一（3.6.11）：别名沿链归并到正名，visited 防环。
    与 _canon_author 的区别——**只查社团别名表**，不混用笔名别名。"""
    aliases = _circle_aliases()
    cur = _canon_circle(str(name or "").strip())
    if not aliases:
        return cur
    seen = set()
    while True:
        if cur in seen:
            break
        seen.add(cur)
        nxt = aliases.get(cur)
        if not nxt:
            break
        cur = _canon_circle(nxt)
    return cur

def _canon_author(a):
    """作者名规范化：尾下划线折叠 + 笔名别名沿链归并（visited 防环）。
    别名表键按"原始形式"与"下划线折叠后"两种形态查找——
    用户登记『Hiten_』或『Hiten』都能命中同一条。"""
    aliases = _author_aliases()
    if not aliases:
        return _canon_circle(a)
    seen = set()
    cur = str(a or "").strip()
    while True:
        if cur in seen:
            break
        seen.add(cur)
        nxt = aliases.get(cur) or aliases.get(_canon_circle(cur))
        if not nxt:
            break
        cur = _canon_circle(nxt)
    return cur or _canon_circle(a)

def _ensure_known_registry():
    """首次调用补齐全库扫描底座：已知社团 + 画师→社团。

    3.6.65 结构：ac 合并抽到 `_merged_artist_circles`，折叠归一抽到 `_fold_known_sets`。
    """
    if h().state.known["ready"]:
        return
    circles, pc = _registry_from_lib()
    for artist, cs in _merged_artist_circles().items():
        for c in cs:
            if str(c).strip():
                pc.setdefault(_canon_author(str(artist)), set()).add(str(c))
    h().state.known["circles"], h().state.known["pc"] = _fold_known_sets(circles, pc)
    h().state.known["ready"] = True


def _merged_artist_circles():
    """画师→社团映射：DB（3.0 权威存储）∪ config 旧值（迁移遗留只读），双轨合并。"""
    ac = {}
    try:
        for a, cs in meta.artist_circles().items():
            ac.setdefault(str(a), set()).update(str(c) for c in cs)
    except Exception:
        h().log.exception("初始化已知画师登记表失败")
    for artist, cs in (h().CFG.get("artist_circles") or {}).items():
        if not isinstance(cs, list):
            continue
        ac.setdefault(str(artist), set()).update(str(c) for c in cs if str(c).strip())
    return ac


def _fold_known_sets(circles, pc):
    """全量折叠 `_` 变体 + 笔名别名：同一画师指向『X』与『X_』或不同笔名时不再构成歧义。"""
    known_circles = {_canon_circle(c) for c in circles}
    folded = {}
    for artist, cs in pc.items():
        for c in cs:
            folded.setdefault(_canon_author(str(artist)), set()).add(_canon_circle(c))
    return known_circles, folded

def _known_learn(circle, personal):
    """登记一条 [C (P)] 知识（进程内即时生效）并持久化到元数据库（3.0 起 DB 权威；
    不再全量回写 config.json——那是 2.x"文件系统当数据库"时代的代价）。"""
    circle = _canon_circle(circle)
    personal = _canon_author(personal)
    if not circle or not personal:
        return
    if _term_blacklisted(circle) or _term_blacklisted(personal):
        return                                 # 词条黑名单：不学习、不进词条库
    # 3.6.12：拒绝"画师 → 自己"的脏学习。裸词条 [広乃あずま] 曾因 bare 被塞进 personals、
    # 又被当成社团学到词条库，于是 artist_circles 里堆了一大片「広乃あずま → 広乃あずま」
    # 这类自我映射——它们既污染词条库，又会让待定词条印证把画师判成社团。
    if _term_key(circle) == _term_key(personal):
        return
    _ensure_known_registry()                   # 首次调用补齐全库扫描底座
    h().state.known["circles"].add(circle)
    owners = h().state.known["pc"].setdefault(personal, set())
    if circle in owners:
        return
    owners.add(circle)
    try:
        meta.learn_artist_circle(personal, circle)
    except Exception:
        h().log.exception("记录画师-社团映射失败（下次扫描需重新学习）")

def _dissolved_circles():
    """已解散社团清单：DB circles 表（dissolved=1，权威）∪ config 旧值（3.0 迁移遗留只读）。"""
    try:
        db = meta.dissolved_circles()
    except Exception:
        db = set()
    try:
        legacy = {str(x).strip() for x in (h().CFG.get("dissolved_circles") or []) if str(x).strip()}
    except Exception:
        legacy = set()
    return db | legacy

def _term_whitelist():
    wl = list(h()._TERM_BLACKLIST_EXEMPT)
    try:
        wl += [str(x).strip() for x in (h().CFG.get("term_whitelist") or []) if str(x).strip()]
    except Exception:
        h().log.exception("解析词条豁免名单失败（请检查 config.json 的 term_whitelist）")
    return [w for w in wl if w]

def _term_blacklist():
    bl = list(h()._TERM_BLACKLIST_BUILTIN)
    try:
        bl += [str(x).strip() for x in (h().CFG.get("term_blacklist") or [])
               if str(x).strip()]
    except Exception:
        h().log.exception("解析词条黑名单失败（请检查 config.json 的 term_blacklist）")
    return [b for b in bl if b]

def _term_blacklisted(t):
    """词条是否命中黑名单（子串、不区分大小写）。"""
    t = str(t or "").strip()
    if not t:
        return False
    tl = t.lower()
    if any(w.lower() in tl for w in _term_whitelist()):
        return False                            # 豁免词优先：真实社团名不因子串撞黑名单被误拦
    return any(b.lower() in tl for b in _term_blacklist())

def _alias_kind(body=None):
    """从 query/body 取 kind，只认 author|circle|original，默认 author。"""
    v = ""
    if body and isinstance(body, dict):
        v = str(body.get("kind", "") or "").strip().lower()
    if not v:
        v = str(request.args.get("kind", "") or "").strip().lower()
    return v if v in h()._ALIAS_KINDS else "author"

def _aliases_of(kind):
    return {"circle": _circle_aliases, "original": _original_aliases}.get(
        kind, _author_aliases)()

def _pixiv_title(name):
    """[Pixiv] 标题规则：文件名带 [Pixiv] 词条时，剥掉全部括号段后的标题文本
    视为社团名/个人名候选（Pixiv 作品标题即画师名）。返回 "" 表示无可提取。"""
    if not re.search(r"\[\s*pixiv\s*\]", str(name), re.IGNORECASE):
        return ""
    base = os.path.splitext(str(name))[0]              # 先去扩展名，防标题混入 ".zip"
    t = re.sub(r"\[[^\[\]]*\]", " ", base)             # 去 [] 段
    t = re.sub(r"\([^\(\)]*\)", " ", t)               # 去 () 段
    t = re.sub(r"【[^【】]*】", " ", t)                    # 去 【】段
    t = re.sub(r"\s+", " ", t).strip(" -_.～~")
    if not t or len(t) < 2 or re.fullmatch(r"[0-9\s]+", t):
        return ""                                       # 空/单字符/纯数字标题不作候选
    return t[:40]

def _rescue_candidates(name):
    """按出现顺序收集合规候选词条：[] 与 () 内容，排除 跳过词/黑名单/已解散/
    纯数字/含嵌套括号/超长；末尾追加 [Pixiv] 标题规则候选。

    3.6.65 结构：单条是否合规抽到 `_rescue_ok`（规则一屏读完）。
    """
    dis = _dissolved_circles()
    cands = []
    for m in re.finditer(r"(\(|^|\s|】)(\()([^()\[\]]{1,40})(\))", str(name)):
        cands.append(m.group(3).strip())
    cands.extend(x.strip() for x in re.findall(r"\[([^\[\]]*)\]", str(name)))
    title = _pixiv_title(name)
    if title:
        cands.append(title)
    out = []
    for c in cands:
        if c and c not in out and _rescue_ok(c, dis):
            out.append(c)
    return out


def _rescue_ok(c, dis):
    """一条候选词条是否可用于词条救援（展会/刊号/原作/黑名单/已解散一律排除）。"""
    if not c or len(c) > 40:
        return False
    if _skip_like_term(c) or _term_blacklisted(c) or c in dis:
        return False
    if re.fullmatch(r"[0-9\s]+", c):
        return False
    if re.match(r"(?i)^(C\d+|COMIC)", c) or ("年" in c and "月号" in c):
        return False                                # 展会/刊号词条不作候选
    if c in h().state.originals or _dp._norm(c) in h().state.norm_to_canon:
        return False                                # 原作词条不作候选
    return True

def _rescue_personal(name):
    """词条救援：主词条不可用（空/黑名单/已解散）时，从文件名后续括号与
    [Pixiv] 标题里抢救真实社团名/个人名。词条库已收录的个人名优先（不猜错词），
    其次按出现顺序取第一个合规候选（陌生词条也入候选）。
    例：[無修正] [無邪気無修宇宙分組] X 【無邪気漢化組】 [玉砂糖] → 玉砂糖；
        [Pixiv] 玉砂糖 (17019837) → 玉砂糖（标题规则）。"""
    if not h().state.known.get("ready"):
        return ""                       # 词条库底座未建（首扫中）：不救援，避免重入扫描
    cands = _rescue_candidates(name)
    for c in cands:                     # 已收录个人名最可信
        pb = _canon_author(c)
        if pb and pb in h().state.known.get("pc", {}):
            return c
    return cands[0] if cands else ""

def _skip_like_term(b):
    """与 djc_parse._skip_term 同口径的跳过判定（汉化组/無修正/语言标记/禁漫）。"""
    return _dp.is_group_term(b) or ("無修正" in b) or b in ("中国翻訳", "中国語") or ("禁漫" in b)

def _work_has_author(w, nb):
    """该作品是否属于画师 nb（含"裸词条正好是这位画师"的情况）。"""
    for a in (w.get("personals") or ([w.get("personal")] if w.get("personal") else [])):
        if _canon_author(a) == nb or _canon_circle(w.get("bare") or "") == nb:
            return True
    return False


def resolve_bare_term(name_b):
    """待定词条解析（规则优先级：第3条 > 第2条）：
    返回 ("circle",) 视为社团 | ("personal", 社团) 为其添加社团名 | None 仍未匹配(待定)
    查进程级常驻词条库（扫描 + 即时学习 + config 持久化三者合并，_ 变体与笔名别名已折叠）。
    作者对应多个社团时按文库中该作者名下各社团作品数多数表决（平票/无数据仍返回 None）。
    合作作品待定词条（"A × B"）逐位反查：任一位命中即按其社团归档。

    3.7.43 结构：单作者解析 `_resolve_single_owner`、多社团表决 `_pick_by_owner_tally`
    提为模块级（原为嵌套闭包，函数 52→30 行）。
    """
    _ensure_known_registry()
    name_b = _canon_circle(name_b)
    if name_b in _dissolved_circles():
        return None   # 已解散的社团词条不再作社团/待定词条（自动降级到其他信息）
    if _term_blacklisted(name_b):
        return None   # 词条黑名单：不作为社团/待定词条反查
    if name_b in h().state.known["circles"]:
        return ("circle",)
    parts = _dp.split_authors(name_b)
    if len(parts) >= 2:                        # 合作作品待定词条：任一位命中即归档
        for p in parts:
            r = _resolve_single_owner(p)
            if r:
                return r
        return None
    return _resolve_single_owner(name_b)


def _resolve_single_owner(nb):
    """单个作者名的社团反查：唯一社团直接定；自引用按个人目录归档；多社团走表决。"""
    owners = h().state.known["pc"].get(_canon_author(nb))
    if not owners:
        return None
    if len(owners) == 1:
        only = next(iter(owners))
        # 自引用(画师=个人作品目录名)：按个人名目录归档,文件名不带 (P)
        return ("circle",) if only == _canon_author(nb) else ("personal", only)
    return _pick_by_owner_tally(nb, owners)


def _pick_by_owner_tally(nb, owners):
    """多社团歧义：多数表决——数一数文库里该作者在各社团下的作品数。
    平票或全为 0 → None（宁可留待定，也不猜）。"""
    tally = {c: 0 for c in owners}
    try:
        lib = h().get_library()
        for g in lib["groups"]:
            if g["name"] not in tally:
                continue
            for w in g["works"]:
                if _work_has_author(w, nb):
                    tally[g["name"]] += 1
    except Exception:
        h().log.exception("解析裸词条归属失败")
    best = max(tally.items(), key=lambda kv: kv[1])
    if best[1] > 0 and sum(1 for v in tally.values() if v == best[1]) == 1:
        return ("personal", best[0])
    return None
