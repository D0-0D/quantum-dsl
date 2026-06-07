# -*- coding: utf-8 -*-
"""GDSII visualization (M7, requirement R5) — read ``chip.gds`` → preview/plot.

This module is **visualization-only and strictly additive**: the layout is still
EMITTED by :func:`gds_adapter.build_gds` (gdstk).  Here we only *read* a finished
``.gds`` and render/inspect it.  Two backends:

- ``"gdsfactory"`` — the R5-named tool.  :func:`to_gdsfactory_component` brings the
  layout into the gdsfactory ecosystem via ``gf.import_gds`` (a stable API); the
  returned ``Component`` is what makes the layout available for gdsfactory-side
  viewing / further manipulation.  OPTIONAL dependency
  (``pip install 'quantum_dsl[viz]'``) — absent by default.
- ``"matplotlib"`` — the default fallback.  Reads polygons with **gdstk** and
  rasterizes them with matplotlib's Agg canvas (headless-safe; no pyplot global
  state).  gdstk + matplotlib ship with the test env, so this path is exercised
  in the suite.

``backend="auto"`` picks gdsfactory when it is importable, else matplotlib.

Unit contract: gdstk user-coordinates are microns (``build_gds`` writes µm verbatim
with ``unit=1e-6``), so :attr:`GdsPreview.bbox_um` and the axes are microns.

Import purity: gdstk / matplotlib / gdsfactory are all imported **lazily** inside
the functions, mirroring the gmsh/gdstk discipline of the other adapters — so
``import quantum_dsl`` never pulls any of them in.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from .errors import DesignDslError

__all__ = [
    "GdsPreview",
    "preview_gds",
    "read_gds_layers",
    "to_gdsfactory_component",
]

_BACKENDS = ("auto", "gdsfactory", "matplotlib")

# Stable, color-blind-friendly palette cycled per (layer, datatype).
_PALETTE = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3",
    "#937860", "#DA8BC3", "#8C8C8C", "#CCB974", "#64B5CD",
]


@dataclass(frozen=True)
class GdsPreview:
    """Result of :func:`preview_gds`.

    - ``gds_path``: the source ``.gds``.
    - ``png_path``: rendered PNG (``None`` when ``out_png`` was ``None`` —
      introspection-only).
    - ``backend``: which backend was used (``"gdsfactory"`` | ``"matplotlib"``);
      for ``"auto"`` this is the resolved choice.
    - ``layers``: sorted ``(layer, datatype)`` present in the top cell.
    - ``polygon_counts``: ``{(layer, datatype): polygon_count}`` in the top cell.
    - ``bbox_um``: ``(xmin, ymin, xmax, ymax)`` of the top cell (microns).
    - ``top_cell``: name of the rendered top cell.
    """

    gds_path: Path
    png_path: Optional[Path]
    backend: str
    layers: list[tuple[int, int]]
    polygon_counts: dict[tuple[int, int], int]
    bbox_um: tuple[float, float, float, float]
    top_cell: str


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _require(mod_name: str, *, extra: Optional[str] = None):
    """Lazy import ``mod_name`` or raise a clear DesignDslError with an install hint."""
    import importlib
    try:
        return importlib.import_module(mod_name)
    except ImportError as exc:  # pragma: no cover - exercised on lite installs
        hint = f" (pip install 'quantum_dsl[{extra}]')" if extra else ""
        raise DesignDslError(
            f"gds_viz: '{mod_name}' is required for this operation{hint}.") from exc


def _read_top_cell(gds_path: Union[str, Path]):
    """``gdstk.read_gds`` → (top_cell, sorted layers, counts, bbox_um). Lazy gdstk."""
    gdstk = _require("gdstk", extra="gds")
    p = Path(gds_path)
    if not p.is_file():
        raise DesignDslError(f"gds_viz: file not found: {p}")
    lib = gdstk.read_gds(str(p))
    tops = lib.top_level()
    if not tops:
        raise DesignDslError(f"gds_viz: {p} has no top-level cell.")
    top = tops[0]
    counts: dict[tuple[int, int], int] = {}
    for poly in top.polygons:
        key = (int(poly.layer), int(poly.datatype))
        counts[key] = counts.get(key, 0) + 1
    bb = top.bounding_box()
    if bb is None:
        bbox = (0.0, 0.0, 0.0, 0.0)
    else:
        (xmin, ymin), (xmax, ymax) = bb
        bbox = (float(xmin), float(ymin), float(xmax), float(ymax))
    return top, sorted(counts), counts, bbox


def _resolve_layer_colors(keys, overrides):
    """Assign a stable color per (layer, datatype), honoring caller overrides."""
    import itertools
    colors = dict(overrides or {})
    cyc = itertools.cycle(_PALETTE)
    for key in keys:
        colors.setdefault(key, next(cyc))
    return colors


def _render_matplotlib(top, png_path: Path, *, dpi: int, bbox, layer_colors) -> None:
    """Rasterize a gdstk top cell's polygons via matplotlib's Agg canvas (headless).

    Uses the object-oriented Figure/FigureCanvasAgg API (NOT pyplot) so there is no
    global backend state and no display is required.
    """
    _require("matplotlib")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.patches import Polygon as MplPolygon, Patch
    from matplotlib.collections import PatchCollection

    keys = sorted({(int(p.layer), int(p.datatype)) for p in top.polygons})
    colors = _resolve_layer_colors(keys, layer_colors)

    fig = Figure(figsize=(8, 8))
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)

    patches_by_key: dict[tuple[int, int], list] = {k: [] for k in keys}
    for poly in top.polygons:
        key = (int(poly.layer), int(poly.datatype))
        patches_by_key[key].append(MplPolygon(poly.points, closed=True))

    handles = []
    for key in keys:
        color = colors[key]
        ax.add_collection(PatchCollection(
            patches_by_key[key], facecolor=color, edgecolor="black",
            linewidths=0.3, alpha=0.7))
        handles.append(Patch(facecolor=color, edgecolor="black",
                             label=f"L{key[0]}/{key[1]}"))

    xmin, ymin, xmax, ymax = bbox
    pad = 0.05 * max(xmax - xmin, ymax - ymin, 1.0)
    ax.set_xlim(xmin - pad, xmax + pad)
    ax.set_ylim(ymin - pad, ymax + pad)
    ax.set_aspect("equal")
    ax.set_xlabel("x (µm)")
    ax.set_ylabel("y (µm)")
    ax.set_title(f"{Path(png_path).stem}  ({top.name})")
    if handles:
        ax.legend(handles=handles, loc="upper right", fontsize=8)
    fig.savefig(str(png_path), dpi=dpi, bbox_inches="tight")


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def to_gdsfactory_component(gds_path: Union[str, Path]) -> Any:
    """Import a ``.gds`` into gdsfactory and return the ``Component`` (R5 bridge).

    This is the gdsfactory integration point: ``gf.import_gds`` is the stable,
    documented entry that lifts our gdstk-emitted layout into the gdsfactory
    ecosystem (for its viewers, 3D, DRC, or further parametric work).  Requires the
    optional ``viz`` extra.

    Raises:
        DesignDslError: the ``.gds`` is missing, or ``gdsfactory`` is not installed.
    """
    p = Path(gds_path)
    if not p.is_file():
        raise DesignDslError(f"gds_viz: file not found: {p}")
    gf = _require("gdsfactory", extra="viz")
    return gf.import_gds(str(p))


def read_gds_layers(gds_path: Union[str, Path]) -> list[tuple[int, int]]:
    """Lightweight introspection: sorted ``(layer, datatype)`` of the top cell.

    Backend-free (gdstk only); handy for asserting which GDS layers a build emitted
    (metal/ground L1, JJ L20, …) without rendering.
    """
    _top, layers, _counts, _bbox = _read_top_cell(gds_path)
    return layers


def preview_gds(gds_path: Union[str, Path],
                *,
                out_png: Optional[Union[str, Path]] = None,
                backend: str = "auto",
                dpi: int = 200,
                layer_colors: Optional[dict[tuple[int, int], str]] = None
                ) -> GdsPreview:
    """Read ``gds_path`` and (optionally) render a PNG preview.

    Args:
        gds_path: a finished ``.gds`` (e.g. ``build_geo``'s ``chip.gds``).
        out_png: PNG output path; ``None`` = introspect only (no render).
        backend: ``"auto"`` (gdsfactory if importable, else matplotlib),
            ``"gdsfactory"`` (import via gdsfactory, then rasterize), or
            ``"matplotlib"`` (gdstk + matplotlib, the always-available path).
        dpi: raster DPI for the PNG.
        layer_colors: optional ``{(layer, datatype): color}`` overrides.

    Returns:
        :class:`GdsPreview` (always populated with layers/counts/bbox; ``png_path``
        is set only when ``out_png`` was given).

    Raises:
        DesignDslError: file missing / no top cell / unknown backend / a forced
            backend's dependency is absent.
    """
    if backend not in _BACKENDS:
        raise DesignDslError(
            f"gds_viz: unknown backend {backend!r} "
            f"(expected one of {', '.join(_BACKENDS)}).")

    # Introspect first (gdstk) — validates the file and is backend-independent.
    top, layers, counts, bbox = _read_top_cell(gds_path)

    chosen = backend
    if backend == "auto":
        import importlib.util
        chosen = ("gdsfactory"
                  if importlib.util.find_spec("gdsfactory") is not None
                  else "matplotlib")

    png_path: Optional[Path] = None
    if out_png is not None:
        png_path = Path(out_png)
        png_path.parent.mkdir(parents=True, exist_ok=True)
        if chosen == "gdsfactory":
            # Exercise the gdsfactory integration (validates it can read our GDS),
            # then rasterize through the robust, version-stable matplotlib path —
            # gdsfactory's own Component.plot() API varies across releases.
            to_gdsfactory_component(gds_path)
        _render_matplotlib(top, png_path, dpi=dpi, bbox=bbox,
                           layer_colors=layer_colors)

    return GdsPreview(
        gds_path=Path(gds_path), png_path=png_path, backend=chosen,
        layers=layers, polygon_counts=counts, bbox_um=bbox, top_cell=top.name)
