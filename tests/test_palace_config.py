# -*- coding: utf-8 -*-
"""Pure tests for the Palace Electrostatic config builder (no gmsh / gdstk).

``palace_adapter`` is pure-Python: it consumes a ``physical_attributes`` name→int
map (from ``GmshMeshResult``) + a ``layer_stack`` and emits an Electrostatic
JSON dict. So this file runs in any env. Covers:
- ``build_palace_config`` shape (Problem.Type=Electrostatic, Model.L0=1.0,
  one Material per dielectric w/ eps_r + vacuum=1.0, Ground = gnd_*_sfs +
  vacuum_outer, Terminals with >=2 enforced);
- ``validate_config`` raises on a missing attribute;
- ``_to_wsl_path`` Windows -> /mnt mapping.
"""

from __future__ import annotations

import pytest

from quantum_dsl.dsl.errors import DesignDslError
from quantum_dsl.dsl.palace_adapter import (
    build_palace_config,
    terminal_bindings,
    TerminalBinding,
    validate_config,
    parse_capacitance_matrix,
    write_results_sidecar,
    _to_wsl_path,
)


# A synthetic post-fragment physical_attributes map mirroring the geo path:
#   2 conductors (Q1_pad/Q2_pad), a metal-ground sheet, a dielectric substrate,
#   vacuum body + outer boundary. Unique int attributes.
def _attrs() -> dict[str, int]:
    return {
        "Q1_pad_sfs": 11,        # conductor terminal
        "Q2_pad_sfs": 12,        # conductor terminal
        "gnd_layer1_sfs": 20,    # metal ground (Ground, not Terminal)
        "substrate_layer3": 30,  # dielectric material
        "vacuum": 40,            # vacuum material
        "vacuum_outer": 41,      # vacuum outer boundary (Ground)
        # volume-only attrs that should NOT become terminals:
        "Q1_pad": 50,
        "Q2_pad": 51,
        "gnd_layer1": 52,
    }


def _layer_stack() -> dict[int, dict]:
    return {
        1: {"kind": "metal", "thickness": 2e-6, "z": 0.0},
        3: {"kind": "dielectric", "thickness": -750e-6, "z": 0.0,
            "eps_r": 11.45},
    }


# -----------------------------------------------------------------------------
# build_palace_config — top-level shape
# -----------------------------------------------------------------------------

def test_problem_type_electrostatic():
    cfg = build_palace_config(_attrs(), _layer_stack())
    assert cfg["Problem"]["Type"] == "Electrostatic"


def test_model_l0_default_is_one():
    cfg = build_palace_config(_attrs(), _layer_stack())
    assert cfg["Model"]["L0"] == 1.0


def test_model_l0_override():
    cfg = build_palace_config(_attrs(), _layer_stack(), l0=2.5)
    assert cfg["Model"]["L0"] == 2.5


# -----------------------------------------------------------------------------
# Materials: one per dielectric (correct eps_r) + vacuum at 1.0
# -----------------------------------------------------------------------------

def test_materials_dielectric_eps_r_and_vacuum():
    cfg = build_palace_config(_attrs(), _layer_stack())
    mats = cfg["Domains"]["Materials"]
    # one dielectric + vacuum
    perms = {tuple(m["Attributes"]): m["Permittivity"] for m in mats}
    assert perms[(30,)] == pytest.approx(11.45)  # substrate_layer3 -> eps_r
    assert perms[(40,)] == pytest.approx(1.0)     # vacuum -> 1.0
    assert len(mats) == 2


def test_materials_dielectric_missing_eps_r_raises():
    ls = _layer_stack()
    del ls[3]["eps_r"]
    with pytest.raises(DesignDslError, match="eps_r"):
        build_palace_config(_attrs(), ls)


def test_energy_postprocessing_spans_dielectric_and_vacuum():
    cfg = build_palace_config(_attrs(), _layer_stack())
    energy = cfg["Domains"]["Postprocessing"]["Energy"]
    attrs = {a for e in energy for a in e["Attributes"]}
    assert attrs == {30, 40}


# -----------------------------------------------------------------------------
# Ground: gnd_*_sfs + vacuum_outer
# -----------------------------------------------------------------------------

def test_ground_covers_metal_ground_and_vacuum_outer():
    cfg = build_palace_config(_attrs(), _layer_stack())
    ground_attrs = set(cfg["Boundaries"]["Ground"]["Attributes"])
    assert ground_attrs == {20, 41}  # gnd_layer1_sfs + vacuum_outer


# -----------------------------------------------------------------------------
# Terminals: one per conductor _sfs, >=2 enforced
# -----------------------------------------------------------------------------

def test_terminals_one_per_conductor_sorted_index():
    cfg = build_palace_config(_attrs(), _layer_stack())
    terms = cfg["Boundaries"]["Terminal"]
    # sorted by name -> Q1_pad_sfs(11) before Q2_pad_sfs(12); Index 1-based.
    assert [t["Index"] for t in terms] == [1, 2]
    assert [t["Attributes"] for t in terms] == [[11], [12]]


def test_terminals_exclude_ground_and_vacuum_sfs():
    cfg = build_palace_config(_attrs(), _layer_stack())
    term_attrs = {a for t in cfg["Boundaries"]["Terminal"] for a in t["Attributes"]}
    # gnd_layer1_sfs(20) and vacuum_outer(41) must NOT be terminals.
    assert 20 not in term_attrs
    assert 41 not in term_attrs


def test_surface_flux_mirrors_terminals():
    cfg = build_palace_config(_attrs(), _layer_stack())
    flux = cfg["Boundaries"]["Postprocessing"]["SurfaceFlux"]
    assert [f["Attributes"] for f in flux] == [[11], [12]]
    assert all(f["Type"] == "Electric" for f in flux)


def test_fewer_than_two_terminals_raises():
    attrs = {
        "Q1_pad_sfs": 11,        # only ONE conductor
        "gnd_layer1_sfs": 20,
        "substrate_layer3": 30,
        "vacuum": 40,
        "vacuum_outer": 41,
    }
    with pytest.raises(DesignDslError, match=">=2 conductor terminals"):
        build_palace_config(attrs, _layer_stack())


# -----------------------------------------------------------------------------
# mesh_path / order optional kwargs
# -----------------------------------------------------------------------------

def test_mesh_path_omitted_by_default():
    cfg = build_palace_config(_attrs(), _layer_stack())
    assert "Mesh" not in cfg["Model"]


def test_mesh_path_set_when_passed():
    cfg = build_palace_config(_attrs(), _layer_stack(), mesh_path="build/chip.msh")
    assert cfg["Model"]["Mesh"] == "build/chip.msh"


def test_order_default_and_override():
    assert build_palace_config(_attrs(), _layer_stack())["Solver"]["Order"] == 2
    assert build_palace_config(
        _attrs(), _layer_stack(), order=3)["Solver"]["Order"] == 3


# -----------------------------------------------------------------------------
# validate_config
# -----------------------------------------------------------------------------

def test_validate_config_passes_on_self_built():
    attrs = _attrs()
    cfg = build_palace_config(attrs, _layer_stack())
    validate_config(cfg, attrs)  # must not raise


def test_validate_config_raises_on_missing_attribute():
    attrs = _attrs()
    cfg = build_palace_config(attrs, _layer_stack())
    # Drop the int backing one of the referenced attributes (the substrate).
    broken = {k: v for k, v in attrs.items() if v != 30}
    with pytest.raises(DesignDslError, match="unknown physical attribute"):
        validate_config(cfg, broken)


# -----------------------------------------------------------------------------
# _to_wsl_path
# -----------------------------------------------------------------------------

def test_to_wsl_path_drive_mapping():
    out = _to_wsl_path(r"D:\Workspace\Quantum-dsl\build\chip.json")
    assert out.startswith("/mnt/d/")  # drive letter lower-cased
    assert "Workspace" in out         # rest of path preserved (case kept)
    assert out.endswith("/build/chip.json")


def test_to_wsl_path_no_backslashes():
    out = _to_wsl_path(r"C:\Users\Administrator\build")
    assert "\\" not in out
    assert out.startswith("/mnt/c/")


# -----------------------------------------------------------------------------
# terminal_bindings — THE single source of truth for matrix row/col order
# -----------------------------------------------------------------------------

def test_terminal_bindings_sorted_index_group_attribute():
    binds = terminal_bindings(_attrs())
    # sorted by name -> Q1_pad_sfs before Q2_pad_sfs; Index 1-based.
    assert [b.index for b in binds] == [1, 2]
    assert [b.group for b in binds] == ["Q1_pad_sfs", "Q2_pad_sfs"]
    assert [b.attribute for b in binds] == [11, 12]
    assert all(b.terminal is None for b in binds)  # no geo_names map given


def test_terminal_bindings_geo_names_enrich_structured_label():
    binds = terminal_bindings(
        _attrs(),
        geo_names={"Q1_pad_sfs": "metal::1::Q1::pad"},
    )
    assert binds[0].terminal == "metal::1::Q1::pad"
    assert binds[1].terminal is None  # not in the map


def test_terminal_bindings_excludes_ground_vacuum_and_volumes():
    groups = {b.group for b in terminal_bindings(_attrs())}
    # only the two conductor _sfs surfaces; never gnd_*/vacuum* or volume-only.
    assert groups == {"Q1_pad_sfs", "Q2_pad_sfs"}


def test_config_terminal_order_matches_terminal_bindings():
    """Regression: build_palace_config Terminals == terminal_bindings (same src)."""
    attrs = _attrs()
    cfg = build_palace_config(attrs, _layer_stack())
    binds = terminal_bindings(attrs)
    cfg_pairs = [(t["Index"], t["Attributes"][0])
                 for t in cfg["Boundaries"]["Terminal"]]
    bind_pairs = [(b.index, b.attribute) for b in binds]
    assert cfg_pairs == bind_pairs


# -----------------------------------------------------------------------------
# parse_capacitance_matrix — real Maxwell + mutual parse (F -> fF)
# -----------------------------------------------------------------------------

# Verbatim CSV text from the working two-spheres Palace PoC (Palace 0.16).
# terminal-C.csv = Maxwell matrix C (+diag, -offdiag);
# terminal-Cm.csv = mutual matrix Cm (all-positive); related by
#   Cm[i][i] = C[i][i] + C[i][j]   and   Cm[i][j] = -C[i][j].
_MAXWELL_CSV = (
    "        i,                C[i][1] (F),                C[i][2] (F)\n"
    " 1.00e+00,        +1.354305474059e-10,        -3.306523790651e-11\n"
    " 2.00e+00,        -3.306523790651e-11,        +1.354665489642e-10\n"
)
_MUTUAL_CSV = (
    "        i,              C_m[i][1] (F),              C_m[i][2] (F)\n"
    " 1.00e+00,        +1.023653094993e-10,        +3.306523790651e-11\n"
    " 2.00e+00,        +3.306523790651e-11,        +1.024013110577e-10\n"
)


def _write_postpro(tmp_path, *, maxwell=True, mutual=True):
    postpro = tmp_path / "postpro"
    postpro.mkdir(parents=True, exist_ok=True)
    if maxwell:
        (postpro / "terminal-C.csv").write_text(_MAXWELL_CSV, encoding="utf-8")
    if mutual:
        (postpro / "terminal-Cm.csv").write_text(_MUTUAL_CSV, encoding="utf-8")
    return postpro


def test_parse_missing_dir_is_unavailable_not_error(tmp_path):
    res = parse_capacitance_matrix(tmp_path / "nope")
    assert res.available is False
    assert res.maxwell == [] and res.mutual == []


def test_parse_maxwell_sign_convention_and_units(tmp_path):
    postpro = _write_postpro(tmp_path)
    res = parse_capacitance_matrix(postpro)
    assert res.available is True
    assert res.units == "fF"
    m = res.maxwell
    # 2x2, F -> fF (x1e15): diagonal positive, off-diagonal negative, symmetric.
    assert m[0][0] == pytest.approx(1.354305474059e-10 * 1e15)
    assert m[0][1] == pytest.approx(-3.306523790651e-11 * 1e15)
    assert m[0][0] > 0 and m[1][1] > 0
    assert m[0][1] < 0 and m[1][0] < 0
    assert m[0][1] == pytest.approx(m[1][0])  # symmetric


def test_parse_mutual_all_positive(tmp_path):
    res = parse_capacitance_matrix(_write_postpro(tmp_path))
    cm = res.mutual
    assert all(cm[i][j] > 0 for i in range(2) for j in range(2))


def test_parse_maxwell_mutual_relationship(tmp_path):
    """Cm[i][i] == C[i][i]+C[i][j];  Cm[i][j] == -C[i][j] (consistency check)."""
    res = parse_capacitance_matrix(_write_postpro(tmp_path))
    c, cm = res.maxwell, res.mutual
    assert cm[0][0] == pytest.approx(c[0][0] + c[0][1])
    assert cm[0][1] == pytest.approx(-c[0][1])


def test_parse_matrix_property_prefers_maxwell(tmp_path):
    res = parse_capacitance_matrix(_write_postpro(tmp_path))
    assert res.matrix == res.maxwell
    # mutual-only -> .matrix falls back to mutual.
    res2 = parse_capacitance_matrix(_write_postpro(tmp_path / "b", maxwell=False))
    assert res2.matrix == res2.mutual and res2.maxwell == []


def test_parse_asserts_squareness_against_terminals(tmp_path):
    postpro = _write_postpro(tmp_path)  # 2x2 matrices
    three = [TerminalBinding(i, f"g{i}", 100 + i) for i in (1, 2, 3)]
    with pytest.raises(DesignDslError, match="binding mismatch"):
        parse_capacitance_matrix(postpro, terminals=three)


def test_parse_rejects_non_square_csv(tmp_path):
    postpro = tmp_path / "postpro"
    postpro.mkdir()
    # header declares 2 value cols but only 1 data row -> not square.
    (postpro / "terminal-C.csv").write_text(
        "i, C[i][1] (F), C[i][2] (F)\n 1.0, +1.0e-15, +2.0e-15\n",
        encoding="utf-8")
    with pytest.raises(DesignDslError, match="not square"):
        parse_capacitance_matrix(postpro)


def test_parse_rejects_out_of_order_rows(tmp_path):
    postpro = tmp_path / "postpro"
    postpro.mkdir()
    (postpro / "terminal-C.csv").write_text(
        "i, C[i][1] (F), C[i][2] (F)\n"
        " 2.0, +1.0e-15, +0.0\n"
        " 1.0, +0.0, +1.0e-15\n",
        encoding="utf-8")
    with pytest.raises(DesignDslError, match="out of order"):
        parse_capacitance_matrix(postpro)


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf"])
def test_parse_rejects_non_finite_values(tmp_path, bad):
    """A diverged/partial Palace solve can emit nan/inf in a value column; bare
    float() accepts those silently. Regression: they must be rejected so NaN/inf
    never propagate into the inverse-cap / transmon math and chip.results.yaml."""
    postpro = tmp_path / "postpro"
    postpro.mkdir()
    (postpro / "terminal-C.csv").write_text(
        "i, C[i][1] (F), C[i][2] (F)\n"
        f" 1.0, +1.0e-15, {bad}\n"
        " 2.0, +0.0, +1.0e-15\n",
        encoding="utf-8")
    with pytest.raises(DesignDslError, match="non-finite"):
        parse_capacitance_matrix(postpro)


# -----------------------------------------------------------------------------
# write_results_sidecar — OUTPUT-ONLY Layer-3 artifact, NOT a meta sidecar
# -----------------------------------------------------------------------------

def test_write_results_sidecar_roundtrips(tmp_path):
    import yaml

    res = parse_capacitance_matrix(
        _write_postpro(tmp_path),
        terminals=terminal_bindings(_attrs()),
    )
    out = write_results_sidecar(
        res, tmp_path / "chip.results.yaml",
        provenance={"solver": {"type": "Electrostatic", "order": 2, "l0": 1.0}},
    )
    assert out.is_file()
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))

    assert doc["schema"] == "qiskit-metal/design-results/1"
    assert doc["tier"] == 3
    cap = doc["capacitance"]
    assert cap["available"] is True
    assert cap["units"] == "fF"
    # row/col binding persisted: index/group/attribute, in Terminal order.
    assert [t["index"] for t in cap["terminals"]] == [1, 2]
    assert [t["group"] for t in cap["terminals"]] == ["Q1_pad_sfs", "Q2_pad_sfs"]
    assert len(cap["maxwell"]) == 2 and len(cap["mutual"]) == 2
    assert cap["source_csv"]["maxwell"] == "terminal-C.csv"
    assert doc["provenance"]["solver"]["type"] == "Electrostatic"


def test_results_sidecar_is_not_a_valid_meta_sidecar(tmp_path):
    """The results artifact must NOT round-trip as a Layer-1 *.meta.yaml input."""
    from quantum_dsl.dsl.parsers.simulation import parse_geo_meta_sidecar

    res = parse_capacitance_matrix(
        _write_postpro(tmp_path), terminals=terminal_bindings(_attrs()))
    out = write_results_sidecar(res, tmp_path / "chip.results.yaml")
    # Distinct schema family + unknown root keys -> the sidecar parser rejects it,
    # proving inputs (design-dsl) and outputs (design-results) stay separate.
    with pytest.raises(DesignDslError):
        parse_geo_meta_sidecar(out)
