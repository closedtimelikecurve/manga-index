# -*- coding: utf-8 -*-
"""文件名实体解码（3.6.139）回归：Windows 文件名禁 `|`，旧库把它编码成字面
`&#124;` 存盘（真实库现存 6 部）。展示字段必须解码成 `|`，标识符必须保持原始名——
解码一旦扩散到查库键，这几部作品就再也查不到了。"""
import os
import sys
import zipfile
from urllib.parse import quote

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
from _originals_helpers import lib_env  # noqa: E402,F401
from common import display_name  # noqa: E402

JPG = b"\xff\xd8\xff\xe0 fake-jpg"

RAW = "[社团A] 标题A &#124; 标题B [DL版]"      # 盘上真实名（含字面实体序列）
DECODED = "[社团A] 标题A | 标题B [DL版]"


def test_display_name_helper():
    """助手本身：只动编码序列，别的一字不碰（& 字面量、普通 | 都不受影响）。"""
    assert display_name(RAW) == DECODED
    assert display_name("A & B | C") == "A & B | C"       # 字面 & 与普通 | 原样
    assert display_name(RAW) != RAW


def test_api_pages_name_decoded_identifier_raw(lib_env):
    """`/api/pages`：展示字段 name 解码；work 标识符 + 原始名查库必须仍然命中。"""
    circ = lib_env / "社团A"
    circ.mkdir()
    with zipfile.ZipFile(str(circ / (RAW + ".zip")), "w") as z:
        z.writestr("cover.jpg", JPG)
        z.writestr("p1.png", JPG)
    app.get_library(force=True)
    client = app.app.test_client()
    j = client.get("/api/pages?group=" + quote("社团A") + "&work=" + quote(RAW)).get_json()
    assert j["ok"], j
    assert j["work"] == RAW               # 标识符原样回传（客户端回查依赖它）
    assert j["name"] == DECODED           # 展示名已解码
