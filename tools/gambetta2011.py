#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Gambetta, Motzoi, Merkel & Wilhelm, PRA 83, 012308 (2011) = arXiv:1011.1949 逐图复现, 再把解析解搬到真实版图的 transmon 上
(docs/physics.md §15.1; 契约锚在 tests/test_gates.py, 用的是 SuperGrad ``sesolve`` —— 本脚本另用 Magnus-4 积分, 两套互为交叉验证)。

论文的数值全在旋转系 RWA 模型上 (Eq. 2.8): ``H = H₀ + δ(t)·H_z + Ω_x(t)/2·H_x + Ω_y(t)/2·H_y``, Δ₂ = −2π (时间单位 2π/|Δ₂|),
截断高斯 Eq. 3.2 (A = π, t_g = 4σ), NOT 门, 误差 1 − F (六轴态平均 Eq. 3.4 = Pedersen 含泄漏式)。论文里每个解析解都是同一个形式
(Eq. 4.46 再加二阶的三次项)::

    Ω_x = a·Ω_G + c₃·Ω_G³/Δ₂²,   Ω_y = −b·Ω̇_G/Δ₂,   δ = g·Ω_G²/Δ₂ + δ₀

一阶 (§IV B): Z-only (4.34) g = λ₁²/4 · Y-only (4.36) b = λ₁²/4 · Motzoi 2009 (4.42) b = 1, g = (λ₁²−4)/4 · 最优 (4.41) b = λ₁/2, g = (λ₁²−2λ₁)/4;
二阶 (§IV B 3) 只改 Ω_x: Z-only c₃ = λ₁²/8 (4.43) · Y-only c₃ = −λ₁²(λ₁²−4)/32 (4.44) · Motzoi c₃ = (λ₁²−4)/8 (4.45) · 最优解的二阶修正为零。
§V 的最优解的 δ: Eq. 5.18 排印错误 (v2 丢了 −2λ̃ 与 λ₋₁ 的平方, arXiv v1 Eq. 5.9 完整), Eq. 5.28 与 5.25 不自洽 (λ₁ → λ̃ 误用到 Stark 项)
—— 照印的算比高斯 / Z-only 还差, 与 Fig. 7/8 矛盾; 由 Eq. 5.13 / 5.25 代 s_y = −t_gΩ_Gλ̃/4 推出 ``g = (S − 2λ̃)/4``
(§V A: S = λ₁² − (Δ₂/Δ₋₁)λ₋₁²; §V B: S = Σ (Δ₂/Δ_k)λ²_{k−1}; λ̃² = Σ (Δ₂/Δ_k)²λ²) 逐条对上图, 离数值最优 γ 0.3–7%。

输出 (``build/gambetta2011/``): fig2 (高斯的频谱与布居) · fig3 (一阶) · fig4 (二阶) · fig5 (数值优化, a: δ₀ = 0, b: δ₀ 自由) ·
fig7 (上下都有泄漏) · fig8 (多个泄漏能级) · fig9 (附录 A: 经读出腔驱动的 λ₁, 标上真实版图的比特) · transmon (同一批解析解开环跑
真实版图的比特 vs ``simulate_gates`` 标定的 DRAG / 高斯) · numbers.yaml。

transmon: results.yaml 的 (E_C, E_J) → 电荷基缀饰谱 (``gates._dressed``), 实验室系不做 RWA (``gates._propagate``), λ₁ = n₁₂/n₀₁,
Δ₂ → α; δ(t) 按附录 B 的相位斜坡 ``ε → ε·e^{i∫δ}`` 实现 (固定频率比特没法真去调频率)。同时用同一组参数的 Eq. 2.8 RWA 模型
算一遍 —— 两者之差 = 反旋转项 (Bloch–Siegert) 的账。

    PYTHONPATH=src python tools/gambetta2011.py [results.yaml ...]      # 默认 build/xp_gates 与 build/xp_tune_gates 的
"""
from __future__ import annotations

import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import yaml
from scipy.optimize import minimize
from scipy.special import erf

OUT = Path("build/gambetta2011")
D2 = -2 * math.pi                                   # 论文的 Δ₂; 时间单位 2π/|Δ₂|
G1, G2 = 0.5 - math.sqrt(3) / 6, 0.5 + math.sqrt(3) / 6
STYLE = {"G": dict(color="tab:blue", ls=":", label="Gaussian (zeroth order)"),
         "Z": dict(color="k", ls="--", label="Z-only"),
         "Y": dict(color="tab:red", ls=(0, (6, 2, 1, 2, 1, 2)), label="Y-only"),
         "M": dict(color="tab:green", ls="-.", label="Motzoi 2009"),
         "O": dict(color="tab:purple", ls="-", label="optimal first order")}


# ---------------------------------------------------------------- 模型 (Eq. 2.8 及 §V 的两种能级结构)

def gauss(t, t_g, s):
    """Eq. 3.2 截断高斯 (A = π) 与导数 —— 与 ``gates.gaussian`` 同式, numpy 版。"""
    off = np.exp(-t_g ** 2 / (8 * s ** 2))
    norm = np.sqrt(2 * np.pi * s ** 2) * erf(t_g / np.sqrt(8 * s ** 2)) - t_g * off
    e = np.exp(-(t - t_g / 2) ** 2 / (2 * s ** 2))
    return math.pi * (e - off) / norm, -math.pi * (t - t_g / 2) / s ** 2 * e / norm


def system(h0, hx, hz, qubit):
    hx = np.asarray(hx, complex)                    # σ^y_{j,k} = −i|j⟩⟨k| + i|k⟩⟨j| (k > j)
    return dict(h0=np.asarray(h0, complex), hx=hx, hy=-1j * np.triu(hx) + 1j * np.tril(hx),
                hz=np.asarray(hz, complex), q=list(qubit))


def sno(d=5):
    """§III–IV: d 能级标准非线性振子, Δ_j = Δ₂ j(j−1)/2, λ_{j−1} = √j。"""
    j, lam = np.arange(d), np.sqrt(np.arange(1, d))
    return system(np.diag(D2 * j * (j - 1) / 2), np.diag(lam, 1) + np.diag(lam, -1), np.diag(j), [0, 1])


def both_sides():
    """§V A (Fig. 7): d = 6 SNO 的 2 → 3 跃迁当比特, 重标号 j = −2…3 后 Δ_j 仍是 Δ₂ j(j−1)/2, λ = √(k/3)。"""
    j, lam = np.arange(-2, 4), np.sqrt(np.arange(1, 6) / 3)
    return system(np.diag(D2 * j * (j - 1) / 2), np.diag(lam, 1) + np.diag(lam, -1), np.diag(j), [2, 3])


def many_levels():
    """§V B (Fig. 8): |1⟩ 同时连到 |2⟩…|5⟩ (λ = 1), Δ₃ = 2Δ₂, Δ₄ = 3Δ₂, Δ₅ = 4Δ₂ (Eq. 5.19–5.21)。"""
    hx = np.zeros((6, 6))
    hx[0, 1] = hx[1, 0] = 1
    hx[1, 2:] = hx[2:, 1] = 1
    return system(np.diag([0, 0, D2, 2 * D2, 3 * D2, 4 * D2]), hx, np.diag([0, 1, 2, 2, 2, 2]), [0, 1])


def rwa_of(lam, n):
    """transmon 缀饰谱 (rad/ns) + n 算符 → 同参数的 Eq. 2.8 模型: Δ_j = Λ_j − jω₀₁, λ_{j−1} = |n_{j−1,j}/n₀₁|。"""
    j = np.arange(len(lam))
    nn = np.abs(np.diag(n, 1) / n[0, 1])
    return system(np.diag(lam - j * lam[1]), np.diag(nn, 1) + np.diag(nn, -1), np.diag(j), [0, 1])


def propagate(sy, p, t_g, d2=D2, steps=None, sigma=None):
    """Eq. 2.8 的 U(t_g): 四阶 Magnus (两点 Gauss), 本征分解求步进, 成对规约。论文的误差下到 1e-11, 二阶中点法不够。"""
    sigma = t_g / 4 if sigma is None else sigma
    steps = steps or max(400, int(250 * t_g / (2 * math.pi / abs(d2))))
    a, b, g, d0, c3 = (p.get(k, v) for k, v in (("a", 1.0), ("b", 0.0), ("g", 0.0), ("d0", 0.0), ("c3", 0.0)))
    dt = t_g / steps

    def h(t):
        om, dom = gauss(t, t_g, sigma)
        ox, oy, dl = a * om + c3 * om ** 3 / d2 ** 2, -b * dom / d2, g * om ** 2 / d2 + d0
        return sy["h0"] + (ox[:, None, None] * sy["hx"] + oy[:, None, None] * sy["hy"]) / 2 + dl[:, None, None] * sy["hz"]

    k = np.arange(steps)
    h1, h2 = h((k + G1) * dt), h((k + G2) * dt)
    kk = dt / 2 * (h1 + h2) - 1j * math.sqrt(3) / 12 * dt ** 2 * (h2 @ h1 - h1 @ h2)
    w, v = np.linalg.eigh(kk)
    u = (v * np.exp(-1j * w)[:, None, :]) @ v.conj().transpose(0, 2, 1)
    return u


def total(u):
    while len(u) > 1:
        if len(u) % 2:
            u = np.concatenate([u, np.eye(u.shape[1])[None]])
        u = u[1::2] @ u[0::2]
    return u[0]


def gate_error(m):
    """计算块 M (2×2) 对 NOT 的 1 − F (Pedersen 含泄漏; d = 2 时 = Eq. 3.4)。"""
    return 1 - (np.trace(m.conj().T @ m).real + abs(m[0, 1] + m[1, 0]) ** 2) / 6


def not_error(sy, p, sigma, d2=D2):
    u = total(propagate(sy, p, 4 * sigma, d2))
    return float(gate_error(u[np.ix_(sy["q"], sy["q"])]))


# ---------------------------------------------------------------- 解族

def first_order(l1):
    return {"G": {}, "Z": dict(g=l1 ** 2 / 4), "Y": dict(b=l1 ** 2 / 4), "M": dict(b=1.0, g=(l1 ** 2 - 4) / 4),
            "O": dict(b=l1 / 2, g=(l1 ** 2 - 2 * l1) / 4)}


def second_order(l1):
    f = first_order(l1)
    return {"G": f["G"], "Z": {**f["Z"], "c3": l1 ** 2 / 8}, "Y": {**f["Y"], "c3": -l1 ** 2 * (l1 ** 2 - 4) / 32},
            "M": {**f["M"], "c3": (l1 ** 2 - 4) / 8}, "O": f["O"]}


def leakage_families(s, lt, printed_g):
    """§V 的 Z-only / Y-only / 最优 (推导式) + 照印的最优 (``O_printed``)。"""
    return {"G": {}, "Z": dict(g=s / 4), "Y": dict(b=s / 4), "O": dict(b=lt / 2, g=(s - 2 * lt) / 4),
            "O_printed": dict(b=lt / 2, g=printed_g)}


def families_va():
    l1, lm, r = math.sqrt(4 / 3), math.sqrt(2 / 3), 1.0          # r = Δ₂/Δ₋₁
    s, lt = l1 ** 2 - r * lm ** 2, math.sqrt(l1 ** 2 + r ** 2 * lm ** 2)
    return leakage_families(s, lt, (l1 ** 2 - r ** 2 * lm) / 4)   # Eq. 5.18 照印: λ₋₁ 没平方, 少 −2λ̃


def families_vb():
    r = np.array([1, 1 / 2, 1 / 3, 1 / 4])                         # Δ₂/Δ_k, λ = 1
    s, lt = float(r.sum()), float(np.sqrt((r ** 2).sum()))
    return leakage_families(s, lt, (lt ** 2 - 2 * lt) / 4)        # Eq. 5.28 照印: 第一项写成 λ̃²


# ---------------------------------------------------------------- 图

def _ax_err(ax, xlabel="pulse width σ [units 2π/|Δ₂|]"):
    ax.set_yscale("log")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Error 1 − F_g")
    ax.grid(alpha=0.3, which="both", lw=0.4)


def curves(sy, fams, sigmas):
    return {k: [not_error(sy, p, s) for s in sigmas] for k, p in fams.items()}


def fig2(plt):
    fig, axs = plt.subplots(2, 3, figsize=(12, 6.5))
    out = {}
    for col, s in enumerate((1 / 3, 2 / 3, 3 / 2)):
        t_g, f = 4 * s, np.linspace(-1.2, 1.2, 961)
        t = np.linspace(0, t_g, 4001)
        om = gauss(t, t_g, s)[0]
        spec = np.abs(np.trapezoid(om[None, :] * np.exp(-2j * np.pi * f[:, None] * t[None, :]), t, axis=1)) / math.pi
        ax = axs[0, col]
        ax.semilogy(f, spec, "k")
        ax.axvline(-1, color="tab:green", ls="--", lw=1)
        ax.set_ylim(1e-5, 2)
        ax.set_xlabel("frequency [units |Δ₂|/2π]  (dashed: 1→2 transition)")
        ax.set_title(f"σ = {s:.3g}·2π/|Δ₂|, t_g = 4σ")
        sy = sno()
        u = propagate(sy, {}, t_g, steps=800)
        psi, pops = np.eye(5)[:, 0].astype(complex), [np.eye(5)[0]]
        for uk in u:
            psi = uk @ psi
            pops.append(np.abs(psi) ** 2)
        pops = np.array(pops)
        tt = np.linspace(0, t_g, len(pops))
        ax = axs[1, col]
        for lvl, st in ((0, dict(color="tab:blue")), (1, dict(color="tab:red", ls=":")), (2, dict(color="tab:green", ls="--"))):
            ax.plot(tt, pops[:, lvl], label=f"|{lvl}⟩", **st)
        ax.set_xlabel("time [units 2π/|Δ₂|]")
        ax.set_ylabel("population")
        ax.legend(fontsize=8)
        out[round(s, 4)] = {"error": not_error(sy, {}, s), "final_P2": float(pops[-1, 2])}
    fig.suptitle("Gambetta 2011 Fig. 2 reproduction — Gaussian NOT, d = 5 SNO")
    fig.tight_layout()
    fig.savefig(OUT / "fig2.png", dpi=150)
    plt.close(fig)
    return out


def fig_families(plt, name, title, data, sigmas, keys, ylim, extra=None):
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    for k in keys:
        ax.plot(sigmas, data[k], lw=1.6, **STYLE[k[0]])
    if extra:
        extra(ax)
    _ax_err(ax)
    ax.set_ylim(*ylim)
    ax.set_title(title, fontsize=10)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / f"{name}.png", dpi=150)
    plt.close(fig)


def _optimize_one(args):
    """Fig. 5 一条曲线: 自由参数集 free, 从大 σ 往小 σ 续接 (上一点的最优当本点初值之一), Nelder–Mead 最小化 log₁₀ 误差。"""
    key, free, start, sigmas = args
    sy, best, out = sno(), None, []
    for s in sigmas[::-1]:
        trials = []
        for x0 in ([start[k] for k in free], best):
            if x0 is None:
                continue
            f = (lambda x: math.log10(max(not_error(sy, dict(zip(free, x)), s), 1e-16)))
            r = minimize(f, x0, method="Nelder-Mead",
                         options=dict(xatol=1e-7, fatol=1e-5, maxiter=4000, adaptive=True))
            trials.append(r)
        r = min(trials, key=lambda r: r.fun)
        best = list(r.x)
        out.append((s, 10 ** r.fun, dict(zip(free, map(float, r.x)))))
    return key, out[::-1]


def fig5(plt, l1):
    sigmas = list(np.round(np.linspace(0.2, 1.4, 13), 4))
    a1, f = first_order(l1), {"G": ["a"], "Z": ["a", "g"], "Y": ["a", "b"], "O": ["a", "b", "g"]}
    jobs = []
    for panel, extra in (("a", []), ("b", ["d0"])):
        for k, free in f.items():
            start = {"a": 1.0, "b": 0.0, "g": 0.0, "d0": 0.0, **a1[k]}
            jobs.append((f"{panel}{k}", free + extra, start, sigmas))
    with ProcessPoolExecutor(max_workers=8) as ex:
        res = dict(ex.map(_optimize_one, jobs))
    fig, axs = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)
    for ax, panel in zip(axs, "ab"):
        for k in "GZYO":
            ax.plot(sigmas, [e for _, e, _ in res[panel + k]], lw=1.6, **STYLE[k])
        _ax_err(ax)
        ax.set_title(f"({panel}) " + ("δ₀ = 0" if panel == "a" else "δ₀ optimized"))
        ax.set_ylim(1e-12, 1)
    axs[0].legend(fontsize=8)
    fig.suptitle("Gambetta 2011 Fig. 5 reproduction — numerically optimized first order (Eq. 4.46)")
    fig.tight_layout()
    fig.savefig(OUT / "fig5.png", dpi=150)
    plt.close(fig)
    return {k: [{"sigma": float(s), "error": float(e), **x} for s, e, x in v] for k, v in res.items()}


def fig9(plt, devices):
    x = np.linspace(-2, 1, 1201)
    lam = np.sqrt(2) / (1 + x)
    lam[np.abs(1 + x) < 0.02] = np.nan
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    zoom = ax.inset_axes([0.34, 0.06, 0.32, 0.36])     # 左下空白处 (下支在 x < −1)
    for a in (ax, zoom):
        a.plot(x, lam, color="tab:blue", label="through resonator, SNO (Eq. A10)")
        a.axhline(math.sqrt(2), color="tab:red", ls="--", label="direct drive, SNO (√2)")
        a.plot([d["x"] for d in devices], [d["lambda1_cavity_exact"] for d in devices], "ko", ms=5,
               label="our qubits via their readout resonator (Eq. A9, transmon)")
        a.plot([d["x"] for d in devices], [d["lambda1_direct"] for d in devices], "ks", ms=5, mfc="none",
               label="our qubits, direct charge drive (n₁₂/n₀₁)")
    for d in devices:
        zoom.annotate(d["label"].replace("xp_tune_gates", "tuned").replace("xp_gates", "orig"),
                      (d["x"], d["lambda1_cavity_exact"]), fontsize=6, xytext=(2, -8), textcoords="offset points")
    zoom.set_xlim(0.06, 0.12)
    zoom.set_ylim(1.2, 1.45)
    zoom.tick_params(labelsize=6)
    ax.set_ylim(-4.5, 4.5)
    ax.set_xlabel("Δ₂/(ω − ω_r)")
    ax.set_ylabel("λ₁")
    ax.axhline(0, color="k", lw=0.5, ls=":")
    ax.axvline(0, color="k", lw=0.5, ls=":")
    ax.legend(fontsize=7, loc="upper right")
    ax.set_title("Gambetta 2011 Fig. 9 (App. A) + this pipeline's qubits", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "fig9.png", dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- transmon (真实版图)

def transmon_rows(q, t_gates, levels=5):
    """同一个比特: 一阶 / 二阶解析解开环 (实验室系 + 同参数 RWA 模型) 与 simulate_gates 的标定 DRAG / 高斯。"""
    import jax.numpy as jnp
    from supergrad.utils.fidelity import compute_average_fidelity_with_leakage as fid
    from threadpoolctl import threadpool_limits

    from quantum_dsl import gates

    lam, (n,) = gates._dressed([("q", q["E_C_GHz"], q["E_J_GHz"])], 0.0, levels)
    w01, alpha, n01 = lam[1], lam[2] - 2 * lam[1], abs(n[0, 1])
    l1 = abs(n[1, 2]) / n01
    rwa, x = rwa_of(lam, n), jnp.array([[0, 1], [1, 0]], dtype=complex)
    fams = {**{k + "1": v for k, v in first_order(l1).items() if k != "G"},
            **{k + "2": v for k, v in second_order(l1).items() if k in "ZYM"}, "G0": {}}

    def lab(p, t_g):
        a, b, g, c3 = (p.get(k, v) for k, v in (("a", 1.0), ("b", 0.0), ("g", 0.0), ("c3", 0.0)))
        tt = np.linspace(0, t_g, 20001)
        dl = g * gauss(tt, t_g, t_g / 4)[0] ** 2 / alpha
        theta = np.concatenate([[0], np.cumsum((dl[1:] + dl[:-1]) / 2 * np.diff(tt))])   # 附录 B: 相位斜坡
        tt_j, th_j = jnp.asarray(tt), jnp.asarray(theta)

        def eps(t):
            g_, dg_ = gates.gaussian(t, t_g, t_g / 4)
            om, dom = math.pi * g_, math.pi * dg_
            return (a * om + c3 * om ** 3 / alpha ** 2 - 1j * b * dom / alpha) / n01 * jnp.exp(1j * jnp.interp(t, tt_j, th_j))

        m = gates._propagate(lam, n, eps, w01, t_g)[:2, :2]
        m = jnp.array([1.0, np.exp(-1j * theta[-1])])[:, None] * m
        return 1 - float(fid(x, m))

    rows = []
    with threadpool_limits(limits=1, user_api="blas"):
        for t_g in t_gates:
            cal = gates._x_drag({"qubit": q["name"], "t_gate_ns": t_g, "levels": levels}, q)
            row = {"t_gate_ns": t_g, "sigma_paper": t_g / 4 / (2 * math.pi / abs(alpha)),
                   "calibrated_drag": cal["error"], "calibrated_gaussian": cal["gaussian_error"],
                   "calibrated_beta": cal["drag_beta"], "calibrated_detuning_MHz": cal["detuning_MHz"]}
            for k, p in fams.items():
                row[f"lab_{k}"] = lab(p, t_g)
                row[f"rwa_{k}"] = not_error(rwa, p, t_g / 4, d2=alpha)
            rows.append(row)
            print(f"  {q['name']} t_g {t_g:5.1f} ns  cal {row['calibrated_drag']:.2e}  "
                  + "  ".join(f"{k} {row['lab_' + k]:.1e}" for k in fams), flush=True)
    return {"f01_GHz": w01 / 2 / math.pi, "alpha_MHz": alpha / 2 / math.pi * 1e3, "lambda1": l1, "rows": rows}


def transmon_fig(plt, tm):
    fig, axs = plt.subplots(1, len(tm), figsize=(6.2 * len(tm), 4.8), squeeze=False)
    for ax, (label, d) in zip(axs[0], tm.items()):
        t = [r["t_gate_ns"] for r in d["rows"]]
        for k, st in (("G0", "G"), ("Y1", "Y"), ("O1", "O"), ("M1", "M"), ("M2", "M")):
            sty = {**STYLE[st], "label": f"{STYLE[st]['label']}{' 2nd order' if k == 'M2' else ''} (open loop, lab frame)"}
            if k == "M2":
                sty.update(lw=2.6)
            ax.plot(t, [r[f"lab_{k}"] for r in d["rows"]], marker=".", **sty)
            ax.plot(t, [r[f"rwa_{k}"] for r in d["rows"]], color=sty["color"], lw=0.8, alpha=0.5)
        ax.plot(t, [r["calibrated_gaussian"] for r in d["rows"]], "o", color="tab:blue", mfc="none", label="Gaussian, calibrated")
        ax.plot(t, [r["calibrated_drag"] for r in d["rows"]], "o-", color="tab:orange", lw=2, label="DRAG, calibrated (pipeline)")
        _ax_err(ax, "gate time t_g [ns]  (σ = t_g/4)")
        ax.set_title(f"{label}: f01 {d['f01_GHz']:.3f} GHz, α {d['alpha_MHz']:.0f} MHz, λ₁ {d['lambda1']:.3f}\n"
                     "thin lines: same pulses in the paper's RWA model (Eq. 2.8)", fontsize=9)
        ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "transmon.png", dpi=150)
    plt.close(fig)


def _devices(paths):
    from quantum_dsl import gates

    devs, tm_qubits = [], {}
    for path in paths:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["hamiltonian"]
        label = Path(path).parent.name
        for q in doc["qubits"]:
            lam, (n,) = gates._dressed([("q", q["E_C_GHz"], q["E_J_GHz"])], 0.0, 5)
            ro = max((r for r in doc.get("readout") or [] if r["qubit"] == q["name"]), key=lambda r: r["g_MHz"], default=None)
            if ro is not None:
                f_r = next(r["f_r_GHz"] for r in doc["resonators"] if r["name"] == ro["resonator"]) * 2 * math.pi
                w01, w12 = lam[1], lam[2] - lam[1]
                x = (w12 - w01) / (w01 - f_r)                                              # Δ₂/(ω − ω_r)
                devs.append({"label": f"{label}/{q['name']}", "resonator": ro["resonator"], "x": float(x),
                             "lambda1_cavity_sno": float(math.sqrt(2) / (1 + x)),                    # Eq. A10
                             "lambda1_cavity_exact": float(abs(n[1, 2] / n[0, 1]) * (w01 - f_r) / (w12 - f_r)),   # Eq. A9
                             "lambda1_direct": float(abs(n[1, 2] / n[0, 1]))})
            if q["name"] == "Q1":
                tm_qubits[label] = q
    return devs, tm_qubits


def main(argv):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from threadpoolctl import threadpool_limits

    with threadpool_limits(limits=1, user_api="blas"):          # 小矩阵; fig5 的子进程 fork 时继承
        _main(plt, argv)


def _main(plt, argv):
    OUT.mkdir(parents=True, exist_ok=True)
    paths = argv or [p for p in ("build/xp_gates/results.yaml", "build/xp_tune_gates/results.yaml") if Path(p).exists()]
    l1, nums = math.sqrt(2), {}
    print("fig2 …", flush=True)
    nums["fig2"] = fig2(plt)
    sig = list(np.round(np.linspace(0.3, 2.5, 45), 4))
    print("fig3 / fig4 …", flush=True)
    for name, fams, title, ylim in (("fig3", first_order(l1), "Fig. 3 reproduction — first order DRAG, d = 5 SNO", (1e-7, 0.3)),
                                    ("fig4", second_order(l1), "Fig. 4 reproduction — second order (Eq. 4.43–4.45)", (1e-12, 0.3))):
        data = curves(sno(), fams, sig)
        nums[name] = {"sigma": sig, **data}
        fig_families(plt, name, title, data, sig, "GZYMO", ylim,
                     extra=lambda ax: ax.plot([1 / 3, 2 / 3, 1.5], [0.198, 0.0160, 0.0030], "kx", ms=8,
                                              label="paper §III (Gaussian)"))
    print("fig7 / fig8 …", flush=True)
    for name, sy, fams, title, ylim in (
            ("fig7", both_sides(), families_va(), "Fig. 7 reproduction — leakage above and below (§V A)", (1e-6, 0.3)),
            ("fig8", many_levels(), families_vb(), "Fig. 8 reproduction — many leakage levels (§V B)", (1e-7, 0.3))):
        data = curves(sy, fams, sig)
        nums[name] = {"sigma": sig, **data, "coefficients": fams}

        def printed(ax, data=data):
            ax.plot(sig, data["O_printed"], color="tab:purple", lw=0.8, ls=(0, (1, 1)),
                    label="optimal, δ as printed (Eq. 5.18 / 5.28)")
        fig_families(plt, name, title, data, sig, "GZYO", ylim, extra=printed)
    print("fig5 (optimization, ~minutes) …", flush=True)
    nums["fig5"] = fig5(plt, l1)
    devices, tm_qubits = _devices(paths)
    nums["fig9"] = devices
    fig9(plt, devices)
    print("transmon …", flush=True)
    tm = {label: transmon_rows(q, [4.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0, 30.0]) for label, q in tm_qubits.items()}
    nums["transmon"] = tm
    transmon_fig(plt, tm)
    nums = json.loads(json.dumps(nums))                       # np.float64 是 float 子类: json 认, yaml.safe_dump 不认
    (OUT / "numbers.yaml").write_text(yaml.safe_dump(nums, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"→ {OUT}/", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
