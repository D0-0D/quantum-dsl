# -*- coding: utf-8 -*-
"""Simulation / Gmsh block parsers for DSL v3."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from ..errors import DesignDslError
from .._helpers import (
    parse_number as _parse_number,
    reject_unknown_keys as _reject_unknown_keys,
)
from ..expression import walk_substitute as _walk_substitute
from ..ir import ComponentIR
from ..schema import (
    AIRBOX_KEYS,
    GDS_LAYER_MAP_ENTRY_KEYS,
    GDS_SIM_KEYS,
    GEO_META_ROOT_KEYS,
    GEO_SURFACE_ROLES,
    GMSH_SIM_KEYS,
    LAYER_STACK_ENTRY_KEYS,
    LAYER_STACK_KINDS,
    MESH_KEYS,
    MESH_REFINE_KEYS,
    OUTPUT_KEYS,
    PORT_KEYS,
    PORT_TYPES,
    SIMULATION_KEYS,
    SOLVER_KEYS,
    SOLVER_TYPES,
    SYMMETRY_CONDITIONS,
    SYMMETRY_KEYS,
    SYMMETRY_PLANES,
)

__all__ = [
    "_parse_simulation",
    "_parse_gmsh_simulation",
    "_parse_layer_stack",
    "_parse_airbox",
    "_parse_ports",
    "_parse_geo_ports",
    "_parse_symmetry",
    "_parse_mesh_settings",
    "_parse_output_settings",
    "_parse_gds_settings",
    "_parse_solver_settings",
    "_parse_scalar_with_optional_unit",
    "parse_geo_meta_sidecar",
    "_SIMPLE_UNIT_SUFFIX_RE",
    "_ALLOWED_IMPEDANCE_UNITS",
]

_SIMPLE_UNIT_SUFFIX_RE = re.compile(
    r"^\s*([+\-]?\d*\.?\d+(?:[eE][+\-]?\d+)?)\s*([A-Za-z]+)?\s*$")
_ALLOWED_IMPEDANCE_UNITS = {"", "ohm", "ohms", "Ohm", "Ohms", "OHM", "OHMS"}


def _parse_scalar_with_optional_unit(value: Any, variables: Mapping[str, Any],
                                     *, owner: str,
                                     allowed_units: set[str]) -> float:
    """Parse a number with a permitted non-length unit suffix (e.g. ``"50ohm"``).

    Dedicated to impedance / eps_r / tan_delta / scaling / value fields that
    use non-length units.  Length fields should use ``_parse_number``
    (``parse_value``, default µm).  ``parse_value`` would raise a pint dimension
    error for ``"50ohm"`` and fall back to the raw string, so here we strip the
    allowed unit suffix manually before calling ``float()``.  ``allowed_units``
    containing ``""`` means bare numbers are accepted.
    Variable interpolation (``"${var}"``) is resolved upstream by
    ``_walk_substitute``.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        match = _SIMPLE_UNIT_SUFFIX_RE.match(stripped)
        if match is None:
            raise DesignDslError(
                f"{owner} must be a number with optional unit, got "
                f"{value!r}")
        number_part, unit_part = match.group(1), (match.group(2) or "")
        if unit_part not in allowed_units:
            raise DesignDslError(
                f"{owner} has unsupported unit {unit_part!r}; expected one "
                f"of {sorted(allowed_units)}")
        try:
            return float(number_part)
        except ValueError as exc:
            raise DesignDslError(
                f"{owner} numeric portion is invalid: {value!r}") from exc
    raise DesignDslError(
        f"{owner} must be a number or '<number><unit>', got {value!r}")


def _parse_simulation(spec: Any, ctx: Mapping[str, Any],
                      variables: Mapping[str, Any],
                      components: list[ComponentIR]) -> dict[str, Any]:
    """Resolve the optional ``simulation`` block into plain Python values.

    All length literals (``"12um"`` etc.) are parsed here into µm floats,
    consistent with ``PrimitiveIR.geometry`` / ``PinIR.width``; the adapter
    entry point multiplies by 1e-6 to convert to SI.  The returned dict
    contains only resolved values — no ``${...}`` strings remain.
    """
    if spec is None:
        return {}
    if not isinstance(spec, Mapping):
        raise DesignDslError("simulation must be a mapping")
    spec = _walk_substitute(dict(spec), ctx)
    _reject_unknown_keys(spec, SIMULATION_KEYS, "simulation")

    out: dict[str, Any] = {}
    if "gmsh" in spec:
        out["gmsh"] = _parse_gmsh_simulation(spec["gmsh"], variables, components)
    return out


def _parse_gmsh_simulation(node: Any, variables: Mapping[str, Any],
                            components: list[ComponentIR],
                            *, geo_mode: bool = False) -> dict[str, Any]:
    """Parse a ``simulation.gmsh`` block.

    ``geo_mode`` (sidecar / native ``.geo`` path): ports bind by physical-group
    NAME (``_parse_geo_ports``) instead of ``component.pin`` (existence deferred
    to ``load_geo``); the ``gds`` and ``solver`` sidecar blocks are parsed; the
    legacy "stack covers every primitive.layer" check is skipped (there is no
    component list — the ``.geo`` is the geometry source).  In YAML mode the
    behaviour is unchanged.
    """
    if not isinstance(node, Mapping):
        raise DesignDslError("simulation.gmsh must be a mapping")
    _reject_unknown_keys(node, GMSH_SIM_KEYS, "simulation.gmsh")

    out: dict[str, Any] = {}
    if "layer_stack" in node:
        out["layer_stack"] = _parse_layer_stack(node["layer_stack"], variables)
    if "airbox" in node:
        out["airbox"] = _parse_airbox(node["airbox"], variables)
    if "ports" in node:
        if geo_mode:
            out["ports"] = _parse_geo_ports(node["ports"], variables)
        else:
            out["ports"] = _parse_ports(node["ports"], variables, components)
    if "symmetry" in node:
        out["symmetry"] = _parse_symmetry(node["symmetry"])
    if "mesh" in node:
        out["mesh"] = _parse_mesh_settings(node["mesh"], variables)
    if "output" in node:
        out["output"] = _parse_output_settings(node["output"], variables)
    if "gds" in node:
        out["gds"] = _parse_gds_settings(node["gds"], variables)
    if "solver" in node:
        out["solver"] = _parse_solver_settings(node["solver"], variables)

    # plan §0 end-of-section requirement: when the gmsh block is present,
    # layer_stack is mandatory and must contain at least one metal entry.
    if "layer_stack" not in out:
        raise DesignDslError("simulation.gmsh.layer_stack is required")
    stack = out["layer_stack"]
    if not stack:
        raise DesignDslError(
            "simulation.gmsh.layer_stack must declare at least one layer")
    if not any(entry["kind"] == "metal" for entry in stack.values()):
        raise DesignDslError(
            "simulation.gmsh.layer_stack must contain at least one metal layer")

    # plan §10 risk register: stack must cover all primitive.layer values.
    # Skipped in geo_mode — geometry comes from the .geo, not a component list;
    # the .geo's authored layers are validated against the stack in load_geo /
    # populate_tracker_from_geo instead.
    if not geo_mode:
        declared_layers = set(stack.keys())
        referenced_layers = {
            primitive.layer
            for component in components
            for primitive in component.primitives
        }
        missing = referenced_layers - declared_layers
        if missing:
            raise DesignDslError(
                f"simulation.gmsh.layer_stack missing layer(s) referenced by "
                f"primitives: {sorted(missing)}")
    return out


def _parse_layer_stack(node: Any,
                       variables: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    if not isinstance(node, Mapping):
        raise DesignDslError(
            "simulation.gmsh.layer_stack must be a mapping {layer: spec}")
    out: dict[int, dict[str, Any]] = {}
    for raw_key, entry in node.items():
        try:
            layer = int(raw_key)
        except (TypeError, ValueError) as exc:
            raise DesignDslError(
                f"simulation.gmsh.layer_stack key must be int, got "
                f"{raw_key!r}") from exc
        if not isinstance(entry, Mapping):
            raise DesignDslError(
                f"simulation.gmsh.layer_stack[{layer}] must be a mapping")
        _reject_unknown_keys(
            entry, LAYER_STACK_ENTRY_KEYS,
            f"simulation.gmsh.layer_stack[{layer}]")
        kind = entry.get("kind")
        if kind not in LAYER_STACK_KINDS:
            raise DesignDslError(
                f"simulation.gmsh.layer_stack[{layer}].kind must be one of "
                f"{sorted(LAYER_STACK_KINDS)}, got {kind!r}")
        if "thickness" not in entry:
            raise DesignDslError(
                f"simulation.gmsh.layer_stack[{layer}].thickness is required")
        thickness = _parse_number(
            entry["thickness"], variables,
            owner=f"simulation.gmsh.layer_stack[{layer}].thickness")
        if thickness == 0:
            raise DesignDslError(
                f"simulation.gmsh.layer_stack[{layer}].thickness must be "
                f"non-zero (negative = dielectric extruded toward -z)")
        z = _parse_number(
            entry.get("z", 0.0), variables,
            owner=f"simulation.gmsh.layer_stack[{layer}].z")
        resolved: dict[str, Any] = {
            "kind": kind,
            "thickness": thickness,
            "z": z,
        }
        if "material" in entry:
            material = entry["material"]
            if not isinstance(material, str) or not material:
                raise DesignDslError(
                    f"simulation.gmsh.layer_stack[{layer}].material must be a "
                    f"non-empty string")
            resolved["material"] = material
        if "eps_r" in entry:
            resolved["eps_r"] = _parse_scalar_with_optional_unit(
                entry["eps_r"], variables,
                owner=f"simulation.gmsh.layer_stack[{layer}].eps_r",
                allowed_units={""})
        if "tan_delta" in entry:
            resolved["tan_delta"] = _parse_scalar_with_optional_unit(
                entry["tan_delta"], variables,
                owner=f"simulation.gmsh.layer_stack[{layer}].tan_delta",
                allowed_units={""})
        out[layer] = resolved
    return out


def _parse_airbox(node: Any,
                  variables: Mapping[str, Any]) -> dict[str, float]:
    """Parse the ``simulation.gmsh.airbox`` block.

    Bug #12 fix: ``top`` and ``bottom`` must be strictly positive (> 0) because
    ``render_vacuum_box`` requires them to extrude above and below the substrate.
    ``side_buffer`` must be non-negative (>= 0).
    """
    if not isinstance(node, Mapping):
        raise DesignDslError("simulation.gmsh.airbox must be a mapping")
    _reject_unknown_keys(node, AIRBOX_KEYS, "simulation.gmsh.airbox")
    out: dict[str, float] = {}
    for key in AIRBOX_KEYS:
        if key in node:
            value = _parse_number(node[key], variables,
                                  owner=f"simulation.gmsh.airbox.{key}")
            if key in {"top", "bottom"}:
                if value <= 0:
                    raise DesignDslError(
                        f"simulation.gmsh.airbox.{key} must be > 0 "
                        f"(got {value}; render_vacuum_box requires strictly positive)")
            else:
                if value < 0:
                    raise DesignDslError(
                        f"simulation.gmsh.airbox.{key} must be >= 0, got {value}")
            out[key] = value
    return out


def _parse_ports(
    node: Any,
    variables: Mapping[str, Any],
    components: list[ComponentIR],
) -> list[dict[str, Any]]:
    if not isinstance(node, list):
        raise DesignDslError("simulation.gmsh.ports must be a list")
    component_pins: dict[str, set[str]] = {
        component.name: {pin.name for pin in component.pins}
        for component in components
    }
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, entry in enumerate(node):
        owner = f"simulation.gmsh.ports[{index}]"
        if not isinstance(entry, Mapping):
            raise DesignDslError(f"{owner} must be a mapping")
        _reject_unknown_keys(entry, PORT_KEYS, owner)
        pin_ref = entry.get("pin")
        if not isinstance(pin_ref, str) or "." not in pin_ref:
            raise DesignDslError(
                f"{owner}.pin must be 'component.pin', got {pin_ref!r}")
        comp_name, pin_name = pin_ref.rsplit(".", 1)
        if comp_name not in component_pins:
            raise DesignDslError(
                f"{owner}.pin references unknown component {comp_name!r}")
        if pin_name not in component_pins[comp_name]:
            raise DesignDslError(
                f"{owner}.pin references unknown pin "
                f"{comp_name}.{pin_name}")
        key = (comp_name, pin_name)
        if key in seen:
            raise DesignDslError(
                f"{owner}.pin reuses endpoint {comp_name}.{pin_name}")
        seen.add(key)
        port_type = entry.get("type", "lumped")
        if port_type not in PORT_TYPES:
            raise DesignDslError(
                f"{owner}.type must be one of {sorted(PORT_TYPES)}, got "
                f"{port_type!r}")
        resolved: dict[str, Any] = {
            "component": comp_name,
            "pin": pin_name,
            "type": port_type,
        }
        if "impedance" in entry:
            resolved["impedance"] = _parse_scalar_with_optional_unit(
                entry["impedance"], variables,
                owner=f"{owner}.impedance",
                allowed_units=_ALLOWED_IMPEDANCE_UNITS)
        if "value" in entry:
            resolved["value"] = _parse_scalar_with_optional_unit(
                entry["value"], variables, owner=f"{owner}.value",
                allowed_units={""})
        out.append(resolved)
    return out


def _parse_symmetry(node: Any) -> list[dict[str, str]]:
    if not isinstance(node, list):
        raise DesignDslError("simulation.gmsh.symmetry must be a list")
    out: list[dict[str, str]] = []
    seen_planes: set[str] = set()
    for index, entry in enumerate(node):
        owner = f"simulation.gmsh.symmetry[{index}]"
        if not isinstance(entry, Mapping):
            raise DesignDslError(f"{owner} must be a mapping")
        _reject_unknown_keys(entry, SYMMETRY_KEYS, owner)
        plane = entry.get("plane")
        if plane not in SYMMETRY_PLANES:
            raise DesignDslError(
                f"{owner}.plane must be one of {sorted(SYMMETRY_PLANES)}, got "
                f"{plane!r}")
        if plane in seen_planes:
            raise DesignDslError(f"{owner}.plane {plane!r} declared twice")
        seen_planes.add(plane)
        condition = entry.get("condition", "pec")
        if condition not in SYMMETRY_CONDITIONS:
            raise DesignDslError(
                f"{owner}.condition must be one of "
                f"{sorted(SYMMETRY_CONDITIONS)}, got {condition!r}")
        out.append({"plane": plane, "condition": condition})
    return out


def _parse_mesh_settings(node: Any,
                         variables: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(node, Mapping):
        raise DesignDslError("simulation.gmsh.mesh must be a mapping")
    _reject_unknown_keys(node, MESH_KEYS, "simulation.gmsh.mesh")
    out: dict[str, Any] = {}
    for key in ("max_size", "min_size", "max_size_jj"):
        if key in node:
            value = _parse_number(node[key], variables,
                                  owner=f"simulation.gmsh.mesh.{key}")
            if value <= 0:
                raise DesignDslError(
                    f"simulation.gmsh.mesh.{key} must be > 0, got {value}")
            out[key] = value
    if "conductor_refine" in node:
        refine = node["conductor_refine"]
        if not isinstance(refine, Mapping):
            raise DesignDslError(
                "simulation.gmsh.mesh.conductor_refine must be a mapping")
        _reject_unknown_keys(
            refine, MESH_REFINE_KEYS,
            "simulation.gmsh.mesh.conductor_refine")
        resolved_refine: dict[str, float] = {}
        for key in MESH_REFINE_KEYS:
            if key in refine:
                resolved_refine[key] = _parse_number(
                    refine[key], variables,
                    owner=f"simulation.gmsh.mesh.conductor_refine.{key}")
        out["conductor_refine"] = resolved_refine
    return out


def _parse_output_settings(node: Any,
                            variables: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(node, Mapping):
        raise DesignDslError("simulation.gmsh.output must be a mapping")
    _reject_unknown_keys(node, OUTPUT_KEYS, "simulation.gmsh.output")
    out: dict[str, Any] = {}
    if "format" in node:
        fmt = node["format"]
        if not isinstance(fmt, str) or not fmt:
            raise DesignDslError(
                "simulation.gmsh.output.format must be a non-empty string")
        out["format"] = fmt
    if "scaling" in node:
        out["scaling"] = _parse_scalar_with_optional_unit(
            node["scaling"], variables,
            owner="simulation.gmsh.output.scaling",
            allowed_units={""})
    return out


# ---------------------------------------------------------------------------
# geo-mode ports — bind by physical-group NAME (existence deferred to load_geo)
# ---------------------------------------------------------------------------

def _parse_geo_ports(node: Any,
                     variables: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Parse ports for the native ``.geo`` path.

    Geo-mode ports reference a physical-group NAME authored in the ``.geo``
    (the structured ``port::N::C::pin`` / conductor ``metal::N::C::P`` name),
    NOT a ``component.pin`` against a component list (there is none — the
    geometry is the ``.geo``).  Existence of the named group is deferred to
    ``load_geo`` at mesh time.  Accepted entry keys mirror ``PORT_KEYS`` but
    the ``pin`` field is a group name string (a single token, no ``"."``
    requirement); ``type`` defaults to ``lumped``.
    """
    if not isinstance(node, list):
        raise DesignDslError("simulation.gmsh.ports must be a list")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, entry in enumerate(node):
        owner = f"simulation.gmsh.ports[{index}]"
        if not isinstance(entry, Mapping):
            raise DesignDslError(f"{owner} must be a mapping")
        _reject_unknown_keys(entry, PORT_KEYS, owner)
        group = entry.get("pin")
        if not isinstance(group, str) or not group:
            raise DesignDslError(
                f"{owner}.pin must be a non-empty physical-group name "
                f"(geo mode), got {group!r}")
        if group in seen:
            raise DesignDslError(
                f"{owner}.pin reuses physical-group name {group!r}")
        seen.add(group)
        port_type = entry.get("type", "lumped")
        if port_type not in PORT_TYPES:
            raise DesignDslError(
                f"{owner}.type must be one of {sorted(PORT_TYPES)}, got "
                f"{port_type!r}")
        resolved: dict[str, Any] = {"group": group, "type": port_type}
        if "impedance" in entry:
            resolved["impedance"] = _parse_scalar_with_optional_unit(
                entry["impedance"], variables,
                owner=f"{owner}.impedance",
                allowed_units=_ALLOWED_IMPEDANCE_UNITS)
        if "value" in entry:
            resolved["value"] = _parse_scalar_with_optional_unit(
                entry["value"], variables, owner=f"{owner}.value",
                allowed_units={""})
        out.append(resolved)
    return out


# ---------------------------------------------------------------------------
# gds block — GDS layer map + gdstk library settings (sidecar only)
# ---------------------------------------------------------------------------

def _parse_gds_layer_entry(entry: Any, owner: str) -> dict[str, int]:
    """Parse one ``{layer, datatype}`` GDS-map entry into ints."""
    if not isinstance(entry, Mapping):
        raise DesignDslError(f"{owner} must be a mapping {{layer, datatype}}")
    _reject_unknown_keys(entry, GDS_LAYER_MAP_ENTRY_KEYS, owner)
    if "layer" not in entry:
        raise DesignDslError(f"{owner}.layer is required")
    resolved: dict[str, int] = {}
    for key in ("layer", "datatype"):
        if key in entry:
            try:
                resolved[key] = int(entry[key])
            except (TypeError, ValueError) as exc:
                raise DesignDslError(
                    f"{owner}.{key} must be an integer, got "
                    f"{entry[key]!r}") from exc
    return resolved


def _parse_gds_settings(node: Any,
                        variables: Mapping[str, Any]) -> dict[str, Any]:
    """Parse the ``simulation.gmsh.gds`` block (GDS layer map + gdstk opts).

    Validates top-level keys vs ``GDS_SIM_KEYS`` and every ``by_name`` /
    ``by_role`` / ``by_layer`` entry vs ``GDS_LAYER_MAP_ENTRY_KEYS``.  ``by_role``
    keys must be valid surface roles.  Resolved values are passed verbatim to
    ``build_gds(..., layer_map=...)`` (the GDS adapter ships defaults; this
    block overrides them).
    """
    if not isinstance(node, Mapping):
        raise DesignDslError("simulation.gmsh.gds must be a mapping")
    _reject_unknown_keys(node, GDS_SIM_KEYS, "simulation.gmsh.gds")
    out: dict[str, Any] = {}

    for str_key in ("lib_name", "top_cell"):
        if str_key in node:
            value = node[str_key]
            if not isinstance(value, str) or not value:
                raise DesignDslError(
                    f"simulation.gmsh.gds.{str_key} must be a non-empty string")
            out[str_key] = value

    for float_key in ("unit", "precision", "arc_tol_um"):
        if float_key in node:
            out[float_key] = _parse_scalar_with_optional_unit(
                node[float_key], variables,
                owner=f"simulation.gmsh.gds.{float_key}",
                allowed_units={""})

    if "default_datatype" in node:
        try:
            out["default_datatype"] = int(node["default_datatype"])
        except (TypeError, ValueError) as exc:
            raise DesignDslError(
                "simulation.gmsh.gds.default_datatype must be an integer, got "
                f"{node['default_datatype']!r}") from exc

    if "union_same_layer" in node:
        value = node["union_same_layer"]
        if not isinstance(value, bool):
            raise DesignDslError(
                "simulation.gmsh.gds.union_same_layer must be a boolean, got "
                f"{value!r}")
        out["union_same_layer"] = value

    for map_key in ("by_name", "by_role", "by_layer"):
        if map_key not in node:
            continue
        block = node[map_key]
        if not isinstance(block, Mapping):
            raise DesignDslError(
                f"simulation.gmsh.gds.{map_key} must be a mapping")
        resolved_map: dict[Any, dict[str, int]] = {}
        for raw_key, entry in block.items():
            owner = f"simulation.gmsh.gds.{map_key}[{raw_key!r}]"
            if map_key == "by_role" and raw_key not in GEO_SURFACE_ROLES:
                raise DesignDslError(
                    f"{owner}: unknown role {raw_key!r} (expected one of "
                    f"{sorted(GEO_SURFACE_ROLES)})")
            key: Any = raw_key
            if map_key == "by_layer":
                try:
                    key = int(raw_key)
                except (TypeError, ValueError) as exc:
                    raise DesignDslError(
                        f"{owner}: layer key must be an integer, got "
                        f"{raw_key!r}") from exc
            resolved_map[key] = _parse_gds_layer_entry(entry, owner)
        out[map_key] = resolved_map

    return out


# ---------------------------------------------------------------------------
# solver block — Palace solver settings (sidecar only)
# ---------------------------------------------------------------------------

def _parse_solver_settings(node: Any,
                           variables: Mapping[str, Any]) -> dict[str, Any]:
    """Parse the ``simulation.gmsh.solver`` block (Palace solver settings).

    Validates keys vs ``SOLVER_KEYS`` and ``type`` vs ``SOLVER_TYPES``.
    Consumed by ``build_palace_config`` (``l0`` / ``order``) and the runner.
    """
    if not isinstance(node, Mapping):
        raise DesignDslError("simulation.gmsh.solver must be a mapping")
    _reject_unknown_keys(node, SOLVER_KEYS, "simulation.gmsh.solver")
    out: dict[str, Any] = {}
    solver_type = node.get("type", "Electrostatic")
    if solver_type not in SOLVER_TYPES:
        raise DesignDslError(
            f"simulation.gmsh.solver.type must be one of "
            f"{sorted(SOLVER_TYPES)}, got {solver_type!r}")
    out["type"] = solver_type
    if "order" in node:
        try:
            out["order"] = int(node["order"])
        except (TypeError, ValueError) as exc:
            raise DesignDslError(
                "simulation.gmsh.solver.order must be an integer, got "
                f"{node['order']!r}") from exc
        if out["order"] < 1:
            raise DesignDslError(
                f"simulation.gmsh.solver.order must be >= 1, got {out['order']}")
    if "l0" in node:
        out["l0"] = _parse_scalar_with_optional_unit(
            node["l0"], variables, owner="simulation.gmsh.solver.l0",
            allowed_units={""})
    if "device" in node:
        device = node["device"]
        if not isinstance(device, str) or not device:
            raise DesignDslError(
                "simulation.gmsh.solver.device must be a non-empty string")
        out["device"] = device
    return out


# ---------------------------------------------------------------------------
# standalone *.meta.yaml sidecar loader (Layer-1 physics metadata)
# ---------------------------------------------------------------------------

def parse_geo_meta_sidecar(path: str | Path) -> dict[str, Any]:
    """Load + validate a standalone ``*.meta.yaml`` sidecar paired with a ``.geo``.

    The sidecar is **purely physics metadata** (materials / eps_r / mesh / GDS
    layer map / solver); the geometry lives in the companion ``.geo`` named by
    the ``geo`` key.  Top-level keys are validated vs ``GEO_META_ROOT_KEYS``
    (``{schema, geo, vars, simulation}``); ``${var}`` expressions resolve against
    ``vars``; the ``simulation.gmsh`` block is parsed in **geo mode** (ports bind
    by group name; gds/solver blocks parsed; no component-layer coverage check).

    Returns ``{"geo": <abs Path>, "simulation": {...}, "vars": {...}}`` — ``geo``
    resolved to an absolute path RELATIVE TO THE SIDECAR.

    Raises:
        DesignDslError: file missing / not a mapping / unknown top-level key /
            missing ``geo`` / referenced ``.geo`` not found.
    """
    sidecar = Path(path)
    if not sidecar.is_file():
        raise DesignDslError(f"geo meta sidecar not found: {sidecar}")
    try:
        raw = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DesignDslError(
            f"failed to parse geo meta sidecar {sidecar}: {exc}") from exc
    if raw is None:
        raise DesignDslError(f"geo meta sidecar {sidecar} is empty")
    if not isinstance(raw, Mapping):
        raise DesignDslError(
            f"geo meta sidecar {sidecar} must be a mapping at the top level")
    _reject_unknown_keys(raw, GEO_META_ROOT_KEYS, f"{sidecar.name}")

    variables = raw.get("vars") or {}
    if not isinstance(variables, Mapping):
        raise DesignDslError(f"{sidecar.name}: vars must be a mapping")

    if "geo" not in raw:
        raise DesignDslError(
            f"{sidecar.name}: 'geo' key (path to companion .geo) is required")
    geo_ref = raw["geo"]
    if not isinstance(geo_ref, str) or not geo_ref:
        raise DesignDslError(
            f"{sidecar.name}: 'geo' must be a non-empty path string")
    geo_path = (sidecar.parent / geo_ref).resolve()
    if not geo_path.is_file():
        raise DesignDslError(
            f"{sidecar.name}: companion geo file not found: {geo_path}")

    simulation_block = raw.get("simulation") or {}
    if not isinstance(simulation_block, Mapping):
        raise DesignDslError(f"{sidecar.name}: simulation must be a mapping")
    # Resolve ${var} across the simulation block, then validate keys.
    simulation_block = _walk_substitute(dict(simulation_block), dict(variables))
    _reject_unknown_keys(simulation_block, SIMULATION_KEYS,
                         f"{sidecar.name}.simulation")
    simulation_out: dict[str, Any] = {}
    if "gmsh" in simulation_block:
        simulation_out["gmsh"] = _parse_gmsh_simulation(
            simulation_block["gmsh"], variables, [], geo_mode=True)

    return {
        "geo": geo_path,
        "simulation": simulation_out,
        "vars": dict(variables),
    }
