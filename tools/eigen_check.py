# -*- coding: utf-8 -*-
"""静电 LOM vs Palace 本征模: 同一网格上的交叉验证 (2026-10-29 冲刺, 不进 src/)。

做法 (同一张网格跑两次 Palace):
1. 几何源里 role = jj 的面 (结) 改名成 ``metal::<导体层>::port_<结名>::jj`` 留在网格里 —— 产品
   管线 (build_mesh) 会删掉它; 这里用 build_mesh 原样出网格, 只是结面多了一个 imprint 进界面的面组。
2. **静电**: 产品的 ``palace_config`` 只给真导体挂 Terminal (结面无 BC = 普通内界面) → C →
   产品的 ``solve_circuit_model`` (同 build 的 qubits / resonators / ports 组装) → LOM。
3. **本征模**: 导体 (含 ground 片) = PEC, 结面 = LumpedPort(L = L_J, Direction 沿结长),
   外边界按静电口径对齐 —— 静电 ``ground`` (Dirichlet φ = 0) ↔ PEC 盒; 静电 ``open`` (ZeroCharge,
   ∂φ/∂n = 0) ↔ 不挂 BC (Palace 自然边界 = PMC, n·E = 0); ``--outer absorbing`` = Palace transmon 例口径。
   ``Model.L0 = 1e-6`` (与产品同一个换算点), Order 2。
4. 读 ``eig.csv`` + ``port-EPR.csv``: 每个结取 EPR 最大的模 = 该比特模; 对齐口径比:
   f_eig (线性 LC 频率) ↔ LOM 线性 ``f_p = √(8 E_C E_J)/h = 1/(2π√(L_J C_Σ))``;
   EPR 一阶 (Minev et al., npj QI 7, 131 (2021)) ``α_m = −Σ_j p_mj² · h f_m² / (8 E_Jj)``,
   ``f01 ≈ f_m − |α_m|`` ↔ LOM 渐近 ``f01 = f_p − E_C``, ``α = −E_C`` (同为一阶微扰)。

用法::

    PYTHONPATH=src python tools/eigen_check.py examples/two_pads_eigen.meta.yaml build/sprint/eigen/tp_40_4
    PYTHONPATH=src python tools/eigen_check.py examples/xmon_pair.meta.yaml build/sprint/eigen/xp --np 6

``--scale s`` = mesh max/min 同乘 s; 结果写 ``<out>/summary.yaml``。⚠ WSL: HWLOC_COMPONENTS=-gl (这里自动带)。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

import yaml

from quantum_dsl.build import _junctions_from_meta, _merge, _palace_bin, _resonators_from
from quantum_dsl.circuit_model import FLUX_QUANTUM_REDUCED, H_PLANCK, solve_circuit_model
from quantum_dsl.errors import QuantumDslError
from quantum_dsl.geo import parse_physical_name
from quantum_dsl.mesh import build_mesh
from quantum_dsl.meta import load_meta
from quantum_dsl.palace import palace_config, parse_capacitance

PORT = "port_"
OUTER = ("pec", "pmc", "absorbing")


# ---------------------------------------------------------------- 几何 / 网格

def port_source(m):
    """meta → (几何源 callable, circuit_model): 源与产品相同, 只把 jj 面改名成 metal 端口面。"""
    cm = dict(m.circuit_model)
    if m.layout_path is not None:
        from quantum_dsl.layout import compile_layout
        lay = compile_layout(m)
        base = lay
        cm["qubits"] = _merge(list(cm.get("qubits") or []), lay.qubits, "qubit")
        cm["resonators"] = _merge(list(cm.get("resonators") or []),
                                  _resonators_from(lay.subsystems), "resonator")
    else:
        base = lambda g: g.merge(str(m.geo_path))
    cond = next((k for k, v in (m.layers or {}).items() if v["kind"] == "conductor"), None)

    def src(gmsh):
        base(gmsh)
        gmsh.model.occ.synchronize()
        # setPhysicalName 不覆盖旧名 (实测), 单组拆挂会让 gmsh free() 崩 —— 照 layout.py:_finish
        # 的做法整体拆掉、删全部名字、再按 (改过的) 名字重挂。
        groups = []
        for dim, tag in gmsh.model.getPhysicalGroups(2):
            name = gmsh.model.getPhysicalName(dim, tag)
            groups.append((name, [int(t) for t in gmsh.model.getEntitiesForPhysicalGroup(dim, tag)]))
        gmsh.model.removePhysicalGroups()
        for name, _ in groups:
            gmsh.model.removePhysicalName(name)
        for name, ents in groups:
            p = parse_physical_name(name)
            if p.role == "jj":
                name = f"metal::{cond or p.layer}::{PORT}{p.component}::{p.primitive}"
            gmsh.model.addPhysicalGroup(2, ents, name=name)
    src.path = m.layout_path or m.geo_path
    return src, cm


def port_direction(bbox) -> str:
    """结面 bbox (xmin, ymin, xmax, ymax) → LumpedPort Direction (沿结长 = bbox 长边)。
    ⚠ 启发式: 只对"长条结" (长 ≥ 2 × 宽, 真实结与 xmon 模板都是) 成立; 比宽还短的端口 (如
    two_pads_eigen_leads 的 4 × 10 µm) 会被判成错的方向 —— Palace 照样算, 静默出错 (实测 LC 模消失),
    这种几何必须 ``--direction`` 显式给。"""
    dx, dy = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if not (dx > 2 * dy or dy > 2 * dx):
        raise QuantumDslError(f"port_direction: junction bbox {dx:g} x {dy:g} um is not "
                              f"axis-aligned/elongated — give Direction by hand")
    return "+X" if dx > dy else "+Y"


def l_j_henry(q: dict) -> float:
    """circuit_model qubit 条目 → L_J (H)。load_meta 已把 E_J 解析成 Hz (E_J/h)。"""
    if "L_J" in q:
        return float(q["L_J"])
    if "E_J" in q:
        return FLUX_QUANTUM_REDUCED ** 2 / (q["E_J"] * H_PLANCK)
    raise QuantumDslError(f"eigen_check: qubit {q.get('name')!r}: SQUID not supported (give L_J/E_J)")


# ---------------------------------------------------------------- Palace config

def default_outer(m) -> str:
    """静电外边界 → 本征模外边界 (同口径): ground ↔ PEC, open ↔ 自然边界 (PMC)。"""
    return "pec" if (m.solver or {}).get("outer_boundary", "ground") == "ground" else "pmc"


def eigen_config(mesh, m, ports, out, *, outer, n_modes, target_ghz, order=2,
                 output="postpro_eig", direction=None) -> dict:
    """本征模 config。``ports`` = [(网格 label, L_J 亨利)], Index = 列表顺序 (1 起)。"""
    if outer not in OUTER:
        raise QuantumDslError(f"eigen_config: outer {outer!r} not in {OUTER}")
    pec = [mesh.conductor_groups[c] for c in mesh.labels if not c.startswith(PORT)]
    if "ground" in mesh.boundary_groups:
        pec.append(mesh.boundary_groups["ground"])
    bnd: dict = {}
    if outer == "pec":
        pec.append(mesh.boundary_groups["outer"])
    elif outer == "absorbing":
        bnd["Absorbing"] = {"Attributes": [mesh.boundary_groups["outer"]], "Order": 1}
    bnd["PEC"] = {"Attributes": pec}
    bnd["LumpedPort"] = [
        {"Index": i + 1, "L": float(l_h), "Attributes": [mesh.conductor_groups[lab]],
         "Direction": direction or port_direction(mesh.conductor_bbox_um[lab])}
        for i, (lab, l_h) in enumerate(ports)]
    eps = float(m.materials["substrate"]["eps_r"])
    cfg = {
        "Problem": {"Type": "Eigenmode", "Verbose": 2, "Output": output},
        "Model": {"L0": 1e-6, "Mesh": mesh.path.name},
        "Domains": {"Materials": [
            {"Attributes": [mesh.domain_groups["substrate"]], "Permeability": 1.0,
             "Permittivity": eps, "LossTan": 0.0},
            {"Attributes": [mesh.domain_groups["vacuum"]], "Permeability": 1.0,
             "Permittivity": 1.0}]},
        "Boundaries": bnd,
        "Solver": {"Order": order, "Device": "CPU",
                   "Eigenmode": {"N": int(n_modes), "Target": float(target_ghz), "Save": 0}},
    }
    out = Path(out)
    out.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def run_palace(cfg: Path, n_rank: int, reuse: bool = False) -> dict:
    """跑 Palace (cwd = config 目录), stdout 落 ``<cfg>.log``。``reuse`` 且 log 已在 = 不重跑, 只读旧 log。"""
    log = cfg.with_suffix(".log")
    if not (reuse and log.is_file()):
        env = dict(os.environ, HWLOC_COMPONENTS="-gl")
        r = subprocess.run([_palace_bin(), "-np", str(n_rank), cfg.name], cwd=cfg.parent, env=env,
                           capture_output=True, text=True)
        log.write_text(r.stdout + "\n--- stderr ---\n" + r.stderr, encoding="utf-8")
        if r.returncode != 0:
            raise QuantumDslError(f"palace rc={r.returncode} on {cfg}, see {log}\n{r.stdout[-1500:]}")
    txt = log.read_text(encoding="utf-8")
    peak = re.findall(r"peak per-node memory usage is:.*Total ([\d.]+\w)", txt)
    ndof = re.findall(r"Level \d+ \(p = \d+\): (\d+) unknowns", txt)
    total = re.findall(r"^Total\s+[\d.]+\s+([\d.]+)", txt, re.M)
    return {"palace_s": float(total[-1]) if total else None, "np": n_rank,
            "peak_mem": peak[-1] if peak else None, "ndof": int(ndof[-1]) if ndof else None}


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    head = [h.strip() for h in rows[0]]
    return [{h: float(v) for h, v in zip(head, r)} for r in rows[1:] if r]


# ---------------------------------------------------------------- 闭式

def epr_alpha_hz(f_hz: float, p: list[float], e_j_hz: list[float]) -> float:
    """EPR 一阶自 Kerr (= α, Hz): α = −Σ_j p_j² · h f² / (8 E_Jj)  (E_J 以 Hz 计, 即 E_J/h)。
    单模单结 p = 1、f = √(8 E_C E_J)/h 时 = −E_C/h —— 与 LOM 的 α = −E_C 同一阶。"""
    return -sum(pj * pj * f_hz * f_hz / (8.0 * ej) for pj, ej in zip(p, e_j_hz))


def epr_levels_hz(f_hz: float, p: list[float], e_j_hz: list[float], n_fock: int = 40,
                  cos_order: int = 10):
    """单模数值对角化 (pyEPR 口径, Minev 2021 Eq. 3–4): Fock 基
    ``H/h = f a†a − Σ_j E_Jj (cos φ_j − 1 + φ_j²/2)``, ``φ_j = φ_zpf,j (a + a†)``,
    ``φ_zpf,j² = |p_j| · f / (2 E_Jj)`` → (f01, f12) Hz。
    余弦按 pyEPR 惯例做 Taylor 截断, 到 φ^cos_order (须 cos_order/2 奇: 6, 10, 14 才有下界;
    不截断的非紧致 φ 会让相邻 2π 势阱的简并态把 f01 拉到 0 —— 实测)。矩阵幂在 n_fock + cos_order
    维里算再截 (边缘元素精确)。p = 1 时对电荷基精确解 (transmon_levels_hz): E_J/E_C = 60 → f01 1e-7、α 1e-4;
    E_J/E_C = 30 → α 2% (φ 非紧致的上限, 小 E_J/E_C 别用)。"""
    import numpy as np
    if cos_order % 4 != 2:
        raise QuantumDslError(f"epr_levels_hz: cos_order {cos_order} gives an unbounded potential")
    n = n_fock + cos_order
    x = np.diag(np.sqrt(np.arange(1, n)), 1)
    x = x + x.T
    xk = {k: np.linalg.matrix_power(x, k)[:n_fock, :n_fock] for k in range(4, cos_order + 1, 2)}
    h = f_hz * np.diag(np.arange(n_fock, dtype=float))
    for pj, ej in zip(p, e_j_hz):
        z2 = abs(pj) * f_hz / (2.0 * ej)
        # cos u − 1 + u²/2 = Σ_{k≥4, 偶} (−1)^{k/2} u^k / k!
        h -= ej * sum((-1) ** (k // 2) * z2 ** (k // 2) * xk[k] / math.factorial(k) for k in xk)
    e = np.linalg.eigvalsh(h)
    return float(e[1] - e[0]), float(e[2] - e[1])


def lom_linear_ghz(e_c_ghz: float, e_j_ghz: float) -> float:
    """LOM 线性等离子频率 f_p = √(8 E_C E_J) (GHz) = 1/(2π√(L_J C_Σ)) —— 与本征模的线性 LC 同口径。"""
    return math.sqrt(8.0 * e_c_ghz * e_j_ghz)


# ---------------------------------------------------------------- 主流程

def run(meta_path, out, *, scale=1.0, outer=None, n_rank=4, n_modes=None, order=2,
        reuse=False, direction=None) -> dict:
    m = load_meta(meta_path)
    if scale != 1.0:
        m = replace(m, mesh={**m.mesh, **{k: scale * float(m.mesh[k])
                                          for k in ("max_size_um", "min_size_um")}})
    outer = outer or default_outer(m)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    src, cm = port_source(m)
    t0 = time.time()
    mesh = build_mesh(src, m, out / "eigen.msh")
    t_mesh = time.time() - t0
    port_labels = [c for c in mesh.labels if c.startswith(PORT)]
    qubits = {q["name"]: q for q in cm.get("qubits") or []}
    missing = [lab for lab in port_labels if lab[len(PORT):] not in qubits]
    if missing or not port_labels:
        raise QuantumDslError(f"eigen_check: junction faces {missing or 'none'} have no "
                              f"circuit_model qubit of the same name ({sorted(qubits)})")

    # --- 静电 (同一网格, 结面不挂 BC) → LOM
    es_mesh = replace(mesh, labels=tuple(c for c in mesh.labels if not c.startswith(PORT)))
    es_cfg = out / "es.json"
    palace_config(es_mesh, m, es_cfg, output="postpro_es")
    es_run = run_palace(es_cfg, n_rank, reuse)
    cap = parse_capacitance(out / "postpro_es", es_mesh.labels)
    model = solve_circuit_model(cap.labels, cap.maxwell_fF, _junctions_from_meta(cm),
                                resonators=cm.get("resonators") or (),
                                ports=cm.get("ports") or (), floating=cm.get("floating") or ())
    lom = {q.name: q for q in model.qubits}

    # --- 本征模
    ports = [(lab, l_j_henry(qubits[lab[len(PORT):]])) for lab in port_labels]
    f_lin = [lom_linear_ghz(lom[lab[len(PORT):]].E_C_GHz, lom[lab[len(PORT):]].E_J_GHz)
             for lab in port_labels]
    n_modes = n_modes or len(ports) + len(model.resonators) + 1
    eig_cfg = out / "eig.json"
    eigen_config(mesh, m, ports, eig_cfg, outer=outer, n_modes=n_modes,
                 target_ghz=round(0.7 * min(f_lin), 3), order=order, direction=direction)
    eig_run = run_palace(eig_cfg, n_rank, reuse)
    eig = read_csv(out / "postpro_eig" / "eig.csv")
    epr = read_csv(out / "postpro_eig" / "port-EPR.csv")
    fcol = next(k for k in eig[0] if k.startswith("Re{f}"))
    qcol = next((k for k in eig[0] if k.strip() == "Q"), None)
    pcols = [next(k for k in epr[0] if k.startswith(f"p[{i + 1}]")) for i in range(len(ports))]
    modes = [{"m": int(e["m"]), "f_GHz": e[fcol], "Q": e.get(qcol) if qcol else None,
              "epr": [r[c] for c in pcols]} for e, r in zip(eig, epr)]

    rows = []
    for i, (lab, l_h) in enumerate(ports):
        name = lab[len(PORT):]
        q = lom[name]
        mode = max(modes, key=lambda md: abs(md["epr"][i]))
        e_j_hz = [FLUX_QUANTUM_REDUCED ** 2 / (lj * H_PLANCK) for _, lj in ports]   # E_J/h
        alpha = epr_alpha_hz(mode["f_GHz"] * 1e9, mode["epr"], e_j_hz)
        f_p = lom_linear_ghz(q.E_C_GHz, q.E_J_GHz)
        f01_num, f12_num = epr_levels_hz(mode["f_GHz"] * 1e9, mode["epr"], e_j_hz)
        rows.append({
            "qubit": name, "L_J_nH": l_h * 1e9, "mode": mode["m"],
            "f_eig_GHz": mode["f_GHz"], "epr": abs(mode["epr"][i]),   # Palace 的 p 带号 (随 Direction)
            "f_lom_linear_GHz": f_p, "rel_f_eig_vs_lom": mode["f_GHz"] / f_p - 1.0,
            "C_sigma_fF": q.C_sigma_fF, "C_sigma_from_eig_fF":
                1e15 / ((2 * math.pi * mode["f_GHz"] * 1e9) ** 2 * l_h),
            "alpha_epr_MHz": alpha / 1e6, "alpha_lom_MHz": q.anharmonicity_MHz,
            "alpha_lom_exact_MHz": q.anharmonicity_exact_MHz,
            "f01_epr_GHz": mode["f_GHz"] + alpha / 1e9, "f01_lom_GHz": q.f01_GHz,
            "f01_lom_exact_GHz": q.f01_exact_GHz,
            "f01_epr_numdiag_GHz": f01_num / 1e9, "alpha_epr_numdiag_MHz": (f12_num - f01_num) / 1e6,
            "EJ_over_EC": q.EJ_over_EC})
    summary = {
        "meta": str(meta_path), "mesh_um": [m.mesh["max_size_um"], m.mesh["min_size_um"]],
        "order": order, "outer_eigen": outer,
        "outer_es": (m.solver or {}).get("outer_boundary", "ground"),
        "mesh_cells": mesh.num_volume_cells, "mesh_s": round(t_mesh, 1),
        "runs": {"electrostatic": es_run, "eigenmode": eig_run},
        "capacitance_fF": {"labels": list(cap.labels), "maxwell": cap.maxwell_fF},
        "qubits": rows, "modes": modes,
        "lom_resonators": [asdict(r) for r in model.resonators],
    }
    (out / "summary.yaml").write_text(yaml.safe_dump(summary, sort_keys=False, allow_unicode=True),
                                      encoding="utf-8")
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("meta")
    ap.add_argument("out")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--outer", choices=OUTER)
    ap.add_argument("--np", type=int, default=4, dest="n_rank")
    ap.add_argument("--n", type=int, dest="n_modes")
    ap.add_argument("--order", type=int, default=2)
    ap.add_argument("--direction", choices=("+X", "+Y"), help="全部端口的 Direction (默认按结面长边猜)")
    ap.add_argument("--reuse", action="store_true", help="out 里已有 Palace log/postpro 时不重跑, 只重算汇总")
    a = ap.parse_args(argv)
    s = run(a.meta, a.out, scale=a.scale, outer=a.outer, n_rank=a.n_rank,
            n_modes=a.n_modes, order=a.order, reuse=a.reuse, direction=a.direction)
    print(yaml.safe_dump({k: s[k] for k in ("mesh_um", "outer_eigen", "runs", "qubits")},
                         sort_keys=False, allow_unicode=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
