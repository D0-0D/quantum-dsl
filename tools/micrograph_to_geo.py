#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Vectorise the Sung et al. (PRX 11, 021058) Fig. 1(c) micrograph into a v4 ``.geo``.

The published layout dimensions exist nowhere but in that photo, so the geometry is
*measured*, not designed: threshold → connected components → contours → rectilinear
polygons → OCC ``.geo``.  Every manual intervention is listed in ``ERASE`` / ``JJ`` below.

Source image: ``fig1_device_layout.pdf`` inside the arXiv e-print
(``curl -L https://arxiv.org/e-print/2011.01261 | tar xz``); the micrograph is a 922×489
TIFF (identical to the PRX PDF's), and the figure's *vector* 100 µm scale bar is 15.83 pt long
while the image is placed at 4.1667 px/pt → **1.516 µm/px** (±1 px ≈ ±1.5 µm per edge).

Pixel → model: light = Al, dark = exposed Si.  Metal components touching the image border are
control/readout lines cut by the field of view → merged into ground (shorted at the field edge).
Interior components: the three islands (QB1, CPLR, QB2, left→right); anything < 500 px is an
airbridge pad or JJ fragment → treated as gap.  Junction leads are below resolution; the three
junctions are added as lumped ``jj::`` rectangles (GDS only, never meshed).

Extra deps beyond the package: ``pip install scipy scikit-image pillow`` (+ ``pypdf`` for .pdf input).

    python tools/micrograph_to_geo.py fig1_device_layout.pdf examples/sung_2021_xmon_traced.geo [measurement.png]

The optional PNG is the measurement audit figure (overlay + dimensions, polygon-vs-mask XOR map,
threshold sensitivity, reconstructed layout) — docs/report/img/sung_2021_xmon_measurement.png.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage
from shapely.geometry import LineString, Polygon
from skimage import measure

UM_PER_PX = 100.0 / (15.83 * 922 / 221.28)   # scale bar (pt) × image placement (px/pt)
THR = 143.5                                    # midpoint of the 8-bit gray range (32..255)
# (x, y, half-size) squares painted as gap: a line end that the threshold fused to the comb
ERASE = [(357, 114, 3)]
# lumped junctions: (device, x_px, y_from_px, y_to_px) — 2 µm wide bar from island tip to ground
JJ = [("QB1", 229, 151, 140), ("CPLR", 493, 122, 106), ("QB2", 692, 401, 407)]
JJ_W_UM = 2.0
GROUND_MARGIN_UM = 250.0                       # ground sheet beyond the photographed field
N8 = np.ones((3, 3), bool)
N4 = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], bool)


def load_gray(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        page = PdfReader(str(path)).pages[0]
        img = max(page.images, key=lambda im: im.image.size[0] * im.image.size[1]).image
    else:
        img = Image.open(path)
    return np.array(img.convert("L")).astype(float)


def snap(coords):
    """Axis-align H/V edges (keep diagonals); vertices = intersections of the snapped lines."""
    pts = [tuple(p) for p in coords]
    if np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    n = len(pts)
    lines = []
    for i in range(n):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        if abs(dy) <= 0.35 * abs(dx):
            lines.append(("H", (y1 + y2) / 2))
        elif abs(dx) <= 0.35 * abs(dy):
            lines.append(("V", (x1 + x2) / 2))
        else:
            lines.append(("D", ((x1, y1), (x2, y2))))
    merged = []
    for L in lines:
        if merged and L[0] in "HV" and merged[-1][0] == L[0]:
            merged[-1] = (L[0], (merged[-1][1] + L[1]) / 2)
        else:
            merged.append(L)
    if len(merged) > 1 and merged[0][0] in "HV" and merged[-1][0] == merged[0][0]:
        merged[0] = (merged[0][0], (merged[0][1] + merged[-1][1]) / 2)
        merged.pop()

    def as_line(L):
        if L[0] == "H":
            return LineString([(-1e4, L[1]), (1e4, L[1])])
        if L[0] == "V":
            return LineString([(L[1], -1e4), (L[1], 1e4)])
        (x1, y1), (x2, y2) = L[1]
        dx, dy = x2 - x1, y2 - y1
        return LineString([(x1 - 100 * dx, y1 - 100 * dy), (x2 + 100 * dx, y2 + 100 * dy)])

    out = []
    m = len(merged)
    for i in range(m):
        a, b = merged[i], merged[(i + 1) % m]
        if a[0] == "H" and b[0] == "V":
            out.append((b[1], a[1]))
        elif a[0] == "V" and b[0] == "H":
            out.append((a[1], b[1]))
        else:
            p = as_line(a).intersection(as_line(b))
            if p.is_empty or p.geom_type != "Point":
                return None
            out.append((p.x, p.y))
    return out


def tidy(pts, min_edge_px=1.0):
    """Round to the half-pixel grid (pixel edges), drop duplicates / collinear points, and
    collapse edges shorter than ``min_edge_px`` (re-snapping after each collapse)."""
    for _ in range(50):
        q = []
        for x, y in ((round(x * 2) / 2, round(y * 2) / 2) for x, y in pts):
            if not q or (x, y) != q[-1]:
                q.append((x, y))
        if len(q) > 1 and q[0] == q[-1]:
            q.pop()
        k = 0
        while k < len(q) and len(q) > 3:
            a, b, c = q[k - 1], q[k], q[(k + 1) % len(q)]
            if (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) == 0:
                q.pop(k)
            else:
                k += 1
        edges = [((q[i][0] - q[(i + 1) % len(q)][0]) ** 2 + (q[i][1] - q[(i + 1) % len(q)][1]) ** 2) ** 0.5
                 for i in range(len(q))]
        i = int(np.argmin(edges))
        if edges[i] >= min_edge_px or len(q) <= 4:
            return q
        a, b = q[i], q[(i + 1) % len(q)]
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        q = [p for j, p in enumerate(q) if j not in (i, (i + 1) % len(q))]
        q.insert(i, mid)
        pts = snap(q) or q
    return q


def polygon_of(mask: np.ndarray, tol_px=1.0) -> Polygon:
    filled = np.pad(ndimage.binary_fill_holes(mask), 1)
    contour = max(measure.find_contours(filled.astype(float), 0.5), key=len)
    xy = np.column_stack([contour[:, 1] - 1, contour[:, 0] - 1])
    simp = measure.approximate_polygon(xy, tol_px)
    sn = snap(simp)
    poly = Polygon(tidy(sn)) if sn else None
    if poly is None or not poly.is_valid or poly.area < 0.5 * Polygon(simp).area:
        poly = Polygon(simp).buffer(0)
        if poly.geom_type != "Polygon":
            poly = max(poly.geoms, key=lambda g: g.area)
    return poly


def vectorise(gray: np.ndarray):
    metal = gray > THR
    H, W = metal.shape
    for x, y, r in ERASE:
        metal[y - r:y + r + 1, x - r:x + r + 1] = False
    lab, n = ndimage.label(metal)
    gid = lab[0, 0]
    objs = ndimage.find_objects(lab)
    areas = ndimage.sum(metal, lab, range(1, n + 1))
    ground = lab == gid
    interior = []
    for i, (sl, a) in enumerate(zip(objs, areas), 1):
        if i == gid:
            continue
        on_border = sl[0].start == 0 or sl[1].start == 0 or sl[0].stop == H or sl[1].stop == W
        if on_border:
            ground |= lab == i
        elif a >= 500:
            interior.append(((sl[1].start + sl[1].stop) / 2, lab == i))
    if len(interior) != 3:
        raise SystemExit(f"expected 3 islands, found {len(interior)} — threshold/ERASE need attention")
    islands = dict(zip(["QB1", "CPLR", "QB2"], [m for _, m in sorted(interior, key=lambda t: t[0])]))
    gap = ~ground
    for m in islands.values():
        gap &= ~m
    glab, gn = ndimage.label(gap, structure=N4)
    gareas = ndimage.sum(gap, glab, range(1, gn + 1))
    isl_polys = {k: polygon_of(m) for k, m in islands.items()}
    holes = []
    for i, a in enumerate(gareas, 1):
        if a < 30:
            continue
        poly = polygon_of(glab == i)
        x0, y0, x1, y1 = poly.bounds
        b = 3  # the micrograph has a 1–2 px light frame on its top/right edges
        sides = [s for s, hit in (("left", x0 <= b), ("right", x1 >= W - 1 - b),
                                  ("top", y0 <= b), ("bottom", y1 >= H - 1 - b)) if hit]
        inside = [k for k, p in isl_polys.items() if poly.contains(p.representative_point())]
        nearest = min(isl_polys, key=lambda k: poly.distance(isl_polys[k]))
        holes.append({"poly": poly, "area_px": int(a), "sides": sides, "contains": inside, "nearest": nearest})
    holes.sort(key=lambda h: (-len(h["contains"]), -h["area_px"]))   # cutouts first, then slots by size
    return isl_polys, holes, (W, H)


def to_um(poly: Polygon, W, H):
    return [((x - W / 2) * UM_PER_PX, (H / 2 - y) * UM_PER_PX) for x, y in poly.exterior.coords[:-1]]


ISLAND_DESC = {
    "QB1": "Xmon cross island — grounded through a single JJ at the top arm tip",
    "CPLR": "comb-shaped coupler island — bottom bar + 6 teeth + centre stub, grounded through a SQUID",
    "QB2": "Xmon cross island — grounded through an asymmetric SQUID at the bottom arm tip",
}


def _xy_table(pts, per_line=5):
    """poly_xy() = {...} block, 5 vertices per line, 0.01 µm (measurement error is ~1.5 µm)."""
    pairs = [f"{x:8.2f},{y:8.2f}" for x, y in pts]
    rows = []
    for i in range(0, len(pairs), per_line):
        chunk = ",   ".join(pairs[i:i + per_line])
        rows.append("  " + chunk + ("," if i + per_line < len(pairs) else ""))
    return "poly_xy() = {\n" + "\n".join(rows) + "\n};"


def _shape_note(poly_um):
    xs = [x for x, _ in poly_um]
    ys = [y for _, y in poly_um]
    return (f"bbox {max(xs) - min(xs):.0f} × {max(ys) - min(ys):.0f} µm, "
            f"x∈[{min(xs):.0f}, {max(xs):.0f}] y∈[{min(ys):.0f}, {max(ys):.0f}], {len(poly_um)} vertices")


def emit_geo(islands, holes, size, out: Path):
    W, H = size
    fw, fh = W * UM_PER_PX, H * UM_PER_PX
    gx0, gy0 = -fw / 2 - GROUND_MARGIN_UM, -fh / 2 - GROUND_MARGIN_UM
    L = [
        "// =====================================================================",
        f"// {out.name} — Sung et al. PRX 11, 021058 (2021) 论文真版图的**逐点描摹**(traced), 由显微照片直接矢量化。",
        "// GENERATED by tools/micrograph_to_geo.py — 不要手改; 改脚本常量 (THR / ERASE / JJ) 再生成。",
        "//",
        f"// 出处: arXiv:2011.01261 e-print 的 fig1_device_layout.pdf, 922×489 px 微照片; 矢量标尺给出",
        f"// {UM_PER_PX:.4f} µm/px (每条边 ±1 px ≈ ±1.5 µm)。视场 {fw:.0f} × {fh:.0f} µm, 原点 = 照片中心, y 向上。",
        "// 浅色 = Al (金属), 深色 = 裸 Si (刻蚀缝)。三个岛都是接地 transmon; 视场内被截断的控制/读出线并入地",
        "// (等价于在视场边缘接地); 结引线低于分辨率, 结按集总 jj:: 补画。量得的关键尺寸 (Xmon 臂宽 30、臂–地缝 32、",
        "// 梳齿 24–26 / 地指 20 / 缝 27 µm …) 见 sung_2021_xmon_traced.meta.yaml 头注; 参数化重建版 = sung_2021_xmon.geo。",
        "//",
        "// 每个多边形 = 一段注释 (是什么、多大、在哪) + 一张 poly_xy() 坐标表 + Call POLY (qlib.geo)。",
        "// ⚠ gmsh 解析器: `Call X;` 之后同一行不能再写语句 (会在宏体执行前被吃掉) —— sret 取值另起一行。",
        "// =====================================================================",
        "",
        'SetFactory("OpenCASCADE");',
        'Include "qlib.geo";',
        "",
        f"jj_w = {JJ_W_UM:g};     // lumped JJ bar width (GDS layer 20 only, never meshed)",
        "",
        "// ---- 1) Islands: three grounded transmons (metal::1::<name>::island) --------------",
    ]
    for name, poly in islands.items():
        pts = to_um(poly, W, H)
        L += ["", f"// {name} — {ISLAND_DESC[name]}", f"//   {_shape_note(pts)}",
              _xy_table(pts), "Call POLY;", f"isl_{name} = sret;",
              f'Physical Surface("metal::1::{name}::island") = {{ isl_{name} }};']
    L += ["", "// ---- 2) Ground: one sheet (field + margin) minus every etched region of the photo -----",
          f"// sheet {fw + 2 * GROUND_MARGIN_UM:.0f} × {fh + 2 * GROUND_MARGIN_UM:.0f} µm = field + {GROUND_MARGIN_UM:g} µm margin all round",
          f"gnd = news; Rectangle(gnd) = {{ {gx0:.2f}, {gy0:.2f}, 0, {fw + 2 * GROUND_MARGIN_UM:.2f}, {fh + 2 * GROUND_MARGIN_UM:.2f} }};"]
    tags = []
    for k, h in enumerate(holes, 1):
        pts = to_um(h["poly"], W, H)
        if h["contains"]:
            what = f"etched moat (gap ring) around {' + '.join(h['contains'])} — that island polygon sits inside it"
        elif h["sides"]:
            what = (f"CPW slot of a control/readout line cut by the field of view at the {'/'.join(h['sides'])} edge, "
                    f"nearest {h['nearest']} — its centre conductor is ground here")
        else:
            what = f"small etched feature near {h['nearest']} (airbridge pad / line end)"
        L += ["", f"// gap {k} — {what}", f"//   {_shape_note(pts)}, {h['area_px']} px",
              _xy_table(pts), "Call POLY;", f"gap{k} = sret;"]
        tags.append(f"gap{k}")
    L += ["", "gd() = BooleanDifference{ Surface{ gnd }; Delete; }{ Surface{ " + ", ".join(tags) + " }; Delete; };",
          'Physical Surface("ground::1::chip::gnd") = { gd(0) };',
          "", "// ---- 3) Junctions: lumped bars from island tip to ground (jj::1::<device>::jj) ----------"]
    for dev, x, y0, y1 in JJ:
        xu = (x - W / 2) * UM_PER_PX
        ya, yb = (H / 2 - y0) * UM_PER_PX, (H / 2 - y1) * UM_PER_PX
        L += ["", f"// {dev}: from island tip (y={ya:.1f}) to ground (y={yb:.1f}) at x={xu:.1f}",
              f"x1 = {xu:.2f}; y1 = {ya:.2f}; x2 = {xu:.2f}; y2 = {yb:.2f}; width = jj_w;  Call JUNCTION;",
              f'Physical Surface("jj::1::{dev}::jj") = {{ sret }};']
    out.write_text("\n".join(L) + "\n", encoding="utf-8")



# ----------------------------------------------------------------------------------------------
# Measurement figure — the visual audit of the vectorisation (docs/report/img/…measurement.png)
# ----------------------------------------------------------------------------------------------
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
COL = {"QB1": (0, 90, 255), "CPLR": (255, 0, 0), "QB2": (0, 170, 0), "gap": (255, 200, 0), "jj": (255, 0, 255)}


def _font(sz):
    try:
        return ImageFont.truetype(FONT, sz)
    except OSError:
        return ImageFont.load_default()


def _runs(line, geom):
    """sorted (lo, hi) intervals where a horizontal/vertical shapely line crosses geom (px)."""
    inter = line.intersection(geom)
    parts = [inter] if inter.geom_type == "LineString" else list(getattr(inter, "geoms", []))
    horizontal = line.coords[0][1] == line.coords[-1][1]
    out = []
    for p in parts:
        if p.geom_type != "LineString" or p.length == 0:
            continue
        v = [c[0] if horizontal else c[1] for c in p.coords]
        out.append((min(v), max(v)))
    return sorted(out)


def _runs(line, geom):
    """sorted (lo, hi) intervals (px) where an axis-parallel shapely line crosses geom."""
    inter = line.intersection(geom)
    parts = [inter] if inter.geom_type == "LineString" else list(getattr(inter, "geoms", []))
    horizontal = line.coords[0][1] == line.coords[-1][1]
    out = []
    for p in parts:
        if p.geom_type != "LineString" or p.length == 0:
            continue
        v = [c[0] if horizontal else c[1] for c in p.coords]
        out.append((min(v), max(v)))
    return sorted(out)


def measure_dims(islands, holes, size):
    """Key dimensions read off the FINAL polygons (exact, sub-pixel): what the FEM sees.
    ground = field minus every gap polygon; anything neither island nor ground is etched gap."""
    from shapely.geometry import LineString, box
    from shapely.ops import unary_union
    W, H = size
    ground = box(-0.5, -0.5, W - 0.5, H - 0.5).difference(unary_union([h["poly"] for h in holes]))
    hline = lambda y: LineString([(-1, y), (W + 1, y)])
    vline = lambda x: LineString([(x, -1), (x, H + 1)])
    m = {}
    for q in ("QB1", "QB2"):
        p = islands[q]
        x0, y0, x1, y1 = p.bounds
        span, yc, arm = 0, 0, None                       # horizontal arm = row with the longest island run
        for y in np.arange(int(y0) + 1, int(y1)):
            for a, b in _runs(hline(y), p):
                if b - a > span:
                    span, yc, arm = b - a, y, (a, b)
        vspan, xc = max((max((b - a for a, b in _runs(vline(x), p)), default=0), x)
                        for x in np.arange(int(x0) + 1, int(x1)))
        g = _runs(hline(yc), ground)
        gl = min((arm[0] - b for a, b in g if b <= arm[0] + 1e-6), default=float("nan"))
        gr = min((a - arm[1] for a, b in g if a >= arm[1] - 1e-6), default=float("nan"))
        aw = [b - a for a, b in _runs(hline(yc + 30), p) if a <= xc <= b]
        m[q] = {"xc": xc, "yc": yc, "span": span, "vspan": vspan, "gap_l": gl, "gap_r": gr, "gap": (gl + gr) / 2,
                "arm_w": aw[0] if aw else float("nan"), "arm_x0": arm[0], "arm_x1": arm[1]}
    c = islands["CPLR"]
    x0, y0, x1, y1 = c.bounds
    yt = y0 + 35                                              # a row through the teeth
    I = _runs(hline(yt), c)
    G = [r for r in _runs(hline(yt), ground) if r[0] >= I[0][0] and r[1] <= I[-1][1]]
    seq = sorted([(a, b, "I") for a, b in I] + [(a, b, "G") for a, b in G])
    fingers = [b - a for k, (a, b, t) in enumerate(seq) if t == "G" and 0 < k < len(seq) - 1
               and seq[k - 1][2] == "I" and seq[k + 1][2] == "I"]      # ground strictly between two teeth
    gaps = [nb[0] - pa[1] for pa, nb in zip(seq, seq[1:]) if nb[0] - pa[1] > 0.6]
    col = _runs(vline(x0 + 60), c)
    m["CPLR"] = {"yt": yt, "teeth": [b - a for a, b in I], "gaps": gaps, "fingers": fingers,
                 "bar": (col[-1][1] - col[-1][0]) if col else float("nan"), "xl": x0 + 60, "x_lo": I[0][0], "x_hi": I[-1][1]}
    m["centre_dist"] = m["QB2"]["xc"] - m["QB1"]["xc"]
    return m


def raster(islands, holes, size):
    """Metal mask implied by the final polygons (pixel centres at k+0.5 → shift polygons by 0.5)."""
    W, H = size
    img = Image.new("1", (W, H), 1)
    d = ImageDraw.Draw(img)
    for h in holes:
        d.polygon([(x + 0.5, y + 0.5) for x, y in h["poly"].exterior.coords], fill=0)
    for p in islands.values():
        d.polygon([(x + 0.5, y + 0.5) for x, y in p.exterior.coords], fill=1)
    return np.array(img, bool)


def figure(gray, islands, holes, size, out_png, alt_thr=(120.0, 160.0)):
    W, H = size
    S = 1.5                                       # px → figure px for the full-field panels
    PW, PH = int(W * S), int(H * S)
    TITLE = 34
    f_t, f_l, f_s = _font(22), _font(17), _font(14)
    photo = Image.fromarray(gray.astype(np.uint8)).convert("RGB")
    base = photo.resize((PW, PH), Image.BILINEAR)
    m = measure_dims(islands, holes, size)
    um = UM_PER_PX

    def P(x, y):                                  # px → panel coords
        return ((x + 0.5) * S, (y + 0.5) * S)

    def outline(d, poly, col, w=2):
        d.line([P(x, y) for x, y in poly.exterior.coords], fill=col, width=w)

    def label(d, xy, text, col=(255, 255, 255), bg=(0, 0, 0), font=None, anchor="la"):
        font = font or f_l
        x, y = xy
        bb = d.textbbox((x, y), text, font=font, anchor=anchor)
        d.rectangle((bb[0] - 3, bb[1] - 2, bb[2] + 3, bb[3] + 2), fill=bg)
        d.text((x, y), text, fill=col, font=font, anchor=anchor)

    def dim(d, a, b, text, col, off=(0, 0)):    # dimension line between px points a, b with a label
        ax, ay = P(*a); bx, by = P(*b)
        d.line([(ax, ay), (bx, by)], fill=col, width=2)
        for x, y in ((ax, ay), (bx, by)):
            d.ellipse((x - 3, y - 3, x + 3, y + 3), fill=col)
        label(d, ((ax + bx) / 2 + off[0], (ay + by) / 2 + off[1]), text, col=(0, 0, 0), bg=col, font=f_s, anchor="mm")

    # ---- panel A: overlay + measured dimensions ------------------------------------------------
    A = base.copy(); d = ImageDraw.Draw(A)
    for h in holes:
        outline(d, h["poly"], COL["gap"], 2)
    for n, p in islands.items():
        outline(d, p, COL[n], 3)
    for dev, x, y0, y1 in JJ:
        d.rectangle((P(x - 1.5, min(y0, y1))[0], P(x, min(y0, y1))[1], P(x + 1.5, max(y0, y1))[0], P(x, max(y0, y1))[1]),
                    outline=COL["jj"], width=3)
    for x, y, r in ERASE:
        x0, y0 = P(x - r - 3, y - r - 3); x1, y1 = P(x + r + 3, y + r + 3)
        d.rectangle((x0, y0, x1, y1), outline=(0, 255, 255), width=3)
        label(d, (x1 + 6, y0), "erased fused line end (7x7 px)", col=(0, 255, 255))
    for q in ("QB1", "QB2"):
        k = m[q]; yc, xc = k["yc"], k["xc"]
        hx0, hx1 = k["arm_x0"] - 0.5, k["arm_x1"] - 0.5
        dim(d, (hx0, yc - 6), (hx1, yc - 6), f"{q} arm span {k['span'] * um:.0f} um", COL[q], off=(0, -14))
        dim(d, (hx0 - k["gap_l"], yc + 6), (hx0, yc + 6), f"gap {k['gap_l'] * um:.0f}", COL["gap"], off=(-38, 14))
        dim(d, (xc - k["arm_w"] / 2, yc + 60), (xc + k["arm_w"] / 2, yc + 60), f"arm {k['arm_w'] * um:.0f}", COL[q], off=(48, 0))
    k = m["CPLR"]
    label(d, P(k["xl"] - 60, k["yt"] - 30), f"CPLR comb: tooth {np.median(k['teeth']) * um:.0f} / gap {np.median(k['gaps']) * um:.0f} / "
          f"ground finger {np.median(k['fingers']) * um:.0f} / bar {k['bar'] * um:.0f} um", col=COL["CPLR"])
    dim(d, (m["QB1"]["xc"], 30), (m["QB2"]["xc"], 30), f"centre-to-centre {m['centre_dist'] * um:.0f} um", (255, 255, 255), off=(0, -14))
    # scale bar
    sb = 100 / um
    d.line([P(20, H - 20), P(20 + sb, H - 20)], fill=(255, 255, 255), width=5)
    label(d, P(20, H - 26), f"100 um = {sb:.2f} px  ({um:.4f} um/px from the figure's vector scale bar)", anchor="lb")
    label(d, (8, 8), "islands: QB1 blue / CPLR red / QB2 green   etched gaps: yellow   lumped JJ: magenta", font=f_s)

    # ---- panel B: mismatch map (polygon raster XOR threshold mask) -----------------------------
    mask = gray > THR
    for x, y, r in ERASE:
        mask[y - r:y + r + 1, x - r:x + r + 1] = False
    ras = raster(islands, holes, size)
    diff = mask ^ ras
    lab, n = ndimage.label(diff, structure=np.ones((3, 3)))
    sizes = ndimage.sum(diff, lab, range(1, n + 1)) if n else []
    blobs = sorted([(int(a), i) for i, a in enumerate(sizes, 1) if a >= 30], reverse=True)
    dim_photo = Image.fromarray((gray * 0.45).astype(np.uint8)).convert("RGB").resize((PW, PH), Image.BILINEAR)
    red = Image.fromarray(np.where(diff, 255, 0).astype(np.uint8)).resize((PW, PH), Image.NEAREST)
    B = dim_photo.copy()
    B.paste(Image.new("RGB", (PW, PH), (255, 40, 40)), mask=red)
    d = ImageDraw.Draw(B)
    notes, compact, strips = [], [], 0
    for a, i in blobs:
        sl = ndimage.find_objects((lab == i).astype(int))[0]
        bh, bw = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        fill = a / (bw * bh)
        if min(bw, bh) <= 3 or (fill < 0.25 and min(bw, bh) > 10):
            strips += 1                                   # 1-px strip along an edge / diagonal staircase
            continue
        cy, cx = (sl[0].start + sl[0].stop) / 2, (sl[1].start + sl[1].stop) / 2
        inside_metal = mask[lab == i].mean()
        from shapely.geometry import Point
        on_line = any(h["sides"] and h["poly"].distance(Point(cx, cy)) <= 3 for h in holes)
        kind = ("dropped metal blob (<500 px interior: airbridge pad / JJ fragment)" if inside_metal > 0.9 else
                "filled hole (<30 px)" if inside_metal < 0.1 else
                "airbridge bar / line-end simplification on a control-line slot (ground-to-ground, no electrical effect)"
                if on_line else "mixed: CHECK")
        compact.append((a, cx, cy, kind))
    for k, (a, cx, cy, kind) in enumerate(compact[:10], 1):
        x, y = P(cx, cy)
        d.ellipse((x - 14, y - 14, x + 14, y + 14), outline=(255, 255, 0), width=2)
        label(d, (x + 16, y - 10), str(k), col=(255, 255, 0), font=f_s)
        notes.append(f"{k}: {a} px @({(cx - W / 2) * um:.0f},{(H / 2 - cy) * um:.0f}) um — {kind}")
    notes.append(f"+ {strips} elongated strips (1-px wide along edges / 45-deg staircases) = sub-pixel edge placement, "
                 f"<= 0.5 px = {0.5 * um:.1f} um — not geometry errors")
    edge_px = int(diff.sum())
    label(d, (8, 8), f"polygon raster XOR threshold mask: {edge_px} px differ = {edge_px / diff.size * 100:.2f}% of field; "
          f"{len(compact)} compact blobs >= 30 px (circled, deliberate drops) + {strips} edge strips", font=f_s)
    for j, t in enumerate(notes):
        label(d, (8, PH - 8 - (len(notes) - j) * 18), t, font=f_s)

    # ---- panel C: threshold sensitivity, zoomed --------------------------------------------------
    cx0, cy0, cw, ch = 150, 60, int(PW / 5), int(PH / 5)     # crop (px) shown at 5x
    Z = 5
    C = photo.crop((cx0, cy0, cx0 + cw, cy0 + ch)).resize((cw * Z, ch * Z), Image.NEAREST)
    d = ImageDraw.Draw(C)
    def Pz(x, y):
        return ((x - cx0 + 0.5) * Z, (y - cy0 + 0.5) * Z)
    variants = [(THR, (0, 90, 255), islands, holes)]
    global_thr = globals()
    for thr, col in zip(alt_thr, ((255, 140, 0), (0, 200, 0))):
        saved = global_thr["THR"]; global_thr["THR"] = thr
        try:
            isl2, holes2, _ = vectorise(gray.copy())
            variants.append((thr, col, isl2, holes2))
        except SystemExit:
            variants.append((thr, col, None, None))
        finally:
            global_thr["THR"] = saved
    leg = []
    for thr, col, isl2, holes2 in variants:
        if isl2 is None:
            leg.append(f"THR={thr:g}: vectorisation FAILS (islands fuse/split)"); continue
        for p in list(isl2.values()) + [h["poly"] for h in holes2]:
            d.line([Pz(x, y) for x, y in p.exterior.coords], fill=col, width=2)
        leg.append(f"THR={thr:g}")
    for j, (t, (thr, col, *_)) in enumerate(zip(leg, variants)):
        label(d, (8, 8 + j * 22), t, col=col, font=f_l)
    label(d, (8, ch * Z - 30), f"zoom {Z}x on QB1 top arm + comb left end; 1 px = {um:.2f} um; outlines shift <= 0.5 px across the valid window", font=f_s)

    # ---- panel D: reconstructed layout (what FEM/GDS see) -----------------------------------------
    D = Image.fromarray(np.where(ras, 225, 60).astype(np.uint8)).convert("RGB").resize((PW, PH), Image.NEAREST)
    d = ImageDraw.Draw(D)
    for dev, x, y0, y1 in JJ:
        d.rectangle((P(x - 1, min(y0, y1))[0], P(x, min(y0, y1))[1], P(x + 1, max(y0, y1))[0], P(x, max(y0, y1))[1]), fill=COL["jj"])
    label(d, (8, 8), "metal (islands + ground) light, etched Si dark, JJ magenta; border-touching lines are ground", font=f_s, col=(0, 0, 0), bg=(225, 225, 225))

    # ---- assemble --------------------------------------------------------------------------------
    pad = 12
    Cw, Chh = C.size
    out = Image.new("RGB", (2 * PW + 3 * pad, 2 * (PH + TITLE) + 3 * pad + 70), (30, 30, 34))
    d = ImageDraw.Draw(out)
    titles = ["A  vectorised polygons over the micrograph + dimensions measured on the final polygons",
              "B  audit: where the polygons disagree with the threshold mask (red)",
              "C  threshold sensitivity (valid window ~115-165)",
              "D  reconstructed layout = FEM / GDS input"]
    cells = [A, B, C.resize((PW, PH), Image.LANCZOS) if C.size != (PW, PH) else C, D]
    for k, (img, t) in enumerate(zip(cells, titles)):
        col, row = k % 2, k // 2
        x = pad + col * (PW + pad); y = pad + row * (PH + TITLE + pad)
        d.text((x, y + 6), t, fill=(255, 255, 255), font=f_t)
        out.paste(img, (x, y + TITLE))
    foot = (f"Source: arXiv:2011.01261 e-print fig1_device_layout.pdf, {W}x{H} px micrograph; scale {um:.4f} um/px; threshold {THR:g} "
            f"(gray range 32-255, Si ~90-110, Al ~230-255); field {W * um:.0f} x {H * um:.0f} um.  "
            f"Measured on the final polygons: Xmon arm {m['QB1']['arm_w'] * um:.1f}/{m['QB2']['arm_w'] * um:.1f} um, gap {m['QB1']['gap'] * um:.1f}/{m['QB2']['gap'] * um:.1f} um, "
            f"span {m['QB1']['span'] * um:.0f}/{m['QB2']['span'] * um:.0f} um; comb tooth {np.median(m['CPLR']['teeth']) * um:.1f}, gap {np.median(m['CPLR']['gaps']) * um:.1f}, "
            f"finger {np.median(m['CPLR']['fingers']) * um:.1f}, bar {m['CPLR']['bar'] * um:.1f} um; centre distance {m['centre_dist'] * um:.0f} um.  +-1 px = +-{um:.1f} um per edge.")
    y = out.size[1] - 66
    for line in (foot[:len(foot) // 2].rsplit(" ", 1)[0], foot[len(foot[:len(foot) // 2].rsplit(" ", 1)[0]) + 1:]):
        d.text((pad, y), line, fill=(230, 230, 230), font=f_s); y += 20
    out.save(out_png)
    return m, edge_px, compact, notes


def main(argv):
    src, dst = Path(argv[1]), Path(argv[2])
    gray = load_gray(src)
    islands, holes, size = vectorise(gray)
    emit_geo(islands, holes, size, dst)
    for k, p in islands.items():
        print(f"{k}: {len(p.exterior.coords) - 1} vertices, area {p.area * UM_PER_PX ** 2:.0f} µm²")
    print(f"{len(holes)} ground gaps, {sum(len(h['poly'].exterior.coords) - 1 for h in holes)} vertices -> {dst}")
    if len(argv) > 3:
        m, edge_px, blobs, notes = figure(gray, islands, holes, size, argv[3])
        um = UM_PER_PX
        print(f"measured on polygons: Xmon arm {m['QB1']['arm_w'] * um:.1f}/{m['QB2']['arm_w'] * um:.1f}, gap {m['QB1']['gap'] * um:.1f}/{m['QB2']['gap'] * um:.1f}, "
              f"span {m['QB1']['span'] * um:.0f}/{m['QB2']['span'] * um:.0f} um; comb tooth {np.median(m['CPLR']['teeth']) * um:.1f} gap {np.median(m['CPLR']['gaps']) * um:.1f} "
              f"finger {np.median(m['CPLR']['fingers']) * um:.1f} bar {m['CPLR']['bar'] * um:.1f} um; centre distance {m['centre_dist'] * um:.0f} um")
        print(f"audit: {edge_px} px differ from threshold mask ({edge_px / (size[0] * size[1]) * 100:.2f}%), {len(blobs)} compact blobs >= 30 px")
        for t in notes:
            print("   ", t)
        print("figure ->", argv[3])


if __name__ == "__main__":
    main(sys.argv)
