# -*- coding: utf-8 -*-
"""拼装 (契约 N9): 多块电容矩阵按共享节点名累加, Schur 消掉未保留节点。

quasi-lumped 近似 (qiskit-metal LOM 2.0 同款, 机制同构证据见
.claude/assemble-lit-survey.md): 跨 cell 连通性 **只靠共享节点名**; 跨块直接
互容 = 结构性零 — 有意直接耦合的导体对必须同块共现 (SPEC「切块纪律」)。

与 v3 不同, v4 契约用 **显式 keep 列表** (不做 junction/动力学节点推断):
不在 keep 的节点全部 Schur 消元 ``C' = C_KK − C_KR·C_RR⁻¹·C_RK`` (被消节点
电荷恒为零的正确积掉, **不是接地**)。keep 里拼错的名字 raise — 拼错 =
静默接地是 v3 踩过的坑。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .circuit_model import _invert_matrix
from .errors import QuantumDslError

__all__ = ["AssembledMatrix", "assemble"]

_CELL_KEYS = frozenset({"name", "labels", "maxwell_fF"})


@dataclass(frozen=True)
class AssembledMatrix:
    """拼装 + 消元后的系统级电容矩阵 (fF), 行序 = ``labels`` = keep 顺序。"""

    labels: tuple[str, ...]
    maxwell_fF: list[list[float]]
    eliminated: tuple[str, ...] = ()


def assemble(cells, keep) -> AssembledMatrix:
    """多个 cell dict (``{name, labels, maxwell_fF}``, fF) → 一个系统矩阵。

    共享同名节点处电容 **自动叠加** (不是块对角拼接); ``keep`` 之外的节点
    Schur 消元。输出行序 = ``keep`` 顺序。
    """
    if not cells:
        raise QuantumDslError("assemble() needs >=1 cell")

    # --- 全局节点集 (首次出现定序) + 输入卫生 ------------------------------
    order: list[str] = []
    index: dict[str, int] = {}
    seen_names: set[str] = set()
    for cell in cells:
        if not isinstance(cell, dict):
            raise QuantumDslError(f"cells entries must be dicts, got {cell!r}")
        unknown = sorted(set(cell) - _CELL_KEYS)
        if unknown:
            raise QuantumDslError(
                f"cell {cell.get('name')!r}: unknown key(s) {unknown} "
                f"(known: {sorted(_CELL_KEYS)})")
        name = cell.get("name")
        if not name or not isinstance(name, str) or name in seen_names:
            raise QuantumDslError(
                f"cell name {name!r} must be a unique non-empty string")
        seen_names.add(name)
        labels = tuple(cell.get("labels") or ())
        mat = cell.get("maxwell_fF")
        nn = len(labels)
        if nn == 0 or len(set(labels)) != nn:
            raise QuantumDslError(
                f"cell {name!r}: labels must be non-empty and unique, "
                f"got {list(labels)}")
        if mat is None or len(mat) != nn or any(len(row) != nn for row in mat):
            raise QuantumDslError(
                f"cell {name!r}: maxwell_fF must be {nn}x{nn} to match labels "
                f"{list(labels)}")
        for i, rowv in enumerate(mat):
            for jc, v in enumerate(rowv):
                if not math.isfinite(v):
                    raise QuantumDslError(
                        f"cell {name!r}: maxwell_fF[{i}][{jc}] = {v} is not "
                        f"finite — refusing a nan/inf matrix")
        for lab in labels:
            if lab not in index:
                index[lab] = len(order)
                order.append(lab)

    keep = tuple(keep)
    known = ", ".join(order)
    for lab in keep:
        if lab not in index:
            raise QuantumDslError(
                f"keep label {lab!r} is not an assembled node (have: {known}) "
                f"— a typo here would silently ground/drop a conductor")
    if not keep or len(set(keep)) != len(keep):
        raise QuantumDslError(f"keep must be non-empty and unique, got {keep}")

    # --- 累加 (共享同名节点处叠加) -----------------------------------------
    dim = len(order)
    mat_g = [[0.0] * dim for _ in range(dim)]
    for cell in cells:
        labels = tuple(cell["labels"])
        cm = cell["maxwell_fF"]
        for i, la in enumerate(labels):
            r = index[la]
            for jc, lb in enumerate(labels):
                mat_g[r][index[lb]] += float(cm[i][jc])

    # --- Schur 消元 keep 之外的节点 ----------------------------------------
    keep_set = set(keep)
    remove = [lab for lab in order if lab not in keep_set]
    k_idx = [index[lab] for lab in keep]
    if remove:
        r_idx = [index[lab] for lab in remove]
        c_rr = [[mat_g[a][b] for b in r_idx] for a in r_idx]
        try:
            c_rr_inv = _invert_matrix(c_rr)
        except QuantumDslError as exc:
            raise QuantumDslError(
                f"Schur elimination failed: the submatrix of eliminated nodes "
                f"({', '.join(remove)}) is singular — each eliminated node "
                f"needs some capacitance of its own. Underlying: {exc}") from exc
        reduced = [
            [mat_g[p][q]
             - sum(mat_g[p][r_idx[a]] * c_rr_inv[a][b] * mat_g[r_idx[b]][q]
                   for a in range(len(r_idx)) for b in range(len(r_idx)))
             for q in k_idx]
            for p in k_idx]
    else:
        reduced = [[mat_g[p][q] for q in k_idx] for p in k_idx]

    return AssembledMatrix(labels=keep, maxwell_fF=reduced,
                           eliminated=tuple(remove))
