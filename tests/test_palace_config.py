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
    validate_config,
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
