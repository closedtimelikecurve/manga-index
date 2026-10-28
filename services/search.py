# -*- coding: utf-8 -*-
"""services/search.py —— 全文检索（FTS5 trigram + LIKE 兜底），3.6.76 从 meta_store 拆出。

**为什么单独成文件**：拆分时 `meta_store` 已顶到 1626 行的冻结上限，任何原地拆分都会让文件超限
（3.6.84 再拆备份/原作/画师三条支线后落到 516 行）。检索是"只读 + 纯查询装配"，
搬走不影响任何写路径的语义。

**为什么 `meta_store` 用 `__getattr__` 再导出而不是普通 import**：
本模块在导入期就要 `import meta_store` 取 `_LOCK/_connect/_in_chunks`；
若 `meta_store` 在底部直接 `from services.search import ...`，先导入本模块时
会撞上"半初始化模块"的 ImportError。PEP 562 的惰性属性访问两者都能工作，
且 `meta.search2` / `from meta_store import search2` / 打桩赋值都不受影响。

**语义不变量**（拆分时逐条保留）：
  1. 词项先做全半角扩展（原词 / NFKC / 全角化），**组内 OR、组间 AND**；
  2. FTS 只接 ≥3 字符的词项（trigram 下限），短词靠 LIKE；
  3. FTS 结果在前、LIKE 在后，按 key 去重保序，截断到 limit；
  4. 结果装配用批量 IN（按 `_in_chunks` 分块），不逐条查询。
"""
import unicodedata

import meta_store as meta


def _fw_variant(s):
    """半角 → 全角变体（3.6.38 #38）：NFKC 只能全角→半角，反向得手工映射
    （半角 query「ぼっち・ざ・ろっく!」要能命中全角内容「ぼっち・ざ・ろっく！」）。
    只转 ASCII 可打印区（0x21~0x7E → 0xFF01~0xFF5E）与空格（→ U+3000）。"""
    out = []
    for ch in str(s or ""):
        code = ord(ch)
        if 0x21 <= code <= 0x7E:
            out.append(chr(code - 0x21 + 0xFF01))
        elif ch == " ":
            out.append("\u3000")
        else:
            out.append(ch)
    return "".join(out)


def _term_groups(raw_terms):
    """每个词项扩展成 [原词, NFKC 归一, 全角化]（去重保序）。"""
    groups = []
    for t in raw_terms:
        variants = [t]
        for v in (unicodedata.normalize("NFKC", t), _fw_variant(t)):
            if v and v not in variants:
                variants.append(v)
        groups.append(variants)
    return groups


def _fts_keys(c, all_terms, limit):
    """FTS5 trigram 子串匹配：只接 ≥3 字符的词项；FTS 不可用/报错时静默降级到 LIKE。"""
    fts_terms = [t for t in all_terms if len(t) >= 3]
    if not fts_terms:
        return []
    match = " ".join('"%s"' % t.replace('"', '""') for t in fts_terms)
    try:
        return [r[0] for r in c.execute(
            "SELECT key FROM works_fts WHERE works_fts MATCH ? LIMIT ?", (match, int(limit)))]
    except Exception:
        return []


def _like_keys(c, term_groups, limit):
    """LIKE 兜底：任意长度词项全列扫（派生表规模下单次毫秒级）。"""
    conds, args = [], []
    for variants in term_groups:
        group = []
        for t in variants:
            pat = meta._like_pat(t)     # 单一源：meta_store 里 definition，originals_search 也用它
            group.append("(w.name LIKE ? ESCAPE '\\' OR w.circle LIKE ? ESCAPE '\\' OR"
                         " w.bare LIKE ? ESCAPE '\\' OR w.group_name LIKE ? ESCAPE '\\'"
                         " OR EXISTS(SELECT 1 FROM work_authors a WHERE a.key=w.key AND a.author LIKE ? ESCAPE '\\')"
                         " OR EXISTS(SELECT 1 FROM work_tags g WHERE g.key=w.key AND g.name LIKE ? ESCAPE '\\'))")
            args.extend([pat] * 6)
        conds.append("(" + " OR ".join(group) + ")")
    if not conds:
        return []
    return [r[0] for r in c.execute(
        "SELECT w.key FROM works w WHERE " + " AND ".join(conds) + " LIMIT ?",
        args + [int(limit)])]


def _dedup(seq):
    """按出现顺序去重（FTS 与 LIKE 结果合并时用）。"""
    out, seen = [], set()
    for k in seq:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _assemble(c, keys):
    """3.3.0：结果装配批量 IN 查询（此前逐 key 两条 SELECT，上限 500 时单次检索
    最多 ~1000 条语句且全程持全局锁）。"""
    out = []
    if not keys:
        return out
    sel = {}
    for chunk in meta._in_chunks(keys):
        q = ",".join("?" * len(chunk))
        for r in c.execute("SELECT key, group_name, name, pages, kind, added_at FROM works"
                           " WHERE key IN (%s)" % q, chunk):
            sel[r[0]] = r
    amap = {}
    for chunk in meta._in_chunks(keys):
        q = ",".join("?" * len(chunk))
        for k, a in c.execute("SELECT key, author FROM work_authors"
                              " WHERE key IN (%s) ORDER BY rowid" % q, chunk):
            amap.setdefault(k, []).append(a)
    for k in keys:
        w = sel.get(k)
        if not w:
            continue
        out.append({"key": w[0], "group": w[1], "work": w[2], "pages": w[3],
                    "kind": w[4], "added_at": w[5], "authors": amap.get(k, [])})
    return out


def search2(q, limit=200):
    """全局检索：FTS 优先、LIKE 兜底，合并去重后截断。空查询返回空列表。"""
    q = str(q or "").strip()
    if not q:
        return []
    term_groups = _term_groups([t for t in q.split() if t])
    all_terms = [t for g in term_groups for t in g]
    limit = int(limit)
    with meta._LOCK:
        c = meta._connect()
        keys = _dedup(_fts_keys(c, all_terms, limit) + _like_keys(c, term_groups, limit))
        return _assemble(c, keys[:limit])
