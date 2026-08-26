# -*- coding: utf-8 -*-
"""live Palace 求解 (默认 skip, 环境变量开闸)。

* 契约 N7 —— two_pads 回归锚 (钉配方可复现): ``QDSL_RUN_PALACE=1``, 单核 ~4 min,
  ⚠ WSL 上 Palace 必须 ``HWLOC_COMPONENTS=-gl`` (build() 已注入)。
* 契约 N15 —— sung 论文器件外部锚 (锚外部真相): ``QDSL_RUN_PALACE_SUNG=1``,
  18.5M 未知量 / 峰值内存 ~154 G, 上 384G 机 (``tools/palace_remote.sh``)。
两者角色互补, 都要。
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from conftest import LIVE_MAXWELL_GOLDEN, SUNG_META, TWO_PADS_META, live, live_sung


@live
def test_two_pads_end_to_end(tmp_path):
    """契约 N7: 一次 build(solve=True): C 矩阵对实测 golden <2%, 且
    results.yaml 的 f01 对「golden + 10 nH 闭式」<3%。"""
    from quantum_dsl import build
    result = build(TWO_PADS_META, tmp_path, solve=True)
    cap = result["capacitance"]
    assert cap.labels == ("A", "B")
    for i in range(2):
        for j in range(2):
            assert cap.maxwell_fF[i][j] == pytest.approx(
                LIVE_MAXWELL_GOLDEN[i][j], rel=0.02)
    doc = yaml.safe_load(Path(result["results"]).read_text(encoding="utf-8"))
    f01 = [q["f01_GHz"] for q in doc["hamiltonian"]["qubits"]]
    assert f01 == pytest.approx([9.3989, 9.3984], rel=0.03)


@live_sung
def test_sung_2021_against_paper(tmp_path):
    """契约 N15: Sung et al. PRX 11, 021058 —— 一次整片 order-2 求解,
    C_Σ ×3 对论文 ±8%, β_qc ×2 对论文 ±20%。判据出处、可复现边界与排除项:
    examples/sung_2021_device.meta.yaml 头注。

    **C_Σ 容差翻案 (2026-08-25, 整片 order-2 首测)**: 原 ±5% 按 v3 Elmer 档
    (P1, 6.87M tets: 102.1/232.8/102.1 fF, 对论文 1.00–1.03) 标定 —— 但
    同网格 (14.1M tets) 交叉实测: order 1 = 101.4/232.6/101.3 (对 Elmer
    <1%, 两独立求解器同 P1 同答案 = 管线正确), order 2 = 95.8/220.7/95.8
    (对论文 0.965/0.969/0.940)。即 Elmer 档的"±3% 吻合"是 P1 离散正偏
    (+5.4~5.8%, 与 two_pads o1 实测 +7.3% 同类) 与简化版图结构性缺失
    (−4~6%: 无 junction leads/读出爪/控制线, 真机这些金属都给 pad 添容)
    相互抵消的产物。锚不动 (论文值 = 外部真相), 容差改为
    ±8% = 版图缺失 −4~6% + 网格/求解波动 ~±2%。诊断参照: 若失败,
    先在同网格跑 order 1 比对 Elmer 档, 再怀疑物理。

    **β**: 无量纲 β = |C'⁻¹_ij|/√(C'⁻¹_ii·C'⁻¹_jj) 与磁通/E_J 无关, 可对论文
    断言 (v3 Elmer 得 0.0390, +7% 系简化版图所致 → 容差 ±20%)。
    排除项 (结构性, 见 meta 头注): β_12/C_12 (本版图无直接 q-q 路径,
    差分远场相消, Elmer 也只得论文的 2%), 绝对 g 与 CPLR/QB2 的 f01
    (论文在磁通工作点, 本模型坐零磁通)。
    """
    from quantum_dsl import build
    result = build(SUNG_META, tmp_path, solve=True)
    doc = yaml.safe_load(Path(result["results"]).read_text(encoding="utf-8"))

    qubits = {q["name"]: q for q in doc["hamiltonian"]["qubits"]}
    paper = {"QB1": 99.3, "CPLR": 227.9, "QB2": 101.9}  # fF, 由论文 E_C 换算
    for name, ref in paper.items():
        assert qubits[name]["C_sigma_fF"] == pytest.approx(ref, rel=0.08), name

    betas = {frozenset((c["qubit_a"], c["qubit_b"])): c["beta"]
             for c in doc["hamiltonian"]["couplings"]}
    assert betas[frozenset(("QB1", "CPLR"))] == pytest.approx(0.0364, rel=0.20)
    assert betas[frozenset(("QB2", "CPLR"))] == pytest.approx(0.0364, rel=0.20)
