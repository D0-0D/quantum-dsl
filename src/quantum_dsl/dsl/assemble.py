# -*- coding: utf-8 -*-
"""Assembly layer (M8c / P0-B): many per-cell capacitance matrices → ONE system.

照抄 qiskit-metal **New LOM (LOM 2.0)** 的做法 (``analyses/quantization/
lom_core_analysis.py``, 理论 arXiv:2103.10344), 不自创机制:

1. **电容图并联累加** —— 每个 cell 的 Maxwell 矩阵转成 (节点对 → 电容) 邻接表, 在
   **全局节点索引**上 ``mat[r][c] += w``。**共享同名节点处电容自动叠加**, 不是块对角
   拼接。跨 cell 的连通性 **只靠共享节点名** (New LOM 的 ``node_rename``), 没有别的
   连接件概念。对照 ``lom_core_analysis.py:216`` (``_df_cmat_to_adj_list``) +
   ``:510-522`` (``_adj_list_to_mat``)。
2. **Schur 消元非动力学节点** (eq 7b, ``:715-732``) —— 只接电容、不接任何电感/结支路
   的节点不是动力学自由度, 其电荷恒为零, 必须**积掉**而不是接地。
   ``nodes_force_keep`` 强行保留想留的节点 (谐振器接入点)。

**本模块在 NODE 基上做 Schur, 不做 New LOM 的 S_n 结基变换** —— 结基变换由既有的
``circuit_model.solve_circuit_model`` (``C' = BᵀC_S B``, M6 已在单 cell 上对 LOM 2.0
验证 <0.1%) 承担。两者可交换: 被消掉的节点不在任何结坐标的张成里, 所以
「先消元再换基」与「先换基再消元」给同一个结果, 而 node-basis Schur 就是 eq 7b 里
S_k/S_r 取选择矩阵时的 Schur 补 ``C_kk − C_kr C_rr⁻¹ C_rk``。选前者是因为它让 M6 一行不改。

**结电容 ``C_j`` 本层不碰** (主控裁决, 避免双计) —— 拼装后的 ``maxwell`` 是纯几何/EM
的电容图; ``CellJunction.C_j`` 只是载体 (sidecar → ``geo_build`` → ``circuit_model``),
本层只校验它非负有限。折入由 ``circuit_model`` 在 **结基对角** 上做
(``cprime[k][k] += C_j``, ``circuit_model.py:699``)。两处折入 **代数恒等**: New LOM 的
``_cj_dict_to_adj_list`` (``lom_core_analysis.py:228``) 在 node 基上加
``mat[a][a] += C_j``/``mat[b][b] += C_j``/``mat[a][b] -= C_j``, 用双岛的
``B`` (``b_mat[a][k]=0.5``, ``b_mat[b][k]=−0.5``, σ 列全 1) 做 ``BᵀC_jB``:

    θθ: 0.25C_j + 0.25C_j + 0.25C_j + 0.25C_j = C_j     ← 只落在结支路对角
    σσ: C_j + C_j − C_j − C_j = 0
    θσ: 0.5C_j − 0.5C_j − 0.5C_j + 0.5C_j = 0
    接地单岛 (``b_mat[a][k]=1``): C_j

即 node 基折入经过结基变换后, 恰好只在 θθ 对角上留下 ``+C_j``。放在
``circuit_model`` 覆盖面更广: 不带 ``extract:`` 的整片解走 ``circuit_model:`` sidecar
块, **不经过本模块**, C_j 若只在这里就永远表达不了。

**非动力学节点用结构判定, 不求 ``L_inv`` 零空间** (spec §12 第 2 项的裁决): 一个节点
若不出现在任何 ``CellJunction.between`` 里 (= 没有电感/结支路接入) 且不在
``nodes_force_keep`` 里, 就是非动力学节点。这与 New LOM 在 ``L_inv`` 零空间上的判定
在 node 基上等价 —— ``L_n_inv`` 的第 i 行全零 ⟺ 节点 i 不接任何电感支路。
实证 (4.05): 参考的 ``get_nodes_remove()`` = ``['pad_bot_Q1','pad_bot_Q2','coupling']``,
其中 ``coupling`` 是本层消掉的那一个, 另两个是 **结基下的共模坐标** ——
它们由 ``circuit_model`` 的 ``C' = BᵀC_S B`` + 完整求逆消掉 (取逆的 θθ 块 **就是**
对 σ 做 Schur 补), 见 ``circuit_model`` 模块 docstring。两层合起来与参考逐项对上,
实测 ``C_k`` 最大偏差 7.7e-16 相对 (``tests/test_assemble.py``)。

单位约定 (与 ``palace_adapter.CapacitanceResult`` / ``circuit_model`` 一致):
**电容矩阵 fF**, 结参数 SI (``L_J`` 亨利 / ``E_J`` 焦耳 / ``C_j`` 法拉)。

纯 Python: 只用 ``math`` + 本包数据类, **不** import gmsh/gdstk/numpy/scipy。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from .circuit_model import _invert_matrix
from .errors import DesignDslError


__all__ = [
    "CellJunction",
    "ExtractedCell",
    "AssembledSystem",
    "assemble",
]


@dataclass(frozen=True)
class CellJunction:
    """一个约瑟夫森元件 (= New LOM 的 ``jj_dict`` + ``cj_dict`` 的一项)。

    Fields:
        name:    结名 (``subsystems[].junction`` 引用它)。
        between: 1 或 2 个 **post-rename** 节点名。2 个 = 结跨两节点 (浮动/差分);
                 1 个 = 节点 ↔ 地 (接地 transmon)。
        L_J:     约瑟夫森电感 (亨利); 与 E_J / SQUID 三选一。
        E_J:     约瑟夫森能 (焦耳); 与 L_J / SQUID 三选一。
        E_J1/E_J2/flux: 磁通可调 (可非对称) SQUID; ``flux`` = Φ/Φ0 (归一化)。
        C_j:     结电容 (法拉), **默认 0.0** —— 不静默移动任何现有数值。
                 对照 New LOM 的 ``cj_dict`` / 老 LOM 的 ``Cq = tCSq + CJ``。
    """

    name: str
    between: tuple[str, ...]
    L_J: float | None = None
    E_J: float | None = None
    E_J1: float | None = None
    E_J2: float | None = None
    flux: float = 0.0
    C_j: float = 0.0


@dataclass(frozen=True)
class ExtractedCell:
    """一次 EM 提取的产物 (= New LOM 的 ``Cell``, ``lom_core_analysis.py:1255``)。

    Fields:
        name:      块名 (``extract.blocks[].name``)。
        terminals: 矩阵行/列对应的 **post-rename** 节点名, 顺序 = 矩阵行序。
        maxwell:   Maxwell 电容矩阵 (**fF**, +对角 −非对角), 与 terminals 同序。
        junctions: 本 cell 的结。
        source:    ``"solved"`` (跑了 Palace) | ``"file"`` | ``"inline"`` ——
                   溯源必须能区分实解与注入 (风险 R4)。
        sha256:    ``source != "solved"`` 时注入文件的内容哈希 (inline 为 None)。
    """

    name: str
    terminals: tuple[str, ...]
    maxwell: tuple[tuple[float, ...], ...]
    junctions: tuple[CellJunction, ...] = ()
    source: str = "solved"
    sha256: str | None = None


@dataclass(frozen=True)
class AssembledSystem:
    """拼装 + Schur 消元后的系统级电容模型。

    Fields:
        nodes:       保留下来的节点名 (动力学节点 + ``nodes_force_keep``), 顺序 =
                     ``maxwell`` 行序。
        maxwell:     拼装并消元后的 Maxwell 电容矩阵 (**fF**), 与 ``nodes`` 同序。
        junctions:   全部 cell 的结 (拼装后仍按 ``between`` 引用 ``nodes``)。
        eliminated:  被 Schur 消掉的节点名 (审计用)。
        ground_node: 参考地节点名 (不进 ``nodes``); None = 无显式地 (退化为无穷远)。
        audit:       拼装审计 —— 每个节点来自哪些 cell、叠加了几次、警告列表
                     (风险 R2: 共享节点名拼错会静默丢/虚增耦合)。
    """

    nodes: tuple[str, ...]
    maxwell: tuple[tuple[float, ...], ...]
    junctions: tuple[CellJunction, ...] = ()
    eliminated: tuple[str, ...] = ()
    ground_node: str | None = None
    audit: dict = field(default_factory=dict)

    def as_capacitance_result(self):
        """包装成 ``CapacitanceResult`` 以直接喂给 ``solve_circuit_model``。

        每个节点造一个 ``TerminalBinding(index=i+1, group=node, attribute=0)``,
        使既有的 M6 求解器 (按 group 名寻址矩阵行) 一行不改地消费拼装结果。
        """
        from .palace_adapter import CapacitanceResult, TerminalBinding
        from pathlib import Path

        return CapacitanceResult(
            postpro_dir=Path("."),
            available=bool(self.maxwell),
            units="fF",
            terminals=tuple(
                TerminalBinding(index=i + 1, group=name, attribute=0)
                for i, name in enumerate(self.nodes)),
            maxwell=[list(row) for row in self.maxwell],
        )


def assemble(cells: Sequence[ExtractedCell],
             *,
             ground_node: str | None = None,
             nodes_force_keep: Sequence[str] = (),
             ) -> AssembledSystem:
    """把多个 ``ExtractedCell`` 按共享节点名累加, 再 Schur 消掉非动力学节点。

    四步 (与 ``lom_core_analysis`` 逐段对照):

    1. **全局节点集**: 按 cell 顺序 + cell 内 terminal 顺序**首次出现**定序 (确定性)。
       ``ground_node`` **不进**节点集 —— 它的电势固定, 对地电容已经在每份 Maxwell
       矩阵的对角里 (对照 ``_maybe_remove_grd_node_then_cache``)。
    2. **累加**: 每份 Maxwell 矩阵按 ``mat[r][c] += w`` 加到全局索引上 (``:216`` 邻接表
       + ``:510-522``)。**同名节点自动叠加**, 不是块对角拼接。``C_j`` 不进这里
       (由 ``circuit_model`` 在结基对角上折入, 见模块 docstring)。
    3. **Schur 消元**: ``C_reduced = C_kk − C_kr C_rr⁻¹ C_rk`` (eq 7b, ``:715-732`` 在
       ``S_k``/``S_r`` 取选择矩阵时的展开)。``C_rr`` 用 ``circuit_model._invert_matrix``
       求逆 (自带 scale-relative 奇异守卫)。
    4. **审计**: 每个节点来自哪些 cell / 哪些是共享节点 / 每个 cell 的来源与 sha256 /
       被消掉的节点 / 警告 (风险 R2+R4)。

    Args:
        cells:            每个 cell 一份 Maxwell 矩阵 + 本 cell 的结。
        ground_node:      参考地节点名 —— 该节点从矩阵里划掉 (电势固定), 其对地
                          电容已在 Maxwell 矩阵的对角里。
        nodes_force_keep: 即便没有电感/结支路也**不许**被消掉的节点 (谐振器接入点)。

    Returns:
        ``AssembledSystem``。

    Raises:
        DesignDslError: ``cells`` 为空 / cell 名重复 / 矩阵非方阵或与 ``terminals``
            长度不符 / 矩阵含非有限元素 / ``between`` 长度不是 1~2 或两端同名 /
            ``C_j`` 非有限或为负 / ``between`` 或 ``nodes_force_keep`` 引用了不存在的
            节点 / 没有任何节点留下 / 消元子矩阵 ``C_rr`` 奇异。
    """
    if not cells:
        raise DesignDslError("assemble() needs >=1 ExtractedCell (cells is empty)")

    # --- 1. 全局节点集 (首次出现定序) + 输入校验 --------------------------------
    order: list[str] = []
    index: dict[str, int] = {}
    contributors: dict[str, list[str]] = {}
    seen_names: set[str] = set()
    for cell in cells:
        if cell.name in seen_names:
            raise DesignDslError(
                f"duplicate cell name {cell.name!r} — every extract block needs a "
                f"unique name (the assembly audit / provenance is keyed by it)")
        seen_names.add(cell.name)
        n = len(cell.terminals)
        if n == 0:
            raise DesignDslError(f"cell {cell.name!r}: terminals must be non-empty")
        if len(cell.maxwell) != n or any(len(row) != n for row in cell.maxwell):
            shape = f"{len(cell.maxwell)}x" + (
                "|".join(str(len(r)) for r in cell.maxwell) or "0")
            raise DesignDslError(
                f"cell {cell.name!r}: Maxwell matrix must be square and match its "
                f"{n} terminals ({list(cell.terminals)}) — got {shape}")
        for i, row in enumerate(cell.maxwell):
            for j, value in enumerate(row):
                # nan/inf 必须在这里挡: 下游全是加法与求逆, 一个 nan 会静默污染整个
                # 拼装矩阵, 而 ``nan <= tol`` 是 False 连奇异守卫都绕过。
                if not math.isfinite(value):
                    raise DesignDslError(
                        f"cell {cell.name!r}: Maxwell[{i}][{j}] = {value} is not "
                        f"finite (fF) — refusing to assemble a nan/inf matrix")
        for term in cell.terminals:
            if term == ground_node:
                continue
            if term not in index:
                index[term] = len(order)
                order.append(term)
            if cell.name not in contributors.setdefault(term, []):
                contributors[term].append(cell.name)

    dim = len(order)
    if dim == 0:
        raise DesignDslError(
            f"assemble(): every terminal is the ground node "
            f"{ground_node!r} — nothing left to solve")

    # --- 2. 电容图并联累加 (共享同名节点处叠加) --------------------------------
    mat = [[0.0] * dim for _ in range(dim)]
    for cell in cells:
        n = len(cell.terminals)
        for i in range(n):
            if cell.terminals[i] == ground_node:
                continue
            r = index[cell.terminals[i]]
            for j in range(i, n):                      # 上三角一次 (含对角)
                if cell.terminals[j] == ground_node:
                    continue
                c = index[cell.terminals[j]]
                mat[r][c] += float(cell.maxwell[i][j])
                if r != c:
                    mat[c][r] += float(cell.maxwell[i][j])

    # --- 结: 校验 + 动力学节点标记 (C_j 不进这里的矩阵, 见模块 docstring) -------
    junctions: list[CellJunction] = []
    dynamic: set[str] = set()
    known = ", ".join(order)
    for cell in cells:
        for jj in cell.junctions:
            junctions.append(jj)
            if not 1 <= len(jj.between) <= 2:
                raise DesignDslError(
                    f"cell {cell.name!r} junction {jj.name!r}: between must name 1 "
                    f"node (node<->ground) or 2 nodes (floating/differential), got "
                    f"{list(jj.between)}")
            if len(jj.between) == 2 and jj.between[0] == jj.between[1]:
                raise DesignDslError(
                    f"cell {cell.name!r} junction {jj.name!r}: between names the "
                    f"same node twice ({jj.between[0]!r}) — a junction needs two "
                    f"distinct nodes (or a single node, meaning node<->ground)")
            grounded = 0
            for name in jj.between:
                if name == ground_node:
                    grounded += 1
                    continue                            # 结的一端接地
                if name not in index:
                    raise DesignDslError(
                        f"cell {cell.name!r} junction {jj.name!r}: between node "
                        f"{name!r} is not an assembled node (have: {known})")
                dynamic.add(name)
            if grounded == len(jj.between):
                raise DesignDslError(
                    f"cell {cell.name!r} junction {jj.name!r}: both ends are the "
                    f"ground node {ground_node!r} — that is a short, not a junction")
            if not (math.isfinite(jj.C_j) and jj.C_j >= 0.0):
                raise DesignDslError(
                    f"cell {cell.name!r} junction {jj.name!r}: C_j must be a finite "
                    f">= 0 capacitance in farad, got {jj.C_j}")

    for name in nodes_force_keep:
        if name not in index:
            hint = (f" (it is the ground node — the ground potential is fixed and "
                    f"never a degree of freedom)" if name == ground_node else "")
            raise DesignDslError(
                f"nodes_force_keep node {name!r} is not an assembled node{hint} "
                f"(have: {known})")

    # --- 3. Schur 消元 (eq 7b) ------------------------------------------------
    keep_set = dynamic | set(nodes_force_keep)
    keep = [name for name in order if name in keep_set]
    remove = [name for name in order if name not in keep_set]
    if not keep:
        raise DesignDslError(
            f"assemble(): no dynamic node left — none of the {dim} nodes "
            f"({known}) is touched by a junction and nodes_force_keep is empty, "
            f"so Schur elimination would remove everything")

    if remove:
        r_idx = [index[name] for name in remove]
        k_idx = [index[name] for name in keep]
        c_rr = [[mat[a][b] for b in r_idx] for a in r_idx]
        try:
            c_rr_inv = _invert_matrix(c_rr)
        except DesignDslError as exc:
            raise DesignDslError(
                f"Schur elimination failed: the capacitance submatrix of the "
                f"non-dynamic nodes being eliminated ({', '.join(remove)}) is "
                f"singular or ill-conditioned — each eliminated node needs some "
                f"capacitance of its own (a node with no capacitance at all is not "
                f"a node; check the shared node names and nodes_force_keep). "
                f"Underlying: {exc}") from exc
        reduced = [
            [mat[p][q] - sum(mat[p][r_idx[a]] * c_rr_inv[a][b] * mat[r_idx[b]][q]
                             for a in range(len(r_idx))
                             for b in range(len(r_idx)))
             for q in k_idx]
            for p in k_idx]
    else:
        reduced = [[mat[a][b] for b in range(dim)] for a in range(dim)]

    # --- 4. 审计 (R2: 共享节点名拼错; R4: 实解 vs 注入) -----------------------
    warnings: list[str] = []
    for name in order:
        if len(contributors[name]) > 1 and name not in keep_set:
            warnings.append(
                f"shared node {name!r} (contributed by cells "
                f"{', '.join(contributors[name])}) is referenced by no junction and "
                f"is not in nodes_force_keep, so it is Schur-eliminated into the "
                f"reduced matrix. That is correct for a passive coupler; if the node "
                f"is meant to be a degree of freedom (a resonator tap) add it to "
                f"nodes_force_keep, and if the name is a typo the cells are coupled "
                f"through the wrong node.")

    audit = {
        "nodes": {name: list(contributors[name]) for name in order},
        "shared_nodes": [n for n in order if len(contributors[n]) > 1],
        "sources": {cell.name: cell.source for cell in cells},
        "sha256": {cell.name: cell.sha256 for cell in cells},
        "eliminated": list(remove),
        "warnings": warnings,
    }

    return AssembledSystem(
        nodes=tuple(keep),
        maxwell=tuple(tuple(row) for row in reduced),
        junctions=tuple(junctions),
        eliminated=tuple(remove),
        ground_node=ground_node,
        audit=audit,
    )
