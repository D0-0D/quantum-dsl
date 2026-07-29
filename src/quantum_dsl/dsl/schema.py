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
    "EXTRACT_KEYS",
    "EXTRACT_BLOCK_KEYS",
    "EXTRACT_SOURCES",
    "EXTRACT_MATRIX_KEYS",
    "EXTRACT_JUNCTION_KEYS",
    "ASSEMBLE_KEYS",
    "SUBSYSTEM_KEYS",
    "SUBSYSTEM_TYPES",
    "CPW_KEYS",
    "RESONATOR_MODES",
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
GEO_META_ROOT_KEYS = {
    "schema", "geo", "vars", "simulation", "circuit_model", "cells",
    "extract", "assemble", "subsystems",
}

# *.meta.yaml ``circuit_model`` block (M6 junction inputs → circuit_model.py).
CIRCUIT_MODEL_KEYS = {"qubits"}
# A single qubit entry: a name, exactly one island ref (``island`` scalar or
# ``islands`` list), and exactly one of L_J / E_J / squid.
CIRCUIT_QUBIT_KEYS = {"name", "island", "islands", "L_J", "E_J", "squid", "C_j"}
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

# ---------------------------------------------------------------------------
# M8 New-LOM parity: extract: / assemble: / subsystems: (lom-parity-spec §4 P0-B..F)
#
# ⚠ 命名冲突已刻意避开 (spec §8.1 / 风险 R10). 两个「cell」是**两个不同概念**:
#
#   cells:            M5a 的**几何** cell 实例 —— 一个放置好的 v3 component 模板,
#                     lower 成 <stem>.elaborated.geo 里的一段几何 (emit_geo bridge).
#                     单位是「一块金属图形」。
#   extract.blocks:   本 spec 的**电学** Cell = **一次 EM 提取** —— 一份 Maxwell C
#                     矩阵 (实解 / 读文件 / inline), 对应 New LOM (tutorial 4.05) 的
#                     一个 Cell。单位是「一份电容矩阵」。
#
# 一个 extract block 可以覆盖多个几何 cell (``components: [QB1, BUS]``), 也可以完全
# 没有几何 (``from: file`` —— 矩阵直接注入, 不碰 .geo)。所以两者不是一对一, **不能**
# 共用 ``cells`` 这个键名: 一份 sidecar 里两个 ``cells:`` 会直接撞车 (YAML 层就是同一
# 个 key), 而且会把「几何子集」与「一次提取」混为一谈 —— 那正是 §4 P0-C「文件来源是
# 主流程」要区分的东西。名字沿用 New LOM 的语义, 键名沿用 spec §8.1 定下的
# ``extract.blocks``。
# ---------------------------------------------------------------------------
EXTRACT_KEYS = {"blocks"}
# 一个 extract block: 名字 + 来源 + 节点重命名 + 本块的结。
# ``from`` = solve|file|inline (见 EXTRACT_SOURCES); ``components`` 只在 solve 时必填
# (块几何子集, 喂 emit_block_geo); ``path`` 只在 file 时必填; ``matrix`` 只在 inline
# 时必填; ``units`` 是 file/inline 矩阵的单位 (默认 fF)。
EXTRACT_BLOCK_KEYS = {
    "name", "components", "from", "path", "matrix", "units", "nodes", "junctions",
}
# C 矩阵来源。solve = 跑 Palace (P0-A); file = 读 Palace CSV / Q3D txt (P0-C);
# inline = 矩阵直接写在 sidecar 里 (P0-C, 零成本回归)。provenance 必须区分三者 (R4)。
EXTRACT_SOURCES = {"solve", "file", "inline"}
EXTRACT_MATRIX_KEYS = {"terminals", "maxwell"}
# 一个结 (= New LOM 的 jj_dict/ind_dict/cj_dict 条目)。``between`` 是 1 或 2 个节点名
# (1 = 接地 transmon, 2 = 浮动/差分); 结元件 L_J / E_J / squid 恰选一个 (与
# CIRCUIT_QUBIT_KEYS 同语义); ``C_j`` 是结电容 (P0-E, 默认 0)。
EXTRACT_JUNCTION_KEYS = {"name", "between", "L_J", "E_J", "squid", "C_j"}

# assemble: 块 → 整片的拼装参数 (P0-B)。``ground_node`` 是被消去的参考节点;
# ``nodes_force_keep`` 是不许被 Schur 消元吃掉的节点 (谐振器接入点, 风险 R3 兜底)。
ASSEMBLE_KEYS = {"ground_node", "nodes_force_keep"}

# subsystems: 拼装后矩阵上的量子子系统 (P0-B/D)。键是两种 type 的**并集** ——
# 每种 type 各自的允许键在 parsers/simulation.py 里按 type 再收紧一次
# (transmon 用 ``junction`` 指结名, tl_resonator 用 ``node`` 指节点名)。
SUBSYSTEM_KEYS = {"name", "type", "junction", "node", "f_res", "Z0", "mode", "cpw"}
SUBSYSTEM_TYPES = {"transmon", "tl_resonator"}
# tl_resonator 的 ``cpw:`` 子块 (P0-F) —— 给了它就用 CPW 解析计算器算 f_res,
# 与直接给 ``f_res`` 二选一。长度量单位 = 仓库内部单位 µm。
CPW_KEYS = {
    "line_width", "line_gap", "length", "substrate_thickness", "film_thickness",
}
# λ/2 (两端开路) 还是 λ/4 (一端短路): 决定 Cr = π/(2 ω_r Z0) 的 /2, Lr 的 ×2。
RESONATOR_MODES = {"half_wave", "quarter_wave"}

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
