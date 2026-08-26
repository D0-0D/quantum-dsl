# -*- coding: utf-8 -*-
"""Palace 静电 (契约 N6): config 生成 + 电容 CSV 解析。

config 骨架 = 回归锚配方 (docs/physics.md §5):
``Model.L0 = 1e-6`` 是仓库里**唯一**的 µm→m 换算点 (网格坐标 µm, 别处不乘
不除); ``Solver.Order = 2`` 是承重件 (同网格 order 1 实测偏 +7.3%); 场输出
默认关 (电容工作流只消费 terminal-C.csv)。

外边界两种口径 (meta ``solver.outer_boundary``):
* ``ground`` (默认) = 接地屏蔽盒 (盒壁 Dirichlet 0);
* ``open``   = 盒壁不挂 BC (Palace 自然边界 ≡ ZeroCharge), 须版图自带
  ground:: 角色提供电位参考 —— 全悬浮导体问题奇异, 两者皆无时 raise。

CSV: Palace 输出 **SI 法拉** (terminal-C.csv 表头 "(F)"), fF = F × 1e15;
mutual (SPICE) 矩阵由 Maxwell 代数导出 (Cm_ii = Σ_j C_ij, Cm_ij = −C_ij),
不再依赖 terminal-Cm.csv。NaN/Inf 一律拒绝 (physics.md §10 #6)。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from .errors import QuantumDslError

__all__ = ["Cap", "palace_config", "parse_capacitance"]

_F_TO_FF = 1.0e15


@dataclass(frozen=True)
class Cap:
    """电容矩阵 (fF)。``maxwell_fF``: +对角 −非对角; ``mutual_fF``: 全正,
    对角 = 对地电容。行序 = ``labels``。"""

    labels: tuple[str, ...]
    maxwell_fF: list[list[float]]
    mutual_fF: list[list[float]]


def palace_config(mesh, meta, out) -> dict:
    """Mesh + Meta → Palace 静电 config (dict, 同时写 JSON 到 ``out``)。"""
    solver = meta.solver or {}
    stype = solver.get("type", "electrostatic")
    if stype != "electrostatic":
        raise QuantumDslError(
            f"palace_config: solver.type {stype!r} unsupported (v4 does "
            f"electrostatic only)")
    order = int(solver.get("order", 2))
    outer_mode = solver.get("outer_boundary", "ground")
    if outer_mode not in ("ground", "open"):
        raise QuantumDslError(
            f"palace_config: solver.outer_boundary {outer_mode!r} must be "
            f"'ground' or 'open'")
    substrate = meta.materials.get("substrate") or {}
    if "eps_r" not in substrate:
        raise QuantumDslError(
            "palace_config: meta.materials.substrate.eps_r is required")

    ground_attrs: list[int] = []
    if outer_mode == "ground":
        ground_attrs.append(mesh.boundary_groups["outer"])
    if "ground" in mesh.boundary_groups:
        ground_attrs.append(mesh.boundary_groups["ground"])
    if not ground_attrs:
        raise QuantumDslError(
            "palace_config: outer_boundary 'open' with no ground:: surfaces — "
            "an all-floating electrostatic problem is singular (no potential "
            "reference); ground the box or add a ground sheet")

    out = Path(out)
    cfg = {
        "Problem": {"Type": "Electrostatic", "Verbose": 2, "Output": "postpro"},
        "Model": {"L0": 1e-6, "Mesh": mesh.path.name},
        "Domains": {"Materials": [
            {"Attributes": [mesh.domain_groups["substrate"]],
             "Permittivity": float(substrate["eps_r"])},
            {"Attributes": [mesh.domain_groups["vacuum"]],
             "Permittivity": 1.0},
        ]},
        "Boundaries": {
            "Ground": {"Attributes": ground_attrs},
            # Index = C 矩阵行列号 (1 起); 顺序 = mesh.labels, 唯一真相源。
            "Terminal": [
                {"Index": i + 1, "Attributes": [mesh.conductor_groups[c]]}
                for i, c in enumerate(mesh.labels)],
        },
        "Solver": {"Order": order, "Device": "CPU",
                   "Electrostatic": {"Save": 0},
                   "Linear": {"Type": "BoomerAMG", "KSPType": "CG",
                              "Tol": 1.0e-8, "MaxIts": 200}},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def parse_capacitance(postpro, labels) -> Cap:
    """Palace postpro 目录 → :class:`Cap` (fF)。NaN/Inf/形状不符 raise。"""
    labels = tuple(labels)
    csv_path = Path(postpro) / "terminal-C.csv"
    if not csv_path.is_file():
        raise QuantumDslError(f"parse_capacitance: no such file: {csv_path}")
    rows = [line.split(",") for line in
            csv_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) < 2:
        raise QuantumDslError(f"parse_capacitance: {csv_path} has no data rows")
    n = len(labels)
    data = rows[1:]                       # 首行表头 "i, C[i][1] (F), ..."
    if len(data) != n or any(len(r) != n + 1 for r in data):
        raise QuantumDslError(
            f"parse_capacitance: {csv_path} is {len(data)}x"
            f"{max(len(r) for r in data) - 1}, expected {n}x{n} for labels "
            f"{labels}")
    maxwell: list[list[float]] = []
    for r in data:
        row = []
        for v in r[1:]:
            try:
                f = float(v)
            except ValueError:
                raise QuantumDslError(
                    f"parse_capacitance: {csv_path}: bad value {v!r}") from None
            if not math.isfinite(f):
                raise QuantumDslError(
                    f"parse_capacitance: {csv_path} contains {v.strip()} — "
                    f"refusing a nan/inf capacitance matrix (the solve is "
                    f"broken, fix it upstream)")
            row.append(f * _F_TO_FF)
        maxwell.append(row)
    mutual = [[sum(maxwell[i]) if i == j else -maxwell[i][j]
               for j in range(n)] for i in range(n)]
    return Cap(labels=labels, maxwell_fF=maxwell, mutual_fF=mutual)
