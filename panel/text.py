# -*- coding: utf-8 -*-
"""panel/text.py —— 纯文本与括号处理（3.6.64 从 djc_parse.py 拆出）。

只依赖 `re`，**不读任何模块级可变状态**（尤其不碰 `NORM_TO_CANON`），
所以可以放心被解析层、命名层、路由层共用：
  * 空白/符号归一（`clean_spaces` / `normalize_symbols`）；
  * Windows 文件名清洗（`sanitize_windows_name`）；
  * 括号剥离与纠错（`strip_wrappers` / `repair_name`）——成品名"永不嵌套/不重复"的最后一关。

`djc_parse` 把这些名字**再导出**，历史调用点（`djc_parse.repair_name` 等）无需改动。
"""
import re
import unicodedata

def clean_spaces(s):
    """规范化自由文本：把 "_" 当作空格，合并连续空白并去除首尾空白。
    注意：原作词条等规范名称走 _norm/词条库匹配，不应调用本函数。"""
    s = str(s or "").replace("_", " ")
    return re.sub(r"\s+", " ", s).strip()


_SYMBOL_PAIRS = {"（": "(", "）": ")",
                 "〔": "[", "〕": "]",
                 "〖": "[", "〗": "]",
                 "［": "[", "］": "]",
                 "｛": "{", "｝": "}"}


_SYMBOL_SEPS = {"，": ",", "、": ",", "﹐": ",", "﹑": ","}


def normalize_symbols(s):
    """符号归一：全角括号→半角，全角逗号/顿号→半角逗号。只动符号，不动大小写与空格。
    供解析识别（primary_bracket_info）与命名规范化（normalize_filename）共用。"""
    if not s:
        return ""
    return "".join(_SYMBOL_PAIRS.get(c, _SYMBOL_SEPS.get(c, c)) for c in str(s))


WIN_BAD_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


WIN_RESERVED_RE = re.compile(r'(?i)^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)')


def sanitize_windows_name(s):
    """Windows 文件/目录名安全清洗：非法字符 \\ / : * ? " < > | 及控制字符 → 空格，
    合并空白、去首尾空白与结尾点；保留设备名（CON/NUL/COM1…）前缀 _ 避免落盘失败。
    用户输入（增补信息/导入文件名）落盘前必须经过本函数。
    注意：不处理 "_"（原作规范名如 Re_Dive 中的下划线需保留）。"""
    s = WIN_BAD_RE.sub(" ", str(s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    s = s.rstrip(". ")
    if WIN_RESERVED_RE.match(s):
        s = "_" + s
    return s


def _dedup(seq):
    out = []
    for x in seq:
        if x not in out:
            out.append(x)
    return out


_BRACKET_PAIRS = {"[": "]", "(": ")", "【": "】", "（": "）", "〔": "〕", "〖": "〗"}


def _balanced(s):
    """括号是否完全配对（防止把 "[a) 作品" 这类不配对的壳剥掉）。"""
    stack = []
    for ch in s:
        if ch in _BRACKET_PAIRS:
            stack.append(_BRACKET_PAIRS[ch])
        elif ch in _BRACKET_PAIRS.values():
            if not stack or stack.pop() != ch:
                return False
    return not stack


def strip_wrappers(s):
    """剥掉字段值外面多余的括号壳（可重复包裹）：
    "[蜂巢 (Apoidea)]" → "蜂巢 (Apoidea)"；"((C102))" → "C102"；"[汉化组]" → "汉化组"。
    只剥**整段被同种括号包住且内部配对**的情况，内部括号（如社团名里的个人名）原样保留。"""
    s = (s or "").strip()
    for _ in range(8):                      # 最多剥 8 层，防御性上限
        if len(s) < 2:
            break
        for op, cl in _BRACKET_PAIRS.items():
            if s.startswith(op) and s.endswith(cl) and len(s) > 2:
                inner = s[1:-1].strip()
                if inner and _balanced(inner):
                    s = inner
                    break
        else:
            break
    return s.strip()


def repair_name(name):
    """成品文件名的括号纠错（生成规范名之后跑一遍，保证输出**永不嵌套/不重复**）：
      1. 去掉空括号对：[ ] ( ) 【 】
      2. 折叠紧邻的重复括号：[[x]] → [x]，((x)) → (x)
      3. 去掉括号内重复的同款 () 词条：[a (b) (b)] → [a (b)]
      4. 去掉整名中重复出现的 [词条] / (词条)（保留首次出现）

    3.7.43 结构：四个去重助手提为模块级私有函数（原为嵌套闭包，函数 70→30 行）。
    """
    s = re.sub(r"\s+", " ", name or "").strip()
    for _ in range(4):
        before = s
        s = re.sub(r"([\[\(【（〔〖])\s*([\]\)】）〕〗])", "", s)   # 空括号对
        s = (s.replace("[[", "[").replace("]]", "]")
              .replace("((", "(").replace("))", ")")
              .replace("【【", "【").replace("】】", "】")
              .replace("（（", "（").replace("））", "）"))
        s = re.sub(r"\s+", " ", s).strip()
        if s == before:
            break

    s = re.sub(r"\[([^\[\]]*)\]", _dedup_inner, s)

    # 4) 全局去重：先收拾"不在任何 [] 【】 里"的独立 ()（其内容此前已出现在别处就丢掉），
    #    再收拾重复的 [词条] / 【词条】。括号内部的 () 不在此处删（避免误伤
    #    "[社团A (画师)] [社团B (画师)]" 这种两个社团各带同一画师的情况）。
    seen = set()
    s = _dedup_standalone_parens(s, seen)
    s = re.sub(r"\[[^\[\]]*\]|【[^【】]*】", lambda m: _dedup_tokens(m, seen), s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([\]\)】）〕〗])", r"\1", s)
    s = re.sub(r"([\[\(【（〔〖])\s+", r"\1", s)
    return s


def _dedup_inner(m):
    """[社团 (个人) (个人)] → [社团 (个人)]"""
    inner = m.group(1)
    seen, out = set(), []
    for part in re.findall(r"\([^()]*\)|[^\s]+", inner):
        k = part.strip()
        if k.startswith("("):
            if k in seen:
                continue
            seen.add(k)
        out.append(part)
    return "[" + " ".join(out) + "]"


def _dedup_standalone_parens(text, seen):
    """删掉整名里重复出现的独立 ()（保留首次）；括号内出现的只记进 seen 供比对。"""
    spans = [(m.start(), m.end()) for m in re.finditer(r"\[[^\[\]]*\]|【[^【】]*】", text)]
    out, last = [], 0
    for m in re.finditer(r"\([^()]*\)", text):
        st, en = m.span()
        key = re.sub(r"\s+", "", m.group(0))
        if any(a <= st and en <= b for a, b in spans):
            seen.add(key)                       # 括号内出现的：记录下来供后面比对
            continue
        if key in seen:
            out.append(text[last:st])
            last = en                           # 丢弃这个重复的独立 ()
        else:
            seen.add(key)
    out.append(text[last:])
    return "".join(out)


def _dedup_tokens(m, seen):
    """删掉重复出现的 [词条] / 【词条】（保留首次）；首次出现时记进 seen。"""
    k = re.sub(r"\s+", "", m.group(0))
    if k in seen:
        return ""
    seen.add(k)
    return m.group(0)


def _clean_title(s):
    s = s.replace("_", " ").replace("丨", " ").replace("｜", " ").replace("　", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip(" -_~|丨｜.·、")


def _norm(s):
    """轻量归一化：NFKC（全半角/兼容字符统一）→ 去首尾空格/末尾下划线，
    全角斜线/星号 → 半角。

    3.6.38 #38：补 NFKC——此前只转斜线星号，全角 ！ ！，。等与半角不等，
    导致「ぼっち・ざ・ろっく！」词条匹配不上文件名里的「ぼっち・ざ・ろっく!」
    （用户报障：全半角不一致让宽松归一形同虚设）。NFKC 把全角标点/字母/数字
    一并折成半角，是全半角宽松的地基。"""
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = s.strip().rstrip("_").strip()
    s = s.replace("／", "/").replace("☆", "*").replace("★", "*").replace("＊", "*")
    return s
