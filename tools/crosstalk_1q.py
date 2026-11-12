#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""真实版图上的串扰 + 单比特门优化 (10-15 组会 TODO「通过串扰优化单比特门」; plan「门仿真后续」④ 的单比特半边)。

``gates.py`` 的 X 门只在**孤立**比特上标定 (旁观比特不进)。这里把同一个 DRAG 脉冲放进两比特系统 (results.yaml 的
hamiltonian 段: 两 transmon + J = 8β√(E_Ca·E_Cb), ``gates._dressed`` 的缀饰谱), 看串扰吃掉多少, 再在两比特系统上重标定。

* 演化 = ``gates._propagate`` 的多驱动版: 缀饰基, 对 diag(Λ) 的精确相互作用绘景, 不做 RWA;
  ``H_I = Σ_k Re[ε_k(t)e^{−iω_k t}]·e^{iΛt}N_k e^{−iΛt}``, 每路驱动各自的步内振荡精确求积 (× sinc)。
* 脉冲 = ``_x_drag`` 口径: ε = π/n₀₁·amp·(Ω_G − i·β/α·Ω̇_G), t_g = 4σ; n₀₁ / α 取**孤立**比特的 (同一物理脉冲),
  载频 ω_d = ω_q − δ₀, ω_q = 两比特系统里的缀饰频率 (另一比特在 |0⟩; = 谱学实测的那个频率)。
* 保真度: 计算子空间 4 维, 每比特各自的旋转系 (被驱动的 = ω_d, 空转的 = 缀饰频率), Pedersen 含泄漏式
  (SuperGrad ``compute_average_fidelity_with_leakage``)。``bare`` = 不补偿; ``vz`` = 门前门后每比特各一个虚 Z (4 个角, 多起点)。
  孤立基线换成 4 维 = (孤立 2×2 块) ⊗ I 代进同一公式 (无泄漏时 4 维误差 = 2 维 × 6/5)。
* 场景: ``iso`` 孤立 Q1 · ``idle`` 同一脉冲 + Q2 空转 (目标 X⊗I) · ``simul`` X⊗X 各用孤立标定的脉冲 ·
  ``*_recal`` 两比特系统上重标定 (每个被驱动比特 amp / β / δ₀ + 4 个虚 Z 角, jax 梯度 + L-BFGS, 多起点) ·
  ``xt`` 经典微波串扰 (**假设值**: 版图里没有 XY 线): Q1 的驱动以幅度比 r 同相漏到 Q2 (H ⊃ r·E₁(t)·n_b)。

    PYTHONPATH=src python tools/crosstalk_1q.py [sweep|xt|check|plot ...]   # 默认全做; 产物 build/sprint/crosstalk/
"""
from __future__ import annotations

import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import yaml

from quantum_dsl.errors import QuantumDslError
from quantum_dsl.gates import STEPS_PER_NS, _dressed, _x_drag, gaussian

OUT = Path("build/sprint/crosstalk")
DEVICES = {"xp_gates": "build/xp_gates/results.yaml", "xp_tune_gates": "build/xp_tune_gates/results.yaml"}
SWEEP = {20.0: (0.5, 1.0, 2.0), 40.0: (1.0,), 30.0: (1.0,), 10.0: (1.0,)}   # 门长 → J 倍率 (J 趋势只在 20 ns 扫)
LEVELS = 4                                 # 扫描用; check 阶段在 levels 5 复核
XT_DB = (-40.0, -30.0, -20.0)
WORKERS = 4                                # 机器与别的 agent 共享
TWO_PI = 2 * math.pi
X2 = np.array([[0, 1], [1, 0]], dtype=complex)
TARGET = {"idle": np.kron(X2, np.eye(2)), "simul": np.kron(X2, X2)}


def load(path) -> dict:
    """results.yaml → {Q1, Q2: (E_C, E_J) GHz, J GHz}; 缺键 / 非正值 raise。"""
    h = (yaml.safe_load(Path(path).read_text()) or {}).get("hamiltonian") or {}
    qs = {q["name"]: (float(q["E_C_GHz"]), float(q["E_J_GHz"])) for q in h.get("qubits") or []}
    cs = h.get("couplings") or []
    if set(qs) != {"Q1", "Q2"} or len(cs) != 1 or {cs[0]["qubit_a"], cs[0]["qubit_b"]} != {"Q1", "Q2"}:
        raise QuantumDslError(f"crosstalk_1q: {path} needs hamiltonian qubits Q1, Q2 and one Q1–Q2 coupling")
    if min(v for q in qs.values() for v in q) <= 0 or not cs[0]["beta"] > 0:
        raise QuantumDslError(f"crosstalk_1q: {path} has non-positive E_C / E_J / beta")
    return {**qs, "J": 8.0 * float(cs[0]["beta"]) * math.sqrt(qs["Q1"][0] * qs["Q2"][0])}


# ---------------------------------------------------------------- 演化

def propagate(lam, drives, t_ns, spn=STEPS_PER_NS):
    """多驱动版 ``gates._propagate``: ``drives = [(N, ε(t), ω)]`` → U_I(T)。每路的 ε / ε* 两个相位频率各自步内精确求积。"""
    import jax.numpy as jnp
    from supergrad.time_evolution.ode import ode_expm

    steps = max(int(round(t_ns * spn)), 1)
    dt = t_ns / steps
    dl = jnp.asarray(lam[:, None] - lam[None, :])
    terms = []
    for op, eps, w in drives:
        lo, hi = dl - w, dl + w
        op = jnp.asarray(op)
        terms.append((eps, lo, hi, op * jnp.sinc(lo * dt / TWO_PI), op * jnp.sinc(hi * dt / TWO_PI)))

    def gen(_, t):
        h = 0
        for eps, lo, hi, a_lo, a_hi in terms:
            e = eps(t)
            h = h + e * a_lo * jnp.exp(1j * lo * t) + jnp.conj(e) * a_hi * jnp.exp(1j * hi * t)
        return -0.5j * h

    return ode_expm(gen, jnp.eye(len(lam), dtype=complex), jnp.array([0.0, t_ns]),
                    astep=steps + 1, custom_vjp=None)[-1]


def iso_pulse(q, t_g, levels=LEVELS) -> dict:
    """孤立比特的 ``_x_drag`` 标定 + 归一化量 (n₀₁, α rad/ns) —— 同一物理脉冲搬进两比特系统要用孤立的归一化。"""
    lam, (n,) = _dressed([("q", *q)], 0.0, levels)
    row = _x_drag({"qubit": "q", "levels": levels, "t_gate_ns": t_g}, {"E_C_GHz": q[0], "E_J_GHz": q[1]})
    return {"n01": float(abs(n[0, 1])), "alpha": float(np.real(lam[2] - 2 * lam[1])), "lambda1": float(row["lambda1"]),
            "amp": float(row["amp"]), "beta": float(row["drag_beta"]),
            "det": float(row["detuning_MHz"]) * TWO_PI * 1e-3, "error_2d": float(row["error"])}


def pair(dev, j_scale, levels=LEVELS) -> dict:
    """两比特缀饰系统; 节点名 a = Q1, b = Q2 → 态 |i_a i_b⟩ 的下标 i_a·d + i_b。"""
    lam, (na, nb) = _dressed([("a", *dev["Q1"]), ("b", *dev["Q2"])], dev["J"] * j_scale, levels)
    d = levels
    comp = np.array([0, 1, d, d + 1])
    if not abs(na[0, d]) > 10 * abs(na[0, 1]):
        raise QuantumDslError("crosstalk_1q: dressed-state labelling failed (n_a does not connect |00⟩–|10⟩)")
    return {"lam": lam, "na": na, "nb": nb, "d": d, "comp": comp, "w": {"a": lam[d], "b": lam[1]},
            "zz": lam[d + 1] - lam[d] - lam[1], "J": dev["J"] * j_scale}


def block(p, pulses, t_g, xt=0.0, spn=STEPS_PER_NS):
    """4×4 计算块, 每比特在自己的旋转系里。``pulses = {"a"|"b": (ref, x)}``, ref = ``iso_pulse``, x = {amp, beta, det};
    ``xt`` = Q1 驱动漏到 Q2 的幅度比 (同相, 同载频)。"""
    import jax.numpy as jnp

    drives, w = [], dict(p["w"])
    for k, (ref, x) in pulses.items():
        w[k] = p["w"][k] - x["det"]
        a, b_, al = math.pi / ref["n01"] * x["amp"], x["beta"], ref["alpha"]

        def eps(t, a=a, b_=b_, al=al):
            g, dg = gaussian(t, t_g, t_g / 4)
            return a * (g - 1j * b_ / al * dg)

        op = p["na"] + xt * p["nb"] if k == "a" else p["nb"]
        drives.append((op, eps, w[k]))
    c = p["comp"]
    m = propagate(p["lam"], drives, t_g, spn)[jnp.ix_(c, c)]
    phase = jnp.asarray(p["lam"][c]) - w["a"] * jnp.array([0, 0, 1, 1]) - w["b"] * jnp.array([0, 1, 0, 1])
    return jnp.exp(-1j * phase * t_g)[:, None] * m


def vz(phi, u):
    """门前 (phi[0:2]) 门后 (phi[2:4]) 每比特一个虚 Z: diag(1, e^{iφ}) 的张量积, 左右乘。"""
    import jax.numpy as jnp

    def diag(pa, pb):
        return jnp.kron(jnp.array([1.0, jnp.exp(1j * pa)]), jnp.array([1.0, jnp.exp(1j * pb)]))
    return diag(phi[2], phi[3])[:, None] * u * diag(phi[0], phi[1])[None, :]


def infid(target, u):
    from supergrad.utils.fidelity import compute_average_fidelity_with_leakage as fid
    return 1 - fid(target, u).real


def best_vz(target, u, starts=12, seed=0):
    """max_φ F(target, vz(φ, u)): 4 个角, L-BFGS 多起点 (零点 + 随机)。→ (误差, φ)。"""
    import jax
    import jax.numpy as jnp
    from scipy.optimize import minimize

    u = jnp.asarray(u)
    f = jax.jit(jax.value_and_grad(lambda ph: jnp.log10(infid(target, vz(ph, u)) + 1e-16)))
    rng = np.random.default_rng(seed)
    best = None
    for x0 in [np.zeros(4)] + [rng.uniform(-math.pi, math.pi, 4) for _ in range(starts - 1)]:
        r = minimize(lambda x: tuple(np.asarray(v, dtype=float) for v in f(jnp.asarray(x))), x0, jac=True,
                     method="L-BFGS-B")
        if best is None or r.fun < best.fun:
            best = r
    return float(infid(target, vz(jnp.asarray(best.x), u))), best.x


def diagnose(target, u) -> dict:
    """误差拆账: 泄漏, 以及 Q2 = |0⟩ / |1⟩ 两个条件块各自对 Q1 目标的 2 维误差 (不补偿; 块内全局相位不计)。"""
    from supergrad.utils.fidelity import compute_average_fidelity_with_leakage as fid

    u = np.asarray(u)
    t2 = np.asarray(target)[np.ix_([0, 2], [0, 2])]
    out = {"leakage": 1 - float(np.trace(u.conj().T @ u).real) / 4}
    if np.allclose(target, TARGET["idle"]):
        for s in (0, 1):
            ix = [s, 2 + s]
            out[f"err_q2_{s}"] = 1 - float(fid(t2, u[np.ix_(ix, ix)]))
    return out


def recal(p, refs, x0s, target, t_g, xt=0.0, spn=STEPS_PER_NS):
    """两比特系统上重标定: 每个被驱动比特 (amp, β, δ₀) + 4 个虚 Z 角, 最小化 log₁₀(1 − F)。多起点取最好。"""
    import jax.numpy as jnp
    from supergrad.utils.optimize import scipy_minimize

    def loss(x):
        u = block(p, {k: (refs[k], x[k]) for k in refs}, t_g, xt, spn)
        return jnp.log10(infid(target, vz(x["phi"], u)) + 1e-16)

    best = None
    for x0 in x0s:
        x0 = {k: ({kk: jnp.asarray(float(vv)) for kk, vv in v.items()} if k != "phi" else jnp.asarray(v))
              for k, v in x0.items()}
        r = scipy_minimize(loss, x0, method="L-BFGS-B", options={"maxiter": 300})
        if best is None or r.fun < best.fun:
            best = r
    x = best.x
    u = np.asarray(block(p, {k: (refs[k], x[k]) for k in refs}, t_g, xt, spn))
    return x, u


# ---------------------------------------------------------------- 场景

def _f(x):
    return float(np.asarray(x).real)


def _params(x, refs) -> dict:
    return {k: {"amp": _f(x[k]["amp"]), "beta": _f(x[k]["beta"]), "det_MHz": _f(x[k]["det"]) / TWO_PI * 1e3}
            for k in refs}


def _x(ref):
    return {k: ref[k] for k in ("amp", "beta", "det")}


def scenario(p, refs, target, t_g, xt=0.0, starts=3) -> dict:
    """同一 (孤立标定) 脉冲: 不补偿 / 虚 Z; 再在 p 上重标定 (多起点: 孤立值 + 最优虚 Z, 一阶闭式, 载频移到两个条件频率中点 ω_q + ζ/2)。"""
    u = np.asarray(block(p, {k: (refs[k], _x(refs[k])) for k in refs}, t_g, xt))
    e_vz, phi = best_vz(target, u)
    row = {"bare": float(infid(target, u)), "vz": e_vz, **diagnose(target, u)}
    x0s = [{**{k: _x(refs[k]) for k in refs}, "phi": phi},
           {**{k: {"amp": 1.0, "beta": refs[k]["lambda1"] / 2, "det": 0.0} for k in refs}, "phi": np.zeros(4)},
           {**{k: {**_x(refs[k]), "det": refs[k]["det"] - p["zz"] / 2} for k in refs}, "phi": phi}][:starts]
    x, u2 = recal(p, refs, x0s, target, t_g, xt)
    e2, _ = best_vz(target, vz(x["phi"], u2))           # 重标定的角再精修一遍 (只会更好)
    row.update(recal=min(e2, float(infid(target, vz(x["phi"], u2)))),
               recal_diag=diagnose(target, vz(x["phi"], u2)), recal_params=_params(x, refs))
    return row


def run_config(dev_name, t_g, j_scales, levels=LEVELS) -> list[dict]:
    """一个器件 × 一个门长: 孤立标定 Q1 / Q2 各一次, 然后每个 J 倍率跑 idle / simul 两个场景。"""
    _limits()
    dev = load(DEVICES[dev_name])
    refs = {"a": iso_pulse(dev["Q1"], t_g, levels), "b": iso_pulse(dev["Q2"], t_g, levels)}
    p0 = pair(dev, 0.0, levels)
    u0 = np.asarray(block(p0, {"a": (refs["a"], _x(refs["a"]))}, t_g))
    rows = []
    for js in j_scales:
        try:
            p = pair(dev, js, levels)
        except QuantumDslError as exc:                # 强杂化: |11⟩ 没有定义, 记下来不算 (表里标出)
            rows.append({"device": dev_name, "t_gate_ns": t_g, "J_scale": js, "levels": levels, "skipped": str(exc)})
            print(f"[{dev_name} {t_g:g} ns J×{js:g}] SKIPPED: {exc}", flush=True)
            continue
        rows.append({"device": dev_name, "t_gate_ns": t_g, "J_scale": js, "levels": levels,
                     "J_MHz": p["J"] * 1e3, "zz_MHz": p["zz"] / TWO_PI * 1e3,
                     "f_Q1_GHz": p["w"]["a"] / TWO_PI, "f_Q2_GHz": p["w"]["b"] / TWO_PI,
                     "f_Q2_12_GHz": (p["lam"][2] - p["lam"][1]) / TWO_PI,
                     "iso_2d": refs["a"]["error_2d"], "iso": float(infid(TARGET["idle"], u0)),
                     "iso_params": {k: {"amp": r["amp"], "beta": r["beta"], "det_MHz": r["det"] / TWO_PI * 1e3}
                                    for k, r in refs.items()},
                     "idle": scenario(p, {"a": refs["a"]}, TARGET["idle"], t_g),
                     "simul": scenario(p, refs, TARGET["simul"], t_g)})
        print(f"[{dev_name} {t_g:g} ns J×{js:g}] iso {rows[-1]['iso']:.2e}  idle bare/vz/recal "
              f"{rows[-1]['idle']['bare']:.2e}/{rows[-1]['idle']['vz']:.2e}/{rows[-1]['idle']['recal']:.2e}  simul "
              f"{rows[-1]['simul']['bare']:.2e}/{rows[-1]['simul']['vz']:.2e}/{rows[-1]['simul']['recal']:.2e}",
              flush=True)
    return rows


def run_xt(dev_name, j_scale, t_g=20.0, dbs=XT_DB, levels=LEVELS) -> list[dict]:
    """经典微波串扰 (假设值): Q1 驱动以 r = 10^(dB/20) 同相漏到 Q2, Q2 空转, 目标 X⊗I。"""
    _limits()
    dev = load(DEVICES[dev_name])
    refs = {"a": iso_pulse(dev["Q1"], t_g, levels)}
    p = pair(dev, j_scale, levels)
    rows = []
    for db in dbs:
        r = scenario(p, refs, TARGET["idle"], t_g, xt=10 ** (db / 20), starts=1)
        rows.append({"device": dev_name, "J_scale": j_scale, "t_gate_ns": t_g, "xt_dB": db, **r})
        print(f"[xt {dev_name} J×{j_scale:g} {db:g} dB] bare/vz/recal {r['bare']:.2e}/{r['vz']:.2e}/{r['recal']:.2e}",
              flush=True)
    return rows


def check(rows) -> list[dict]:
    """收敛检查: 每个器件 J×1 / 20 ns 的重标定脉冲, 步数加倍、levels 4 → 5 各重算一次 (同一组参数, 虚 Z 重新优化)。"""
    import jax.numpy as jnp

    _limits()
    out = []
    for r in rows:
        if r["J_scale"] != 1.0 or r["t_gate_ns"] != 20.0:
            continue
        dev = load(DEVICES[r["device"]])
        refs = {"a": iso_pulse(dev["Q1"], 20.0, r["levels"]), "b": iso_pulse(dev["Q2"], 20.0, r["levels"])}
        for sc in ("idle", "simul"):
            rr = {k: refs[k] for k in ("a",) + (("b",) if sc == "simul" else ())}
            x = {k: {"amp": jnp.asarray(v["amp"]), "beta": jnp.asarray(v["beta"]),
                     "det": jnp.asarray(v["det_MHz"] * TWO_PI * 1e-3)} for k, v in r[sc]["recal_params"].items()}
            res = {"device": r["device"], "scenario": sc, "base": r[sc]["recal"]}
            for tag, levels, spn in (("steps_x2", r["levels"], 2 * STEPS_PER_NS), ("levels_5", 5, STEPS_PER_NS)):
                u = np.asarray(block(pair(dev, 1.0, levels), {k: (rr[k], x[k]) for k in rr}, 20.0, spn=spn))
                res[tag] = best_vz(TARGET[sc], u)[0]
            out.append(res)
            print(f"[check {r['device']} {sc}] {res}", flush=True)
    return out


def _limits():
    """小矩阵 BLAS 单线程 (gates.py: 25 维 expm 多线程慢 ~100×); 必须在 scipy / supergrad 载入**之后**设, 否则管不到。"""
    import scipy.linalg  # noqa: F401
    import supergrad  # noqa: F401
    from threadpoolctl import threadpool_limits
    threadpool_limits(limits=1, user_api="blas")


# ---------------------------------------------------------------- 图表

COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"]   # dataviz 参考色板, 固定顺序
CURVES = [("iso", "isolated Q1 (X⊗I, 4-dim)", "o", "-"),
          (("idle", "bare"), "Q2 idle, same pulse", "s", "--"),
          (("idle", "vz"), "Q2 idle, + virtual Z", "s", "-"),
          (("idle", "recal"), "Q2 idle, re-calibrated", "s", ":"),
          (("simul", "vz"), "X⊗X, isolated pulses + VZ", "^", "-"),
          (("simul", "recal"), "X⊗X, re-calibrated", "^", ":")]


def _get(r, key):
    return r[key] if isinstance(key, str) else r[key[0]][key[1]]


def plot(rows, xt_rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    devs = [d for d in DEVICES if any(r["device"] == d for r in rows)]
    for xkey, fixed, fname, xlabel in (("t_gate_ns", ("J_scale", 1.0), "vs_tgate.png", "gate length t_g (ns)"),
                                      ("zz_MHz", ("t_gate_ns", 20.0), "vs_coupling.png",
                                       "static ZZ ζ/2π (MHz)  [J × 0.5, 1, 2]")):
        fig, axes = plt.subplots(1, len(devs), figsize=(5.2 * len(devs), 4.2), sharey=True, squeeze=False)
        for ax, dev in zip(axes[0], devs):
            sel = sorted((r for r in rows if r["device"] == dev and r[fixed[0]] == fixed[1]), key=lambda r: r[xkey])
            xs = [abs(r[xkey]) for r in sel]
            for c, (key, label, mk, ls) in zip(COLORS, CURVES):
                ax.plot(xs, [max(_get(r, key), 1e-12) for r in sel], color=c, marker=mk, ls=ls, lw=2, ms=6, label=label)
            ax.set_yscale("log")
            if xkey == "zz_MHz":
                ax.set_xscale("log")
            ax.set_title(f"{dev}  ({fixed[0]} = {fixed[1]:g})", fontsize=10)
            ax.set_xlabel(xlabel)
            ax.grid(alpha=0.25, which="both", lw=0.5)
        axes[0][0].set_ylabel("1 − F (4-dim, with leakage)")
        axes[0][-1].legend(fontsize=8, loc="best")
        fig.tight_layout()
        fig.savefig(OUT / fname, dpi=130)
        plt.close(fig)
    if xt_rows:
        fig, axes = plt.subplots(1, len(devs), figsize=(5.2 * len(devs), 4.2), sharey=True, squeeze=False)
        for ax, dev in zip(axes[0], devs):
            for i, js in enumerate(sorted({r["J_scale"] for r in xt_rows})):
                sel = sorted((r for r in xt_rows if r["device"] == dev and r["J_scale"] == js), key=lambda r: r["xt_dB"])
                for j, (key, label, ls) in enumerate((("vz", "same pulse + VZ", "-"), ("recal", "re-calibrated Q1", ":"))):
                    ax.plot([r["xt_dB"] for r in sel], [max(r[key], 1e-12) for r in sel], color=COLORS[2 * i + j],
                            marker="os"[i], ls=ls, lw=2, ms=6, label=f"J×{js:g}: {label}")
            ax.set_yscale("log")
            ax.set_title(f"{dev}  (t_g = 20 ns, Q2 idle; r is ASSUMED)", fontsize=10)
            ax.set_xlabel("microwave crosstalk Q1 drive → Q2, 20·log10 r (dB)")
            ax.grid(alpha=0.25, which="both", lw=0.5)
        axes[0][0].set_ylabel("1 − F (4-dim, with leakage)")
        axes[0][-1].legend(fontsize=8, loc="best")
        fig.tight_layout()
        fig.savefig(OUT / "vs_xy_crosstalk.png", dpi=130)
        plt.close(fig)


def table(rows) -> str:
    """markdown 表: 器件 × 门长 × J 倍率 × 场景。"""
    head = ("| 器件 | t_g | J× | J / ζ (MHz) | 孤立 | 空转 不补偿 | 空转 +VZ | 空转 泄漏 | 空转 Q2=1 条件块 | 空转 重标定 | "
            "X⊗X +VZ | X⊗X 重标定 |\n|" + "---|" * 12)
    lines = [head]
    for r in sorted(rows, key=lambda r: (list(DEVICES).index(r["device"]), r["J_scale"], r["t_gate_ns"])):
        i, s = r["idle"], r["simul"]
        lines.append(f"| {r['device']} | {r['t_gate_ns']:g} | {r['J_scale']:g} | {r['J_MHz']:.2f} / {r['zz_MHz']:.3g} | "
                     f"{r['iso']:.1e} | {i['bare']:.1e} | {i['vz']:.1e} | {i['leakage']:.1e} | {i['err_q2_1']:.1e} | "
                     f"**{i['recal']:.1e}** | {s['vz']:.1e} | **{s['recal']:.1e}** |")
    return "\n".join(lines)


def main(argv):
    import multiprocessing as mp

    OUT.mkdir(parents=True, exist_ok=True)
    missing = [d for d, p in DEVICES.items() if not Path(p).exists()]
    if "xp_gates" in missing:
        raise QuantumDslError(f"crosstalk_1q: {DEVICES['xp_gates']} missing — run examples/xmon_pair first")
    for d in missing:
        print(f"[skip] {DEVICES.pop(d)} missing — only the original layout")
    stages = argv or ["sweep", "xt", "check", "plot"]
    ctx = mp.get_context("spawn")                       # jax 不能 fork
    jobs = ([("sweep.json", run_config, (d, t, js)) for t, js in SWEEP.items() for d in DEVICES] * ("sweep" in stages)
            + [("xt.json", run_xt, (d, js)) for d in DEVICES for js in (0.0, 1.0)] * ("xt" in stages))
    if jobs:                                            # 一个池, 长任务先发; 每完成一个就落盘 (中途 raise 不丢已算的)
        done = {f: [] for f, _, _ in jobs}
        with ProcessPoolExecutor(WORKERS, mp_context=ctx) as ex:
            futs = {ex.submit(fn, *args): f for f, fn, args in jobs}
            for fut in as_completed(futs):
                done[futs[fut]] += fut.result()
                (OUT / futs[fut]).write_text(json.dumps(done[futs[fut]], indent=1))
    rows = [r for r in json.loads((OUT / "sweep.json").read_text()) if "skipped" not in r]
    if "check" in stages:
        (OUT / "check.json").write_text(json.dumps(check(rows), indent=1))
    if "plot" in stages:
        xt_path = OUT / "xt.json"
        plot(rows, json.loads(xt_path.read_text()) if xt_path.exists() else [])
        (OUT / "table.md").write_text(table(rows) + "\n")
        print(table(rows))


if __name__ == "__main__":
    main(sys.argv[1:])
