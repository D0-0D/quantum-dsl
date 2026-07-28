# -*- coding: utf-8 -*-
"""Circuit-model solve (M6): Palace capacitance matrix → transmon Hamiltonian.

把 M3 写出的 **Maxwell 电容矩阵** (``chip.results.yaml`` 的 ``capacitance.maxwell``,
单位 fF) 约化成集总振子模型 (LOM) 的 transmon 量子比特 Hamiltonian 参数, 实现
"physical group → circuit model" (需求 R1 + R3)。本模块是 **纯 Python**:
只用 ``math`` (标准库) + ``CapacitanceResult``/``TerminalBinding`` 数据类, **不**
import gmsh / gdstk / numpy / scipy, 因此在任何环境 (含 metal-env-old) 下可单测。

物理 (lumped-oscillator inverse-capacitance method, 结支坐标形式):
    取 Maxwell 矩阵在 **所有被 qubit 引用的岛** 上的子矩阵 ``C_S`` (SI 法拉), 动能
    ``T = ½ φ̇ᵀ C_S φ̇`` (φ = 节点磁通)。每个 qubit k 的约瑟夫森元件定义一个 **支路
    坐标** (junction branch coordinate):

    * **接地单岛** (``islands=(a,)``): θ_k = φ_a —— 结跨在岛与地之间。
    * **浮动/差分双岛** (``islands=(a, b)``): θ_k = φ_a − φ_b (结跨两焊盘),
      再补一个正交的共模坐标 σ_k = (φ_a + φ_b)/2。

    组成变换 ``φ = B ξ``, ``ξ = (θ…, σ…)``, 换基后
        C' = Bᵀ C_S B
        E_C,k  = (e²/2) · [C'⁻¹]_θθ,kk                     (充电能, 焦耳)
        C_Σ,k  = 1 / [C'⁻¹]_θθ,kk                          (等效节点电容, 法拉)
        E_J,k  = (ħ/2e)² / L_J,k   (或直接给定)            (约瑟夫森能, 焦耳)
        f01,k  = (√(8 E_C E_J) − E_C) / h                  (跃迁频率, Hz)
        α_k    = −E_C,k / h                                (非简谐性, Hz)
        g_ij/2π = ½ · |[C'⁻¹]_ij| / √([C'⁻¹]_ii·[C'⁻¹]_jj) · √(f_i·f_j)  (电荷耦合, Hz)

    **必须求整个 C' 的逆再取 θθ 块**: 共模 σ 的电荷是守恒的 c-number (浮动岛对没有
    到地的约瑟夫森/电感元件), 令其电荷为零正是正确的约化, 而这一约化只在完整逆里才
    体现 (θθ 块的逆 ≠ 逆的 θθ 块)。

    退化情形: 全为接地单岛时 B 退化成选择矩阵, 上式 **逐位** 等于旧的
    ``E_C = (e²/2)[C_S⁻¹]_ii``; 单个孤立岛 (1×1) 再退化为 E_C = e²/(2 C_ii);
    N=2 退化为 g = ½(C_g/√(C_Σi C_Σj))√(f_i f_j)。对称双焊盘浮动 qubit
    ``C_S = [[g+m, −m], [−m, g+m]]`` 手算给 C' = diag(g/2+m, 2g), 即
    C_Σ = m + g/2 = c_tb + c_t0∥c_b0 (经典串联结果)。

    **未被任何 qubit 引用的 Terminal 一律视作接地电极** (固定电势) —— 不进入 C_S,
    其电容已折进被引用岛的对角线。已知局限: 一条 **浮动耦合总线** (galvanic 隔离、
    但物理上不该接地的导体) 同样会被接地, 正确处理需要对该节点做 Schur 补消元
    (而不是像 σ 那样简单丢弃), 目前不支持。

约定: 充电能/约瑟夫森能内部一律用 **焦耳**; 仅在写进结果数据类时转 GHz/MHz。
公式按 transmon 微扰展开 (leading order in E_C/E_J), 在 E_J/E_C ≫ 1 时有效 (典型 >~50
误差 <1%); 故每个结果带 ``EJ_over_EC`` 供消费端判断有效域。耦合 g 取电荷耦合率
(RWA, 简谐化岛), 在色散/transmon 区有效。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .errors import DesignDslError
from .palace_adapter import CapacitanceResult


__all__ = [
    "JunctionInput",
    "QubitResult",
    "CouplingResult",
    "CircuitModelResult",
    "solve_circuit_model",
    "charging_energy_joule",
    "josephson_energy_joule",
    "transmon_f01_hz",
    "ELEM_CHARGE",
    "H_PLANCK",
    "HBAR",
    "FLUX_QUANTUM_REDUCED",
]


# ---------------------------------------------------------------------------
# physical constants — exact SI (2019 redefinition); ħ derived, never hardcoded
# ---------------------------------------------------------------------------
ELEM_CHARGE = 1.602176634e-19          # C   (exact, SI-2019)
H_PLANCK = 6.62607015e-34              # J·s (exact, SI-2019)
HBAR = H_PLANCK / (2.0 * math.pi)      # J·s (derived — never a rounded literal)
FLUX_QUANTUM_REDUCED = HBAR / (2.0 * ELEM_CHARGE)  # Wb, φ0 = ħ/2e

_F_PER_FF = 1.0e-15  # 1 fF = 1e-15 F


# ---------------------------------------------------------------------------
# inputs / outputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class JunctionInput:
    """一个量子比特的输入: 岛 (Terminal 组名) + 约瑟夫森元件 (L_J 或 E_J)。

    Fields:
        name:    量子比特名 (结果里 qubit 的标识)。
        islands: 引用的导体岛 = ``capacitance.terminals[].group`` 组名 (已 sanitize 的
                 ``{component}_{primitive}_sfs``)。1 个岛 = **接地 transmon** (结跨岛
                 与地); 2 个岛 = **浮动/差分 transmon** (结跨两焊盘, 顺序 (a, b) 定义
                 θ = φ_a − φ_b, 符号不影响任何输出量)。>2 个岛需要多个结, 不支持。
        L_J:     约瑟夫森电感, **亨利 (SI)**; 与 E_J 二选一。
        E_J:     约瑟夫森能, **焦耳 (SI)**; 与 L_J 二选一。
    """

    name: str
    islands: tuple[str, ...]
    L_J: float | None = None
    E_J: float | None = None

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise DesignDslError("JunctionInput.name must be a non-empty string")
        if not self.islands:
            raise DesignDslError(
                f"JunctionInput {self.name!r}: islands must be non-empty")
        if (self.L_J is None) == (self.E_J is None):
            raise DesignDslError(
                f"JunctionInput {self.name!r}: set exactly one of L_J / E_J")
        if self.L_J is not None and self.L_J <= 0:
            raise DesignDslError(
                f"JunctionInput {self.name!r}: L_J must be > 0 (henry)")
        if self.E_J is not None and self.E_J <= 0:
            raise DesignDslError(
                f"JunctionInput {self.name!r}: E_J must be > 0 (joule)")

    def e_j_joule(self) -> float:
        """约瑟夫森能 (焦耳): 直接给的 E_J, 或由 L_J 推 (ħ/2e)²/L_J。"""
        if self.E_J is not None:
            return self.E_J
        return FLUX_QUANTUM_REDUCED ** 2 / self.L_J  # type: ignore[operator]


@dataclass(frozen=True)
class QubitResult:
    """一个 transmon 的派生 Hamiltonian 参数 (单位见各字段名后缀)。"""

    name: str
    islands: tuple[str, ...]
    C_sigma_fF: float        # 等效结电容 1/[C'⁻¹]_θθ,kk (fF)
    E_C_GHz: float           # 充电能 / h (GHz)
    E_J_GHz: float           # 约瑟夫森能 / h (GHz)
    f01_GHz: float           # 0→1 跃迁频率 (GHz)
    anharmonicity_MHz: float # α = −E_C (MHz, 负)
    EJ_over_EC: float        # E_J/E_C 比 (判断 transmon 有效域)


@dataclass(frozen=True)
class CouplingResult:
    """一对量子比特的电容耦合 (电荷耦合率 g/2π)。"""

    qubit_a: str
    qubit_b: str
    # 支路坐标间的耦合电容 |C'_θiθj| (fF): 两个接地单岛 → |Maxwell offdiag|;
    # 两个差分 qubit → ¼|c_aiaj + c_bibj − c_aibj − c_biaj| (差分-差分电容)。
    C_g_fF: float
    g_MHz: float             # g/2π (MHz, 取正)


@dataclass(frozen=True)
class CircuitModelResult:
    """电路模型求解结果 (R1+R3 的产物; 写进 chip.results.yaml 的 ``hamiltonian`` 段)。"""

    qubits: tuple[QubitResult, ...]
    couplings: tuple[CouplingResult, ...]
    method: str = "lumped_oscillator_inverse_cap"
    validity: str = (
        "perturbative transmon (leading order in E_C/E_J, valid E_J/E_C >> 1); "
        "charge coupling in RWA (harmonic islands), valid in the dispersive regime; "
        "junction-branch coordinates (2-island qubits are solved as floating/"
        "differential, common mode charge = 0); capacitance terminals not "
        "referenced by any qubit are treated as grounded electrodes"
    )
    units: dict[str, str] = field(default_factory=lambda: {
        "capacitance": "fF",
        "energy": "GHz",
        "frequency": "GHz",
        "anharmonicity": "MHz",
        "coupling": "MHz",
    })


# ---------------------------------------------------------------------------
# closed-form transmon helpers (energies in Joule unless noted)
# ---------------------------------------------------------------------------

def charging_energy_joule(c_sigma_farad: float) -> float:
    """E_C = e²/(2 C_Σ) (焦耳)。"""
    if c_sigma_farad <= 0:
        raise DesignDslError(
            f"charging energy needs C_Sigma > 0, got {c_sigma_farad}")
    return ELEM_CHARGE ** 2 / (2.0 * c_sigma_farad)


def josephson_energy_joule(l_j_henry: float) -> float:
    """E_J = (ħ/2e)²/L_J (焦耳)。"""
    if l_j_henry <= 0:
        raise DesignDslError(f"E_J needs L_J > 0, got {l_j_henry}")
    return FLUX_QUANTUM_REDUCED ** 2 / l_j_henry


def transmon_f01_hz(e_c_joule: float, e_j_joule: float) -> float:
    """f01 = (√(8 E_C E_J) − E_C)/h (Hz)。E_C/E_J 为焦耳。"""
    return (math.sqrt(8.0 * e_c_joule * e_j_joule) - e_c_joule) / H_PLANCK


# ---------------------------------------------------------------------------
# tiny symmetric matrix inverse (pure Python — no numpy/scipy)
# ---------------------------------------------------------------------------

def _invert_matrix(mat: Sequence[Sequence[float]]) -> list[list[float]]:
    """Gauss-Jordan 求逆 (partial pivoting), 用于小的电容子矩阵。

    输入须为 N×N 方阵 (N≥1)。奇异 → ``DesignDslError``。纯 Python, 无外部依赖。
    """
    n = len(mat)
    if n == 0 or any(len(row) != n for row in mat):
        raise DesignDslError("capacitance submatrix must be square and non-empty")
    # 增广 [A | I]
    aug = [[float(mat[i][j]) for j in range(n)]
           + [1.0 if i == k else 0.0 for k in range(n)]
           for i in range(n)]
    # 奇异/病态判据须 *相对* 于矩阵量级: 绝对阈值 (旧值 1e-300) 对法拉级
    # (~1e-15) 输入毫无意义 —— 近奇异/病态子矩阵会被静默求逆成垃圾 C⁻¹。
    # 当某 pivot 跌到矩阵特征量级的 ~1e-12 以下 (即条件数 ≳ 1e12, 双精度已无
    # 有效位) 即判定不可逆。全零矩阵 (scale=0 → tol=0, pivot=0) 同样命中。
    scale = max((abs(mat[i][j]) for i in range(n) for j in range(n)),
                default=0.0)
    sing_tol = 1e-12 * scale
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) <= sing_tol:
            raise DesignDslError(
                f"capacitance submatrix is singular or ill-conditioned — "
                f"cannot invert (pivot {abs(aug[pivot][col]):.3e} ≤ tol "
                f"{sing_tol:.3e}); check that the qubit islands are distinct, "
                f"well-separated conductors (for a floating/differential qubit "
                f"the island pair also needs some capacitance to ground — an "
                f"otherwise isolated pair has a zero common-mode capacitance)")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        diag = aug[col][col]
        aug[col] = [v / diag for v in aug[col]]
        for r in range(n):
            if r != col:
                factor = aug[r][col]
                if factor != 0.0:
                    aug[r] = [a - factor * b for a, b in zip(aug[r], aug[col])]
    return [row[n:] for row in aug]


def _congruence(mat: Sequence[Sequence[float]],
                b: Sequence[Sequence[float]]) -> list[list[float]]:
    """``Bᵀ M B`` (naive triple loop — matrices here are ≤ ~10×10).

    For ``B`` = a selection matrix (all-grounded case) this is bit-exact with
    the corresponding sub-block of ``M``: the extra terms are exact ``0.0``.
    """
    n = len(mat)
    ncol = len(b[0]) if b else 0
    return [[sum(b[p][i] * mat[p][q] * b[q][j]
                 for p in range(n) for q in range(n))
             for j in range(ncol)] for i in range(ncol)]


# ---------------------------------------------------------------------------
# the solve
# ---------------------------------------------------------------------------

def solve_circuit_model(
    cap_result: CapacitanceResult,
    qubits: Sequence[JunctionInput],
) -> CircuitModelResult:
    """Maxwell 电容矩阵 + 约瑟夫森输入 → transmon Hamiltonian 参数 + 成对耦合。

    在被引用岛的节点子矩阵 ``C_S`` 上换到 **结支路坐标** 求解 (推导见模块 docstring):

    * ``islands=(a,)`` → **接地 transmon**, θ = φ_a;
    * ``islands=(a, b)`` → **浮动/差分 transmon**, θ = φ_a − φ_b 外加共模
      σ = (φ_a + φ_b)/2 (σ 电荷守恒 = 0, 但必须进 ``C' = Bᵀ C_S B`` 一起求逆, 再取
      θθ 块 —— 只把 σ 行列删掉是错的)。

    单岛写法把浮动 transmon 的另一个焊盘 **静默接地**, 在真实器件上是 ~1.8× 的
    C_Σ 误差; 差分器件务必声明两个岛。

    **未被任何 qubit 引用的 Terminal 视作接地电极** (固定电势, 不进 ``C_S``, 其电容
    已折进被引用岛的对角线)。已知局限: 浮动耦合总线 (不该接地的孤立导体) 也会被
    接地 —— 那需要 Schur 补消元, 不在本函数范围内。

    Args:
        cap_result: 已解析的电容结果 (须含非空 ``maxwell`` 矩阵 + ``terminals`` 绑定)。
        qubits:     量子比特输入列表 (每个引用 1 或 2 个岛组名 + L_J/E_J)。

    Returns:
        ``CircuitModelResult`` (qubits 派生参数 + 每个无序对的耦合 g)。

    Raises:
        DesignDslError: 无 Maxwell 矩阵 / 岛不是已知 Terminal / 一个 qubit 引用 >2 个岛 /
            两处引用同一个 Terminal / qubit 列表为空 / 变换后矩阵奇异 /
            ``[C'⁻¹]_θθ,kk ≤ 0`` / 非 transmon 区 (f01 ≤ 0)。
    """
    if not qubits:
        raise DesignDslError("solve_circuit_model needs >=1 qubit")
    if not cap_result.maxwell:
        raise DesignDslError(
            "circuit-model solve needs a Maxwell capacitance matrix "
            "(capacitance.maxwell / terminal-C.csv); none available")

    maxwell = cap_result.maxwell
    # group name → 0-based 矩阵行列号 (Terminal Index − 1), 矩阵行列的唯一真相源。
    group_to_idx: dict[str, int] = {
        b.group: (b.index - 1) for b in cap_result.terminals
    }
    if not group_to_idx:
        raise DesignDslError(
            "capacitance result carries no terminal bindings — cannot map "
            "qubit islands to matrix rows")
    available = ", ".join(sorted(group_to_idx)) or "<none>"

    node_idx: list[int] = []          # 子矩阵行 → Maxwell 行
    seen: dict[int, str] = {}         # Maxwell 行 → 已占用它的岛名
    for q in qubits:
        if len(q.islands) > 2:
            raise DesignDslError(
                f"qubit {q.name!r}: {len(q.islands)} islands "
                f"({list(q.islands)}) — only 1 island (grounded transmon, "
                f"junction island↔ground) or 2 islands (floating/differential "
                f"transmon, junction across the two pads) are supported; a "
                f">2-island network needs one Josephson element per branch, "
                f"which a single L_J/E_J cannot express — split it into "
                f"several qubit entries or model it externally")
        for island in q.islands:
            if island not in group_to_idx:
                raise DesignDslError(
                    f"qubit {q.name!r}: island {island!r} is not a capacitance "
                    f"terminal (have: {available})")
            idx = group_to_idx[island]
            if idx in seen:
                raise DesignDslError(
                    f"qubit {q.name!r}: island {island!r} and {seen[idx]!r} are "
                    f"the same capacitance terminal (row {idx + 1}) — every "
                    f"qubit island must be a distinct conductor")
            seen[idx] = island
            node_idx.append(idx)

    # 被引用岛的节点子矩阵 C_S (fF, 与输入同单位); 未引用的 Terminal 视作接地 →
    # 不入子矩阵。
    sub = [[maxwell[a][b] for b in node_idx] for a in node_idx]

    # φ = B ξ, ξ = (θ_0..θ_{nq-1}, σ…): 前 nq 列 = 每个 qubit 的结支路坐标,
    # 之后每个浮动 qubit 追加一个共模列。接地单岛 → B 该行退化为选择行 (=1.0),
    # 全接地时 B = 单位矩阵 → C' 与 C_S 逐位相同 (向后兼容金值)。
    n_theta = len(qubits)
    n_cols = n_theta + sum(1 for q in qubits if len(q.islands) == 2)
    b_mat = [[0.0] * n_cols for _ in node_idx]
    row = 0
    sigma_col = n_theta
    for k, q in enumerate(qubits):
        if len(q.islands) == 1:
            b_mat[row][k] = 1.0                 # φ_a = θ_k
            row += 1
        else:
            b_mat[row][k] = 0.5                 # φ_a = σ_k + θ_k/2
            b_mat[row][sigma_col] = 1.0
            b_mat[row + 1][k] = -0.5            # φ_b = σ_k − θ_k/2
            b_mat[row + 1][sigma_col] = 1.0
            row += 2
            sigma_col += 1

    cprime = _congruence(sub, b_mat)                        # fF
    cinv = _invert_matrix(                                  # 法拉⁻¹, 含 σ 块
        [[v * _F_PER_FF for v in r] for r in cprime])

    qubit_results: list[QubitResult] = []
    for k, q in enumerate(qubits):
        cinv_kk = cinv[k][k]   # θθ 块的对角 (θ 列排在最前, 故下标就是 k)
        if cinv_kk <= 0:
            raise DesignDslError(
                f"qubit {q.name!r}: non-physical inverse capacitance "
                f"[C^-1]_ii={cinv_kk} (matrix not positive-definite?)")
        e_c = 0.5 * ELEM_CHARGE ** 2 * cinv_kk          # Joule
        e_j = q.e_j_joule()                              # Joule
        f01 = transmon_f01_hz(e_c, e_j)                  # Hz
        if f01 <= 0.0:
            # E_J/E_C < 1/8 → the leading-order transmon expansion gives a
            # non-physical f01<=0.  Fail fast here with a clear DesignDslError
            # (honours the documented Raises contract) rather than letting the
            # later coupling sqrt leak a bare ValueError, and rather than emitting
            # a meaningless QubitResult.
            raise DesignDslError(
                f"qubit {q.name!r}: non-transmon regime — perturbative f01="
                f"{f01 / 1e9:.4g} GHz <= 0 (E_J/E_C={e_j / e_c:.4g} < 1/8); the "
                f"leading-order transmon model is invalid (increase E_J / "
                f"decrease E_C: larger island capacitance or smaller L_J)")
        c_sigma = 1.0 / cinv_kk                          # Farad
        qubit_results.append(QubitResult(
            name=q.name,
            islands=q.islands,
            C_sigma_fF=c_sigma / _F_PER_FF,
            E_C_GHz=e_c / H_PLANCK / 1e9,
            E_J_GHz=e_j / H_PLANCK / 1e9,
            f01_GHz=f01 / 1e9,
            anharmonicity_MHz=-e_c / H_PLANCK / 1e6,
            EJ_over_EC=e_j / e_c,
        ))

    couplings: list[CouplingResult] = []
    for i in range(len(qubits)):
        for j in range(i + 1, len(qubits)):
            cinv_ij = cinv[i][j]
            denom = math.sqrt(cinv[i][i] * cinv[j][j])
            prefactor = abs(cinv_ij) / denom if denom > 0 else 0.0
            f_i = qubit_results[i].f01_GHz * 1e9
            f_j = qubit_results[j].f01_GHz * 1e9
            g_hz = 0.5 * prefactor * math.sqrt(f_i * f_j)
            # 支路坐标间的耦合电容: 两个接地单岛时 == |Maxwell offdiag| (逐位),
            # 差分-差分时 == ¼|c_aa + c_bb − c_ab − c_ba|。
            c_g_ff = abs(cprime[i][j])
            couplings.append(CouplingResult(
                qubit_a=qubits[i].name,
                qubit_b=qubits[j].name,
                C_g_fF=c_g_ff,
                g_MHz=g_hz / 1e6,
            ))

    return CircuitModelResult(
        qubits=tuple(qubit_results),
        couplings=tuple(couplings),
    )
