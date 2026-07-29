# -*- coding: utf-8 -*-
"""M5a — lower a resolved v3 ``DesignIR`` → a flat, positive-tone native Gmsh ``.geo``.

This is the **emit_geo bridge** (the "legacy bridge" of the geometry pivot): it
reuses the entire v3 front-end (``build_ir`` → resolved shapely
``PrimitiveIR`` / ``PinIR``) as the *cell library* and lowers the resolved
primitives into an explicit, flat OpenCASCADE ``.geo`` whose Physical names follow
the ``"<role>::<layer>::<component>::<primitive>"`` contract.  It runs strictly
**upstream of ``load_geo``** (the Elaborator writes ``<stem>.elaborated.geo``);
nothing below ``load_geo`` changes, so the GDS + mesh + Palace pipeline consumes
parametric, **rounded-corner** cells unchanged and Palace names stay
byte-identical (geometry-source-agnostic).

Locked seam decisions (session ``2606080224.md``):

* **#1 ground** — synthesize **one chip-wide ground per layer**: aggregate **all**
  ``subtract:true`` primitives (pocket + cpw-gaps, across all cells on that layer)
  and punch them as holes out of a chip-extent rectangle.  The Boolean is resolved
  **in shapely** (``ground_rect.difference(union(subtracts))``) and the result is
  emitted as explicit multi-loop ``Plane Surface`` geometry — functionally the
  single ``BooleanDifference`` of decision #1, done in Python so GDS == mesh parity
  is guaranteed and overlapping / ground-splitting subtracts are handled cleanly.
* **#2 ports** — emit ``PinIR`` as a plain ``port::layer::comp::pin`` dim-1 marker
  only; the edge-topology / fragment-survival / lumped-port contract is deferred
  (electrostatic uses conductor surfaces, not 1D ports).
* **#3 curves** — **pre-sample** shapely buffers → polygon ``Line`` segments here in
  Python (rounded corners come from the buffer's round joins); the loader only sees
  straight ``Line`` segments, so GDS == mesh and loader arc sampling is sidestepped.

IMPORTANT: at module level this file imports **only shapely** (a v3-core
dependency) — **never** ``gmsh`` or ``gdstk``.  It runs before either backend
touches the geometry.  The one exception is :func:`emit_block_geo` (P0-A), whose
input is an *already existing* ``.geo`` rather than an IR, so it **lazily** imports
``_gmsh_geo_source`` inside the call to read the source geometry (spec §12.4).
``import quantum_dsl.dsl.geo_emit`` still pulls in no gmsh.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable, Optional, Sequence, Union

from shapely.geometry import LineString, MultiPolygon, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from .errors import DesignDslError
from .ir import ComponentIR, DesignIR, PinIR, PrimitiveIR
from .schema import CURRENT_SCHEMA

__all__ = ["emit_geo", "elaborate_cells", "emit_block_geo"]


# ---------------------------------------------------------------------------
# Tunables / defaults
# ---------------------------------------------------------------------------

# Default chord-height tolerance (µm) for sampling buffer arcs into Line segments.
DEFAULT_ARC_TOL_UM = 0.5
# Default ground-plane margin (µm) added around the union bbox of all features on
# a layer when no explicit chip floorplan is supplied.
DEFAULT_GROUND_MARGIN_UM = 120.0
# Default block window margin (µm): how far past the selected conductors' bbox the
# derived block keeps ground / substrate (§4 P0-A rule S3).
DEFAULT_BLOCK_SIDE_BUFFER_UM = 200.0


def _fmt(v: float) -> str:
    """Deterministic, compact coordinate formatting (µm)."""
    return f"{float(v):.9g}"


def _quad_segs(radius: float, arc_tol_um: float) -> int:
    """Segments per quarter-circle so a buffer arc's chord error ≤ ``arc_tol_um``.

    Clamped to [4, 64] — a floor keeps rounded corners visibly round on tiny
    features, the ceiling caps the vertex count of large fillets.
    """
    if radius <= 0.0 or arc_tol_um <= 0.0:
        return 8
    ratio = min(max(1.0 - arc_tol_um / radius, 0.0), 1.0 - 1e-12)
    theta = math.acos(ratio)  # half-angle subtended by one chord
    if theta <= 0.0:
        return 64
    qs = math.ceil((math.pi / 2.0) / (2.0 * theta))
    return int(max(4, min(qs, 64)))


def _ring_points(ring: Iterable[Iterable[float]]) -> list[tuple[float, float]]:
    """Coords of a shapely ring without the repeated closing vertex."""
    pts = [(float(x), float(y)) for x, y in ring]
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


def _iter_polygons(geom: BaseGeometry) -> list[Polygon]:
    """Flatten a Polygon / MultiPolygon into a list of non-empty Polygons."""
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return [g for g in geom.geoms if not g.is_empty]
    # GeometryCollection or line/point residue from a degenerate Boolean — keep
    # only the polygonal parts.
    polys: list[Polygon] = []
    for g in getattr(geom, "geoms", []):
        if isinstance(g, Polygon) and not g.is_empty:
            polys.append(g)
        elif isinstance(g, MultiPolygon):
            polys.extend(p for p in g.geoms if not p.is_empty)
    return polys


# ---------------------------------------------------------------------------
# .geo text writer
# ---------------------------------------------------------------------------

class _GeoWriter:
    """Accumulates flat OpenCASCADE ``.geo`` statements with fresh tag names.

    Every geometric entity gets a uniquely-named variable (``_p3``, ``_l7`` …)
    backed by gmsh's ``newp`` / ``newl`` / ``newll`` / ``news`` allocators, so the
    output never collides regardless of how many cells are concatenated.
    """

    def __init__(self) -> None:
        self._lines: list[str] = []
        self._n = 0

    def raw(self, line: str = "") -> None:
        self._lines.append(line)

    def comment(self, text: str) -> None:
        self._lines.append(f"// {text}")

    def _fresh(self, prefix: str) -> str:
        self._n += 1
        return f"_{prefix}{self._n}"

    def _curve_loop(self, ring: list[tuple[float, float]]) -> str:
        """Emit Point + Line + Curve Loop for one closed ring; return loop var."""
        pvars: list[str] = []
        for x, y in ring:
            p = self._fresh("p")
            self.raw(f"{p} = newp; Point({p}) = {{ {_fmt(x)}, {_fmt(y)}, 0 }};")
            pvars.append(p)
        lvars: list[str] = []
        n = len(pvars)
        for i in range(n):
            a, b = pvars[i], pvars[(i + 1) % n]
            ln = self._fresh("l")
            self.raw(f"{ln} = newl; Line({ln}) = {{ {a}, {b} }};")
            lvars.append(ln)
        cl = self._fresh("cl")
        self.raw(f"{cl} = newll; Curve Loop({cl}) = {{ {', '.join(lvars)} }};")
        return cl

    def plane_surface(self, polygon: Polygon) -> str:
        """Emit a Plane Surface for a Polygon (exterior + interior hole loops)."""
        polygon = orient(polygon, sign=1.0)  # exterior CCW, holes CW
        ext = _ring_points(polygon.exterior.coords)
        if len(ext) < 3:
            raise DesignDslError(
                "emit_geo: degenerate polygon with <3 exterior points")
        loops = [self._curve_loop(ext)]
        for interior in polygon.interiors:
            hole = _ring_points(interior.coords)
            if len(hole) >= 3:
                loops.append(self._curve_loop(hole))
        s = self._fresh("s")
        self.raw(f"{s} = news; Plane Surface({s}) = {{ {', '.join(loops)} }};")
        return s

    def boolean_difference(self, base_var: str, tool_vars: list[str]) -> str:
        """Emit an OCC ``BooleanDifference`` (base − tools); return the result-array var.

        Used for the synthesized ground: ``base`` is the chip-extent rectangle and
        ``tools`` are the subtract primitives punched as holes.  This is the
        ``tiny_chip.geo`` idiom — unlike a multi-loop ``Plane Surface``, the OCC
        boolean produces a face whose holes survive ``extrude`` into a holed prism
        (a multi-loop face fills its holes on extrude).  Use ``f"{var}()"`` to refer
        to the whole result array (it may split into >1 surface).
        """
        d = self._fresh("diff")
        tools = "; ".join(f"Surface{{ {t} }}" for t in tool_vars)
        self.raw(
            f"{d}() = BooleanDifference{{ Surface{{ {base_var} }}; Delete; }}"
            f"{{ {tools}; Delete; }};")
        return d

    def line_marker(self, p0: tuple[float, float],
                    p1: tuple[float, float]) -> str:
        """Emit a free 1D Line (port marker); return the line var."""
        a = self._fresh("p")
        self.raw(f"{a} = newp; Point({a}) = {{ {_fmt(p0[0])}, {_fmt(p0[1])}, 0 }};")
        b = self._fresh("p")
        self.raw(f"{b} = newp; Point({b}) = {{ {_fmt(p1[0])}, {_fmt(p1[1])}, 0 }};")
        ln = self._fresh("l")
        self.raw(f"{ln} = newl; Line({ln}) = {{ {a}, {b} }};")
        return ln

    def physical_surface(self, name: str, surface_vars: list[str]) -> None:
        self.raw(f'Physical Surface("{name}") = {{ {", ".join(surface_vars)} }};')

    def physical_curve(self, name: str, curve_vars: list[str]) -> None:
        self.raw(f'Physical Curve("{name}") = {{ {", ".join(curve_vars)} }};')

    def text(self) -> str:
        return "\n".join(self._lines) + "\n"


# ---------------------------------------------------------------------------
# Primitive → shapely Polygon lowering
# ---------------------------------------------------------------------------

def _primitive_polygons(prim: PrimitiveIR, *, arc_tol_um: float,
                        cap_style: str, join_style: str) -> list[Polygon]:
    """Resolve one PrimitiveIR's shapely geometry into filled Polygon(s) (µm).

    * ``poly`` (Polygon)  → used verbatim (already a filled region).
    * ``path`` (LineString) → buffered by ``width/2`` with **round** joins/caps
      (rounded corners — decision #3).
    * ``junction`` (LineString) → buffered by ``width/2`` with **flat** caps
      (a clean rectangle; the JJ is a lumped element).
    """
    geom = prim.geometry
    if isinstance(geom, Polygon):
        return _iter_polygons(geom)
    if isinstance(geom, LineString):
        if prim.width is None or prim.width <= 0:
            raise DesignDslError(
                f"emit_geo: {prim.component}.{prim.name} is a {prim.kind} but "
                f"has no positive width to buffer.")
        half = float(prim.width) / 2.0
        is_jj = prim.kind == "junction"
        cap = "flat" if is_jj else cap_style
        join = "mitre" if is_jj else join_style
        qs = _quad_segs(half, arc_tol_um)
        buffered = geom.buffer(half, quad_segs=qs, cap_style=cap,
                               join_style=join)
        polys = _iter_polygons(buffered)
        if not polys:
            raise DesignDslError(
                f"emit_geo: {prim.component}.{prim.name} ({prim.kind}, width "
                f"{prim.width}) is degenerate — its buffer produced no polygon "
                f"(zero-length / single-point geometry?).")
        return polys
    raise DesignDslError(
        f"emit_geo: {prim.component}.{prim.name} has unsupported geometry "
        f"type {type(geom).__name__} (expected Polygon or LineString).")


def _prim_role(prim: PrimitiveIR) -> str:
    """Map a primitive to its geo role: junctions → 'jj', else 'metal'."""
    return "jj" if prim.kind == "junction" else "metal"


# ---------------------------------------------------------------------------
# emit_geo — public API
# ---------------------------------------------------------------------------

def emit_geo(design_ir: DesignIR,
             out_path: Optional[Union[str, Path]] = None,
             *,
             arc_tol_um: float = DEFAULT_ARC_TOL_UM,
             ground_margin_um: float = DEFAULT_GROUND_MARGIN_UM,
             chip_bbox: Optional[tuple[float, float, float, float]] = None,
             emit_ports: bool = False,
             cap_style: str = "round",
             join_style: str = "round") -> str:
    """Lower a resolved v3 ``DesignIR`` → flat positive-tone native ``.geo`` text.

    Args:
        design_ir: resolved IR from ``build_ir`` (geometry already placed — the v3
            component transforms are baked into each ``PrimitiveIR.geometry``).
        out_path: optional; if given, the ``.geo`` text is written there too.
        arc_tol_um: chord-height tolerance (µm) for sampling buffer arcs into
            ``Line`` segments (rounded corners).
        ground_margin_um: margin (µm) added around the per-layer feature bbox when
            synthesizing the chip-wide ground (ignored if ``chip_bbox`` given).
        chip_bbox: optional explicit ``(xmin, ymin, xmax, ymax)`` floorplan (µm)
            for the synthesized ground extent (overrides the computed bbox).
        emit_ports: emit each pin as a ``port::`` dim-1 ``Physical Curve`` marker.
            **Default False** (decision #2 — the lumped-port contract is deferred and
            the electrostatic solve uses conductor surfaces, not 1D ports). The
            marker is geometrically harmless (``load_geo`` accepts it; the mesh
            generates; ``populate_tracker_from_geo`` skips marker roles), so set it
            True to forward pin metadata for a future driven/eigenmode phase.
        cap_style / join_style: shapely buffer styles for ``path`` primitives
            (default ``"round"`` for rounded corners).

    Returns:
        The ``.geo`` text (also written to ``out_path`` when supplied).

    Raises:
        DesignDslError: degenerate / unsupported geometry, or no emittable surfaces.
    """
    w = _GeoWriter()
    w.comment("=" * 69)
    w.comment("AUTO-GENERATED by quantum_dsl.dsl.geo_emit.emit_geo (M5a).")
    w.comment("Flat, positive-tone OpenCASCADE .geo lowered from a v3 DesignIR.")
    w.comment("Units: µm.  DO NOT EDIT — regenerate from the *.meta.yaml cells:.")
    w.comment("=" * 69)
    w.raw()
    w.raw('SetFactory("OpenCASCADE");')
    w.raw()

    # --- pass 1: bucket primitives by layer ---------------------------------
    # positives[layer] = list of (role, component, primitive, [Polygon, ...])
    positives: dict[int, list[tuple[str, str, str, list[Polygon]]]] = {}
    # subtracts[layer] = list of Polygon (ground holes, aggregated)
    subtracts: dict[int, list[Polygon]] = {}
    # feature bbox accumulation per layer (positives + subtracts)
    feat_bounds: dict[int, list[float]] = {}

    def _accumulate_bounds(layer: int, polys: list[Polygon]) -> None:
        for p in polys:
            if p.is_empty:
                continue
            x0, y0, x1, y1 = p.bounds
            b = feat_bounds.get(layer)
            if b is None:
                feat_bounds[layer] = [x0, y0, x1, y1]
            else:
                b[0], b[1] = min(b[0], x0), min(b[1], y0)
                b[2], b[3] = max(b[2], x1), max(b[3], y1)

    for comp in design_ir.components:
        for prim in comp.primitives:
            if prim.helper:
                continue
            polys = _primitive_polygons(prim, arc_tol_um=arc_tol_um,
                                        cap_style=cap_style, join_style=join_style)
            if not polys:
                continue
            layer = int(prim.layer)
            _accumulate_bounds(layer, polys)
            if prim.subtract:
                subtracts.setdefault(layer, []).extend(polys)
            else:
                positives.setdefault(layer, []).append(
                    (_prim_role(prim), comp.name, prim.name, polys))

    if not positives and not subtracts:
        raise DesignDslError("emit_geo: DesignIR has no emittable primitives.")

    # --- pass 2: emit positive conductors (metal) + junctions ---------------
    for layer in sorted(positives):
        for role, component, primitive, polys in positives[layer]:
            surf_vars = [w.plane_surface(p) for p in polys]
            name = f"{role}::{layer}::{component}::{primitive}"
            w.physical_surface(name, surf_vars)
    if positives:
        w.raw()

    # --- pass 3: synthesize one chip-wide ground per layer (decision #1) ----
    # Aggregate ALL subtract:true primitives on the layer and punch them as holes
    # out of a chip-extent rectangle via a single OCC BooleanDifference (the
    # tiny_chip.geo idiom).  NOTE: this MUST be an OCC boolean, not a multi-loop
    # Plane Surface — OCC extrude FILLS the inner loops of a multi-loop face, so a
    # multi-loop "frame" would extrude to a solid slab and re-cover the pads.
    for layer in sorted(subtracts):
        b = feat_bounds[layer]
        if chip_bbox is not None:
            gx0, gy0, gx1, gy1 = chip_bbox
            # The ground rect MUST enclose every feature on the layer, else the
            # subtract holes spill past the ground and the BooleanDifference yields
            # a clipped / empty ground (silent bad geometry).
            if not (gx0 <= b[0] and gy0 <= b[1] and b[2] <= gx1 and b[3] <= gy1):
                raise DesignDslError(
                    f"emit_geo: chip_bbox {chip_bbox} does not enclose layer "
                    f"{layer} features (bbox {tuple(round(v, 3) for v in b)}).")
        else:
            m = float(ground_margin_um)
            gx0, gy0, gx1, gy1 = b[0] - m, b[1] - m, b[2] + m, b[3] + m
        base = w.plane_surface(box(gx0, gy0, gx1, gy1))
        # Each subtract primitive becomes a hole tool.  unary_union first so
        # overlapping subtracts (pocket ∪ cpw-gap) cut cleanly and the tool count
        # stays small; the union may split into several disjoint polygons.
        holes = _iter_polygons(unary_union(subtracts[layer]))
        if not holes:
            raise DesignDslError(
                f"emit_geo: layer {layer} has subtract primitives but they "
                f"resolved to no polygonal holes.")
        tool_vars = [w.plane_surface(h) for h in holes]
        diff = w.boolean_difference(base, tool_vars)
        w.physical_surface(f"ground::{layer}::chip::gnd", [f"{diff}()"])
    if subtracts:
        w.raw()

    # --- pass 4: pins → port:: dim-1 markers (decision #2, deferred) ---------
    if emit_ports:
        emitted_any = False
        for comp in design_ir.components:
            comp_layer = _component_layer(comp)
            for pin in comp.pins:
                pts = pin.points or []
                if len(pts) < 2:
                    continue
                p0 = (float(pts[0][0]), float(pts[0][1]))
                p1 = (float(pts[-1][0]), float(pts[-1][1]))
                if p0 == p1:
                    continue
                ln = w.line_marker(p0, p1)
                w.physical_curve(
                    f"port::{comp_layer}::{comp.name}::{pin.name}", [ln])
                emitted_any = True
        if emitted_any:
            w.raw()

    text = w.text()
    if out_path is not None:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    return text


def _component_layer(comp: ComponentIR) -> int:
    """The layer to tag a component's port markers with (its first metal layer)."""
    for prim in comp.primitives:
        if not prim.helper and not prim.subtract and prim.kind != "junction":
            return int(prim.layer)
    for prim in comp.primitives:
        if not prim.helper:
            return int(prim.layer)
    return 1


# ---------------------------------------------------------------------------
# Elaborator — cells: sidecar → one merged DesignIR → <stem>.elaborated.geo
# ---------------------------------------------------------------------------

DEFAULT_CHIP_SIZE = "12mm x 12mm"


def _placement_str(value: object, default: str) -> str:
    """Coerce a cell placement value into a DSL value string (µm if unitless)."""
    if value is None:
        return default
    if isinstance(value, bool):  # guard: bools are ints in Python
        raise DesignDslError(f"cell placement value must be a number/str, got {value!r}")
    if isinstance(value, (int, float)):
        return f"{value}um"
    return str(value)


def elaborate_cells(cells: list[dict],
                    out_path: Optional[Union[str, Path]] = None,
                    *,
                    chip_size: str = DEFAULT_CHIP_SIZE,
                    arc_tol_um: float = DEFAULT_ARC_TOL_UM,
                    ground_margin_um: float = DEFAULT_GROUND_MARGIN_UM,
                    chip_bbox: Optional[tuple[float, float, float, float]] = None,
                    emit_ports: bool = False,
                    cap_style: str = "round",
                    join_style: str = "round") -> str:
    """Elaborate a ``cells:`` block → one flat ``<stem>.elaborated.geo``.

    Per the M5a Elaborator contract: run ``build_ir`` **per cell instance** (each
    cell is a self-contained v3 component-template invocation — the cell library),
    placing it via the template's ``pos_x`` / ``pos_y`` / ``orientation`` options;
    concatenate every resolved ``ComponentIR`` into one merged ``DesignIR``; assert
    the ``component`` names are globally unique (so ``load_geo``'s duplicate-name
    guard never trips); then lower the merge with :func:`emit_geo`.

    Args:
        cells: list of cell dicts (``cell_type`` + globally-unique ``component``
            required; optional ``x`` / ``y`` / ``rot`` / ``layer`` placement and a
            ``params`` mapping of template-option overrides).
        out_path: optional; written with the elaborated ``.geo`` text.
        chip_size: DesignPlanar chip size string for the per-cell build_ir scaffold
            (geometry-only; does not affect the emitted surfaces).
        (others): forwarded to :func:`emit_geo`.

    Returns:
        The elaborated ``.geo`` text.

    Raises:
        DesignDslError: missing required keys, duplicate ``component`` names, or a
            cell that build_ir / emit_geo cannot resolve.
    """
    import yaml  # base dep; deferred so module import stays light

    from .builder import build_ir  # local import: avoid heavy import at load

    if not cells:
        raise DesignDslError("elaborate_cells: 'cells' is empty — nothing to emit.")

    components: list[ComponentIR] = []
    seen: set[str] = set()
    for i, cell in enumerate(cells):
        if not isinstance(cell, dict):
            raise DesignDslError(f"cells[{i}] must be a mapping, got {type(cell).__name__}")
        cell_type = cell.get("cell_type")
        component = cell.get("component")
        if not cell_type or not isinstance(cell_type, str):
            raise DesignDslError(f"cells[{i}] requires a string 'cell_type'.")
        if not component or not isinstance(component, str):
            raise DesignDslError(f"cells[{i}] requires a string 'component' name.")
        if component in seen:
            raise DesignDslError(
                f"cells: duplicate component name {component!r} — every cell's "
                f"'component' must be globally unique (it is the ::<component>:: "
                f"field of the binding name).")
        seen.add(component)

        options: dict = dict(cell.get("params") or {})
        options["pos_x"] = _placement_str(cell.get("x"), "0um")
        options["pos_y"] = _placement_str(cell.get("y"), "0um")
        if cell.get("rot") is not None:
            rot = cell["rot"]
            if isinstance(rot, bool) or not isinstance(rot, (int, float, str)):
                raise DesignDslError(
                    f"cells[{i}].rot must be a number (degrees) or value string, "
                    f"got {rot!r}")
            options["orientation"] = rot
        if cell.get("layer") is not None:
            try:
                options["layer"] = int(cell["layer"])
            except (TypeError, ValueError) as exc:
                raise DesignDslError(
                    f"cells[{i}].layer must be an integer, got "
                    f"{cell['layer']!r}") from exc

        design = {
            "schema": CURRENT_SCHEMA,
            "geometry": {
                "design": {"class": "DesignPlanar", "chip": {"size": chip_size}},
                "components": {component: {"type": cell_type, "options": options}},
            },
        }
        try:
            ir = build_ir(yaml.safe_dump(design, sort_keys=False))
        except DesignDslError:
            raise
        except Exception as exc:  # surface build_ir failures with cell context
            raise DesignDslError(
                f"cells[{i}] ({component} = {cell_type}): build_ir failed: {exc}"
            ) from exc
        components.extend(ir.components)

    merged = DesignIR(
        schema=CURRENT_SCHEMA, vars={}, hamiltonian=None, circuit=None,
        netlist=None, design={}, components=components, geometry={},
        derived={}, simulation={})
    return emit_geo(merged, out_path, arc_tol_um=arc_tol_um,
                    ground_margin_um=ground_margin_um, chip_bbox=chip_bbox,
                    emit_ports=emit_ports, cap_style=cap_style,
                    join_style=join_style)


# ---------------------------------------------------------------------------
# emit_block_geo — 从整片 .geo 派生一份只含若干 component 的 block_<name>.geo
# ---------------------------------------------------------------------------

def _geo_physical_name(surf) -> str:
    """``GeoSurface`` 的 4 段身份 → 源 ``.geo`` 里那个 physical 名 (逐字重组)。"""
    return f"{surf.role}::{surf.layer}::{surf.component}::{surf.primitive}"


def _emit_face(w: _GeoWriter, poly: Polygon) -> str:
    """发一个 shapely 面 → 可写进 ``Physical Surface`` 的 surface 表达式。

    无孔 → ``Plane Surface``; **有孔 → ``BooleanDifference``**。后者是硬要求:
    多环 ``Plane Surface`` 在 OCC ``extrude`` 时孔会被填实 (M5a 的发现, 见
    :meth:`_GeoWriter.boolean_difference` 的 docstring), 地平面的 pocket 就会
    在 mesh 分支里悄悄消失。
    """
    if not poly.interiors:
        return w.plane_surface(poly)
    base = w.plane_surface(Polygon(poly.exterior))
    tools = [w.plane_surface(Polygon(ring)) for ring in poly.interiors]
    return f"{w.boolean_difference(base, tools)}()"


def _fill_excluded_holes(poly: Polygon, selected: list[Polygon],
                         excluded: list[Polygon]) -> Polygon:
    """**故意错误**的 pocket 过滤 (只服务 ``keep_all_subtractive=False``)。

    去掉「只与未入选 component 的金属相交」的内环 = 把那些 pocket **填实**。
    与未入选金属**和**入选金属都相交的孔 (例如 chip_layout 里 bus gap 与 qubit
    pocket 已经连通成同一个孔) 保留 —— 填掉它会把入选导体也埋进金属里。
    """
    # ponytail: 保留这个错误分支是有意的 —— 它是 §7 那条 live 护栏测试的被测项,
    # 用来量化「按 component 过滤 pocket」的对地电容偏高幅度。删掉它就等于删掉
    # 防止 S2 被「优化」回错误实现的那道防线 (§11 R1)。天花板: 只按「孔 vs 金属
    # 相交」判定, 不理会孔的成因; 够护栏用, 不要拿它当生产路径。
    if not poly.interiors or not excluded:
        return poly
    kept = []
    for ring in poly.interiors:
        hole = Polygon(ring)
        if any(hole.intersects(m) for m in selected):
            kept.append(ring)
        elif any(hole.intersects(m) for m in excluded):
            continue  # ← 这一句就是被护栏测试量化的那个错误
        else:
            kept.append(ring)
    return Polygon(poly.exterior, kept)


def emit_block_geo(src_geo: Union[str, Path],
                   *,
                   components: Sequence[str],
                   out_path: Union[str, Path],
                   arc_tol_um: float = DEFAULT_ARC_TOL_UM,
                   side_buffer_um: float = DEFAULT_BLOCK_SIDE_BUFFER_UM,
                   keep_all_subtractive: bool = True) -> Path:
    """P0-A: 从一份**已存在的整片** ``.geo`` 派生只含 ``components`` 的块几何。

    按 §3.0 的 G1 实现为一个 **emitter**, 不是运行时的 tracker 过滤器: 产物
    ``block_<name>.geo`` **落盘**, 严格运行在 ``load_geo`` 上游, ``load_geo``
    及其下游一行不改 (与 M5a 的 ``emit_geo`` / ``elaborate_cells`` 同构)。落盘
    的好处不只是可归档/可 diff —— 它让 §4 P0-A 的头号风险 S2 变成**可以用 gmsh
    GUI 目视确认**的东西, 而不是只能靠单元测试。

    与 ``emit_geo`` 的分工差别: 输入是几何而不是 IR, 所以本函数需要 gmsh 读一次
    源几何 (``load_geo`` + ``surface_outline_um`` → shapely), 布尔运算全在
    shapely 里做, **不引入任何新的 OCC 布尔切割** (§3.2: 切割面只能落在
    component 边界)。

    §4 P0-A 的五条规则在这里的落地:

    * **S1** ``metal::`` / ``jj::``: 只保留 ``component ∈ components``。
    * **S2/S3** ``ground::`` / ``substrate::``: 整张面与「块窗口」求交
      (``ground_poly.intersection(window)``), 窗口 = 入选 metal/jj 并集 bbox 向外
      扩 ``side_buffer_um``。**这是本函数最重要的一行**: ground 在源 ``.geo`` 里
      已经是一张**带孔**的面 (孔由 ``.geo`` 内的 ``BooleanDifference`` 挖好),
      shapely 求交**自动保留窗口内的全部孔**, 不问那个孔属于哪个 component。所以
      **绝不能**「按 component 重建 ground 的孔集合」—— 那正是 §4 P0-A 记的头号
      silent-wrong-result: 被排除 component 的 pocket 没挖 → ground 金属侵入本该
      是真空腔的区域 → 留下来的导体对地电容**静默偏高, 管线全绿**。
      正确语义是: 被排除的 component 留下一个**有洞、没金属的空真空腔**。
      这正是 qiskit-metal ``add_endcaps()`` 的等价物
      (``renderers/renderer_ansys/ansys_renderer.py:1388`` 起, 在 open pin 处
      画一个 ``gap × (width+2·gap)`` 矩形加进 ``chip_subtract_dict``, 即从地平面
      减掉) —— 两边都是「金属移走、地平面开口留下」, 不是新概念。
    * **S4** airbox: **本函数不写一行代码**。airbox 由 ``gmsh_adapter`` 从
      ``compute_chip_bbox_from_geo(块几何)`` + sidecar 的 ``airbox:`` 参数派生,
      块几何小了它自动跟着小 —— 这就是分块省算力的主要来源, 白拿的。
    * **S5** ``port::`` / ``symmetry::`` (dim=1): 随 S1 按 component 过滤后原样重发。

    Physical 名从源几何的 4 段身份原样重组 (``role::layer::component::primitive``),
    所以块几何过 ``load_geo`` → ``assign_physical_groups`` 之后的 group 名与整片
    解**逐字相同** (G1 契约, §7 的 byte-identical 判据)。

    session 所有权: 与 ``load_geo`` 同一契约 —— gmsh 未初始化时由 ``load_geo``
    initialize, 但本函数 **从不 finalize** (调用方拥有 session)。所以从
    ``build_geo`` 的单一 session 里调用是安全的 (见 ``geo_build.py`` 的
    SESSION OWNERSHIP 注释)。

    Args:
        src_geo: 整片 ``.geo`` 路径 (µm, OpenCASCADE)。
        components: 入选的 component 名 (``::<component>::`` 字段)。
        out_path: 块 ``.geo`` 的落盘路径。
        arc_tol_um: 读源几何轮廓时的弧线采样弦高容差 (µm)。
        side_buffer_um: 块窗口在入选导体 bbox 外的余量 (µm, 规则 S3)。
        keep_all_subtractive: **True 是唯一物理正确的行为** (见上面 S2)。
            ``False`` 是**故意错的**: 它把「只与未入选 component 的金属相交」的
            pocket 填实, 存在的唯一目的是让 §7 的 live 护栏测试能**量化**「按
            component 过滤 pocket」造成的误差 (对地电容偏高)。护栏测试的存在本身
            就是为了防止后人把 True 的行为「优化」掉。生产代码永远不要传 False。

    Returns:
        写出的块 ``.geo`` 路径 (``Path(out_path)``)。

    Raises:
        DesignDslError: ``components`` 为空 / 有名字不在源几何里 / 入选后没有任何
            metal|jj 面 / ground 与块窗口求交后为空。
    """
    # 惰性导入: 本模块其余部分不依赖 gmsh (见模块 docstring)。
    from ._gmsh_geo_source import (  # noqa: PLC0415
        _curve_points_um, load_geo, surface_outline_um,
    )

    wanted = list(dict.fromkeys(components or ()))
    if not wanted:
        raise DesignDslError(
            "emit_block_geo: 'components' is empty — a block must name at least "
            "one component to keep.")

    surfaces = load_geo(src_geo, scale_to_si=False)
    available = sorted({s.component for s in surfaces})
    unknown = [c for c in wanted if c not in available]
    if unknown:
        raise DesignDslError(
            f"emit_block_geo: unknown component(s) {unknown} in {src_geo} — "
            f"available components: {available}.")
    keep = set(wanted)

    # --- pass 0: 每个 dim-2 physical group 的实体 → shapely Polygon (µm) -----
    # 一个 physical group 可能有多个 entity, 逐个转。
    dim2: list[tuple[object, list[Polygon]]] = []
    selected_metal: list[Polygon] = []
    excluded_metal: list[Polygon] = []
    for surf in surfaces:
        if surf.dim != 2:
            continue
        polys: list[Polygon] = []
        for ent in surf.entities:
            exterior, holes = surface_outline_um(int(ent), arc_tol_um)
            polys.extend(_iter_polygons(Polygon(exterior, holes)))
        if not polys:
            continue
        dim2.append((surf, polys))
        if surf.role in ("metal", "jj"):
            (selected_metal if surf.component in keep
             else excluded_metal).extend(polys)

    if not selected_metal:
        raise DesignDslError(
            f"emit_block_geo: components {wanted} select no metal|jj surface in "
            f"{src_geo} — available components: {available}.")

    # --- 块窗口 = 入选导体并集 bbox + side_buffer (规则 S3) ------------------
    bx0, by0, bx1, by1 = unary_union(selected_metal).bounds
    sb = float(side_buffer_um)
    window = box(bx0 - sb, by0 - sb, bx1 + sb, by1 + sb)

    w = _GeoWriter()
    w.comment("=" * 69)
    w.comment("AUTO-GENERATED by quantum_dsl.dsl.geo_emit.emit_block_geo (P0-A).")
    w.comment(f"Block subset derived from: {Path(src_geo).name}")
    w.comment(f"components      : {', '.join(wanted)}")
    w.comment(f"side_buffer_um  : {_fmt(sb)}")
    w.comment(f"window (µm)     : {tuple(_fmt(v) for v in window.bounds)}")
    w.comment(f"keep_all_subtractive: {keep_all_subtractive}"
              + ("" if keep_all_subtractive else "   <-- PHYSICALLY WRONG"
                                                " (guard-rail test only)"))
    w.comment("Units: µm.  DO NOT EDIT — regenerate from the source .geo.")
    w.comment("=" * 69)
    w.raw()
    w.raw('SetFactory("OpenCASCADE");')
    w.raw()

    # --- pass 1: 入选的 metal / jj (规则 S1) --------------------------------
    for surf, polys in dim2:
        if surf.role not in ("metal", "jj") or surf.component not in keep:
            continue
        w.physical_surface(_geo_physical_name(surf),
                           [_emit_face(w, p) for p in polys])
    w.raw()

    # --- pass 2: ground / substrate ∩ 窗口 (规则 S2/S3) ---------------------
    for surf, polys in dim2:
        if surf.role not in ("ground", "substrate"):
            continue
        clipped: list[Polygon] = []
        for poly in polys:
            if not keep_all_subtractive:
                poly = _fill_excluded_holes(
                    poly, selected_metal, excluded_metal)
            clipped.extend(
                p for p in _iter_polygons(poly.intersection(window))
                if p.area > 0.0)
        if not clipped:
            raise DesignDslError(
                f"emit_block_geo: {_geo_physical_name(surf)} does not "
                f"intersect the block window "
                f"{tuple(round(v, 3) for v in window.bounds)} — nothing left to "
                f"emit (side_buffer_um too small, or the components lie off the "
                f"sheet).")
        # 求交可能得到 MultiPolygon: 每块单独发面, 一起挂同一个 Physical 名。
        w.physical_surface(_geo_physical_name(surf),
                           [_emit_face(w, p) for p in clipped])
    w.raw()

    # --- pass 3: port / symmetry dim-1 marker, 随 S1 过滤 (规则 S5) ----------
    for surf in surfaces:
        if surf.dim != 1 or surf.component not in keep:
            continue
        markers: list[str] = []
        for ent in surf.entities:
            # 复用 loader 的曲线采样器; marker 实际都是直线 (emit_geo 发的是
            # line_marker), 弧线 marker 会退化成弦 —— 静电用不到 (M5a 决策 #2)。
            pts = _curve_points_um(1, int(ent), arc_tol=arc_tol_um)
            if len(pts) >= 2 and pts[0] != pts[-1]:
                markers.append(w.line_marker(pts[0], pts[-1]))
        if markers:
            w.physical_curve(_geo_physical_name(surf), markers)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(w.text(), encoding="utf-8")
    return out
