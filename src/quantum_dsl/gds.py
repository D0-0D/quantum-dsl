# -*- coding: utf-8 -*-
"""GDS 分叉 (契约「GDS」): ``.geo`` → GDS, µm verbatim, 旁路网格。

坐标 **µm 逐字** (gdstk Library ``unit=1e-6``), 不缩放 (SPEC「不双重缩放」)。
映射两种口径: meta 有 ``layers:`` 表时按 **层** (Physical 名第 2 段 → ``layers[id].gds``,
没给 gds 的层不进 GDS); 否则按 ``gds.by_role`` (role → {layer, datatype}); 不在映射里的
面不进 GDS (映射就是选择机制 —— jj 要进 GDS 就映射 jj)。几何源 = ``.geo`` 路径或版图 Layout。

面 → 多边形走 gmsh 2D 三角化 + gdstk 布尔并 (逐面): 对任意 OCC 面 (含布尔
差挖出的带孔 ground) 都稳健; 直边多边形的角点是网格顶点, 逐字保真。
gmsh/gdstk 惰性 import (import 纯度)。

``render_gds_png``: GDS → PNG 概览 (金属浅 / 衬底深 / jj 品红), build() 随 GDS 一起产
``<stem>.gds.png``。带孔 ground 用 field − metal 布尔取真缝 (PIL 不会填孔)。PIL 惰性 import。
"""

from __future__ import annotations

from pathlib import Path

from .errors import QuantumDslError
from .geo import parse_physical_name

__all__ = ["build_gds", "render_gds_png", "gds_map", "jj_gds_layers"]

_METAL, _SUBSTRATE, _JJ = (225, 225, 225), (60, 60, 66), (255, 0, 200)


def gds_map(meta) -> dict:
    """GDS 映射: ``{("layer", id) | ("role", role): (layer, datatype)}``; 空 = 不出 GDS。"""
    if meta.layers:
        return {("layer", lid): spec["gds"] for lid, spec in meta.layers.items() if "gds" in spec}
    return {("role", r): (int(spec["layer"]), int(spec.get("datatype", 0)))
            for r, spec in ((meta.gds or {}).get("by_role") or {}).items()}


def jj_gds_layers(meta) -> tuple[int, ...]:
    """预览里画品红的 GDS 层号: junction 层 (层表) 或 by_role.jj。"""
    if meta.layers:
        return tuple(spec["gds"][0] for spec in meta.layers.values()
                     if spec["kind"] == "junction" and "gds" in spec)
    jj = ((meta.gds or {}).get("by_role") or {}).get("jj")
    return (int(jj["layer"]),) if jj else ()


def build_gds(source, meta, out) -> Path:
    """几何源 (``.geo`` 路径或 Layout) + Meta → GDS 文件路径。"""
    from ._gmsh import geo_model, source_label

    label = source_label(source)
    if not callable(source) and not Path(source).is_file():
        raise QuantumDslError(f"build_gds: no such file: {source}")
    gmap = gds_map(meta)
    if not gmap:
        raise QuantumDslError(
            "build_gds: no GDS mapping — give layers.<id>.gds: [layer, datatype] or "
            "gds.by_role (e.g. metal: {layer: 1, datatype: 0})")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    import gdstk

    with geo_model(source) as gmsh:
        groups = []                     # (Physical, (layer, datatype), [face tags])
        for dim, ptag in gmsh.model.getPhysicalGroups(2):
            phys = parse_physical_name(gmsh.model.getPhysicalName(dim, ptag))
            spec = gmap.get(("layer", phys.layer)) or gmap.get(("role", phys.role))
            if spec is not None:
                groups.append((phys, spec, [int(t) for t in
                               gmsh.model.getEntitiesForPhysicalGroup(dim, ptag)]))
        if not groups:
            raise QuantumDslError(
                f"build_gds: no surfaces in {label} match the GDS mapping {sorted(gmap)}")

        # 粗三角化只为提取多边形轮廓 (尺寸=domain 级 → 直边三角形最少)。
        # gmsh.option 是全局的 (进程级共享 session) — 依赖的选项全部显式设。
        # 圆弧按 180 段/2π 采样: 90° 弧 45 段, 面积误差 ≲1e-4; 设 0 时一段 90° 弧只剩 2 段折线,
        # 46 段弧的蛇形面积错 1.8% (2026-08-27 实测)。FromPoints / ExtendFromBoundary 必须关: 否则弧端
        # ~1.4 µm 的尺寸沿直边与面内传染, 1.7 mm 地平面变成百万三角形 + gdstk 并 >5 min。
        gmsh.option.setNumber("Mesh.MeshSizeMin", 0)
        gmsh.option.setNumber("Mesh.MeshSizeMax", 1e9)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 180)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.ElementOrder", 1)
        gmsh.model.mesh.generate(2)
        tags, coords, _ = gmsh.model.mesh.getNodes()
        xy = {int(t): (coords[3 * i], coords[3 * i + 1])
              for i, t in enumerate(tags)}

        lib = gdstk.Library(name=out.stem, unit=1e-6, precision=1e-9)
        cell = lib.new_cell(out.stem)
        for phys, (layer, dtype), faces in groups:
            tris = []
            for f in faces:
                etypes, _, enodes = gmsh.model.mesh.getElements(2, f)
                for etype, nodes in zip(etypes, enodes):
                    if etype != 2:      # 线性三角形
                        continue
                    for k in range(0, len(nodes), 3):
                        tris.append(gdstk.Polygon(
                            [xy[int(n)] for n in nodes[k:k + 3]]))
            if not tris:
                raise QuantumDslError(
                    f"build_gds: surface group {phys.name!r} produced no "
                    f"triangles — empty/degenerate geometry")
            for poly in gdstk.boolean(tris, [], "or",
                                      layer=layer, datatype=dtype):
                cell.add(poly)

    # GDSII 单多边形上限 8190 点 (gdstk 默认 199 会把长圆弧蛇形切成几十片; 几何不变但一岛一多边形更好查)。
    lib.write_gds(str(out), max_points=8190)
    return out


def render_gds_png(gds_path, out, jj_layers=(), px_per_um=None, bbox=None) -> Path:
    """GDS → PNG。``jj_layers`` 的多边形画品红, 其余一律金属。``px_per_um=None`` →
    长边 2000 px; ``bbox=((x0, y0), (x1, y1))`` µm 裁剪, 默认整个 cell。"""
    import gdstk
    from PIL import Image, ImageDraw

    cell = gdstk.read_gds(str(gds_path)).top_level()[0]
    polys = cell.get_polygons(apply_repetitions=True, include_paths=True, depth=None)
    if not polys:
        raise QuantumDslError(f"render_gds_png: {gds_path} has no polygons")
    jj_layers = set(jj_layers)
    metal = [p for p in polys if p.layer not in jj_layers]
    (x0, y0), (x1, y1) = bbox or cell.bounding_box()
    s = px_per_um or 2000 / max(x1 - x0, y1 - y0)
    img = Image.new("RGB", (int((x1 - x0) * s) + 1, int((y1 - y0) * s) + 1), _METAL)
    draw = ImageDraw.Draw(img)

    def px(pts):
        return [((x - x0) * s, (y1 - y) * s) for x, y in pts]

    for gap in gdstk.boolean(gdstk.rectangle((x0, y0), (x1, y1)), metal, "not"):
        draw.polygon(px(gap.points), fill=_SUBSTRATE)
    for p in polys:
        if p.layer in jj_layers:
            draw.polygon(px(p.points), fill=_JJ)
    out = Path(out)
    img.save(out)
    return out
