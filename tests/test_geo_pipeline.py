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

import os
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
TWO_PADS_META = FIXTURES / "two_pads.meta.yaml"
SUNG_META = (Path(__file__).resolve().parents[1]
             / "examples" / "dsl" / "geo" / "sung_2021_device.meta.yaml")


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
    # Approach A: BOTH the metal pad AND the metal ground sheet are carved OUT
    # (voids), so only their *surface* groups are registered — there is NO 'P_pad'
    # or 'gnd_layer1' 3D volume group (M5a carves the metal ground like a terminal
    # so its wall is an EXTERIOR Ground boundary, unblocking the full-chip solve).
    names = set(pa)
    assert {"gnd_layer1_sfs", "substrate_layer3",
            "vacuum", "vacuum_outer", "P_pad_sfs"} <= names
    assert "P_pad" not in names       # carved conductor has no 3D volume group
    assert "gnd_layer1" not in names  # carved ground has no 3D volume group

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

    # metal::1::P::pad is carved (Approach A): geo_name_to_group still maps the
    # volume-name stem 'P_pad', but the REGISTERED group is the surface 'P_pad_sfs'.
    assert geo_name_to_group("metal", 1, "P", "pad") == "P_pad"
    assert "P_pad_sfs" in names
    # ground::1::chip::gnd is carved (M5a Approach A): geo_name_to_group maps the
    # volume-name stem 'gnd_layer1', but the REGISTERED group is the *surface*
    # 'gnd_layer1_sfs' (no 3D ground volume — same as the carved pad terminals).
    assert geo_name_to_group("ground", 1, "chip", "gnd") == "gnd_layer1"
    assert "gnd_layer1_sfs" in names
    assert "gnd_layer1" not in names
    # dielectric substrate auto-derived for layer 3 -> 'substrate_layer3'.
    assert geo_name_to_group("substrate", 3, "chip", "sub") == "substrate_layer3"
    assert "substrate_layer3" in names


# -----------------------------------------------------------------------------
# two_pads: conductors-as-voids carve -> only *_sfs terminals, no 3D conductor vol
# -----------------------------------------------------------------------------

def test_two_pads_carve_groups(tmp_path):
    """Approach A on the clean 2-conductor reference: two carved terminals
    (A_pad_sfs, B_pad_sfs) + substrate + vacuum + vacuum_outer; NO pad volumes."""
    meta = parse_geo_meta_sidecar(TWO_PADS_META)
    res = build_mesh_from_geo(
        meta["geo"], meta["simulation"]["gmsh"],
        output_path=tmp_path / "chip.msh", generate=True)
    names = set(res.physical_groups)
    assert {"A_pad_sfs", "B_pad_sfs", "substrate_layer3",
            "vacuum", "vacuum_outer"} <= names
    # carved conductors have no 3D volume group, and there is no ground sheet.
    assert "A_pad" not in names and "B_pad" not in names
    assert not any(n.startswith("gnd_") for n in names)


# -----------------------------------------------------------------------------
# shipped example: examples/dsl/geo/sung_2021_device — GDS + mesh + Palace config
# -----------------------------------------------------------------------------

# Runs in a SUBPROCESS (see the test's docstring): gmsh keeps compiled .geo
# ``Macro``s in a PROCESS-GLOBAL table that survives finalize() while qlib.geo's
# ``_QLIB_INCLUDED`` include-guard constant does not, so merging qlib.geo in this
# process would make every LATER test that merges it (e.g.
# tests/test_geo_topology.py::test_examples_fragment_to_clean_topology) die with
# "Redefinition of function PAD".
_SUNG_BUILD_CHILD = r'''
import json, sys
from pathlib import Path
import gmsh
from quantum_dsl.dsl.gds_adapter import build_gds
from quantum_dsl.dsl.gmsh_adapter import build_mesh_from_geo
from quantum_dsl.dsl.palace_adapter import (build_palace_config,
                                            validate_config,
                                            write_palace_config)
from quantum_dsl.dsl.parsers.simulation import parse_geo_meta_sidecar

meta_path, out = Path(sys.argv[1]), Path(sys.argv[2])
meta = parse_geo_meta_sidecar(meta_path)
sim = meta["simulation"]["gmsh"]
# coarsened on purpose: this guards topology + naming, not capacitance accuracy.
sim["mesh"] = {"max_size": 200, "min_size": 8,
               "conductor_refine": {"min_dist": 8, "max_dist": 60}}
gmsh.initialize()                      # one session spans both branches
gmsh.option.setNumber("General.Terminal", 0)
build_gds(meta["geo"], output_path=out / "chip.gds")
res = build_mesh_from_geo(meta["geo"], sim, output_path=out / "chip.msh",
                          generate=True)
gmsh.finalize()
s = sim["solver"]
cfg = build_palace_config(res.physical_attributes, res.options.layer_stack,
                          l0=float(s["l0"]), order=int(s["order"]),
                          ground_outer=s["outer_boundary"] != "open",
                          mesh_path=res.mesh_path.name)
validate_config(cfg, res.physical_attributes)
write_palace_config(cfg, out / "chip.json")
print(json.dumps(sorted(res.physical_groups)))
'''


def test_sung_2021_example_builds_differential_islands(tmp_path):
    """The shipped Sung-2021 example builds GDS + mesh + Palace config (no solve),
    keeps its 10 physical groups, and declares every transmon as TWO islands.

    One island per qubit silently grounds the other pad of a floating transmon
    (1.70x on C_Sigma / E_C for this device), so the two-island declaration and
    the pad group names it references are part of the example's contract.
    """
    import json
    import os
    import subprocess
    import sys

    meta = parse_geo_meta_sidecar(SUNG_META)
    qubits = meta["circuit_model"]["qubits"]
    assert [q["name"] for q in qubits] == ["QB1", "CPLR", "QB2"]
    assert [len(q["islands"]) for q in qubits] == [2, 2, 2]

    env = dict(os.environ)
    src_root = Path(geo.__file__).resolve().parents[2]   # .../src
    env["PYTHONPATH"] = os.pathsep.join(
        [str(src_root)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    proc = subprocess.run(
        [sys.executable, "-c", _SUNG_BUILD_CHILD, str(SUNG_META), str(tmp_path)],
        capture_output=True, text=True, env=env, timeout=1800)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]

    groups = json.loads(proc.stdout.strip().splitlines()[-1])
    assert set(groups) == {
        "QB1_pad_top_sfs", "QB1_pad_bot_sfs",
        "CPLR_pad_top_sfs", "CPLR_pad_bot_sfs",
        "QB2_pad_top_sfs", "QB2_pad_bot_sfs",
        "gnd_layer1_sfs", "substrate_layer3", "vacuum", "vacuum_outer"}
    # every declared island is a real conductor terminal group
    for qubit in qubits:
        for island in qubit["islands"]:
            assert island in groups, island
    for name in ("chip.gds", "chip.msh", "chip.json"):
        assert (tmp_path / name).is_file(), name


# -----------------------------------------------------------------------------
# LIVE Palace solve (gated): two_pads -> known-sign 2x2 capacitance matrix.
# Slow + needs Palace (native or WSL spack). Enable with QDSL_RUN_PALACE=1.
# -----------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.environ.get("QDSL_RUN_PALACE"),
    reason="live Palace solve; set QDSL_RUN_PALACE=1 (needs Palace/WSL spack)")
def test_build_geo_archives_inputs_and_writes_manifest(tmp_path):
    """每次 build 都把 meta.yaml + .geo 复制进 out_dir, 并写 chip.manifest.yaml
    (输入副本 + 全部产物的 sha256/时间戳); 此处不跑 Palace, 故无 results 条目。"""
    import hashlib
    import yaml
    from quantum_dsl.dsl.geo_build import build_geo

    res = build_geo(meta_path=str(TWO_PADS_META), out_dir=str(tmp_path),
                    run_palace=False)

    # input copies present with original names
    meta_copy = tmp_path / TWO_PADS_META.name
    assert meta_copy.is_file()
    geo_name = parse_geo_meta_sidecar(TWO_PADS_META)["geo"].name
    assert (tmp_path / geo_name).is_file()

    assert res["manifest"] == tmp_path / "chip.manifest.yaml"
    doc = yaml.safe_load(res["manifest"].read_text(encoding="utf-8"))
    assert doc["schema"] == "quantum-dsl/build-manifest/1"

    by_name = {f["name"]: f for f in doc["files"]}
    # inputs (both copies) + outputs (gds/msh/json) recorded; no results.yaml.
    assert by_name[TWO_PADS_META.name]["role"] == "input"
    assert by_name[geo_name]["role"] == "input"
    assert {"chip.gds", "chip.msh", "chip.json"} <= set(by_name)
    assert "chip.results.yaml" not in by_name

    # every record has a sha256 / bytes / modified_utc, and the sha is correct.
    for rec in doc["files"]:
        assert rec["sha256"] and rec["bytes"] > 0 and rec["modified_utc"]
    gds_bytes = (tmp_path / "chip.gds").read_bytes()
    assert by_name["chip.gds"]["sha256"] == hashlib.sha256(gds_bytes).hexdigest()


def test_two_pads_live_capacitance_matrix(tmp_path):
    import yaml
    from quantum_dsl.dsl.geo_build import build_geo

    res = build_geo(meta_path=str(TWO_PADS_META), out_dir=str(tmp_path),
                    run_palace=True, dry_run=False)
    assert res["results"] is not None, "no chip.results.yaml produced"

    # a real solve -> manifest also lists the chip.results.yaml output.
    man = yaml.safe_load(Path(res["manifest"]).read_text(encoding="utf-8"))
    assert "chip.results.yaml" in {f["name"] for f in man["files"]}
    doc = yaml.safe_load(Path(res["results"]).read_text(encoding="utf-8"))

    cap = doc["capacitance"]
    assert cap["available"] is True and cap["units"] == "fF"
    # row/col binding = the two carved terminals, in sorted order.
    assert [t["group"] for t in cap["terminals"]] == ["A_pad_sfs", "B_pad_sfs"]

    m = cap["maxwell"]            # Maxwell matrix: +diagonal, -offdiagonal, symmetric
    assert len(m) == 2 and len(m[0]) == 2
    assert m[0][0] > 0 and m[1][1] > 0
    assert m[0][1] < 0 and m[1][0] < 0
    assert abs(m[0][1] - m[1][0]) < 1e-6
    cm = cap["mutual"]           # mutual matrix: all-positive
    assert all(cm[i][j] > 0 for i in range(2) for j in range(2))
    # consistency: Cm[0][0] == C[0][0] + C[0][1];  Cm[0][1] == -C[0][1]
    assert abs(cm[0][0] - (m[0][0] + m[0][1])) < 1e-6
    assert abs(cm[0][1] - (-m[0][1])) < 1e-6

    # M6: the sidecar's circuit_model block -> tier-2 derived Hamiltonian section
    # written into the SAME results artifact by build_geo (two grounded transmons).
    assert doc["tier"] == 2                      # descending: 2 = +Hamiltonian
    ham = doc["hamiltonian"]
    assert ham["method"] == "lumped_oscillator_inverse_cap"
    assert [q["name"] for q in ham["qubits"]] == ["A", "B"]
    for q in ham["qubits"]:
        assert q["E_C_GHz"] > 0 and q["E_J_GHz"] > 0
        assert q["f01_GHz"] > 0
        assert q["anharmonicity_MHz"] < 0        # alpha = -E_C
        assert q["EJ_over_EC"] > 0
    assert len(ham["couplings"]) == 1
    g = ham["couplings"][0]
    assert {g["qubit_a"], g["qubit_b"]} == {"A", "B"}
    assert g["C_g_fF"] > 0 and g["g_MHz"] > 0
    # provenance records the authored junction inputs
    assert "circuit_model_inputs" in doc["provenance"]


# -----------------------------------------------------------------------------
# carve_conductors — split vacuum is KEPT (multi-volume), empty vacuum raises
# -----------------------------------------------------------------------------

def test_carve_conductors_keeps_all_split_vacuum_volumes():
    """A carve that severs the vacuum into several connected volumes keeps ALL.

    A ground-plane + lead design pinches the thin metal-layer vacuum into the
    pocket interior plus one sliver per lead CPW-gap; every piece is still part
    of the dielectric domain. Earlier code raised on a split (after an even-older
    warn-and-drop that solved on an INCOMPLETE domain). Now carve retains every
    post-cut volume — vacuum_box (largest) + vacuum_extra — so
    assign_physical_groups can tag them all 'vacuum' and Palace solves the full
    domain. Regression: ground+lead designs (e.g. the transmon cell) must build.
    """
    from quantum_dsl.dsl._gmsh_geometry import GeomTracker
    from quantum_dsl.dsl._gmsh_layers import carve_conductors

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("carve_split")
    vac = gmsh.model.occ.addBox(0, 0, 0, 10, 10, 10)
    # A slab spanning the full x-y cross-section, bisecting the box in z: carving
    # it out severs the vacuum into two disconnected halves (z<4.5 and z>5.5).
    slab = gmsh.model.occ.addBox(-1, -1, 4.5, 12, 12, 1.0)
    gmsh.model.occ.synchronize()

    tr = GeomTracker()
    tr.vacuum_box = vac
    tr.conductor_solids = {1: {("Q", "wall"): [slab]}}

    carve_conductors(tr)  # must NOT raise — both halves are vacuum
    all_vac = [tr.vacuum_box, *tr.vacuum_extra]
    assert len(all_vac) == 2, f"expected both severed halves kept, got {all_vac}"
    assert tr.vacuum_box is not None
    model_vols = {t for (d, t) in gmsh.model.getEntities(3)}
    assert set(all_vac) <= model_vols
    # vacuum_box is the larger half (sorted by volume): both halves ~ 4.5*100.
    # autouse _clean_gmsh_session finalizes the session afterwards.


def test_carve_conductors_raises_when_vacuum_fully_consumed():
    """If the carve tools cover the ENTIRE vacuum box (0 volumes remain) that is
    a genuine authoring error and must still raise (not silently produce an
    empty dielectric domain)."""
    from quantum_dsl.dsl._gmsh_geometry import GeomTracker
    from quantum_dsl.dsl._gmsh_layers import carve_conductors
    from quantum_dsl.dsl.errors import DesignDslError

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("carve_consume")
    vac = gmsh.model.occ.addBox(0, 0, 0, 10, 10, 10)
    big = gmsh.model.occ.addBox(-1, -1, -1, 12, 12, 12)  # fully contains vac
    gmsh.model.occ.synchronize()

    tr = GeomTracker()
    tr.vacuum_box = vac
    tr.conductor_solids = {1: {("Q", "all"): [big]}}

    with pytest.raises(DesignDslError, match="0 volumes remain"):
        carve_conductors(tr)
    # autouse _clean_gmsh_session finalizes the session afterwards.


# -----------------------------------------------------------------------------
# generate_mesh — silent-empty 3D failure must trigger the HXT fallback
# -----------------------------------------------------------------------------

def test_generate_mesh_silent_empty_falls_back_to_hxt(monkeypatch):
    """Newer gmsh builds (conda-forge 4.11.1 / pip 4.15.2) LOG the coplanar
    "PLC Error" and return normally with an EMPTY 3D mesh instead of raising —
    generate_mesh must detect the empty mesh and still fall back to HXT
    (regression: qm4q silently wrote a 533-byte 0-element chip.msh)."""
    from quantum_dsl.dsl._gmsh_mesh import generate_mesh

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("silent_empty")
    gmsh.model.occ.addBox(0, 0, 0, 1, 1, 1)
    gmsh.model.occ.synchronize()

    real_generate = gmsh.model.mesh.generate
    calls = {"n": 0}

    def first_call_silently_fails(dim=3):
        calls["n"] += 1
        if calls["n"] == 1:
            return  # simulate: PLC error logged, no exception, no elements
        real_generate(dim)

    monkeypatch.setattr(gmsh.model.mesh, "generate", first_call_silently_fails)
    generate_mesh(dim=3)

    assert calls["n"] == 2, "empty first pass must trigger exactly one retry"
    _, element_tags, _ = gmsh.model.mesh.getElements(3)
    assert sum(len(t) for t in element_tags) > 0, "HXT fallback must produce a mesh"
    assert gmsh.option.getNumber("Mesh.Algorithm3D") == 1  # default restored


def test_generate_mesh_raises_when_hxt_also_empty(monkeypatch):
    """If the HXT fallback ALSO yields no 3D elements, generate_mesh must raise
    instead of letting the caller write an empty (unsolvable) mesh."""
    from quantum_dsl.dsl._gmsh_mesh import generate_mesh

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("always_empty")
    gmsh.model.occ.addBox(0, 0, 0, 1, 1, 1)
    gmsh.model.occ.synchronize()

    monkeypatch.setattr(gmsh.model.mesh, "generate", lambda dim=3: None)

    with pytest.raises(RuntimeError, match="no elements"):
        generate_mesh(dim=3)
