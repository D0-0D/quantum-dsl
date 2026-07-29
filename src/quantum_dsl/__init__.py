# -*- coding: utf-8 -*-
"""quantum_dsl — a DSL for superconducting quantum-chip layout.

Two geometry front-ends feed a shared physical-group model that forks to
multiple backends:

* **Native Gmsh ``.geo`` path (primary).** A Layer-1 ``*.meta.yaml`` physics
  sidecar + a Layer-2 native Gmsh ``.geo`` (microns) fork to **gdstk → GDSII**
  and **Gmsh → mesh → Palace** (Electrostatic capacitance matrix → circuit
  model). Entry point :func:`quantum_dsl.dsl.geo_build.build_geo`::

      python -m quantum_dsl.dsl.geo_build chip.meta.yaml --out-dir build/

* **Legacy YAML path.** :func:`build_ir` / :func:`build_design` resolve a single
  ``.metal.yaml`` into a qiskit-metal ``QDesign`` (and, via the Gmsh adapter, a
  mesh) without instantiating qlibrary component classes. ``build_ir`` is also
  reused by the native path's ``emit_geo`` cell bridge.

This package depends on ``qiskit-metal`` at runtime (unit parsing, ``draw``
helpers, ``QComponent``). The Gmsh / gdstk / gdsfactory adapters are imported
lazily so ``import quantum_dsl`` stays free of those optional dependencies.
"""
from __future__ import annotations

from .dsl import (
    BUILTIN_COMPONENT_TEMPLATE_PATHS,
    BUILTIN_DESIGNS,
    CURRENT_SCHEMA,
    ComponentIR,
    ComponentTemplate,
    ComponentTemplateExpansion,
    ComponentTemplateRegistry,
    DEFAULT_GEOMETRY_OPERATIONS,
    DesignDslError,
    DesignIR,
    GeometryOperationRegistry,
    NativeComponent,
    PinIR,
    PrimitiveIR,
    TEMPLATE_SCHEMA,
    build_design,
    build_ir,
    clear_user_registry,
    evaluate_expression,
    evaluate_geometry_operations,
    export_ir_to_metal,
    register_design,
    resolve_operation_reference,
    substitute_string,
    walk_substitute,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "DesignDslError",
    "DesignIR",
    "PrimitiveIR",
    "PinIR",
    "ComponentIR",
    "NativeComponent",
    "BUILTIN_DESIGNS",
    "CURRENT_SCHEMA",
    "build_ir",
    "export_ir_to_metal",
    "build_design",
    "register_design",
    "clear_user_registry",
    "ComponentTemplate",
    "ComponentTemplateExpansion",
    "ComponentTemplateRegistry",
    "BUILTIN_COMPONENT_TEMPLATE_PATHS",
    "TEMPLATE_SCHEMA",
    "evaluate_expression",
    "substitute_string",
    "walk_substitute",
    "DEFAULT_GEOMETRY_OPERATIONS",
    "GeometryOperationRegistry",
    "evaluate_geometry_operations",
    "resolve_operation_reference",
    # --- lazily resolved (optional gmsh/gdstk backends) ---
    "build_mesh",
    "build_mesh_from_geo",
    "build_geo",
    "build_gds",
    "GdsResult",
    "build_palace_config",
    "validate_config",
    "parse_geo_meta_sidecar",
    "solve_circuit_model",
    "CircuitModelResult",
    "JunctionInput",
    "ResonatorInput",
    "emit_block_geo",
    "lumped_cpw",
    "guided_wavelength",
    "preview_gds",
    "GdsPreview",
    "to_gdsfactory_component",
    "read_gds_layers",
]

# Lazy re-export of the optional gmsh/gdstk-backed entry points.  Delegating to
# ``quantum_dsl.dsl.__getattr__`` keeps ``import quantum_dsl`` free of any eager
# gmsh / gdstk import (those backends are only pulled in on first access).
# (``circuit_model`` is pure Python, but routed through the same lazy path for a
# uniform public surface.)
_LAZY_NAMES = frozenset({
    "build_mesh",
    "build_mesh_from_geo",
    "build_geo",
    "build_gds",
    "GdsResult",
    "build_palace_config",
    "validate_config",
    "parse_geo_meta_sidecar",
    "solve_circuit_model",
    "CircuitModelResult",
    "JunctionInput",
    "ResonatorInput",
    "emit_block_geo",
    "lumped_cpw",
    "guided_wavelength",
    "preview_gds",
    "GdsPreview",
    "to_gdsfactory_component",
    "read_gds_layers",
})


def __getattr__(name: str):
    """PEP 562 lazy export — defers to :mod:`quantum_dsl.dsl`."""
    if name in _LAZY_NAMES:
        from . import dsl
        return getattr(dsl, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
