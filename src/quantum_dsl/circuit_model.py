# -*- coding: utf-8 -*-
"""电路模型 (契约「电路模型 / 子系统」): Maxwell 电容矩阵 → transmon Hamiltonian 参数。

逆电容 LOM, 结支路坐标形式 (审后搬运自 v3 ``dsl/circuit_model.py``, 口径
= docs/physics.md §8, 已对契约 golden 逐位复算):

* 取被引用岛的子矩阵 ``C_S`` (这里契约要求全部 label 被认领, 故 = 全矩阵),
  组结支路变换 ``φ = B ξ``: 接地单岛 θ=φ_a (选择列); 浮动双岛 θ=φ_a−φ_b
  外加共模 σ=(φ_a+φ_b)/2 (φ_a = σ+θ/2, φ_b = σ−θ/2)。
* ``C' = Bᵀ C_S B`` → **完整求逆取 θθ 块**: 共模电荷守恒 = 0 的正确约化只在
  完整逆里体现 (θθ 块的逆 ≠ 逆的 θθ 块; "删共模行列再求逆" = A⁻¹, 仅 B=0 时
  等价 — Yanay et al. npj QI 2020 Eq. 50–57 同口径)。
* ``C_Σ = 1/[C'⁻¹]_θθ,kk`` (dressed 有效电容, **不是** Maxwell 对角),
  ``E_C = e²/(2C_Σ)``, ``E_J = (ħ/2e)²/L_J``,
  ``f01 = (√(8E_C·E_J) − E_C)/h`` (**g 钉 f01 支**, 不是裸等离子频率 f_p ——
  文献真实分叉, docs/physics.md §8 已钉死), ``α = −E_C/h``。
* 耦合 ``β = |C'⁻¹_ij|/√(C'⁻¹_ii·C'⁻¹_jj)`` (纯几何, 与磁通/E_J 无关),
  ``g = ½·β·√(f01_i·f01_j)``。|·| 只适合输出耦合强度; 多路径/环路哈密顿量
  必须保留 C⁻¹_ij 符号 (将来做时别搬这里的 abs)。
* SQUID: ``E_J(φ) = (E_J1+E_J2)·hypot(cos πφ, d·sin πφ)``,
  ``d = (E_J1−E_J2)/(E_J1+E_J2)`` — 无奇点形式 (tan 写法在 φ=0.5 除零)。
* 防线 (docs/physics.md §10): 求逆前查反对称残差 ``‖C−Cᵀ‖_F/‖C‖_F`` (超 1e-6 即解
  本身有病, raise 而非对称化掩盖) 再 ``(C+Cᵀ)/2``; L_J/E_J 拒 nan/inf/≤0
  (``not (isfinite(v) and v>0)`` — nan 过得了 ``<=0``); 未被认领的 label
  禁止静默接地 (v3 实案: 静默接地删掉 25 MHz 中介耦合 / C_Σ 错 1.70×)。

* **无结导体** (2026-10-04, docs/physics.md §8.1) 必须显式声明处置, 否则照旧 raise:
  ``floating`` = 电中性浮岛, 先 Schur 消元; ``ports`` = 外接负载 R 的导体 (馈线 / 驱动线),
  AC 接地后删行列, 但它与各模的互容 C_kp 留作衰减: ``Γ = ω²·Σ_p C_kp²·R_p / C_eff``
  (Göppl 2008 Eq. 14–21 的 Norton 等效, ωC_κR ≪ 1); ``resonators`` = 传输线谐振腔的集总 LC 节点:
  ``(C_r, L_r) = resonator_lumped_lc(f_bare, Z0, mode)``, 网格里画的是整条线 (``drawn: full``) 时
  **用 C_r 换掉该 net 的 FEM 对地电容** (互容全留), 只画耦合爪 (``drawn: claw``) 时 C_r 叠加。
  腔与 qubit 同进逆电容 → 负载后 f_r = f_bare·√(C_r/C_eff)、g_qr 与 q–q 同式 (β 同口径)、
  χ = dispersive_shift_hz (精确 f01/f12)、κ/2π、Purcell ``Γ_P = κ·(g/Δ)²`` (Sete 2015 Eq. 2, 单模)。
* **精确 transmon 能级** (Koch 2007 Eq. 2.1): 电荷基 (2N+1) 三对角 ``4E_C n² − E_J/2 (|n⟩⟨n+1| + h.c.)``,
  n_g = 0, N = 30 → ``f01_exact`` / ``α_exact`` (α = −E_C 只是领头阶, E_J/E_C = 50 时精确值 −1.15 E_C)。
  渐近字段 ``f01_GHz`` / ``anharmonicity_MHz`` 是契约 golden, 不改; g 仍钉渐近 f01 支。

单位: 电容矩阵入参 **fF**; 结参数 **SI** (L_J 亨利, E_J/E_J1/E_J2 焦耳);
能量内部一律焦耳, 只在写结果时转 GHz/MHz。常数 SI-2019 精确, ħ 派生。
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from typing import Sequence

from .errors import QuantumDslError

__all__ = [
    "ELEM_CHARGE", "H_PLANCK", "HBAR", "FLUX_QUANTUM_REDUCED",
    "QubitResult", "CouplingResult", "ResonatorResult", "ReadoutResult", "CircuitModelResult",
    "solve_circuit_model", "resonator_lumped_lc", "dispersive_shift_hz", "transmon_levels_hz",
    "transmon_from_spectrum",
]

# --- 常数: SI-2019 精确 (e/h 是定义值); ħ/φ0 派生, 不硬编码舍入字面量 -----
ELEM_CHARGE = 1.602176634e-19          # C   (exact, SI-2019)
H_PLANCK = 6.62607015e-34              # J·s (exact, SI-2019)
HBAR = H_PLANCK / (2.0 * math.pi)      # J·s (derived)
FLUX_QUANTUM_REDUCED = HBAR / (2.0 * ELEM_CHARGE)  # Wb, φ0 = ħ/2e

_F_PER_FF = 1.0e-15
RESONATOR_MODES = frozenset({"half_wave", "quarter_wave"})
_JUNCTION_KEYS = frozenset({"name", "islands", "L_J", "E_J", "squid"})
_RESONATOR_KEYS = frozenset({"name", "net", "f_r", "Z0", "mode", "drawn"})
_PORT_KEYS = frozenset({"name", "net", "R"})
_SQUID_KEYS = frozenset({"E_J1", "E_J2", "flux"})


@dataclass(frozen=True)
class QubitResult:
    """一个 transmon 的派生 Hamiltonian 参数 (单位见字段名后缀)。"""

    name: str
    islands: tuple[str, ...]
    C_sigma_fF: float         # 有效结电容 1/[C'⁻¹]_θθ,kk
    E_C_GHz: float
    E_J_GHz: float
    f01_GHz: float
    anharmonicity_MHz: float  # α = −E_C (负)
    EJ_over_EC: float         # transmon 有效域判据 (微扰式要求 ≫ 1)
    f01_exact_GHz: float = math.nan            # 电荷基精确对角化 (n_g = 0)
    anharmonicity_exact_MHz: float = math.nan  # f12 − f01, 精确
    T1_port_us: float = math.inf               # 经 ports 直接辐射的 T1 (无 port = inf)


@dataclass(frozen=True)
class CouplingResult:
    """一对 qubit 的电容耦合。β 纯几何 (无量纲), g = ½·β·√(f01_a·f01_b)。"""

    qubit_a: str
    qubit_b: str
    beta: float
    g_MHz: float


@dataclass(frozen=True)
class ResonatorResult:
    """传输线谐振腔的集总 LC 模。f_r 是负载后 (逆电容 dressed) 的频率, κ 是 κ/2π。"""

    name: str
    net: str
    C_r_fF: float             # TL 等效电容 (resonator_lumped_lc)
    L_r_nH: float
    Z0_ohm: float
    f_bare_GHz: float         # 画出那条线的裸 TL 频率
    f_r_GHz: float            # 1/(2π√(L_r·C_eff)), C_eff = 1/[C'⁻¹]_rr
    kappa_MHz: float          # κ/2π 经 ports (Norton, ωC_κR ≪ 1); 无 port = 0
    C_gnd_fem_over_tl: float  # FEM 对地电容 / 线的静电容 2·C_r —— drawn: full 时应 ≈ 1


@dataclass(frozen=True)
class ReadoutResult:
    """qubit–腔对: g 与 q–q 同式 (渐近 f01 支), χ = 单边 cavity pull (Zhu 非 RWA 三能级, 精确 f01/f12),
    Purcell = 单模 κ(g/Δ)²。"""

    qubit: str
    resonator: str
    beta: float
    g_MHz: float
    chi_MHz: float
    T1_purcell_us: float


@dataclass(frozen=True)
class CircuitModelResult:
    qubits: tuple[QubitResult, ...]
    couplings: tuple[CouplingResult, ...]
    method: str = "lumped_oscillator_inverse_cap"
    resonators: tuple[ResonatorResult, ...] = ()
    readout: tuple[ReadoutResult, ...] = ()


# ---------------------------------------------------------------------------
# closed-form helpers
# ---------------------------------------------------------------------------

def transmon_f01_hz(e_c_joule: float, e_j_joule: float) -> float:
    """f01 = (√(8·E_C·E_J) − E_C)/h (Hz)。E_C/E_J 焦耳。"""
    return (math.sqrt(8.0 * e_c_joule * e_j_joule) - e_c_joule) / H_PLANCK


def transmon_levels_hz(e_c_joule: float, e_j_joule: float,
                       n_cut: int = 30) -> tuple[float, float]:
    """精确 (f01, f12) Hz: 电荷基 ``H = 4E_C n² − (E_J/2)(|n⟩⟨n+1| + h.c.)``, n ∈ [−N, N], n_g = 0
    (Koch 2007 Eq. 2.1; transmon 域电荷色散可忽略)。E_J = 0 → 能级 0, 4E_C, 4E_C (n = ±1 简并)。
    numpy 惰性 import (``import quantum_dsl`` 不拉起它)。"""
    import numpy as np

    n = np.arange(-n_cut, n_cut + 1, dtype=float)
    off = np.full(2 * n_cut, -0.5 * e_j_joule / H_PLANCK)
    e = np.linalg.eigvalsh(np.diag(4.0 * e_c_joule / H_PLANCK * n * n)
                           + np.diag(off, 1) + np.diag(off, -1))
    return float(e[1] - e[0]), float(e[2] - e[1])


def transmon_from_spectrum(f01_hz: float, alpha_hz: float,
                           ratio_bounds: tuple[float, float] = (2.0, 2000.0)) -> tuple[float, float]:
    """``transmon_levels_hz`` 的逆: 精确 (f01, α) Hz → (E_C, E_J) 焦耳 (综合的第 0 步: 目标 C_Σ* = e²/2E_C 与结的 E_J*)。

    能级对 E_C 一次齐次 ⇒ α/f01 只是 r = E_J/E_C 的函数 (r ↑ 单调趋向 0⁻) → 对 r 一维对数二分,
    再按 f01 定 E_C。目标比值落在 ``ratio_bounds`` 的 r 区间外 (非 transmon 区 / α ≥ 0) → raise。"""
    if not (math.isfinite(f01_hz) and f01_hz > 0 and math.isfinite(alpha_hz) and alpha_hz < 0):
        raise QuantumDslError(f"transmon_from_spectrum needs f01 > 0 and alpha < 0 (Hz), "
                              f"got {f01_hz!r} / {alpha_hz!r}")

    def shape(r):                                    # E_C = h·1 Hz 时的 (f01, α/f01)
        f01, f12 = transmon_levels_hz(H_PLANCK, r * H_PLANCK)
        return f01, (f12 - f01) / f01

    want = alpha_hz / f01_hz
    lo, hi = ratio_bounds
    if not shape(lo)[1] <= want <= shape(hi)[1]:
        raise QuantumDslError(
            f"transmon_from_spectrum: alpha/f01 = {want:.4g} is outside the transmon range "
            f"[{shape(lo)[1]:.4g}, {shape(hi)[1]:.4g}] (E_J/E_C in {list(ratio_bounds)})")
    while hi / lo - 1 > 1e-13:
        mid = math.sqrt(lo * hi)
        lo, hi = (mid, hi) if shape(mid)[1] < want else (lo, mid)
    r = math.sqrt(lo * hi)
    e_c = H_PLANCK * f01_hz / shape(r)[0]
    return e_c, r * e_c


def resonator_lumped_lc(f_res_hz: float, z0_ohm: float,
                        mode: str = "half_wave") -> tuple[float, float]:
    """分布式 TL 谐振器 → 等效集总 (C_r 法拉, L_r 亨利)。

    ``C_r = π/(2·ω_r·Z0)``, ``L_r = 1/(ω_r²·C_r)``, ω_r 用 **裸** 频率。
    λ/4 在同一共振频率下等效电容是 λ/2 的 **一半** (电感因此加倍) ——
    方向是 ``C_r /= 2``, 别记反 (共振频率不变, 子系统测试锚了它)。
    """
    if not (math.isfinite(f_res_hz) and f_res_hz > 0):
        raise QuantumDslError(f"resonator f_res must be > 0 Hz, got {f_res_hz}")
    if not (math.isfinite(z0_ohm) and z0_ohm > 0):
        raise QuantumDslError(f"resonator Z0 must be > 0 ohm, got {z0_ohm}")
    if mode not in RESONATOR_MODES:
        raise QuantumDslError(
            f"resonator mode {mode!r} is not one of {sorted(RESONATOR_MODES)}")
    omega = 2.0 * math.pi * f_res_hz
    c_r = 0.5 * math.pi / (omega * z0_ohm)
    l_r = 1.0 / (omega * omega * c_r)
    if mode == "quarter_wave":
        c_r /= 2.0
        l_r *= 2.0
    return c_r, l_r


def dispersive_shift_hz(g_hz: float, f_res_hz: float,
                        f01_hz: float, f12_hz: float) -> float:
    """色散位移 χ — **非 RWA 三能级二阶微扰** (Zhu et al. arXiv:1210.1605
    Eq. (11)–(14) 取三能级; 含反旋转分母 1/(ω+ω_r))。

    ⚠ 引文注意: **不要**引成 Koch 2007 (3.9)/(3.10) — Koch 原式是 RWA 版
    (无 ω+ω_r 项), qiskit-metal 源码注释就是这处误引的源头 (docs/physics.md §8)。

        chi_0 = −2g²·f01/(f01² − f_r²)                      (|0⟩ 的 pull)
        chi_1 = g²·(1/(f01−f_r) − 2/(f12−f_r)
                    + 1/(f01+f_r) − 2/(f12+f_r))            (|1⟩ 的 pull)
        χ = (chi_1 − chi_0)/2

    返回的是 **单边 cavity pull** χ, 不是总劈裂 2χ (消费端要 2χ 自己乘 2)。
    公式对频率一次齐次 (g²/ω), 喂 Hz 得 Hz, 无 2π 因子。
    微扰式要求 |f01 − f_res| ≫ g; 精确共振时分母为零 → raise。
    """
    if f01_hz == f_res_hz or f12_hz == f_res_hz:
        raise QuantumDslError(
            f"dispersive shift: perturbative formula diverges on resonance "
            f"(f01={f01_hz:.6g}, f12={f12_hz:.6g}, f_res={f_res_hz:.6g} Hz) — "
            f"it needs |f01 - f_res| >> g; use numerical diagonalisation there")
    g_sq = g_hz * g_hz
    chi_0 = -2.0 * g_sq * f01_hz / (f01_hz ** 2 - f_res_hz ** 2)
    chi_1 = g_sq * (1.0 / (f01_hz - f_res_hz) - 2.0 / (f12_hz - f_res_hz)
                    + 1.0 / (f01_hz + f_res_hz) - 2.0 / (f12_hz + f_res_hz))
    return (chi_1 - chi_0) / 2.0


# ---------------------------------------------------------------------------
# tiny matrix helpers (pure python — 矩阵 ≤ ~10×10)
# ---------------------------------------------------------------------------

def _invert_matrix(mat: Sequence[Sequence[float]]) -> list[list[float]]:
    """Gauss-Jordan 求逆 (partial pivoting)。奇异判据尺度相对 (绝对阈值对
    法拉级 ~1e-15 输入毫无意义): pivot ≤ 1e-12·max|C_ij| 即判不可逆。"""
    n = len(mat)
    if n == 0 or any(len(row) != n for row in mat):
        raise QuantumDslError("matrix must be square and non-empty")
    aug = [[float(mat[i][j]) for j in range(n)]
           + [1.0 if i == k else 0.0 for k in range(n)]
           for i in range(n)]
    scale = max((abs(mat[i][j]) for i in range(n) for j in range(n)),
                default=0.0)
    sing_tol = 1e-12 * scale
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) <= sing_tol:
            raise QuantumDslError(
                f"capacitance matrix is singular or ill-conditioned — cannot "
                f"invert (pivot {abs(aug[pivot][col]):.3e} <= tol "
                f"{sing_tol:.3e}); check that islands are distinct conductors "
                f"(a floating pair also needs some capacitance to ground, "
                f"else the common mode is a gauge zero mode — pick a datum)")
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
    """``Bᵀ M B``。B 为选择矩阵 (全接地单岛) 时与 M 子块逐位相同 (额外项
    是精确 0.0) — 向后逐位保住 golden。"""
    n = len(mat)
    ncol = len(b[0]) if b else 0
    return [[sum(b[p][i] * mat[p][q] * b[q][j]
                 for p in range(n) for q in range(n))
             for j in range(ncol)] for i in range(ncol)]


# ---------------------------------------------------------------------------
# junction dict 解析 (契约「电路模型」: dict 入参, L_J / E_J / squid 三选一)
# ---------------------------------------------------------------------------

def _junction_e_j_joule(j: dict) -> float:
    """校验一个 junction dict 并返回有效 E_J (焦耳)。"""
    name = j.get("name")
    unknown = sorted(set(j) - _JUNCTION_KEYS)
    if unknown:
        raise QuantumDslError(
            f"junction {name!r}: unknown key(s) {unknown} "
            f"(known: {sorted(_JUNCTION_KEYS)})")
    n_given = sum(k in j for k in ("L_J", "E_J", "squid"))
    if n_given != 1:
        raise QuantumDslError(
            f"junction {name!r}: set exactly one of L_J (henry) / E_J (joule) "
            f"/ squid {{E_J1, E_J2, flux}} (joule), got {n_given}")
    if "L_J" in j:
        l_j = j["L_J"]
        # isfinite 必须查: nan 过得了 <=0, 下游 f01<=0 对 nan 也是 False,
        # 会静默写出一整条 nan 结果 (1e400 溢出成 inf 同理)。
        if not (isinstance(l_j, (int, float)) and not isinstance(l_j, bool)
                and math.isfinite(l_j) and l_j > 0):
            raise QuantumDslError(
                f"junction {name!r}: L_J must be > 0 and finite (henry), "
                f"got {l_j!r}")
        return FLUX_QUANTUM_REDUCED ** 2 / l_j
    if "E_J" in j:
        e_j = j["E_J"]
        if not (isinstance(e_j, (int, float)) and not isinstance(e_j, bool)
                and math.isfinite(e_j) and e_j > 0):
            raise QuantumDslError(
                f"junction {name!r}: E_J must be > 0 and finite (joule), "
                f"got {e_j!r}")
        return e_j
    squid = j["squid"]
    if not isinstance(squid, dict):
        raise QuantumDslError(f"junction {name!r}: squid must be a mapping")
    unknown = sorted(set(squid) - _SQUID_KEYS)
    if unknown:
        raise QuantumDslError(
            f"junction {name!r}: unknown squid key(s) {unknown} "
            f"(known: {sorted(_SQUID_KEYS)})")
    if "E_J1" not in squid or "E_J2" not in squid:
        raise QuantumDslError(
            f"junction {name!r}: a SQUID needs BOTH E_J1 and E_J2 (joule) — "
            f"one branch alone is a single junction, use E_J")
    for key in ("E_J1", "E_J2"):
        v = squid[key]
        if not (isinstance(v, (int, float)) and not isinstance(v, bool)
                and math.isfinite(v) and v > 0):
            raise QuantumDslError(
                f"junction {name!r}: {key} must be > 0 and finite (joule), "
                f"got {v!r}")
    flux = squid.get("flux", 0.0)
    if not (isinstance(flux, (int, float)) and not isinstance(flux, bool)
            and math.isfinite(flux)):
        raise QuantumDslError(
            f"junction {name!r}: flux must be a finite number (Phi/Phi0), "
            f"got {flux!r}")
    e_sum = squid["E_J1"] + squid["E_J2"]
    asym = (squid["E_J2"] - squid["E_J1"]) / e_sum
    phase = math.pi * flux
    # 无奇点恒等形式 E_JΣ·√(cos²+d²sin²): 教科书 |cos|·√(1+d²tan²) 在
    # φ=0.5 是 0×∞ → nan。φ=0 → E_JΣ; φ=0.5 → E_JΣ|d| = |E_J1−E_J2|。
    return e_sum * math.hypot(math.cos(phase), asym * math.sin(phase))


# ---------------------------------------------------------------------------
# the solve
# ---------------------------------------------------------------------------

def _entries(items, keys, what) -> list[dict]:
    """resonators / ports 条目的通用校验: dict、键白名单、name 与 net 是非空字符串。"""
    out = []
    for e in items:
        if not isinstance(e, dict):
            raise QuantumDslError(f"{what} entries must be dicts, got {e!r}")
        unknown = sorted(set(e) - keys)
        if unknown:
            raise QuantumDslError(f"{what} {e.get('name')!r}: unknown key(s) {unknown} (known: {sorted(keys)})")
        for k in ("name", "net"):
            if not isinstance(e.get(k), str) or not e[k]:
                raise QuantumDslError(f"{what} entry needs a non-empty string {k!r}, got {e!r}")
        out.append(e)
    return out


def _positive(v, what) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not (math.isfinite(v) and v > 0):
        raise QuantumDslError(f"{what} must be > 0 and finite (SI), got {v!r}")
    return float(v)


def solve_circuit_model(labels, maxwell_fF, junctions, resonators=(), ports=(),
                        floating=()) -> CircuitModelResult:
    """Maxwell 电容矩阵 (fF) + 结输入 → transmon 参数 + 成对耦合 (契约「电路模型」/「读出链路」)。

    Args:
        labels:     矩阵行/列的岛名 (顺序 = 行序), = .geo Physical 名的
                    component 段。
        maxwell_fF: Maxwell 电容矩阵 (fF, +对角 −非对角), 与 labels 同序。
        junctions:  dict 列表: ``name``, ``islands`` (1 个 = 接地 transmon,
                    2 个 = 浮动/差分, 结桥接两岛), 且 ``L_J`` (亨利) /
                    ``E_J`` (焦耳) / ``squid: {E_J1, E_J2, flux}`` 三选一。
        resonators: dict 列表 ``{name, net, f_r (Hz, 画出那条线的裸频率), Z0 (Ω),
                    mode: quarter_wave|half_wave, drawn: full|claw (默认 full)}``。
        ports:      dict 列表 ``{name, net, R (Ω)}``: 外接负载的导体 (直通馈线从耦合点看是 Z0/2)。
        floating:   net 名列表: 电中性浮岛, 先 Schur 消元。

    每个 label 必须被 **恰好一个** junction / resonator / port / floating 认领: 未认领 = 会被静默接地
    (v3 实案 C_Σ 错 1.70×) → raise。
    """
    if not junctions:
        raise QuantumDslError("solve_circuit_model needs >=1 junction")
    labels = tuple(labels)
    n = len(labels)
    if n == 0 or len(set(labels)) != n:
        raise QuantumDslError(f"labels must be non-empty and unique, got {labels}")
    if len(maxwell_fF) != n or any(len(row) != n for row in maxwell_fF):
        raise QuantumDslError(
            f"maxwell_fF must be {n}x{n} to match labels {labels}")
    for i in range(n):
        for jcol in range(n):
            if not math.isfinite(maxwell_fF[i][jcol]):
                raise QuantumDslError(
                    f"maxwell_fF[{i}][{jcol}] = {maxwell_fF[i][jcol]} is not "
                    f"finite — refusing a nan/inf matrix")

    # 防线 (physics.md §10 #6): 反对称残差超阈值 = 解本身有病, 不能靠对称化掩盖。
    asym = math.sqrt(sum((maxwell_fF[i][jc] - maxwell_fF[jc][i]) ** 2
                         for i in range(n) for jc in range(n)))
    norm = math.sqrt(sum(v * v for row in maxwell_fF for v in row))
    if norm > 0.0 and asym / norm > 1e-6:
        raise QuantumDslError(
            f"maxwell_fF asymmetry |C-C^T|/|C| = {asym / norm:.3e} > 1e-6 — "
            f"the solver output itself is suspect; do not mask it by "
            f"symmetrisation, fix the solve (mesh/convergence) instead")
    # 清理求解器的微小反对称残差 (非物理步骤)。
    c_sym = [[0.5 * (maxwell_fF[i][jc] + maxwell_fF[jc][i]) for jc in range(n)]
             for i in range(n)]

    # --- 无结导体 ①: floating = 电中性浮岛 → Schur 消元 (与 assemble 同一段代码) ------------
    floating = tuple(floating)
    bad = [f for f in floating if f not in labels]
    if bad or len(set(floating)) != len(floating):
        raise QuantumDslError(f"floating net(s) {bad or list(floating)} are not unique matrix labels "
                              f"(have: {', '.join(labels)})")
    if floating:
        from .assemble import assemble
        red = assemble([{"name": "chip", "labels": labels, "maxwell_fF": c_sym}],
                       keep=[lab for lab in labels if lab not in floating])
        labels, c_sym = red.labels, [list(r) for r in red.maxwell_fF]
        n = len(labels)

    idx = {lab: i for i, lab in enumerate(labels)}
    claimed: dict[int, str] = {}      # Maxwell 行 → 认领者 (结 / 腔 / port 共用一张表)
    names_seen: set[str] = set()

    def claim(net, who):
        if net not in idx:
            raise QuantumDslError(f"{who}: net {net!r} is not a matrix label (have: {', '.join(labels)})")
        if idx[net] in claimed:
            raise QuantumDslError(f"{who}: net {net!r} is already claimed by {claimed[idx[net]]!r} — "
                                  f"every conductor gets exactly one treatment")
        claimed[idx[net]] = who
        return idx[net]

    def unique_name(name, what):
        if not name or not isinstance(name, str) or name in names_seen:
            raise QuantumDslError(f"{what} name {name!r} must be a unique non-empty string "
                                  f"(qubits / resonators / ports share one namespace)")
        names_seen.add(name)

    # --- 无结导体 ②: ports = 外接负载 → AC 接地 (删行列), 互容留给衰减率 ----------------------
    port_mut: list[tuple[float, list[float]]] = []    # (R Ω, 每行对该 port 的互容 fF)
    for pt in _entries(ports, _PORT_KEYS, "port"):
        unique_name(pt["name"], "port")
        row_p = claim(pt["net"], f"port {pt['name']!r}")
        port_mut.append((_positive(pt.get("R"), f"port {pt['name']!r}: R"),
                         [-c_sym[x][row_p] for x in range(n)]))

    # --- 无结导体 ③: resonators = TL 等效 LC; drawn: full 时 C_r 换掉 FEM 对地电容 --------------
    res_parsed: list[tuple[str, str, int, float, float, float, float, float]] = []
    for rs in _entries(resonators, _RESONATOR_KEYS, "resonator"):
        name = rs["name"]
        unique_name(name, "resonator")
        row_r = claim(rs["net"], f"resonator {name!r}")
        if rs.get("mode") not in RESONATOR_MODES:
            raise QuantumDslError(f"resonator {name!r}: mode must be one of {sorted(RESONATOR_MODES)} "
                                  f"(λ/4 vs λ/2 halves C_r — no default), got {rs.get('mode')!r}")
        drawn = rs.get("drawn", "full")
        if drawn not in ("full", "claw"):
            raise QuantumDslError(f"resonator {name!r}: drawn must be full|claw, got {drawn!r}")
        f_bare = _positive(rs.get("f_r"), f"resonator {name!r}: f_r")
        z0 = _positive(rs.get("Z0"), f"resonator {name!r}: Z0")
        c_r, l_r = resonator_lumped_lc(f_bare, z0, rs["mode"])
        c_r_fF = c_r / _F_PER_FF
        gnd = sum(c_sym[row_r])                       # FEM 对地电容 = Maxwell 行和
        ratio = gnd / (2.0 * c_r_fF)                  # 线的静电容 c'l = 2·C_r (λ/2 与 λ/4 同)
        c_sym[row_r][row_r] += c_r_fF - (gnd if drawn == "full" else 0.0)
        if drawn == "full" and not 0.5 <= ratio <= 2.0:
            warnings.warn(
                f"resonator {name!r}: FEM ground capacitance of net {rs['net']!r} is {ratio:.3g}x the "
                f"TL line capacitance 2*C_r — drawn: full assumes the whole line is in the mesh; if only "
                f"the coupling claw is drawn, declare drawn: claw", stacklevel=2)
        res_parsed.append((name, rs["net"], row_r, c_r, l_r, z0, f_bare, ratio))

    node_idx: list[int] = []          # 子矩阵行 → Maxwell 行 (结岛按 junction 序, 再接腔)
    parsed: list[tuple[str, tuple[str, ...], float]] = []
    for j in junctions:
        if not isinstance(j, dict):
            raise QuantumDslError(f"junctions entries must be dicts, got {j!r}")
        name = j.get("name")
        unique_name(name, "junction")
        islands = tuple(j.get("islands") or ())
        if not 1 <= len(islands) <= 2:
            raise QuantumDslError(
                f"junction {name!r}: islands must name 1 (grounded) or 2 "
                f"(floating/differential) conductors, got {list(islands)}")
        for island in islands:
            node_idx.append(claim(island, f"junction {name!r}"))
        parsed.append((name, islands, _junction_e_j_joule(j)))
    node_idx += [r[2] for r in res_parsed]

    # 防线 (physics.md §10 #7): 未认领 label 禁止静默接地。
    unclaimed = [lab for i, lab in enumerate(labels) if i not in claimed]
    if unclaimed:
        raise QuantumDslError(
            f"label(s) {unclaimed} are not claimed by any junction — refusing "
            f"to silently ground them (that deletes real mediated coupling); "
            f"declare them in circuit_model as resonators / ports / floating, "
            f"Schur-eliminate them via assemble(cells, keep=...) or drop the row/column")

    sub = [[c_sym[a][b] for b in node_idx] for a in node_idx]

    # φ = B ξ, ξ = (θ_0..θ_{nq-1}, 腔…, σ…): 接地单岛 / 腔 → 选择列; 浮动双岛 →
    # φ_a = σ+θ/2, φ_b = σ−θ/2。全接地时 B = 单位阵 → C' 与 C_S 逐位相同。
    n_theta = len(parsed)
    n_res = len(res_parsed)
    n_sigma = sum(1 for _, islands, _ in parsed if len(islands) == 2)
    n_cols = n_theta + n_res + n_sigma
    b_mat = [[0.0] * n_cols for _ in node_idx]
    row = 0
    sigma_col = n_theta + n_res
    for k, (_, islands, _) in enumerate(parsed):
        if len(islands) == 1:
            b_mat[row][k] = 1.0
            row += 1
        else:
            b_mat[row][k] = 0.5
            b_mat[row][sigma_col] = 1.0
            b_mat[row + 1][k] = -0.5
            b_mat[row + 1][sigma_col] = 1.0
            row += 2
            sigma_col += 1
    for k in range(n_res):
        b_mat[row + k][n_theta + k] = 1.0

    cprime = _congruence(sub, b_mat)                 # fF
    cinv = _invert_matrix(                           # F⁻¹, 含 σ 块
        [[v * _F_PER_FF for v in r] for r in cprime])

    def decay(k, f_hz):
        """模 k (B 的列) 经全部 port 的能量衰减率 Γ (1/s): Norton ωC_κR ≪ 1, Γ = ω²·ΣC_kp²·R / C_eff。"""
        tot = 0.0
        for r_ohm, mut in port_mut:
            c_kp = sum(b_mat[rw][k] * mut[node_idx[rw]] for rw in range(len(node_idx))) * _F_PER_FF
            tot += c_kp * c_kp * r_ohm
        return (2.0 * math.pi * f_hz) ** 2 * tot * cinv[k][k]

    qubit_results: list[QubitResult] = []
    levels: list[tuple[float, float]] = []           # 精确 (f01, f12) Hz
    for k, (name, islands, e_j) in enumerate(parsed):
        cinv_kk = cinv[k][k]        # θ 列排最前, θθ 对角下标就是 k
        if cinv_kk <= 0:
            raise QuantumDslError(
                f"qubit {name!r}: non-physical inverse capacitance "
                f"[C'^-1]_kk={cinv_kk} (matrix not positive-definite?)")
        e_c = 0.5 * ELEM_CHARGE ** 2 * cinv_kk       # Joule
        f01 = transmon_f01_hz(e_c, e_j)              # Hz
        if f01 <= 0.0:
            raise QuantumDslError(
                f"qubit {name!r}: non-transmon regime — perturbative f01="
                f"{f01 / 1e9:.4g} GHz <= 0 (E_J/E_C={e_j / e_c:.4g} < 1/8); "
                f"increase E_J / decrease E_C (or, for a SQUID, move flux "
                f"away from 0.5 Phi0 where E_J,eff -> 0)")
        c_sigma = 1.0 / cinv_kk                      # Farad
        f01_x, f12_x = transmon_levels_hz(e_c, e_j)
        levels.append((f01_x, f12_x))
        gamma = decay(k, f01_x)
        qubit_results.append(QubitResult(
            name=name,
            islands=islands,
            C_sigma_fF=c_sigma / _F_PER_FF,
            E_C_GHz=e_c / H_PLANCK / 1e9,
            E_J_GHz=e_j / H_PLANCK / 1e9,
            f01_GHz=f01 / 1e9,
            anharmonicity_MHz=-e_c / H_PLANCK / 1e6,
            EJ_over_EC=e_j / e_c,
            f01_exact_GHz=f01_x / 1e9,
            anharmonicity_exact_MHz=(f12_x - f01_x) / 1e6,
            T1_port_us=1e6 / gamma if gamma > 0 else math.inf,
        ))

    couplings: list[CouplingResult] = []
    for i in range(len(parsed)):
        for jq in range(i + 1, len(parsed)):
            denom = math.sqrt(cinv[i][i] * cinv[jq][jq])
            beta = abs(cinv[i][jq]) / denom if denom > 0 else 0.0
            f_i = qubit_results[i].f01_GHz * 1e9
            f_j = qubit_results[jq].f01_GHz * 1e9
            g_hz = 0.5 * beta * math.sqrt(f_i * f_j)
            couplings.append(CouplingResult(
                qubit_a=parsed[i][0],
                qubit_b=parsed[jq][0],
                beta=beta,
                g_MHz=g_hz / 1e6,
            ))

    res_results: list[ResonatorResult] = []
    readout: list[ReadoutResult] = []
    for jr, (name, net, _, c_r, l_r, z0, f_bare, ratio) in enumerate(res_parsed):
        kr = n_theta + jr
        f_r = 1.0 / (2.0 * math.pi * math.sqrt(l_r / cinv[kr][kr]))
        kappa = decay(kr, f_r)                        # rad/s
        res_results.append(ResonatorResult(
            name=name, net=net, C_r_fF=c_r / _F_PER_FF, L_r_nH=l_r * 1e9, Z0_ohm=z0,
            f_bare_GHz=f_bare / 1e9, f_r_GHz=f_r / 1e9, kappa_MHz=kappa / (2.0 * math.pi) / 1e6,
            C_gnd_fem_over_tl=ratio))
        for k, q in enumerate(qubit_results):
            beta = abs(cinv[k][kr]) / math.sqrt(cinv[k][k] * cinv[kr][kr])
            g_hz = 0.5 * beta * math.sqrt(q.f01_GHz * 1e9 * f_r)
            f01_x, f12_x = levels[k]
            chi = dispersive_shift_hz(g_hz, f_r, f01_x, f12_x)
            gamma_p = kappa * (g_hz / (f01_x - f_r)) ** 2   # 单模 Purcell (Sete 2015 Eq. 2)
            readout.append(ReadoutResult(
                qubit=q.name, resonator=name, beta=beta, g_MHz=g_hz / 1e6, chi_MHz=chi / 1e6,
                T1_purcell_us=1e6 / gamma_p if gamma_p > 0 else math.inf))

    return CircuitModelResult(qubits=tuple(qubit_results),
                              couplings=tuple(couplings),
                              resonators=tuple(res_results),
                              readout=tuple(readout))
