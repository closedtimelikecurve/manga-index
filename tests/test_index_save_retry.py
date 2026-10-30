# -*- coding: utf-8 -*-
"""索引缓存的落盘重试（3.6.163）。

## 为什么要这一步

本项目常态是**双实例共存**：8765（本机回环）+ 8766（局域网/隧道）。
两边都会在重扫后写 `library_index.json`，而写盘用的是
「临时文件 + os.replace」——Windows 上 `os.replace` 目标**被另一个进程打开**时
会直接 `PermissionError: [WinError 5] 拒绝访问`（不是 POSIX 那种"覆盖即成功"）。

实测代价：撞上就整次保存作废，下次重启得重新扫全库（30 秒~几分钟），
日志里只有一行 `写入索引缓存失败`，用户完全无感。

修法：撞上时短暂重试 4 次。对方通常只是读几百毫秒，重试基本都能过；
四次都失败才按原样记异常（真出问题仍要能看见）。
"""
import json
import os
import sys

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
from services import index_cache as ic  # noqa: E402


def _flaky_replace(monkeypatch, fail_times):
    """让前 fail_times 次 os.replace 抛 PermissionError，之后放行。返回调用计数器。"""
    calls = {"n": 0}
    real = os.replace

    def fake(src, dst):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise PermissionError(5, "拒绝访问")
        return real(src, dst)

    monkeypatch.setattr(ic.os, "replace", fake)
    return calls


def _prepare(tmp_path, monkeypatch):
    """把索引文件指到临时目录——绝不能碰真实的 _state/library_index.json。"""
    target = str(tmp_path / "library_index.json")
    monkeypatch.setattr(app, "INDEX_FILE", target)
    monkeypatch.setattr(app.state, "index", {"works": {}, "originals_hash": ""})
    monkeypatch.setattr(app.state, "index_keys", set())
    return target


def test_retries_when_target_is_locked(tmp_path, monkeypatch):
    """另一个实例短暂占着目标文件时，重试应该把它救回来。"""
    target = _prepare(tmp_path, monkeypatch)
    calls = _flaky_replace(monkeypatch, fail_times=3)

    ic._index_save()

    assert calls["n"] == 4, "应该重试到第 4 次才成功"
    assert os.path.exists(target), "最终必须真的写下去"


def test_gives_up_after_four_attempts(tmp_path, monkeypatch):
    """四次都占用就不该无限重试——记异常、放过这次保存（下次重扫还能补）。"""
    target = _prepare(tmp_path, monkeypatch)
    calls = _flaky_replace(monkeypatch, fail_times=99)

    ic._index_save()          # 内部自己 log.exception，不往上抛

    assert calls["n"] == 4
    assert not os.path.exists(target), "没成功就不该留下半个文件"


def test_no_retry_when_everything_is_fine(tmp_path, monkeypatch):
    """正常情况只调一次 os.replace（重试是异常路径，不该拖慢常态）。"""
    target = _prepare(tmp_path, monkeypatch)
    calls = _flaky_replace(monkeypatch, fail_times=0)

    ic._index_save()

    assert calls["n"] == 1
    assert os.path.exists(target)


def test_empty_index_keys_does_not_wipe_index(tmp_path, monkeypatch):
    """启动时直接复用磁盘索引、没走扫描 → `index_keys` 为空，不能把整张索引写空。

    真实故障：重启后面板突然 0 部作品。`_index_save` 用 `index_keys` 过滤"本轮仍有效
    的作品"，但那个集合只有**真正扫过**才会填；复用磁盘索引时它是空的，
    过滤结果就是"一个都不留"。
    """
    target = _prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(app.state, "index",
                        {"works": {"k1": {"name": "a"}, "k2": {"name": "b"}},
                         "originals_hash": ""})
    monkeypatch.setattr(app.state, "index_keys", set())      # 没扫过
    _flaky_replace(monkeypatch, fail_times=0)

    ic._index_save()

    saved = json.load(open(target, encoding="utf-8"))
    assert len(saved["works"]) == 2, "没扫过就不许拿空集合当'全部删除'"


def test_scan_keys_still_prune_deleted_works(tmp_path, monkeypatch):
    """真正扫过时照旧清理已删除的作品（别把上面那条修成"永不清理"）。"""
    target = _prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(app.state, "index",
                        {"works": {"k1": {"name": "a"}, "gone": {"name": "b"}},
                         "originals_hash": ""})
    monkeypatch.setattr(app.state, "index_keys", {"k1"})     # 本轮只扫到 k1
    _flaky_replace(monkeypatch, fail_times=0)

    ic._index_save()

    saved = json.load(open(target, encoding="utf-8"))
    assert list(saved["works"]) == ["k1"]


def test_temp_file_cleaned_when_giving_up(tmp_path, monkeypatch):
    """放弃时要清掉临时文件：否则 _state 里会堆一堆 library_index_xxxx.json。"""
    _prepare(tmp_path, monkeypatch)
    _flaky_replace(monkeypatch, fail_times=99)

    ic._index_save()

    leftovers = [f for f in os.listdir(str(tmp_path)) if f.startswith("library_index_")]
    assert leftovers == [], "临时文件没清理：%s" % leftovers
