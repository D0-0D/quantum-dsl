# -*- coding: utf-8 -*-
"""Public package API for the native YAML design DSL."""

from __future__ import annotations

# Import first: applies the µm default-unit override before any parse_value
# call (see quantum_dsl.dsl._units).
from . import _units  # noqa: F401

from .builder import (
    BUILTIN_DESIGNS,
    CURRENT_SCHEMA,
    ComponentIR,
    DesignDslError,
    DesignIR,
    NativeComponent,
    PinIR,
    PrimitiveIR,
    build_design,
    build_ir,
    clear_user_registry,
    export_ir_to_metal,
    register_design,
)
from .component_templates import ComponentTemplateExpansion
from .expression import evaluate_expression, substitute_string, walk_substitute
from .geometry_ops import (
    DEFAULT_GEOMETRY_OPERATIONS,
    GeometryOperationRegistry,
    evaluate_geometry_operations,
    resolve_operation_reference,
)
from .template_model import ComponentTemplate, TEMPLATE_SCHEMA
from .template_registry import (
    BUILTIN_COMPONENT_TEMPLATE_PATHS,
    ComponentTemplateRegistry,
)

__all__ = [
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


# Lazy attribute access for the optional gmsh/gdstk-backed entry points so that
# ``import quantum_dsl.dsl`` does NOT eagerly import gmsh or gdstk.  Each symbol
# is resolved from its submodule on first access.  Submodules: ``gmsh_adapter``
# (gmsh), ``gds_adapter`` (gdstk), ``palace_adapter`` (pure), ``geo_build``,
# ``parsers.simulation`` (pure).
_LAZY_EXPORTS = {
    "build_mesh": ("gmsh_adapter", "build_mesh"),
    "build_mesh_from_geo": ("gmsh_adapter", "build_mesh_from_geo"),
    "build_geo": ("geo_build", "build_geo"),
    "build_gds": ("gds_adapter", "build_gds"),
    "GdsResult": ("gds_adapter", "GdsResult"),
    "build_palace_config": ("palace_adapter", "build_palace_config"),
    "validate_config": ("palace_adapter", "validate_config"),
    "parse_geo_meta_sidecar": ("parsers.simulation", "parse_geo_meta_sidecar"),
}


def __getattr__(name: str):
    """PEP 562 lazy export of optional-backend entry points."""
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}")
    import importlib
    module_name, attr = target
    module = importlib.import_module(f"{__name__}.{module_name}")
    return getattr(module, attr)
