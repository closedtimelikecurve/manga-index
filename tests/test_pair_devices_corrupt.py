# -*- coding: utf-8 -*-
"""设备表损坏时的行为（3.6.168）。

## 为什么有这个文件

2026-10-29 的真实故障：手机令牌一直在，Tailscale 与面板进程都正常，**所有远程请求恒定 401**。
根因是 `_state/pair_devices.json` 末尾多出一个 `}`，`json.load` 抛 `Extra data`，
而旧的 `_load` 是 `except (OSError, ValueError): return {}` —— 静默变成空表：
服务端一台设备都不认，日志里却一个字都没有，只能靠人翻文件才看得出来。

现在的要求（本文件即守门人）：

* 尾部多字符这类**能救的**损坏 → 抢救出设备、**写回规范 JSON 自愈**、留 WARNING；
* 救不回来的（截断在对象中间 / 根本不是 JSON）→ 空表 + ERROR，**绝不抛异常**打断请求；
* 正常文件不受影响：不该被重写，也不该报错。
"""
import json
import os
import sys

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import pytest  # noqa: E402

from services import pair_devices as pd  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_cache():
    """`_hash_map` 按 mtime 缓存，模块级；不清会串到下一个用例。"""
    pd._cache.update({"path": None, "mtime": None, "map": {}})
    yield
    pd._cache.update({"path": None, "mtime": None, "map": {}})


def _write(tmp_path, text):
    path = os.path.join(str(tmp_path), "pair_devices.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def test_trailing_garbage_still_verifies_and_self_heals(tmp_path, caplog):
    """尾部多一个 `}`（真实故障形状）：令牌照样验得过，文件被修好。"""
    d = str(tmp_path)
    issued = pd.issue(d, name="V2405A", machine="machine-a")
    path = os.path.join(d, "pair_devices.json")
    with open(path, encoding="utf-8") as f:
        good = f.read()
    _write(tmp_path, good + "\n}")
    pd._cache.update({"path": None, "mtime": None, "map": {}})   # 模拟新进程首次读取

    with caplog.at_level("WARNING"):
        assert pd.verify(d, issued["token"]) == issued["deviceId"]

    assert any("抢救" in r.message for r in caplog.records)
    with open(path, encoding="utf-8") as f:
        healed = json.load(f)                                    # 自愈后必须是合法 JSON
    assert list(healed) == [issued["deviceId"]]


def test_truncated_file_returns_empty_without_raising(tmp_path, caplog):
    """截断在对象中间：救不回来 → 空表 + ERROR，但请求不能炸。"""
    d = str(tmp_path)
    _write(tmp_path, '{"abc": {"h": "deadbeef"')
    pd._cache.update({"path": None, "mtime": None, "map": {}})

    with caplog.at_level("ERROR"):
        assert pd.verify(d, "dev-" + "0" * 32) is None
        assert pd.list_devices(d) == []

    assert any("无法抢救" in r.message for r in caplog.records)


def test_healthy_file_is_not_rewritten(tmp_path):
    """正常文件不该被"自愈"折腾：mtime 与内容都保持原样。"""
    d = str(tmp_path)
    issued = pd.issue(d, name="Pixel", machine="machine-b")
    path = os.path.join(d, "pair_devices.json")
    before = os.stat(path).st_mtime_ns
    text_before = open(path, encoding="utf-8").read()

    pd._cache.update({"path": None, "mtime": None, "map": {}})
    assert pd.verify(d, issued["token"]) == issued["deviceId"]
    assert os.stat(path).st_mtime_ns == before
    assert open(path, encoding="utf-8").read() == text_before


def test_non_dict_top_level_is_treated_as_empty(tmp_path):
    """顶层是数组 / 字符串：结构不对，按空表处理，不抛。"""
    d = str(tmp_path)
    _write(tmp_path, "[]")
    pd._cache.update({"path": None, "mtime": None, "map": {}})
    assert pd.list_devices(d) == []


def test_missing_file_is_normal_not_an_error(tmp_path, caplog):
    """还没配过设备：文件不存在是正常状态，不该报错（否则新装就一堆 ERROR）。"""
    d = str(tmp_path)
    with caplog.at_level("ERROR"):
        assert pd.list_devices(d) == []
    assert not [r for r in caplog.records if r.levelno >= 40]
