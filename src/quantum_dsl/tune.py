# -*- coding: utf-8 -*-
"""FEM 在环综合 (契约「tune」): meta ``tune:`` 声明「旋钮 → targets 核对项」, ``tune(meta, out)`` 迭代到全部命中,
产出一份**普通的** ``*.layout.yaml`` + ``*.meta.yaml`` (配置即综合输出, 可独立 ``build`` 复核)。

算法 = QDesignOptimizer 的 ANMod (arXiv:2508.18027 Eq. 2/3/5) 的对角特例 + 对数割线:

* 方阵: 每个旋钮对准恰好一条核对项 (加载时查)。每轮**一次** FEM (整片 ``build(solve=True)``)。
* **结旋钮** (``<步骤>.E_J`` / ``.L_J``) 不动几何 → 在本轮缓存的 C 矩阵上对电路模型做对数二分求根
  (默认范围 ×1/10 … ×10 或 ``bounds``), 不花 FEM。
* **几何旋钮** (模板参数 / ``<步骤>.length.f_r``) 按声明的比例律 ``target ∝ param^law`` 一步:
  ``x ← x·(y*/y)^(damping/p)``; 有上一轮时 p 换成观测指数 ``ln(y/y₀)/ln(x/x₀)`` (与声明同号才用) —— 律只需趋势对。
* 停: 全部旋钮的核对项 pass (tol 就是判据), 或 ``max_iter`` 用完 (warn)。

产物: ``out/iter_<k>/`` = 每轮的完整配置 + build 产物 (各带 manifest); ``out/<layout>`` + ``out/<meta>`` = 终版配置
(相对路径改写到 out); ``out/results.yaml`` = 终版 (几何 = 最后一轮, 结参数 = 求根后) 在最后一轮 C 上的结果 + validation;
``out/tune.yaml`` = 逐轮旋钮值与核对项。
"""

from __future__ import annotations

import copy
import math
import os
import re
import warnings
from pathlib import Path

import yaml

from .build import _actual, _results_doc, _tables, _validation, build
from .errors import QuantumDslError
from .meta import JUNCTION_KNOBS, Meta, load_meta
from .units import parse_quantity

__all__ = ["tune"]

_UNIT = re.compile(r"[A-Za-zµΩ]+$")


def _slot(step: dict, path: str, defaults: dict, where: str):
    """旋钮在配置 dict 里的落点 → (容器, 键)。单段非结键 = 模板参数 (缺省取模板默认, 写进 step.params);
    多段 = 沿步骤 dict 下钻 (``length.f_r``)。"""
    parts = path.split(".")
    if len(parts) == 1 and parts[0] not in JUNCTION_KNOBS:
        if parts[0] not in defaults:
            raise QuantumDslError(f"{where}: {parts[0]!r} is not a template param (have: {sorted(defaults)})")
        params = step.setdefault("params", {})
        params.setdefault(parts[0], defaults[parts[0]])
        return params, parts[0]
    d = step
    for part in parts[:-1]:
        d = d.get(part) if isinstance(d, dict) else None
    if not isinstance(d, dict) or parts[-1] not in d:
        raise QuantumDslError(f"{where}: step has no {path!r}")
    return d, parts[-1]


def _get(slot) -> float:
    v = slot[0][slot[1]]
    return parse_quantity(v) if isinstance(v, str) else float(v)


def _put(slot, value: float) -> None:
    box, key = slot
    old = box[key]
    if isinstance(old, str):                       # 带单位的量: 保留原单位写回
        unit = _UNIT.search(old.strip()).group(0)
        box[key] = f"{value / parse_quantity('1' + unit):.9g}{unit}"
    else:
        box[key] = round(value, 4)                 # µm 几何, 0.1 nm 分辨


def _write(raw_meta, raw_lay, src_dir: Path, names, d: Path, note: str) -> Path:
    """把 (已改旋钮的) 配置写进目录 d: 版图里的相对路径 (templates / geo 步骤) 改写成相对 d。"""
    d.mkdir(parents=True, exist_ok=True)
    rel = lambda p: os.path.relpath((src_dir / p).resolve(), d.resolve())
    lay = copy.deepcopy(raw_lay)
    lay["templates"] = [rel(t) for t in lay.get("templates") or ["."]]
    for st in lay["steps"]:
        if isinstance(st, dict) and "geo" in st:
            st["geo"] = rel(st["geo"])
    meta = {**copy.deepcopy(raw_meta), "layout": names[0]}
    for name, doc in zip(names, (lay, meta)):
        (d / name).write_text(f"# {note}\n" + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True,
                                                            default_flow_style=None), encoding="utf-8")
    return d / names[1]


def _root(f, x0, bounds, where) -> float:
    """f 单调时的对数二分: f(x) = 0, x ∈ bounds (默认 x0 的 ×1/10 … ×10)。"""
    lo, hi = bounds or (x0 / 10, x0 * 10)
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        raise QuantumDslError(f"{where}: target not reachable for this knob in [{lo:.4g}, {hi:.4g}] "
                              f"(residuals {flo:+.3g} / {fhi:+.3g}) — widen bounds")
    for _ in range(80):
        mid = math.sqrt(lo * hi)
        fm = f(mid)
        if fm == 0 or hi / lo - 1 < 1e-12:
            return mid
        lo, hi, flo = (lo, mid, flo) if flo * fm < 0 else (mid, hi, fm)
    return math.sqrt(lo * hi)


def tune(meta, out_dir) -> dict:
    """meta (须有 ``layout:`` + ``targets:`` + ``tune:``) → 迭代到旋钮核对项全部命中。
    返回 ``{converged, iterations, meta, layout, results, tune, history}`` (路径指 out 下的终版)。"""
    m = meta if isinstance(meta, Meta) else load_meta(meta)
    if not m.tune:
        raise QuantumDslError(f"tune: {m.path} has no tune: block")
    if m.layout_path is None:
        raise QuantumDslError("tune: knobs live in layout steps — needs a layout: meta")
    from .layout import _load_template

    out = Path(out_dir)
    raw_meta = yaml.safe_load(m.path.read_text(encoding="utf-8"))
    raw_lay = yaml.safe_load(m.layout_path.read_text(encoding="utf-8"))
    src_dir = m.layout_path.parent
    tdirs = tuple((src_dir / t).resolve() for t in raw_lay.get("templates") or ["."])
    names = (m.layout_path.name, m.path.name)
    steps = {st["name"]: st for st in raw_lay["steps"] if isinstance(st, dict) and "name" in st}
    meta_q = {q.get("name"): q for q in (raw_meta.get("circuit_model") or {}).get("qubits") or []}

    knobs = []
    for k in m.tune["knobs"]:
        where = f"tune: knob {k['param']!r}"
        st = steps.get(k["step"])
        if k["path"] in JUNCTION_KNOBS and (st is None or k["path"] not in st):
            st = meta_q.get(k["step"])                  # 结写在 meta circuit_model.qubits 里
            defaults = {}
        else:
            tname = st and (st.get("template") or st.get("route"))
            defaults = (_load_template(tname, tdirs).doc.get("params") or {}) if tname else {}
        if st is None:
            raise QuantumDslError(f"{where}: no layout step / meta qubit named {k['step']!r}")
        knobs.append({**k, "slot": _slot(st, k["path"], defaults, where)})
    checks = m.targets["checks"]
    max_iter, damping = m.tune["max_iter"], m.tune["damping"]

    history, prev, converged = [], {}, False
    for it in range(max_iter):
        d = out / f"iter_{it}"
        with warnings.catch_warnings():         # 这轮的 validation 用的是求根前的结参数, 下面重算
            warnings.filterwarnings("ignore", message="targets:")
            r = build(_write(raw_meta, raw_lay, src_dir, names, d, f"quantum_dsl.tune iteration {it}"),
                      d, solve=True)
        cap, cm = r["capacitance"], copy.deepcopy(r["circuit_model"])
        subsystems = yaml.safe_load(Path(r["results"]).read_text(encoding="utf-8")).get("subsystems") or []

        for k in (k for k in knobs if k["path"] in JUNCTION_KNOBS):       # 结旋钮: 缓存 C 上求根, 不跑 FEM
            q = next(q for q in cm["qubits"] if q["name"] == k["step"])
            want = checks[k["check"]]["expected"]

            def resid(x, q=q, k=k, want=want):
                q[k["path"]] = x
                return _actual(_tables(_results_doc(cap, [], cm)), checks[k["check"]]) - want
            x = _root(resid, _get(k["slot"]), k["bounds"], f"tune: knob {k['param']!r}")
            q[k["path"]] = x
            _put(k["slot"], x)

        doc = _results_doc(cap, subsystems, cm)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")                               # 中间轮的未命中不刷屏
            doc["validation"] = _validation(doc, m.targets)
        rows = doc["validation"]["checks"]
        history.append({"iter": it, "knobs": {k["param"]: _get(k["slot"]) for k in knobs},
                        "checks": {k["target"]: {f: rows[k["check"]][f] for f in ("actual", "deviation", "pass")}
                                   for k in knobs}, "dir": str(d)})
        converged = all(rows[k["check"]]["pass"] for k in knobs)
        if converged or it == max_iter - 1:
            break
        for k in (k for k in knobs if k["path"] not in JUNCTION_KNOBS):   # 几何旋钮: 比例律 / 对数割线
            x, y, ys = _get(k["slot"]), rows[k["check"]]["actual"], rows[k["check"]]["expected"]
            if not y * ys > 0:
                raise QuantumDslError(f"tune: {k['target']} = {y:.4g} has the wrong sign for target "
                                      f"{ys:.4g} — a power law cannot cross zero")
            p = k["law"]
            x0, y0 = prev.get(k["param"], (x, y))
            if x != x0 and y != y0 and math.log(y / y0) / math.log(x / x0) * p > 0:
                p = math.log(y / y0) / math.log(x / x0)
            prev[k["param"]] = (x, y)
            xn = x * (ys / y) ** (damping / p)
            lo, hi = k["bounds"] or (0.0, math.inf)
            _put(k["slot"], min(max(xn, lo), hi))

    if not converged:
        warnings.warn(f"tune: not converged after {max_iter} iteration(s) — "
                      + "; ".join(f"{t} {c['deviation']:+.2%}" for t, c in history[-1]["checks"].items()
                                  if not c["pass"]), stacklevel=2)
    final_meta = _write(raw_meta, raw_lay, src_dir, names, out,
                        f"quantum_dsl.tune: synthesized from {m.path.name} "
                        f"({'converged' if converged else 'NOT converged'}, {len(history)} FEM run(s))")
    res_path = out / "results.yaml"
    res_path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    log = {"source": str(m.path), "converged": converged, "iterations": len(history),
           "results_from": history[-1]["dir"], "history": history}
    tune_path = out / "tune.yaml"
    tune_path.write_text(yaml.safe_dump(log, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return {"converged": converged, "iterations": len(history), "meta": final_meta,
            "layout": out / names[0], "results": res_path, "tune": tune_path, "history": history}
