# -*- coding: utf-8 -*-
"""Native Gmsh ``.geo`` ingest — Layer 2 geometry source (M1 pivot).

把作者手写的 OpenCASCADE ``.geo`` 几何接入既有 Gmsh 流水线 + GDS 后端。
唯一耦合 = 每个实体上的结构化 Physical 名 (``::`` 分隔):

    <role>::<layer>::<component>::<primitive>

- role ∈ ``{metal, ground, jj, substrate}`` (2D 面) 或 ``{port, symmetry}`` (1D marker)。
- layer = ``simulation.gmsh.layer_stack`` 的 int key。
- component / primitive = 身份标识 → 稳定的 GDS / Palace 名 + ports 查表。

本模块只读取 / 翻译这些名字, 不做注册 (注册仍由 fragment 之后的
``assign_physical_groups`` 统一完成, 保证与 YAML 路径输出名字节一致)。

单位约定 (cross-cutting 契约):
- ``.geo`` 以 **微米 (µm)** 书写。
- GDS 分支: ``scale_to_si=False`` — 直接读 µm 轮廓 (gdstk unit=1e-6 透传)。
- MESH 分支: ``scale_to_si=True`` — ``gmsh.merge`` 之后立刻 ``occ.dilate`` µm→m,
  使后续所有 SI-based 阶段无改动复用。

session 生命周期: ``load_geo`` **不** finalize, 也不在内部 initialize-and-own
(除非调用方未初始化)。调用方 (build_gds / mesh 分支) 拥有 session, load 后
模型仍然在内存中存活。

允许 import: ``gmsh``, ``numpy``, 标准库, 本包 ``schema`` / ``errors`` /
``_gmsh_physical`` / ``_gmsh_geometry`` / ``_gmsh_layers``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import numpy as np

from .errors import DesignDslError
from .schema import GEO_ROLES, GEO_SURFACE_ROLES, GEO_MARKER_ROLES
from ._gmsh_geometry import GeomTracker
from ._gmsh_layers import render_layer_grounds

try:
    import gmsh
except ImportError:  # pragma: no cover — exercised on lite installs
    gmsh = None


__all__ = [
    "GeoSurface",
    "load_geo",
    "split_geo_name",
    "lint_geo_names",
    "surface_outline_um",
    "populate_tracker_from_geo",
    "compute_chip_bbox_from_geo",
    "SI_PER_INTERNAL",
]

# µm → m. Mirrors ``_units.SI_PER_INTERNAL`` (kept local so the dilate factor
# in the mesh branch is byte-identical to the project SI boundary).
SI_PER_INTERNAL = 1e-6

# DEFAULT substrate-top ε-nudge below a carved metal ground (SI metres). The
# default 1 µm keeps the metal/ground void bottom a free, non-coincident face,
# which the carve/fragment/resolve path has always relied on (a centered-pad
# fixture e.g. tiny_chip otherwise mis-resolves under exact coplanarity).
# Physically a vacuum gap under the metal depresses capacitance (~30% at 1 µm),
# so accuracy-critical designs override it toward 0 via the meta key
# ``simulation.gmsh.substrate_gap_um`` (e.g. qm4q uses 0 = coplanar, the
# physically-correct metal-on-substrate stack; fragment scales to µm + the mesher
# falls back to HXT so the coplanar interface still builds).
CARVED_GROUND_SUBSTRATE_GAP_SI = 1e-6


# ---------------------------------------------------------------------------
# GeoSurface — one authored Physical group (SHARED PYTHON API CONTRACT)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GeoSurface:
    """一个作者标注的 Physical group, 已解析成结构化身份。

    ``dim`` = 2 (surface role) 或 1 (marker role); ``entities`` 是该 physical
    group 的几何实体 tag 列表 (dim-2 surface tags / dim-1 curve tags)。
    """

    role: str
    layer: int
    component: str
    primitive: str
    dim: int
    entities: list[int]


# ---------------------------------------------------------------------------
# Physical 名解析 + lint
# ---------------------------------------------------------------------------

def split_geo_name(name: str) -> tuple[str, int, str, str]:
    """把 ``"<role>::<layer>::<component>::<primitive>"`` 拆成 4-tuple。

    校验:
    - 恰好 4 段 (``::`` 分隔);
    - role ∈ ``GEO_ROLES``;
    - layer 可转 int。

    任何不满足都 ``raise DesignDslError`` 并点名出错的 group。
    """
    parts = name.split("::")
    if len(parts) != 4:
        raise DesignDslError(
            f"geo physical name {name!r} must have exactly 4 '::'-delimited "
            f"fields '<role>::<layer>::<component>::<primitive>', got "
            f"{len(parts)} field(s)."
        )
    role, layer_str, component, primitive = parts
    if role not in GEO_ROLES:
        raise DesignDslError(
            f"geo physical name {name!r}: unknown role {role!r} "
            f"(expected one of {sorted(GEO_ROLES)})."
        )
    try:
        layer = int(layer_str)
    except (TypeError, ValueError) as exc:
        raise DesignDslError(
            f"geo physical name {name!r}: layer field {layer_str!r} is not an "
            f"integer."
        ) from exc
    if not component:
        raise DesignDslError(
            f"geo physical name {name!r}: component field is empty.")
    if not primitive:
        raise DesignDslError(
            f"geo physical name {name!r}: primitive field is empty.")
    return role, layer, component, primitive


def lint_geo_names(names: list[str]) -> list[str]:
    """返回 ``names`` 中不符合 ``::`` 约定的名字 (不抛异常)。

    供加载器 / CLI 在解析前先报告所有问题名, 而非首个就 raise。
    """
    bad: list[str] = []
    for name in names:
        try:
            split_geo_name(name)
        except DesignDslError:
            bad.append(name)
    return bad


# ---------------------------------------------------------------------------
# gmsh session helpers (mirror gmsh_adapter._gmsh_initialize ownership guard)
# ---------------------------------------------------------------------------

def _require_gmsh() -> None:
    if gmsh is None:  # pragma: no cover
        raise ImportError("gmsh required for .geo ingest")


# gmsh's .geo parser keeps compiled ``Macro`` definitions in a PROCESS-GLOBAL
# table that survives both ``gmsh.clear()`` AND ``finalize()`` + ``initialize()``,
# while those calls DO reset parser constants.  So a re-``Include`` of qlib.geo
# after a clear/finalize raises "Redefinition of function".  The robust fix is
# to NEVER clear/finalize the parser between loads — instead switch to a fresh,
# uniquely-named ``gmsh.model`` (the include-guard constant in qlib.geo then
# stays alive, so the guarded ``Macro`` block is skipped on the 2nd Include).
# This also keeps a caller's pre-existing model intact (we don't clobber it).
_MODEL_COUNTER = 0


# ---------------------------------------------------------------------------
# load_geo — gmsh.merge + (optional) dilate + enumerate physical groups
# ---------------------------------------------------------------------------

def load_geo(path: Union[str, Path], *,
             scale_to_si: bool = False) -> list[GeoSurface]:
    """加载一个 ``.geo`` 文件并枚举其 Physical group。

    步骤:
    1. (若 gmsh 未初始化) initialize; 否则 ``clear`` 后用一个新 model。
       — 注意: 调用方拥有 session; 本函数 **不** finalize, 模型在返回后存活。
    2. ``gmsh.merge(path)`` + ``occ.synchronize()``。
    3. 若 ``scale_to_si``: ``occ.dilate(getEntities(), 0,0,0, 1e-6,1e-6,1e-6)``
       + sync, 把整模型 µm→m (mesh 分支用)。
    4. 枚举 dim=1 与 dim=2 的 physical group → ``GeoSurface`` 列表。

    Args:
        path: ``.geo`` 文件路径。
        scale_to_si: True 时 dilate µm→m (mesh 分支); False 时保持 µm
            (GDS 分支直读轮廓)。

    Returns:
        ``list[GeoSurface]`` — 每个作者标注的 ``::`` physical group 一条。

    Raises:
        DesignDslError: 文件无法打开, 或存在不符合 ``::`` 约定的 physical 名。
    """
    global _MODEL_COUNTER
    _require_gmsh()
    path = Path(path)
    if not path.is_file():
        raise DesignDslError(f"geo file not found: {path}")

    # session ownership: mirror gmsh_adapter ownership guard — initialize only
    # if the caller hasn't.  We do NOT clear/finalize the parser (that would
    # drop qlib.geo's include-guard constant while keeping its compiled macros,
    # breaking a re-Include).  Instead each load uses a fresh, uniquely-named
    # model so a caller's pre-existing model stays intact and parser state
    # (macros + guard constant) is preserved.  load_geo never finalizes — the
    # caller owns the session lifecycle (model stays live after we return).
    if not gmsh.isInitialized():
        gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    _MODEL_COUNTER += 1
    model_name = f"geo_source_{_MODEL_COUNTER}"
    gmsh.model.add(model_name)
    gmsh.model.setCurrent(model_name)

    try:
        gmsh.merge(str(path))
    except Exception as exc:  # gmsh raises bare Exception on parse failure
        raise DesignDslError(f"failed to merge geo file {path}: {exc}") from exc
    gmsh.model.occ.synchronize()

    # IMPORTANT: enumerate physical groups *before* any dilate.  ``occ.dilate``
    # + ``synchronize`` preserves entity TAGS but WIPES physical-group
    # assignments on the OCC model.  So we snapshot (dim, name, entity-tags)
    # now; the tags stay valid across the dilate (geometry moves, tags don't).
    raw: list[tuple[int, str, list[int]]] = []
    for dim in (1, 2):
        for (d, tag) in gmsh.model.getPhysicalGroups(dim):
            name = gmsh.model.getPhysicalName(d, tag)
            ents = [int(e)
                    for e in gmsh.model.getEntitiesForPhysicalGroup(d, tag)]
            raw.append((d, name, ents))

    if scale_to_si:
        ents_all = gmsh.model.getEntities()
        if ents_all:
            gmsh.model.occ.dilate(
                ents_all, 0.0, 0.0, 0.0,
                SI_PER_INTERNAL, SI_PER_INTERNAL, SI_PER_INTERNAL)
            gmsh.model.occ.synchronize()

    names = [name for (_d, name, _e) in raw]
    bad = lint_geo_names(names)
    if bad:
        raise DesignDslError(
            f"geo file {path} has physical name(s) that violate the "
            f"'<role>::<layer>::<component>::<primitive>' convention: {bad}"
        )

    surfaces: list[GeoSurface] = []
    seen: set[tuple[str, int, str, str]] = set()
    for (d, name, ents) in raw:
        role, layer, component, primitive = split_geo_name(name)
        # dim sanity vs role kind
        if role in GEO_SURFACE_ROLES and d != 2:
            raise DesignDslError(
                f"geo physical name {name!r}: surface role {role!r} must tag a "
                f"2D Physical Surface, but it is declared at dim={d}."
            )
        if role in GEO_MARKER_ROLES and d != 1:
            raise DesignDslError(
                f"geo physical name {name!r}: marker role {role!r} must tag a "
                f"1D Physical Curve, but it is declared at dim={d}."
            )
        key = (role, layer, component, primitive)
        if key in seen:
            raise DesignDslError(
                f"geo file {path}: duplicate physical name {name!r}.")
        seen.add(key)
        surfaces.append(GeoSurface(
            role=role, layer=layer, component=component,
            primitive=primitive, dim=d, entities=list(ents)))
    return surfaces


# ---------------------------------------------------------------------------
# surface_outline_um — read a 2D surface's exterior + holes (CURRENT units)
# ---------------------------------------------------------------------------

def _curve_points_um(dim: int, curve: int, *,
                     arc_tol: float) -> list[tuple[float, float]]:
    """采样一条 (有符号方向的) 边界曲线, 返回 head→tail 的完整 xy 点序列。

    - ``curve`` 带符号: 正 = 参数递增方向, 负 = 递减方向。
    - Line: 取两端点 (fast path)。
    - 其它 (Circle / Ellipse / Spline / BSpline): 按 ``arc_tol`` 均匀采样
      (M1 弧线保真度有限, 见模块 docstring)。

    返回 ``[head, ..., tail]`` (含两端点); 拼接时由 ``_assemble_loops`` 去重。
    """
    tag = abs(curve)
    reverse = curve < 0
    ctype = gmsh.model.getType(dim, tag)
    pmin_arr, pmax_arr = gmsh.model.getParametrizationBounds(dim, tag)
    pmin = float(pmin_arr[0])
    pmax = float(pmax_arr[0])

    if ctype == "Line":
        params = [pmin, pmax]
    else:
        # 估算采样段数: 用半参数处弦长 + arc_tol 粗略定 N。
        # 退化策略: 至少 8 段, 上限 256 段。
        try:
            length = abs(pmax - pmin)
            p_mid = gmsh.model.getValue(dim, tag, [(pmin + pmax) * 0.5])
            p_a = gmsh.model.getValue(dim, tag, [pmin])
            chord = float(np.linalg.norm(
                np.array(p_mid[:2]) - np.array(p_a[:2]))) or length
        except Exception:
            chord = abs(pmax - pmin)
        n = int(max(8, min(256, np.ceil(2.0 * chord / max(arc_tol, 1e-9)) + 1)))
        params = list(np.linspace(pmin, pmax, n))

    pts: list[tuple[float, float]] = []
    for u in params:
        v = gmsh.model.getValue(dim, tag, [float(u)])
        pts.append((float(v[0]), float(v[1])))
    if reverse:
        pts.reverse()
    return pts


def _assemble_loops(curves: list[tuple[int, int]], *,
                    arc_tol: float, weld_tol: float
                    ) -> list[list[tuple[float, float]]]:
    """把 (有向) 边界曲线 head→tail 拼成一个或多个闭合环。

    ``curves`` 来自 ``getBoundary(..., oriented=True)``: 每个外环 / 内孔的
    曲线连续排列且方向一致。顺序拼接, 当当前曲线尾端点回到本环起点
    (距离 < weld_tol) 时收一个环。每个环 **不** 重复首尾点 (开放多边形)。
    """
    loops: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for (dim, curve) in curves:
        seg = _curve_points_um(dim, curve, arc_tol=arc_tol)
        if len(seg) < 2:
            continue
        if not current:
            current.extend(seg)
        else:
            # weld: skip the head of seg if it coincides with current tail.
            if _close(current[-1], seg[0], weld_tol):
                current.extend(seg[1:])
            else:
                current.extend(seg)
        # close when the running tail returns to the loop start.
        if len(current) >= 3 and _close(current[-1], current[0], weld_tol):
            current.pop()  # drop the duplicated closing vertex
            loops.append(current)
            current = []
    if len(current) >= 3:
        loops.append(current)
    return loops


def _close(a: tuple[float, float], b: tuple[float, float], tol: float) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _signed_area(loop: list[tuple[float, float]]) -> float:
    """shoelace 有符号面积 (CCW 为正)。"""
    n = len(loop)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x0, y0 = loop[i]
        x1, y1 = loop[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return area * 0.5


def surface_outline_um(entity_tag: int, arc_tol_um: float = 0.01
                       ) -> tuple[list[list[float]], list[list[list[float]]]]:
    """读出一个 2D surface 的外环 + 内孔轮廓, 单位 = **当前模型单位**。

    返回 ``(exterior_xy, [hole_xy, ...])``:
    - ``exterior_xy``: ``[[x, y], ...]`` 闭合多边形 (CCW), 最大 |面积| 的环。
    - holes: 其余环 (内孔), 每个 ``[[x, y], ...]``。

    实现: ``getBoundary([(2, tag)], combined=False, oriented=True)`` → 逐曲线
    采样 (Line 取端点; 弧/样条按 ``arc_tol`` 采样) → head→tail 拼环 →
    shoelace 有符号面积分类 (最大 |area| = 外环, 其余 = 孔)。

    单位: ``arc_tol_um`` 与模型同单位。GDS 分支模型为 µm (scale_to_si=False),
    故 ``arc_tol_um`` 直接是 µm。

    M1: 直线 + 简单孔 **精确**; 曲线 fallback 采样, 弧线 GDS 保真度为后续里程碑。
    """
    _require_gmsh()
    curves = gmsh.model.getBoundary(
        [(2, int(entity_tag))], combined=False, oriented=True)
    if not curves:
        raise DesignDslError(
            f"surface {entity_tag} has no boundary curves (degenerate?).")
    # weld tolerance: a fraction of arc_tol, but floor for numerical noise.
    weld_tol = max(arc_tol_um * 1e-2, 1e-6)
    loops = _assemble_loops(
        [(int(d), int(c)) for (d, c) in curves],
        arc_tol=arc_tol_um, weld_tol=weld_tol)
    if not loops:
        raise DesignDslError(
            f"surface {entity_tag}: failed to assemble any closed boundary loop.")
    # classify by |signed area|
    ranked = sorted(loops, key=lambda lp: abs(_signed_area(lp)), reverse=True)
    exterior_loop = ranked[0]
    holes_loops = ranked[1:]

    def _orient(loop: list[tuple[float, float]], ccw: bool
                ) -> list[list[float]]:
        area = _signed_area(loop)
        if (area < 0 and ccw) or (area > 0 and not ccw):
            loop = list(reversed(loop))
        return [[float(x), float(y)] for (x, y) in loop]

    exterior = _orient(exterior_loop, ccw=True)
    holes = [_orient(h, ccw=False) for h in holes_loops]
    return exterior, holes


# ---------------------------------------------------------------------------
# populate_tracker_from_geo — extrude authored surfaces into GeomTracker
# ---------------------------------------------------------------------------

def populate_tracker_from_geo(geo_surfaces: list[GeoSurface],
                              layer_stack_si: dict[int, dict],
                              tracker: GeomTracker) -> None:
    """把作者标注的 ``GeoSurface`` 翻译进既有 ``GeomTracker`` (SI 模型上)。

    前置条件: 模型已 dilate 到 SI 米 (mesh 分支 ``load_geo(scale_to_si=True)``)。

    映射 (mirror ``render_polygon_primitive`` 的 extrude 尾段):
    - ``metal::N::C::P`` → extrude 该面 ``layer_stack_si[N].thickness`` →
      ``tracker.polys[N][(C, P)]`` (3D volume tags)。
    - ``ground::N::*::*`` → extrude → ``tracker.layer_ground[N]`` (3D volume)。
    - ``substrate::N::*::*`` → extrude → ``tracker.layer_ground[N]`` (dielectric)。
    - ``jj::N::C::P`` → **不** extrude, 留在 metal 层 z (translate 到层中心),
      记 ``tracker.juncs[N][(C, P)]`` (2D surface)。
    - marker (port / symmetry): M1 不在此处理 (端口 ::edge 推迟)。

    若某 dielectric layer 没有 ``substrate::`` 面被标注, 由调用方在 bbox
    可用后用 ``render_layer_grounds`` 兜底 (见 ``ensure_dielectric_substrates``)。
    """
    _require_gmsh()
    for surf in geo_surfaces:
        if surf.role in GEO_MARKER_ROLES:
            continue
        layer = surf.layer
        if layer not in layer_stack_si:
            raise DesignDslError(
                f"geo surface {surf.role}::{surf.layer}::{surf.component}::"
                f"{surf.primitive} references layer {layer} not present in "
                f"layer_stack.")
        spec = layer_stack_si[layer]
        z_si = float(spec.get("z", 0.0))
        thickness_si = float(spec["thickness"])

        if surf.role == "jj":
            # JJ 是集总元件 (lumped element), mesh 分支 **不** 把它作为导体面
            # 网格化:
            #   - 物理上: Electrostatic 电容提取里, 把 JJ 当导体桥会把它连接的
            #     两块焊盘短路, C 矩阵失去意义;
            #   - 网格上: 一个嵌在薄金属 slab 中面 (z=thickness/2) 的 2D 面, 在
            #     size-field 强制细化下会让 3D mesher 报 "overlapping facets"
            #     (薄面内嵌薄体, 厚度方向无法生成有效四面体)。
            # 因此从 OCC 模型中移除 JJ 面 (GDS 分支独立 load_geo, 仍把 JJ 输出到
            # 掩模层)。未来 Eigenmode/Driven 里 JJ 作为 lumped port 边界单独处理。
            ent_dimtags = [(2, ent) for ent in surf.entities]
            if ent_dimtags:
                gmsh.model.occ.remove(ent_dimtags, recursive=True)
            continue

        # metal / ground / substrate → extrude the dim-2 surface to a volume.
        for ent in surf.entities:
            extruded = gmsh.model.occ.extrude(
                [(2, ent)], dx=0.0, dy=0.0, dz=thickness_si)
            volume_tags = [tag for (dim, tag) in extruded if dim == 3]
            if not volume_tags:
                raise DesignDslError(
                    f"OCC extrude produced no volume for "
                    f"{surf.role}::{surf.layer}::{surf.component}::"
                    f"{surf.primitive} (surface {ent}).")
            volume = volume_tags[0]
            if surf.role == "metal":
                # Approach A: a metal terminal is a PEC equipotential — it is NOT
                # meshed as a conductor. Stash the extruded solid; carve_conductors
                # later cuts it OUT of the vacuum box so the cavity wall becomes an
                # EXTERIOR Terminal boundary (Palace's invariant: a Terminal face
                # must have ≤1 adjacent element). Meshing it as a slab makes the
                # _sfs face INTERIOR (2 elements) → MFEM rejects it at solve time.
                tracker.conductor_solids.setdefault(layer, {}).setdefault(
                    (surf.component, surf.primitive), []).append(volume)
            elif surf.role == "ground":
                # Approach A (M5a): a metal ground sheet is a PEC equipotential
                # too — carve it OUT of the vacuum like a terminal so its cavity
                # wall is an EXTERIOR Ground boundary.  Meshing it as a coplanar
                # slab makes the wall INTERIOR (2 elements) → MFEM rejects it,
                # and even mesh GENERATION fails ("overlapping facets") once the
                # sheet shares the z=0 plane with the substrate.  Stash per layer;
                # carve_conductors consumes it.
                tracker.ground_solids.setdefault(layer, []).append(volume)
            else:  # substrate (dielectric) — stays a meshed body
                tracker.layer_ground.setdefault(layer, []).append(volume)

    gmsh.model.occ.synchronize()


def ensure_dielectric_substrates(geo_surfaces: list[GeoSurface],
                                 layer_stack_si: dict[int, dict],
                                 tracker: GeomTracker,
                                 bbox_si: tuple[float, float, float, float],
                                 substrate_gap_si: float =
                                 CARVED_GROUND_SUBSTRATE_GAP_SI
                                 ) -> None:
    """对没有 ``substrate::`` 面被标注的 dielectric layer, 用 bbox 兜底画衬底。

    复用 ``render_layer_grounds`` (它对每个 layer 画一个 Box → ``layer_ground``)。
    这里只对「dielectric 且 tracker 里还没有体」的 layer 单独调用, 避免重复画
    已被作者显式标注的衬底。
    """
    _require_gmsh()
    authored_layers = {
        s.layer for s in geo_surfaces if s.role in ("substrate", "ground")
    }
    missing: dict[int, dict] = {}
    for layer, spec in layer_stack_si.items():
        if spec.get("kind") != "dielectric":
            continue
        if layer in authored_layers and tracker.layer_ground.get(layer):
            continue
        if tracker.layer_ground.get(layer):
            continue
        missing[layer] = spec
    if missing:
        # Drop the auto-substrate top by ε below the carved metal/ground bottom
        # (z=0) when a metal ground is carved. ε keeps the metal/ground void
        # bottom a FREE face (not coplanar-coincident with the substrate top) —
        # exact coplanarity makes resolve_conductor_faces mis-key a centered
        # terminal vs the ground annulus, and tetgen choke on the coincident
        # footprint.
        # ε is NOT physically free: a vacuum gap under the metal depresses every
        # capacitance (~30% at the 1 µm default). The fix is NOT a smaller ε but
        # ε = 0: set ``simulation.gmsh.substrate_gap_um: 0`` for a physically
        # exact coplanar metal-on-substrate stack (qm4q does). The default stays
        # 1 µm only for backward compatibility with the fixtures that mis-resolve
        # under exact coplanarity — see CARVED_GROUND_SUBSTRATE_GAP_SI.
        # (fragment_everything scales the model for occ.fragment + generate_mesh
        # falls back to HXT, so ε=0 fragments and meshes robustly.)
        if tracker.ground_solids and substrate_gap_si:
            missing = {
                layer: {**spec, "z": float(spec.get("z", 0.0)) - substrate_gap_si}
                for layer, spec in missing.items()
            }
        render_layer_grounds(bbox_si, missing, tracker)
        gmsh.model.occ.synchronize()


# ---------------------------------------------------------------------------
# compute_chip_bbox_from_geo — union getBoundingBox over metal+ground surfaces
# ---------------------------------------------------------------------------

def compute_chip_bbox_from_geo(geo_surfaces: list[GeoSurface],
                               side_buffer_si: float
                               ) -> tuple[float, float, float, float]:
    """从 metal + ground 面的包围盒并集计算 chip XY bbox (含 side_buffer)。

    返回 ``(xmin, ymin, xmax, ymax)``, 单位 = **当前模型单位** (mesh 分支模型
    已 dilate 到 SI 米, 故返回 SI 米; side_buffer_si 同单位)。

    用 ``gmsh.model.getBoundingBox(2, ent)`` 在 metal / ground 面上取并集
    (排除 substrate — 衬底可能由 bbox 反推, 会形成循环依赖)。
    """
    _require_gmsh()
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    for surf in geo_surfaces:
        if surf.role not in ("metal", "ground"):
            continue
        for ent in surf.entities:
            x0, y0, _z0, x1, y1, _z1 = gmsh.model.getBoundingBox(2, ent)
            minx = min(minx, x0)
            miny = min(miny, y0)
            maxx = max(maxx, x1)
            maxy = max(maxy, y1)
    if not np.isfinite(minx):
        raise DesignDslError(
            "geo design has no metal/ground surfaces to compute chip bbox from.")
    return (
        minx - side_buffer_si,
        miny - side_buffer_si,
        maxx + side_buffer_si,
        maxy + side_buffer_si,
    )
