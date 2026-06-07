# -*- coding: utf-8 -*-
"""quantum_dsl — a native YAML design DSL for superconducting-circuit layouts.

Extracted as a standalone package from qiskit-metal's
``qiskit_metal.toolbox_metal.dsl``. It resolves a single ``.metal.yaml`` file
into a Metal ``QDesign`` (and, optionally, a Gmsh mesh) without instantiating
qlibrary component classes.

The implementation lives in the :mod:`quantum_dsl.dsl` subpackage; the most
common entry points are re-exported here for convenience::

    import quantum_dsl
    design = quantum_dsl.build_design("chain_2q_native.metal.yaml")

This package depends on ``qiskit-metal`` at runtime (for unit parsing, the
``draw`` helpers, ``QComponent`` and the optional Gmsh renderer utilities).
The Gmsh adapter (``quantum_dsl.dsl.gmsh_adapter``) is imported lazily because
it additionally needs the optional ``gmsh`` package.
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
]

# Lazy re-export of the optional gmsh/gdstk-backed entry points.  Delegating to
# ``quantum_dsl.dsl.__getattr__`` keeps ``import quantum_dsl`` free of any eager
# gmsh / gdstk import (those backends are only pulled in on first access).
_LAZY_NAMES = frozenset({
    "build_mesh",
    "build_mesh_from_geo",
    "build_geo",
    "build_gds",
    "GdsResult",
    "build_palace_config",
    "validate_config",
    "parse_geo_meta_sidecar",
})


def __getattr__(name: str):
    """PEP 562 lazy export — defers to :mod:`quantum_dsl.dsl`."""
    if name in _LAZY_NAMES:
        from . import dsl
        return getattr(dsl, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
