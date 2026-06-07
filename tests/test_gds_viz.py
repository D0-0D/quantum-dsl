# -*- coding: utf-8 -*-
"""GDSII visualization tests (M7, requirement R5) for ``quantum_dsl.dsl.gds_viz``.

The matplotlib backend (gdstk + matplotlib — both ship with conda ``metal-env``)
is exercised directly here; the gdsfactory backend is gated with
``importorskip("gdsfactory")`` (skips when the optional ``viz`` extra is absent,
mirroring the gmsh/gdstk gating elsewhere).  Import purity mirrors the
circuit_model / optional-backend contract.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

# gds_viz reads a .gds via gdstk and rasterizes via matplotlib — both are needed
# for every test below except the (subprocess) purity check.
gdstk = pytest.importorskip("gdstk")
pytest.importorskip("matplotlib")

from quantum_dsl.dsl.gds_viz import (  # noqa: E402
    GdsPreview,
    preview_gds,
    read_gds_layers,
    to_gdsfactory_component,
)
from quantum_dsl.dsl.errors import DesignDslError  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
_GDSFACTORY = importlib.util.find_spec("gdsfactory") is not None


def _make_gds(path, *, with_jj=True):
    """Write a tiny GDS: two metal pads (L1/0) + an optional JJ (L20/0), in µm."""
    lib = gdstk.Library(name="chip", unit=1e-6, precision=1e-9)
    cell = lib.new_cell("chip")
    cell.add(gdstk.rectangle((-50, -20), (-10, 20), layer=1, datatype=0))
    cell.add(gdstk.rectangle((10, -20), (50, 20), layer=1, datatype=0))
    if with_jj:
        cell.add(gdstk.rectangle((-2, -2), (2, 2), layer=20, datatype=0))
    lib.write_gds(str(path))
    return path


# --- introspection (backend-free) -----------------------------------------

def test_read_gds_layers(tmp_path):
    layers = read_gds_layers(_make_gds(tmp_path / "c.gds"))
    assert layers == [(1, 0), (20, 0)]


def test_preview_introspects_without_png(tmp_path):
    prev = preview_gds(_make_gds(tmp_path / "c.gds", with_jj=False))
    assert isinstance(prev, GdsPreview)
    assert prev.png_path is None
    assert prev.layers == [(1, 0)]
    assert prev.polygon_counts[(1, 0)] == 2
    xmin, ymin, xmax, ymax = prev.bbox_um
    assert (round(xmin), round(ymin), round(xmax), round(ymax)) == (-50, -20, 50, 20)
    assert prev.top_cell == "chip"


# --- matplotlib render (always-available backend) -------------------------

def test_preview_matplotlib_writes_png(tmp_path):
    png = tmp_path / "preview.png"
    prev = preview_gds(_make_gds(tmp_path / "c.gds"), out_png=png,
                       backend="matplotlib")
    assert prev.backend == "matplotlib"
    assert prev.png_path == png
    assert png.is_file() and png.stat().st_size > 0
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"   # PNG magic
    assert set(prev.layers) == {(1, 0), (20, 0)}


def test_auto_backend_falls_back_to_matplotlib_when_gdsfactory_absent(tmp_path):
    if _GDSFACTORY:
        pytest.skip("gdsfactory installed -> auto resolves to gdsfactory")
    prev = preview_gds(_make_gds(tmp_path / "c.gds"),
                       out_png=tmp_path / "p.png", backend="auto")
    assert prev.backend == "matplotlib"
    assert (tmp_path / "p.png").is_file()


def test_custom_layer_colors_render(tmp_path):
    prev = preview_gds(_make_gds(tmp_path / "c.gds"), out_png=tmp_path / "p.png",
                       backend="matplotlib",
                       layer_colors={(1, 0): "#ff0000", (20, 0): "#00ff00"})
    assert prev.backend == "matplotlib"
    assert (tmp_path / "p.png").is_file()


# --- error handling --------------------------------------------------------

def test_missing_file_raises(tmp_path):
    with pytest.raises(DesignDslError):
        preview_gds(tmp_path / "nope.gds")


def test_unknown_backend_raises(tmp_path):
    with pytest.raises(DesignDslError):
        preview_gds(_make_gds(tmp_path / "c.gds"), backend="inkscape")


def test_empty_library_no_top_cell_raises(tmp_path):
    lib = gdstk.Library(name="empty", unit=1e-6, precision=1e-9)
    lib.write_gds(str(tmp_path / "empty.gds"))
    with pytest.raises(DesignDslError):
        preview_gds(tmp_path / "empty.gds")


# --- gdsfactory backend (optional viz extra; gated) ------------------------

def test_to_gdsfactory_component(tmp_path):
    pytest.importorskip("gdsfactory")
    comp = to_gdsfactory_component(_make_gds(tmp_path / "c.gds"))
    assert comp is not None


def test_preview_gdsfactory_backend(tmp_path):
    pytest.importorskip("gdsfactory")
    prev = preview_gds(_make_gds(tmp_path / "c.gds"),
                       out_png=tmp_path / "gf.png", backend="gdsfactory")
    assert prev.backend == "gdsfactory"
    assert (tmp_path / "gf.png").is_file()


def test_gdsfactory_backend_without_dep_raises_clearly(tmp_path):
    if _GDSFACTORY:
        pytest.skip("gdsfactory installed -> absent-path not exercised")
    # Forcing the gdsfactory backend with the dep absent must raise a clear
    # DesignDslError (with an install hint), not a bare ImportError.
    with pytest.raises(DesignDslError):
        preview_gds(_make_gds(tmp_path / "c.gds"),
                    out_png=tmp_path / "x.png", backend="gdsfactory")


# --- integration: a real build_gds output is previewable -------------------

def test_preview_real_chip_gds_from_geo(tmp_path):
    pytest.importorskip("gmsh")
    from quantum_dsl.dsl.gds_adapter import build_gds
    res = build_gds(FIXTURES / "tiny_chip.geo", output_path=tmp_path / "chip.gds")
    prev = preview_gds(res.gds_path, out_png=tmp_path / "chip.png",
                       backend="matplotlib")
    assert (tmp_path / "chip.png").is_file()
    assert 1 in {layer for (layer, _dt) in prev.layers}   # metal/ground on L1


# --- public lazy exports ---------------------------------------------------

def test_lazy_exports_resolve():
    import quantum_dsl
    assert quantum_dsl.preview_gds is preview_gds
    assert quantum_dsl.GdsPreview is GdsPreview
    assert quantum_dsl.to_gdsfactory_component is to_gdsfactory_component
    assert quantum_dsl.read_gds_layers is read_gds_layers


# --- import purity (mirror circuit_model / optional-backend contract) ------

def test_gds_viz_import_is_pure():
    code = (
        "import quantum_dsl.dsl.gds_viz, sys\n"
        "bad=[m for m in ('gmsh','gdstk','gdsfactory') if m in sys.modules]\n"
        "print(','.join(bad))\n"
        "sys.exit(1 if bad else 0)\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, env=env)
    assert r.returncode == 0, f"gds_viz pulled deps eagerly: {r.stdout!r} {r.stderr!r}"
