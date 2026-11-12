# -*- coding: utf-8 -*-
"""tools/eigen_check.py: 静电 LOM vs Palace 本征模交叉验证 (冲刺工具, 不是契约)。

快测只查 config 生成与闭式 (无 gmsh / Palace); live 用例 ``QDSL_RUN_PALACE=1`` 开闸
(two_pads_eigen 80/8, 静电 + 本征模各一次, np 4 约 1–2 min)。"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import EXAMPLES, LIVE_MAXWELL_GOLDEN, ROOT, live

sys.path.insert(0, str(ROOT / "tools"))
import eigen_check as E  # noqa: E402

META = EXAMPLES / "two_pads_eigen.meta.yaml"
_MESH = SimpleNamespace(
    path=Path("eigen.msh"), labels=("A", "B", "port_Q"),
    boundary_groups={"outer": 1}, domain_groups={"substrate": 2, "vacuum": 3},
    conductor_groups={"A": 4, "B": 5, "port_Q": 6},
    conductor_bbox_um={"port_Q": (-40, -5, 40, 5)})


def _cfg(tmp_path, outer):
    from quantum_dsl import load_meta
    return E.eigen_config(_MESH, load_meta(META), [("port_Q", 10e-9)], tmp_path / "eig.json",
                          outer=outer, n_modes=2, target_ghz=9.7)


def test_eigen_config_pec_box(tmp_path):
    cfg = _cfg(tmp_path, "pec")
    assert cfg["Problem"]["Type"] == "Eigenmode"
    assert cfg["Model"]["L0"] == 1e-6                     # 唯一 µm→m 换算点, 与静电同
    assert cfg["Solver"]["Order"] == 2
    assert cfg["Boundaries"]["PEC"]["Attributes"] == [4, 5, 1]   # 导体 + 盒壁 (↔ 静电接地盒)
    assert cfg["Boundaries"]["LumpedPort"] == [
        {"Index": 1, "L": 10e-9, "Attributes": [6], "Direction": "+X"}]
    assert "Absorbing" not in cfg["Boundaries"]
    assert cfg["Solver"]["Eigenmode"] == {"N": 2, "Target": 9.7, "Save": 0}
    assert (tmp_path / "eig.json").is_file()


def test_eigen_config_outer_modes(tmp_path):
    pmc = _cfg(tmp_path, "pmc")["Boundaries"]               # 自然边界 ↔ 静电 open (ZeroCharge)
    assert pmc["PEC"]["Attributes"] == [4, 5] and "Absorbing" not in pmc
    ab = _cfg(tmp_path, "absorbing")["Boundaries"]
    assert ab["Absorbing"] == {"Attributes": [1], "Order": 1} and ab["PEC"]["Attributes"] == [4, 5]
    with pytest.raises(Exception, match="outer"):
        _cfg(tmp_path, "open")


def test_port_direction():
    assert E.port_direction((-40, -5, 40, 5)) == "+X"
    assert E.port_direction((-1, 170, 1, 202)) == "+Y"      # xmon 结: 2 µm 宽跨 32 µm 缝
    with pytest.raises(Exception, match="elongated"):
        E.port_direction((0, 0, 10, 10))
    # 比宽还短的端口 (4 µm 长 × 10 µm 宽) 启发式必错 —— 只能显式给 (2026-10-29 实测: 错方向 LC 模消失)
    assert E.port_direction((-2, -5, 2, 5)) == "+Y"


def test_direction_override(tmp_path):
    from quantum_dsl import load_meta
    cfg = E.eigen_config(_MESH, load_meta(META), [("port_Q", 10e-9)], tmp_path / "eig.json",
                         outer="pec", n_modes=1, target_ghz=9.7, direction="+Y")
    assert cfg["Boundaries"]["LumpedPort"][0]["Direction"] == "+Y"


def test_closed_forms():
    from quantum_dsl.circuit_model import ELEM_CHARGE, H_PLANCK, solve_circuit_model
    # E_J ↔ L_J 往返: E_J/h = 12 GHz ↔ L_J = (ħ/2e)²/E_J ≈ 13.62 nH
    l_j = E.l_j_henry({"name": "Q1", "E_J": 12e9})
    assert l_j == pytest.approx(13.6206e-9, rel=1e-4)
    # LOM 线性频率 = 1/(2π√(L C_Σ)); two_pads golden C、10 nH 跨 A–B (浮动): C_Σ = C_m + C_a C_b/(C_a + C_b)
    m = solve_circuit_model(("A", "B"), LIVE_MAXWELL_GOLDEN,
                            [{"name": "Q", "islands": ["A", "B"], "L_J": 10e-9}])
    q = m.qubits[0]
    ca, cb = (sum(r) for r in LIVE_MAXWELL_GOLDEN)
    assert q.C_sigma_fF == pytest.approx(1.9472 + ca * cb / (ca + cb), rel=1e-9)
    f_p = E.lom_linear_ghz(q.E_C_GHz, q.E_J_GHz)
    assert f_p == pytest.approx(1 / (2 * math.pi * math.sqrt(10e-9 * q.C_sigma_fF * 1e-15)) / 1e9,
                                rel=1e-9)
    # EPR 一阶 α: 单模单结 p = 1 → 恰为 −E_C (与 LOM 同一阶)
    alpha = E.epr_alpha_hz(f_p * 1e9, [1.0], [q.E_J_GHz * 1e9])
    assert alpha == pytest.approx(-q.E_C_GHz * 1e9, rel=1e-9)
    assert q.E_C_GHz * 1e9 == pytest.approx(ELEM_CHARGE ** 2 / (2 * q.C_sigma_fF * 1e-15) / H_PLANCK)


def test_epr_numdiag_matches_charge_basis():
    """pyEPR 口径的 Fock 基数值对角化 (cos 截到 φ¹⁰), p = 1 单结 = transmon: 对电荷基精确解。"""
    from quantum_dsl.circuit_model import H_PLANCK, transmon_levels_hz
    ec, ej = 0.2e9, 12e9                                  # E_J/E_C = 60 (xmon 量级)
    f01, f12 = E.epr_levels_hz(math.sqrt(8 * ec * ej), [1.0], [ej])
    g01, g12 = transmon_levels_hz(ec * H_PLANCK, ej * H_PLANCK)
    assert f01 == pytest.approx(g01, rel=1e-6)
    assert f12 - f01 == pytest.approx(g12 - g01, rel=1e-3)
    with pytest.raises(Exception, match="unbounded"):
        E.epr_levels_hz(1e9, [1.0], [ej], cos_order=8)


@live
def test_two_pads_eigen_vs_lom(tmp_path):
    """同网格 (80/8, order 2, PEC 盒) 静电 LOM 线性 f_p 与本征模 f 差 <2%, 结 EPR > 0.95。
    2026-10-29 实测见 build/sprint/eigen.md。"""
    s = E.run(META, tmp_path, scale=2.0, n_rank=4)
    (q,) = s["qubits"]
    assert abs(q["rel_f_eig_vs_lom"]) < 0.02
    assert q["epr"] > 0.95
