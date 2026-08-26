# -*- coding: utf-8 -*-
"""CPW 解析集总 (契约 N10): 单位长度 L/C/G、Z0 与导波波长 (AGM 椭圆积分)。

**自洽公式集** (2026-08-24 裁定, 见 docs/physics.md §9), 每一式有独立
文献出处:

  * k0 共面 / k1 有限衬底 sinh 分支 — Simons Eq. (2.37)/(2.38)
    (背面接地版图是 tanh 分支, 不可混用);
  * ε_eff = 1 + q(ε_r − 1), C′ = 4ε0·ε_eff·K/K′ — Göppl Eq. (2)–(5)
    (源流 Wen 1969), 准静态零厚度;
  * L_g′ = (μ0/4)·K′/K — 同上, 纯几何外电感;
  * L_k′ — Mohebbi & Majedi (SUST 22, 125028) 薄膜拟合式, 对 Clem
    (arXiv:1210.5929) 核定; 窄线超导 CPW 里与 L_g 同量级, 不是修正项;
  * 总 L′ = L_g′ + L_k′, **Z0 = √(L′/C′), λ_g = 1/(f·√(L′C′))** — Clem
    Eq. (35): 加入 L_k 后相速/阻抗必须由总 L′C′ 重算, 不能再用 c/√ε_eff。

历史: v3 = qiskit-metal ``cpw_calculations.py`` 逐行, 其 Z0/λ_g 不含 Lk,
且 ε_eff 打了膜厚+TE 色散补丁而 C 没打 (两者差 ~2.6%, Lext=Z0²C 连带失真),
常数还是截断值 (c0=2.9979e8)。契约曾把这套输出钉为 golden——已翻案, v4
锚自洽集; 参考实现差值: Z0 −1.08%, λ_g −1.56%, ε_eff +2.63%, C/Lk 不变。

# ponytail: 弃掉的膜厚 ε 修正与 TE 色散项在本仓工况 (t/w≲0.03, f≲0.2·f_TE)
# 均 <3% 且是上述不自洽的来源; 若将来要 >20 GHz 或厚膜, 升级到 2D/3D EM,
# 别把补丁式加回来。

⚠⚠ **接口单位是 SI 米 / Hz, 不是仓库内部的 µm** ⚠⚠ 10 µm 线宽写 ``10e-6``。
从 µm 侧接线时乘 1e-6, 且只乘一次。

常数: c = 299792458 (SI 精确), μ0 = 4π×10⁻⁷, ε0 = 1/(μ0c²) — 与 SI-2019
CODATA 差 ~5e-10, 远低于任何物理容差; golden 由同一组常数导出, 逐位稳定。
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

_C0 = 299792458.0
_MU0 = 4 * math.pi * 1e-7
_EPS0 = 1.0 / (_MU0 * _C0 * _C0)

EPS_R_SILICON = 11.45               # 低温硅
LOSS_TANGENT_DEFAULT = 10**-5
LONDON_DEPTH_NIOBIUM = 30 * 10**-9  # m, 铌


@dataclass(frozen=True)
class CpwLumped:
    """单位长度集总等效: Lk/Lext [H/m], C [F/m], G [S/m], Z0 [Ω]
    (= √((Lext+Lk)/C), **含 Lk**), eps_eff/q 无量纲 (准静态介质填充值,
    不含 Lk — 所以 λ_g ≠ (c/f)/√ε_eff), lambda_g [m] (**全**波长, 含 Lk)。"""

    Lk: float
    Lext: float
    C: float
    G: float
    Z0: float
    eps_eff: float
    q: float
    lambda_g: float


@dataclass(frozen=True)
class GuidedWavelength:
    """λ_g [m] (**全**波长: λ/2 谐振器取 /2, λ/4 取 /4; vp = f·λ_g, 含 Lk)
    + 与 ``lumped_cpw()`` 逐位相同的 ε_eff/q/集总量。"""

    lambda_g: float
    eps_eff: float
    q: float
    Lk: float
    Lext: float
    C: float
    G: float


def complete_elliptic_k(m: float) -> float:
    """第一类完全椭圆积分 K, **参数约定 m = k²** (与 scipy.special.ellipk
    一致)。AGM 实现: K(m) = π/(2·agm(1, √(1−m))), 二次收敛。检查点:
    K(0)=π/2; m→1⁻ 对数发散。"""
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
    """(Kk0, Kk0', Kk1, Kk1') — k0 = s/(s+2w) 共面;
    k1 = sinh(πs/4h)/sinh(π(s+2w)/4h) 有限衬底 (开放上空间, sinh 分支)。"""
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


def _check_inputs(freq, line_width, line_gap, substrate_thickness,
                  film_thickness, eps_r, loss_tangent,
                  london_penetration_depth):
    """全部输入有限正数 (SI); t > 0 (Lk 有 1/sinh(t/2λ_L))。"""
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
    """CPW 单位长度集总等效 (含动力学电感, Z0/λ_g 由总 L′C′ 自洽导出)。

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
    eps_eff = 1 + q * (eps_r - 1)                    # ≡ C/(4ε0·K0/K0′), 自洽
    G = wfreq * C * q * loss_tangent                 # 介质损耗电导

    Lext = _MU0 / 4 * Kk01 / Kk0                     # 纯几何外电感 (Göppl)

    # 动力学电感 (Mohebbi & Majedi 薄膜拟合式)
    A1 = (-t / math.pi) + (1 / 2) * math.sqrt((2 * t / math.pi) ** 2 + s**2)
    B1 = s**2 / (4 * A1)
    C1 = B1 - (t / math.pi) + math.sqrt((t / math.pi) ** 2 + w**2)
    D1 = 2 * t / math.pi + C1
    LkinStep = _MU0 * london_penetration_depth * C1 / (4 * A1 * D1 * Kk0)
    Lk = (LkinStep * 1.7 / math.sinh(t / (2 * london_penetration_depth))
          + LkinStep * 0.4 / math.sqrt(
              (((B1 / A1) ** 2) - 1) * (1 - (B1 / D1) ** 2)))

    Ltot = Lext + Lk
    Z0 = math.sqrt(Ltot / C)
    lambdaG = 1.0 / (freq * math.sqrt(Ltot * C))     # vp = 1/√(L′C′)

    return CpwLumped(Lk=Lk, Lext=Lext, C=C, G=G, Z0=Z0, eps_eff=eps_eff,
                     q=q, lambda_g=lambdaG)


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
