# -*- coding: utf-8 -*-
"""Schema constants for the native YAML design DSL v3.

This module declares all keyword sets, kind enumerations, and the
``CURRENT_SCHEMA`` version tag.  It has no imports from this package.
"""

from __future__ import annotations

__all__ = [
    "CURRENT_SCHEMA",
    "ROOT_KEYS",
    "GEOMETRY_KEYS",
    "SIMULATION_KEYS",
    "GMSH_SIM_KEYS",
    "LAYER_STACK_ENTRY_KEYS",
    "LAYER_STACK_KINDS",
    "AIRBOX_KEYS",
    "PORT_KEYS",
    "PORT_TYPES",
    "SYMMETRY_KEYS",
    "SYMMETRY_PLANES",
    "SYMMETRY_CONDITIONS",
    "MESH_KEYS",
    "MESH_REFINE_KEYS",
    "OUTPUT_KEYS",
    "GEO_ROLES",
    "GEO_SURFACE_ROLES",
    "GEO_MARKER_ROLES",
    "GEO_META_ROOT_KEYS",
    "CELL_KEYS",
    "GDS_SIM_KEYS",
    "GDS_LAYER_MAP_ENTRY_KEYS",
    "SOLVER_KEYS",
    "SOLVER_TYPES",
    "CIRCUIT_MODEL_KEYS",
    "CIRCUIT_QUBIT_KEYS",
    "CIRCUIT_SQUID_KEYS",
    "DESIGN_KEYS",
    "TRANSFORM_KEYS",
    "COMPONENT_KEYS",
    "PRIMITIVE_KEYS",
    "PIN_KEYS",
    "GENERATOR_KEYS",
    "NETLIST_KEYS",
    "NETLIST_CONNECTION_KEYS",
    "CHIP_KEYS",
    "CHIP_SIZE_KEYS",
    "BUILTIN_DESIGNS",
]

CURRENT_SCHEMA = "qiskit-metal/design-dsl/3"

ROOT_KEYS = {
    "schema", "vars", "hamiltonian", "circuit", "netlist", "geometry",
    "templates", "simulation",
}
GEOMETRY_KEYS = {"design", "templates", "components", "transforms"}
SIMULATION_KEYS = {"gmsh"}
GMSH_SIM_KEYS = {
    "layer_stack", "airbox", "ports", "symmetry", "mesh", "output",
    "gds", "solver", "substrate_gap_um",
}
LAYER_STACK_ENTRY_KEYS = {
    "kind", "thickness", "z", "material", "eps_r", "tan_delta",
}
LAYER_STACK_KINDS = {"metal", "dielectric"}
AIRBOX_KEYS = {"top", "bottom", "side_buffer"}
PORT_KEYS = {"pin", "type", "impedance", "value"}
PORT_TYPES = {"lumped", "ground"}
SYMMETRY_KEYS = {"plane", "condition"}
SYMMETRY_PLANES = {"x0", "y0", "z0"}
SYMMETRY_CONDITIONS = {"pec", "pmc"}
MESH_KEYS = {
    "max_size", "min_size", "max_size_jj", "conductor_refine",
}
MESH_REFINE_KEYS = {"min_dist", "max_dist"}
OUTPUT_KEYS = {"format", "scaling"}

# ---------------------------------------------------------------------------
# Native Gmsh .geo geometry-DSL binding (Layer 2) + Layer-1 metadata sidecar.
# A .geo author tags each entity with a structured Physical name:
#     "<role>::<layer>::<component>::<primitive>"
# This name is the single binding key shared by the GDS layer map, the Palace
# attribute assignment, and the Layer-1 metadata (layer index -> layer_stack).
# ---------------------------------------------------------------------------
# Roles that name a 2D Plane Surface (extruded to a 3D volume in the mesh branch).
GEO_SURFACE_ROLES = {"metal", "ground", "jj", "substrate"}
# Roles that name a 1D edge / marker (not extruded).
GEO_MARKER_ROLES = {"port", "symmetry"}
GEO_ROLES = GEO_SURFACE_ROLES | GEO_MARKER_ROLES

# Top-level keys of a standalone *.meta.yaml sidecar paired with a .geo file.
# ``geo`` points at the companion .geo (relative to the sidecar); ``simulation``
# reuses the existing simulation.gmsh vocabulary; ``circuit_model`` (M6) carries
# optional junction inputs (islands + L_J/E_J) for the capacitance→Hamiltonian
# solve.  ``circuit_model`` is deliberately NOT named ``circuit``/``hamiltonian``
# (those root keys belong to the legacy full DSL with a different shape — the
# geo sidecar never feeds the legacy builder, so the two never meet).  ``cells``
# (M5a) is an OPTIONAL block that lowers v3 component-template instances → a
# generated ``<stem>.elaborated.geo`` (the emit_geo bridge); when present, ``geo``
# is optional (the geometry is generated, not authored).
GEO_META_ROOT_KEYS = {"schema", "geo", "vars", "simulation", "circuit_model", "cells"}

# *.meta.yaml ``circuit_model`` block (M6 junction inputs → circuit_model.py).
CIRCUIT_MODEL_KEYS = {"qubits"}
# A single qubit entry: a name, exactly one island ref (``island`` scalar or
# ``islands`` list), and exactly one of L_J / E_J / squid.
CIRCUIT_QUBIT_KEYS = {"name", "island", "islands", "L_J", "E_J", "squid"}
# The ``squid:`` sub-block of a qubit entry — a flux-tunable, possibly ASYMMETRIC
# SQUID (two parallel junctions).  ``E_J1``/``E_J2`` take the same unit-bearing
# strings as ``E_J`` (frequency E_J/h or energy); ``flux`` is a bare float =
# Phi/Phi0 (normalised, dimensionless), default 0.0.  E_J,eff is computed in
# ``circuit_model.JunctionInput.e_j_joule``.
CIRCUIT_SQUID_KEYS = {"E_J1", "E_J2", "flux"}

# A single ``cells:`` instance — one placed v3 component-template cell.
# ``cell_type`` = template id (e.g. transmon_pocket); ``component`` = the globally
# unique component name (becomes the ``::<component>::`` field of every Physical
# name, so it MUST be unique across cells — load_geo's duplicate guard enforces
# it).  ``x/y/rot/layer`` place the cell (→ template pos_x/pos_y/orientation/layer
# options); ``params`` overrides any template option.
CELL_KEYS = {"cell_type", "component", "x", "y", "rot", "layer", "params"}

# simulation.gmsh.gds block: GDS layer map + gdstk library settings.
GDS_SIM_KEYS = {
    "default_datatype", "by_name", "by_role", "by_layer",
    "top_cell", "lib_name", "unit", "precision", "arc_tol_um",
    "union_same_layer",
}
GDS_LAYER_MAP_ENTRY_KEYS = {"layer", "datatype"}

# simulation.gmsh.solver block: Palace solver settings.
SOLVER_KEYS = {"type", "order", "l0", "device", "outer_boundary"}
SOLVER_TYPES = {"Electrostatic"}  # Eigenmode / Driven added in a later milestone.
DESIGN_KEYS = {
    "class", "metadata", "overwrite_enabled", "enable_renderers", "variables",
    "chip",
}
TRANSFORM_KEYS = {"translate", "rotate", "origin"}
COMPONENT_KEYS = {
    "name", "primitives", "pins", "metadata", "transform", "translate",
    "rotate", "origin", "type", "options", "operations", "generators",
}
PRIMITIVE_KEYS = {
    "name", "kind", "shape", "type", "primitive", "points", "center", "size",
    "subtract", "helper", "layer", "chip", "width", "fillet", "transform",
    "operation",
}
PIN_KEYS = {
    "name", "points", "width", "gap", "chip", "transform", "mode",
    "from_operation", "operation", "segment",
}
GENERATOR_KEYS = {"for_each", "as", "operations", "primitives", "pins"}
NETLIST_KEYS = {"connections"}
NETLIST_CONNECTION_KEYS = {"from", "to"}
CHIP_KEYS = {
    "name", "size", "size_x", "size_y", "size_z", "center_x", "center_y",
    "center_z",
}
CHIP_SIZE_KEYS = {"size_x", "size_y"}

BUILTIN_DESIGNS: dict[str, str] = {
    "DesignPlanar": "qiskit_metal.designs.design_planar.DesignPlanar",
    "DesignFlipChip": "qiskit_metal.designs.design_flipchip.DesignFlipChip",
    "DesignMultiPlanar":
        "qiskit_metal.designs.design_multiplanar.MultiPlanar",
}
