# -*- coding: utf-8 -*-
"""门仿真 opt-in ``drag_gamma`` (plan ⑥): x_drag 标定族放开时变失谐 γ (Gambetta 2011 Eq. 4.46 全族, App. B 相位斜坡)
+ 论文一阶解多起点。整体关掉 = 删本文件 + gates.py 的 ``_gaussian_sq_integral`` / ``_drag_starts`` / ``"gamma" in x`` 分支
+ meta.py 的 ``drag_gamma`` 键。实测账 = build/sprint/gamma.md。

锚: ∫Ω_G² 的 erf 闭式 = 数值积分; γ 的符号 / 量纲 = tools/gambetta2011.py 的开环 Z-only (RWA 模型 1.340e-3, 那边
数值累加相位); 标定后 γ 族比旧族好 ≥ 20× (8 ns); meta 键校验 (拼错 / 非 bool / 挂在 cr 上 raise)。默认关时旧族
不变由 test_gates.py 原有断言 + 不加键的 load_meta 字典相等 (test_frontend) 守着 (逐位比对做过一次, 见 gamma.md)。
"""
from __future__ import annotations

import math
import types

import pytest

# xmon_pair_tune 综合终版 Q1 (= test_gates.py 的 Q1): f01 4.8 GHz, α −249 MHz, λ₁ 1.377
Q1 = {"name": "Q1", "E_C_GHz": 0.22146443584270326, "E_J_GHz": 14.294990715992935}


def test_drag_gamma_meta_key(tmp_path):
    """契约「门仿真」: ``drag_gamma`` 只收 bool、只挂 x_drag; 不写时条目里没有这个键 (默认路径不变)。"""
    from quantum_dsl import QuantumDslError, load_meta
    head = "schema: quantum-dsl/meta/1\ngeo: x.geo\n"
    p = tmp_path / "g.meta.yaml"
    p.write_text(head + "gates: [{name: X, kind: x_drag, qubit: Q1, t_gate: 8ns, drag_gamma: true},"
                 " {name: Y, kind: x_drag, qubit: Q1, t_gate: 8ns}]\n", encoding="utf-8")
    g = load_meta(p).gates
    assert g[0]["drag_gamma"] is True and "drag_gamma" not in g[1]
    for body, match in (("{name: X, kind: x_drag, qubit: Q1, t_gate: 8ns, drag_gama: true}", "unknown key"),
                        ("{name: X, kind: x_drag, qubit: Q1, t_gate: 8ns, drag_gamma: 1}", "drag_gamma must be"),
                        ("{name: X, kind: x_drag, qubit: Q1, t_gate: 8ns, drag_gamma: 'yes'}", "drag_gamma must be"),
                        ("{name: X, kind: cr, control: Q1, target: Q2, t_gate: 200ns, drag_gamma: true}",
                         "unknown key")):
        p.write_text(head + f"gates: [{body}]\n", encoding="utf-8")
        with pytest.raises(QuantumDslError, match=match):
            load_meta(p)


def test_gaussian_sq_integral_closed_form():
    """∫₀ᵗ g² (g = Eq. 3.2 单位面积截断高斯) 的 erf 闭式 = 数值积分 (相对 1e-12)。"""
    pytest.importorskip("supergrad")
    from scipy.integrate import quad

    from quantum_dsl.gates import _gaussian_sq_integral, gaussian
    for t_g in (4.0, 30.0):
        for t in (0.3 * t_g, t_g):
            ref = quad(lambda u: float(gaussian(u, t_g, t_g / 4)[0]) ** 2, 0, t, epsabs=0, epsrel=1e-13)[0]
            assert float(_gaussian_sq_integral(t, t_g, t_g / 4)) == pytest.approx(ref, rel=1e-12)


def test_gamma_phase_ramp_sign_matches_open_loop_z_only(monkeypatch):
    """γ 的量纲与符号: 不标定 (优化器换成恒等) 时, 唯一起点 = Z-only (β = 0, γ = λ₁²/4, Eq. 4.34) 的 10 ns 门误差
    = tools/gambetta2011.py 的开环 Z-only (实验室系 1.3428e-3; 同参数 RWA 模型 1.3399e-3); 高斯开环 1.6e-2 是对照
    (γ 符号反了会离 1.34e-3 很远)。"""
    pytest.importorskip("supergrad")
    import supergrad.utils.optimize as so

    from quantum_dsl import gates
    monkeypatch.setattr(so, "scipy_minimize", lambda f, x0, **kw: types.SimpleNamespace(x=x0))
    monkeypatch.setattr(gates, "_drag_starts", lambda l1: {"z_only": {"beta": 0.0, "gamma": l1 ** 2 / 4}})
    r = gates.simulate_gates({"qubits": [Q1]}, [{"name": "X", "kind": "x_drag", "qubit": "Q1",
                                                 "t_gate_ns": 10.0, "levels": 5, "drag_gamma": True}])[0]
    assert r["drag_gamma"] == pytest.approx(r["lambda1"] ** 2 / 4) and r["drag_start"] == "z_only"
    assert r["error"] == pytest.approx(1.3428e-3, rel=2e-3)
    assert r["gaussian_error"] == pytest.approx(1.6e-2, rel=0.05)


def test_gamma_family_beats_old_family():
    """契约「门仿真」: 8 ns X 门 (σ = 2 ns ≈ 0.5·2π/|α|)。旧族 (amp, β, δ₀) = 2.42e-5 (physics §15.1 表; 28 起点网格
    也是它, build/sprint/gamma.md); γ 族多起点 2.8e-7 —— 锁 ≥ 20×; 结果带 drag_gamma / drag_start;
    高斯基线不受开关影响 (= 旧族那次的 5.61e-4)。旧族本身由 test_gates.py 的 10 ns 断言守着, 这里不重算 (省 ~15 s)。"""
    pytest.importorskip("supergrad")
    from quantum_dsl import gates
    r = gates.simulate_gates({"qubits": [Q1]}, [{"name": "X", "kind": "x_drag", "qubit": "Q1", "t_gate_ns": 8.0,
                                                 "levels": 5, "drag_gamma": True}])[0]
    assert r["error"] < 2.42e-5 / 20 and r["leakage"] == pytest.approx(r["error"], rel=0.05)
    assert r["drag_start"] in gates._drag_starts(1.0) and math.isfinite(r["drag_gamma"])
    assert r["gaussian_error"] == pytest.approx(5.6117e-4, rel=1e-3)
