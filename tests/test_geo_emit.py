# -*- coding: utf-8 -*-
"""M5a — emit_geo cell-library bridge + Elaborator + ``cells:`` sidecar.

Verifies that lowering a resolved v3 ``DesignIR`` → a flat positive-tone native
``.geo`` (``emit_geo``) feeds the existing GDS + mesh + Palace pipeline unchanged:

* physical names follow the ``role::layer::component::primitive`` contract;
* path/junction primitives buffer to **rounded** polygon ``Line`` segments;
* one chip-wide ground per layer aggregates every ``subtract:true`` primitive as
  holes (decision #1);
* **golden parity**: an emit_geo cell and a hand-authored equivalent ``.geo``
  produce byte-identical mesh physical-group names + GDS layers;
* the ``cells:`` sidecar + Elaborator wire through ``build_geo`` end-to-end.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

gmsh = pytest.importorskip("gmsh")
gdstk = pytest.importorskip("gdstk")

from quantum_dsl.dsl import _gmsh_geo_source as geo  # noqa: E402
from quantum_dsl.dsl.builder import build_ir  # noqa: E402
from quantum_dsl.dsl.errors import DesignDslError  # noqa: E402
from quantum_dsl.dsl.gds_adapter import build_gds, verify_roundtrip  # noqa: E402
from quantum_dsl.dsl.geo_build import build_geo  # noqa: E402
from quantum_dsl.dsl.geo_emit import elaborate_cells, emit_geo  # noqa: E402
from quantum_dsl.dsl.gmsh_adapter import build_mesh_from_geo  # noqa: E402
from quantum_dsl.dsl.parsers.simulation import parse_geo_meta_sidecar  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_gmsh_session():
    """Each test starts and ends with gmsh finalized (adapters self-own)."""
    if gmsh.isInitialized():
        gmsh.finalize()
    yield
    if gmsh.isInitialized():
        gmsh.finalize()


# --- a small all-poly cell: emit_geo output is geometrically identical to a
#     hand-authored .geo (poly rects + flat-capped jj rect), so the two paths'
#     mesh group names + GDS layers must match byte-for-byte. ------------------
PARITY_CELL_YAML = """
schema: qiskit-metal/design-dsl/3
geometry:
  design: {class: DesignPlanar, chip: {size: 4mm x 4mm}}
  components:
    Q1:
      primitives:
        - {name: pad_top, type: poly.rectangle, center: [0um, 40um], size: [160um, 50um], layer: 1}
        - {name: pad_bot, type: poly.rectangle, center: [0um, -40um], size: [160um, 50um], layer: 1}
        - {name: pocket, type: poly.rectangle, center: [0um, 0um], size: [240um, 240um], subtract: true, layer: 1}
        - {name: jj, type: junction.line, points: [[0um, -15um], [0um, 15um]], width: 6um, layer: 1}
"""

# Hand-authored equivalent.  feature bbox = pocket ±120 µm; default
# ground_margin_um = 120 → ground rect ±240 µm with the pocket punched as a hole.
PARITY_HAND_GEO = """SetFactory("OpenCASCADE");
a = news; Rectangle(a) = { -80, 15, 0, 160, 50 };
Physical Surface("metal::1::Q1::pad_top") = { a };
b = news; Rectangle(b) = { -80, -65, 0, 160, 50 };
Physical Surface("metal::1::Q1::pad_bot") = { b };
j = news; Rectangle(j) = { -3, -15, 0, 6, 30 };
Physical Surface("jj::1::Q1::jj") = { j };
g = news; Rectangle(g) = { -240, -240, 0, 480, 480 };
h = news; Rectangle(h) = { -120, -120, 0, 240, 240 };
d() = BooleanDifference{ Surface{ g }; Delete; }{ Surface{ h }; Delete; };
Physical Surface("ground::1::chip::gnd") = { d() };
"""

# Coarse Layer-1 metadata so the mesh + Palace config build quickly.
SIM_GMSH = {
    "layer_stack": {
        1: {"kind": "metal", "thickness": 2, "z": 0, "material": "pec"},
        3: {"kind": "dielectric", "thickness": -380, "z": 0,
            "material": "silicon", "eps_r": 11.45},
    },
    "airbox": {"top": 300, "bottom": 400, "side_buffer": 150},
    "mesh": {"max_size": 160, "min_size": 30},
    "gds": {
        "lib_name": "emit", "top_cell": "emit", "unit": 1.0e-6,
        "precision": 1.0e-9,
        "by_role": {"metal": {"layer": 1, "datatype": 0},
                    "ground": {"layer": 1, "datatype": 0}},
    },
    "solver": {"type": "Electrostatic", "order": 2, "l0": 1.0},
}


def _geo_ids(geo_path):
    """The set of (role, layer, component, primitive) tuples authored in a .geo."""
    surfaces = geo.load_geo(geo_path, scale_to_si=False)
    try:
        return {(s.role, s.layer, s.component, s.primitive) for s in surfaces}
    finally:
        if gmsh.isInitialized():
            gmsh.finalize()


def _mesh_group_names(geo_path, tmp_path, name):
    res = build_mesh_from_geo(
        geo_path, SIM_GMSH, output_path=tmp_path / f"{name}.msh", generate=True)
    try:
        return set(res.physical_groups)
    finally:
        if gmsh.isInitialized():
            gmsh.finalize()


# ---------------------------------------------------------------------------
# emit_geo — physical-name contract
# ---------------------------------------------------------------------------

def test_emit_geo_emits_binding_contract_names(tmp_path):
    """metal/jj primitives + a synthesized ground get role::layer::comp::prim names."""
    ir = build_ir(PARITY_CELL_YAML)
    out = tmp_path / "cell.geo"
    emit_geo(ir, out, emit_ports=False)
    ids = _geo_ids(out)
    assert ("metal", 1, "Q1", "pad_top") in ids
    assert ("metal", 1, "Q1", "pad_bot") in ids
    assert ("jj", 1, "Q1", "jj") in ids
    assert ("ground", 1, "chip", "gnd") in ids
    # the subtract pocket is NOT a standalone surface — it is a ground hole.
    assert ("metal", 1, "Q1", "pocket") not in ids


def test_emit_geo_is_pure_shapely_no_gmsh_gdstk():
    """emit_geo / the module must not import gmsh or gdstk."""
    import sys
    import importlib

    # importing the module fresh must not have pulled the optional backends.
    importlib.import_module("quantum_dsl.dsl.geo_emit")
    src = Path(
        importlib.import_module("quantum_dsl.dsl.geo_emit").__file__
    ).read_text(encoding="utf-8")
    assert "import gmsh" not in src
    assert "import gdstk" not in src


def test_emit_geo_buffers_path_to_rounded_polygon(tmp_path):
    """A path primitive becomes a closed polygon with rounded (sampled) corners."""
    ir = build_ir("""
schema: qiskit-metal/design-dsl/3
geometry:
  design: {class: DesignPlanar, chip: {size: 4mm x 4mm}}
  components:
    W:
      primitives:
        - {name: wire, type: path.polyline,
           points: [[0um, 0um], [100um, 0um], [100um, 100um]],
           width: 10um, layer: 1}
""")
    text = emit_geo(ir, tmp_path / "w.geo", arc_tol_um=0.5, emit_ports=False)
    assert 'Physical Surface("metal::1::W::wire")' in text
    # a round-joined buffer of an L-path samples the corner into many points →
    # far more than the 6 points a sharp mitre would give.
    n_points = text.count("Point(")
    assert n_points > 8, f"expected a sampled rounded polygon, got {n_points} points"


def test_emit_geo_port_markers_optional_and_loadable(tmp_path):
    """emit_ports=True emits a dim-1 port:: marker load_geo accepts; default = off."""
    ir = build_ir("""
schema: qiskit-metal/design-dsl/3
geometry:
  design: {class: DesignPlanar, chip: {size: 4mm x 4mm}}
  components:
    Q1:
      primitives:
        - {name: pad, type: poly.rectangle, center: [0um, 0um], size: [120um, 120um], layer: 1}
        - {name: pocket, type: poly.rectangle, center: [0um, 0um], size: [300um, 300um], subtract: true, layer: 1}
      pins:
        - {name: p, points: [[100um, -6um], [100um, 6um]], width: 12um}
""")
    # default: NO port markers (deferred contract — decision #2).
    off = emit_geo(ir, tmp_path / "off.geo")
    assert "Physical Curve" not in off
    # opt-in: a dim-1 port:: Physical Curve, accepted by load_geo as a marker role.
    on_path = tmp_path / "on.geo"
    on = emit_geo(ir, on_path, emit_ports=True)
    assert 'Physical Curve("port::1::Q1::p")' in on
    surfaces = geo.load_geo(on_path, scale_to_si=False)
    try:
        assert ("port", 1) in {(s.role, s.dim) for s in surfaces}
    finally:
        if gmsh.isInitialized():
            gmsh.finalize()


# ---------------------------------------------------------------------------
# Golden parity — emit_geo cell == hand-authored .geo (names + GDS + mesh)
# ---------------------------------------------------------------------------

def test_emit_geo_authored_ids_match_hand_geo(tmp_path):
    emitted = tmp_path / "emit.geo"
    emit_geo(build_ir(PARITY_CELL_YAML), emitted, emit_ports=False)
    hand = tmp_path / "hand.geo"
    hand.write_text(PARITY_HAND_GEO, encoding="utf-8")
    assert _geo_ids(emitted) == _geo_ids(hand)


def test_emit_geo_gds_layers_match_hand_geo(tmp_path):
    emitted = tmp_path / "emit.geo"
    emit_geo(build_ir(PARITY_CELL_YAML), emitted, emit_ports=False)
    hand = tmp_path / "hand.geo"
    hand.write_text(PARITY_HAND_GEO, encoding="utf-8")

    em = build_gds(emitted, output_path=tmp_path / "emit.gds",
                   layer_map=SIM_GMSH["gds"])
    assert verify_roundtrip(em)["ok"]
    if gmsh.isInitialized():
        gmsh.finalize()
    hd = build_gds(hand, output_path=tmp_path / "hand.gds",
                   layer_map=SIM_GMSH["gds"])
    if gmsh.isInitialized():
        gmsh.finalize()
    # metal+ground → layer (1,0); jj → layer (20,0).  Same layers AND per-layer
    # polygon counts (catches a duplicated/dropped/fragmented polygon regression).
    assert em.polygons_by_layer == hd.polygons_by_layer
    assert (1, 0) in em.polygons_by_layer and (20, 0) in em.polygons_by_layer
    # geometry parity: identical overall extents (both forks read the same .geo).
    assert em.bbox_um == pytest.approx(hd.bbox_um, abs=1e-6)


def test_emit_geo_mesh_group_names_byte_identical_to_hand_geo(tmp_path):
    """THE golden parity: final physical-group names match a hand-authored .geo."""
    emitted = tmp_path / "emit.geo"
    emit_geo(build_ir(PARITY_CELL_YAML), emitted, emit_ports=False)
    hand = tmp_path / "hand.geo"
    hand.write_text(PARITY_HAND_GEO, encoding="utf-8")

    emit_names = _mesh_group_names(emitted, tmp_path, "emit")
    hand_names = _mesh_group_names(hand, tmp_path, "hand")
    assert emit_names == hand_names
    # both carve pads + ground (Approach A): terminals + ground surface, no volumes.
    assert {"Q1_pad_top_sfs", "Q1_pad_bot_sfs", "gnd_layer1_sfs",
            "substrate_layer3", "vacuum", "vacuum_outer"} <= emit_names
    assert "gnd_layer1" not in emit_names  # carved ground → no 3D volume


# ---------------------------------------------------------------------------
# Elaborator + cells: sidecar
# ---------------------------------------------------------------------------

def test_elaborate_cells_rejects_duplicate_component(tmp_path):
    cells = [
        {"cell_type": "transmon_pocket", "component": "Q1",
         "params": {"connection_pads": {}}},
        {"cell_type": "transmon_pocket", "component": "Q1",
         "params": {"connection_pads": {}}},
    ]
    with pytest.raises(DesignDslError, match="duplicate component"):
        elaborate_cells(cells, tmp_path / "dup.geo", emit_ports=False)


def test_elaborate_cells_places_and_names_each_instance(tmp_path):
    cells = [
        {"cell_type": "transmon_pocket", "component": "Q1", "x": "-600um",
         "params": {"connection_pads": {}}},
        {"cell_type": "transmon_pocket", "component": "Q2", "x": "600um",
         "params": {"connection_pads": {}}},
    ]
    out = tmp_path / "two.geo"
    elaborate_cells(cells, out, emit_ports=False)
    ids = _geo_ids(out)
    assert ("metal", 1, "Q1", "pad_top") in ids
    assert ("metal", 1, "Q2", "pad_top") in ids
    # one chip-wide ground per layer (decision #1) — not one per cell.
    grounds = {(c, p) for (r, l, c, p) in ids if r == "ground"}
    assert grounds == {("chip", "gnd")}


def test_cells_sidecar_parses_without_geo_key(tmp_path):
    sidecar = tmp_path / "cells.meta.yaml"
    sidecar.write_text(
        "schema: qiskit-metal/design-dsl/3\n"
        "cells:\n"
        "  - {cell_type: transmon_pocket, component: Q1, params: {connection_pads: {}}}\n"
        "simulation:\n"
        "  gmsh:\n"
        "    layer_stack:\n"
        "      1: {kind: metal, thickness: 2, z: 0, material: pec}\n"
        "      3: {kind: dielectric, thickness: -380, z: 0, material: silicon, eps_r: 11.45}\n"
        "    airbox: {top: 300, bottom: 400, side_buffer: 150}\n"
        "    mesh: {max_size: 160, min_size: 30}\n"
        "    solver: {type: Electrostatic, order: 2, l0: 1.0}\n",
        encoding="utf-8")
    meta = parse_geo_meta_sidecar(sidecar)
    assert meta["geo"] is None
    assert len(meta["cells"]) == 1
    assert meta["cells"][0]["component"] == "Q1"


def test_cells_sidecar_rejects_duplicate_component(tmp_path):
    sidecar = tmp_path / "dup.meta.yaml"
    sidecar.write_text(
        "schema: qiskit-metal/design-dsl/3\n"
        "cells:\n"
        "  - {cell_type: transmon_pocket, component: Q1}\n"
        "  - {cell_type: transmon_pocket, component: Q1}\n",
        encoding="utf-8")
    with pytest.raises(DesignDslError, match="duplicate component"):
        parse_geo_meta_sidecar(sidecar)


# ---------------------------------------------------------------------------
# End-to-end: build_geo drives the cells: sidecar → GDS + mesh + Palace config
# ---------------------------------------------------------------------------

def _cells_sidecar_text():
    return (
        "schema: qiskit-metal/design-dsl/3\n"
        "cells:\n"
        "  - {cell_type: transmon_pocket, component: Q1, x: \"-700um\","
        " params: {connection_pads: {}}}\n"
        "  - {cell_type: transmon_pocket, component: Q2, x: \"700um\","
        " params: {connection_pads: {}}}\n"
        "simulation:\n"
        "  gmsh:\n"
        "    layer_stack:\n"
        "      1: {kind: metal, thickness: 2, z: 0, material: pec}\n"
        "      3: {kind: dielectric, thickness: -380, z: 0, material: silicon, eps_r: 11.45}\n"
        "    airbox: {top: 300, bottom: 400, side_buffer: 150}\n"
        "    mesh: {max_size: 200, min_size: 40}\n"
        "    gds:\n"
        "      lib_name: cells\n"
        "      top_cell: cells\n"
        "      unit: 1.0e-6\n"
        "      precision: 1.0e-9\n"
        "      by_role: {metal: {layer: 1, datatype: 0}, ground: {layer: 1, datatype: 0}}\n"
        "    solver: {type: Electrostatic, order: 2, l0: 1.0}\n"
    )


def test_build_geo_cells_sidecar_end_to_end(tmp_path):
    """A cells: sidecar elaborates → GDS + mesh + a >=2-terminal Palace config."""
    sidecar = tmp_path / "cells.meta.yaml"
    sidecar.write_text(_cells_sidecar_text(), encoding="utf-8")
    out = tmp_path / "out"
    res = build_geo(meta_path=str(sidecar), out_dir=str(out),
                    run_palace=False, dry_run=True)
    # the elaborated geo was generated and consumed by BOTH forks.
    assert (out / "cells.elaborated.geo").is_file()
    assert res["gds"] and Path(res["gds"]).is_file()
    assert res["msh"] and Path(res["msh"]).is_file()
    assert res["palace_json"] and Path(res["palace_json"]).is_file()
    names = set(res["physical_groups"])
    # four carved qubit-pad terminals + one carved chip ground.
    assert {"Q1_pad_top_sfs", "Q1_pad_bot_sfs",
            "Q2_pad_top_sfs", "Q2_pad_bot_sfs", "gnd_layer1_sfs"} <= names
