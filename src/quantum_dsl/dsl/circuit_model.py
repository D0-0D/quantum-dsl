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
        E_J,k  = (ħ/2e)² / L_J,k   (或直接给定, 或 SQUID 见下)  (约瑟夫森能, 焦耳)
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

    **磁通可调 (可非对称) SQUID** (Koch et al. 2007, PRA 76, 042319 的标准结果):
    结元件是两个并联结 E_J1/E_J2 时, 有效约瑟夫森能随 **归一化** 外磁通 Φ/Φ0
    (磁通量子数, 无量纲) 变化
        E_JΣ = E_J1 + E_J2,   d = (E_J2 − E_J1)/(E_J1 + E_J2) ∈ [−1, 1]
        E_J,eff(Φ) = E_JΣ · |cos(πΦ/Φ0)| · sqrt(1 + d² tan²(πΦ/Φ0))
                   ≡ E_JΣ · sqrt(cos²(πΦ/Φ0) + d² sin²(πΦ/Φ0))
    **实现一律用下面那个恒等形式**: tan 在 Φ=0.5Φ0 处发散, 上式在那里是 0×∞ → nan,
    而无奇点形式代数上完全等价且处处有限。检查点: Φ=0 → E_JΣ; d=0 → E_JΣ|cos|,
    在 Φ=0.5Φ0 归零; d≠0 时 Φ=0.5Φ0 不归零, 极小值 = E_JΣ|d|。周期为 Φ0
    (flux=1.2 合法, 与 0.2 同值)。E_J,eff 趋零 → E_J/E_C < 1/8, 走既有的
    "non-transmon regime" 报错路径 (不新造失败模式)。

    **未被任何 qubit 引用的 Terminal 一律视作接地电极** (固定电势) —— 不进入 C_S,
    其电容已折进被引用岛的对角线。已知局限: 一条 **浮动耦合总线** (galvanic 隔离、
    但物理上不该接地的导体) 同样会被接地, 正确处理需要对该节点做 Schur 补消元
    (而不是像 σ 那样简单丢弃), 目前不支持。

    **结电容 C_j** (P0-E): 约瑟夫森结的两片电极自身是个平板电容, 并在 **结支路** 上
    (与结并联)。θ_k **就是** 结支路坐标, 所以它就是 C' 的 θθ 对角上的一项:
        C'_θθ,kk += C_j,k        —— 在 **求逆之前**
    ⚠ **不能** 求逆后再标量加 (``C_Σ = 1/[C'⁻¹]_θθ + C_j``, 老 LOM
    ``lumped_capacitive.py:320`` 的 ``Cq = tCSq + CJ``): 那只对 **孤立** 结成立; 耦合
    系统里 C_j 必须进矩阵才能参与耦合的重整化 (New LOM 就是折进电容图,
    ``lom_core_analysis.py:228`` 的 ``_cj_dict_to_adj_list``)。

    「θθ 对角 += C_j, 其余不动」与 New LOM 的 **node 基** 折入 **恒等** —— node 基是
    ``ΔC_aa = ΔC_bb = +C_j``, ``ΔC_ab = ΔC_ba = −C_j``, 过 ``C' = BᵀΔC B`` (双岛:
    B[a][k]=+0.5, B[b][k]=−0.5, σ 列全 1):
        θθ: 0.25C_j + 0.25C_j + 0.25C_j + 0.25C_j = C_j
        σσ: C_j + C_j − C_j − C_j = 0
        θσ: 0.5C_j − 0.5C_j − 0.5C_j + 0.5C_j = 0
    接地单岛 (B[a][k]=1, 另一端就是地): 直接 C_j。故一行搞定, 且 **不需要** 知道 cell
    的节点拓扑。C_j 默认 0.0 且用 ``if q.C_j:`` 短路 → 旧结果逐位不动。

    (顺带: 只有 **一个** qubit 带 C_j 时, Sherman-Morrison 给
    ``[C'_new⁻¹]_kk = 1/(1/[C'⁻¹]_kk + C_j)``, 即此时标量式与矩阵式的 **对角** 恰好
    重合 —— 但非对角 (→ g) 仍只有矩阵式才对; 多个 qubit 同时带 C_j 时连对角也不再
    重合。所以 ``C_sigma_geometric_fF`` 是另求一次不含 C_j 的逆得到的, 不是减法。)

    **TL_RESONATOR 与色散位移 χ** (P0-D, 对标 ``lom_core_analysis.py:841-849``):
    谐振器 **不进 FEM** —— 它的耦合爪子是真实导体, 已经是电容矩阵里的一个 terminal;
    分布式传输线本身用已知的 (f_res, Z0, mode) 折成等效集总 LC (对照
    ``lumped_capacitive.py:238-250``):
        ω_r = 2π f_res,  C_r = π/(2 ω_r Z0),  L_r = 1/(ω_r² C_r)
        λ/4: 同频率下等效电容是 λ/2 的一半 → **C_r /= 2, L_r *= 2** (源码逐字如此)
    谐振器进解算的方式与 qubit 的 θ 同构: 它是 ``B`` 里的一个 **独立选择列**, 解析 C_r
    加在它的对角上 (自电容 = 解析 C_r + 爪子实测电容 = **加载**), 于是
        C_r,eff = 1/[C'⁻¹]_rr,  f_loaded = 1/(2π√(L_r C_r,eff)) < f_bare
        g_qr/2π = ½·|[C'⁻¹]_qr|/√([C'⁻¹]_qq[C'⁻¹]_rr)·√(f01·f_res)   (同 qubit-qubit)
        χ = 2·chi(g, f_res, f01, f12),  f12 = f01 + α   (Koch 2007 eq. (3.9)/(3.10),
            逐行对照 ``lumped_capacitive.py:133-158``, 调用点 ``:402``)

    ⚠ **f_res 的裸/dressed 语义陷阱** (spec §11 R5): New LOM 的 ``f_res`` 是 **dressed**
    频率 (tutorial 4.05 注释 ``resonator dressed frequency``), 老 LOM 的 ``freq_readout``
    是 **裸** 频率。本模块取 **裸频率** (与老 LOM 一致, 加载效应由拼装矩阵自然给出),
    结果里 ``f_bare_GHz`` 与 ``f_loaded_GHz`` **都输出**; g 与 χ 一律用裸频率 (与
    ``lumped_capacitive.py`` 的 ``wr`` 同约定), ``f_loaded`` 是爪子加载量的诊断值。
    ⚠ **χ 是微扰式** (spec §6 的取舍 + §11 R6): 结果标 ``chi_method="perturbative"``。
    Koch 的二阶微扰要求 |Δ| = |f01 − f_res| ≫ g; 强耦合/近共振时它不如 (New LOM 走的)
    scqubits 数值对角化 —— 本仓不引 numpy/scipy/qutip, 故此处不追那个精度。

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
from .schema import RESONATOR_MODES


__all__ = [
    "JunctionInput",
    "ResonatorInput",
    "QubitResult",
    "CouplingResult",
    "ResonatorResult",
    "QubitResonatorCoupling",
    "CircuitModelResult",
    "solve_circuit_model",
    "charging_energy_joule",
    "josephson_energy_joule",
    "transmon_f01_hz",
    "resonator_lumped_lc",
    "dispersive_shift_hz",
    "RESONATOR_MODES",
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
    """一个量子比特的输入: 岛 (Terminal 组名) + 约瑟夫森元件 (L_J / E_J / SQUID)。

    结元件三种写法 **恰选一种** (sidecar 里对应 ``L_J:`` / ``E_J:`` / ``squid:``):
    单结电感 ``L_J``、单结能量 ``E_J``、或磁通可调 SQUID ``E_J1``+``E_J2``(+``flux``)。

    Fields:
        name:    量子比特名 (结果里 qubit 的标识)。
        islands: 引用的导体岛 = ``capacitance.terminals[].group`` 组名 (已 sanitize 的
                 ``{component}_{primitive}_sfs``)。1 个岛 = **接地 transmon** (结跨岛
                 与地); 2 个岛 = **浮动/差分 transmon** (结跨两焊盘, 顺序 (a, b) 定义
                 θ = φ_a − φ_b, 符号不影响任何输出量)。>2 个岛需要多个结, 不支持。
        L_J:     约瑟夫森电感, **亨利 (SI)**; 与 E_J / SQUID 三选一。
        E_J:     约瑟夫森能, **焦耳 (SI)**; 与 L_J / SQUID 三选一。
        E_J1:    SQUID 第一个结的约瑟夫森能, **焦耳 (SI)**; 与 E_J2 成对出现。
        E_J2:    SQUID 第二个结的约瑟夫森能, **焦耳 (SI)**; 与 E_J1 成对出现。
                 E_J1≠E_J2 即非对称 SQUID (工艺常态), 不对称度
                 d = (E_J2−E_J1)/(E_J1+E_J2)。
        flux:    外磁通, **归一化为磁通量子数 Φ/Φ0 (无量纲)**, 默认 0.0 (=零磁通,
                 E_J,eff 取最大值 E_JΣ)。任意实数, 周期 1。只对 SQUID 有意义 ——
                 与 L_J/E_J 同时给非零 flux 会报错 (免得静默无效)。
        C_j:     结电容 (结电极自身的平板电容), **法拉 (SI)**, 与 L_J 用亨利同风格。
                 并在结支路上 → C_Σ,eff = 1/[C'⁻¹]_θθ + C_j (见模块 docstring)。
                 **默认 0.0** (不静默移动任何既有数值); 老 LOM / New LOM 的实务默认
                 是 2 fF (``cj_dict={('pad_top_Q1','pad_bot_Q1'): 2}``), 不写就是
                 把结电容当 0 → E_C 系统性偏高, 由 sidecar 显式声明。
    """

    name: str
    islands: tuple[str, ...]
    L_J: float | None = None
    E_J: float | None = None
    E_J1: float | None = None
    E_J2: float | None = None
    flux: float = 0.0
    C_j: float = 0.0

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise DesignDslError("JunctionInput.name must be a non-empty string")
        if not self.islands:
            raise DesignDslError(
                f"JunctionInput {self.name!r}: islands must be non-empty")
        is_squid = self.E_J1 is not None or self.E_J2 is not None
        if (self.L_J is not None) + (self.E_J is not None) + is_squid != 1:
            raise DesignDslError(
                f"JunctionInput {self.name!r}: set exactly one of L_J / E_J / "
                f"squid (E_J1+E_J2)")
        # 必须用 isfinite: ``nan <= 0`` 是 False, 光判 <= 0 会放行 nan/inf, 而下游
        # ``f01 <= 0`` 对 nan 同样是 False → 绕过 non-transmon 守卫, 静默写出一整条
        # nan 的结果。inf 同理。
        if self.L_J is not None and not (math.isfinite(self.L_J) and self.L_J > 0):
            raise DesignDslError(
                f"JunctionInput {self.name!r}: L_J must be > 0 and finite "
                f"(henry), got {self.L_J}")
        if self.E_J is not None and not (math.isfinite(self.E_J) and self.E_J > 0):
            raise DesignDslError(
                f"JunctionInput {self.name!r}: E_J must be > 0 and finite "
                f"(joule), got {self.E_J}")
        if is_squid and (self.E_J1 is None or self.E_J2 is None):
            raise DesignDslError(
                f"JunctionInput {self.name!r}: a SQUID needs BOTH E_J1 and E_J2 "
                f"(joule) — one branch alone is a single junction, use E_J")
        # nan/inf 必须挡: ``nan <= 0`` 是 False, 会一路静默算出 nan 的 f01/g。
        for label, value in (("E_J1", self.E_J1), ("E_J2", self.E_J2)):
            if value is not None and not (math.isfinite(value) and value > 0):
                raise DesignDslError(
                    f"JunctionInput {self.name!r}: {label} must be > 0 (joule), "
                    f"got {value}")
        if not math.isfinite(self.flux):
            raise DesignDslError(
                f"JunctionInput {self.name!r}: flux must be a finite number "
                f"(Phi/Phi0), got {self.flux}")
        if self.flux and not is_squid:
            raise DesignDslError(
                f"JunctionInput {self.name!r}: flux={self.flux} only applies to a "
                f"SQUID (E_J1+E_J2) — a single L_J/E_J junction is not tunable")
        # 同上的 isfinite 理由: nan 过得了 ``< 0``, 之后 C_Σ+nan → 整条结果静默变
        # nan (f01<=0 守卫对 nan 也是 False)。0 是合法值 (= 忽略结电容, 既有默认)。
        if not (math.isfinite(self.C_j) and self.C_j >= 0):
            raise DesignDslError(
                f"JunctionInput {self.name!r}: C_j must be >= 0 and finite "
                f"(farad), got {self.C_j}")

    def e_j_joule(self) -> float:
        """有效约瑟夫森能 (焦耳): 直接给的 E_J、由 L_J 推 (ħ/2e)²/L_J, 或 SQUID 在
        ``flux`` (归一化磁通 Φ/Φ0) 处的 E_J,eff。

        SQUID 用 **无奇点** 的等价形式 ``E_JΣ·sqrt(cos²(πΦ/Φ0) + d²sin²(πΦ/Φ0))``
        (``math.hypot``): 它与教科书写法 ``E_JΣ|cos|·sqrt(1+d²tan²)`` 代数上恒等, 但
        后者的 tan 在 Φ=0.5Φ0 处发散 → 0×∞ → nan。d=0 时在 Φ=0.5Φ0 精确归零;
        d≠0 时取到极小值 E_JΣ|d|。
        """
        if self.E_J is not None:
            return self.E_J
        if self.L_J is not None:
            return FLUX_QUANTUM_REDUCED ** 2 / self.L_J
        e_sum = self.E_J1 + self.E_J2                    # type: ignore[operator]
        asym = (self.E_J2 - self.E_J1) / e_sum           # type: ignore[operator]
        phase = math.pi * self.flux                      # πΦ/Φ0
        return e_sum * math.hypot(math.cos(phase), asym * math.sin(phase))


@dataclass(frozen=True)
class ResonatorInput:
    """一个已知频率的分布式传输线谐振器 (对标 New LOM 的 ``TL_RESONATOR``)。

    谐振器 **不进 FEM**: 只有它的耦合爪子作为一个真实导体在电容矩阵里 (``node``),
    传输线本身由 (``f_res``, ``Z0``, ``mode``) 折成等效集总 LC 并到该节点上。

    Fields:
        name:  谐振器名 (结果里的标识; 不得与另一个谐振器或某个 qubit 同名)。
        node:  拼装/Maxwell 矩阵里的节点名 = ``capacitance.terminals[].group``
               (爪子导体)。必须是矩阵里的真实一行, 且不能与任何 qubit 岛撞车。
        f_res: **裸** 共振频率 (Hz) —— 未被爪子加载的传输线本征频率, 与老 LOM 的
               ``freq_readout`` 同语义。⚠ New LOM 的 ``f_res`` 是 **dressed** 频率,
               语义不同 (spec §11 R5); 结果里 ``f_bare``/``f_loaded`` 都会输出。
        Z0:    特征阻抗 (欧姆), 默认 50。
        mode:  ``"half_wave"`` (λ/2) 或 ``"quarter_wave"`` (λ/4); λ/4 在同频率下
               等效电容减半、等效电感加倍。
    """

    name: str
    node: str
    f_res: float
    Z0: float = 50.0
    mode: str = "half_wave"

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise DesignDslError("ResonatorInput.name must be a non-empty string")
        if not self.node or not isinstance(self.node, str):
            raise DesignDslError(
                f"ResonatorInput {self.name!r}: node must be a non-empty string "
                f"(a capacitance terminal group name)")
        # isfinite 理由同 JunctionInput: nan 过得了 ``<= 0``, 然后 ω_r=nan → Cr/Lr/
        # f_loaded/g/χ 一整条 nan 静默写出。
        if not (math.isfinite(self.f_res) and self.f_res > 0):
            raise DesignDslError(
                f"ResonatorInput {self.name!r}: f_res must be > 0 and finite "
                f"(hertz, BARE frequency), got {self.f_res}")
        if not (math.isfinite(self.Z0) and self.Z0 > 0):
            raise DesignDslError(
                f"ResonatorInput {self.name!r}: Z0 must be > 0 and finite (ohm), "
                f"got {self.Z0}")
        if self.mode not in RESONATOR_MODES:
            raise DesignDslError(
                f"ResonatorInput {self.name!r}: mode {self.mode!r} is not one of "
                f"{sorted(RESONATOR_MODES)}")


@dataclass(frozen=True)
class QubitResult:
    """一个 transmon 的派生 Hamiltonian 参数 (单位见各字段名后缀)。"""

    name: str
    islands: tuple[str, ...]
    C_sigma_fF: float        # **有效** 结电容 1/[C'⁻¹]_θθ,kk (fF, 已含 C_j)
    E_C_GHz: float           # 充电能 / h (GHz)
    E_J_GHz: float           # 约瑟夫森能 / h (GHz)
    f01_GHz: float           # 0→1 跃迁频率 (GHz)
    anharmonicity_MHz: float # α = −E_C (MHz, 负)
    EJ_over_EC: float        # E_J/E_C 比 (判断 transmon 有效域)
    # 纯 **几何** 等效电容 (fF): 只有电容矩阵贡献, 不含结电容 →
    # ``C_sigma_fF − C_sigma_geometric_fF == C_j``。C_j=0 时两者相等。
    # 分两个字段是为了让「FEM 解出来的」与「工艺/输入给的」在结果里可分辨。
    C_sigma_geometric_fF: float = 0.0


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
class ResonatorResult:
    """一个 TL 谐振器的派生参数 (等效集总 LC + 裸/加载频率)。

    ``f_bare_GHz`` = 输入的裸频率 (传输线本征); ``f_loaded_GHz`` = 被耦合爪子的实测
    电容加载后的频率 = 1/(2π√(L_r·C_r,eff)), 必然 **低于** 裸频率。g 与 χ 用的是
    **裸** 频率 (与老 LOM 的 ``wr`` 同约定, spec §11 R5)。
    """

    name: str
    node: str
    f_bare_GHz: float        # 输入的裸频率 (GHz)
    f_loaded_GHz: float      # 爪子加载后的频率 (GHz), < f_bare
    Cr_fF: float             # 等效集总电容 π/(2 ω_r Z0) (fF; λ/4 已减半)
    Lr_nH: float             # 等效集总电感 1/(ω_r² C_r) (nH; λ/4 已加倍)
    Z0_ohm: float
    mode: str


@dataclass(frozen=True)
class QubitResonatorCoupling:
    """一个 qubit ↔ 一个谐振器的耦合 g 与色散位移 χ。"""

    qubit: str
    resonator: str
    g_MHz: float             # g/2π (MHz, 取正) — 与 qubit-qubit 同一 inverse-cap 公式
    chi_MHz: float           # χ/2π (MHz, 带符号) = 2·chi(g, f_res, f01, f12)
    # χ 的算法标签: ``"perturbative"`` = Koch 2007 eq. (3.10) 解析式, 要求
    # |f01 − f_res| ≫ g; 近共振/强耦合时不如数值对角化 (spec §11 R6)。
    chi_method: str = "perturbative"


@dataclass(frozen=True)
class CircuitModelResult:
    """电路模型求解结果 (R1+R3 的产物; 写进 chip.results.yaml 的 ``hamiltonian`` 段)。"""

    qubits: tuple[QubitResult, ...]
    couplings: tuple[CouplingResult, ...]
    # P0-D: 声明了 ``resonators=`` 才非空 → 老调用方逐位不变。
    resonators: tuple[ResonatorResult, ...] = ()
    resonator_couplings: tuple[QubitResonatorCoupling, ...] = ()
    method: str = "lumped_oscillator_inverse_cap"
    validity: str = (
        "perturbative transmon (leading order in E_C/E_J, valid E_J/E_C >> 1); "
        "charge coupling in RWA (harmonic islands), valid in the dispersive regime; "
        "junction-branch coordinates (2-island qubits are solved as floating/"
        "differential, common mode charge = 0); capacitance terminals not "
        "referenced by any qubit are treated as grounded electrodes; "
        "TL resonators are lumped LC equivalents loaded by the measured claw "
        "capacitance, f_res is the BARE frequency (both f_bare and f_loaded are "
        "reported) and chi is Koch et al. 2007 eq. (3.10) second-order "
        "perturbation theory — valid only for |f01 - f_res| >> g, NOT near "
        "resonance or at strong coupling"
    )
    units: dict[str, str] = field(default_factory=lambda: {
        "capacitance": "fF",
        "inductance": "nH",
        "energy": "GHz",
        "frequency": "GHz",
        "anharmonicity": "MHz",
        "coupling": "MHz",
        "dispersive_shift": "MHz",
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


def resonator_lumped_lc(f_res_hz: float, z0_ohm: float,
                        mode: str = "half_wave") -> tuple[float, float]:
    """分布式 TL 谐振器 → 等效集总 (C_r 法拉, L_r 亨利)。

    逐行对照参考实现 ``lumped_capacitive.py:238-250``::

        Cr = 0.5 * np.pi / (wr * Zbus)      # = π/(2 ω_r Z0)
        Lr = 1 / wr**2 / Cr                 # = 1/(ω_r² C_r)
        if res_L4_corr[i]: Cr[i] /= 2.0; Lr[i] *= 2.0

    即 λ/4 谐振器在 **同一共振频率** 下的等效电容是 λ/2 的 **一半** (等效电感因此
    加倍) —— 方向是 ``C_r /= 2``, 别记反。ω_r = 2π f_res 用 **裸** 频率。
    """
    omega = 2.0 * math.pi * f_res_hz
    c_r = 0.5 * math.pi / (omega * z0_ohm)
    l_r = 1.0 / (omega * omega * c_r)
    if mode == "quarter_wave":
        c_r /= 2.0
        l_r *= 2.0
    elif mode != "half_wave":
        raise DesignDslError(
            f"resonator mode {mode!r} is not one of {sorted(RESONATOR_MODES)}")
    return c_r, l_r


def dispersive_shift_hz(g_hz: float, f_res_hz: float,
                        f01_hz: float, f12_hz: float) -> float:
    """色散位移 χ (Koch et al. 2007, PRA 76 042319, eq. (3.9)/(3.10))。

    逐行对照参考实现 ``lumped_capacitive.py:133-158`` 的 ``chi()``::

        chibus_0 = -2 * g**2 * w01 / (w01**2 - wr**2)        # Koch eq. (3.10)
        chibus_1 = g**2 * (1/(w01-wr) - 2/(w12-wr)
                           + 1/(w01+wr) - 2/(w12+wr))
        return (chibus_1 - chibus_0) / 2                      # Koch eq. (3.9)

    ``chibus_0`` 是 |0⟩ 的 cavity-mediated 位移, ``chibus_1`` 是 |1⟩ 的 (第 2 项的
    因子 2 = |1⟩→|2⟩ 的矩阵元按 √n 标度)。参考实现的入参是 rad/s 并在调用点
    (``:402``) 除 2π 回到 Hz; 本式对频率是 **一次齐次** 的 (g²/ω), 所以直接喂 Hz
    就得 Hz, 不需要任何 2π 因子。

    Args:
        g_hz:     qubit-cavity 线性耦合 g/2π (Hz)。
        f_res_hz: 谐振器频率 (Hz) —— 本仓一律用 **裸** 频率 (老 LOM 的 ``wr``)。
        f01_hz:   qubit 0→1 频率 (Hz)。
        f12_hz:   qubit 1→2 频率 (Hz) = f01 + α (α = −E_C/h < 0), 对应参考实现
                  ``:401-402`` 的 ``d + wq`` (``d = alpha * 2π * 1e6``)。

    Returns:
        χ (Hz) —— 注意 **|0⟩→|1⟩ 的总劈裂是 2χ**, 调用方乘 2 (参考实现 ``:402``:
        ``Chi_in_MHz = 2 * chi(...)``)。

    Raises:
        DesignDslError: f01 或 f12 与 f_res 精确共振 (分母为 0) —— 微扰式在那里失效
            (|Δ| ≲ g 时本来就不该用它, 见模块 docstring 的 R6 说明)。
    """
    if f01_hz == f_res_hz or f12_hz == f_res_hz:
        raise DesignDslError(
            f"dispersive shift: the perturbative Koch formula diverges on "
            f"resonance (f01={f01_hz:.6g} Hz, f12={f12_hz:.6g} Hz, "
            f"f_res={f_res_hz:.6g} Hz) — it needs |f01 - f_res| >> g; a "
            f"near-resonant/strongly-coupled system needs numerical "
            f"diagonalisation instead")
    g_sq = g_hz * g_hz
    chi_0 = -2.0 * g_sq * f01_hz / (f01_hz ** 2 - f_res_hz ** 2)
    chi_1 = g_sq * (1.0 / (f01_hz - f_res_hz) - 2.0 / (f12_hz - f_res_hz)
                    + 1.0 / (f01_hz + f_res_hz) - 2.0 / (f12_hz + f_res_hz))
    return (chi_1 - chi_0) / 2.0


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
    *,
    resonators: Sequence[ResonatorInput] = (),
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

    **结电容 C_j** (``JunctionInput.C_j``, 法拉, 默认 0) 并在结支路上 → 加到 ``C'`` 的
    θθ 对角, **求逆之前** (= New LOM 的 node 基折入, 恒等式见模块 docstring); 求逆后
    标量加只对孤立结成立。C_j=0 时整段短路跳过 → 逐位不动。

    **TL 谐振器** (``resonators=``, P0-D): 每个谐振器的爪子已经是矩阵里的一个真实
    terminal, 所以它在 ``B`` 里就是 θ/σ 列之后的 **一个独立选择列**; 解析等效电容
    ``C_r = π/(2 ω_r Z0)`` (λ/4 减半) 加到它的对角上 = 加载。于是 g 与 f_loaded 都从
    **同一个** ``[C'⁻¹]`` 里读出 (不另立一套机制), χ 走 Koch 解析式
    (``dispersive_shift_hz``)。不给 ``resonators`` 时 ``B`` 与结果与从前逐位相同。

    Args:
        cap_result: 已解析的电容结果 (须含非空 ``maxwell`` 矩阵 + ``terminals`` 绑定)。
        qubits:     量子比特输入列表 (每个引用 1 或 2 个岛组名 + L_J/E_J/SQUID;
                    SQUID 取声明 ``flux`` 处的 E_J,eff, 见 ``JunctionInput``)。
        resonators: 可选的 TL 谐振器列表 (每个引用矩阵里的 **一个** 爪子节点 +
                    **裸** f_res/Z0/mode, 见 ``ResonatorInput``)。

    Returns:
        ``CircuitModelResult`` (qubits 派生参数 + 每个无序对的耦合 g + 谐振器等效
        LC/裸/加载频率 + 每个 qubit×谐振器的 g 与 χ)。

    Raises:
        DesignDslError: 无 Maxwell 矩阵 / 岛不是已知 Terminal / 一个 qubit 引用 >2 个岛 /
            两处引用同一个 Terminal (岛与岛、岛与谐振器节点、谐振器与谐振器) /
            qubit 列表为空 / 谐振器名重复或与 qubit 同名 / 谐振器节点不是已知
            Terminal / 变换后矩阵奇异 / ``[C'⁻¹]_θθ,kk ≤ 0`` /
            非 transmon 区 (f01 ≤ 0) / χ 精确共振。
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

    # 谐振器的爪子节点: 同样是矩阵里的真实一行 → 进 node_idx (排在所有岛之后),
    # 并占用 ``seen`` (爪子不能同时是某个 qubit 的岛)。
    q_names = {q.name for q in qubits}
    res_seen: set[str] = set()
    for res in resonators:
        if res.name in res_seen or res.name in q_names:
            raise DesignDslError(
                f"resonator name {res.name!r} is already used by another "
                f"resonator or a qubit — every subsystem needs a unique name")
        res_seen.add(res.name)
        if res.node not in group_to_idx:
            raise DesignDslError(
                f"resonator {res.name!r}: node {res.node!r} is not a capacitance "
                f"terminal (have: {available})")
        idx = group_to_idx[res.node]
        if idx in seen:
            raise DesignDslError(
                f"resonator {res.name!r}: node {res.node!r} and {seen[idx]!r} are "
                f"the same capacitance terminal (row {idx + 1}) — a resonator claw "
                f"cannot also be a qubit island or another resonator's claw")
        seen[idx] = res.node
        node_idx.append(idx)

    # 被引用岛 (+ 谐振器爪子) 的节点子矩阵 C_S (fF, 与输入同单位); 未引用的 Terminal
    # 视作接地 → 不入子矩阵。
    sub = [[maxwell[a][b] for b in node_idx] for a in node_idx]

    # φ = B ξ, ξ = (θ_0..θ_{nq-1}, σ…, r…): 前 nq 列 = 每个 qubit 的结支路坐标,
    # 之后每个浮动 qubit 追加一个共模列, 最后每个谐振器一个独立选择列 (它的爪子就是
    # 一个真实节点, 没有换基)。接地单岛 → B 该行退化为选择行 (=1.0), 全接地 + 无
    # 谐振器时 B = 单位矩阵 → C' 与 C_S 逐位相同 (向后兼容金值)。
    n_theta = len(qubits)
    n_sigma = sum(1 for q in qubits if len(q.islands) == 2)
    n_cols = n_theta + n_sigma + len(resonators)
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
    res_cols = [n_theta + n_sigma + i for i in range(len(resonators))]
    for col in res_cols:
        b_mat[row][col] = 1.0                   # φ_claw = r_i (选择行)
        row += 1

    cprime = _congruence(sub, b_mat)             # fF — **纯几何** (C_g 读它的非对角)
    # 求逆用的矩阵 = 纯几何 + 谐振器解析 C_r + 结电容 C_j, 三者都在 **求逆之前** 折进
    # **对角** (fF, 非对角一行不动)。C_j 必须在求逆前进矩阵才能参与耦合的重整化 ——
    # 求逆后再标量加是老 LOM 的 ``Cq = tCSq + CJ``, 只对孤立结成立。
    loaded = [list(r) for r in cprime]
    lumped_lc = [resonator_lumped_lc(r.f_res, r.Z0, r.mode) for r in resonators]
    for col, (c_r, _l_r) in zip(res_cols, lumped_lc):
        loaded[col][col] += c_r / _F_PER_FF      # 爪子实测电容已在对角上 → 加载
    # C_j=0 (默认) → 下面两段整个跳过 → cinv 与从前逐位相同。
    has_cj = any(q.C_j for q in qubits)
    # 纯几何 (不含 C_j) 的逆, 只为报 ``C_sigma_geometric_fF``: 多个 qubit 同时带 C_j
    # 时 rank-m 更新的对角不再精确等于 "几何值 + C_j", 所以老老实实再求一次逆
    # (矩阵 ≤ ~10×10, 且只在真有 C_j 时才做)。
    cinv_geom = _invert_matrix(
        [[v * _F_PER_FF for v in r] for r in loaded]) if has_cj else None
    for k, q in enumerate(qubits):
        if q.C_j:
            loaded[k][k] += q.C_j / _F_PER_FF    # θ_k **就是** 结支路坐标
    cinv = _invert_matrix(                       # 法拉⁻¹, 含 σ 块与谐振器块
        [[v * _F_PER_FF for v in r] for r in loaded])

    qubit_results: list[QubitResult] = []
    for k, q in enumerate(qubits):
        cinv_kk = cinv[k][k]   # θθ 块的对角 (θ 列排在最前, 故下标就是 k); 已含 C_j
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
                f"decrease E_C: larger island capacitance, smaller L_J, or — for "
                f"a SQUID — a flux further from 0.5 Phi0, where E_J,eff -> 0)")
        c_sigma = 1.0 / cinv_kk                          # Farad (含 C_j)
        qubit_results.append(QubitResult(
            name=q.name,
            islands=q.islands,
            C_sigma_fF=c_sigma / _F_PER_FF,
            E_C_GHz=e_c / H_PLANCK / 1e9,
            E_J_GHz=e_j / H_PLANCK / 1e9,
            f01_GHz=f01 / 1e9,
            anharmonicity_MHz=-e_c / H_PLANCK / 1e6,
            EJ_over_EC=e_j / e_c,
            # 纯几何部分 = 同一变换但不折 C_j 的 1/[C'⁻¹]_θθ (C_j=0 时逐位 = C_sigma)。
            C_sigma_geometric_fF=(c_sigma if cinv_geom is None
                                  else 1.0 / cinv_geom[k][k]) / _F_PER_FF,
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

    resonator_results: list[ResonatorResult] = []
    for i, res in enumerate(resonators):
        col = res_cols[i]
        c_r, l_r = lumped_lc[i]
        cinv_rr = cinv[col][col]
        if cinv_rr <= 0:
            raise DesignDslError(
                f"resonator {res.name!r}: non-physical inverse capacitance "
                f"[C'^-1]_rr={cinv_rr} (matrix not positive-definite?)")
        c_r_eff = 1.0 / cinv_rr                          # Farad (Cr + 爪子电容)
        f_loaded = 1.0 / (2.0 * math.pi * math.sqrt(l_r * c_r_eff))
        resonator_results.append(ResonatorResult(
            name=res.name,
            node=res.node,
            f_bare_GHz=res.f_res / 1e9,
            f_loaded_GHz=f_loaded / 1e9,
            Cr_fF=c_r / _F_PER_FF,
            Lr_nH=l_r / 1e-9,
            Z0_ohm=res.Z0,
            mode=res.mode,
        ))

    # qubit ↔ 谐振器: 与 qubit-qubit **同一个** inverse-cap 公式 (只是第二个坐标是
    # 谐振器列), 频率用谐振器的 **裸** 频率 (老 LOM 的 ``wr`` 约定, spec §11 R5)。
    res_couplings: list[QubitResonatorCoupling] = []
    for k, q in enumerate(qubits):
        f01 = qubit_results[k].f01_GHz * 1e9
        # f12 = f01 + α, α = anharmonicity < 0 (对照 lumped_capacitive.py:401-402
        # 的 ``d + wq``)。
        f12 = f01 + qubit_results[k].anharmonicity_MHz * 1e6
        for i, res in enumerate(resonators):
            col = res_cols[i]
            denom = math.sqrt(cinv[k][k] * cinv[col][col])
            prefactor = abs(cinv[k][col]) / denom if denom > 0 else 0.0
            g_hz = 0.5 * prefactor * math.sqrt(f01 * res.f_res)
            chi_hz = 2.0 * dispersive_shift_hz(g_hz, res.f_res, f01, f12)
            res_couplings.append(QubitResonatorCoupling(
                qubit=q.name,
                resonator=res.name,
                g_MHz=g_hz / 1e6,
                chi_MHz=chi_hz / 1e6,
            ))

    return CircuitModelResult(
        qubits=tuple(qubit_results),
        couplings=tuple(couplings),
        resonators=tuple(resonator_results),
        resonator_couplings=tuple(res_couplings),
    )
