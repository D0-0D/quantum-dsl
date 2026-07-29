# -*- coding: utf-8 -*-
"""CPW 解析集总计算器 (P0-F): 共面波导的单位长度 L/C/G、Z0 与导波波长。

对标 qiskit-metal ``analyses/em/cpw_calculations.py`` (Apache-2.0) 的
``lumped_cpw()`` (:97) 与 ``guided_wavelength()`` (:46), 以及它们调用的
``effective_dielectric_constant()`` (:190) / ``elliptic_int_constants()`` (:228)。
本模块是 **逐行移植**, 不是重新推导 —— 验收判据是「对参考实现 < 1%」(spec §7),
所以连参考实现的常数取值和内部不自洽之处都照抄 (见下「已知不自洽」)。

**它不是可选附属工具**: New LOM 的 ``TL_RESONATOR`` 在 ``vp="use_design"`` 时
内部就调 ``guided_wavelength()`` 求相速 (``lom_core_analysis.py:1142-1144``:
``vp = f_res · λ_g``), 因此这是「``f_res`` 从哪来 / 谐振器长度↔频率」的唯一入口。

⚠⚠ **THIS MODULE'S INTERFACE IS SI METRES + Hz, *NOT* THE REPO-INTERNAL µm** ⚠⚠
⚠⚠ **本模块的接口单位是 SI 米 / Hz, 不是仓库内部的 µm** ⚠⚠
    与参考实现一致 (它的 docstring 明确写 "in meters", "in Hz")。仓库内部长度单位
    是 µm (``_units.SI_PER_INTERNAL = 1e-6``), 所以从 IR/sidecar 接线过来时
    **必须先乘 1e-6**, 且只乘一次 —— 别双重缩放。每个参数的单位都写在 docstring 里。

单位速查 (全部 **单位长度** 量, 参考实现的 docstring 把 C/Lk 写成 "Farads"/"Henries"
是笔误 —— 公式里 ε0 [F/m]、µ0 [H/m] 都没有再乘长度):
    C, C_star: F/m      Lk, Lext: H/m      G: S/m      Z0: Ω      λ_g: m
    eps_eff, q: 无量纲

物理 (Simons / Goppl et al. JAP 104, 113904 (2008) / Mohebbi & Majedi SUST 22,
125028 (2009) 的标准共形映射结果; 假设基片 µ_r = 1、封装地面无穷远、无损超导):

    共形映射的模数与第一类完全椭圆积分 K (参考 :246-252) ——
        k0  = s/(s+2w)                       (共面, 半无穷厚基片)
        k0' = √(1 − k0²)
        k1  = sinh(πs/4h) / sinh(π(s+2w)/4h) (有限厚 h 的修正)
        k1' = √(1 − k1²)
    以下一律记 Kk0 = K(k0²) 等 —— **K 的参数约定见 `complete_elliptic_k`**。

    填充因子与单位长度电容 (:158-161)
        q = ½ · (Kk1·Kk0') / (Kk1'·Kk0)
        C = 2ε0(ε_r − 1)(Kk1/Kk1') + 4ε0(Kk0/Kk0')
    介质损耗电导 (:164)
        G = 2πf · C · q · tanδ
    膜厚+基片厚修正后的有效介电常数 (:211-223, √ε_eff 记作 etfSqrt)
        ε00 = 1 + q(ε_r − 1)
        ε_t0 = ε00 − 0.7(ε00−1)(t/w) / [(Kk0/Kk0') + 0.7 t/w]
        p = ln(s/h),  v = 0.43 − 0.86p + 0.54p²,  u = 0.54 − 0.64p + 0.015p²
        f_TE = c0 / (4h√(ε_r − 1)),  g = exp(u·ln(s/w) + v)
        √ε_eff = √ε_t0 + (√ε_r − √ε_t0) / (1 + g·(f/f_TE)^−1.8)
    特征阻抗与几何 (外) 电感 (:170-172)
        Z0 = (30π/√ε_eff)·(Kk0'/Kk0)          [30π Ω ≈ ¼√(µ0/ε0), 见「已知不自洽」]
        Lext = Z0² · C
        C_star = 2ε0(ε_eff − 1)(Kk1/Kk1') + 4ε0(Kk0/Kk0')   (用 ε_eff 代 ε_r 的 C)
    导波波长 (:92)
        λ_g = (c0/f) / √ε_eff                  (全波长! λ/2 谐振器除以 2, λ/4 除以 4)

    **动力学电感** (:175-185, Mohebbi & Majedi 的薄膜 CPW 拟合式; 窄线超导 CPW
    里 Lk 与 Lext 同量级 —— 1 µm 线宽 / 20 nm 膜时 Lk/Lext ≈ 1.4, 绝不可忽略):
        A = −t/π + ½√((2t/π)² + s²)
        B = s²/(4A)
        C1 = B − t/π + √((t/π)² + w²)
        D = 2t/π + C1
        Lk_step = µ0·λ_L·C1 / (4·A·D·Kk0)
        Lk = Lk_step·1.7/sinh(t/2λ_L) + Lk_step·0.4/√[((B/A)²−1)(1−(B/D)²)]
    λ_L 是伦敦穿透深度; 若线宽已到 Pearl 长度量级, 该拟合式失效 (参考 :121-125)。

**已知不自洽 (照抄参考实现, 消费端不要假设这些恒等式)**:
  1. ``Z0 == √(Lext/C)`` 逐位成立 (因为 Lext 就是由 Z0²C 定义的), 但
     ``Z0 ≠ √((Lext+Lk)/C)`` —— 参考实现的 Z0 来自共形映射闭式, 不含 Lk。
     动力学电感对阻抗的抬升要消费端自己算 (窄线时是 +50% 量级)。
  2. ``λ_g ≠ 1/(f·√((Lext+Lk)·C))``, 连 ``1/(f·√(Lext·C))`` 都差 ~2.6% ——
     因为 λ_g 走 ε_eff, 而 C 走 ε_r + 填充因子 q (二者只在 ``C_star`` 里对齐)。
     λ_g 的定义就是 (c0/f)/√ε_eff, 别用 LC 反推。
  3. 常数按参考实现的字面值 (:34-36, :170): c0 = 2.9979e8、ε0 = 8.85419e-12、
     µ0 = 4πe−7、Z0 前因子 30π。与 SI-2019 精确值的相对偏差: ε0 1.4e−7、
     µ0 5.5e−10、c0 8.2e−6、30π vs ¼√(µ0/ε0)=94.184 是 6.8e−4 (最大项,
     经 Lext=Z0²C 放大到 1.4e−3)。全在 1% 预算内, 但 **为了与参考实现逐位对齐,
     这里不"修正"成 SI 精确值** —— 本模块的正确性定义就是参考实现本身。
     (与 ``circuit_model.py`` 的 "exact SI" 约定不同, 是刻意的, 原因如上。)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import DesignDslError


__all__ = [
    "CpwLumped",
    "GuidedWavelength",
    "lumped_cpw",
    "guided_wavelength",
    "complete_elliptic_k",
    "EPS_R_SILICON",
    "LOSS_TANGENT_DEFAULT",
    "LONDON_DEPTH_NIOBIUM",
]


# ---------------------------------------------------------------------------
# 常数 —— 逐字取自参考实现 (cpw_calculations.py:34-36, :105, :170)。
# 不换成 SI-2019 精确值: 见模块 docstring「已知不自洽」第 3 条。
# ---------------------------------------------------------------------------
_C0 = 2.9979 * 10**8            # m/s   光速 (参考 :34)
_EPS0 = 8.85419 * 10**-12       # F/m   真空介电常数 (参考 :35)
_MU0 = 4 * math.pi * 10**-7     # H/m   真空磁导率 (参考 :36)
_Z0_PREFACTOR = 30 * math.pi    # Ω     ≈ ¼√(µ0/ε0) (参考 :170 的字面 30π)

EPS_R_SILICON = 11.45           # 低温硅的相对介电常数 (参考默认值 :103/:52)
LOSS_TANGENT_DEFAULT = 10**-5   # 介质损耗角正切 (参考默认值 :104)
LONDON_DEPTH_NIOBIUM = 30 * 10**-9  # m, 铌的伦敦穿透深度 (参考默认值 :105)


# ---------------------------------------------------------------------------
# 输出数据类
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CpwLumped:
    """``lumped_cpw()`` 的结果 —— 单位长度集总等效电路 (参考 :130-145 的返回元组)。

    ::

        -----Lext + Lk--+---+---
                        |   |
                        C   G
                        |   |
        ----------------+---+---

    Fields:
        Lk:       串联动力学电感, **H/m**。
        Lext:     串联几何 (外) 电感, **H/m** (= Z0²·C; 内部几何电感被忽略)。
        C:        并联电容, **F/m**。
        G:        并联电导 (介质损耗), **S/m**。
        Z0:       特征阻抗, **Ω** (共形映射闭式, **不含 Lk**)。
        eps_eff:  有效介电常数 (含膜厚/基片厚修正), 无量纲 = 参考的 ``etfSqrt**2``。
        C_star:   把 ε_r 换成 ε_eff 的并联电容, **F/m** (参考的 ``Cstar`` ——
                  它 docstring 里写 "External Inductance" 是笔误)。
        q:        填充因子, 无量纲。
        lambda_g: 导波 **全** 波长, **m** —— 与 ``guided_wavelength()`` 逐位相同
                  (同一段计算), 放在这里省得为了长度↔频率再算一遍。
    """

    Lk: float
    Lext: float
    C: float
    G: float
    Z0: float
    eps_eff: float
    C_star: float
    q: float
    lambda_g: float


@dataclass(frozen=True)
class GuidedWavelength:
    """``guided_wavelength()`` 的结果 (参考 :70-74 的返回元组 + 集总量)。

    Fields:
        lambda_g: 导波 **全** 波长, **m**。λ/2 谐振器取 ``lambda_g/2``,
                  λ/4 取 ``lambda_g/4``。相速 ``vp = freq · lambda_g``
                  (New LOM ``lom_core_analysis.py:1144`` 就是这么算的)。
        eps_eff:  有效介电常数, 无量纲 (参考返回的是 ``etfSqrt`` = 它的平方根,
                  这里统一成 ε_eff 本身, 与 ``CpwLumped.eps_eff`` 一致)。
        q:        填充因子, 无量纲。
        Lk/Lext/C/G: 与 ``lumped_cpw()`` **逐位相同** 的单位长度集总量,
                  单位同 ``CpwLumped``。
    """

    lambda_g: float
    eps_eff: float
    q: float
    Lk: float
    Lext: float
    C: float
    G: float


# ---------------------------------------------------------------------------
# 第一类完全椭圆积分 —— AGM, 替掉参考实现的 scipy.special.ellipk
# ---------------------------------------------------------------------------

def complete_elliptic_k(m: float) -> float:
    """第一类完全椭圆积分 K, **参数约定 m = k² (parameter, 不是 modulus k)**。

    与 ``scipy.special.ellipk`` 的约定 **完全一致** —— 已核对参考实现
    ``elliptic_int_constants`` (:252) 传进去的是 ``k0**2.0`` 等平方值, 而
    scipy 的 ``ellipk(m)`` 文档也说取参数 m; 实测 ``ellipk(0.5) = 1.8540746773``
    = 教科书的 K(k=1/√2), 确认无疑。教科书写 K(k) 时对应这里的 ``m = k**2``。

    实现: 算术-几何平均 (AGM), 用来避开对 scipy 的依赖 (本模块必须是纯 math)
        K(m) = π / (2 · agm(1, √(1−m)))
    AGM 二次收敛, 十几次迭代就到双精度极限。检查点: K(0) = π/2 (√(1−0)=1,
    agm(1,1)=1), m→1⁻ 时 √(1−m)→0 → agm→0 → K→∞ (对数发散)。

    Args:
        m: 参数 m = k², 必须落在 ``[0, 1)``。m ≥ 1 时 K 发散/非实数, 报错。

    Returns:
        float: K(m)。

    Raises:
        DesignDslError: m 非有限, 或不在 [0, 1) 内。
    """
    if not isinstance(m, (int, float)) or not math.isfinite(m):
        raise DesignDslError(
            f"complete_elliptic_k: m must be a finite real number, got {m!r}")
    if m < 0.0 or m >= 1.0:
        raise DesignDslError(
            f"complete_elliptic_k: m = k**2 must satisfy 0 <= m < 1, got {m!r}")
    a, b = 1.0, math.sqrt(1.0 - m)
    for _ in range(64):
        if abs(a - b) <= 1e-17 * a:
            break
        a, b = 0.5 * (a + b), math.sqrt(a * b)
    return math.pi / (2.0 * a)


# ---------------------------------------------------------------------------
# 内部: 共形映射常数 + 有效介电常数 (参考 :228-252 / :190-225)
# ---------------------------------------------------------------------------

def _elliptic_int_constants(
    s: float, w: float, h: float
) -> tuple[float, float, float, float]:
    """(Kk0, Kk0', Kk1, Kk1') —— 参考 ``elliptic_int_constants`` :246-252 逐行。"""
    k0 = s / (s + 2 * w)
    k01 = math.sqrt(1 - k0**2)
    try:
        k1 = math.sinh((math.pi * s) / (4 * h)) / math.sinh(
            (math.pi * (s + 2 * w)) / (4 * h))
    except OverflowError as exc:  # h ≪ s: sinh 溢出, 该几何超出模型适用域
        raise DesignDslError(
            "cpw_analytic: substrate_thickness is too small relative to the line "
            f"(s={s!r} m, h={h!r} m) — sinh(pi*s/4h) overflows; the conformal-"
            "mapping model needs h on the order of the line dimensions or larger"
        ) from exc
    k11 = math.sqrt(1 - k1**2)
    return (complete_elliptic_k(k0**2.0), complete_elliptic_k(k01**2.0),
            complete_elliptic_k(k1**2.0), complete_elliptic_k(k11**2.0))


def _effective_dielectric_sqrt(
    freq: float, s: float, w: float, h: float, t: float,
    q: float, Kk0: float, Kk01: float, eps_r: float,
) -> float:
    """√ε_eff —— 参考 ``effective_dielectric_constant`` :211-223 逐行。"""
    e00 = 1 + q * (eps_r - 1)
    et0 = e00 - (0.7 * (e00 - 1) * t / w) / ((Kk0 / Kk01) + 0.7 * t / w)

    p = math.log(s / h)
    v = 0.43 - 0.86 * p + 0.54 * p**2
    u = 0.54 - 0.64 * p + 0.015 * p**2
    fTE = _C0 / (4 * h * math.sqrt(eps_r - 1))
    g = math.exp(u * math.log(s / w) + v)

    return math.sqrt(et0) + (math.sqrt(eps_r) - math.sqrt(et0)) / (
        1 + g * (freq / fTE) ** -1.8)


def _check_inputs(
    freq: float, line_width: float, line_gap: float, substrate_thickness: float,
    film_thickness: float, eps_r: float, loss_tangent: float,
    london_penetration_depth: float,
) -> None:
    """所有输入必须是有限正数 (SI), 且 eps_r > 1; 否则 ``DesignDslError``。

    ``eps_r > 1`` 是硬要求: f_TE 里有 ``√(ε_r − 1)`` (参考 :218), ε_r ≤ 1 时
    非实数/除零。``film_thickness > 0`` 同理: Lk 里有 ``1/sinh(t/2λ_L)``。
    """
    for name, value in (
        ("freq", freq),
        ("line_width", line_width),
        ("line_gap", line_gap),
        ("substrate_thickness", substrate_thickness),
        ("film_thickness", film_thickness),
        ("eps_r", eps_r),
        ("loss_tangent", loss_tangent),
        ("london_penetration_depth", london_penetration_depth),
    ):
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise DesignDslError(
                f"cpw_analytic: {name} must be a finite real number, got {value!r}")
        if value <= 0.0:
            raise DesignDslError(
                f"cpw_analytic: {name} must be > 0 (SI units, lengths in METRES), "
                f"got {value!r}")
    if eps_r <= 1.0:
        raise DesignDslError(
            f"cpw_analytic: eps_r must be > 1 (vacuum is 1), got {eps_r!r}")


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def lumped_cpw(
    freq: float,
    line_width: float,
    line_gap: float,
    substrate_thickness: float,
    film_thickness: float,
    *,
    eps_r: float = EPS_R_SILICON,
    loss_tangent: float = LOSS_TANGENT_DEFAULT,
    london_penetration_depth: float = LONDON_DEPTH_NIOBIUM,
) -> CpwLumped:
    """CPW 的单位长度集总等效 (含动力学电感) —— 参考 ``lumped_cpw`` :97-187 逐行。

    ⚠ **所有长度参数是 SI 米 (METRES), 不是仓库内部的 µm**。10 µm 线宽写 ``10e-6``。

    Args:
        freq: 频率, **Hz** (例 ``5e9``)。
        line_width: 中心导体线宽 s, **m** (例 ``10e-6``)。
        line_gap: 缝隙宽 w, **m** (例 ``6e-6``)。
        substrate_thickness: 基片厚 h, **m** (例 ``760e-6``)。
        film_thickness: 薄膜厚 t, **m** (例 ``200e-9``)。
        eps_r: 基片相对介电常数, 无量纲, 默认 11.45 (低温硅, 参考默认值)。
            必须 > 1。
        loss_tangent: 介质损耗角正切 tanδ, 无量纲, 默认 1e-5 (参考默认值;
            只影响 ``G``)。
        london_penetration_depth: 伦敦穿透深度 λ_L, **m**, 默认 30e-9 (铌,
            参考默认值)。建议用与温度/膜厚相关的实测值; 线宽接近 Pearl 长度时
            动力学电感公式失效。

    Returns:
        CpwLumped: 单位长度 Lk/Lext/C/G + Z0/ε_eff/C_star/q + λ_g。

    Raises:
        DesignDslError: 任一输入非有限或 ≤ 0, 或 eps_r ≤ 1, 或几何超出模型适用域。
    """
    _check_inputs(freq, line_width, line_gap, substrate_thickness, film_thickness,
                  eps_r, loss_tangent, london_penetration_depth)

    s = line_width
    w = line_gap
    h = substrate_thickness
    t = film_thickness
    tanD = loss_tangent
    lambdaLT = london_penetration_depth
    wfreq = freq * 2 * math.pi

    Kk0, Kk01, Kk1, Kk11 = _elliptic_int_constants(s, w, h)

    C = 2 * _EPS0 * (eps_r - 1) * (Kk1 / Kk11) + 4 * _EPS0 * (Kk0 / Kk01)

    # 填充因子 (参考 :161)
    q = 0.5 * (Kk1 * Kk01) / (Kk11 * Kk0)

    # 介质损耗电导 (参考 :164)
    G = wfreq * C * q * tanD

    # 有效介电常数 (参考 :167) —— etfSqrt = √ε_eff
    etfSqrt = _effective_dielectric_sqrt(freq, s, w, h, t, q, Kk0, Kk01, eps_r)

    # 特征阻抗 / 几何电感 (参考 :170-172)
    Z0 = (_Z0_PREFACTOR / etfSqrt) * Kk01 / Kk0
    Lext = Z0**2 * C
    Cstar = 2 * _EPS0 * (etfSqrt**2 - 1) * (Kk1 / Kk11) + 4 * _EPS0 * (Kk0 / Kk01)

    # 动力学电感 (参考 :175-185)
    A1 = (-t / math.pi) + (1 / 2) * math.sqrt((2 * t / math.pi) ** 2 + s**2)
    B1 = s**2 / (4 * A1)
    C1 = B1 - (t / math.pi) + math.sqrt((t / math.pi) ** 2 + w**2)
    D1 = 2 * t / math.pi + C1

    LkinStep = _MU0 * lambdaLT * C1 / (4 * A1 * D1 * Kk0)

    Lkin1 = LkinStep * 1.7 / (math.sinh(t / (2 * lambdaLT)))
    Lkin2 = LkinStep * 0.4 / (
        math.sqrt((((B1 / A1) ** 2) - 1) * (1 - (B1 / D1) ** 2)))

    Lk = Lkin1 + Lkin2

    # 导波波长 (参考 guided_wavelength :92) —— 同一 etfSqrt, 所以两个 API 逐位一致
    lambdaG = (_C0 / freq) / etfSqrt

    return CpwLumped(Lk=Lk, Lext=Lext, C=C, G=G, Z0=Z0, eps_eff=etfSqrt**2,
                     C_star=Cstar, q=q, lambda_g=lambdaG)


def guided_wavelength(
    freq: float,
    line_width: float,
    line_gap: float,
    substrate_thickness: float,
    film_thickness: float,
    *,
    eps_r: float = EPS_R_SILICON,
    loss_tangent: float = LOSS_TANGENT_DEFAULT,
    london_penetration_depth: float = LONDON_DEPTH_NIOBIUM,
) -> GuidedWavelength:
    """CPW 导波波长 (长度↔频率) —— 参考 ``guided_wavelength`` :46-94。

    ⚠ **所有长度参数是 SI 米 (METRES), 不是仓库内部的 µm**。参数含义与
    ``lumped_cpw()`` 完全相同 (``loss_tangent`` 只影响顺带返回的 ``G``,
    参考实现的 ``guided_wavelength`` 没这个参数, 也不返回 G)。

    λ_g 是 **全** 波长: λ/2 谐振器长度 = ``lambda_g/2``, λ/4 = ``lambda_g/4``。
    New LOM 的 ``vp="use_design"`` 就是 ``vp = freq · lambda_g``
    (``lom_core_analysis.py:1142-1144``)。

    Returns:
        GuidedWavelength: λ_g + ε_eff + q + 与 ``lumped_cpw()`` 逐位相同的集总量。

    Raises:
        DesignDslError: 同 ``lumped_cpw()``。
    """
    r = lumped_cpw(freq, line_width, line_gap, substrate_thickness, film_thickness,
                   eps_r=eps_r, loss_tangent=loss_tangent,
                   london_penetration_depth=london_penetration_depth)
    return GuidedWavelength(lambda_g=r.lambda_g, eps_eff=r.eps_eff, q=r.q,
                            Lk=r.Lk, Lext=r.Lext, C=r.C, G=r.G)
