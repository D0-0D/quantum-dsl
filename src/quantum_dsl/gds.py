# -*- coding: utf-8 -*-
"""GDS 分叉 (契约 N4): ``.geo`` → GDS, µm verbatim, 旁路网格。

坐标 **µm 逐字** (gdstk Library ``unit=1e-6``), 不缩放 (SPEC「不双重缩放」)。
映射 = meta ``gds.by_role`` (role → {layer, datatype}); 不在 by_role 里的
role 不进 GDS (by_role 就是选择机制 —— jj 要进 GDS 就映射 jj)。

面 → 多边形走 gmsh 2D 三角化 + gdstk 布尔并 (逐面): 对任意 OCC 面 (含布尔
差挖出的带孔 ground) 都稳健; 直边多边形的角点是网格顶点, 逐字保真。
gmsh/gdstk 惰性 import (N0)。
"""

from __future__ import annotations

from pathlib import Path

from .errors import QuantumDslError
from .geo import parse_physical_name

__all__ = ["build_gds"]


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
