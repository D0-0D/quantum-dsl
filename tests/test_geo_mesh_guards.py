# -*- coding: utf-8 -*-
"""Guards in ``_gmsh_mesh``: the empty-3D-mesh check must also hold on the
``QDSL_MESH_ALGO3D`` override path, and an inert ``max_size_jj`` must be loud.

Both are regressions found while reviewing ``sung_2021_device`` (session
2607280204): the env override returned straight after ``generate`` and so
skipped the empty-mesh guard, and ``max_size_jj`` is a dead knob on the
native-geo path (jj:: surfaces are removed as lumped elements).
"""

from __future__ import annotations

import pytest

gmsh = pytest.importorskip("gmsh")

from quantum_dsl.dsl import _gmsh_mesh
from quantum_dsl.dsl._gmsh_geometry import GeomTracker


def test_algo3d_override_still_rejects_an_empty_mesh(monkeypatch):
    """A 3D entity with zero 3D elements must raise on the override path too."""
    monkeypatch.setenv("QDSL_MESH_ALGO3D", "10")
    calls = {"generate": 0, "algo": None}

    monkeypatch.setattr(
        _gmsh_mesh.gmsh.option, "setNumber",
        lambda name, value: calls.__setitem__("algo", (name, value)))
    monkeypatch.setattr(
        _gmsh_mesh.gmsh.model.mesh, "generate",
        lambda dim: calls.__setitem__("generate", calls["generate"] + 1))
    monkeypatch.setattr(_gmsh_mesh, "_mesh_3d_is_empty", lambda: True)

    with pytest.raises(RuntimeError, match="QDSL_MESH_ALGO3D"):
        _gmsh_mesh.generate_mesh(dim=3)
    assert calls["generate"] == 1                     # no silent retry loop
    assert calls["algo"] == ("Mesh.Algorithm3D", 10)  # the override was applied


def test_algo3d_override_passes_a_non_empty_mesh(monkeypatch):
    monkeypatch.setenv("QDSL_MESH_ALGO3D", "10")
    monkeypatch.setattr(_gmsh_mesh.gmsh.option, "setNumber",
                        lambda name, value: None)
    monkeypatch.setattr(_gmsh_mesh.gmsh.model.mesh, "generate", lambda dim: None)
    monkeypatch.setattr(_gmsh_mesh, "_mesh_3d_is_empty", lambda: False)
    _gmsh_mesh.generate_mesh(dim=3)  # must not raise


def test_inert_max_size_jj_warns(caplog):
    """No tracked junction (the geo path) + authored max_size_jj -> warning."""
    tracker = GeomTracker()
    gmsh.initialize()
    try:
        gmsh.model.add("test_inert_max_size_jj_warns")
        gmsh.model.setCurrent("test_inert_max_size_jj_warns")
        with caplog.at_level("WARNING", logger=_gmsh_mesh.logger.name):
            _gmsh_mesh.define_size_fields(
                tracker, {1: {"kind": "metal", "thickness": 2e-6, "z": 0.0}},
                {"max_size": 80e-6, "min_size": 2e-6, "max_size_jj": 0.5e-6})
    finally:
        gmsh.finalize()
    assert [r for r in caplog.records if "max_size_jj" in str(r.msg)]


def test_absent_max_size_jj_does_not_warn(caplog):
    tracker = GeomTracker()
    gmsh.initialize()
    try:
        gmsh.model.add("test_absent_max_size_jj_does_not_warn")
        gmsh.model.setCurrent("test_absent_max_size_jj_does_not_warn")
        with caplog.at_level("WARNING", logger=_gmsh_mesh.logger.name):
            _gmsh_mesh.define_size_fields(
                tracker, {1: {"kind": "metal", "thickness": 2e-6, "z": 0.0}},
                {"max_size": 80e-6, "min_size": 2e-6})
    finally:
        gmsh.finalize()
    assert not [r for r in caplog.records if "max_size_jj" in str(r.msg)]
