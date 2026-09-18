# -*- coding: utf-8 -*-
"""``*.meta.yaml`` sidecar 加载 (契约「meta 加载」; 词汇见 SPEC「Layer-1 词汇」)。

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
_TOP_KEYS = frozenset({"schema", "geo", "layout", "layers", "materials", "airbox", "mesh",
                       "solver", "gds", "circuit_model", "extract", "subsystems"})
_LAYER_KEYS = frozenset({"kind", "gds"})
_LAYER_KINDS = frozenset({"conductor", "junction", "drawing"})


@dataclass(frozen=True)
class Meta:
    """已加载的 sidecar。字典字段原样透传 (键即 SPEC 词汇)。"""

    path: Path
    geo_path: Path | None                       # 手写 .geo (与 layout_path 二选一)
    layout_path: Path | None = None             # 版图 *.layout.yaml
    layers: dict = field(default_factory=dict)  # 芯片层表 {id: {kind, gds: [layer, datatype]}}
    materials: dict = field(default_factory=dict)
    airbox: dict = field(default_factory=dict)
    mesh: dict = field(default_factory=dict)
    solver: dict = field(default_factory=dict)
    gds: dict = field(default_factory=dict)
    circuit_model: dict = field(default_factory=dict)
    extract: dict = field(default_factory=dict)
    subsystems: list = field(default_factory=list)


def _layers(tbl, path) -> dict:
    """``layers: {a: {kind: conductor, gds: [1, 0]}, …}`` 校验 + 归一 (gds → (layer, datatype))。
    kind: conductor (进静电网格, z = 0) / junction (集总, 进 GDS 不进网格) / drawing (只进 GDS)。"""
    if not isinstance(tbl, dict):
        raise QuantumDslError(f"load_meta: {path}: 'layers' must be a mapping")
    out = {}
    for lid, spec in tbl.items():
        where = f"load_meta: {path}: layers[{lid!r}]"
        if not isinstance(spec, dict):
            raise QuantumDslError(f"{where} must be a mapping with kind:")
        unknown = sorted(set(spec) - _LAYER_KEYS)
        if unknown:
            raise QuantumDslError(f"{where}: unknown key(s) {unknown} (known: {sorted(_LAYER_KEYS)}); "
                                  f"z != 0 conductor planes are not supported yet")
        if spec.get("kind") not in _LAYER_KINDS:
            raise QuantumDslError(f"{where}: kind {spec.get('kind')!r} not in {sorted(_LAYER_KINDS)}")
        entry = {"kind": spec["kind"]}
        if "gds" in spec:
            g = spec["gds"]
            if isinstance(g, dict):
                g = [g.get("layer"), g.get("datatype", 0)]
            if not (isinstance(g, list) and 1 <= len(g) <= 2 and all(isinstance(v, int) for v in g)):
                raise QuantumDslError(f"{where}: gds must be [layer, datatype] ints")
            entry["gds"] = (g[0], g[1] if len(g) == 2 else 0)
        out[lid] = entry
    return out


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
    geo, layout = doc.get("geo"), doc.get("layout")
    if (geo is None) == (layout is None):
        raise QuantumDslError(f"load_meta: {path}: give exactly one of 'geo' / 'layout'")
    src = geo if geo is not None else layout
    if not isinstance(src, str) or not src:
        raise QuantumDslError(f"load_meta: {path}: 'geo'/'layout' must name a file")
    layers = _layers(doc.get("layers") or {}, path)
    if layout is not None and not layers:
        raise QuantumDslError(f"load_meta: {path}: 'layout' requires a 'layers' table")

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
        geo_path=path.parent / geo if geo is not None else None,
        layout_path=path.parent / layout if layout is not None else None,
        layers=layers,
        materials=doc.get("materials") or {},
        airbox=doc.get("airbox") or {},
        mesh=doc.get("mesh") or {},
        solver=doc.get("solver") or {},
        gds=doc.get("gds") or {},
        circuit_model=circuit_model,
        extract=doc.get("extract") or {},
        subsystems=doc.get("subsystems") or [],
    )
