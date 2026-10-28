# -*- coding: utf-8 -*-
"""门级时间演化 (契约「门仿真」): results 的 hamiltonian 段 → SuperGrad → 标定后的单比特 DRAG X 门 / 两比特 CR 门。

管线的最后一段: 逆电容 LOM 给出每个 transmon 的 (E_C, E_J) 与成对 β; 这里原样交给 SuperGrad
(``Transmon`` 电荷基 n_g = 0 + ``capacitive_coupling`` J·n_a·n_b), 在缀饰本征基里含时演化、标定脉冲、报门误差。
口径与实测账 = docs/physics.md §15:

* 耦合: H = ½QᵀC'⁻¹Q, Q = 2e·n ⇒ J_ab = 4e²[C'⁻¹]_ab/h = **8β·√(E_C,a·E_C,b)** (只用 results 里已有的量)。
  β 是绝对值: 两比特对里 J 变号 = 对一个比特做宇称变换 (缀饰基里对角 ±1, 局域), 不改任何保真度。
* 演化: 对缀饰空转哈密顿量 H₀ = diag(Λ) 的**精确**相互作用绘景, 不做 RWA:
  ``i dU_I/dt = E(t)·e^{iΛt} N e^{−iΛt} U_I`` (N = 被驱动比特的 n, 缀饰基), SuperGrad ``ode_expm`` 中点指数积分。
  实验室系同一问题 (SuperGrad ``Evolve``) 的换位子误差里有 ~30 rad/ns 的 H₀, 要 ~20× 步数; 测试交叉验证过两者。
* **X 门** (Gambetta, Motzoi, Merkel & Wilhelm, PRA 83, 012308 (2011) = arXiv:1011.1949):
  Eq. 3.2 截断高斯 (t_g = 4σ, 单位面积) → ``E(t) = A·[Ω_G cos ω_d t − (β/Δ)·Ω̇_G sin ω_d t]``, Δ = 2π·α (rad/ns),
  A = π/n₀₁ × ``amp``。标定 (amp, β, δ₀ = ω₀₁ − ω_d) = 论文 §IV C 的「x 高斯 + y 导数 + 常失谐」族 (Eq. 4.46, γ = 0),
  SuperGrad 的 jax 梯度 + L-BFGS 最小化 log₁₀(1 − F), 初值 = 一阶最优闭式 β = λ₁/2 (Eq. 4.41, λ₁ = n₁₂/n₀₁)。
  同法标定 β ≡ 0 给高斯基线 (DRAG 的收益 = 两者之比)。F = 计算子空间平均门保真度含泄漏 (Pedersen 2007; d = 2 时
  = 论文 Eq. 3.4 的六轴态平均, 测试逐位对过), 在驱动系里比, **不给**虚 Z 补偿 (论文口径: 相位误差算误差)。
* **CR 门** (Rigetti & Devoret 2010; Chow 2011): 控制比特上平顶 cos 斜坡脉冲, 频率 = 目标比特缀饰频率;
  误差 = 1 − max_{前后任意单比特旋转} F(ZX90) (SuperGrad ``compute_fidelity_with_1q_rotation_axis``, arbit_single;
  ZX90 与 CNOT 局域等价) —— 即假定单比特门理想。驱动相位 / 小失谐只是目标比特的局域系变换, 被补偿吸收,
  所以只标定幅度 (有界一维搜索, 区间只含 ZX 角 π/4 那一瓣); 初值 = 一阶闭式
  ``c_ZX = −(gΩ/2)·α_c/(Δ(Δ+α_c))`` (H ⊃ c_ZX·Z⊗X, g = J·n₀₁·n₀₁; Magesan & Gambetta PRA 101, 052308 (2020))。

ponytail: 只演化门涉及的比特 (旁观比特 / 读出腔不进), 无退相干; 要加时往 ``_dressed`` 的 SCGraph 里加节点 / 改 mesolve。
依赖 SuperGrad (``pip install -e '.[gates]'``, 拉 jax / dm-haiku / scipy), 全部惰性 import (契约「import 纯度」)。
"""

from __future__ import annotations

import math
import warnings

from .errors import QuantumDslError

__all__ = ["GATE_KINDS", "simulate_gates"]

GATE_KINDS = ("x_drag", "cr")
STEPS_PER_NS = 50          # 相互作用绘景中点步数; 测试锚了步数加倍时门误差的变化
_TWO_PI = 2.0 * math.pi


def _supergrad():
    """``.[gates]`` 装没装; build / tune 在第一次 FEM 之前就调 (缺依赖不能等解完才 raise)。"""
    try:
        import supergrad  # noqa: F401  (import 时打开 jax x64)
    except ImportError as exc:
        raise QuantumDslError("gates: needs SuperGrad — pip install -e '.[gates]' "
                              "(pulls jax / dm-haiku / scipy)") from exc


def _dressed(qubits, j_ghz: float, levels: int):
    """SuperGrad 静态系统: ``qubits = [(节点名, E_C GHz, E_J GHz)]`` (+ 两个时的耦合 J GHz) →
    (Λ rad/ns 以基态为零, [各比特 n 算符 (缀饰基)])。缀饰态按裸积基标签排 (节点按名字排序, 调用方用 'c' < 't')。"""
    import jax.numpy as jnp
    import numpy as np
    from supergrad.helper import Helper
    from supergrad.scgraph.graph import SCGraph
    from supergrad.utils.utility import identity_wrap

    graph = SCGraph()
    for name, e_c, e_j in qubits:
        graph.add_node(name, ec=_TWO_PI * e_c, ej=_TWO_PI * e_j, system_type="transmon",
                       arguments={"ng": 0.0, "phiext": 0.0, "basis": "charge", "n_max": 31, "num_basis": 62,
                                  "truncated_dim": levels})
    if len(qubits) == 2:
        graph.add_edge(qubits[0][0], qubits[1][0], capacitive_coupling={"strength": _TWO_PI * j_ghz})

    class Static(Helper):
        def _init_quantum_system(self):
            self.hilbertspace = self.graph.convert_graph_to_quantum_system(
                add_random=False, share_params=False, truncated_dim=levels)

        def matrices(self):
            hs = self.hilbertspace
            u = hs.compute_transform_matrix()            # 积基 → 缀饰本征基
            lam = jnp.real(jnp.diag(u.conj().T @ hs.idling_hamiltonian_in_prod_basis().full() @ u))
            return lam, [u.conj().T @ identity_wrap(hs[name].n_operator, hs.subsystem_list).full() @ u
                         for name, _, _ in qubits]

    st = Static()
    st.graph, st.share_params, st.unify_coupling = graph, False, False
    lam, ns = st.matrices(st.all_params)
    lam = np.asarray(lam)
    return lam - lam[0], [np.asarray(n) for n in ns]


def _propagate(lam, drive, eps, w_d: float, t_ns: float):
    """U_I(T): 对 diag(Λ) 的相互作用绘景, ``i dU/dt = E(t)·e^{iΛt} N e^{−iΛt} U``, 驱动 ``E(t) = Re[ε(t)·e^{−iω_d t}]``
    (ε = 慢复包络)。SuperGrad ode_expm 每步取**步内平均**的 H_I: 包络取中点, 快相位 e^{iνt} 精确积分 (× sinc(ν·dt/2))
    —— 一阶 Magnus + 振荡项精确求积, 仍是厄米。只在中点取样相位的话, 2ω_d … 4ω_d 的反旋转项要逐周期分辨
    (两比特 5 能级 50 步/ns 时 CR 泄漏差 20%); 这样步数只受包络与换位子限制。"""
    import jax.numpy as jnp
    from supergrad.time_evolution.ode import ode_expm

    steps = max(int(round(t_ns * STEPS_PER_NS)), 1)
    dt = t_ns / steps
    dl = jnp.asarray(lam[:, None] - lam[None, :])
    lo, hi = dl - w_d, dl + w_d                       # ε 项 / ε* 项的相位频率 (w_d 可以是被求导的量)
    op = jnp.asarray(drive)
    a_lo = op * jnp.sinc(lo * dt / (2 * math.pi))     # jnp.sinc(x) = sin(πx)/(πx)
    a_hi = op * jnp.sinc(hi * dt / (2 * math.pi))

    def gen(_, t):
        e = eps(t)
        return -0.5j * (e * a_lo * jnp.exp(1j * lo * t) + jnp.conj(e) * a_hi * jnp.exp(1j * hi * t))

    return ode_expm(gen, jnp.eye(len(lam), dtype=complex), jnp.array([0.0, t_ns]),
                    astep=steps + 1, custom_vjp=None)[-1]


def gaussian(t, t_g, sigma):
    """Gambetta 2011 Eq. 3.2 截断高斯 (单位面积, 两端为零) 与其时间导数。"""
    import jax.numpy as jnp
    from jax.scipy.special import erf

    off = jnp.exp(-t_g ** 2 / (8 * sigma ** 2))
    norm = jnp.sqrt(2 * jnp.pi * sigma ** 2) * erf(t_g / jnp.sqrt(8 * sigma ** 2)) - t_g * off
    e = jnp.exp(-(t - t_g / 2) ** 2 / (2 * sigma ** 2))
    return (e - off) / norm, -(t - t_g / 2) / sigma ** 2 * e / norm


def _x_drag(spec: dict, q: dict) -> dict:
    import jax.numpy as jnp
    import numpy as np
    from supergrad.utils.fidelity import compute_average_fidelity_with_leakage as fid
    from supergrad.utils.optimize import scipy_minimize

    lam, (n,) = _dressed([("q", q["E_C_GHz"], q["E_J_GHz"])], 0.0, spec["levels"])
    w01, alpha = lam[1], lam[2] - 2 * lam[1]
    n01 = abs(n[0, 1])
    lam1 = abs(n[1, 2]) / n01
    t_g = spec["t_gate_ns"]
    target = jnp.array([[0, 1], [1, 0]], dtype=complex)

    def block(x):
        """驱动系 (ω_d = ω01 − δ₀) 里的 2×2 计算块: U = e^{−i(Λ − ω_d·N)T}·U_I。"""
        def eps(t):                                   # ε = Ωx + iΩy ⇔ E = Ωx cos ω_d t + Ωy sin ω_d t
            g, dg = gaussian(t, t_g, t_g / 4)
            return math.pi / n01 * x["amp"] * (g - 1j * x["beta"] / alpha * dg)

        m = _propagate(lam, n, eps, w01 - x["detuning"], t_g)[:2, :2]
        return jnp.array([1.0, jnp.exp(-1j * x["detuning"] * t_g)])[:, None] * m

    def calibrate(x0, **fixed):
        res = scipy_minimize(lambda x: jnp.log10(1 - fid(target, block({**x, **fixed}))), x0,
                             method="L-BFGS-B", options={"maxiter": 200})
        x = {**res.x, **fixed}
        m = np.asarray(block(x))
        return x, 1 - float(fid(target, m)), 1 - float(np.trace(m.conj().T @ m).real) / 2

    one, zero = jnp.asarray(1.0), jnp.asarray(0.0)
    x, err, leak = calibrate({"amp": one, "beta": jnp.asarray(lam1 / 2), "detuning": zero})
    err_g = calibrate({"amp": one, "detuning": zero}, beta=zero)[1]
    return {"qubit": spec["qubit"], "f01_GHz": w01 / _TWO_PI, "anharmonicity_MHz": alpha / _TWO_PI * 1e3,
            "error": err, "leakage": leak, "gaussian_error": err_g,
            "amp": float(x["amp"]), "drag_beta": float(x["beta"]), "beta_first_order": lam1 / 2,
            "lambda1": lam1, "detuning_MHz": float(x["detuning"]) / _TWO_PI * 1e3}


def _cr(spec: dict, qc: dict, qt: dict, beta: float) -> dict:
    import jax
    import jax.numpy as jnp
    import numpy as np
    from scipy.optimize import minimize_scalar
    from supergrad.utils.fidelity import compute_fidelity_with_1q_rotation_axis

    d = spec["levels"]
    j_ghz = 8.0 * beta * math.sqrt(qc["E_C_GHz"] * qt["E_C_GHz"])
    lam, (n_c, n_t) = _dressed([("c", qc["E_C_GHz"], qc["E_J_GHz"]), ("t", qt["E_C_GHz"], qt["E_J_GHz"])],
                               j_ghz, d)
    comp = np.array([0, 1, d, d + 1])                      # |c t⟩ = 00, 01, 10, 11
    w_c, w_t = lam[d], lam[1]
    zz = lam[d + 1] - w_c - w_t
    alpha_c = lam[2 * d] - 2 * w_c
    delta = w_c - w_t
    g = j_ghz * _TWO_PI * abs(n_c[0, d]) * abs(n_t[0, 1])   # 交换耦合 (缀饰矩阵元近似裸的, 只进初值)
    t_g, ramp = spec["t_gate_ns"], spec["ramp_ns"]
    c_zx = -(g / 2) * alpha_c / (delta * (delta + alpha_c))   # 每单位 Ω 的 ZX 系数 (一阶)
    omega0 = (math.pi / 4) / (abs(c_zx) * (t_g - ramp))   # cos 斜坡平顶的面积 = (t_g − ramp)·Ω
    amp0 = omega0 / abs(n_c[0, d])
    resid = jnp.asarray(np.array([0.0, 0.0, 0.0, zz]))      # 每比特各自缀饰频率的旋转系里只剩 ZZ 相位
    zx90 = jax.scipy.linalg.expm(-1j * math.pi / 4 * jnp.kron(jnp.diag(jnp.array([1.0, -1.0])),
                                                             jnp.array([[0.0, 1.0], [1.0, 0.0]])))

    def envelope(t):
        up, down = (1 - jnp.cos(jnp.pi * t / ramp)) / 2, (1 - jnp.cos(jnp.pi * (t_g - t) / ramp)) / 2
        return jnp.where(t < ramp, up, jnp.where(t > t_g - ramp, down, 1.0))

    @jax.jit
    def block(amp):
        m = _propagate(lam, n_c, lambda t: amp * envelope(t), w_t, t_g)[jnp.ix_(comp, comp)]
        return jnp.exp(-1j * resid * t_g)[:, None] * m

    best = jax.jit(lambda m: compute_fidelity_with_1q_rotation_axis(
        zx90, m, opt_method="lbfgs", compensation_option="arbit_single")[0])
    lo, hi = 0.4 * amp0, 2.2 * amp0          # ZX 角 π/4 那一瓣; 0 与 2×、3× 处是局域 / 另一个 CNOT 等价点
    res = minimize_scalar(lambda a: float(1 - best(block(a))), bounds=(lo, hi), method="bounded",
                          options={"xatol": 1e-5 * amp0})
    if not lo * 1.01 < res.x < hi * 0.99:
        warnings.warn(f"gates: CR {spec['name']!r} amplitude calibration ended on its search bound "
                      f"({res.x / amp0:.2f}× the first-order estimate) — the ZX90 lobe is outside "
                      f"[0.4, 2.2]× first order; the reported error is not a calibrated optimum", stacklevel=3)
    m = np.asarray(block(res.x))
    return {"control": spec["control"], "target": spec["target"], "ramp_ns": ramp,
            "error": float(res.fun), "leakage": 1 - float(np.trace(m.conj().T @ m).real) / 4,
            "zz_static_MHz": zz / _TWO_PI * 1e3, "detuning_MHz": delta / _TWO_PI * 1e3,
            "drive_MHz": res.x * abs(n_c[0, d]) / _TWO_PI * 1e3, "drive_first_order_MHz": omega0 / _TWO_PI * 1e3,
            "coupling_J_MHz": j_ghz * 1e3}


def simulate_gates(hamiltonian: dict, gates) -> list[dict]:
    """results.yaml 的 ``hamiltonian`` 段 (qubits 的 E_C_GHz / E_J_GHz, couplings 的 β) + 门声明 (``load_meta`` 校验后的
    ``gates`` 条目: name, kind, t_gate_ns, levels, qubit │ control + target [, ramp_ns][, max_error]) → 每门一条结果。
    声明了 ``max_error`` 的门另有 ``pass``, 未达标只 warn (与 targets 同: 偏差是要报的信息)。"""
    _supergrad()
    from threadpoolctl import threadpool_limits

    qubits = {q["name"]: q for q in hamiltonian.get("qubits") or []}
    betas = {frozenset((c["qubit_a"], c["qubit_b"])): c["beta"] for c in hamiltonian.get("couplings") or []}
    # OpenBLAS 多线程与 XLA 线程池争抢: jax 的 CPU expm 在 ≥ 24 维 (两比特 levels 5 = 25) 每步 12 ms,
    # 单线程 60–80 µs (实测 2026-10-28, 20 核 WSL)。小矩阵 BLAS 本来就不该开线程。
    with threadpool_limits(limits=1, user_api="blas"):
        return _simulate(qubits, betas, gates)


def _simulate(qubits, betas, gates) -> list[dict]:
    out = []
    for spec in gates:
        names = [spec["qubit"]] if spec["kind"] == "x_drag" else [spec["control"], spec["target"]]
        missing = [n for n in names if n not in qubits]
        if missing:
            raise QuantumDslError(f"gates: {spec['name']!r} names unknown qubit(s) {missing}; "
                                  f"hamiltonian has {sorted(qubits)}")
        if spec["kind"] == "x_drag":
            row = _x_drag(spec, qubits[names[0]])
        else:
            row = _cr(spec, qubits[names[0]], qubits[names[1]], betas[frozenset(names)])
        row = {"name": spec["name"], "kind": spec["kind"], "t_gate_ns": spec["t_gate_ns"],
               "levels": spec["levels"], **{k: v.item() if hasattr(v, "item") else v for k, v in row.items()}}
        if "max_error" in spec:
            row.update(max_error=spec["max_error"], **{"pass": row["error"] <= spec["max_error"]})
        out.append(row)
    missed = [r for r in out if r.get("pass") is False]
    if missed:
        warnings.warn(f"gates: {len(missed)}/{len(out)} above max_error — " + "; ".join(
            f"{r['name']} error {r['error']:.3g} > {r['max_error']:.3g}" for r in missed), stacklevel=3)
    return out
