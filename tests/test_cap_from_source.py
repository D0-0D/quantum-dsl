# -*- coding: utf-8 -*-
"""P0-C — 从文件 / inline 读电容矩阵 (``capacitance_from_file/_inline``).

这是拼装层的**正常输入方式** (tutorial 4.05 的标准入口就是两份矩阵文件), 不是调试
旁路。本文件是**纯 Python** 测试: 不需要 gmsh / Palace / numpy。

覆盖:
  (1) **往返恒等** — 把仓库里那份实测 6x6 Maxwell 矩阵 (Gmsh+ElmerFEM, sung_2021)
      写成 Palace 风格 CSV, 读回来喂 ``solve_circuit_model``, 要与直接构造
      ``CapacitanceResult`` 的路径逐位一致;
  (2) 真实 Q3D 文件 (4.05 的 ``Q1_TwoTransmon_CapMatrix.txt``) 解析 + 对参考实现
      ``load_q3d_capacitance_matrix`` 的交叉验算 (golden 硬编码, 见下), 另配一份
      **不依赖上游文件**的内联 fixture 版本;
  (3) 互容 → Maxwell 换算 (手算小例子);
  (4) inline 路径 + 单位换算 (fF/pF/F);
  (5) ``source``/``sha256`` 溯源 (solved | file | inline);
  (6) 每条校验的报错路径 (nan/inf、非方阵、不对称、符号混杂、格式不识别、
      terminals 长度不符、单位未知、文件缺失/空)。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from quantum_dsl.dsl.circuit_model import (
    ELEM_CHARGE,
    H_PLANCK,
    JunctionInput,
    solve_circuit_model,
)
from quantum_dsl.dsl.errors import DesignDslError
from quantum_dsl.dsl.palace_adapter import (
    CapacitanceResult,
    TerminalBinding,
    capacitance_from_file,
    capacitance_from_inline,
    parse_capacitance_matrix,
    write_results_sidecar,
)


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------

# The measured sung_2021_device 6-terminal Maxwell matrix (fF), copied verbatim
# from tests/test_circuit_model.py::_SUNG_MAXWELL — Gmsh + ElmerFEM on the
# reproduced device, row/col order QB1_top, QB1_bot, CPLR_top, CPLR_bot,
# QB2_top, QB2_bot.
_SUNG_MAXWELL = [
    [38.3635, -6.8074, -0.5407, -0.4427, -0.0628, -0.0615],
    [-6.8074, 38.3940, -0.4435, -0.5403, -0.0615, -0.0629],
    [-0.5407, -0.4435, 57.3523, -10.9032, -0.5404, -0.4436],
    [-0.4427, -0.5403, -10.9032, 57.3349, -0.4432, -0.5413],
    [-0.0628, -0.0615, -0.5404, -0.4432, 38.3767, -6.8111],
    [-0.0615, -0.0629, -0.4436, -0.5413, -6.8111, 38.4087],
]
_SUNG_PADS = ["QB1_pad_top_sfs", "QB1_pad_bot_sfs", "CPLR_pad_top_sfs",
              "CPLR_pad_bot_sfs", "QB2_pad_top_sfs", "QB2_pad_bot_sfs"]
_SUNG_EJ_GHZ = {"QB1": 12.2, "CPLR": 71.0, "QB2": 15.8}

# The upstream qiskit-metal tutorial 4.05 inputs (Apache-2.0, read-only).
_Q3D_DIR = Path("/home/administrator/metal/qiskit-metal/tutorials/"
                "4 Analysis/A. Core - EM and quantization")
_Q3D_Q1 = _Q3D_DIR / "Q1_TwoTransmon_CapMatrix.txt"

# Cross-check golden: ``load_q3d_capacitance_matrix(_Q3D_Q1, user_units="fF")``
# run in conda env ``quantum-metal`` (quantum-metal 0.7.6).  The file self-reports
# ``C Units:fF`` so pint's scale factor is exactly 1.0 and the reference returns
# the file literals verbatim -> our numbers must match BIT-for-BIT.
_Q3D_Q1_NAMES = ["coupler_connector_pad_Q1", "ground_main_plane", "pad_bot_Q1",
                 "pad_top_Q1", "readout_connector_pad_Q1"]
_Q3D_Q1_REF_FF = [
    [59.19879, -37.28461, -2.00818, -19.10774, -0.22976],
    [-37.28461, 246.32877, -39.78914, -39.86444, -37.29686],
    [-2.00818, -39.78914, 93.05074, -30.61038, -19.21994],
    [-19.10774, -39.86444, -30.61038, 92.99428, -2.00897],
    [-0.22976, -37.29686, -19.21994, -2.00897, 59.32747],
]

# A byte-faithful excerpt of that upstream file (tab separated, CRLF, `C Units`
# header) so the parser is covered even where the tutorials are not installed.
_Q3D_INLINE = (
    "Setup:LastAdaptive\r\n"
    "Problem Type:  C\r\n"
    "C Units:fF, G Units:mSie\r\n"
    "Reduce Matrix:  Original\r\n"
    "Frequency:  5GHz\r\n"
    "\r\n"
    "Capacitance Matrix\r\n"
    "\tcoupler_connector_pad_Q1\tground_main_plane\tpad_bot_Q1\tpad_top_Q1"
    "\treadout_connector_pad_Q1\t\r\n"
    "coupler_connector_pad_Q1\t59.19879\t-37.28461\t-2.00818\t-19.10774"
    "\t-0.22976\r\n"
    "ground_main_plane\t-37.28461\t246.32877\t-39.78914\t-39.86444"
    "\t-37.29686\r\n"
    "pad_bot_Q1\t-2.00818\t-39.78914\t93.05074\t-30.61038\t-19.21994\r\n"
    "pad_top_Q1\t-19.10774\t-39.86444\t-30.61038\t92.99428\t-2.00897\r\n"
    "readout_connector_pad_Q1\t-0.22976\t-37.29686\t-19.21994\t-2.00897"
    "\t59.32747\r\n"
    "\r\n"
    "Conductance Matrix\r\n"
    "\tcoupler_connector_pad_Q1\tground_main_plane\tpad_bot_Q1\tpad_top_Q1"
    "\treadout_connector_pad_Q1\r\n"
    "coupler_connector_pad_Q1\t 0.00000\t 0.00000\t 0.00000\t 0.00000"
    "\t 0.00000\r\n"
    "ground_main_plane\t 0.00000\t 0.00000\t 0.00000\t 0.00000\t 0.00000\r\n"
    "pad_bot_Q1\t 0.00000\t 0.00000\t 0.00000\t 0.00000\t 0.00000\r\n"
    "pad_top_Q1\t 0.00000\t 0.00000\t 0.00000\t 0.00000\t 0.00000\r\n"
    "readout_connector_pad_Q1\t 0.00000\t 0.00000\t 0.00000\t 0.00000"
    "\t 0.00000\r\n"
)


def _palace_csv(matrix, *, unit: str = "F", divisor: float = 1.0e15) -> str:
    """把 fF 矩阵写成一张 Palace 风格 ``terminal-C.csv`` 文本 (缺省: SI 法拉)。

    ``v / divisor`` 而不是 ``v * (1/divisor)`` —— 前者的往返 (读回时 ×divisor) 在这份
    矩阵上只有 1 个元素差 1 ulp, 后者有 22 个。
    """
    n = len(matrix)
    head = "        i," + ",".join(f"   C[i][{j}] ({unit})"
                                   for j in range(1, n + 1))
    lines = [head]
    for i, row in enumerate(matrix, start=1):
        cells = ",".join(f" {v / divisor!r}" for v in row)
        lines.append(f" {float(i)!r},{cells}")
    return "\n".join(lines) + "\n"


def _flat(matrix) -> list[float]:
    """摊平成一维 —— 本版 pytest 的 ``approx`` 不支持嵌套序列。"""
    return [v for row in matrix for v in row]


def _sung_qubits() -> list[JunctionInput]:
    """三个 **浮动/差分** transmon (与 test_circuit_model 的 golden 一致)。"""
    return [
        JunctionInput(name, (_SUNG_PADS[2 * k], _SUNG_PADS[2 * k + 1]),
                      E_J=_SUNG_EJ_GHZ[name] * 1e9 * H_PLANCK)
        for k, name in enumerate(("QB1", "CPLR", "QB2"))
    ]


# ---------------------------------------------------------------------------
# (1) round-trip identity — the strongest regression
# ---------------------------------------------------------------------------

def test_sung_matrix_roundtrips_through_a_palace_csv(tmp_path):
    """CSV → capacitance_from_file → solve_circuit_model 与直接构造**逐位一致**。

    Golden numbers are test_circuit_model's
    ``test_sung_device_differential_matches_lom2`` targets (C_Sigma 22.593002 /
    34.123189 / 22.601826 fF, E_C 0.8573554 / 0.5676558 / 0.8570206 GHz).

    ⚠ spec §7 的 P0-C 行写的是「复现 E_C 0.190/0.083/0.190」—— 那对的是**标定后**
    几何的 Elmer 解, 那份矩阵不在仓库里。仓库里有的是标定前的 6x6 实测矩阵
    (``test_circuit_model._SUNG_MAXWELL``), 所以往返恒等用它来做。
    """
    csv = tmp_path / "terminal-C.csv"
    csv.write_text(_palace_csv(_SUNG_MAXWELL), encoding="utf-8")

    cap = capacitance_from_file(csv, terminals=_SUNG_PADS)

    assert cap.available is True
    assert cap.units == "fF"
    assert cap.source == "file"
    assert [b.index for b in cap.terminals] == [1, 2, 3, 4, 5, 6]
    assert [b.group for b in cap.terminals] == _SUNG_PADS
    assert [b.attribute for b in cap.terminals] == [0] * 6
    assert not cap.mutual  # the file was already Maxwell
    # F -> fF round-trip is exact for every entry except a single 1-ulp wobble
    # (57.3523 -> 57.35230000000001), so compare at 1e-15 rather than ==.
    assert _flat(cap.maxwell) == pytest.approx(_flat(_SUNG_MAXWELL), rel=1e-15)

    got = solve_circuit_model(cap, _sung_qubits())
    assert [q.C_sigma_fF for q in got.qubits] == pytest.approx(
        [22.593002, 34.123189, 22.601826], rel=1e-6)
    assert [q.E_C_GHz for q in got.qubits] == pytest.approx(
        [0.8573554, 0.5676558, 0.8570206], rel=1e-6)

    # ...and bit-identical to feeding the very same matrix in directly: the file
    # front-end adds nothing but provenance.
    direct = CapacitanceResult(
        postpro_dir=tmp_path, available=True,
        terminals=tuple(TerminalBinding(i + 1, g, 0)
                        for i, g in enumerate(_SUNG_PADS)),
        maxwell=cap.maxwell)
    ref = solve_circuit_model(direct, _sung_qubits())
    assert [q.C_sigma_fF for q in got.qubits] == [q.C_sigma_fF for q in ref.qubits]
    assert [q.E_C_GHz for q in got.qubits] == [q.E_C_GHz for q in ref.qubits]
    assert [c.g_MHz for c in got.couplings] == [c.g_MHz for c in ref.couplings]


def test_palace_csv_in_farads_is_bit_identical_to_the_solved_path(tmp_path):
    """同一份 CSV 走 ``parse_capacitance_matrix`` 与 ``capacitance_from_file`` 逐位相同。

    表头自述 ``(F)`` → 单位修正因子恰为 1.0 → 不引入任何额外浮点运算。
    """
    text = _palace_csv(_SUNG_MAXWELL)
    (tmp_path / "terminal-C.csv").write_text(text, encoding="utf-8")
    solved = parse_capacitance_matrix(tmp_path)
    injected = capacitance_from_file(tmp_path / "terminal-C.csv")
    assert injected.maxwell == solved.maxwell          # exact
    assert solved.source == "solved" and solved.sha256 is None
    # no terminal names in a Palace CSV -> generated t1..tN
    assert [b.group for b in injected.terminals] == [f"t{i}" for i in range(1, 7)]


def test_palace_csv_header_unit_beats_the_units_fallback(tmp_path):
    """表头自述单位优先于 ``units=`` 兜底 (与参考实现同序)。"""
    csv = tmp_path / "cap.csv"
    csv.write_text(_palace_csv([[10.0, -1.0], [-1.0, 12.0]], unit="pF",
                               divisor=1e3), encoding="utf-8")
    # header says pF; the (wrong) fallback must be ignored
    cap = capacitance_from_file(csv, units="F")
    assert _flat(cap.maxwell) == pytest.approx(_flat([[10.0, -1.0],
                                                      [-1.0, 12.0]]), rel=1e-12)


def test_palace_csv_without_a_unit_label_stays_in_farads(tmp_path):
    """表头漏了 ``(F)`` 标签也按 F 处理 —— 不能被 ``units`` 缺省值缩掉 1e15 倍。"""
    csv = tmp_path / "terminal-C.csv"
    csv.write_text("        i,   C[i][1],   C[i][2]\n"
                   " 1.0, 1e-14, -1e-15\n"
                   " 2.0, -1e-15, 1.2e-14\n", encoding="utf-8")
    cap = capacitance_from_file(csv)                  # units= defaults to "fF"
    assert _flat(cap.maxwell) == pytest.approx(_flat([[10.0, -1.0],
                                                      [-1.0, 12.0]]), rel=1e-12)


# ---------------------------------------------------------------------------
# (2) real Q3D file + cross-check against the reference implementation
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _Q3D_Q1.is_file(),
                    reason=f"upstream qiskit-metal tutorial file missing: {_Q3D_Q1}")
def test_q3d_file_matches_load_q3d_capacitance_matrix():
    """真实 4.05 输入: terminal 名 + 形状 + 数值对参考实现逐位一致。"""
    cap = capacitance_from_file(_Q3D_Q1)
    assert [b.group for b in cap.terminals] == _Q3D_Q1_NAMES
    assert len(cap.maxwell) == 5 and all(len(r) == 5 for r in cap.maxwell)
    assert cap.units == "fF"          # the file self-reports 'C Units:fF'
    assert cap.maxwell == _Q3D_Q1_REF_FF   # bit-identical to the reference
    assert not cap.mutual             # Ansys exported the Maxwell matrix
    assert cap.source == "file"
    assert cap.sha256 == hashlib.sha256(_Q3D_Q1.read_bytes()).hexdigest()


def test_q3d_inline_fixture_parses_without_the_upstream_file(tmp_path):
    """同样的格式, 内联 fixture 版 —— 不依赖上游 tutorial 目录。"""
    src = tmp_path / "Q1_TwoTransmon_CapMatrix.txt"
    src.write_bytes(_Q3D_INLINE.encode("utf-8"))
    cap = capacitance_from_file(src)
    assert [b.group for b in cap.terminals] == _Q3D_Q1_NAMES
    assert cap.maxwell == _Q3D_Q1_REF_FF
    assert cap.postpro_dir == tmp_path
    assert cap.csv_paths == {"maxwell": src}
    assert cap.raw["maxwell"] == _Q3D_INLINE


def test_q3d_units_are_read_from_the_file_not_the_fallback(tmp_path):
    """``C Units:farad`` → 自述单位换算成 fF, ``units=`` 兜底被忽略。"""
    src = tmp_path / "q3d_farad.txt"
    src.write_text(
        "C Units:farad, G Units:mSie\n"
        "Capacitance Matrix\n"
        "\tA\tB\n"
        "A\t9.5831E-14\t-3.2415E-14\n"
        "B\t-3.2415E-14\t9.132E-14\n",
        encoding="utf-8")
    cap = capacitance_from_file(src, units="pF")   # fallback must not be used
    assert _flat(cap.maxwell) == pytest.approx(
        _flat([[95.831, -32.415], [-32.415, 91.32]]), rel=1e-12)


def test_q3d_without_a_unit_header_uses_the_units_fallback(tmp_path):
    """文件没自述单位时才用 ``units=`` 兜底。"""
    src = tmp_path / "q3d_nounit.txt"
    src.write_text("Capacitance Matrix\n\tA\tB\nA\t0.1\t-0.01\nB\t-0.01\t0.12\n",
                   encoding="utf-8")
    cap = capacitance_from_file(src, units="pF")
    assert _flat(cap.maxwell) == pytest.approx(
        _flat([[100.0, -10.0], [-10.0, 120.0]]), rel=1e-12)


def test_q3d_row_label_order_mismatch_is_rejected(tmp_path):
    src = tmp_path / "q3d_swapped.txt"
    src.write_text("C Units:fF,\nCapacitance Matrix\n\tA\tB\n"
                   "B\t10\t-1\nA\t-1\t12\n", encoding="utf-8")
    with pytest.raises(DesignDslError, match="row labels"):
        capacitance_from_file(src)


def test_q3d_ragged_row_is_rejected(tmp_path):
    src = tmp_path / "q3d_ragged.txt"
    src.write_text("C Units:fF,\nCapacitance Matrix\n\tA\tB\n"
                   "A\t10\t-1\t3\nB\t-1\t12\n", encoding="utf-8")
    with pytest.raises(DesignDslError, match="whitespace"):
        capacitance_from_file(src)


# ---------------------------------------------------------------------------
# (3) mutual -> Maxwell conversion (hand-computed)
# ---------------------------------------------------------------------------

def test_mutual_2x2_is_converted_to_maxwell():
    """Cm = [[c10, c12], [c12, c20]] → C = [[c10+c12, -c12], [-c12, c20+c12]]。"""
    cap = capacitance_from_inline([[3.0, 2.0], [2.0, 5.0]])
    assert cap.maxwell == [[5.0, -2.0], [-2.0, 7.0]]
    assert cap.mutual == [[3.0, 2.0], [2.0, 5.0]]   # original kept


def test_mutual_3x3_is_converted_to_maxwell():
    mutual = [[10.0, 1.0, 2.0],
              [1.0, 20.0, 4.0],
              [2.0, 4.0, 30.0]]
    cap = capacitance_from_inline(mutual)
    assert cap.maxwell == [[13.0, -1.0, -2.0],
                           [-1.0, 25.0, -4.0],
                           [-2.0, -4.0, 36.0]]
    assert cap.mutual == mutual


def test_maxwell_input_is_passed_through_untouched():
    maxwell = [[13.0, -1.0, -2.0], [-1.0, 25.0, -4.0], [-2.0, -4.0, 36.0]]
    cap = capacitance_from_inline(maxwell)
    assert cap.maxwell == maxwell
    assert cap.mutual == []


def test_mutual_file_records_the_mutual_kind(tmp_path):
    src = tmp_path / "terminal-Cm.csv"
    src.write_text(_palace_csv([[3.0, 2.0], [2.0, 5.0]]), encoding="utf-8")
    cap = capacitance_from_file(src)
    assert _flat(cap.maxwell) == pytest.approx(_flat([[5.0, -2.0],
                                                      [-2.0, 7.0]]), rel=1e-15)
    assert set(cap.csv_paths) == {"mutual"}


def test_mixed_offdiagonal_signs_are_rejected():
    with pytest.raises(DesignDslError, match="signs are mixed"):
        capacitance_from_inline([[10.0, 1.0, -2.0],
                                 [1.0, 20.0, -4.0],
                                 [-2.0, -4.0, 30.0]])


def test_maxwell_with_a_non_positive_diagonal_is_rejected():
    with pytest.raises(DesignDslError, match="positive"):
        capacitance_from_inline([[0.0, -1.0], [-1.0, 12.0]])


# ---------------------------------------------------------------------------
# (4) inline path + unit conversion
# ---------------------------------------------------------------------------

def test_inline_dict_with_terminals_and_maxwell():
    cap = capacitance_from_inline(
        {"terminals": ["A_pad_sfs", "B_pad_sfs"],
         "maxwell": [[24.7288, -1.976], [-1.976, 24.7293]]})
    assert [b.group for b in cap.terminals] == ["A_pad_sfs", "B_pad_sfs"]
    assert [b.index for b in cap.terminals] == [1, 2]
    assert cap.maxwell == [[24.7288, -1.976], [-1.976, 24.7293]]
    assert cap.postpro_dir == Path("inline")


def test_inline_units_pF_and_F():
    want = _flat([[24.0, -2.0], [-2.0, 25.0]])
    pf = capacitance_from_inline([[0.024, -0.002], [-0.002, 0.025]], units="pF")
    assert _flat(pf.maxwell) == pytest.approx(want, rel=1e-12)
    si = capacitance_from_inline([[2.4e-14, -2e-15], [-2e-15, 2.5e-14]],
                                 units="F")
    assert _flat(si.maxwell) == pytest.approx(want, rel=1e-12)
    assert si.units == "fF"          # internal unit is always fF
    # units inside the dict win over the parameter default (never silently dropped)
    d = capacitance_from_inline({"maxwell": [[0.024, -0.002], [-0.002, 0.025]],
                                 "units": "pF"})
    assert _flat(d.maxwell) == pytest.approx(want, rel=1e-12)


def test_inline_label_and_terminal_generation():
    cap = capacitance_from_inline([[10.0, -1.0], [-1.0, 11.0]], label="sung_elmer")
    assert cap.postpro_dir == Path("sung_elmer")
    assert [b.group for b in cap.terminals] == ["t1", "t2"]


def test_inline_feeds_the_circuit_model():
    """注入矩阵直接可解 —— 零成本回归 (不需要 FEM)。"""
    cap = capacitance_from_inline({"terminals": _SUNG_PADS,
                                   "maxwell": _SUNG_MAXWELL})
    got = solve_circuit_model(cap, _sung_qubits())
    assert [q.C_sigma_fF for q in got.qubits] == pytest.approx(
        [22.593002, 34.123189, 22.601826], rel=1e-6)
    assert [q.E_C_GHz for q in got.qubits] == pytest.approx(
        [0.8573554, 0.5676558, 0.8570206], rel=1e-6)
    # E_C = e^2/(2 C_Sigma) closes the loop analytically
    e_c = ELEM_CHARGE ** 2 / (2 * got.qubits[0].C_sigma_fF * 1e-15) / H_PLANCK
    assert e_c / 1e9 == pytest.approx(got.qubits[0].E_C_GHz, rel=1e-12)


def test_inline_rejects_unknown_keys_and_missing_matrix():
    with pytest.raises(DesignDslError, match="unknown inline capacitance key"):
        capacitance_from_inline({"maxwell": [[1.0]], "mutual": [[1.0]]})
    with pytest.raises(DesignDslError, match="needs a 'maxwell' key"):
        capacitance_from_inline({"terminals": ["a"]})


def test_inline_rejects_non_matrix_input():
    with pytest.raises(DesignDslError, match="2-D list"):
        capacitance_from_inline([1.0, 2.0])
    with pytest.raises(DesignDslError, match="2-D list"):
        capacitance_from_inline("[[1.0]]")


def test_unknown_unit_is_rejected():
    with pytest.raises(DesignDslError, match="unknown capacitance unit"):
        capacitance_from_inline([[1.0]], units="bananas")


# ---------------------------------------------------------------------------
# (5) provenance — source / sha256 (spec R4)
# ---------------------------------------------------------------------------

def test_source_and_sha256_distinguish_the_three_paths(tmp_path):
    postpro = tmp_path / "postpro"
    postpro.mkdir()
    (postpro / "terminal-C.csv").write_text(
        _palace_csv([[10.0, -1.0], [-1.0, 12.0]]), encoding="utf-8")

    solved = parse_capacitance_matrix(postpro)
    assert solved.source == "solved" and solved.sha256 is None

    src = tmp_path / "measured.csv"
    src.write_text(_palace_csv([[10.0, -1.0], [-1.0, 12.0]]), encoding="utf-8")
    from_file = capacitance_from_file(src)
    assert from_file.source == "file"
    assert from_file.sha256 == hashlib.sha256(src.read_bytes()).hexdigest()

    inline = capacitance_from_inline([[10.0, -1.0], [-1.0, 12.0]])
    assert inline.source == "inline" and inline.sha256 is None


def test_results_sidecar_records_source_and_sha256(tmp_path):
    import yaml

    src = tmp_path / "measured.csv"
    src.write_text(_palace_csv([[10.0, -1.0], [-1.0, 12.0]]), encoding="utf-8")
    cap = capacitance_from_file(src, terminals=["A_pad_sfs", "B_pad_sfs"])
    out = write_results_sidecar(cap, tmp_path / "chip.results.yaml")
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))["capacitance"]
    assert doc["source"] == "file"
    assert doc["sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()
    assert doc["source_csv"] == {"maxwell": "measured.csv"}


# ---------------------------------------------------------------------------
# (6) validation error paths
# ---------------------------------------------------------------------------

def test_nan_and_inf_are_rejected():
    for bad in (float("nan"), float("inf")):
        with pytest.raises(DesignDslError, match="not finite|non-finite"):
            capacitance_from_inline([[10.0, -1.0], [-1.0, bad]])


def test_nan_in_a_q3d_file_is_rejected(tmp_path):
    src = tmp_path / "q3d_nan.txt"
    src.write_text("C Units:fF,\nCapacitance Matrix\n\tA\tB\n"
                   "A\t10\t-1\nB\t-1\tnan\n", encoding="utf-8")
    with pytest.raises(DesignDslError, match="not finite"):
        capacitance_from_file(src)


def test_non_square_matrix_is_rejected():
    with pytest.raises(DesignDslError, match="not square"):
        capacitance_from_inline([[10.0, -1.0, -2.0], [-1.0, 12.0, -1.0]])


def test_asymmetric_matrix_is_rejected_with_the_worst_offender():
    with pytest.raises(DesignDslError, match="not symmetric") as exc:
        capacitance_from_inline([[10.0, -1.0], [-3.0, 12.0]])
    assert "[1][2]" in str(exc.value)
    # within tolerance (solver noise) -> accepted
    cap = capacitance_from_inline([[10.0, -1.0], [-1.000001, 12.0]])
    assert cap.maxwell[0][1] == -1.0


def test_terminal_count_mismatch_is_rejected():
    with pytest.raises(DesignDslError, match="terminal name"):
        capacitance_from_inline([[10.0, -1.0], [-1.0, 12.0]],
                                terminals=["only_one"])


def test_unrecognised_format_is_rejected(tmp_path):
    src = tmp_path / "junk.txt"
    src.write_text("<xml><cap>1.0</cap></xml>\n", encoding="utf-8")
    with pytest.raises(DesignDslError, match="unrecognised capacitance matrix"):
        capacitance_from_file(src)


def test_missing_and_empty_files_are_rejected(tmp_path):
    with pytest.raises(DesignDslError, match="not found"):
        capacitance_from_file(tmp_path / "nope.csv")
    empty = tmp_path / "empty.csv"
    empty.write_text("   \n\n", encoding="utf-8")
    with pytest.raises(DesignDslError, match="is empty"):
        capacitance_from_file(empty)
