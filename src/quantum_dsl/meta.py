# -*- coding: utf-8 -*-
"""``*.meta.yaml`` sidecar 加载 (契约「meta 加载」; 词汇见 SPEC「Layer-1 词汇」)。

扁平词汇, schema ``quantum-dsl/meta/1``。未知顶层键一律 raise (typo 不静默)。
``circuit_model.qubits`` 里的结参数在加载时就解析成数:
``L_J`` → 亨利 (SI); ``E_J``/``E_J1``/``E_J2`` 按论文惯例写成频率 (如
``12.2GHz``) → 解析成 **Hz (E_J/h)**, 换算焦耳 (×h) 是 build 接线时的事。
``targets:`` (issue #23) 在加载时展平成逐项核对条目 (键即 results.yaml 的字段名, 值是裸数),
名字能否对上 qubit 由 build 在网格化之前查。
``circuit_model`` 只收 qubits / resonators / ports / floating (无结导体的三种显式处置, docs/physics.md §8.1);
``tune:`` (FEM 在环综合, ``quantum_dsl.tune``) 在加载时校验成方阵: 每个旋钮对准恰好一条 targets 核对项。
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

from .circuit_model import CouplingResult, QubitResult, ReadoutResult, ResonatorResult
from .errors import QuantumDslError
from .units import parse_quantity

__all__ = ["Meta", "load_meta"]

_SCHEMA = "quantum-dsl/meta/1"
_TOP_KEYS = frozenset({"schema", "geo", "layout", "layers", "materials", "airbox", "mesh",
                       "solver", "gds", "circuit_model", "extract", "subsystems", "targets", "tune"})
_CM_KEYS = frozenset({"qubits", "resonators", "ports", "floating"})
_TUNE_KEYS = frozenset({"knobs", "max_iter", "damping"})
_KNOB_KEYS = frozenset({"param", "target", "law", "bounds"})
JUNCTION_KNOBS = ("E_J", "L_J")      # 结旋钮: 在缓存的 C 矩阵上闭式求根, 不跑 FEM
_LAYER_KEYS = frozenset({"kind", "gds"})
_LAYER_KINDS = frozenset({"conductor", "junction", "drawing"})
# 可核对的量 = results.yaml hamiltonian 段里的数值字段 (单位在字段名后缀里)
_QUBIT_FIELDS = frozenset(f.name for f in fields(QubitResult)) - {"name", "islands"}
_COUPLING_FIELDS = frozenset(f.name for f in fields(CouplingResult)) - {"qubit_a", "qubit_b"}
_RESONATOR_FIELDS = frozenset(f.name for f in fields(ResonatorResult)) - {"name", "net"}
_READOUT_FIELDS = frozenset(f.name for f in fields(ReadoutResult)) - {"qubit", "resonator"}


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
    targets: dict = field(default_factory=dict)  # {source, checks: [{qubit|pair|resonator|readout, field, expected, tol}]}
    tune: dict = field(default_factory=dict)     # {knobs: [{param, step, path, target, check, law, bounds}], max_iter, damping}


def _targets(tbl, path) -> dict:
    """``targets: {source, qubits: {Q: {C_sigma_fF: 99.3, tol: 8%}}, couplings: [{pair: [a, b], beta: .., tol: ..}]}``
    → ``{source, checks: [...]}``, 每个 (对象, 字段) 一条。tol 只收 ``"8%"`` 写法 (裸数 8 是 8% 还是 800% 说不清)。"""
    where = f"load_meta: {path}: targets"
    if not isinstance(tbl, dict) or set(tbl) - {"source", "qubits", "couplings", "resonators", "readout"}:
        raise QuantumDslError(f"{where} must be a mapping with keys source / qubits / couplings / "
                              f"resonators / readout, got {tbl!r}")

    def entry(spec, allowed, head, what):   # head = 定位键 ({"qubit": ..} / {"pair": ..})
        if not isinstance(spec, dict):
            raise QuantumDslError(f"{where}: {what} must be a mapping, got {spec!r}")
        unknown = sorted(set(spec) - allowed - {"tol"} - ({"pair"} if "pair" in head or "readout" in head else set()))
        if unknown:
            raise QuantumDslError(f"{where}: {what}: unknown key(s) {unknown} (known: {sorted(allowed)} + tol)")
        tol = spec.get("tol")
        try:
            t = float(tol[:-1]) / 100 if isinstance(tol, str) and tol.endswith("%") else math.nan
        except ValueError:
            t = math.nan
        if not 0 < t < math.inf:
            raise QuantumDslError(f"{where}: {what}: tol must be a positive percentage like '8%', got {tol!r}")
        quantities = sorted(set(spec) & allowed)
        if not quantities:
            raise QuantumDslError(f"{where}: {what}: no quantity to check (known: {sorted(allowed)})")
        out = []
        for q in quantities:
            v = spec[q]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v == 0:
                raise QuantumDslError(f"{where}: {what}.{q} must be a finite non-zero number "
                                      f"(unit is in the key name), got {v!r}")
            out.append({**copy.deepcopy(head), "field": q, "expected": float(v), "tol": t})  # 共享 list 会让 yaml 出锚点
        return out

    checks = []
    for sec, fields_, loc in (("qubits", _QUBIT_FIELDS, "qubit"), ("resonators", _RESONATOR_FIELDS, "resonator")):
        named = tbl.get(sec) or {}
        if not isinstance(named, dict):
            raise QuantumDslError(f"{where}.{sec} must map {loc} name → quantities")
        for name, spec in named.items():
            checks += entry(spec, fields_, {loc: str(name)}, f"{sec}[{name!r}]")
    for sec, fields_, loc, what in (("couplings", _COUPLING_FIELDS, "pair", "qubit_a, qubit_b"),
                                    ("readout", _READOUT_FIELDS, "readout", "qubit, resonator")):
        pairs = tbl.get(sec) or []
        if not isinstance(pairs, list):
            raise QuantumDslError(f"{where}.{sec} must be a list of {{pair: [{what}], ...}}")
        for i, spec in enumerate(pairs):
            pair = spec.get("pair") if isinstance(spec, dict) else None
            if not (isinstance(pair, list) and len(pair) == 2 and all(isinstance(n, str) for n in pair)
                    and pair[0] != pair[1]):
                raise QuantumDslError(f"{where}: {sec}[{i}] needs pair: [{what}], got {spec!r}")
            checks += entry(spec, fields_, {loc: list(pair)}, f"{sec}[{i}]")
    if not checks:
        raise QuantumDslError(f"{where}: declares no qubits / couplings / resonators / readout to check")
    return {"source": tbl.get("source"), "checks": checks}


def target_ref(check: dict) -> str:
    """核对项的引用名: ``Q1.f01_GHz`` / ``R1.kappa_MHz`` / ``Q1~R1.chi_MHz`` (tune 旋钮按它对准 targets)。"""
    loc = check.get("qubit") or check.get("resonator") or "~".join(check.get("pair") or check["readout"])
    return f"{loc}.{check['field']}"


def _tune(tbl, targets, path) -> dict:
    """``tune: {knobs: [{param: Q1.arm_L, target: Q1.anharmonicity_exact_MHz, law: -1, bounds: [150, 450]}],
    max_iter: 8, damping: 1}`` → 校验后的旋钮表。方阵 (ANMod): 旋钮 param 唯一、target 唯一且必须是 targets 里的
    一条核对项; 几何旋钮必须给比例律指数 ``law`` (target ∝ param^law, 只需趋势对), 结旋钮 (E_J / L_J) 不收 law。"""
    where = f"load_meta: {path}: tune"
    if not isinstance(tbl, dict) or set(tbl) - _TUNE_KEYS:
        raise QuantumDslError(f"{where} must be a mapping with keys {sorted(_TUNE_KEYS)}, got {tbl!r}")
    if not targets:
        raise QuantumDslError(f"{where}: needs a targets: block — knobs aim at its checks")
    refs: dict[str, int] = {}
    for i, c in enumerate(targets["checks"]):
        refs[target_ref(c)] = i
        if "pair" in c or "readout" in c:                       # 对的两种写法都认
            a, b = c.get("pair") or c["readout"]
            refs[f"{b}~{a}.{c['field']}"] = i
    knobs = tbl.get("knobs")
    if not isinstance(knobs, list) or not knobs:
        raise QuantumDslError(f"{where}.knobs must be a non-empty list")
    out, seen_p, seen_t = [], set(), set()
    for i, k in enumerate(knobs):
        w = f"{where}.knobs[{i}]"
        if not isinstance(k, dict) or set(k) - _KNOB_KEYS:
            raise QuantumDslError(f"{w} must be a mapping with keys {sorted(_KNOB_KEYS)}, got {k!r}")
        param, target = k.get("param"), k.get("target")
        if not (isinstance(param, str) and "." in param and all(param.split("."))):
            raise QuantumDslError(f"{w}: param must be '<step>.<template param>' / '<step>.E_J' / "
                                  f"'<step>.length.f_r', got {param!r}")
        if target not in refs:
            raise QuantumDslError(f"{w}: target {target!r} is not a targets check (have: {sorted(refs)})")
        if param in seen_p or refs[target] in seen_t:
            raise QuantumDslError(f"{w}: param / target used twice — tune needs one knob per target "
                                  f"(square system)")
        seen_p.add(param)
        seen_t.add(refs[target])
        step, key = param.split(".", 1)
        law = k.get("law")
        if key in JUNCTION_KNOBS:
            if law is not None:
                raise QuantumDslError(f"{w}: junction knobs are root-solved on the cached C matrix; "
                                      f"law is not used — drop it")
        elif isinstance(law, bool) or not isinstance(law, (int, float)) or not math.isfinite(law) or law == 0:
            raise QuantumDslError(f"{w}: geometric knob needs law: <non-zero exponent p> "
                                  f"(target ∝ param^p, e.g. -1 for E_C ∝ 1/arm_L), got {law!r}")
        bounds = k.get("bounds")
        if bounds is not None and not (isinstance(bounds, list) and len(bounds) == 2
                                       and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                               for v in bounds) and 0 < bounds[0] < bounds[1]):
            raise QuantumDslError(f"{w}: bounds must be [lo, hi] with 0 < lo < hi (SI for E_J/L_J/f_r, "
                                  f"um for geometry), got {bounds!r}")
        out.append({"param": param, "step": step, "path": key, "target": target, "check": refs[target],
                    "law": None if law is None else float(law), "bounds": bounds})
    max_iter, damping = tbl.get("max_iter", 8), tbl.get("damping", 1.0)
    if isinstance(max_iter, bool) or not isinstance(max_iter, int) or max_iter < 1:
        raise QuantumDslError(f"{where}.max_iter must be a positive int, got {max_iter!r}")
    if isinstance(damping, bool) or not isinstance(damping, (int, float)) or not 0 < damping <= 1:
        raise QuantumDslError(f"{where}.damping must be in (0, 1], got {damping!r}")
    return {"knobs": out, "max_iter": max_iter, "damping": float(damping)}


def _circuit_model(tbl, path) -> dict:
    """circuit_model 键白名单 + 带量纲量解析成 SI (E_J 系 → Hz, L_J → H, f_r → Hz, Z0 / R → Ω)。
    条目内的键与取值由 solve_circuit_model 查 (那里有完整报错)。"""
    cm = copy.deepcopy(tbl or {})
    if not isinstance(cm, dict):
        raise QuantumDslError(f"load_meta: {path}: circuit_model must be a mapping")
    unknown = sorted(set(cm) - _CM_KEYS)
    if unknown:
        raise QuantumDslError(f"load_meta: {path}: circuit_model: unknown key(s) {unknown} "
                              f"(known: {sorted(_CM_KEYS)})")
    for sec in ("qubits", "resonators", "ports"):
        for q in cm.get(sec) or []:
            if not isinstance(q, dict):
                raise QuantumDslError(f"load_meta: {path}: circuit_model.{sec} entries must be "
                                      f"mappings, got {q!r}")
            for key in ("L_J", "E_J", "f_r", "Z0", "R"):
                if key in q:
                    q[key] = parse_quantity(q[key])
            for key in ("E_J1", "E_J2"):
                if key in q.get("squid", {}):
                    q["squid"][key] = parse_quantity(q["squid"][key])
    fl = cm.get("floating")
    if fl is not None and not (isinstance(fl, list) and all(isinstance(v, str) for v in fl)):
        raise QuantumDslError(f"load_meta: {path}: circuit_model.floating must be a list of net names")
    return cm


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

    circuit_model = _circuit_model(doc.get("circuit_model"), path)
    targets = _targets(doc["targets"], path) if "targets" in doc else {}

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
        targets=targets,
        tune=_tune(doc["tune"], targets, path) if "tune" in doc else {},
    )
