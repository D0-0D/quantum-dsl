# -*- coding: utf-8 -*-
"""tools/crosstalk_1q.py: 两比特系统里的单比特门串扰 (冲刺工具, 不是契约; 要 SuperGrad, 没装整文件 skip)。

快测 (levels 3, 10 ns 门; 重标定 10 步/ns): ① J = 0 时两比特计算块 = 孤立 2×2 块 ⊗ I (多驱动传播子 = ``gates._propagate``);
② 有耦合时 重标定 ≤ 同一脉冲 + 虚 Z ≤ 不补偿。"""
from __future__ import annotations

import math
import sys

import numpy as np
import pytest

from conftest import ROOT

pytest.importorskip("supergrad")
sys.path.insert(0, str(ROOT / "tools"))
import crosstalk_1q as X  # noqa: E402

# xmon_pair_tune 综合终版 (同 test_gates.py 的 PAIR)
DEV = {"Q1": (0.22146443584270326, 14.294990715992935), "Q2": (0.22182758856060428, 15.427980784044026),
       "J": 8 * 0.00327566610257095 * math.sqrt(0.22146443584270326 * 0.22182758856060428)}
LV, SPN, TG = 3, 10, 10.0


@pytest.fixture(scope="module")
def ref():
    X._limits()
    return X.iso_pulse(DEV["Q1"], TG, LV)


def test_zero_coupling_reduces_to_isolated(ref):
    import jax.numpy as jnp

    from quantum_dsl.gates import _dressed, _propagate, gaussian

    x = {k: jnp.asarray(ref[k]) for k in ("amp", "beta", "det")}
    u2 = np.asarray(X.block(X.pair(DEV, 0.0, LV), {"a": (ref, x)}, TG))
    lam, (n,) = _dressed([("q", *DEV["Q1"])], 0.0, LV)

    def eps(t):
        g, dg = gaussian(t, TG, TG / 4)
        return math.pi / ref["n01"] * ref["amp"] * (g - 1j * ref["beta"] / ref["alpha"] * dg)

    m = np.asarray(_propagate(lam, n, eps, lam[1] - ref["det"], TG))[:2, :2]        # gates 的 STEPS_PER_NS
    m = np.diag([1.0, np.exp(-1j * ref["det"] * TG)]) @ m
    assert np.abs(u2 - np.kron(m, np.eye(2))).max() < 1e-9
    assert X.best_vz(X.TARGET["idle"], u2)[0] <= float(X.infid(X.TARGET["idle"], u2)) + 1e-12


def test_recalibration_not_worse(ref):
    p = X.pair(DEV, 1.0, LV)
    target = X.TARGET["idle"]
    import jax.numpy as jnp
    u = np.asarray(X.block(p, {"a": (ref, {k: jnp.asarray(ref[k]) for k in ("amp", "beta", "det")})}, TG, spn=SPN))
    bare = float(X.infid(target, u))
    e_vz, phi = X.best_vz(target, u, starts=4)
    x0 = {"a": {k: ref[k] for k in ("amp", "beta", "det")}, "phi": phi}
    x, u2 = X.recal(p, {"a": ref}, [x0], target, TG, spn=SPN)
    e_recal = float(X.infid(target, X.vz(x["phi"], u2)))
    assert e_recal <= e_vz * (1 + 1e-6) and e_vz <= bare * (1 + 1e-9), (bare, e_vz, e_recal)
    assert p["zz"] != 0 and e_vz > 1e-6          # 有耦合时 Q2 空转确实可见
