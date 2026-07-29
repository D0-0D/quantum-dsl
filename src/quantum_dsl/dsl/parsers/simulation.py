# -*- coding: utf-8 -*-
"""Simulation / Gmsh block parsers for DSL v3."""

from __future__ import annotations

import math
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
    ASSEMBLE_KEYS,
    CELL_KEYS,
    CIRCUIT_MODEL_KEYS,
    CIRCUIT_QUBIT_KEYS,
    CIRCUIT_SQUID_KEYS,
    CPW_KEYS,
    EXTRACT_BLOCK_KEYS,
    EXTRACT_JUNCTION_KEYS,
    EXTRACT_KEYS,
    EXTRACT_MATRIX_KEYS,
    EXTRACT_SOURCES,
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
    RESONATOR_MODES,
    SIMULATION_KEYS,
    SOLVER_KEYS,
    SOLVER_TYPES,
    SUBSYSTEM_KEYS,
    SUBSYSTEM_TYPES,
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
    "_parse_extract",
    "_parse_assemble",
    "_parse_subsystems",
    "parse_geo_meta_sidecar",
    "_SIMPLE_UNIT_SUFFIX_RE",
    "_ALLOWED_IMPEDANCE_UNITS",
    "_HENRY_UNITS",
    "_EJ_FREQ_UNITS",
    "_FARAD_UNITS",
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
# Capacitance: unit string -> multiplier to Farad (SI).  Used by the M8 ``C_j``
# junction capacitance and to validate ``extract.blocks[].units``.  ASCII only
# ("uF" not "µF"), same reason as _HENRY_UNITS.
_FARAD_UNITS = {
    "F": 1.0, "mF": 1e-3, "uF": 1e-6, "nF": 1e-9, "pF": 1e-12, "fF": 1e-15,
    "aF": 1e-18,
}


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
        # (metal directly on dielectric, physically exact — but only builds for
        # geometries occ.fragment accepts at exact coplanarity). Default (key
        # absent) = 0.01 µm, see _gmsh_geo_source.CARVED_GROUND_SUBSTRATE_GAP_SI
        # for the measured C-vs-ε ladder behind that number.
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

    # Exactly one junction element: L_J (henry) / E_J (joule) / squid block.
    junction_keys = [k for k in ("L_J", "E_J", "squid") if k in entry]
    if len(junction_keys) != 1:
        raise DesignDslError(
            f"{owner} must set exactly one of 'L_J' / 'E_J' / 'squid'")
    resolved: dict[str, Any] = {"name": name, "islands": islands,
                                "L_J": None, "E_J": None,
                                "E_J1": None, "E_J2": None, "flux": None}
    if "L_J" in entry:
        l_j = _parse_unit_value(entry["L_J"], _HENRY_UNITS,
                                owner=f"{owner}.L_J")
        # isfinite: ``1e400H`` float-溢出成 inf, 光判 <= 0 会放行 (见 e_j_joule 旁注)
        if not (math.isfinite(l_j) and l_j > 0):
            raise DesignDslError(
                f"{owner}.L_J must be > 0 and finite, got {l_j}")
        resolved["L_J"] = l_j
    elif "E_J" in entry:
        e_j = _parse_ej_joule(entry["E_J"], owner=f"{owner}.E_J")
        if not (math.isfinite(e_j) and e_j > 0):
            raise DesignDslError(
                f"{owner}.E_J must be > 0 and finite, got {e_j}")
        resolved["E_J"] = e_j
    else:
        resolved.update(_parse_squid_entry(entry["squid"], owner=f"{owner}.squid"))

    # 结电容 C_j (M8 / P0-E), 法拉, 可选, **默认 0** —— 不静默移动任何现有数值。
    # 与 ``extract.blocks[].junctions[].C_j`` 同一语义 (``circuit_model`` 把它折在
    # 结基对角上、求逆之前), 在这里也开放, 好让**整片**路径同样能表达结电容。
    resolved["C_j"] = 0.0
    if "C_j" in entry:
        c_j = _parse_unit_value(entry["C_j"], _FARAD_UNITS, owner=f"{owner}.C_j")
        if not (math.isfinite(c_j) and c_j >= 0):
            raise DesignDslError(
                f"{owner}.C_j must be >= 0 and finite (farad), got {c_j}")
        resolved["C_j"] = c_j
    return resolved


def _parse_squid_entry(node: Any, *, owner: str) -> dict[str, Any]:
    """Parse a qubit's ``squid:`` sub-block → ``{E_J1, E_J2, flux}``.

    ``E_J1``/``E_J2`` (both REQUIRED, > 0) go through the very same
    ``_parse_ej_joule`` path as a single ``E_J`` (frequency form ``60GHz`` = E_J/h,
    or an explicit energy) → Joule.  ``flux`` is a BARE float = the external flux
    normalised to the flux quantum, Phi/Phi0 (dimensionless, period 1, any real);
    it defaults to 0.0 = zero flux, where E_J,eff is maximal (= E_J1 + E_J2).
    E_J1 != E_J2 is the asymmetric SQUID; see ``circuit_model.JunctionInput``.
    """
    if not isinstance(node, Mapping):
        raise DesignDslError(f"{owner} must be a mapping "
                             f"(e.g. {{E_J1: 60GHz, E_J2: 11GHz, flux: 0.0}})")
    _reject_unknown_keys(node, CIRCUIT_SQUID_KEYS, owner)
    out: dict[str, Any] = {}
    for key in ("E_J1", "E_J2"):
        if key not in node:
            raise DesignDslError(
                f"{owner} must set both 'E_J1' and 'E_J2' (a SQUID has two "
                f"junctions; for a single junction use 'E_J' or 'L_J')")
        value = _parse_ej_joule(node[key], owner=f"{owner}.{key}")
        if value <= 0:
            raise DesignDslError(f"{owner}.{key} must be > 0, got {value}")
        out[key] = value
    flux = node.get("flux", 0.0)
    if isinstance(flux, bool) or not isinstance(flux, (int, float)):
        raise DesignDslError(
            f"{owner}.flux must be a bare number — the external flux normalised "
            f"to the flux quantum, Phi/Phi0 (dimensionless); got {flux!r}")
    out["flux"] = float(flux)
    return out


def _parse_circuit_model(node: Any,
                         variables: Mapping[str, Any]) -> dict[str, Any]:
    """Parse the top-level ``circuit_model`` sidecar block (M6 junction inputs).

    Shape::

        circuit_model:
          qubits:
            - {name: A, island: A_pad_sfs, L_J: 10nH}
            - {name: B, islands: [B_pad_sfs], E_J: 14GHz}
            - name: C
              islands: [C_top_sfs, C_bot_sfs]
              squid: {E_J1: 60GHz, E_J2: 11GHz, flux: 0.0}

    ``island``/``islands`` reference a conductor terminal group name (or the
    ``role::layer::component::primitive`` token); the junction element is exactly
    one of ``L_J`` (henry), ``E_J`` (frequency E_J/h or energy) or ``squid``
    (a flux-tunable, possibly asymmetric SQUID — see ``_parse_squid_entry``).
    Returns ``{"qubits": [{name, islands: tuple, L_J, E_J, E_J1, E_J2, flux}]}``
    with L_J in Henry, E_J/E_J1/E_J2 in Joule, flux in Phi/Phi0 (unused fields
    are ``None``).  Names + normalised islands must be unique within the block.
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
# M8 New-LOM parity — extract: / assemble: / subsystems: (lom-parity-spec §4)
#
# 三个块合起来描述「多 cell 拼装」: ``extract`` 说每份 Maxwell C 矩阵从哪来 + 它的
# 节点叫什么名字 + 块内有哪些结; ``assemble`` 说参考地与不许被消元吃掉的节点;
# ``subsystems`` 说拼装后的矩阵上挂哪些量子子系统。全部是**纯数据**解析 —— 没有任何
# 几何 / 名字存在性校验 (那要等 geo_build 对着真实 TerminalBinding 做)。
#
# ⚠ ``extract.blocks`` 是**电学** Cell (一次 EM 提取), 与 M5a 的 ``cells:``
# (**几何** cell 实例) 是两个概念 —— 键名区分的理由见 schema.py 的对照注释
# (spec §8.1 / 风险 R10)。
#
# ⚠ 与 spec §4 P0-B 例子文本的**两处刻意偏离**:
#
#   1. spec 写单数 ``junction:`` (一个 block 一个结)。这里用**列表** ``junctions:``
#      —— 4.05 那种「每个 cell 一个结」只是最简情形; sung 那类一块里多个结的设计
#      (以及未来把 coupler 与 qubit 放进同一块) 必须能表达多个结, 而单数键要表达它
#      就得改 schema 或加 ``junction2``。列表从一开始就没有这个上限。
#   2. spec 写 ``{name: QB1, type: transmon, node: j1}`` —— 用 ``node:`` 指一个
#      **结**名, 与 tl_resonator 的 ``node:`` (真的指节点) 撞语义。这里 transmon 用
#      ``junction:`` 指结名、tl_resonator 用 ``node:`` 指节点名, 并按 type 收紧允许
#      键, 所以照 spec 例子写的 ``type: transmon`` + ``node:`` 会**直接报错**并提示
#      改用 ``junction:`` (而不是静默把结名当节点名查, 那会是 R2 类静默错)。
#
# 节点命名空间 (照 New LOM 4.05): ``nodes:`` 的 rename **先**生效, 之后
# ``junctions[].between`` / ``assemble.ground_node`` / ``nodes_force_keep`` /
# ``subsystems[].node`` 全部指 rename **之后**的名字; 没被 rename 的名字原样通过。
# ---------------------------------------------------------------------------

def _parse_node_name(value: Any, *, owner: str) -> str:
    """校验一个节点名是非空字符串, 原样返回 (**不解析、不校验存在性**)。

    节点名可以是结构化 geo 名 (``role::layer::component::primitive``) **或**已
    sanitize 的 terminal group 名 (``{comp}_{prim}_sfs``), **或**任何 ``nodes:``
    rename 之后的共享名 (``coupling``)。三者在这一层无法区分 —— 真正的解析要对着
    ``load_geo``/Palace 给出的 ``TerminalBinding`` 做, 所以这里只当字符串保留。
    """
    if not isinstance(value, str) or not value.strip():
        raise DesignDslError(f"{owner} must be a non-empty node-name string, "
                             f"got {value!r}")
    return value


def _parse_extract_matrix(node: Any, *, owner: str) -> dict[str, Any]:
    """解析 ``from: inline`` 的 ``matrix: {terminals, maxwell}`` 子块 (P0-C)。

    ``maxwell`` 必须是与 ``terminals`` 等长的**方阵**, 元素全部有限。拒 nan/inf 的
    理由与 ``palace_adapter.parse_capacitance_matrix`` 一样: ``nan <= 0`` 是 False,
    所有下游守卫都会放行, 于是静默算出一整片 nan 的 E_C/g。
    """
    if not isinstance(node, Mapping):
        raise DesignDslError(
            f"{owner} must be a mapping {{terminals, maxwell}}")
    _reject_unknown_keys(node, EXTRACT_MATRIX_KEYS, owner)
    raw_terminals = node.get("terminals")
    if not isinstance(raw_terminals, list) or not raw_terminals:
        raise DesignDslError(f"{owner}.terminals must be a non-empty list")
    terminals = tuple(
        _parse_node_name(t, owner=f"{owner}.terminals[{i}]")
        for i, t in enumerate(raw_terminals))
    if len(set(terminals)) != len(terminals):
        raise DesignDslError(f"{owner}.terminals has duplicate names")

    rows = node.get("maxwell")
    if not isinstance(rows, list) or not rows:
        raise DesignDslError(f"{owner}.maxwell must be a non-empty list of rows")
    if len(rows) != len(terminals):
        raise DesignDslError(
            f"{owner}.maxwell has {len(rows)} row(s) but "
            f"{len(terminals)} terminal(s) — must match")
    maxwell: list[tuple[float, ...]] = []
    for i, row in enumerate(rows):
        if not isinstance(row, list):
            raise DesignDslError(f"{owner}.maxwell[{i}] must be a list")
        if len(row) != len(terminals):
            raise DesignDslError(
                f"{owner}.maxwell[{i}] has {len(row)} entr(ies), expected "
                f"{len(terminals)} (the matrix must be square)")
        values: list[float] = []
        for j, cell in enumerate(row):
            if isinstance(cell, bool) or not isinstance(cell, (int, float)):
                raise DesignDslError(
                    f"{owner}.maxwell[{i}][{j}] must be a number, got {cell!r}")
            if not math.isfinite(cell):
                raise DesignDslError(
                    f"{owner}.maxwell[{i}][{j}] is not finite ({cell!r}) — a "
                    f"nan/inf entry passes every downstream '<= 0' guard and "
                    f"silently produces nan results")
            values.append(float(cell))
        maxwell.append(tuple(values))
    return {"terminals": terminals, "maxwell": tuple(maxwell)}


def _parse_extract_junction(entry: Any, *, owner: str) -> dict[str, Any]:
    """解析 ``extract.blocks[].junctions[]`` 的一个结。

    ``between`` = 1 或 2 个节点名 (1 = 结跨岛与地; 2 = 浮动/差分, 顺序 (a, b) 定义
    θ = φ_a − φ_b)。结元件 ``L_J`` (亨利) / ``E_J`` (焦耳) / ``squid`` **恰选一个**
    —— 与 ``JunctionInput.__post_init__`` 同语义, 但在解析层就报, 消息点名
    block + junction。``C_j`` = 结电容 → **法拉**, 默认 0.0 (P0-E: 默认 0 才不会
    静默移动任何现有数值)。
    """
    if not isinstance(entry, Mapping):
        raise DesignDslError(f"{owner} must be a mapping")
    _reject_unknown_keys(entry, EXTRACT_JUNCTION_KEYS, owner)
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        raise DesignDslError(f"{owner}.name must be a non-empty string")

    raw_between = entry.get("between")
    if not isinstance(raw_between, list) or not 1 <= len(raw_between) <= 2:
        raise DesignDslError(
            f"{owner}.between must be a list of 1 or 2 node names (1 = junction "
            f"to ground, 2 = floating/differential), got {raw_between!r}")
    between = tuple(
        _parse_node_name(n, owner=f"{owner}.between[{i}]")
        for i, n in enumerate(raw_between))

    junction_keys = [k for k in ("L_J", "E_J", "squid") if k in entry]
    if len(junction_keys) != 1:
        raise DesignDslError(
            f"{owner} (junction {name!r}) must set exactly one of "
            f"'L_J' / 'E_J' / 'squid', got {sorted(junction_keys)}")
    out: dict[str, Any] = {"name": name, "between": between,
                           "L_J": None, "E_J": None,
                           "E_J1": None, "E_J2": None, "flux": 0.0}
    if "L_J" in entry:
        l_j = _parse_unit_value(entry["L_J"], _HENRY_UNITS, owner=f"{owner}.L_J")
        if not (math.isfinite(l_j) and l_j > 0):
            raise DesignDslError(f"{owner}.L_J must be > 0 and finite, got {l_j}")
        out["L_J"] = l_j
    elif "E_J" in entry:
        e_j = _parse_ej_joule(entry["E_J"], owner=f"{owner}.E_J")
        if not (math.isfinite(e_j) and e_j > 0):
            raise DesignDslError(f"{owner}.E_J must be > 0 and finite, got {e_j}")
        out["E_J"] = e_j
    else:
        out.update(_parse_squid_entry(entry["squid"], owner=f"{owner}.squid"))

    c_j = 0.0
    if "C_j" in entry:
        c_j = _parse_unit_value(entry["C_j"], _FARAD_UNITS, owner=f"{owner}.C_j")
        if not (math.isfinite(c_j) and c_j >= 0):
            raise DesignDslError(
                f"{owner}.C_j must be >= 0 and finite (farad), got {c_j}")
    out["C_j"] = c_j
    return out


def _parse_extract(node: Any, variables: Mapping[str, Any], *,
                   base_dir: Path, where: str = "extract") -> dict[str, Any]:
    """解析顶层 ``extract:`` 块 —— 每个 block = 一次 EM 提取 = 一个 New LOM Cell。

    形状::

        extract:
          blocks:
            - name: qb1
              components: [QB1]          # from: solve 时必填 (块几何子集)
              from: solve                # solve (默认) | file | inline
              path: measured/QB1.csv     # from: file 时必填 (相对 sidecar → 绝对)
              matrix:                    # from: inline 时必填
                terminals: [a, b]
                maxwell: [[1.0, -0.1], [-0.1, 1.0]]
              units: fF                  # file/inline 矩阵的单位, 默认 fF
              nodes:                     # = New LOM 的 node_rename
                metal::1::QB1::coupler_pad: coupling
                QB1_readout_pad_sfs: readout_qb1
              junctions:
                - {name: j1, between: [...], E_J: 12.2GHz, C_j: 2fF}

    返回 ``{"blocks": [{name, components, source, path, matrix, units, nodes,
    junctions}]}``: ``source`` 是归一化后的 ``from`` (缺省 ``"solve"``);
    ``path`` 是绝对 ``Path`` 或 ``None``; ``matrix`` 是 ``_parse_extract_matrix``
    的产物或 ``None``; ``nodes`` 是原样保留的 ``{旧名: 新名}`` (**不**解析 key ——
    见 ``_parse_node_name``); ``junctions`` 里 L_J 亨利 / E_J 焦耳 / C_j 法拉。

    block 名必须唯一; ``junctions[].name`` 在**整个 extract 块内全局**唯一
    (拼装后它们同处一个结索引空间, 重名会静默把两个结叠在一起)。
    """
    if not isinstance(node, Mapping):
        raise DesignDslError(f"{where} must be a mapping")
    node = _walk_substitute(dict(node), dict(variables))
    _reject_unknown_keys(node, EXTRACT_KEYS, where)

    raw_blocks = node.get("blocks")
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise DesignDslError(f"{where}.blocks must be a non-empty list")

    blocks: list[dict[str, Any]] = []
    seen_blocks: set[str] = set()
    seen_junctions: dict[str, str] = {}
    for index, entry in enumerate(raw_blocks):
        owner = f"{where}.blocks[{index}]"
        if not isinstance(entry, Mapping):
            raise DesignDslError(f"{owner} must be a mapping")
        _reject_unknown_keys(entry, EXTRACT_BLOCK_KEYS, owner)

        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise DesignDslError(f"{owner}.name must be a non-empty string")
        if name in seen_blocks:
            raise DesignDslError(
                f"{where}.blocks: duplicate block name {name!r} (every block "
                f"name must be unique — it labels one EM extraction)")
        seen_blocks.add(name)

        source = entry.get("from", "solve")
        if source not in EXTRACT_SOURCES:
            raise DesignDslError(
                f"{owner}.from must be one of {sorted(EXTRACT_SOURCES)}, got "
                f"{source!r}")

        components: tuple[str, ...] = ()
        if "components" in entry:
            raw_components = entry["components"]
            if not isinstance(raw_components, list) or not raw_components:
                raise DesignDslError(
                    f"{owner}.components must be a non-empty list of component "
                    f"names")
            for i, comp in enumerate(raw_components):
                if not isinstance(comp, str) or not comp:
                    raise DesignDslError(
                        f"{owner}.components[{i}] must be a non-empty string, "
                        f"got {comp!r}")
            components = tuple(raw_components)
        elif source == "solve":
            raise DesignDslError(
                f"{owner}.components is required for from: solve (it selects the "
                f"geometry subset emit_block_geo carves out)")

        path: Path | None = None
        if "path" in entry:
            raw_path = entry["path"]
            if not isinstance(raw_path, str) or not raw_path:
                raise DesignDslError(f"{owner}.path must be a non-empty string")
            path = (base_dir / raw_path).resolve()
            if not path.is_file():
                raise DesignDslError(
                    f"{owner}.path capacitance-matrix file not found: {path}")
        elif source == "file":
            raise DesignDslError(f"{owner}.path is required for from: file")

        matrix: dict[str, Any] | None = None
        if "matrix" in entry:
            matrix = _parse_extract_matrix(entry["matrix"],
                                           owner=f"{owner}.matrix")
        elif source == "inline":
            raise DesignDslError(f"{owner}.matrix is required for from: inline")

        # units 只对 file/inline 的矩阵有意义 (solve 的单位由 Palace 输出决定)。
        units = entry.get("units", "fF")
        if units not in _FARAD_UNITS:
            raise DesignDslError(
                f"{owner}.units must be one of {sorted(_FARAD_UNITS)}, got "
                f"{units!r}")

        nodes: dict[str, str] = {}
        if "nodes" in entry:
            raw_nodes = entry["nodes"]
            if not isinstance(raw_nodes, Mapping):
                raise DesignDslError(
                    f"{owner}.nodes must be a mapping {{old_name: shared_name}}")
            for raw_key, raw_value in raw_nodes.items():
                key = _parse_node_name(raw_key, owner=f"{owner}.nodes key")
                nodes[key] = _parse_node_name(
                    raw_value, owner=f"{owner}.nodes[{key!r}]")

        junctions: list[dict[str, Any]] = []
        if "junctions" in entry:
            raw_junctions = entry["junctions"]
            if not isinstance(raw_junctions, list) or not raw_junctions:
                raise DesignDslError(
                    f"{owner}.junctions must be a non-empty list")
            for j_index, j_entry in enumerate(raw_junctions):
                junction = _parse_extract_junction(
                    j_entry, owner=f"{owner}.junctions[{j_index}]")
                previous = seen_junctions.get(junction["name"])
                if previous is not None:
                    raise DesignDslError(
                        f"{owner}.junctions[{j_index}]: junction name "
                        f"{junction['name']!r} already used by block "
                        f"{previous!r} — junction names must be unique across "
                        f"the whole extract block")
                seen_junctions[junction["name"]] = name
                junctions.append(junction)

        blocks.append({
            "name": name, "components": components, "source": source,
            "path": path, "matrix": matrix, "units": units, "nodes": nodes,
            "junctions": junctions,
        })
    return {"blocks": blocks}


def _parse_assemble(node: Any, variables: Mapping[str, Any], *,
                    where: str = "assemble") -> dict[str, Any]:
    """解析顶层 ``assemble:`` 块 (P0-B 拼装参数)。

    形状::

        assemble:
          ground_node: ground::1::chip::gnd
          nodes_force_keep: [readout_qb1, readout_qb2]

    返回 ``{"ground_node": str|None, "nodes_force_keep": tuple[str, ...]}``。
    两者都指 ``extract.blocks[].nodes`` rename **之后**的名字, 原样保留字符串。
    ``nodes_force_keep`` 是 Schur 消元的兜底 (风险 R3): 列在里面的节点不许被当成
    非动力学节点消掉 —— 谐振器接入点必须留着才能接 tl_resonator。
    """
    if not isinstance(node, Mapping):
        raise DesignDslError(f"{where} must be a mapping")
    node = _walk_substitute(dict(node), dict(variables))
    _reject_unknown_keys(node, ASSEMBLE_KEYS, where)

    ground_node: str | None = None
    if "ground_node" in node:
        ground_node = _parse_node_name(node["ground_node"],
                                       owner=f"{where}.ground_node")
    keep: tuple[str, ...] = ()
    if "nodes_force_keep" in node:
        raw_keep = node["nodes_force_keep"]
        if not isinstance(raw_keep, list):
            raise DesignDslError(
                f"{where}.nodes_force_keep must be a list of node names")
        keep = tuple(
            _parse_node_name(n, owner=f"{where}.nodes_force_keep[{i}]")
            for i, n in enumerate(raw_keep))
    return {"ground_node": ground_node, "nodes_force_keep": keep}


def _parse_cpw_block(node: Any, *, owner: str,
                     variables: Mapping[str, Any]) -> dict[str, float]:
    """解析 ``subsystems[].cpw:`` 子块 (P0-F CPW 解析计算器的输入)。

    ⚠ **单位**: 长度量解成 **µm** (``_parse_number`` 的默认单位, 与仓库内部单位
    一致 —— ``_units.SI_PER_INTERNAL = 1e-6``), **不是**米。``cpw_analytic`` 的接口
    是 SI 米, 所以 ``geo_build`` 接线时负责 ×1e-6。这里不换算, 是为了让 sidecar 里
    所有长度 (layer_stack.thickness / airbox / cpw.length) 单位一致、可互相比对。
    """
    if not isinstance(node, Mapping):
        raise DesignDslError(
            f"{owner} must be a mapping (e.g. "
            f"{{line_width: 10um, line_gap: 6um, length: 4200um}})")
    _reject_unknown_keys(node, CPW_KEYS, owner)
    for key in ("line_width", "line_gap", "length"):
        if key not in node:
            raise DesignDslError(
                f"{owner}.{key} is required (a CPW needs line_width, line_gap "
                f"and length)")
    out: dict[str, float] = {}
    for key in CPW_KEYS:
        if key not in node:
            continue
        value = _parse_number(node[key], variables, owner=f"{owner}.{key}")
        if not (math.isfinite(value) and value > 0):
            raise DesignDslError(
                f"{owner}.{key} must be > 0 and finite (µm), got {value}")
        out[key] = value
    return out


# 每种子系统各自的允许键 —— SUBSYSTEM_KEYS 是两者的并集, 按 type 再收紧一次, 免得
# ``type: transmon`` 写了 ``f_res:``/``node:`` 却被静默忽略 (见模块顶部偏离 #2)。
_TRANSMON_KEYS = {"name", "type", "junction"}
_TL_RESONATOR_KEYS = {"name", "type", "node", "f_res", "Z0", "mode", "cpw"}


def _parse_subsystems(node: Any, variables: Mapping[str, Any], *,
                      where: str = "subsystems") -> list[dict[str, Any]]:
    """解析顶层 ``subsystems:`` 列表 (P0-B/D: 拼装后矩阵上的量子子系统)。

    形状::

        subsystems:
          - {name: QB1, type: transmon, junction: j1}
          - {name: RO1, type: tl_resonator, node: readout_qb1, f_res: 7.0GHz,
             Z0: 50ohm, mode: half_wave}
          - {name: RO2, type: tl_resonator, node: readout_qb2, Z0: 50ohm,
             mode: half_wave, cpw: {line_width: 10um, line_gap: 6um,
                                    length: 4200um}}

    ``transmon`` 用 ``junction:`` 指 ``extract.blocks[].junctions[].name``;
    ``tl_resonator`` 用 ``node:`` 指一个 (rename 之后的) 节点名 —— 谐振器的耦合爪子
    就是那个节点上的真实导体。两者的允许键按 type 分开校验 (见模块顶部偏离 #2)。

    ``f_res`` 与 ``cpw`` **恰给一个**: 直接给频率, 或给 CPW 几何让 P0-F 解析算。
    ``f_res`` 解成 **Hz** (``7.0GHz`` → 7e9) 且按 spec §4 P0-D / 风险 R5 是**裸**
    频率 (与老 LOM 的 ``freq_readout`` 一致, 不是 New LOM 的 dressed 频率);
    ``Z0`` 解成**欧姆** (``50ohm`` 或裸数字 ``50``), 默认 50.0;
    ``mode`` 默认 ``half_wave``。

    返回 list[dict]: transmon → ``{name, type, junction}``; tl_resonator →
    ``{name, type, node, f_res, Z0, mode, cpw}``。``name`` 必须唯一。
    """
    if not isinstance(node, list) or not node:
        raise DesignDslError(f"{where} must be a non-empty list")
    node = _walk_substitute(list(node), dict(variables))

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, entry in enumerate(node):
        owner = f"{where}[{index}]"
        if not isinstance(entry, Mapping):
            raise DesignDslError(f"{owner} must be a mapping")
        _reject_unknown_keys(entry, SUBSYSTEM_KEYS, owner)
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise DesignDslError(f"{owner}.name must be a non-empty string")
        if name in seen:
            raise DesignDslError(
                f"{where}: duplicate subsystem name {name!r}")
        seen.add(name)

        kind = entry.get("type")
        if kind not in SUBSYSTEM_TYPES:
            raise DesignDslError(
                f"{owner}.type must be one of {sorted(SUBSYSTEM_TYPES)}, got "
                f"{kind!r}")
        allowed = _TRANSMON_KEYS if kind == "transmon" else _TL_RESONATOR_KEYS
        extra = set(entry) - allowed
        if extra:
            raise DesignDslError(
                f"{owner} (type {kind!r}) does not accept key(s) "
                f"{sorted(extra)}; allowed: {sorted(allowed)} — a transmon names "
                f"its JUNCTION via 'junction:', a tl_resonator names its NODE "
                f"via 'node:'")

        if kind == "transmon":
            junction = entry.get("junction")
            if not isinstance(junction, str) or not junction:
                raise DesignDslError(
                    f"{owner}.junction is required for type 'transmon' (the "
                    f"extract.blocks[].junctions[].name this qubit is built on)")
            out.append({"name": name, "type": kind, "junction": junction})
            continue

        node_name = entry.get("node")
        if not isinstance(node_name, str) or not node_name:
            raise DesignDslError(
                f"{owner}.node is required for type 'tl_resonator' (the node "
                f"whose conductor is the resonator's coupling claw)")
        if ("f_res" in entry) == ("cpw" in entry):
            raise DesignDslError(
                f"{owner} must set exactly one of 'f_res' (bare resonance "
                f"frequency) / 'cpw' (CPW geometry → f_res computed analytically)")
        f_res: float | None = None
        if "f_res" in entry:
            f_res = _parse_unit_value(entry["f_res"], _EJ_FREQ_UNITS,
                                      owner=f"{owner}.f_res")
            if not (math.isfinite(f_res) and f_res > 0):
                raise DesignDslError(
                    f"{owner}.f_res must be > 0 and finite (Hz), got {f_res}")
        cpw = None
        if "cpw" in entry:
            cpw = _parse_cpw_block(entry["cpw"], owner=f"{owner}.cpw",
                                   variables=variables)
        z0 = 50.0
        if "Z0" in entry:
            z0 = _parse_scalar_with_optional_unit(
                entry["Z0"], variables, owner=f"{owner}.Z0",
                allowed_units=_ALLOWED_IMPEDANCE_UNITS)
            if not (math.isfinite(z0) and z0 > 0):
                raise DesignDslError(
                    f"{owner}.Z0 must be > 0 and finite (ohm), got {z0}")
        mode = entry.get("mode", "half_wave")
        if mode not in RESONATOR_MODES:
            raise DesignDslError(
                f"{owner}.mode must be one of {sorted(RESONATOR_MODES)}, got "
                f"{mode!r}")
        out.append({"name": name, "type": kind, "node": node_name,
                    "f_res": f_res, "Z0": z0, "mode": mode, "cpw": cpw})
    return out


# ---------------------------------------------------------------------------
# standalone *.meta.yaml sidecar loader (Layer-1 physics metadata)
# ---------------------------------------------------------------------------

def parse_geo_meta_sidecar(path: str | Path) -> dict[str, Any]:
    """Load + validate a standalone ``*.meta.yaml`` sidecar paired with a ``.geo``.

    The sidecar is **purely physics metadata** (materials / eps_r / mesh / GDS
    layer map / solver); the geometry lives in the companion ``.geo`` named by
    the ``geo`` key.  Top-level keys are validated vs ``GEO_META_ROOT_KEYS``;
    ``${var}`` expressions resolve against ``vars``; the ``simulation.gmsh`` block
    is parsed in **geo mode** (ports bind by group name; gds/solver blocks parsed;
    no component-layer coverage check); the optional ``circuit_model`` block (M6
    junction inputs) is parsed by ``_parse_circuit_model``; the optional M8
    New-LOM-parity blocks ``extract`` / ``assemble`` / ``subsystems`` are parsed by
    ``_parse_extract`` / ``_parse_assemble`` / ``_parse_subsystems``.

    Returns ``{"geo": <abs Path>, "cells": [...], "simulation": {...},
    "vars": {...}, "circuit_model": {...}|None, "extract": {...}|None,
    "assemble": {...}|None, "subsystems": [...]|None}`` — ``geo`` resolved to an
    absolute path RELATIVE TO THE SIDECAR; every optional block is ``None`` when
    absent (a sidecar declaring none of them behaves exactly as before).

    Raises:
        DesignDslError: file missing / not a mapping / unknown top-level key /
            missing ``geo`` / referenced ``.geo`` not found / invalid
            ``circuit_model`` / ``extract`` / ``assemble`` / ``subsystems`` block.
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

    # M8: the three New-LOM parity blocks.  Each is None when absent, so a sidecar
    # that declares none of them behaves EXACTLY as before (whole-chip solve).
    extract_out: dict[str, Any] | None = None
    if "extract" in raw:
        extract_out = _parse_extract(raw["extract"], variables,
                                     base_dir=sidecar.parent,
                                     where=f"{sidecar.name}.extract")
    assemble_out: dict[str, Any] | None = None
    if "assemble" in raw:
        assemble_out = _parse_assemble(raw["assemble"], variables,
                                       where=f"{sidecar.name}.assemble")
    subsystems_out: list[dict[str, Any]] | None = None
    if "subsystems" in raw:
        subsystems_out = _parse_subsystems(raw["subsystems"], variables,
                                           where=f"{sidecar.name}.subsystems")

    return {
        "geo": geo_path,
        "cells": cells,
        "simulation": simulation_out,
        "vars": dict(variables),
        "circuit_model": circuit_model_out,
        "extract": extract_out,
        "assemble": assemble_out,
        "subsystems": subsystems_out,
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
