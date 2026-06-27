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
    CELL_KEYS,
    CIRCUIT_MODEL_KEYS,
    CIRCUIT_QUBIT_KEYS,
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
    "_parse_unit_value",
    "_parse_circuit_model",
    "_parse_geo_cells",
    "parse_geo_meta_sidecar",
    "_SIMPLE_UNIT_SUFFIX_RE",
    "_ALLOWED_IMPEDANCE_UNITS",
    "_HENRY_UNITS",
    "_EJ_FREQ_UNITS",
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


# ---------------------------------------------------------------------------
# SI-prefix-scaling unit parser — for physical quantities whose magnitude DOES
# depend on the prefix (inductance H, frequency Hz).  Unlike
# ``_parse_scalar_with_optional_unit`` (which validates then DISCARDS the unit,
# correct only for dimensionless/ohm fields), this MULTIPLIES by the prefix
# factor: ``"10nH" -> 1e-8`` (henry), not ``10.0``.  Never route L_J/E_J through
# ``parse_number`` (length, µm-default) or ``_parse_scalar_with_optional_unit``
# (no scaling) — both silently mis-handle SI prefixes.
# ---------------------------------------------------------------------------

# Inductance: unit string -> multiplier to Henry (SI).  ASCII only (the suffix
# regex matches [A-Za-z]+, so use "uH" not "µH").
_HENRY_UNITS = {
    "H": 1.0, "mH": 1e-3, "uH": 1e-6, "nH": 1e-9, "pH": 1e-12, "fH": 1e-15,
}
# E_J as a frequency E_J/h: unit string -> multiplier to Hz (then ×h -> Joule).
_EJ_FREQ_UNITS = {"Hz": 1.0, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9, "THz": 1e12}
# E_J as a bare energy: unit string -> multiplier to Joule.
_EJ_ENERGY_UNITS = {"J": 1.0}


def _parse_unit_value(value: Any, units: Mapping[str, float], *,
                      owner: str) -> float:
    """Parse ``"<number><unit>"`` with an explicit SI-prefixed unit → SI float.

    ``units`` maps each accepted unit string to its multiplier into the SI base
    unit (e.g. ``{"nH": 1e-9, "H": 1.0}``).  An explicit unit is **required**: a
    bare number (or unitless string) is rejected, because for a quantity whose
    magnitude depends on the prefix ``10`` is dangerously ambiguous (10 H vs
    10 nH differ by 1e9), so authoring must spell the unit (``"10nH"``).  SI
    floats are still accepted via the dataclass API, not here.  ``${var}`` is
    resolved upstream by ``_walk_substitute``.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        raise DesignDslError(
            f"{owner} needs an explicit unit (one of {sorted(units)}); got bare "
            f"number {value!r} — write it with a unit, e.g. '10nH'.")
    if not isinstance(value, str):
        raise DesignDslError(
            f"{owner} must be a '<number><unit>' string, got {value!r}")
    match = _SIMPLE_UNIT_SUFFIX_RE.match(value.strip())
    if match is None:
        raise DesignDslError(
            f"{owner} must be '<number><unit>', got {value!r}")
    number_part, unit_part = match.group(1), (match.group(2) or "")
    if unit_part == "":
        raise DesignDslError(
            f"{owner} needs an explicit unit (one of {sorted(units)}); got bare "
            f"string {value!r}.")
    if unit_part not in units:
        raise DesignDslError(
            f"{owner} has unsupported unit {unit_part!r}; expected one of "
            f"{sorted(units)}")
    try:
        return float(number_part) * units[unit_part]
    except ValueError as exc:
        raise DesignDslError(
            f"{owner} numeric portion is invalid: {value!r}") from exc


def _parse_ej_joule(value: Any, *, owner: str) -> float:
    """Parse an ``E_J`` field → **Joule** (explicit unit required).

    Accepts a frequency form (``"14GHz"`` etc., interpreted as E_J/h and
    multiplied by Planck's h to get Joule) or an explicit energy (``"...J"``).
    Frequency is the form physicists usually quote, so it is the primary path.
    A bare number is rejected for the same reason as ``_parse_unit_value`` (the
    SI-float path is the dataclass API).
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        raise DesignDslError(
            f"{owner} needs an explicit unit (a frequency "
            f"{sorted(_EJ_FREQ_UNITS)} for E_J/h, or an energy "
            f"{sorted(_EJ_ENERGY_UNITS)}); got bare number {value!r}.")
    if not isinstance(value, str):
        raise DesignDslError(
            f"{owner} must be a '<number><unit>' string, got {value!r}")
    match = _SIMPLE_UNIT_SUFFIX_RE.match(value.strip())
    if match is None:
        raise DesignDslError(f"{owner} must be '<number><unit>', got {value!r}")
    number_part, unit_part = match.group(1), (match.group(2) or "")
    if unit_part in _EJ_ENERGY_UNITS:
        return float(number_part) * _EJ_ENERGY_UNITS[unit_part]
    if unit_part in _EJ_FREQ_UNITS:
        # E_J given as the frequency E_J/h -> energy = h * f.  h hardcoded as the
        # exact SI-2019 value (mirrors circuit_model.H_PLANCK; kept local so the
        # pure parser needs no import of circuit_model).
        h_planck = 6.62607015e-34
        return float(number_part) * _EJ_FREQ_UNITS[unit_part] * h_planck
    raise DesignDslError(
        f"{owner} needs an explicit unit (a frequency {sorted(_EJ_FREQ_UNITS)} "
        f"(E_J/h) or an energy {sorted(_EJ_ENERGY_UNITS)}); got {value!r}")


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
    if "substrate_gap_um" in node:
        # auto-substrate top nudge below a carved metal ground (µm). 0 = coplanar
        # (metal directly on dielectric, physically exact). Default (key absent)
        # is the 1µm in _gmsh_geo_source.CARVED_GROUND_SUBSTRATE_GAP_SI.
        try:
            gap = float(node["substrate_gap_um"])
        except (TypeError, ValueError) as exc:
            raise DesignDslError(
                "simulation.gmsh.substrate_gap_um must be a number (µm), got "
                f"{node['substrate_gap_um']!r}") from exc
        if gap < 0:
            raise DesignDslError(
                f"simulation.gmsh.substrate_gap_um must be >= 0, got {gap}")
        out["substrate_gap_um"] = gap

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
    if "outer_boundary" in node:
        ob = node["outer_boundary"]
        if ob not in ("ground", "open"):
            raise DesignDslError(
                "simulation.gmsh.solver.outer_boundary must be 'ground' or "
                f"'open', got {ob!r}")
        out["outer_boundary"] = ob
    return out


# ---------------------------------------------------------------------------
# circuit_model block — M6 junction inputs (islands + L_J/E_J) for the
# capacitance→Hamiltonian solve.  Output is consumed by
# ``circuit_model.solve_circuit_model`` via ``circuit_model.JunctionInput``.
# ---------------------------------------------------------------------------

def _sanitize_group(name: str) -> str:
    """Mirror ``_gmsh_physical._sanitize`` (kept local so this pure parser does
    not import the gmsh-backed module): non-``[A-Za-z0-9_]`` → ``_``; empty →
    ``unnamed``; leading digit → ``g_`` prefix."""
    out = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not out:
        return "unnamed"
    if out[0].isdigit():
        out = "g_" + out
    return out


def _normalize_island_ref(ref: str, *, owner: str) -> str:
    """Normalise a qubit island reference to a conductor terminal **group name**.

    Accepts either the sanitised group name verbatim (``"A_pad_sfs"`` — exactly
    the ``capacitance.terminals[].group`` label authored in chip.results.yaml),
    or the structured ``role::layer::component::primitive`` token
    (``"metal::1::A::pad"``) as sugar, which is converted to the surface group
    name ``_sanitize("{component}_{primitive}_sfs")``.  Final existence is
    validated at solve time against the real terminal set (which lists the
    available groups on mismatch), so this conversion is best-effort sugar.
    """
    if not isinstance(ref, str) or not ref:
        raise DesignDslError(f"{owner} island ref must be a non-empty string")
    if "::" not in ref:
        return ref
    parts = ref.split("::")
    if len(parts) != 4 or not all(parts):
        raise DesignDslError(
            f"{owner} structured island ref {ref!r} must be "
            f"'role::layer::component::primitive'")
    role, _layer, component, primitive = parts
    # Only metal conductors become capacitance Terminals (qubit islands); other
    # roles use a different surface-group template (e.g. ground -> gnd_layerN_sfs),
    # so a {component}_{primitive}_sfs normalisation would be wrong for them.
    if role != "metal":
        raise DesignDslError(
            f"{owner} structured island ref {ref!r} must have role 'metal' "
            f"(qubit islands are metal conductor surfaces), got role {role!r}")
    return _sanitize_group(f"{component}_{primitive}_sfs")


def _parse_qubit_entry(entry: Any, index: int) -> dict[str, Any]:
    owner = f"circuit_model.qubits[{index}]"
    if not isinstance(entry, Mapping):
        raise DesignDslError(f"{owner} must be a mapping")
    _reject_unknown_keys(entry, CIRCUIT_QUBIT_KEYS, owner)

    name = entry.get("name")
    if not isinstance(name, str) or not name:
        raise DesignDslError(f"{owner}.name must be a non-empty string")

    # island (scalar) XOR islands (list) — normalise to a tuple of group names.
    if ("island" in entry) == ("islands" in entry):
        raise DesignDslError(
            f"{owner} must set exactly one of 'island' / 'islands'")
    if "island" in entry:
        raw_islands: Any = [entry["island"]]
    else:
        raw_islands = entry["islands"]
        if not isinstance(raw_islands, list) or not raw_islands:
            raise DesignDslError(f"{owner}.islands must be a non-empty list")
    islands = tuple(
        _normalize_island_ref(isl, owner=owner) for isl in raw_islands)

    # L_J (henry) XOR E_J (joule).
    if ("L_J" in entry) == ("E_J" in entry):
        raise DesignDslError(
            f"{owner} must set exactly one of 'L_J' / 'E_J'")
    resolved: dict[str, Any] = {"name": name, "islands": islands,
                                "L_J": None, "E_J": None}
    if "L_J" in entry:
        l_j = _parse_unit_value(entry["L_J"], _HENRY_UNITS,
                                owner=f"{owner}.L_J")
        if l_j <= 0:
            raise DesignDslError(f"{owner}.L_J must be > 0, got {l_j}")
        resolved["L_J"] = l_j
    else:
        e_j = _parse_ej_joule(entry["E_J"], owner=f"{owner}.E_J")
        if e_j <= 0:
            raise DesignDslError(f"{owner}.E_J must be > 0, got {e_j}")
        resolved["E_J"] = e_j
    return resolved


def _parse_circuit_model(node: Any,
                         variables: Mapping[str, Any]) -> dict[str, Any]:
    """Parse the top-level ``circuit_model`` sidecar block (M6 junction inputs).

    Shape::

        circuit_model:
          qubits:
            - {name: A, island: A_pad_sfs, L_J: 10nH}
            - {name: B, islands: [B_pad_sfs], E_J: 14GHz}

    ``island``/``islands`` reference a conductor terminal group name (or the
    ``role::layer::component::primitive`` token); ``L_J`` (henry) and ``E_J``
    (frequency E_J/h or energy) are mutually exclusive.  Returns
    ``{"qubits": [{name, islands: tuple, L_J: float|None, E_J: float|None}]}``
    with L_J in Henry and E_J in Joule.  Names + normalised islands must be
    unique within the block.
    """
    if not isinstance(node, Mapping):
        raise DesignDslError("circuit_model must be a mapping")
    node = _walk_substitute(dict(node), dict(variables))
    _reject_unknown_keys(node, CIRCUIT_MODEL_KEYS, "circuit_model")

    qubits_raw = node.get("qubits")
    if not isinstance(qubits_raw, list) or not qubits_raw:
        raise DesignDslError("circuit_model.qubits must be a non-empty list")

    out_qubits: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    seen_islands: set[str] = set()
    for index, entry in enumerate(qubits_raw):
        q = _parse_qubit_entry(entry, index)
        if q["name"] in seen_names:
            raise DesignDslError(
                f"circuit_model.qubits[{index}].name {q['name']!r} reused")
        seen_names.add(q["name"])
        for island in q["islands"]:
            if island in seen_islands:
                raise DesignDslError(
                    f"circuit_model.qubits[{index}] island {island!r} already "
                    f"bound to another qubit")
            seen_islands.add(island)
        out_qubits.append(q)
    return {"qubits": out_qubits}


# ---------------------------------------------------------------------------
# standalone *.meta.yaml sidecar loader (Layer-1 physics metadata)
# ---------------------------------------------------------------------------

def parse_geo_meta_sidecar(path: str | Path) -> dict[str, Any]:
    """Load + validate a standalone ``*.meta.yaml`` sidecar paired with a ``.geo``.

    The sidecar is **purely physics metadata** (materials / eps_r / mesh / GDS
    layer map / solver); the geometry lives in the companion ``.geo`` named by
    the ``geo`` key.  Top-level keys are validated vs ``GEO_META_ROOT_KEYS``
    (``{schema, geo, vars, simulation, circuit_model}``); ``${var}`` expressions
    resolve against ``vars``; the ``simulation.gmsh`` block is parsed in **geo
    mode** (ports bind by group name; gds/solver blocks parsed; no
    component-layer coverage check); the optional ``circuit_model`` block (M6
    junction inputs) is parsed by ``_parse_circuit_model``.

    Returns ``{"geo": <abs Path>, "simulation": {...}, "vars": {...},
    "circuit_model": {...}|None}`` — ``geo`` resolved to an absolute path
    RELATIVE TO THE SIDECAR; ``circuit_model`` is ``None`` when the block is absent.

    Raises:
        DesignDslError: file missing / not a mapping / unknown top-level key /
            missing ``geo`` / referenced ``.geo`` not found / invalid
            ``circuit_model`` block.
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

    # M5a: a 'cells:' block lowers v3 template instances → a generated
    # <stem>.elaborated.geo (emit_geo bridge).  When present, 'geo' is OPTIONAL
    # (the geometry is generated, not authored).  Exactly one source is required.
    cells = _parse_geo_cells(raw.get("cells"), f"{sidecar.name}")
    geo_path: Path | None = None
    if "geo" in raw:
        geo_ref = raw["geo"]
        if not isinstance(geo_ref, str) or not geo_ref:
            raise DesignDslError(
                f"{sidecar.name}: 'geo' must be a non-empty path string")
        geo_path = (sidecar.parent / geo_ref).resolve()
        if not geo_path.is_file():
            raise DesignDslError(
                f"{sidecar.name}: companion geo file not found: {geo_path}")
    elif not cells:
        raise DesignDslError(
            f"{sidecar.name}: a 'geo' key (companion .geo) or a 'cells:' block "
            f"(emit_geo cell instances) is required")

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

    circuit_model_out: dict[str, Any] | None = None
    if "circuit_model" in raw:
        circuit_model_out = _parse_circuit_model(raw["circuit_model"], variables)

    return {
        "geo": geo_path,
        "cells": cells,
        "simulation": simulation_out,
        "vars": dict(variables),
        "circuit_model": circuit_model_out,
    }


def _parse_geo_cells(node: Any, where: str) -> list[dict[str, Any]]:
    """Validate + normalize the optional ``cells:`` block of a geo meta sidecar.

    Each entry lowers one placed v3 component-template cell (the emit_geo
    bridge).  Returns a list of plain dicts (consumed by
    ``geo_emit.elaborate_cells``); ``[]`` when absent.  Validation here is
    structural only — ``cell_type`` resolution and option semantics are deferred
    to ``build_ir`` at elaboration time.
    """
    if node is None:
        return []
    if not isinstance(node, list):
        raise DesignDslError(f"{where}.cells must be a list of cell mappings")
    cells: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, entry in enumerate(node):
        if not isinstance(entry, Mapping):
            raise DesignDslError(f"{where}.cells[{i}] must be a mapping")
        extra = set(entry) - CELL_KEYS
        if extra:
            raise DesignDslError(
                f"{where}.cells[{i}]: unknown key(s) {sorted(extra)} "
                f"(allowed: {sorted(CELL_KEYS)})")
        cell_type = entry.get("cell_type")
        component = entry.get("component")
        if not isinstance(cell_type, str) or not cell_type:
            raise DesignDslError(
                f"{where}.cells[{i}]: 'cell_type' (template id) is required")
        if not isinstance(component, str) or not component:
            raise DesignDslError(
                f"{where}.cells[{i}]: 'component' (unique name) is required")
        if component in seen:
            raise DesignDslError(
                f"{where}.cells: duplicate component name {component!r} "
                f"(every cell's 'component' must be globally unique)")
        seen.add(component)
        params = entry.get("params")
        if params is not None and not isinstance(params, Mapping):
            raise DesignDslError(
                f"{where}.cells[{i}].params must be a mapping")
        cells.append(dict(entry))
    return cells
