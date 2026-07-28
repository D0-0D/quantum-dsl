# -*- coding: utf-8 -*-
"""Post-fragment topology invariants + conductor-face attribution (silent-wrong
result class).

``occ.fragment`` can **silently** return a corrupt model (a duplicated body, a
body it failed to cut, a negative-area face) at a badly conditioned coordinate
scale, and ``resolve_conductor_faces`` used to attribute a face to whatever
entity's bbox contained its centroid — so a chip-wide ground would claim the
whole z=0 substrate/vacuum interface and Palace would ground the entire substrate
top with no error. These tests pin both guards.
"""

from __future__ import annotations

from pathlib import Path

import pytest

gmsh = pytest.importorskip("gmsh")

from quantum_dsl.dsl import gmsh_adapter  # noqa: E402
from quantum_dsl.dsl._gmsh_geometry import GeomTracker  # noqa: E402
from quantum_dsl.dsl._gmsh_layers import (  # noqa: E402
    _bbox_contains,
    _centroid_in_bbox,
    check_fragment_topology,
    resolve_conductor_faces,
)
from quantum_dsl.dsl.errors import DesignDslError  # noqa: E402
from quantum_dsl.dsl.parsers.simulation import (  # noqa: E402
    parse_geo_meta_sidecar,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "dsl" / "geo"


@pytest.fixture(autouse=True)
def _clean_gmsh_session():
    """Each test starts and ends with gmsh finalized."""
    if gmsh.isInitialized():
        gmsh.finalize()
    yield
    if gmsh.isInitialized():
        gmsh.finalize()


def _session(name: str) -> None:
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add(name)


# -----------------------------------------------------------------------------
# check_fragment_topology — overlapping / duplicated bodies must raise
# -----------------------------------------------------------------------------

def test_overlapping_volumes_raise():
    """Two volumes occupying the same space = fragment silently failed.

    Reproduces the shape of the observed corruption (sung_2021_device at
    FRAGMENT_SCALE=1e6: the dielectric substrate present TWICE, and a vacuum box
    OCC never cut). Detected by "sum of volumes > model bbox volume", which no
    non-overlapping set of bodies can violate.
    """
    _session("overlap")
    gmsh.model.occ.addBox(0, 0, 0, 1e-4, 1e-4, 1e-4)
    gmsh.model.occ.addBox(0, 0, 0, 1e-4, 1e-4, 1e-4)  # exact duplicate
    gmsh.model.occ.synchronize()

    with pytest.raises(DesignDslError, match="volumes OVERLAP"):
        check_fragment_topology()


def test_disjoint_volumes_pass():
    """A healthy fragment output (bodies tiling their bbox) must NOT raise."""
    _session("disjoint")
    gmsh.model.occ.addBox(0, 0, 0, 1e-4, 1e-4, 1e-4)
    gmsh.model.occ.addBox(1e-4, 0, 0, 1e-4, 1e-4, 1e-4)
    gmsh.model.occ.synchronize()

    check_fragment_topology()  # must not raise


def test_negative_area_face_raises(monkeypatch):
    """A dim-2 entity with negative ``occ.getMass`` is a corrupt face.

    That is how OCC reported the broken faces it emitted on sung_2021_device
    (surf 231, -7.008e5 µm²).  A negative area cannot be built through the OCC
    API on purpose, so the reading is stubbed for the one offending face and the
    rest of the model is real.
    """
    _session("negmass")
    surf = gmsh.model.occ.addRectangle(0, 0, 0, 1e-4, 1e-4)
    gmsh.model.occ.synchronize()
    real_get_mass = gmsh.model.occ.getMass
    monkeypatch.setattr(
        gmsh.model.occ, "getMass",
        lambda dim, tag: (-real_get_mass(dim, tag)
                          if (dim, tag) == (2, surf) else
                          real_get_mass(dim, tag)))

    with pytest.raises(DesignDslError, match="NEGATIVE mass"):
        check_fragment_topology()


# -----------------------------------------------------------------------------
# resolve_conductor_faces — centroid alone is NOT enough (extent must match too)
# -----------------------------------------------------------------------------

def _carved_ground_model() -> tuple[GeomTracker, int, int]:
    """Vacuum box with a small ground sheet carved out of its z=0 floor.

    Returns ``(tracker, floor_face, cavity_face_count)``.  ``floor_face`` is the
    vacuum's own z=0 floor: it spans the WHOLE footprint yet its centroid sits at
    (0, 0, 0) — squarely inside the chip-wide ground's bbox.  A pure centroid test
    hands the whole floor to the ground (Palace then grounds the entire substrate
    top: a wrong answer with no error).
    """
    _session("carved_ground")
    half = 1e-4          # 100 µm half-width of the vacuum footprint
    gnd_half = 2e-5      # 20 µm half-width of the ground sheet
    thick = 2e-6         # 2 µm metal thickness
    vac = gmsh.model.occ.addBox(-half, -half, 0.0, 2 * half, 2 * half, 5e-4)
    gnd = gmsh.model.occ.addBox(-gnd_half, -gnd_half, 0.0,
                                2 * gnd_half, 2 * gnd_half, thick)
    gmsh.model.occ.synchronize()
    gnd_bbox = gmsh.model.getBoundingBox(3, gnd)
    out, _ = gmsh.model.occ.cut([(3, vac)], [(3, gnd)],
                                removeObject=True, removeTool=True)
    gmsh.model.occ.synchronize()

    tracker = GeomTracker()
    tracker.vacuum_box = [t for (d, t) in out if d == 3][0]
    tracker.ground_bbox = {1: gnd_bbox}

    floor_face = None
    for dim, tag in gmsh.model.getBoundary(
            [(3, tracker.vacuum_box)], combined=True, oriented=False):
        face = abs(int(tag))
        bb = gmsh.model.getBoundingBox(2, face)
        if abs(bb[5] - bb[2]) < thick / 2 and bb[0] < -half / 2:
            floor_face = face  # the full-footprint z=0 floor
    assert floor_face is not None, "fixture did not produce a z=0 floor face"
    return tracker, floor_face, gnd_bbox


def test_ground_cannot_claim_a_face_larger_than_itself():
    tracker, floor_face, gnd_bbox = _carved_ground_model()
    floor_bb = gmsh.model.getBoundingBox(2, floor_face)
    floor_com = gmsh.model.occ.getCenterOfMass(2, floor_face)

    # the ground's bbox DOES contain the floor's centroid — this is exactly why
    # the old centroid-only test mis-attributed it ...
    assert _centroid_in_bbox(gnd_bbox, floor_com)
    # ... and exactly why the extent test is needed.
    assert not _bbox_contains(gnd_bbox, floor_bb)

    # layer_stack with no dielectric layer: the domain is the vacuum alone, so
    # its z=0 floor stays on the combined boundary and reaches attribution.
    resolve_conductor_faces(tracker, {1: {"kind": "metal", "z": 0.0,
                                          "thickness": 2e-6}})

    assert floor_face not in tracker.ground_faces.get(1, []), (
        "the chip-wide ground claimed a face spanning the whole footprint")
    assert floor_face in tracker.vacuum_outer_faces
    # the ground still owns its real cavity walls (4 sides + top).
    assert len(tracker.ground_faces.get(1, [])) == 5


def test_carved_terminal_with_no_faces_raises():
    """A terminal that resolves to 0 faces = a silently missing Palace boundary
    (one fewer row/column in the capacitance matrix)."""
    _session("orphan_terminal")
    gmsh.model.occ.addBox(0, 0, 0, 1e-4, 1e-4, 1e-4)
    gmsh.model.occ.synchronize()

    tracker = GeomTracker()
    tracker.vacuum_box = 1
    # bbox far outside the vacuum: no boundary face can be attributed to it.
    tracker.conductor_bbox = {(1, "Q1", "pad"): (1.0, 1.0, 1.0, 1.1, 1.1, 1.1)}

    with pytest.raises(DesignDslError, match="0 boundary faces"):
        resolve_conductor_faces(tracker, {1: {"kind": "metal", "z": 0.0,
                                              "thickness": 2e-6}})


def test_examples_fragment_to_clean_topology(monkeypatch):
    """FRAGMENT_SCALE regression: every shipped geo example must fragment clean.

    Fails at the previous FRAGMENT_SCALE=1e6 (and at 1e4) for
    ``sung_2021_device`` — OCC silently returned 3 volumes, the substrate
    duplicated and the vacuum never cut, plus a negative-area face — and at scale
    1/10/1e4 for ``qm4q_transmon_cell`` ("Boolean fragments failed"). The mesher
    is stubbed out: this pins the GEOMETRY, which is what the scale affects,
    without paying for a 3D mesh (the full scale matrix is in
    ``fragment_everything``).

    Both examples run in ONE gmsh session owned by the test: gmsh's ``.geo``
    parser keeps compiled ``Macro``s in a process-global table that survives
    ``finalize()`` while the ``qlib.geo`` include-guard constant does not, so a
    second ``Include`` after a finalize would raise "Redefinition of function"
    (see the note in ``load_geo``).
    """
    monkeypatch.setattr(gmsh_adapter, "generate_mesh", lambda **kw: None)
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    for stem in ("sung_2021_device", "qm4q_transmon_cell"):
        meta_path = EXAMPLES / f"{stem}.meta.yaml"
        if not meta_path.is_file():  # pragma: no cover — examples are optional
            pytest.skip(f"{meta_path} not present")
        sim = (parse_geo_meta_sidecar(meta_path)["simulation"])["gmsh"]

        result = gmsh_adapter.build_mesh_from_geo(
            EXAMPLES / f"{stem}.geo", sim, output_path=None, generate=True)

        # exactly one substrate body and one vacuum body — the corruption showed
        # up as a SECOND, duplicated substrate volume. (check_fragment_topology
        # and _check_carved_faces have already raised on the other modes.)
        groups = result.physical_groups
        assert len(groups["substrate_layer3"][1]) == 1, (stem, groups)
        assert len(groups["vacuum"][1]) == 1, (stem, groups)
        assert "gnd_layer1_sfs" in groups, (stem, sorted(groups))


def test_dielectric_layer_must_own_exactly_one_volume():
    """The substrate box duplicated by a bad fragment must be caught."""
    _session("dup_substrate")
    gmsh.model.occ.addBox(0, 0, 0, 1e-4, 1e-4, 1e-4)
    gmsh.model.occ.synchronize()

    tracker = GeomTracker()
    tracker.layer_ground = {3: [1, 2]}  # 2 bodies for one dielectric layer
    with pytest.raises(DesignDslError, match="exactly 1 volume"):
        resolve_conductor_faces(tracker, {3: {"kind": "dielectric", "z": 0.0,
                                              "thickness": -1e-4}})
