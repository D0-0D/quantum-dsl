#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""自动布线调试画廊 (临时调试用, 不进契约 / 文档): 一批场景直接喂 ``route.plan_cpw``, 每个场景一张 PNG ——
画出 region 矩形 (蓝框; 拼接矩形之间的缝红底), 端口位姿 (箭头), axis 框架 (右上角罗盘), 最短骨架 (细灰), 定长后的 CPW (中心线红 + 两边灰),
左上角写参数 / 腿数 / 转弯数 / 耗时; 规划失败的场景把报错文字画进图。全部场景再拼成 gallery.png。
另外给 build 出的 demo GDS 图叠上每条 cpw_route 的 region 框与 axis 标注 (<stem>.gds.debug.png)。

    PYTHONPATH=src python tools/route_gallery.py                     # → build/demo/route_gallery/*.png + gallery.png
    PYTHONPATH=src python tools/route_gallery.py --overlay examples/cpw_route_demo.layout.yaml build/demo/cpw_route/cpw_route_demo.gds
"""
from __future__ import annotations

import math
import sys
import textwrap
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from quantum_dsl import QuantumDslError
from quantum_dsl.route import path_length, plan_cpw

R, W = 40.0, 22.0
A = dict(start=(210, 0, 0.0), end=(900, -690, -math.pi / 2), R=R, width=W, lead=60)      # demo 的一对桨
REGION = [180, -720, 1000, 100]
REGION_B = [[180, -720, 700, 100], [180, -720, 1000, -300]]

# 场景: 名字 → plan_cpw 的关键字参数 (缺 length 的只画最短骨架)。故意失败的场景名带 "!"。
SCENES = {
    "L_default": dict(A, length=3000, region=REGION),
    "L_free": dict(A, length=3000, region=REGION, axis="free"),
    "L_axis45": dict(A, length=3000, region=REGION, axis=45),
    "L_legs8": dict(A, length=3000, region=REGION, n_legs=8),
    "notch_union": dict(A, length=3000, region=REGION_B),
    "notch_shortest": dict(A, region=REGION_B),
    "gap_error!": dict(A, region=[[180, -720, 700, 100], [750, -720, 1000, 100]]),
    "Z_facing_offset": dict(start=(0, 0, 0.0), end=(900, 250, 0.0), R=R, width=W, lead=40, length=2600, region=[-30, -200, 930, 450]),
    "straight_asym": dict(start=(0, 0, 0.0), end=(900, 0, 0.0), R=R, width=W, lead=40, length=2400, region=[-30, -120, 930, 500]),
    "U_turn": dict(start=(0, 0, 0.0), end=(-300, 300, math.pi), R=R, width=W, lead=40, length=1400, region=[-400, -100, 300, 500]),
    "hairpin_back": dict(start=(0, 0, 0.0), end=(-500, 0, math.pi), R=R, width=W, lead=40, region=[-600, -300, 300, 300]),
    "T_region": dict(start=(20, 100, 0.0), end=(450, -580, -math.pi / 2), R=R, width=W, lead=30, length=2500,
                     region=[[0, 0, 900, 200], [300, -600, 600, 0]]),
    "rotated_port": dict(start=(0, 0, math.radians(30)), end=(800, 400, 0.0), R=R, width=W, lead=40, length=2200, region=[-50, -100, 850, 600]),
    "corridor": dict(start=(30, 0, 0.0), end=(640, -680, -math.pi / 2), R=R, width=W, lead=30, length=1800,
                     region=[[0, -110, 750, 110], [530, -700, 750, 110]]),
    "corridor_too_thin!": dict(start=(30, 0, 0.0), end=(640, -680, -math.pi / 2), R=R, width=W, lead=30, length=1800,
                               region=[[0, -60, 700, 60], [580, -700, 700, 60]]),
    "ring_around": dict(start=(30, 0, 0.0), end=(30, -600, math.pi), R=R, width=W, lead=40, length=2900,
                        region=[[0, -100, 900, 100], [700, -700, 900, 100], [0, -700, 900, -500]]),
    "notch_free": dict(A, length=3000, region=REGION_B, axis="free"),
    "Z_free": dict(start=(0, 0, 0.0), end=(900, 250, 0.0), R=R, width=W, lead=40, length=2600, region=[-30, -200, 930, 450], axis="free"),
    "facing_narrow": dict(start=(0, 0, 0.0), end=(900, 0, 0.0), R=R, width=W, lead=40, length=3000, region=[-30, -150, 930, 150]),
    "too_short!": dict(A, length=1200, region=REGION),
    "too_many_legs!": dict(A, length=3000, region=REGION, n_legs=20),
}

BLUE, RED, GREY, DARK, PINK = (70, 90, 220), (200, 30, 30), (150, 150, 150), (40, 40, 40), (255, 215, 215)


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                                  # 老 PIL
        return ImageFont.load_default()


def _dense(p, step=1.0):
    if p[0] == "line":
        return [(p[1], p[2]), (p[3], p[4])]
    _, cx, cy, r, a0, a1 = p
    n = max(2, int(abs(a1 - a0) * r / step))
    return [(cx + r * math.cos(a0 + (a1 - a0) * k / n), cy + r * math.sin(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]


def _offset(pts, d):
    """折线按法向偏 d (画 CPW 两边用, 调试精度够)。"""
    out = []
    for i, (x, y) in enumerate(pts):
        (x0, y0), (x1, y1) = pts[max(i - 1, 0)], pts[min(i + 1, len(pts) - 1)]
        L = math.hypot(x1 - x0, y1 - y0) or 1.0
        out.append((x - d * (y1 - y0) / L, y + d * (x1 - x0) / L))
    return out


def _rects(region):
    if region is None:
        return []
    return [list(r) for r in region] if isinstance(region[0], (list, tuple)) else [list(region)]


def _gaps(rects):
    """外框内不属于任何矩形的格子 (与 route._Region 同一定义)。"""
    xs = sorted({v for r in rects for v in (r[0], r[2])})
    ys = sorted({v for r in rects for v in (r[1], r[3])})
    return [(xs[i], ys[j], xs[i + 1], ys[j + 1]) for i in range(len(xs) - 1) for j in range(len(ys) - 1)
            if not any(r[0] <= (xs[i] + xs[i + 1]) / 2 <= r[2] and r[1] <= (ys[j] + ys[j + 1]) / 2 <= r[3] for r in rects)]


def render_scene(name, kw, size=900):
    rects = _rects(kw.get("region"))
    t = time.perf_counter()
    err, prims, skel = None, None, None
    try:
        prims = plan_cpw(**kw)
        if kw.get("length") is not None:
            skel = plan_cpw(**{k: v for k, v in kw.items() if k not in ("length", "n_legs")})
    except QuantumDslError as e:
        err = str(e)
    ms = (time.perf_counter() - t) * 1e3
    # 视野: region 外框 (没有就路 / 端口的包围盒) 加边
    pts = [q for p in (prims or skel or []) for q in _dense(p)] + [kw["start"][:2], kw["end"][:2]]
    xs = [v for r in rects for v in (r[0], r[2])] + [x for x, _ in pts]
    ys = [v for r in rects for v in (r[1], r[3])] + [y for _, y in pts]
    x0, x1, y0, y1 = min(xs) - 80, max(xs) + 80, min(ys) - 80, max(ys) + 80
    top = 95                                            # 顶部文字区
    s = min((size - 1) / (x1 - x0), (size - 1 - top) / (y1 - y0))
    img = Image.new("RGB", (size, size), "white")
    d = ImageDraw.Draw(img)

    def T(x, y):
        return ((x - x0) * s, top + (y1 - y) * s)
    for g in _gaps(rects):
        d.rectangle([T(g[0], g[3]), T(g[2], g[1])], fill=PINK)
    for r in rects:
        d.rectangle([T(r[0], r[3]), T(r[2], r[1])], outline=BLUE, width=2)
    if skel:
        for p in skel:
            d.line([T(*q) for q in _dense(p)], fill=GREY, width=1)
    if prims:
        w2 = kw.get("width", 0) / 2
        for p in prims:
            pts_p = _dense(p)
            for side in (-w2, w2):
                d.line([T(*q) for q in _offset(pts_p, side)], fill=GREY, width=2)
            d.line([T(*q) for q in pts_p], fill=RED, width=2)
    # 端口位姿 (箭头 = 行进方向) 与引出
    for (x, y, th), lab in ((kw["start"], "from"), (kw["end"], "to")):
        ax, ay = x + 60 * math.cos(th), y + 60 * math.sin(th)
        d.line([T(x, y), T(ax, ay)], fill=DARK, width=3)
        for k in (1, -1):
            d.line([T(ax, ay), T(ax - 18 * math.cos(th - k * 0.5), ay - 18 * math.sin(th - k * 0.5))], fill=DARK, width=3)
        d.text(T(x, y), lab, fill=DARK, font=_font(14), anchor="rb" if lab == "from" else "lt")
    # axis 罗盘
    axis = kw.get("axis", 0.0)
    cx, cy = size - 70, 70
    if axis == "free":
        d.ellipse([cx - 30, cy - 30, cx + 30, cy + 30], outline=BLUE, width=2)
        d.text((cx, cy), "free", fill=BLUE, font=_font(14), anchor="mm")
    else:
        for k in range(4):
            a = math.radians(axis) + k * math.pi / 2
            d.line([(cx, cy), (cx + 32 * math.cos(a), cy - 32 * math.sin(a))], fill=BLUE, width=2)
        d.text((cx, cy + 40), f"axis {axis}°", fill=BLUE, font=_font(14), anchor="mt")
    # 文字块
    lines = [name, f"R {kw['R']}  width {kw.get('width', 0)}  lead {kw.get('lead', 0)}  axis {axis}",
             f"region {rects if rects else None}",
             f"length {kw.get('length')}  n_legs {kw.get('n_legs', 0) or 'auto'}"]
    if prims:
        legs = sum(1 for p in prims if p[0] == "line") - 2 - (2 if skel and len(skel) > 2 else 0)
        turns = sum(1 for a, b in zip([None] + prims, prims) if b[0] == "arc" and not (a and a[0] == "arc" and a[1:4] == b[1:4]))
        lines.append(f"drawn {path_length(prims):.3f} um  prims {len(prims)}  arcs {turns}  {ms:.1f} ms")
    for i, ln in enumerate(lines):
        d.text((10, 10 + 17 * i), ln, fill=DARK, font=_font(14))
    if err:
        wrapped = textwrap.wrap(err, 120)[:14]
        y = size - 15 * len(wrapped) - 12
        pad = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(pad).rectangle([4, y - 6, size - 4, size - 4], fill=(255, 255, 255, 215), outline=RED)
        img = Image.alpha_composite(img.convert("RGBA"), pad).convert("RGB")
        d = ImageDraw.Draw(img)
        for ln in wrapped:
            d.text((10, y), ln, fill=RED, font=_font(12))
            y += 15
    return img


def gallery(out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    imgs = []
    for name, kw in SCENES.items():
        img = render_scene(name, kw)
        img.save(out_dir / f"{name.rstrip('!')}.png")
        imgs.append(img)
        print(name, "->", out_dir / f"{name.rstrip('!')}.png")
    cols = 4
    rows = math.ceil(len(imgs) / cols)
    sheet = Image.new("RGB", (cols * 900, rows * 900), "white")
    for i, img in enumerate(imgs):
        sheet.paste(img, ((i % cols) * 900, (i // cols) * 900))
    sheet.save(out_dir / "gallery.png")
    print("gallery ->", out_dir / "gallery.png")


def overlay(layout_yaml, gds_path):
    """在 build 出的 <gds>.png 上叠每条 cpw_route 步骤的 region 框 (蓝) / 缝 (红底) / 名字 + axis, 存 <gds>.debug.png。"""
    import gdstk
    import yaml

    doc = yaml.safe_load(Path(layout_yaml).read_text(encoding="utf-8"))
    png = Path(str(gds_path) + ".png")
    img = Image.open(png).convert("RGB")
    d = ImageDraw.Draw(img)
    cell = gdstk.read_gds(str(gds_path)).top_level()[0]
    (x0, y0), (x1, y1) = cell.bounding_box()
    s = 2000 / max(x1 - x0, y1 - y0)                    # 与 gds.render_gds_png 同一映射

    def T(x, y):
        return ((x - x0) * s, (y1 - y) * s)
    for step in doc.get("steps", []):
        if step.get("template") != "cpw_route" or "region" not in step:
            continue
        rects = _rects(step["region"])
        for g in _gaps(rects):
            d.rectangle([T(g[0], g[3]), T(g[2], g[1])], fill=PINK)
        for r in rects:
            d.rectangle([T(r[0], r[3]), T(r[2], r[1])], outline=BLUE, width=3)
        bx, by = min(r[0] for r in rects), max(r[3] for r in rects)
        label = f"{step['name']}  axis {step.get('axis', 0)}  region {rects}"
        d.text((T(bx, by)[0] + 4, T(bx, by)[1] + 4), label, fill=BLUE, font=_font(16))
    out = Path(str(gds_path) + ".debug.png")
    img.save(out)
    print("overlay ->", out)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--overlay":
        overlay(sys.argv[2], sys.argv[3])
    else:
        gallery(sys.argv[1] if len(sys.argv) > 1 else "build/demo/route_gallery")
