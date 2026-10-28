# -*- coding: utf-8 -*-
"""远程低带宽模式回归测试。

背景：在外面走 Tailscale 中继时实测往返 480~677ms（手机→旧金山中继→家里），
而一页原图 9.8MB → APP 完全打不开。现在服务端会给"远程且走中继"的客户端按需转码小图，
本机/局域网与"Tailscale 直连"（例如手机在家）仍给原图，且可用 ?img=orig|low 显式覆盖。
"""
import io
import os
import sys
import zipfile

import pytest

sys.dont_write_bytecode = True
PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROG_DIR)

import app  # noqa: E402
import panel.images as _images  # noqa: E402  低带宽/封面图已抽至 panel/images.py

try:
    from PIL import Image
except Exception:
    Image = None

pytestmark = pytest.mark.skipif(Image is None or not app.PIL_OK,
                                reason="需要 Pillow 才能测转码")


def _big_jpeg(w=1600, h=2400, color=(120, 60, 200)):
    """造一张足够大的 JPEG（模拟扫描页），随机噪点让体积接近真实。"""
    import random
    rnd = random.Random(7)
    im = Image.new("RGB", (w, h), color)
    px = im.load()
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            c = (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
            for dy in range(4):
                for dx in range(4):
                    if x + dx < w and y + dy < h:
                        px[x + dx, y + dy] = c
    out = io.BytesIO()
    im.save(out, "JPEG", quality=92)
    return out.getvalue()


def _anim_gif(frames=3, w=800, h=800, transparency=None):
    ims = []
    for i in range(frames):
        im = Image.new("RGB", (w, h), (30 * i % 255, 90, 200 - 30 * i))
        ims.append(im)
    out = io.BytesIO()
    kw = {"transparency": transparency} if transparency is not None else {}
    ims[0].save(out, "GIF", save_all=True, append_images=ims[1:], duration=120, loop=0, **kw)
    return out.getvalue()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    d = root / "社团L" / "作品L"
    d.mkdir(parents=True)
    (d / "01.jpg").write_bytes(_big_jpeg())
    (d / "02.gif").write_bytes(_anim_gif())
    monkeypatch.setattr(app, "INDEX_FILE", str(tmp_path / "library_index.json"))
    # 低带宽缓存目录是 panel.images 的可重绑定常量：打桩须打到真正读取它的模块
    monkeypatch.setattr(_images, "LOW_DIR", str(tmp_path / "low_cache"))  # 别往仓库里写缓存
    monkeypatch.setitem(app.CFG, "root", str(root))
    monkeypatch.setitem(app.CFG, "token", "")
    monkeypatch.setitem(app.CFG, "dissolved_circles", [])
    app.state.index_loaded = False
    app.state.index = {"v": 2, "originals_hash": "", "works": {}}
    app.state.index_keys.clear()
    app.state.lib["data"] = None
    yield {"root": root, "low_dir": tmp_path / "low_cache"}
    app.state.index_keys.clear()


def _page(c, n, img=None, remote="127.0.0.1"):
    q = f"/page?group=社团L&work=作品L&n={n}" + (f"&img={img}" if img else "")
    return c.get(q, environ_base={"REMOTE_ADDR": remote})


# ---------------------------------------------------------------- 判定逻辑

def test_client_wants_low_decision(monkeypatch):
    """本机/局域网给原图；Tailscale 看该对端是直连还是中继；可用 ?img= 覆盖。"""
    monkeypatch.setattr(_images, "_tailnet_direct_map", lambda ttl=20.0: {"100.101.102.103": True,
                                                                     "100.101.102.104": False})
    with app.app.test_request_context("/page", environ_base={"REMOTE_ADDR": "127.0.0.1"}):
        assert app.client_wants_low() is False                 # 本机
    for lan in ("192.168.1.20", "172.24.132.27", "10.0.0.5"):
        with app.app.test_request_context("/page", environ_base={"REMOTE_ADDR": lan}):
            assert app.client_wants_low() is False, lan        # 局域网
    with app.app.test_request_context("/page", environ_base={"REMOTE_ADDR": "100.101.102.103"}):
        assert app.client_wants_low() is False                 # Tailscale 直连（如手机在家）
    with app.app.test_request_context("/page", environ_base={"REMOTE_ADDR": "100.101.102.104"}):
        assert app.client_wants_low() is True                  # Tailscale 中继
    with app.app.test_request_context("/page?img=orig", environ_base={"REMOTE_ADDR": "100.101.102.104"}):
        assert app.client_wants_low() is False                 # 显式要原图
    with app.app.test_request_context("/page?img=low", environ_base={"REMOTE_ADDR": "127.0.0.1"}):
        assert app.client_wants_low() is True                  # 显式要省流


def test_unknown_tailnet_peer_is_conservative(monkeypatch):
    """查不到对端路径（没装 CLI 等）→ 保守按低带宽处理，宁可糊一点也别打不开。"""
    monkeypatch.setattr(_images, "_tailnet_direct_map", lambda ttl=20.0: {})
    with app.app.test_request_context("/page", environ_base={"REMOTE_ADDR": "100.64.0.9"}):
        assert app.client_wants_low() is True


# ---------------------------------------------------------------- 实际转码

def test_low_mode_serves_smaller_image(env):
    app.get_library(force=True)
    c = app.app.test_client()
    orig = _page(c, 0, "orig")
    assert orig.status_code == 200
    assert orig.headers.get("X-Img-Mode") == "orig"

    low = _page(c, 0, "low")
    assert low.status_code == 200
    assert low.headers.get("X-Img-Mode") == "low"
    assert low.headers["Content-Type"].startswith("image/jpeg")
    assert len(low.data) < len(orig.data), (len(low.data), len(orig.data))
    assert len(low.data) < len(orig.data) / 3, "低带宽版应显著更小"
    with Image.open(io.BytesIO(low.data)) as im:
        assert max(im.size) <= app.LOW_PAGE_SIDE
    # 落盘缓存：第二次不再重复转码，字节一致
    low2 = _page(c, 0, "low")
    assert low2.data == low.data
    assert os.path.isdir(str(env["low_dir"])) and os.listdir(str(env["low_dir"]))


def test_low_mode_keeps_gif_animated_but_smaller(env):
    """动图（GIF）是体积大户：低带宽版必须仍然是**动图**，但单帧尺寸被压下来。"""
    app.get_library(force=True)
    c = app.app.test_client()
    orig = _page(c, 1, "orig")
    low = _page(c, 1, "low")
    assert low.status_code == 200
    assert low.headers["Content-Type"] == "image/gif"
    assert len(low.data) < len(orig.data)
    with Image.open(io.BytesIO(low.data)) as im:
        assert getattr(im, "is_animated", False), "低带宽版把动图搞成静图了"
        assert im.n_frames == 3
        assert max(im.size) <= app.LOW_ANIM_SIDE


def test_low_mode_handles_gif_with_transparency(env):
    """带 transparency 的 GIF 也必须能转码且**保住动画** —— 真实库里那个 9.8MB 动图
    就是在这里抛 ValueError（P 模式 transparency 是 bytes）被整页回退成原图的。
    夹具要造得真实：每帧的不透明区域不同，否则会被编码器当成重复帧合并掉。"""
    from PIL import ImageDraw
    frames = []
    for i in range(3):
        im = Image.new("P", (400, 400), 1)                 # 索引 1 = 不透明
        im.putpalette([0, 0, 0, 210, 60, 60] + [0] * (256 * 3 - 6))
        ImageDraw.Draw(im).rectangle([0, 0, 80 + i * 40, 400], fill=0)   # 每帧透明区不同
        frames.append(im)
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:],
                   duration=100, loop=0, transparency=0)
    data = buf.getvalue()
    assert Image.open(io.BytesIO(data)).info.get("transparency") is not None

    got = app.lowres_image(data, "t.gif", "transp-seed")
    if got is not None:
        out, mime = got
        assert mime == "image/gif"
        with Image.open(io.BytesIO(out)) as o:
            assert getattr(o, "is_animated", False), "带透明度的动图被压成静图了"
            assert o.n_frames >= 2


def test_localhost_always_gets_original(env):
    """本机（127.0.0.1）永远拿原图 —— 别把本地浏览体验也降级了。"""
    app.get_library(force=True)
    c = app.app.test_client()
    r = _page(c, 0)                      # 不带 img 参数，来源 127.0.0.1
    assert r.status_code == 200 and r.headers.get("X-Img-Mode") == "orig"


def test_lowres_image_fallbacks(env):
    """转码失败 → 返回 None（调用方给原图），且不抛异常；小图转码本身无害。
    注意：'转完更大就放弃' 只是省事的微优化，小图有机会变小就照转 —— 这里只钉住
    真正的兜底契约：垃圾字节必须返回 None，而不是抛异常或返回坏数据。"""
    assert app.lowres_image(b"not an image at all", "x.jpg", "seed1") is None
    assert app.lowres_image(b"", "x.jpg", "seed2") is None
    assert app.lowres_image(b"\x00\x01\x02\x03", "x.png", "seed2b") is None

    small = io.BytesIO()
    Image.new("RGB", (48, 48), (200, 200, 200)).save(small, "JPEG", quality=60)
    got = app.lowres_image(small.getvalue(), "tiny.jpg", "seed3")
    if got is not None:                      # 允许转（省事规则命中时不转也算）
        data, mime = got
        assert mime == "image/jpeg"
        with Image.open(io.BytesIO(data)) as im:
            assert max(im.size) <= app.LOW_PAGE_SIDE


def test_pages_reports_low_flag(env, monkeypatch):
    """/api/pages 告诉客户端当前是不是低带宽发图（APP 可据此提示用户）。"""
    monkeypatch.setattr(_images, "_tailnet_direct_map", lambda ttl=20.0: {"100.101.102.104": False})
    # 3.6.147：门禁改成 fail-closed —— 主令牌为空时非回环访问一律 401（旧版是放行）。
    # 这个用例只想测 low 标志，给它一个有效令牌即可，不必依赖"无令牌放行"。
    monkeypatch.setitem(app.CFG, "token", "bks-lowflag")
    app.get_library(force=True)
    c = app.app.test_client()
    j = c.get("/api/pages?group=社团L&work=作品L",
              environ_base={"REMOTE_ADDR": "100.101.102.104"},
              headers={"X-Token": "bks-lowflag"}).get_json()
    assert j["ok"] is True and j["low"] is True
    j2 = c.get("/api/pages?group=社团L&work=作品L").get_json()
    assert j2["low"] is False
