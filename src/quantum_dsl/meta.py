# -*- coding: utf-8 -*-
"""``*.meta.yaml`` sidecar 加载 (契约 N3; 词汇见 SPEC「Layer-1 词汇」)。

扁平词汇, schema ``quantum-dsl/meta/1``。未知顶层键一律 raise (typo 不静默)。
``circuit_model.qubits`` 里的结参数在加载时就解析成数:
``L_J`` → 亨利 (SI); ``E_J``/``E_J1``/``E_J2`` 按论文惯例写成频率 (如
``12.2GHz``) → 解析成 **Hz (E_J/h)**, 换算焦耳 (×h) 是 build 接线时的事。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .errors import QuantumDslError
from .units import parse_quantity

__all__ = ["Meta", "load_meta"]

_SCHEMA = "quantum-dsl/meta/1"
_TOP_KEYS = frozenset({"schema", "geo", "materials", "airbox", "mesh", "solver",
                       "gds", "circuit_model", "extract", "subsystems"})


@dataclass(frozen=True)
class Meta:
    """已加载的 sidecar。字典字段原样透传 (键即 SPEC 词汇)。"""

    path: Path
    geo_path: Path
    materials: dict = field(default_factory=dict)
    airbox: dict = field(default_factory=dict)
    mesh: dict = field(default_factory=dict)
    solver: dict = field(default_factory=dict)
    gds: dict = field(default_factory=dict)
    circuit_model: dict = field(default_factory=dict)
    extract: dict = field(default_factory=dict)
    subsystems: list = field(default_factory=list)


def load_meta(path) -> Meta:
    """加载并校验 ``*.meta.yaml`` → :class:`Meta`。"""
    path = Path(path)
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise QuantumDslError(f"load_meta: cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise QuantumDslError(f"load_meta: invalid YAML in {path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise QuantumDslError(f"load_meta: {path} is not a YAML mapping")

    unknown = sorted(set(doc) - _TOP_KEYS)
    if unknown:
        raise QuantumDslError(
            f"load_meta: {path}: unknown top-level key(s) {unknown} "
            f"(known: {sorted(_TOP_KEYS)})")
    if doc.get("schema") != _SCHEMA:
        raise QuantumDslError(
            f"load_meta: {path}: schema {doc.get('schema')!r} != {_SCHEMA!r}")
    geo = doc.get("geo")
    if not isinstance(geo, str) or not geo:
        raise QuantumDslError(f"load_meta: {path}: 'geo' must name a .geo file")

    circuit_model = copy.deepcopy(doc.get("circuit_model") or {})
    for q in circuit_model.get("qubits", []):
        if not isinstance(q, dict):
            raise QuantumDslError(
                f"load_meta: {path}: circuit_model.qubits entries must be "
                f"mappings, got {q!r}")
        for key in ("L_J", "E_J"):
            if key in q:
                q[key] = parse_quantity(q[key])
        for key in ("E_J1", "E_J2"):
            if key in q.get("squid", {}):
                q["squid"][key] = parse_quantity(q["squid"][key])

    return Meta(
        path=path,
        geo_path=path.parent / geo,
        materials=doc.get("materials") or {},
        airbox=doc.get("airbox") or {},
        mesh=doc.get("mesh") or {},
        solver=doc.get("solver") or {},
        gds=doc.get("gds") or {},
        circuit_model=circuit_model,
        extract=doc.get("extract") or {},
        subsystems=doc.get("subsystems") or [],
    )
