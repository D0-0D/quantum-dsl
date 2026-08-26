# -*- coding: utf-8 -*-
"""物理内核 (纯数学, 不依赖 gmsh/Palace): 逆电容 LOM (N8)、拼装 (N9)、
CPW 解析 (N10)、子系统 (N11)。所有 golden 为闭式手验值, 出处见各 docstring。"""
from __future__ import annotations

import math

import pytest

from conftest import N8_MAXWELL


# ---------------------------------------------------------------- N8 电路模型
def _two_pads():
    from quantum_dsl import solve_circuit_model
    return solve_circuit_model(
        labels=("A", "B"), maxwell_fF=N8_MAXWELL,
        junctions=[{"name": "A", "islands": ["A"], "L_J": 10e-9},
                   {"name": "B", "islands": ["B"], "L_J": 10e-9}])


def test_single_island_closed_form():
    """契约 N8: 1×1 时必须精确退化为 E_C = e²/2C (闭式验证过的 golden)。"""
    from quantum_dsl import solve_circuit_model
    r = solve_circuit_model(
        labels=("Q",), maxwell_fF=[[135.0]],
        junctions=[{"name": "Q", "islands": ["Q"], "L_J": 10e-9}])
    (q,) = r.qubits
    assert q.C_sigma_fF == pytest.approx(135.0, rel=1e-12)
    assert q.E_C_GHz == pytest.approx(0.14348318018266015, rel=1e-9)
    assert q.E_J_GHz == pytest.approx(16.34615128067812, rel=1e-9)
    assert q.f01_GHz == pytest.approx(4.188165715559985, rel=1e-9)
    assert q.anharmonicity_MHz == pytest.approx(-143.48318018266016, rel=1e-9)
    assert q.EJ_over_EC == pytest.approx(113.92381504137822, rel=1e-9)


def test_two_pads_inverse_capacitance_not_raw_diagonal():
    """契约 N8: C_Σ = 1/[C⁻¹]_ii —— 不是 Maxwell 对角 24.73, 也不是对地 22.75;
    α = −E_C 精确成立。"""
    a, b = _two_pads().qubits
    assert a.C_sigma_fF == pytest.approx(24.57140776699029, rel=1e-9)
    assert b.C_sigma_fF == pytest.approx(24.561471896482004, rel=1e-9)
    assert a.E_C_GHz == pytest.approx(0.7883239539364719, rel=1e-9)
    assert a.f01_GHz == pytest.approx(9.364926800074445, rel=1e-9)
    assert a.EJ_over_EC == pytest.approx(20.735322324095453, rel=1e-9)
    assert a.anharmonicity_MHz == pytest.approx(-a.E_C_GHz * 1e3, rel=1e-12)


def test_floating_two_island_closed_form():
    """契约 N8: 浮动双岛 —— 结桥接两岛, 都不接地 (sung 例子依赖的数学)。

    手算: 岛 a,b 对地 50/40 fF, 岛间 30 fF → Maxwell = [[80,-30],[-30,70]] fF。
    结支路差模的有效电容 (完整求逆取 θθ 块, Yanay et al. npj QI 2020
    Eq. 56 同款闭式): C_eff = C_ab + C_ag·C_bg/(C_ag+C_bg) = 30 + 50·40/90
    = 52.2222… fF。
    错误口径参照: 把 b 静默接地 → 1/[C⁻¹]_aa = 67.14 fF (v3 实测这类错误在
    sung 上放大成 1.70×); "删共模行列再求逆" = A⁻¹, 亦错。
    """
    from quantum_dsl import solve_circuit_model
    r = solve_circuit_model(
        labels=("a", "b"), maxwell_fF=[[80.0, -30.0], [-30.0, 70.0]],
        junctions=[{"name": "Q", "islands": ["a", "b"], "L_J": 10e-9}])
    (q,) = r.qubits
    assert q.C_sigma_fF == pytest.approx(52.22222222222223, rel=1e-9)
    assert q.E_C_GHz == pytest.approx(0.37091928494028104, rel=1e-9)
    assert q.f01_GHz == pytest.approx(6.593621041343882, rel=1e-9)
    assert q.EJ_over_EC == pytest.approx(44.06929470736441, rel=1e-9)


def test_two_pads_coupling_g():
    """契约 N8: β 是与磁通/E_J 无关的纯几何耦合度量 (sung 对论文断言的就是它);
    g = ½·β·√(f01_a·f01_b) —— 两条 golden 互为闭式一致性校验。"""
    (c,) = _two_pads().couplings
    assert {c.qubit_a, c.qubit_b} == {"A", "B"}
    assert c.beta == pytest.approx(0.08008089142510777, rel=1e-9)
    assert c.g_MHz == pytest.approx(375.0105674523576, rel=1e-6)


def test_squid_flux_tuning_singularity_free():
    """契约 N8: 非对称 SQUID 用无奇点形式 E_JΣ·√(cos²(πφ)+d²sin²(πφ)):
    φ=0 → E_J1+E_J2; φ=0.5 → |E_J1−E_J2| (教科书 tan 写法在这里发散)。"""
    from quantum_dsl import H_PLANCK, solve_circuit_model
    e1, e2 = 12e9 * H_PLANCK, 8e9 * H_PLANCK

    def f(flux):
        r = solve_circuit_model(
            labels=("Q",), maxwell_fF=[[100.0]],
            junctions=[{"name": "Q", "islands": ["Q"],
                        "squid": {"E_J1": e1, "E_J2": e2, "flux": flux}}])
        return r.qubits[0].E_J_GHz

    assert f(0.0) == pytest.approx(20.0, rel=1e-12)
    assert f(0.5) == pytest.approx(4.0, rel=1e-9)   # 甜点有限, 不是 nan/0


def test_lj_nan_inf_nonpositive_rejected():
    """契约 N8: L_J 拒 nan/inf/0/负 (nan 能穿过 `<= 0`, 必须 isfinite)。"""
    from quantum_dsl import QuantumDslError, solve_circuit_model
    for bad in (float("nan"), float("inf"), 0.0, -1e-9):
        with pytest.raises(QuantumDslError):
            solve_circuit_model(
                labels=("Q",), maxwell_fF=[[100.0]],
                junctions=[{"name": "Q", "islands": ["Q"], "L_J": bad}])


# ---------------------------------------------------------------- N9 拼装
def test_assemble_shared_node_accumulation():
    """契约 N9: 块 1 (a,s) + 块 2 (s,b) → (a,s,b); 共享节点 s 的对角相加。"""
    from quantum_dsl import assemble
    out = assemble(
        cells=[{"name": "b1", "labels": ("a", "s"),
                "maxwell_fF": [[5.0, -1.0], [-1.0, 4.0]]},
               {"name": "b2", "labels": ("s", "b"),
                "maxwell_fF": [[3.0, -2.0], [-2.0, 6.0]]}],
        keep=("a", "s", "b"))
    assert out.labels == ("a", "s", "b")
    # pytest.approx 不支持嵌套 list → 逐行比较。
    expected = [[5.0, -1.0, 0.0], [-1.0, 7.0, -2.0], [0.0, -2.0, 6.0]]
    for row, exp in zip(out.maxwell_fF, expected, strict=True):
        assert row == pytest.approx(exp)


def test_assemble_schur_elimination():
    """契约 N9: 消掉未保留节点 g: C' = C_AA − C_AB·C_BB⁻¹·C_BA (手算可验)。"""
    from quantum_dsl import assemble
    out = assemble(
        cells=[{"name": "b1", "labels": ("a", "b", "g"),
                "maxwell_fF": [[10.0, -2.0, -3.0],
                               [-2.0, 8.0, -1.0],
                               [-3.0, -1.0, 12.0]]}],
        keep=("a", "b"))
    assert out.labels == ("a", "b")
    expected = [[10.0 - 9.0 / 12.0, -2.0 - 3.0 / 12.0],
                [-2.0 - 3.0 / 12.0, 8.0 - 1.0 / 12.0]]
    for row, exp in zip(out.maxwell_fF, expected, strict=True):
        assert row == pytest.approx(exp)


def test_assemble_unknown_keep_label_raises():
    """契约 N9: keep 里写错的名字必须 raise —— 拼错 = 静默接地是 v3 踩过的坑。"""
    from quantum_dsl import QuantumDslError, assemble
    with pytest.raises(QuantumDslError):
        assemble(cells=[{"name": "b1", "labels": ("a",), "maxwell_fF": [[5.0]]}],
                 keep=("a", "typo"))


# ---------------------------------------------------------------- N10 CPW
_CPW_TYPICAL = dict(freq=5e9, line_width=10e-6, line_gap=6e-6,
                    substrate_thickness=760e-6, film_thickness=200e-9)
# 自洽物理集的手验值 (Göppl Eq.2–5 零厚度准静态 + Simons sinh 有限衬底
# + Mohebbi&Majedi Lk; Z0 与 λ_g 由总 L′=Lext+Lk 导出 — Clem Eq.35)。
# 对 qiskit-metal 参考实现的翻案 (其 Z0 −1.08% / λ_g −1.56% / ε_eff +2.63%
# 系统偏差) 见 docs/physics.md「CPW 解析」。
# 常数: c=299792458 精确, μ0=4πe-7, ε0=1/(μ0c²)。
_CPW_GOLDEN = dict(Lk=2.368128738137757e-09, Lext=4.236292014318449e-07,
                   C=1.6349287600947502e-10, Z0=51.04509563807205,
                   eps_eff=6.22481040888492, lambda_g=0.023964983826402806)


def test_cpw_golden_and_self_consistency():
    """契约 N10: lumped_cpw / guided_wavelength 对自洽集 golden 逐位; 且
    λ_g·f·√(L′C′) ≡ 1、Z0 = √(L′/C′) —— Z0/λ_g 必须含 Lk, 不许退回 c/√ε_eff
    (ε_eff 是介质填充值, 不含 Lk)。"""
    from quantum_dsl import guided_wavelength, lumped_cpw
    r = lumped_cpw(**_CPW_TYPICAL)
    for key in ("Lk", "Lext", "C", "Z0", "eps_eff", "lambda_g"):
        assert getattr(r, key) == pytest.approx(_CPW_GOLDEN[key], rel=1e-9), key
    assert r.lambda_g * _CPW_TYPICAL["freq"] * math.sqrt(
        (r.Lext + r.Lk) * r.C) == pytest.approx(1.0, rel=1e-12)
    assert r.Z0 == pytest.approx(math.sqrt((r.Lext + r.Lk) / r.C), rel=1e-12)
    g = guided_wavelength(**_CPW_TYPICAL)
    assert g.lambda_g == pytest.approx(_CPW_GOLDEN["lambda_g"], rel=1e-9)
    assert g.eps_eff == pytest.approx(_CPW_GOLDEN["eps_eff"], rel=1e-9)


def test_cpw_kinetic_inductance_can_dominate():
    """契约 N10: 窄线 + 薄膜 + 大 λ_L → Lk > Lext (动力学电感不是修正项, 是主项)。"""
    from quantum_dsl import lumped_cpw
    r = lumped_cpw(freq=5e9, line_width=1e-6, line_gap=0.5e-6,
                   substrate_thickness=500e-6, film_thickness=20e-9,
                   london_penetration_depth=90e-9)
    assert r.Lk > r.Lext


# ---------------------------------------------------------------- N11 子系统
def test_resonator_lumped_lc_half_and_quarter_wave():
    """契约 N11: λ/2: C_r = π/(2ωZ0), L_r = 1/(ω²C_r); λ/4 同频下 C 减半、
    L 加倍 (方向别记反), 共振频率不变。"""
    from quantum_dsl import resonator_lumped_lc
    omega = 2 * math.pi * 7.0e9
    c_h, l_h = resonator_lumped_lc(7.0e9, 50.0, mode="half_wave")
    assert c_h == pytest.approx(math.pi / (2 * omega * 50.0), rel=1e-12)
    assert l_h == pytest.approx(1.0 / (omega ** 2 * c_h), rel=1e-12)
    c_q, l_q = resonator_lumped_lc(7.0e9, 50.0, mode="quarter_wave")
    assert c_q == pytest.approx(c_h / 2, rel=1e-12)
    assert l_q == pytest.approx(l_h * 2, rel=1e-12)
    assert 1 / (2 * math.pi * math.sqrt(l_q * c_q)) == pytest.approx(7.0e9)


def test_dispersive_shift_golden():
    """契约 N11: χ 非 RWA 三能级二阶式 (Zhu et al. arXiv:1210.1605 Eq. 11–14;
    注意 Koch 2007 (3.9)/(3.10) 是 RWA 版, qiskit-metal 源码注释误引)。
    golden: g=41.19 MHz, f_r=7 GHz, f01=5.2, f12=4.95。"""
    from quantum_dsl import dispersive_shift_hz
    chi = dispersive_shift_hz(41.19e6, 7.0e9, 5.2e9, 4.95e9)
    assert chi == pytest.approx(-117856.23947910377, rel=1e-9)
