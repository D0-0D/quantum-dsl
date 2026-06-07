# -*- coding: utf-8 -*-
"""DSL → GDSII adapter (Layer-2 ``.geo`` → ``chip.gds``, M1 pivot).

把作者手写的 native Gmsh ``.geo`` (微米) 的 **2D 面轮廓** 直接导出成 GDSII,
**绕过 3D mesh** (the GDS branch reads surface outlines from the .geo model in
MICRONS and writes them verbatim — NO SI scaling)。

唯一耦合 = ``.geo`` 实体上的结构化 Physical 名 ``<role>::<layer>::<component>::
<primitive>`` (见 ``_gmsh_geo_source``)。本分支只取 surface role ∈
``{metal, ground, jj}``; ``port`` / ``symmetry`` (1D marker) 跳过。

单位契约 (cross-cutting, 见 plan §critical-unit):
- ``.geo`` 以微米书写; 经 ``load_geo(scale_to_si=False)`` 读出的轮廓即微米。
- ``gdstk.Library(unit=1e-6, precision=1e-9)`` — 微米透传 (100µm 特征 → 用户
  坐标 extent 100.0)。绝不在 GDS 侧做 SI 缩放。

session 生命周期: ``build_gds`` 用 ``_did_initialize`` ownership guard 拥有
gmsh session (镜像 ``gmsh_adapter``), 只 finalize 自己 initialize 的 session。

允许 import: ``gdstk`` (惰性), ``gmsh`` (经 ``_gmsh_geo_source``), 标准库,
本包 ``_gmsh_geo_source`` / ``_gds_layers`` / ``schema`` / ``errors``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from .errors import DesignDslError
from ._gds_layers import (
    GDS_LAYER_MAP,
    GDS_EMIT_ROLES,
    resolve_gds_layer,
    normalize_layer_map,
)
from . import _gmsh_geo_source as _geo

try:
    import gdstk
except ImportError:  # pragma: no cover — exercised on lite installs
    gdstk = None

try:
    import gmsh
except ImportError:  # pragma: no cover
    gmsh = None


__all__ = [
    "GdsOptions",
    "GdsResult",
    "build_gds",
    "verify_roundtrip",
]


# ---------------------------------------------------------------------------
# Options + Result (frozen dataclasses, codebase style)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GdsOptions:
    """gdstk library / 导出选项 (镜像 sidecar ``simulation.gmsh.gds`` 块)。

    单位默认 µm 透传: ``unit=1e-6, precision=1e-9``。``arc_tol_um`` 是弧线采样
    弦高容差 (微米, 模型当前单位)。``union_same_layer`` 为 True 时同 GDS 层的
    多边形做并集 (M1 默认对 ground 合并, 减少碎片)。
    """

    lib_name: str = "chip"
    top_cell: str = "chip"
    unit: float = 1e-6
    precision: float = 1e-9
    arc_tol_um: float = 0.01
    union_same_layer: bool = True

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> "GdsOptions":
        """从 sidecar ``gds`` 块 (或部分覆盖 dict) 构造, 缺省取默认。

        只取与库导出相关的键 (``lib_name``/``top_cell``/``unit``/``precision``/
        ``arc_tol_um``/``union_same_layer``); 层映射键 (``by_*``) 由
        ``_gds_layers`` 处理, 这里忽略。
        """
        if not data:
            return cls()
        return cls(
            lib_name=str(data.get("lib_name", cls.lib_name)),
            top_cell=str(data.get("top_cell", cls.top_cell)),
            unit=float(data.get("unit", cls.unit)),
            precision=float(data.get("precision", cls.precision)),
            arc_tol_um=float(data.get("arc_tol_um", cls.arc_tol_um)),
            union_same_layer=bool(
                data.get("union_same_layer", cls.union_same_layer)),
        )


@dataclass(frozen=True)
class GdsResult:
    """``build_gds`` 出参。

    - ``gds_path``: 写出的 ``.gds`` 路径 (``output_path=None`` 时为 None,
      但 polygons 仍在内存里, 可 ``verify_roundtrip`` 前先写)。
    - ``polygons_by_layer``: ``{(gds_layer, gds_datatype): polygon_count}``。
    - ``bbox_um``: top cell 包围盒 ``(xmin, ymin, xmax, ymax)`` (微米)。
    - ``layer_map``: 实际生效的 sidecar gds 块 (规范化后), 供下游 / 测试核对。
    """

    gds_path: Optional[Path]
    polygons_by_layer: dict[tuple[int, int], int]
    bbox_um: tuple[float, float, float, float]
    layer_map: dict[str, Any] = field(default_factory=dict)
    source_geo: Optional[Path] = None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _require_gdstk() -> None:
    if gdstk is None:  # pragma: no cover
        raise ImportError(
            "gdstk required for GDS export (pip install 'quantum_dsl[gds]').")


def _polygon_area(ring: list[list[float]]) -> float:
    """shoelace |面积| (微米²) — 用于 round-trip 面积核对。"""
    n = len(ring)
    if n < 3:
        return 0.0
    acc = 0.0
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        acc += x0 * y1 - x1 * y0
    return abs(acc) * 0.5


# ---------------------------------------------------------------------------
# build_gds — main entry point
# ---------------------------------------------------------------------------

def build_gds(source: Union[str, Path],
              *,
              output_path: Optional[Union[str, Path]] = None,
              layer_map: Optional[dict[str, Any]] = None,
              options: Optional[Union[dict[str, Any], GdsOptions]] = None
              ) -> GdsResult:
    """从 native ``.geo`` (微米) 导出 GDSII (绕过 3D mesh)。

    Args:
        source: ``.geo`` 文件路径。经 ``load_geo(scale_to_si=False)`` 读出
            微米轮廓 (gdstk ``unit=1e-6`` 透传)。**绝不** SI 缩放。
        output_path: ``.gds`` 输出路径; ``None`` 时不落盘 (``gds_path=None``,
            但 polygons 已在 lib 内存, 可先写后 verify)。
        layer_map: sidecar ``simulation.gmsh.gds`` 块 (层映射 + 库设置)。覆盖
            优先级 by_name > by_role > by_layer > 内置默认。
        options: 库导出选项 (``GdsOptions`` 或 dict); 缺省取 ``layer_map`` 中
            的库键 (lib_name/top_cell/unit/precision/...), 再回落默认。

    Returns:
        ``GdsResult``。

    Raises:
        DesignDslError: ``.geo`` 解析失败 / 轮廓退化 / 层映射非法。
        ImportError: gdstk / gmsh 缺失。
    """
    _require_gdstk()
    if gmsh is None:  # pragma: no cover
        raise ImportError("gmsh required for .geo ingest (GDS branch).")

    source_path = Path(source)
    lm = normalize_layer_map(layer_map)

    # 库导出选项: 显式 options 优先, 否则从 layer_map (gds 块) 取库键。
    if isinstance(options, GdsOptions):
        opts = options
    elif isinstance(options, dict):
        opts = GdsOptions.from_dict(options)
    else:
        opts = GdsOptions.from_dict(lm)

    # session ownership: 镜像 gmsh_adapter — 只 finalize 我们 initialize 的。
    _did_initialize = not gmsh.isInitialized()
    try:
        # load_geo 在 gmsh 未初始化时会自行 initialize; 微米直读 (no SI scale)。
        geo_surfaces = _geo.load_geo(source_path, scale_to_si=False)

        lib = gdstk.Library(name=opts.lib_name, unit=opts.unit,
                            precision=opts.precision)
        cell = lib.new_cell(opts.top_cell)

        # 先按 GDS (layer, datatype) 聚合多边形, 便于可选的同层并集。
        by_gds: dict[tuple[int, int], list] = {}

        for surf in geo_surfaces:
            if surf.role not in GDS_EMIT_ROLES:
                # port / symmetry markers — 不进 GDS。
                continue
            # 防御: 命名层产物 (*_sfs / vacuum*) 不会作为作者 .geo 面名出现,
            # 但若出现则跳过。
            if surf.primitive.endswith("_sfs") or \
                    surf.component.startswith("vacuum") or \
                    surf.primitive.startswith("vacuum"):
                continue

            gds_layer, gds_dt = resolve_gds_layer(
                surf.role, surf.layer, surf.component, surf.primitive,
                layer_map=lm)
            bucket = by_gds.setdefault((gds_layer, gds_dt), [])

            for ent in surf.entities:
                exterior, holes = _geo.surface_outline_um(
                    ent, arc_tol_um=opts.arc_tol_um)
                if len(exterior) < 3:
                    raise DesignDslError(
                        f"gds: surface {ent} of "
                        f"{surf.role}::{surf.layer}::{surf.component}::"
                        f"{surf.primitive} has a degenerate exterior "
                        f"({len(exterior)} pts).")
                poly = gdstk.Polygon(exterior, layer=gds_layer,
                                     datatype=gds_dt)
                if holes:
                    cut = gdstk.boolean(
                        poly,
                        [gdstk.Polygon(h) for h in holes],
                        "not", layer=gds_layer, datatype=gds_dt)
                    bucket.extend(cut)
                else:
                    bucket.append(poly)

        # 可选同层并集 (默认对所有发出的层做 union — 见 GdsOptions)。
        polygons_by_layer: dict[tuple[int, int], int] = {}
        for (gds_layer, gds_dt), polys in by_gds.items():
            if not polys:
                continue
            if opts.union_same_layer and len(polys) > 1:
                polys = gdstk.boolean(polys, [], "or",
                                      layer=gds_layer, datatype=gds_dt)
            for p in polys:
                cell.add(p)
            polygons_by_layer[(gds_layer, gds_dt)] = (
                polygons_by_layer.get((gds_layer, gds_dt), 0) + len(polys))

        # top cell bbox (微米). 空 cell → 退化 bbox。
        bb = cell.bounding_box()
        if bb is None:
            bbox_um: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
        else:
            (xmin, ymin), (xmax, ymax) = bb
            bbox_um = (float(xmin), float(ymin), float(xmax), float(ymax))

        gds_path: Optional[Path] = None
        if output_path is not None:
            gds_path = Path(output_path)
            gds_path.parent.mkdir(parents=True, exist_ok=True)
            lib.write_gds(str(gds_path))

        return GdsResult(
            gds_path=gds_path,
            polygons_by_layer=polygons_by_layer,
            bbox_um=bbox_um,
            layer_map=lm,
            source_geo=source_path,
        )
    finally:
        if _did_initialize and gmsh is not None and gmsh.isInitialized():
            gmsh.finalize()


# ---------------------------------------------------------------------------
# verify_roundtrip — read back the written GDS and compare per-layer area/bbox
# ---------------------------------------------------------------------------

def verify_roundtrip(result: GdsResult,
                     *,
                     rel_area_tol: float = 1e-3,
                     bbox_grid_tol: float = 1.0
                     ) -> dict[str, Any]:
    """读回写出的 ``.gds`` 并与 ``result`` 比对 per-layer 总面积 + bbox。

    比对策略:
    - 每个 ``(layer, datatype)`` 的总多边形面积 (gdstk ``Polygon.area()``,
      用户坐标 = 微米) 相对误差 ≤ ``rel_area_tol``。
    - top cell bbox 各坐标差 ≤ ``bbox_grid_tol`` grid unit (微米)。

    "源" 面积/包围盒由再次加载 ``.geo`` 并对每个发出面跑 shoelace (外环 − 内孔)
    得到 — 这与写出路径走同一条 ``surface_outline_um`` 提取, 故是几何级核对
    (而非简单回读自身)。

    Returns:
        ``{"ok": bool, "per_layer": {(l,dt): {...}}, "bbox": {...},
           "issues": [...]}``。
    """
    _require_gdstk()
    if result.gds_path is None:
        raise DesignDslError(
            "verify_roundtrip needs a written GDS (build_gds with output_path).")
    if gmsh is None:  # pragma: no cover
        raise ImportError("gmsh required for verify_roundtrip source areas.")

    gds_path = Path(result.gds_path)
    if not gds_path.is_file():
        raise DesignDslError(f"gds file not found for round-trip: {gds_path}")

    # --- 1) 读回 GDS, 按 (layer, datatype) 累计面积 + 全局 bbox -------------
    lib = gdstk.read_gds(str(gds_path))
    top_cells = lib.top_level()
    if not top_cells:
        raise DesignDslError(f"gds file {gds_path} has no top-level cell.")
    top = top_cells[0]

    read_area: dict[tuple[int, int], float] = {}
    for poly in top.polygons:
        key = (int(poly.layer), int(poly.datatype))
        read_area[key] = read_area.get(key, 0.0) + abs(poly.area())
    read_bb = top.bounding_box()
    if read_bb is None:
        read_bbox = (0.0, 0.0, 0.0, 0.0)
    else:
        (rxmin, rymin), (rxmax, rymax) = read_bb
        read_bbox = (float(rxmin), float(rymin), float(rxmax), float(rymax))

    # --- 2) 源面积: 重新加载 .geo, 对每个发出面跑 shoelace (外环 − 内孔) -----
    #   这是与回读独立的几何级核对 (直接在 µm 模型上提取轮廓), 能抓 unit /
    #   SI-scaling 类错误。layer_map 用 result 记录的规范化 sidecar gds 块。
    if result.source_geo is None:
        raise DesignDslError(
            "verify_roundtrip needs result.source_geo (the .geo path) to "
            "recompute source areas; build_gds populates it.")
    lm = result.layer_map or {}
    opts = GdsOptions.from_dict(lm)

    #   按与 build_gds 完全一致的语义重建源多边形 (外环 − 内孔 boolean, 再按
    #   union_same_layer 同层并集), 故面积是同一集合语义下的独立核对: 仍直读 µm
    #   轮廓 (能抓 SI-scaling / unit 错误), 但避免把重叠同层面的面积重复计数。
    src_by_gds: dict[tuple[int, int], list] = {}
    _did_initialize = not gmsh.isInitialized()
    try:
        geo_surfaces = _geo.load_geo(result.source_geo, scale_to_si=False)
        for surf in geo_surfaces:
            if surf.role not in GDS_EMIT_ROLES:
                continue
            if surf.primitive.endswith("_sfs") or \
                    surf.component.startswith("vacuum") or \
                    surf.primitive.startswith("vacuum"):
                continue
            gds_layer, gds_dt = resolve_gds_layer(
                surf.role, surf.layer, surf.component, surf.primitive,
                layer_map=lm)
            bucket = src_by_gds.setdefault((gds_layer, gds_dt), [])
            for ent in surf.entities:
                exterior, holes = _geo.surface_outline_um(
                    ent, arc_tol_um=opts.arc_tol_um)
                poly = gdstk.Polygon(exterior, layer=gds_layer,
                                     datatype=gds_dt)
                if holes:
                    bucket.extend(gdstk.boolean(
                        poly, [gdstk.Polygon(h) for h in holes], "not",
                        layer=gds_layer, datatype=gds_dt))
                else:
                    bucket.append(poly)
    finally:
        if _did_initialize and gmsh is not None and gmsh.isInitialized():
            gmsh.finalize()

    src_area: dict[tuple[int, int], float] = {}
    for key, polys in src_by_gds.items():
        gds_layer, gds_dt = key
        if opts.union_same_layer and len(polys) > 1:
            polys = gdstk.boolean(polys, [], "or",
                                  layer=gds_layer, datatype=gds_dt)
        src_area[key] = sum(abs(p.area()) for p in polys)

    # --- 3) 比对 ------------------------------------------------------------
    issues: list[str] = []
    per_layer: dict[tuple[int, int], dict[str, float]] = {}
    keys = set(read_area) | set(src_area)
    for key in sorted(keys):
        a_read = read_area.get(key, 0.0)
        a_src = src_area.get(key, 0.0)
        denom = max(abs(a_src), abs(a_read), 1e-30)
        rel = abs(a_read - a_src) / denom
        per_layer[key] = {
            "read_area": a_read, "src_area": a_src, "rel_area_err": rel}
        if rel > rel_area_tol:
            issues.append(
                f"layer {key}: area mismatch read={a_read:.6g} "
                f"src={a_src:.6g} rel={rel:.3e} > {rel_area_tol:.1e}")

    bbox_diffs = [abs(r - e) for r, e in zip(read_bbox, result.bbox_um)]
    bbox_ok = all(d <= bbox_grid_tol for d in bbox_diffs)
    if not bbox_ok:
        issues.append(
            f"bbox mismatch read={read_bbox} expected={result.bbox_um} "
            f"diffs={bbox_diffs} > {bbox_grid_tol} grid")

    return {
        "ok": not issues,
        "per_layer": per_layer,
        "bbox": {"read": read_bbox, "expected": result.bbox_um,
                 "diffs": bbox_diffs, "ok": bbox_ok},
        "issues": issues,
    }
