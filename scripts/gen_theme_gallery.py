# -*- coding: utf-8 -*-
"""生成内置主题图库资产（3.6.122）。

产物（提交进仓库，运行时不依赖本脚本，也不依赖 PIL）：
* `b01_default_bg.jpg`   ← `static/img/bg.jpg` 重编码（默认背景图入图库）
* `b02_default_hero.jpg` ← `static/img/hero.jpg` 重编码（默认横幅入图库）
* `b06_draw_neon.jpg`    霓虹网格（手绘）
* `b07_draw_jade.jpg`    翡翠涟漪（手绘）
* `b08_draw_dusk.jpg`    暮色条纹（手绘）

`b03~b05_pexels_*.jpg` 是下载来的免费商用图，不在本脚本里（不在构建时联网），
来源与许可写在同目录 `CREDITS.md`。

用法（纪律 §4.5：argparse 与执行流程都在 main() 内，`--help` 无副作用）：
    python scripts/gen_theme_gallery.py --defaults --draw
    python scripts/gen_theme_gallery.py --draw --seed 7
"""
import argparse
import os
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "static", "img", "gallery")
W, H = 1600, 1000


def _lerp(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def _vgrad(size, top, bottom):
    """竖向渐变底（逐行插值，不引入 numpy）。"""
    w, h = size
    img = Image.new("RGB", (1, h))
    img.putdata([_lerp(top, bottom, y / max(1, h - 1)) for y in range(h)])
    return img.resize((w, h))


def _glow(layer, radius):
    return layer.filter(ImageFilter.GaussianBlur(radius))


def _save(img, name, quality=82):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    img.convert("RGB").save(path, "JPEG", quality=quality, optimize=True, progressive=True)
    return path


def _resized_jpeg(src, name, width=1920, quality=72):
    """把默认图重编码成图库条目（只缩不放、不裁内容；q72 是体积与细节的折中）。"""
    im = Image.open(src).convert("RGB")
    if im.width > width:                       # 只缩不放：放大只会变糊并撑大体积
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    return _save(im, name, quality)


def _radial_glow(size, center, radius, color, steps=48):
    """在黑底上叠同心椭圆做柔光（PIL 没有径向渐变，这是最省事且可复现的近似）。"""
    w, h = size
    img = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = center
    for i in range(steps, 0, -1):
        t = i / steps
        r = radius * t
        c = tuple(int(v * (1.0 - t) ** 1.6) for v in color)
        d.ellipse([cx - r, cy - r * 0.6, cx + r, cy + r * 0.6], fill=c)
    return img.filter(ImageFilter.GaussianBlur(radius * 0.06))


def draw_solid(color, name):
    """纯色图（3.6.128：图库要保留「纯黑背景」这一档，等价于"不要背景图"）。"""
    return _save(Image.new("RGB", (W, H), color), name, quality=85)


def draw_neon(rng):
    """霓虹网格：消失点透视 + 地平线辉光 + 稀疏星点。"""
    img = _vgrad((W, H), (10, 6, 22), (30, 12, 48))
    lines = Image.new("RGB", (W, H), (0, 0, 0))
    g = ImageDraw.Draw(lines)
    vx, vy = W // 2, int(H * 0.52)
    for i in range(-12, 13):                                  # 向消失点收敛的纵线
        x = int(vx + i * (W / 9.0))
        g.line([(vx, vy), (x, H)], fill=(255, 61, 242), width=2)
    y, step = vy + 8, 5.0
    while y < H:                                              # 越近越疏的横线
        g.line([(0, y), (W, y)], fill=(77, 201, 255), width=2)
        step *= 1.24
        y += step
    horizon = _radial_glow((W, H), (vx, vy), 620, (150, 52, 190))   # 地平线柔光
    img = Image.blend(img, horizon, 0.85)
    mask = Image.new("L", (1, H))                             # 远处线条渐隐（雾感）
    mask.putdata([0 if y < vy else int(255 * ((y - vy) / max(1.0, H - vy)) ** 0.7)
                  for y in range(H)])
    mask = mask.resize((W, H))
    img = Image.composite(Image.blend(img, lines, 0.85), img, mask)
    img = Image.blend(img, _glow(lines, 12), 0.45)             # 外发光
    img = Image.blend(img, _glow(lines, 2), 0.75)              # 芯线
    d = ImageDraw.Draw(img)
    for _ in range(240):                                      # 星点
        sx, sy = rng.randrange(W), rng.randrange(int(H * 0.5))
        r = rng.choice((1, 1, 1, 2))
        d.ellipse([sx, sy, sx + r, sy + r], fill=(232, 224, 255))
    return img


def draw_jade(rng):
    """翡翠涟漪：同心波纹 + 中心柔光（波纹半径带轻微抖动，避免机械感）。"""
    img = _vgrad((W, H), (6, 26, 22), (2, 8, 12))
    layer = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = int(W * 0.5), int(H * 0.62)
    for i in range(40):
        r = 40 + i * 33 + rng.uniform(-4, 4)
        color = _lerp((72, 255, 194), (22, 86, 120), min(1.0, i / 28.0))
        box = [cx - r, cy - r * 0.5, cx + r, cy + r * 0.5]
        d.ellipse(box, outline=color, width=2 if i < 26 else 1)
    img = Image.blend(img, _glow(layer, 18), 0.55)
    img = Image.blend(img, _glow(layer, 2), 0.7)
    img = Image.blend(img, _radial_glow((W, H), (cx, cy), 220, (46, 190, 150)), 0.55)
    return img


def draw_dusk(rng):
    """暮色条纹：斜向色带（暖橙→紫→青），加色叠加后柔化 + 轻暗角。"""
    img = _vgrad((W, H), (26, 12, 42), (10, 7, 22))
    layer = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(layer)
    bands = [(255, 150, 100), (188, 118, 255), (255, 86, 138), (92, 208, 255)]
    x, i = -H, 0
    while x < W + H:
        color = bands[i % len(bands)]
        width = int(rng.uniform(110, 240))
        d.polygon([(x, H), (x + width, H), (x + width + H, 0), (x + H, 0)], fill=color)
        x += width + int(rng.uniform(14, 52))
        i += 1
    # 加色叠加（blend 会逐层乘 0.62，十几层后必然衰减成纯黑——3.6.122 第一版就踩了这个）
    img = ImageChops.add(img, Image.eval(layer, lambda v: v * 9 // 20))
    img = img.filter(ImageFilter.GaussianBlur(6.0))
    img = Image.blend(img, _vgrad((W, H), (8, 5, 16), (8, 5, 16)), 0.28)   # 压饱和，贴夜色
    img = Image.blend(img, _radial_glow((W, H), (int(W * 0.62), int(H * 0.42)), 900,
                                       (120, 80, 160)), 0.25)
    mask = Image.new("L", (W, H), 0)                           # 轻暗角（不能压成纯黑）
    ImageDraw.Draw(mask).ellipse([-W * 0.45, -H * 0.55, W * 1.45, H * 1.55], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(240))
    return Image.composite(img, Image.new("RGB", (W, H), (14, 9, 24)), mask)


def main():
    ap = argparse.ArgumentParser(description="生成内置主题图库资产")
    ap.add_argument("--defaults", action="store_true", help="重编码 bg.jpg / hero.jpg 为 b01/b02")
    ap.add_argument("--draw", action="store_true", help="生成 b06~b08 三张手绘抽象图")
    ap.add_argument("--seed", type=int, default=20261026, help="手绘随机种子（固定可复现）")
    args = ap.parse_args()
    if not args.defaults and not args.draw:
        ap.print_help()
        return 1
    if args.defaults:
        print(_resized_jpeg(os.path.join(ROOT, "static", "img", "bg.jpg"), "b01_default_bg.jpg"))
        print(_resized_jpeg(os.path.join(ROOT, "static", "img", "hero.jpg"), "b02_default_hero.jpg"))
        # 3.6.127：手机端内置默认背景（`settings_bg.jpg` 的源图，此前漏在图库外）
        print(_resized_jpeg(os.path.join(ROOT, "static", "img", "side.jpg"), "b09_default_mobile.jpg"))
    if args.draw:
        rng = random.Random(args.seed)
        print(draw_solid((0, 0, 0), "b00_black.jpg"))
        print(_save(draw_neon(rng), "b06_draw_neon.jpg"))
        print(_save(draw_jade(rng), "b07_draw_jade.jpg"))
        print(_save(draw_dusk(rng), "b08_draw_dusk.jpg"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
