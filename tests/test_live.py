# -*- coding: utf-8 -*-
"""live Palace 求解 (默认 skip, 环境变量开闸)。

* 契约「two_pads 锚」 —— two_pads 回归锚 (钉配方可复现): ``QDSL_RUN_PALACE=1``, 单核 ~4 min,
  ⚠ WSL 上 Palace 必须 ``HWLOC_COMPONENTS=-gl`` (build() 已注入)。
* 契约「sung 外部锚」 —— sung 论文器件外部锚 (锚外部真相): ``QDSL_RUN_PALACE_SUNG=1``,
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
    """契约「two_pads 锚」: 一次 build(solve=True): C 矩阵对实测 golden <2%, 且
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
    """契约「sung 外部锚」: Sung et al. PRX 11, 021058 —— 一次整片 order-2 求解,
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

    判据写在 sung meta 的 ``targets:`` (契约「targets」), 这里读 results.yaml 的 validation 段;
    核对集合与容差在此锁死 —— 放宽 meta 里的 tol 不能让本锚静默变松。
    """
    from quantum_dsl import build
    result = build(SUNG_META, tmp_path, solve=True)
    doc = yaml.safe_load(Path(result["results"]).read_text(encoding="utf-8"))

    checks = doc["validation"]["checks"]
    assert {(c.get("qubit") or tuple(c["pair"]), c["field"], c["expected"], c["tol"])
            for c in checks} == {
        ("QB1", "C_sigma_fF", 99.3, 0.08), ("CPLR", "C_sigma_fF", 227.9, 0.08),
        ("QB2", "C_sigma_fF", 101.9, 0.08),           # fF, 由论文 E_C 换算
        (("QB1", "CPLR"), "beta", 0.0364, 0.20), (("QB2", "CPLR"), "beta", 0.0364, 0.20)}
    assert doc["validation"]["passed"], [c for c in checks if not c["pass"]]


@live
def test_two_pads_converge(tmp_path):
    """契约「网格收敛」: two_pads 80/8 → 40/4 (细档 = 锚配方) 两档真解。2026-09-24 实测:
    细档与 golden 逐位相同; 相对变化 C_AA −1.55% / C_BB −1.65% / C_AB +3.03% (physics §6)。"""
    from quantum_dsl import converge
    r = converge(TWO_PADS_META, tmp_path, scales=(2, 1))
    fine = r["runs"][-1]["capacitance"].maxwell_fF
    for i in range(2):
        for j in range(2):
            assert fine[i][j] == pytest.approx(LIVE_MAXWELL_GOLDEN[i][j], rel=0.02)
    rel = r["doc"]["capacitance"]["maxwell_rel_change"]
    assert -0.03 < rel[0][0] < 0 and -0.03 < rel[1][1] < 0     # 加密 → 自电容降
    assert 0 < rel[0][1] < 0.06
