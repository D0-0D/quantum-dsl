# -*- coding: utf-8 -*-
"""CPW 解析集总 (契约 N10): 单位长度 L/C/G、Z0 与导波波长 (AGM 椭圆积分)。

审后搬运自 v3 ``dsl/cpw_analytic.py`` = qiskit-metal
``analyses/em/cpw_calculations.py`` (Apache-2.0) 的逐行移植。**契约 golden
就是参考实现的输出 (rel=1e-9)**, 所以连参考实现的常数取值和内部不自洽都
照抄 — 本模块的正确性定义是参考实现本身。

物理谱系: 椭圆积分共形映射 (Wen 1969 / Simons ch.2 / Göppl JAP 104, 113904);
动力学电感 Lk 是 Mohebbi & Majedi (SUST 22, 125028) 薄膜拟合式 — 窄线超导
CPW 里 Lk 与 Lext 同量级, 不是修正项 (N10 有 Lk > Lext 的测试)。

⚠⚠ **接口单位是 SI 米 / Hz, 不是仓库内部的 µm** ⚠⚠ 10 µm 线宽写 ``10e-6``。
从 µm 侧接线时乘 1e-6, 且只乘一次。

**已知不自洽 (照抄参考实现, 消费端不要假设这些恒等式)**:
  1. ``Z0 == √(Lext/C)`` 逐位成立 (Lext 由 Z0²·C 定义), 但 Z0 **不含 Lk** —
     共形映射闭式。总 ``L' = Lext + Lk`` 下的 Z0/相速/λ_g **必须由消费端用
     总 L'C' 重算** (pipeline §2 审点; 由几何反推 f_res 时才需要, V4-5 再做),
     窄线时抬升是 +50% 量级 — 本模块契约锚定参考实现, 不"顺手改进"。
  2. ``λ_g = (c0/f)/√ε_eff`` 是定义式, 别用 LC 反推 (连 √(Lext·C) 都差 ~2.6%,
     因为 λ_g 走 ε_eff 而 C 走 ε_r + 填充因子 q)。
  3. 常数按参考实现字面值 (c0=2.9979e8, ε0=8.85419e-12, 前因子 30π) — 与
     SI-2019 的偏差最大 1.4e-3 (经 Lext=Z0²C 放大), 在验收预算内; 为逐位
     对齐 golden **不修正** (与 circuit_model 的 "exact SI" 约定刻意不同)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import QuantumDslError

__all__ = [
    "CpwLumped", "GuidedWavelength", "lumped_cpw", "guided_wavelength",
    "complete_elliptic_k",
    "EPS_R_SILICON", "LOSS_TANGENT_DEFAULT", "LONDON_DEPTH_NIOBIUM",
]

# 常数逐字取自参考实现 (cpw_calculations.py:34-36, :105, :170) — 见模块
# docstring「已知不自洽」第 3 条, 不换成 SI-2019 精确值。
_C0 = 2.9979 * 10**8
_EPS0 = 8.85419 * 10**-12
_MU0 = 4 * math.pi * 10**-7
_Z0_PREFACTOR = 30 * math.pi

EPS_R_SILICON = 11.45               # 低温硅 (参考默认值)
LOSS_TANGENT_DEFAULT = 10**-5
LONDON_DEPTH_NIOBIUM = 30 * 10**-9  # m, 铌


@dataclass(frozen=True)
class CpwLumped:
    """单位长度集总等效: Lk/Lext [H/m], C [F/m], G [S/m], Z0 [Ω] (不含 Lk),
    eps_eff/q 无量纲, C_star [F/m] (ε_eff 版 C), lambda_g [m] (**全**波长)。"""

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
    """λ_g [m] (**全**波长: λ/2 谐振器取 /2, λ/4 取 /4; vp = f·λ_g) +
    与 ``lumped_cpw()`` 逐位相同的 ε_eff/q/集总量。"""

    lambda_g: float
    eps_eff: float
    q: float
    Lk: float
    Lext: float
    C: float
    G: float


def complete_elliptic_k(m: float) -> float:
    """第一类完全椭圆积分 K, **参数约定 m = k²** (与 scipy.special.ellipk
    一致 — 参考实现传的是 k² 平方值)。AGM 实现: K(m) = π/(2·agm(1, √(1−m))),
    二次收敛。检查点: K(0)=π/2; m→1⁻ 对数发散。"""
    if not isinstance(m, (int, float)) or not math.isfinite(m):
        raise QuantumDslError(
            f"complete_elliptic_k: m must be a finite real number, got {m!r}")
    if m < 0.0 or m >= 1.0:
        raise QuantumDslError(
            f"complete_elliptic_k: m = k**2 must satisfy 0 <= m < 1, got {m!r}")
    a, b = 1.0, math.sqrt(1.0 - m)
    for _ in range(64):
        if abs(a - b) <= 1e-17 * a:
            break
        a, b = 0.5 * (a + b), math.sqrt(a * b)
    return math.pi / (2.0 * a)


def _elliptic_int_constants(s, w, h):
    """(Kk0, Kk0', Kk1, Kk1') — 参考 ``elliptic_int_constants`` 逐行。
    k0 = s/(s+2w) 共面; k1 = sinh(πs/4h)/sinh(π(s+2w)/4h) 有限厚修正。"""
    k0 = s / (s + 2 * w)
    k01 = math.sqrt(1 - k0**2)
    try:
        k1 = math.sinh((math.pi * s) / (4 * h)) / math.sinh(
            (math.pi * (s + 2 * w)) / (4 * h))
    except OverflowError as exc:  # h ≪ s: 超出共形映射适用域
        raise QuantumDslError(
            f"cpw: substrate_thickness too small relative to the line "
            f"(s={s!r} m, h={h!r} m) — sinh(pi*s/4h) overflows") from exc
    k11 = math.sqrt(1 - k1**2)
    return (complete_elliptic_k(k0**2.0), complete_elliptic_k(k01**2.0),
            complete_elliptic_k(k1**2.0), complete_elliptic_k(k11**2.0))


def _effective_dielectric_sqrt(freq, s, w, h, t, q, Kk0, Kk01, eps_r):
    """√ε_eff (膜厚 t + 基片厚 h 修正) — 参考 ``effective_dielectric_constant``
    逐行 (sinh 分支, 半无穷上空间; 背面接地版图是 tanh 分支, 不可混用)。"""
    e00 = 1 + q * (eps_r - 1)
    et0 = e00 - (0.7 * (e00 - 1) * t / w) / ((Kk0 / Kk01) + 0.7 * t / w)
    p = math.log(s / h)
    v = 0.43 - 0.86 * p + 0.54 * p**2
    u = 0.54 - 0.64 * p + 0.015 * p**2
    fTE = _C0 / (4 * h * math.sqrt(eps_r - 1))
    g = math.exp(u * math.log(s / w) + v)
    return math.sqrt(et0) + (math.sqrt(eps_r) - math.sqrt(et0)) / (
        1 + g * (freq / fTE) ** -1.8)


def _check_inputs(freq, line_width, line_gap, substrate_thickness,
                  film_thickness, eps_r, loss_tangent,
                  london_penetration_depth):
    """全部输入有限正数 (SI), eps_r > 1 (f_TE 有 √(ε_r−1)); t > 0 (Lk 有
    1/sinh(t/2λ_L))。"""
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
            raise QuantumDslError(
                f"cpw: {name} must be a finite real number, got {value!r}")
        if value <= 0.0:
            raise QuantumDslError(
                f"cpw: {name} must be > 0 (SI units, lengths in METRES), "
                f"got {value!r}")
    if eps_r <= 1.0:
        raise QuantumDslError(f"cpw: eps_r must be > 1 (vacuum is 1), got {eps_r!r}")


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
    """CPW 单位长度集总等效 (含动力学电感) — 参考 ``lumped_cpw`` 逐行。

    ⚠ 长度参数一律 **SI 米**: line_width 中心导体 s, line_gap 缝 w,
    substrate_thickness 基片 h, film_thickness 膜厚 t; freq Hz。
    λ_L (london_penetration_depth) 用实测值更好; 线宽接近 Pearl 长度
    Λ=2λ²/t 时 Lk 拟合式失效 (Clem 2013)。
    """
    _check_inputs(freq, line_width, line_gap, substrate_thickness,
                  film_thickness, eps_r, loss_tangent,
                  london_penetration_depth)
    s = line_width
    w = line_gap
    h = substrate_thickness
    t = film_thickness
    wfreq = freq * 2 * math.pi

    Kk0, Kk01, Kk1, Kk11 = _elliptic_int_constants(s, w, h)

    C = 2 * _EPS0 * (eps_r - 1) * (Kk1 / Kk11) + 4 * _EPS0 * (Kk0 / Kk01)
    q = 0.5 * (Kk1 * Kk01) / (Kk11 * Kk0)            # 填充因子
    G = wfreq * C * q * loss_tangent                 # 介质损耗电导

    etfSqrt = _effective_dielectric_sqrt(freq, s, w, h, t, q, Kk0, Kk01, eps_r)

    Z0 = (_Z0_PREFACTOR / etfSqrt) * Kk01 / Kk0      # 共形映射闭式, 不含 Lk
    Lext = Z0**2 * C
    Cstar = 2 * _EPS0 * (etfSqrt**2 - 1) * (Kk1 / Kk11) + 4 * _EPS0 * (Kk0 / Kk01)

    # 动力学电感 (Mohebbi & Majedi 薄膜拟合式, 参考 :175-185 逐行)
    A1 = (-t / math.pi) + (1 / 2) * math.sqrt((2 * t / math.pi) ** 2 + s**2)
    B1 = s**2 / (4 * A1)
    C1 = B1 - (t / math.pi) + math.sqrt((t / math.pi) ** 2 + w**2)
    D1 = 2 * t / math.pi + C1
    LkinStep = _MU0 * london_penetration_depth * C1 / (4 * A1 * D1 * Kk0)
    Lk = (LkinStep * 1.7 / math.sinh(t / (2 * london_penetration_depth))
          + LkinStep * 0.4 / math.sqrt(
              (((B1 / A1) ** 2) - 1) * (1 - (B1 / D1) ** 2)))

    lambdaG = (_C0 / freq) / etfSqrt                 # 定义式, 别用 LC 反推

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
    """CPW 导波波长 (长度↔频率) — 与 ``lumped_cpw()`` 同一段计算, 逐位一致。"""
    r = lumped_cpw(freq, line_width, line_gap, substrate_thickness,
                   film_thickness, eps_r=eps_r, loss_tangent=loss_tangent,
                   london_penetration_depth=london_penetration_depth)
    return GuidedWavelength(lambda_g=r.lambda_g, eps_eff=r.eps_eff, q=r.q,
                            Lk=r.Lk, Lext=r.Lext, C=r.C, G=r.G)
