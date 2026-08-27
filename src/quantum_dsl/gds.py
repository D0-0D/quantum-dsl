# -*- coding: utf-8 -*-
"""GDS 分叉 (契约 N4): ``.geo`` → GDS, µm verbatim, 旁路网格。

坐标 **µm 逐字** (gdstk Library ``unit=1e-6``), 不缩放 (SPEC「不双重缩放」)。
映射 = meta ``gds.by_role`` (role → {layer, datatype}); 不在 by_role 里的
role 不进 GDS (by_role 就是选择机制 —— jj 要进 GDS 就映射 jj)。

面 → 多边形走 gmsh 2D 三角化 + gdstk 布尔并 (逐面): 对任意 OCC 面 (含布尔
差挖出的带孔 ground) 都稳健; 直边多边形的角点是网格顶点, 逐字保真。
gmsh/gdstk 惰性 import (N0)。

``render_gds_png``: GDS → PNG 概览 (金属浅 / 衬底深 / jj 品红), build() 随 GDS 一起产
``<stem>.gds.png``。带孔 ground 用 field − metal 布尔取真缝 (PIL 不会填孔)。PIL 惰性 import。
"""

from __future__ import annotations

from pathlib import Path

from .errors import QuantumDslError
from .geo import parse_physical_name

__all__ = ["build_gds", "render_gds_png"]

_METAL, _SUBSTRATE, _JJ = (225, 225, 225), (60, 60, 66), (255, 0, 200)


def build_gds(geo_path, meta, out) -> Path:
    """``.geo`` + Meta → GDS 文件路径。"""
    geo_path = Path(geo_path)
    if not geo_path.is_file():
        raise QuantumDslError(f"build_gds: no such file: {geo_path}")
    by_role = (meta.gds or {}).get("by_role") or {}
    if not by_role:
        raise QuantumDslError(
            "build_gds: meta.gds.by_role is empty — map at least one role "
            "(e.g. metal: {layer: 1, datatype: 0})")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    import gdstk

    from ._gmsh import geo_model

    with geo_model(geo_path) as gmsh:
        groups = []                     # (Physical, [face tags])
        for dim, ptag in gmsh.model.getPhysicalGroups(2):
            phys = parse_physical_name(gmsh.model.getPhysicalName(dim, ptag))
            if phys.role in by_role:
                groups.append((phys, [int(t) for t in
                               gmsh.model.getEntitiesForPhysicalGroup(dim, ptag)]))
        if not groups:
            raise QuantumDslError(
                f"build_gds: no surfaces in {geo_path} match gds.by_role "
                f"roles {sorted(by_role)}")

        # 粗三角化只为提取多边形轮廓 (尺寸=domain 级 → 三角形最少)。
        # gmsh.option 是全局的 (进程级共享 session) — 依赖的选项全部显式设。
        gmsh.option.setNumber("Mesh.MeshSizeMin", 0)
        gmsh.option.setNumber("Mesh.MeshSizeMax", 1e9)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 1)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 1)
        gmsh.option.setNumber("Mesh.ElementOrder", 1)
        gmsh.model.mesh.generate(2)
        tags, coords, _ = gmsh.model.mesh.getNodes()
        xy = {int(t): (coords[3 * i], coords[3 * i + 1])
              for i, t in enumerate(tags)}

        lib = gdstk.Library(name=geo_path.stem, unit=1e-6, precision=1e-9)
        cell = lib.new_cell(geo_path.stem)
        for phys, faces in groups:
            spec = by_role[phys.role]
            layer, dtype = int(spec["layer"]), int(spec.get("datatype", 0))
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

    lib.write_gds(str(out))
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
