# -*- coding: utf-8 -*-
"""quantum_dsl v4 — 超导量子芯片版图 DSL。

契约 = SPEC.md, 可执行形式 = tests/。顶层 API 扁平 (SPEC「公共 API」表);
``import quantum_dsl`` 保持轻量 —— gmsh/gdstk 只在用到的函数里惰性 import
(契约 N0)。
"""

from __future__ import annotations

from .errors import QuantumDslError
from .units import parse_length, parse_quantity
from .geo import Geo, Physical, load_geo, parse_physical_name
from .meta import Meta, load_meta

__all__ = [
    "QuantumDslError",
    "parse_length", "parse_quantity",
    "Geo", "Physical", "load_geo", "parse_physical_name",
    "Meta", "load_meta",
]

# V4-3 物理内核 (纯 math, 不依赖 V4-2)
from .circuit_model import (ELEM_CHARGE, FLUX_QUANTUM_REDUCED, H_PLANCK, HBAR,
                            dispersive_shift_hz, resonator_lumped_lc,
                            solve_circuit_model)
from .assemble import assemble
from .cpw import guided_wavelength, lumped_cpw

__all__ += [
    "ELEM_CHARGE", "FLUX_QUANTUM_REDUCED", "H_PLANCK", "HBAR",
    "solve_circuit_model", "resonator_lumped_lc", "dispersive_shift_hz",
    "assemble", "guided_wavelength", "lumped_cpw",
]

# V4-2 几何分叉 (gmsh/gdstk 惰性 import 在各函数内) + V4-4 cells + V4-5 编排
from .gds import build_gds
from .mesh import Mesh, build_mesh
from .palace import Cap, palace_config, parse_capacitance
from .cells import emit_geo, rounded_polygon
from .build import build

__all__ += [
    "build_gds", "Mesh", "build_mesh", "Cap", "palace_config",
    "parse_capacitance", "rounded_polygon", "emit_geo", "build",
]
