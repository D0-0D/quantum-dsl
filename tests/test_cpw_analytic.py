# -*- coding: utf-8 -*-
"""P0-F — CPW 解析集总计算器: 对 qiskit-metal ``cpw_calculations`` 的数值对标。

三块内容:
  (1) ``complete_elliptic_k`` (AGM 实现的第一类完全椭圆积分) 的独立测试 ——
      参数约定必须是 **m = k²**, 与 ``scipy.special.ellipk`` 一致;
  (2) ``lumped_cpw`` / ``guided_wavelength`` 对 **硬编码 golden** 的比对
      (默认就跑, 不需要 scipy / qiskit-metal);
  (3) gated 的 **实时** 交叉验算 —— 直接调 ``qiskit_metal.analyses.em.
      cpw_calculations``, 缺 scipy 或缺 qiskit-metal 时 skip。

GOLDEN 数据来源 (逐字记录, 别手改):
    脚本  <scratchpad>/cpw_ref.py  (调 lumped_cpw / guided_wavelength /
          elliptic_int_constants / scipy.special.ellipk, 用 repr() 打印)
    环境  conda env ``quantum-metal``: qiskit-metal **0.7.6** (editable,
          ~/metal/qiskit-metal) + scipy 1.17.1 + Python 3.x
    命令  conda run -n quantum-metal python <scratchpad>/cpw_ref.py
    日期  2026-07-29
`metal-env` 里的 qiskit_metal 0.5.1 的 ``cpw_calculations`` 与 0.7.6 只差
排版 (已 diff 确认表达式逐字相同), 所以 (3) 在 metal-env 里也能真跑。

验收判据是 **rel < 1e-2** (spec §7), 实测最坏 **9.2e-16** (纯浮点 ULP 级) ——
所以这里用 ``RTOL = 1e-12`` 把它钉死: 任何公式/常数改动都会立刻炸, 而不是
悄悄漂到 0.9% 还算"通过"。
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from quantum_dsl.dsl.cpw_analytic import (
    EPS_R_SILICON,
    LONDON_DEPTH_NIOBIUM,
    LOSS_TANGENT_DEFAULT,
    CpwLumped,
    GuidedWavelength,
    complete_elliptic_k,
    guided_wavelength,
    lumped_cpw,
)
from quantum_dsl.dsl.errors import DesignDslError


# 钉住的容差; 验收只要 1e-2 (spec §7), 实测 9.2e-16。
RTOL = 1e-12
# spec §7 的验收判据本身 —— 单独断言一遍, 免得将来放松 RTOL 时把判据也丢了。
SPEC_RTOL = 1e-2


# ---------------------------------------------------------------------------
# GOLDEN: scipy.special.ellipk(m) —— 注意参数是 m = k², 不是 modulus k
# ---------------------------------------------------------------------------
ELLIPK_GOLDEN = {
    0.0: 1.5707963267948966,        # = π/2 (解析值)
    1e-12: 1.5707963267952894,
    0.1: 1.6124413487202192,
    0.5: 1.8540746773013719,        # 教科书 K(k=1/√2) = 1.8540747
    0.9: 2.5780921133481733,
    0.99: 3.6956373629898747,
    0.999999: 8.294051463601061,
}


# ---------------------------------------------------------------------------
# GOLDEN: lumped_cpw / guided_wavelength
# 每条 = (label, 入参 kwargs, 参考输出)。参考的返回元组
#   (Lk, Lext, C, G, Z0, etfSqrt**2, Cstar)  +  (lambdaG, etfSqrt, q)
# 映射到我们的字段名 (eps_eff = etfSqrt**2, C_star = Cstar)。
# ---------------------------------------------------------------------------
CASES: tuple[tuple[str, dict, dict], ...] = (
    (
        # 典型: 10 µm / 6 µm 硅上 CPW, 50 Ω 附近, 5 GHz
        "typical_10_6_si",
        dict(freq=5e9, line_width=10e-6, line_gap=6e-6,
             substrate_thickness=760e-6, film_thickness=200e-9),
        dict(Lk=2.3681287381377575e-09, Lext=4.353629666360981e-07,
             C=1.63492916307188e-10, G=2.5680475379588533e-05,
             Z0=51.60315696321091, eps_eff=6.065432087076736,
             C_star=9.278339184874006e-11, q=0.49998185730956207,
             lambda_g=0.024345363624151843),
    ),
    (
        # 窄线 + 薄膜 + 大 λ_L: 动力学电感 **超过** 几何电感 (Lk/Lext ≈ 1.4)
        "narrow_1_05_thin",
        dict(freq=5e9, line_width=1e-6, line_gap=0.5e-6,
             substrate_thickness=500e-6, film_thickness=20e-9,
             london_penetration_depth=90e-9),
        dict(Lk=5.800164107342136e-07, Lext=4.144790934511103e-07,
             C=1.7234098517517668e-10, G=2.707123940581729e-05,
             Z0=49.040741607531494, eps_eff=6.044312425208674,
             C_star=9.751195579220714e-11, q=0.4999996446208673,
             lambda_g=0.02438785956521346),
    ),
    (
        # 厚膜 (1 µm) + 宽线, 6.5 GHz
        "thick_film_20_12",
        dict(freq=6.5e9, line_width=20e-6, line_gap=12e-6,
             substrate_thickness=500e-6, film_thickness=1e-6),
        dict(Lk=6.935573618953326e-10, Lext=4.5187288302894027e-07,
             C=1.6345190188447607e-10, G=3.336626759894304e-05,
             Z0=52.57910034914765, eps_eff=5.8423555824815985,
             C_star=8.983497153428857e-11, q=0.4998324239705789,
             lambda_g=0.01908138053144771),
    ),
    (
        # 薄膜 (50 nm) + 薄基片 (380 µm), 4 GHz
        "thin_film_10_6",
        dict(freq=4e9, line_width=10e-6, line_gap=6e-6,
             substrate_thickness=380e-6, film_thickness=50e-9),
        dict(Lk=6.563855412909337e-09, Lext=4.270132733975224e-07,
             C=1.634779815897866e-10, G=2.0540267953258336e-05,
             Z0=51.10825511686422, eps_eff=6.183468882526706,
             C_star=9.432602942114704e-11, q=0.49992744365357245,
             lambda_g=0.030139848224378808),
    ),
    (
        # 非默认 eps_r + 非默认 tanδ, 7.5 GHz
        "eps10_15_9",
        dict(freq=7.5e9, line_width=15e-6, line_gap=9e-6,
             substrate_thickness=675e-6, film_thickness=100e-9,
             eps_r=10.0, loss_tangent=2e-6),
        dict(Lk=3.098112946804581e-09, Lext=4.2784925055054763e-07,
             C=1.444437411396899e-10, G=6.8060465385670875e-06,
             Z0=54.42469747596196, eps_eff=5.452833542443027,
             C_star=8.473488883021769e-11, q=0.49994825712287544,
             lambda_g=0.017117674294376585),
    ),
    (
        # 蓝宝石量级 eps_r + 非默认 λ_L, 8 GHz
        "sapphire_ish",
        dict(freq=8e9, line_width=12e-6, line_gap=6e-6,
             substrate_thickness=430e-6, film_thickness=150e-9,
             eps_r=9.27, london_penetration_depth=45e-9),
        dict(Lk=4.520636541013697e-09, Lext=4.0967198810851307e-07,
             C=1.421482562746123e-10, G=3.572081079747334e-05,
             Z0=53.68430887683823, eps_eff=5.043897237314142,
             C_star=8.365585592278432e-11, q=0.4999308256273345,
             lambda_g=0.016685684988993983),
    ),
)

_CASE_IDS = [c[0] for c in CASES]


def _rel(got: float, ref: float) -> float:
    return abs(got - ref) / abs(ref)


def _ref_kwargs(kwargs: dict) -> dict:
    """我们的 kwargs → 参考实现的 kwargs (只有 eps_r 改了名)。"""
    out = dict(kwargs)
    if "eps_r" in out:
        out["dielectric_constant"] = out.pop("eps_r")
    return out


# ---------------------------------------------------------------------------
# (1) 完全椭圆积分 K
# ---------------------------------------------------------------------------

def test_complete_elliptic_k_matches_scipy_golden():
    """K(m) 的 AGM 实现 vs scipy.special.ellipk **同样的参数 m = k²**。"""
    worst = 0.0
    for m, ref in ELLIPK_GOLDEN.items():
        got = complete_elliptic_k(m)
        rel = _rel(got, ref)
        worst = max(worst, rel)
        assert rel < RTOL, f"K({m!r}): got {got!r}, ref {ref!r}, rel {rel:.3e}"
    assert worst < 1e-15, f"worst K rel deviation drifted: {worst:.3e}"


def test_complete_elliptic_k_analytic_anchors():
    """无需外部参考的解析锚点: K(0) = π/2 逐位; 单调递增; m→1⁻ 对数发散。"""
    assert complete_elliptic_k(0.0) == math.pi / 2.0
    values = [complete_elliptic_k(m) for m in (0.0, 0.25, 0.5, 0.75, 0.9, 0.99)]
    assert values == sorted(values)
    assert all(b > a for a, b in zip(values, values[1:]))
    # 发散: 越靠近 1 越大, 但仍有限 (对数发散, 不是极点)
    assert complete_elliptic_k(1 - 1e-15) > 18.0
    assert math.isfinite(complete_elliptic_k(1 - 1e-15))


@pytest.mark.parametrize("bad", [-1e-9, -1.0, 1.0, 1.5, float("nan"),
                                 float("inf"), "0.5", None])
def test_complete_elliptic_k_rejects_out_of_range(bad):
    """m ∉ [0, 1) 或非实数 → DesignDslError (m = 1 时 K 发散)。"""
    with pytest.raises(DesignDslError):
        complete_elliptic_k(bad)


# ---------------------------------------------------------------------------
# (2) 硬编码 golden 比对 —— 默认就跑, 无外部依赖
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,kwargs,ref", CASES, ids=_CASE_IDS)
def test_lumped_cpw_matches_golden(label, kwargs, ref):
    """``lumped_cpw`` 的每个字段对 qiskit-metal golden 的相对偏差。"""
    got = lumped_cpw(**kwargs)
    assert isinstance(got, CpwLumped)
    worst = 0.0
    for field, refv in ref.items():
        rel = _rel(getattr(got, field), refv)
        worst = max(worst, rel)
        assert rel < SPEC_RTOL, (  # spec §7 的正式判据
            f"{label}.{field}: rel {rel:.3e} exceeds the spec budget {SPEC_RTOL}")
        assert rel < RTOL, (
            f"{label}.{field}: got {getattr(got, field)!r}, golden {refv!r}, "
            f"rel {rel:.3e} — parity with qiskit-metal lumped_cpw() broke")
    assert worst < 1e-14, f"{label}: worst rel deviation drifted to {worst:.3e}"


@pytest.mark.parametrize("label,kwargs,ref", CASES, ids=_CASE_IDS)
def test_guided_wavelength_matches_golden(label, kwargs, ref):
    """``guided_wavelength`` 的 λ_g / ε_eff / q 对 golden。"""
    got = guided_wavelength(**kwargs)
    assert isinstance(got, GuidedWavelength)
    for field in ("lambda_g", "eps_eff", "q"):
        rel = _rel(getattr(got, field), ref[field])
        assert rel < RTOL, (
            f"{label}.{field}: got {getattr(got, field)!r}, "
            f"golden {ref[field]!r}, rel {rel:.3e}")


@pytest.mark.parametrize("label,kwargs,ref", CASES, ids=_CASE_IDS)
def test_guided_wavelength_and_lumped_cpw_are_bitwise_consistent(label, kwargs, ref):
    """两个 API 共享同一段计算 → 公共字段必须 **逐位** 相同 (不是"接近")。"""
    lc = lumped_cpw(**kwargs)
    gw = guided_wavelength(**kwargs)
    for field in ("Lk", "Lext", "C", "G", "eps_eff", "q", "lambda_g"):
        assert getattr(gw, field) == getattr(lc, field), f"{label}.{field}"


# ---------------------------------------------------------------------------
# 定义性恒等式 —— 按参考实现的 **实际** 定义, 不是教科书的理想关系
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,kwargs,ref", CASES, ids=_CASE_IDS)
def test_definitional_identities(label, kwargs, ref):
    """成立的: Z0 = √(Lext/C) 与 λ_g = (c0/f)/√ε_eff。

    参考实现里 ``Lext ≡ Z0²·C`` (:171), 所以 Z0 = √(Lext/C) 是恒等式;
    λ_g ≡ (c0/f)/√ε_eff (:92)。c0 用参考实现的 2.9979e8。
    """
    r = lumped_cpw(**kwargs)
    assert _rel(math.sqrt(r.Lext / r.C), r.Z0) < 1e-12, label
    c0_ref = 2.9979 * 10**8
    assert _rel((c0_ref / kwargs["freq"]) / math.sqrt(r.eps_eff), r.lambda_g) < 1e-12


@pytest.mark.parametrize("label,kwargs,ref", CASES, ids=_CASE_IDS)
def test_kinetic_inductance_is_excluded_from_z0_and_lambda_g(label, kwargs, ref):
    """**不** 成立的两条 —— 钉住, 免得有人"顺手修正"就破了 parity。

    参考实现的 Z0 来自共形映射闭式 (:170), 不含 Lk; λ_g 走 ε_eff 而 C 走
    ε_r + 填充因子 q, 二者只在 ``C_star`` 里对齐。所以:
        Z0 ≠ √((Lext+Lk)/C)              (窄线时差 50%)
        λ_g ≠ 1/(f·√(Lext·C))             (实测差 0.7% ~ 6%)
    消费端要 Lk 抬升后的阻抗/波长, 必须自己算。
    """
    r = lumped_cpw(**kwargs)
    z0_with_lk = math.sqrt((r.Lext + r.Lk) / r.C)
    assert z0_with_lk > r.Z0                       # Lk > 0 → 严格抬升
    assert _rel(z0_with_lk, r.Z0) > 1e-4           # 而 Z0 确实没含它
    lam_from_lc = 1.0 / (kwargs["freq"] * math.sqrt(r.Lext * r.C))
    assert _rel(lam_from_lc, r.lambda_g) > 1e-3    # λ_g 不是 LC 反推出来的


def test_kinetic_inductance_dominates_a_narrow_line():
    """P0-F 为什么必须含 Lk: 1 µm 线 / 20 nm 膜时 Lk/Lext ≈ 1.4, 忽略它错 >100%。"""
    narrow = lumped_cpw(freq=5e9, line_width=1e-6, line_gap=0.5e-6,
                        substrate_thickness=500e-6, film_thickness=20e-9,
                        london_penetration_depth=90e-9)
    assert narrow.Lk / narrow.Lext > 1.0
    wide = lumped_cpw(freq=5e9, line_width=20e-6, line_gap=12e-6,
                      substrate_thickness=500e-6, film_thickness=1e-6)
    assert wide.Lk / wide.Lext < 0.01              # 宽线厚膜: 可忽略量级


def test_defaults_match_the_reference_defaults():
    """默认值必须与参考实现一致 (:52/:103-105), 否则 golden 全错。

    ⚠ 连 **字面写法** 都要一致: ``30 * 10**-9`` = 3.0000000000000004e-08 ≠
    ``30e-9`` = 3e-08 (差 1 ULP), 会在 Lk 的末位上体现出来。参考实现写的是
    ``30 * 10**-9``, golden 也是那么生成的, 所以我们照抄。
    """
    assert EPS_R_SILICON == 11.45
    assert LOSS_TANGENT_DEFAULT == 10**-5
    assert LONDON_DEPTH_NIOBIUM == 30 * 10**-9
    explicit = lumped_cpw(5e9, 10e-6, 6e-6, 760e-6, 200e-9,
                          eps_r=11.45, loss_tangent=10**-5,
                          london_penetration_depth=30 * 10**-9)
    assert lumped_cpw(5e9, 10e-6, 6e-6, 760e-6, 200e-9) == explicit


# ---------------------------------------------------------------------------
# 报错路径 / 纯度
# ---------------------------------------------------------------------------

_OK = dict(freq=5e9, line_width=10e-6, line_gap=6e-6,
           substrate_thickness=760e-6, film_thickness=200e-9)


@pytest.mark.parametrize("field", list(_OK) + [
    "eps_r", "loss_tangent", "london_penetration_depth"])
@pytest.mark.parametrize("bad", [0.0, -1e-6, float("nan"), float("inf")])
@pytest.mark.parametrize("fn", [lumped_cpw, guided_wavelength])
def test_non_positive_or_non_finite_inputs_raise(fn, field, bad):
    """宽度/缝隙/频率/厚度/eps_r/tanδ/λ_L 任一 ≤ 0 或非有限 → DesignDslError。"""
    kwargs = dict(_OK)
    kwargs[field] = bad
    with pytest.raises(DesignDslError):
        fn(**kwargs)


@pytest.mark.parametrize("eps_r", [1.0, 0.5])
def test_eps_r_must_exceed_one(eps_r):
    """f_TE 里有 √(ε_r − 1) (参考 :218) → ε_r ≤ 1 必须报错, 不能出 nan。"""
    with pytest.raises(DesignDslError):
        lumped_cpw(**_OK, eps_r=eps_r)


def test_absurdly_thin_substrate_raises_instead_of_overflowing():
    """h ≪ s 时 sinh(πs/4h) 溢出 → 变成 DesignDslError, 不是 OverflowError。"""
    with pytest.raises(DesignDslError):
        lumped_cpw(5e9, 10e-6, 6e-6, 1e-12, 200e-9)


def test_module_is_pure_math():
    """spec 要求 ``cpw_analytic.py`` 与 ``circuit_model.py`` 同纯度: 不许 numpy/scipy。"""
    src = (Path(__file__).resolve().parents[1] / "src" / "quantum_dsl" / "dsl"
           / "cpw_analytic.py").read_text(encoding="utf-8")
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            assert "numpy" not in stripped and "scipy" not in stripped, stripped


# ---------------------------------------------------------------------------
# (3) gated 实时交叉验算 —— 需要 scipy + qiskit-metal, 二者缺一即 skip。
#     ⚠ importorskip 只放在这个函数体内: 上面的纯测试 **不** 依赖它们。
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,kwargs,ref", CASES, ids=_CASE_IDS)
def test_cross_check_live_qiskit_metal(label, kwargs, ref):
    """直接调 qiskit-metal 的 ``lumped_cpw``/``guided_wavelength`` 实时比对。

    在只有 quantum-metal / metal-env 这类装了 qiskit-metal + scipy 的环境里真跑;
    别的环境 skip (预期行为 —— 参考实现是可选依赖)。
    """
    pytest.importorskip("scipy", reason="reference lumped_cpw needs scipy.special")
    cpw = pytest.importorskip(
        "qiskit_metal.analyses.em.cpw_calculations",
        reason="live cross-check needs qiskit-metal installed")

    kw = _ref_kwargs(kwargs)
    Lk, Lext, C, G, Z0, eps_eff, Cstar = cpw.lumped_cpw(
        kw.pop("freq"), kw.pop("line_width"), kw.pop("line_gap"),
        kw.pop("substrate_thickness"), kw.pop("film_thickness"), **kw)
    got = lumped_cpw(**kwargs)
    for field, refv in (("Lk", Lk), ("Lext", Lext), ("C", C), ("G", G),
                        ("Z0", Z0), ("eps_eff", eps_eff), ("C_star", Cstar)):
        rel = _rel(getattr(got, field), refv)
        assert rel < SPEC_RTOL, f"{label}.{field}: rel {rel:.3e} > {SPEC_RTOL}"
        assert rel < RTOL, f"{label}.{field}: rel {rel:.3e} (live), ref {refv!r}"

    gkw = _ref_kwargs(kwargs)
    gkw.pop("loss_tangent", None)
    gkw.pop("london_penetration_depth", None)
    lambdaG, etfSqrt, q = cpw.guided_wavelength(
        gkw.pop("freq"), gkw.pop("line_width"), gkw.pop("line_gap"),
        gkw.pop("substrate_thickness"), gkw.pop("film_thickness"), **gkw)
    gw = guided_wavelength(**kwargs)
    assert _rel(gw.lambda_g, lambdaG) < RTOL, label
    assert _rel(gw.eps_eff, etfSqrt**2) < RTOL, label
    assert _rel(gw.q, q) < RTOL, label
