# -*- coding: utf-8 -*-
"""End-to-end ``.geo`` pipeline tests (gated on gmsh + gdstk).

Exercises the real backends against ``tests/fixtures/tiny_chip.geo``:
- ``load_geo`` finds the authored ``::`` surfaces;
- ``build_gds`` round-trips area/bbox within tolerance, maps a known feature
  size 1:1 (NO SI scaling), and writes ``lib.unit == 1e-6``;
- ``build_mesh_from_geo`` yields a non-empty ``physical_attributes`` map with
  unique ints and the expected key groups;
- single-rectangle parity: geo-path output group names match the
  ``geo_name_to_group`` expectations for each authored surface.

Each adapter owns its own gmsh session (initializes + finalizes when the caller
hasn't initialized), so the tests call them on a clean session and let them
clean up. ``load_geo`` does NOT finalize — the test owns and finalizes that one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

gmsh = pytest.importorskip("gmsh")
gdstk = pytest.importorskip("gdstk")

from quantum_dsl.dsl import _gmsh_geo_source as geo  # noqa: E402
from quantum_dsl.dsl.gds_adapter import build_gds, verify_roundtrip  # noqa: E402
from quantum_dsl.dsl.gmsh_adapter import build_mesh_from_geo  # noqa: E402
from quantum_dsl.dsl.parsers.simulation import (  # noqa: E402
    parse_geo_meta_sidecar,
)
from quantum_dsl.dsl._gmsh_physical import geo_name_to_group  # noqa: E402


FIXTURES = Path(__file__).resolve().parent / "fixtures"
TINY_GEO = FIXTURES / "tiny_chip.geo"
TINY_META = FIXTURES / "tiny_chip.meta.yaml"


@pytest.fixture(autouse=True)
def _clean_gmsh_session():
    """Each test starts and ends with gmsh finalized (adapters self-own)."""
    if gmsh.isInitialized():
        gmsh.finalize()
    yield
    if gmsh.isInitialized():
        gmsh.finalize()


# -----------------------------------------------------------------------------
# load_geo — finds the authored '::' surfaces
# -----------------------------------------------------------------------------

def test_load_geo_finds_tagged_surfaces():
    surfaces = geo.load_geo(TINY_GEO, scale_to_si=False)
    try:
        ids = {(s.role, s.layer, s.component, s.primitive) for s in surfaces}
        assert ("metal", 1, "P", "pad") in ids
        assert ("ground", 1, "chip", "gnd") in ids
        # both authored surfaces are 2D with at least one entity each.
        for s in surfaces:
            assert s.dim == 2
            assert len(s.entities) >= 1
    finally:
        # load_geo never finalizes — the caller (this test) owns the session.
        if gmsh.isInitialized():
            gmsh.finalize()


def test_load_geo_microns_not_scaled():
    """scale_to_si=False keeps microns: pad bbox extent == 100 x 60 µm."""
    surfaces = geo.load_geo(TINY_GEO, scale_to_si=False)
    try:
        pad = next(s for s in surfaces
                   if s.role == "metal" and s.primitive == "pad")
        x0, y0, _z0, x1, y1, _z1 = gmsh.model.getBoundingBox(2, pad.entities[0])
        assert (x1 - x0) == pytest.approx(100.0, abs=1e-6)
        assert (y1 - y0) == pytest.approx(60.0, abs=1e-6)
    finally:
        if gmsh.isInitialized():
            gmsh.finalize()


# -----------------------------------------------------------------------------
# build_gds — round-trip + 1:1 micron feature + lib.unit
# -----------------------------------------------------------------------------

def test_build_gds_roundtrip_and_units(tmp_path):
    out = tmp_path / "chip.gds"
    res = build_gds(TINY_GEO, output_path=out)
    assert res.gds_path == out
    assert out.is_file()

    # The ground sheet is 300 x 300 µm centered at origin -> extent 300 (1:1,
    # NO SI scaling).  100µm-class features pass through verbatim.
    xmin, ymin, xmax, ymax = res.bbox_um
    assert (xmax - xmin) == pytest.approx(300.0, abs=1e-3)
    assert (ymax - ymin) == pytest.approx(300.0, abs=1e-3)

    # gdstk library unit/precision: microns verbatim.
    lib = gdstk.read_gds(str(out))
    assert lib.unit == pytest.approx(1e-6)
    assert lib.precision == pytest.approx(1e-9)

    # geometric round-trip: per-layer area + bbox within tolerance.
    report = verify_roundtrip(res, rel_area_tol=1e-3, bbox_grid_tol=1.0)
    assert report["ok"], report["issues"]


def test_build_gds_default_layer_map_emits_layer_1_0(tmp_path):
    """metal + ground default to GDS layer 1/0 -> one merged polygon set."""
    res = build_gds(TINY_GEO, output_path=tmp_path / "chip.gds")
    assert (1, 0) in res.polygons_by_layer
    assert res.polygons_by_layer[(1, 0)] >= 1


# -----------------------------------------------------------------------------
# build_mesh_from_geo — physical_attributes non-empty, unique, expected groups
# -----------------------------------------------------------------------------

def test_build_mesh_from_geo_physical_attributes(tmp_path):
    meta = parse_geo_meta_sidecar(TINY_META)
    sim_gmsh = meta["simulation"]["gmsh"]
    res = build_mesh_from_geo(
        meta["geo"], sim_gmsh, output_path=tmp_path / "chip.msh",
        generate=True)

    pa = res.physical_attributes
    assert pa, "physical_attributes must be non-empty for a generated mesh"
    # unique integer attributes.
    assert len(set(pa.values())) == len(pa)
    assert all(isinstance(v, int) for v in pa.values())

    # expected key groups (byte-identical to the YAML path naming).
    names = set(pa)
    assert {"gnd_layer1", "gnd_layer1_sfs", "substrate_layer3",
            "vacuum", "vacuum_outer", "P_pad", "P_pad_sfs"} <= names

    # physical_groups and physical_attributes cover the same name set.
    assert set(res.physical_groups) == names
    # geo path carries no DesignIR.
    assert res.ir is None
    # msh2.2 written to disk for Palace.
    assert res.mesh_path is not None and res.mesh_path.is_file()


# -----------------------------------------------------------------------------
# single-rectangle parity: geo-path group names == geo_name_to_group expectation
# -----------------------------------------------------------------------------

def test_geo_group_names_match_geo_name_to_group(tmp_path):
    """Every authored surface's output group name equals geo_name_to_group()."""
    meta = parse_geo_meta_sidecar(TINY_META)
    res = build_mesh_from_geo(
        meta["geo"], meta["simulation"]["gmsh"],
        output_path=tmp_path / "chip.msh", generate=True)
    names = set(res.physical_groups)

    # metal::1::P::pad -> volume 'P_pad' (geo_name_to_group is the bridge).
    assert geo_name_to_group("metal", 1, "P", "pad") == "P_pad"
    assert geo_name_to_group("metal", 1, "P", "pad") in names
    # ground::1::chip::gnd -> 'gnd_layer1'.
    assert geo_name_to_group("ground", 1, "chip", "gnd") == "gnd_layer1"
    assert geo_name_to_group("ground", 1, "chip", "gnd") in names
    # dielectric substrate auto-derived for layer 3 -> 'substrate_layer3'.
    assert geo_name_to_group("substrate", 3, "chip", "sub") == "substrate_layer3"
    assert "substrate_layer3" in names
