# -*- coding: utf-8 -*-
"""门仿真 (契约「门仿真」; 要 SuperGrad: ``pip install -e '.[gates]'``, 没装整文件 skip)。

锚只锚论文与闭式 (docs/physics.md §15):
* Gambetta, Motzoi, Merkel & Wilhelm PRA 83, 012308 (2011) = arXiv:1011.1949 §III–IV: d = 5 标准非线性振子
  旋转系 NOT 门, 高斯误差 0.198 / 0.0160 / 0.0030 与一阶 DRAG 解的排序 (Fig. 3 正文);
* SuperGrad transmon 谱 = circuit_model 的电荷基精确能级; J = 8β√(E_Ca E_Cb) 的静态 ZZ = 二阶微扰闭式;
* 相互作用绘景 (模块) = SuperGrad 自己的实验室系 ``Evolve`` (同一 CR 脉冲); 步数加倍门误差不变;
* transmon 上标定后: DRAG 比高斯好一个量级以上、β 落在一阶最优 λ₁/2 附近; CR 幅度在一阶闭式附近。
"""
from __future__ import annotations

import math

import pytest

pytest.importorskip("supergrad")
pytest.importorskip("threadpoolctl")

# xmon_pair_tune 综合出的两比特 (build/xp_tune, 2026-10-14): f01 4.8 / 5.0 GHz, α ≈ −249 MHz, g ≈ 8 MHz
Q1 = {"name": "Q1", "E_C_GHz": 0.22146443584270326, "E_J_GHz": 14.294990715992935}
Q2 = {"name": "Q2", "E_C_GHz": 0.22182758856060428, "E_J_GHz": 15.427980784044026}
PAIR = {"qubits": [Q1, Q2], "couplings": [{"qubit_a": "Q2", "qubit_b": "Q1", "beta": 0.00327566610257095}]}


def _sno_not_error(sigma, cy=0.0, cz=0.0):
    """论文 Eq. 2.8: d = 5 SNO (Δ_j = Δ₂ j(j−1)/2, λ_{j−1} = √j), 旋转系, Δ₂ = −2π (时间单位 2π/|Δ₂|), t_g = 4σ。
    Ωx = Ω_G (Eq. 3.2, A = π), Ωy = cy·Ω̇_G/Δ₂, δ = cz·Ω_G²/Δ₂ → (1 − F_Pedersen, 1 − F_六轴态 Eq. 3.4)。"""
    import jax.numpy as jnp
    import numpy as np
    import supergrad
    from supergrad.utils.fidelity import compute_average_fidelity_with_leakage

    from quantum_dsl.gates import gaussian

    d, d2, tg = 5, -2 * math.pi, 4 * sigma
    lam = np.sqrt(np.arange(1, d))
    h0 = np.diag([d2 * j * (j - 1) / 2 for j in range(d)]).astype(complex)
    hz = np.diag(np.arange(d)).astype(complex)
    hx = (np.diag(lam, 1) + np.diag(lam, -1)).astype(complex)
    hy = -1j * np.diag(lam, 1) + 1j * np.diag(lam, -1)     # σy_{j−1,j} = −i|j−1⟩⟨j| + i|j⟩⟨j−1|

    def omega(t):
        g, dg = gaussian(t, tg, sigma)
        return math.pi * g, math.pi * dg

    ham = [jnp.asarray(h0), [jnp.asarray(hx), lambda t, a: omega(t)[0] / 2],
           [jnp.asarray(hy), lambda t, a: cy * omega(t)[1] / d2 / 2],
           [jnp.asarray(hz), lambda t, a: cz * omega(t)[0] ** 2 / d2]]
    m = np.asarray(supergrad.sesolve(ham, jnp.eye(d, dtype=complex)[:, :2], jnp.array([0.0, tg]),
                                     options={"astep": 4000, "trotter_order": None})[-1])[:2]
    x = np.array([[0, 1], [1, 0]], dtype=complex)
    axial = [np.array(v, complex) / np.linalg.norm(v) for v in ([1, 1], [1, -1], [1, 1j], [1, -1j], [1, 0], [0, 1])]
    six = np.mean([abs(np.vdot(x @ p, m @ p)) ** 2 for p in axial])
    return 1 - float(compute_average_fidelity_with_leakage(x, m)), 1 - six


def test_gaussian_and_first_order_drag_reproduce_gambetta_2011():
    """契约「门仿真」: 论文 §III 的高斯 NOT 门误差 (σ = 1/3, 2/3, 3/2 × 2π/|Δ₂|: 0.198 / 0.0160 / 0.0030, 三位有效数字);
    六轴态平均 (Eq. 3.4) = Pedersen 含泄漏式 (逐位); §IV B 一阶解 (λ₁ = √2): 最优 (Eq. 4.41) < Y-only (4.36) <
    Motzoi 2009 (4.42) < Z-only < 高斯 —— 正文对 Fig. 3 的四条陈述。"""
    l1 = math.sqrt(2)
    for sigma, paper in ((1 / 3, 0.198), (2 / 3, 0.0160), (1.5, 0.0030)):
        ped, six = _sno_not_error(sigma)
        assert ped == pytest.approx(six, abs=1e-12)
        assert ped == pytest.approx(paper, rel=0.02)
    for sigma in (2 / 3, 1.5):
        err = [_sno_not_error(sigma, cy=-l1 / 2, cz=(l1 ** 2 - 2 * l1) / 4)[0],   # 一阶最优
               _sno_not_error(sigma, cy=-l1 ** 2 / 4)[0],                       # Y-only
               _sno_not_error(sigma, cy=-1.0, cz=(l1 ** 2 - 4) / 4)[0],         # Motzoi 2009
               _sno_not_error(sigma, cz=l1 ** 2 / 4)[0],                        # Z-only
               _sno_not_error(sigma)[0]]                                        # 高斯
        assert err == sorted(err), (sigma, err)
    assert err[0] < err[-1] / 1000                       # σ = 1.5: 一阶最优把高斯压三个量级以上


def test_supergrad_spectrum_and_coupling_match_circuit_model():
    """SuperGrad transmon (电荷基, n_g = 0) 的 f01 / α = circuit_model 电荷基精确能级 (逐位到 1e-9);
    J = 8β√(E_Ca E_Cb) 接成 J·n_a·n_b 后, 缀饰谱的静态 ZZ = 二阶微扰闭式 (自推, 非 RWA, 矩阵元用精确 λ = n₁₂/n₀₁):
    ``g²[λ_t²/(Δ−α_t) − λ_c²/(Δ+α_c)] + g²[λ_c²/(Σ+α_c) + λ_t²/(Σ+α_t) − λ_c²λ_t²/(Σ+α_c+α_t)]``, g = J·n₀₁·n₀₁,
    Δ = ω_c − ω_t, Σ = ω_c + ω_t。λ² = 2 时第一项 = 教科书 2g²(α₁+α₂)/((Δ+α₁)(Δ−α₂)); transmon 的 λ² ≈ 1.90,
    照抄教科书式差 4%, 反旋转项 ~1% 也不能丢。远失谐 Δ/2π ≈ −0.5 GHz, 四阶余项 (g/|Δ−α_t|)² ~ 3e-4。"""
    from quantum_dsl.circuit_model import H_PLANCK, transmon_from_spectrum, transmon_levels_hz
    from quantum_dsl.gates import _dressed

    two_pi = 2 * math.pi
    lam, (n,) = _dressed([("q", Q1["E_C_GHz"], Q1["E_J_GHz"])], 0.0, 5)
    f01, f12 = transmon_levels_hz(Q1["E_C_GHz"] * 1e9 * H_PLANCK, Q1["E_J_GHz"] * 1e9 * H_PLANCK)
    assert lam[1] / two_pi * 1e9 == pytest.approx(f01, rel=1e-9)
    assert (lam[2] - lam[1]) / two_pi * 1e9 == pytest.approx(f12, rel=1e-9)

    ec2, ej2 = (v / H_PLANCK / 1e9 for v in transmon_from_spectrum(5.3e9, -230e6))
    beta = 0.002
    j = 8 * beta * math.sqrt(Q1["E_C_GHz"] * ec2)
    lam2, (n_2,) = _dressed([("q", ec2, ej2)], 0.0, 5)
    lam12, _ = _dressed([("c", Q1["E_C_GHz"], Q1["E_J_GHz"]), ("t", ec2, ej2)], j, 5)
    g = j * two_pi * abs(n[0, 1]) * abs(n_2[0, 1])
    l1, l2 = (abs(m[1, 2] / m[0, 1]) ** 2 for m in (n, n_2))
    w1, w2, a1, a2 = lam[1], lam2[1], lam[2] - 2 * lam[1], lam2[2] - 2 * lam2[1]
    d, s = w1 - w2, w1 + w2
    zz_pert = g ** 2 * (l2 / (d - a2) - l1 / (d + a1) + l1 / (s + a1) + l2 / (s + a2) - l1 * l2 / (s + a1 + a2))
    zz = lam12[5 + 1] - lam12[5] - lam12[1]
    assert zz == pytest.approx(zz_pert, rel=2e-3)


def test_interaction_picture_matches_supergrad_lab_frame():
    """模块的演化 (对缀饰 H₀ 的精确相互作用绘景 + 步内振荡精确求积) = SuperGrad 自己的实验室系 ``Evolve``
    (同一 rampcos CR 脉冲, 积基演化 + 本征基变换, 细步长) —— 换绘景不丢物理, 只省步数。"""
    import jax
    import jax.numpy as jnp
    import numpy as np
    from supergrad.helper import Evolve
    from supergrad.scgraph.graph import SCGraph

    from quantum_dsl.gates import _dressed, _propagate

    levels, t_g, ramp, amp = 3, 40.0, 10.0, 0.6
    j = 8 * PAIR["couplings"][0]["beta"] * math.sqrt(Q1["E_C_GHz"] * Q2["E_C_GHz"])
    lam, (n_c, _) = _dressed([("c", Q1["E_C_GHz"], Q1["E_J_GHz"]), ("t", Q2["E_C_GHz"], Q2["E_J_GHz"])], j, levels)
    w_t = float(lam[1])

    def env(t):
        up, down = (1 - jnp.cos(jnp.pi * t / ramp)) / 2, (1 - jnp.cos(jnp.pi * (t_g - t) / ramp)) / 2
        return jnp.where(t < ramp, up, jnp.where(t > t_g - ramp, down, 1.0))

    u_lab = np.exp(-1j * lam * t_g)[:, None] * np.asarray(_propagate(lam, n_c, lambda t: amp * env(t), w_t, t_g))
    comp = [0, 1, levels, levels + 1]

    graph = SCGraph()
    for name, q in (("c", Q1), ("t", Q2)):
        graph.add_node(name, ec=2 * math.pi * q["E_C_GHz"], ej=2 * math.pi * q["E_J_GHz"], system_type="transmon",
                       arguments={"ng": 0.0, "phiext": 0.0, "basis": "charge", "n_max": 31, "num_basis": 62,
                                  "truncated_dim": levels})
    graph.add_edge("c", "t", capacitive_coupling={"strength": 2 * math.pi * j})
    graph.nodes["c"]["pulse"] = {"amp": amp, "t_ramp": ramp, "t_plateau": t_g - 2 * ramp, "omega_d": w_t,
                                 "phase": 0.0, "pulse_type": "rampcos", "operator_type": "n_operator", "delay": 0.0}
    evo = Evolve(graph, truncated_dim=levels, add_random=False,
                 options={"astep": int(t_g * 2000), "trotter_order": None, "custom_vjp": None})
    ref = np.asarray(jax.jit(evo.eigen_basis)(evo.all_params))
    m = u_lab[np.ix_(comp, comp)]
    m = m * np.exp(-1j * np.angle(np.trace(ref.conj().T @ m)))          # 基态能零点不同 → 只差全局相位
    assert np.abs(m - ref).max() < 2e-3
    assert np.abs(ref[2, 3]) > 0.05                                      # 真有条件翻转, 不是空比较


def test_drag_x_gate_on_transmon_calibrates_and_beats_gaussian(monkeypatch):
    """契约「门仿真」: 10 ns X 门 (σ = 2.5 ns), f01 4.8 GHz / α −249 MHz。标定后 DRAG 误差 ~1e-5 (泄漏主导),
    同法标定的高斯 > 10× 它; 拟合 β 在一阶最优 λ₁/2 (Eq. 4.41) 的 ±15% 内; 步数加倍误差变化 < 2%。"""
    from quantum_dsl import gates

    spec = {"name": "X", "kind": "x_drag", "qubit": "Q1", "t_gate_ns": 10.0, "levels": 5, "max_error": 1e-6}
    with pytest.warns(UserWarning, match=r"gates: 1/1 above max_error — X error"):
        r = gates.simulate_gates({"qubits": [Q1], "couplings": []}, [spec])[0]
    assert r["pass"] is False and r["max_error"] == 1e-6
    assert r["f01_GHz"] == pytest.approx(4.8, abs=1e-6)
    assert 3e-6 < r["error"] < 3e-5
    assert r["leakage"] == pytest.approx(r["error"], rel=0.05)         # 相位误差被 β + δ₀ 吃掉, 只剩泄漏
    assert r["gaussian_error"] > 10 * r["error"]
    assert r["drag_beta"] == pytest.approx(r["beta_first_order"], rel=0.15)
    assert r["lambda1"] == pytest.approx(math.sqrt(2), rel=0.05)      # transmon ≈ 谐振子矩阵元
    monkeypatch.setattr(gates, "STEPS_PER_NS", 2 * gates.STEPS_PER_NS)
    fine = gates.simulate_gates({"qubits": [Q1], "couplings": []}, [{**spec, "max_error": 0.1}])[0]
    assert fine["error"] == pytest.approx(r["error"], rel=0.02) and fine["pass"] is True


def test_cr_gate_calibrates_to_cnot_equivalent():
    """契约「门仿真」: Q1 (4.8) 控制 → Q2 (5.0) 目标, 240 ns 平顶 (20 ns cos 斜坡), 4 能级。
    标定幅度后 1 − max_局域 F(ZX90) < 2e-4; 幅度在一阶闭式 (Magesan & Gambetta 2020) 的 1–1.6 倍;
    静态 ZZ = 缀饰谱 (这对比特 +2.66 MHz); 未知比特名 raise。"""
    from quantum_dsl import QuantumDslError, simulate_gates

    spec = {"name": "CX", "kind": "cr", "control": "Q1", "target": "Q2", "t_gate_ns": 240.0, "ramp_ns": 20.0,
            "levels": 4}
    r = simulate_gates(PAIR, [spec])[0]
    assert r["error"] < 2e-4 and 0 < r["leakage"] <= r["error"]
    assert 1.0 < r["drive_MHz"] / r["drive_first_order_MHz"] < 1.6
    assert r["zz_static_MHz"] == pytest.approx(2.66, abs=0.05)
    assert r["detuning_MHz"] == pytest.approx(-200.6, abs=0.5)
    assert r["coupling_J_MHz"] == pytest.approx(8e3 * PAIR["couplings"][0]["beta"]
                                                * math.sqrt(Q1["E_C_GHz"] * Q2["E_C_GHz"]))
    with pytest.raises(QuantumDslError, match=r"unknown qubit\(s\) \['Q3'\]"):
        simulate_gates(PAIR, [{**spec, "target": "Q3"}])
