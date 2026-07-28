# -*- coding: utf-8 -*-
"""M6 — circuit-model solve: Maxwell C-matrix → transmon Hamiltonian.

Three concerns, all runnable in any env (the solver + parser are pure Python —
NO gmsh/gdstk/numpy/scipy):
  (1) circuit_model.solve_circuit_model known-value physics (closed-form transmon
      via the lumped-oscillator inverse-capacitance method);
  (2) the *.meta.yaml ``circuit_model`` block schema / parse / unit-scaling;
  (3) the OUTPUT-only results write-back (tier 2 + ``hamiltonian`` section) and its
      regression guards.

Golden values were computed from the implementation and cross-checked against the
closed-form arithmetic (and, optionally + gated, against qiskit-metal's exact CPB
diagonalisation ``Hcpb``).
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from quantum_dsl.dsl.errors import DesignDslError
from quantum_dsl.dsl.circuit_model import (
    CircuitModelResult,
    CouplingResult,
    JunctionInput,
    QubitResult,
    ELEM_CHARGE,
    H_PLANCK,
    HBAR,
    FLUX_QUANTUM_REDUCED,
    charging_energy_joule,
    josephson_energy_joule,
    solve_circuit_model,
    transmon_f01_hz,
)
from quantum_dsl.dsl.palace_adapter import (
    CapacitanceResult,
    TerminalBinding,
    parse_capacitance_matrix,
    terminal_bindings,
    write_results_sidecar,
)
from quantum_dsl.dsl.parsers.simulation import (
    _HENRY_UNITS,
    _parse_ej_joule,
    _parse_unit_value,
    parse_geo_meta_sidecar,
)


# ---------------------------------------------------------------------------
# fixtures — CapacitanceResult builders mirroring the geo-path SSOT
# ---------------------------------------------------------------------------

def _single(c_sigma_fF: float) -> CapacitanceResult:
    """One isolated conductor (1x1 Maxwell matrix)."""
    return CapacitanceResult(
        postpro_dir=Path("."), available=True,
        terminals=(TerminalBinding(1, "Q_pad_sfs", 11),),
        maxwell=[[c_sigma_fF]])


# two_pads LIVE Palace Maxwell matrix (fF): symmetric, +diag/-offdiag.
_TWO_PADS_MAXWELL = [[24.73, -1.98], [-1.98, 24.72]]
_TWO_PADS_MUTUAL = [[22.75, 1.98], [1.98, 22.74]]


def _two_pads() -> CapacitanceResult:
    return CapacitanceResult(
        postpro_dir=Path("."), available=True,
        terminals=(TerminalBinding(1, "A_pad_sfs", 11),
                   TerminalBinding(2, "B_pad_sfs", 12)),
        maxwell=_TWO_PADS_MAXWELL, mutual=_TWO_PADS_MUTUAL)


# Golden values (computed from the implementation; verified by closed-form below).
_C1 = dict(C_sigma_fF=135.0, E_C_GHz=0.14348318018266015,
           E_J_GHz=16.34615128067812, f01_GHz=4.188165715559985,
           anharmonicity_MHz=-143.48318018266016, EJ_over_EC=113.92381504137822)


# ---------------------------------------------------------------------------
# physical constants
# ---------------------------------------------------------------------------

def test_constants_are_exact_si_and_hbar_is_derived():
    assert ELEM_CHARGE == 1.602176634e-19          # exact, SI-2019
    assert H_PLANCK == 6.62607015e-34              # exact, SI-2019
    # hbar derived from h, not an independently-rounded literal
    assert HBAR == H_PLANCK / (2.0 * math.pi)
    assert HBAR == pytest.approx(1.0545718176461565e-34, rel=1e-12)
    assert FLUX_QUANTUM_REDUCED == HBAR / (2.0 * ELEM_CHARGE)


# ---------------------------------------------------------------------------
# (1) known-value transmon physics — single isolated island
# ---------------------------------------------------------------------------

def test_single_qubit_known_values():
    r = solve_circuit_model(_single(135.0),
                            [JunctionInput("Q", ("Q_pad_sfs",), L_J=10e-9)])
    assert len(r.qubits) == 1 and not r.couplings
    q = r.qubits[0]
    assert q.C_sigma_fF == pytest.approx(_C1["C_sigma_fF"], rel=1e-9)
    assert q.E_C_GHz == pytest.approx(_C1["E_C_GHz"], rel=1e-9)
    assert q.E_J_GHz == pytest.approx(_C1["E_J_GHz"], rel=1e-9)
    assert q.f01_GHz == pytest.approx(_C1["f01_GHz"], rel=1e-9)
    assert q.anharmonicity_MHz == pytest.approx(_C1["anharmonicity_MHz"], rel=1e-9)
    assert q.EJ_over_EC == pytest.approx(_C1["EJ_over_EC"], rel=1e-9)


def test_anharmonicity_is_minus_e_c():
    q = solve_circuit_model(_single(135.0),
                            [JunctionInput("Q", ("Q_pad_sfs",), L_J=10e-9)]).qubits[0]
    # alpha = -E_C exactly (MHz vs GHz*1e3)
    assert q.anharmonicity_MHz == pytest.approx(-q.E_C_GHz * 1e3, rel=1e-12)


def test_single_island_inverse_equals_diagonal_e_c():
    """For a 1x1 matrix the inverse method must reduce EXACTLY to e^2/(2 C_ii)."""
    q = solve_circuit_model(_single(135.0),
                            [JunctionInput("Q", ("Q_pad_sfs",), L_J=10e-9)]).qubits[0]
    direct_GHz = charging_energy_joule(135.0e-15) / H_PLANCK / 1e9
    assert q.E_C_GHz == pytest.approx(direct_GHz, rel=1e-15)


def test_e_j_input_equals_l_j_input():
    """E_J given directly (Joule) must reproduce the L_J-derived f01."""
    by_lj = solve_circuit_model(
        _single(135.0), [JunctionInput("Q", ("Q_pad_sfs",), L_J=10e-9)])
    e_j_joule = josephson_energy_joule(10e-9)
    by_ej = solve_circuit_model(
        _single(135.0), [JunctionInput("Q", ("Q_pad_sfs",), E_J=e_j_joule)])
    assert by_ej.qubits[0].f01_GHz == pytest.approx(by_lj.qubits[0].f01_GHz, rel=1e-15)
    assert by_ej.qubits[0].E_J_GHz == pytest.approx(by_lj.qubits[0].E_J_GHz, rel=1e-15)


def test_closed_form_helpers_match_formula():
    e_c = charging_energy_joule(135.0e-15)
    e_j = josephson_energy_joule(10e-9)
    assert e_j == pytest.approx(FLUX_QUANTUM_REDUCED ** 2 / 10e-9)
    assert transmon_f01_hz(e_c, e_j) == pytest.approx(
        (math.sqrt(8 * e_c * e_j) - e_c) / H_PLANCK)


# ---------------------------------------------------------------------------
# (1) known-value transmon physics — coupled two_pads (inverse-cap LOM)
# ---------------------------------------------------------------------------

def test_two_pads_uses_inverse_effective_c_sigma_not_raw_diagonal():
    """C_Sigma = 1/[C^-1]_ii (rigorous LOM), NOT the raw Maxwell diagonal (24.73)
    and NOT the mutual/cap-to-ground diagonal (22.75)."""
    r = solve_circuit_model(_two_pads(),
                            [JunctionInput("A", ("A_pad_sfs",), L_J=10e-9),
                             JunctionInput("B", ("B_pad_sfs",), L_J=10e-9)])
    a, b = r.qubits
    assert a.C_sigma_fF == pytest.approx(24.57140776699029, rel=1e-9)
    assert b.C_sigma_fF == pytest.approx(24.561471896482004, rel=1e-9)
    # explicitly distinct from the two naive choices:
    assert a.C_sigma_fF != pytest.approx(24.73)   # raw Maxwell diagonal
    assert a.C_sigma_fF != pytest.approx(22.75)   # mutual / cap-to-ground diagonal


def test_two_pads_qubit_energies():
    r = solve_circuit_model(_two_pads(),
                            [JunctionInput("A", ("A_pad_sfs",), L_J=10e-9),
                             JunctionInput("B", ("B_pad_sfs",), L_J=10e-9)])
    a, b = r.qubits
    assert a.E_C_GHz == pytest.approx(0.7883239539364719, rel=1e-9)
    assert b.E_C_GHz == pytest.approx(0.7886428552123362, rel=1e-9)
    assert a.f01_GHz == pytest.approx(9.364926800074445, rel=1e-9)
    assert b.f01_GHz == pytest.approx(9.366661342191808, rel=1e-9)
    # marginal transmon regime (EJ/EC ~ 21 << 50) — surfaced for the consumer
    assert a.EJ_over_EC == pytest.approx(20.735322324095453, rel=1e-9)


def test_two_pads_coupling_from_offdiagonal():
    r = solve_circuit_model(_two_pads(),
                            [JunctionInput("A", ("A_pad_sfs",), L_J=10e-9),
                             JunctionInput("B", ("B_pad_sfs",), L_J=10e-9)])
    assert len(r.couplings) == 1
    c = r.couplings[0]
    assert {c.qubit_a, c.qubit_b} == {"A", "B"}
    assert c.C_g_fF == pytest.approx(1.98)   # |Maxwell offdiag| = mutual Cm_ij
    assert c.g_MHz == pytest.approx(375.0105674523576, rel=1e-6)


def test_couplings_are_unordered_pairs_no_self():
    """N qubits -> N-choose-2 couplings, one per unordered pair, deterministic."""
    cap = CapacitanceResult(
        postpro_dir=Path("."), available=True,
        terminals=(TerminalBinding(1, "A_pad_sfs", 11),
                   TerminalBinding(2, "B_pad_sfs", 12),
                   TerminalBinding(3, "C_pad_sfs", 13)),
        maxwell=[[30.0, -2.0, -1.0], [-2.0, 31.0, -1.5], [-1.0, -1.5, 29.0]])
    qubits = [JunctionInput(n, (f"{n}_pad_sfs",), L_J=10e-9) for n in "ABC"]
    r1 = solve_circuit_model(cap, qubits)
    r2 = solve_circuit_model(cap, qubits)
    pairs = [(c.qubit_a, c.qubit_b) for c in r1.couplings]
    assert pairs == [("A", "B"), ("A", "C"), ("B", "C")]   # i<j, deterministic
    assert pairs == [(c.qubit_a, c.qubit_b) for c in r2.couplings]


# ---------------------------------------------------------------------------
# (1) floating / differential (multi-island) transmons — GH #20
#
# theta_k = phi_a - phi_b (junction branch), sigma_k = (phi_a + phi_b)/2;
# phi = B xi,  C' = B^T C_S B,  E_C = (e^2/2)[C'^-1]_{theta theta,kk}.
# ---------------------------------------------------------------------------

def _floating_pair(g: float, m: float) -> CapacitanceResult:
    """Symmetric 2-pad floating qubit: C_S = [[g+m, -m], [-m, g+m]] with
    g = pad-to-ground capacitance and m = pad-to-pad capacitance (fF)."""
    return CapacitanceResult(
        postpro_dir=Path("."), available=True,
        terminals=(TerminalBinding(1, "Q_top_sfs", 11),
                   TerminalBinding(2, "Q_bot_sfs", 12)),
        maxwell=[[g + m, -m], [-m, g + m]])


def test_symmetric_floating_pair_matches_hand_derivation():
    """Hand derivation, concrete numbers g=30 fF, m=5 fF:

        C_S = [[35, -5], [-5, 35]],  B = [[.5, 1], [-.5, 1]]
        C' = B^T C_S B = [[g/2 + m, 0], [0, 2g]] = [[20, 0], [0, 60]]

    C' is block diagonal (theta and sigma decouple by symmetry), so
        C_Sigma = 1/[C'^-1]_{theta theta} = C'_{theta theta} = g/2 + m = 20 fF
                = c_tb + (c_t0 || c_b0) = 5 + 30/2.
    A wrong single-island read of the same device would give the raw Maxwell
    diagonal 35 fF (the other pad silently grounded) — 1.75x too large.
    """
    g, m = 30.0, 5.0
    q = solve_circuit_model(
        _floating_pair(g, m),
        [JunctionInput("Q", ("Q_top_sfs", "Q_bot_sfs"), L_J=10e-9)]).qubits[0]
    assert q.C_sigma_fF == pytest.approx(g / 2.0 + m, rel=1e-12)   # == 20.0
    assert q.C_sigma_fF == pytest.approx(m + 1.0 / (1.0 / g + 1.0 / g), rel=1e-12)
    assert q.E_C_GHz == pytest.approx(
        charging_energy_joule(20.0e-15) / H_PLANCK / 1e9, rel=1e-12)
    # and explicitly NOT the single-island (other pad grounded) answer:
    grounded = solve_circuit_model(
        _floating_pair(g, m),
        [JunctionInput("Q", ("Q_top_sfs",), L_J=10e-9)]).qubits[0]
    assert grounded.C_sigma_fF == pytest.approx(g + m, rel=1e-12)   # 35 fF
    assert grounded.C_sigma_fF / q.C_sigma_fF == pytest.approx(1.75, rel=1e-12)


def test_floating_island_order_does_not_change_results():
    """theta -> -theta under (a, b) -> (b, a): every observable is invariant."""
    fwd = solve_circuit_model(
        _floating_pair(30.0, 5.0),
        [JunctionInput("Q", ("Q_top_sfs", "Q_bot_sfs"), L_J=10e-9)]).qubits[0]
    rev = solve_circuit_model(
        _floating_pair(30.0, 5.0),
        [JunctionInput("Q", ("Q_bot_sfs", "Q_top_sfs"), L_J=10e-9)]).qubits[0]
    assert rev.C_sigma_fF == pytest.approx(fwd.C_sigma_fF, rel=1e-12)
    assert rev.f01_GHz == pytest.approx(fwd.f01_GHz, rel=1e-12)


def test_asymmetric_floating_pair_full_inverse_not_theta_block_only():
    """When the pads are asymmetric, theta/sigma do NOT decouple; the answer must
    come from inverting the FULL C' and taking the theta-theta element (which
    differs from 1/C'_{theta theta}, i.e. from just dropping the sigma row/col)."""
    cap = CapacitanceResult(
        postpro_dir=Path("."), available=True,
        terminals=(TerminalBinding(1, "Q_top_sfs", 11),
                   TerminalBinding(2, "Q_bot_sfs", 12)),
        # g_top = 20, g_bot = 60, m = 5
        maxwell=[[25.0, -5.0], [-5.0, 65.0]])
    q = solve_circuit_model(cap, [JunctionInput(
        "Q", ("Q_top_sfs", "Q_bot_sfs"), L_J=10e-9)]).qubits[0]
    # closed form: C' = [[(g_t+g_b)/4 + m, (g_t-g_b)/2], [(g_t-g_b)/2, g_t+g_b]]
    g_t, g_b, m = 20.0, 60.0, 5.0
    c_tt = 0.25 * (g_t + g_b) + m
    c_ts = 0.5 * (g_t - g_b)
    c_ss = g_t + g_b
    det = c_tt * c_ss - c_ts * c_ts
    expect = det / c_ss                     # 1/[C'^-1]_tt (Schur complement)
    assert q.C_sigma_fF == pytest.approx(expect, rel=1e-12)
    assert expect == pytest.approx(m + 1.0 / (1.0 / g_t + 1.0 / g_b), rel=1e-12)
    # dropping the sigma row/col instead of inverting would give c_tt = 25 fF
    assert q.C_sigma_fF != pytest.approx(c_tt, rel=1e-6)


def test_all_single_island_is_bit_identical_to_selection_matrix():
    """Backwards compatibility: for grounded qubits B degenerates to a selection
    matrix, so C' == C_S and the numbers are the pre-#20 ones EXACTLY."""
    r = solve_circuit_model(_two_pads(),
                            [JunctionInput("A", ("A_pad_sfs",), L_J=10e-9),
                             JunctionInput("B", ("B_pad_sfs",), L_J=10e-9)])
    assert r.qubits[0].C_sigma_fF == 24.57140776699029
    assert r.qubits[1].C_sigma_fF == 24.561471896482004
    assert r.couplings[0].C_g_fF == 1.98      # bit-exact |Maxwell offdiag|


def test_mixed_grounded_and_floating_qubits():
    """One grounded + one floating qubit in the same solve (B has one selection
    row and one theta/sigma pair); the grounded one keeps its 1-island answer."""
    cap = CapacitanceResult(
        postpro_dir=Path("."), available=True,
        terminals=(TerminalBinding(1, "G_pad_sfs", 11),
                   TerminalBinding(2, "F_top_sfs", 12),
                   TerminalBinding(3, "F_bot_sfs", 13)),
        maxwell=[[35.0, -0.5, -0.1],
                 [-0.5, 35.0, -5.0],
                 [-0.1, -5.0, 35.0]])
    r = solve_circuit_model(cap, [
        JunctionInput("G", ("G_pad_sfs",), L_J=10e-9),
        JunctionInput("F", ("F_top_sfs", "F_bot_sfs"), L_J=10e-9)])
    grounded, floating = r.qubits
    assert grounded.islands == ("G_pad_sfs",)
    assert floating.islands == ("F_top_sfs", "F_bot_sfs")
    # floating: pads have g = 35 - 5 - (0.5|0.1) to ground, so C_Sigma ~ g/2 + m
    assert floating.C_sigma_fF == pytest.approx(19.9, abs=0.2)
    assert grounded.C_sigma_fF == pytest.approx(35.0, abs=0.05)
    assert len(r.couplings) == 1
    # differential-to-single coupling = (c_ga - c_gb)/2 = (-0.5 + 0.1)/2
    assert r.couplings[0].C_g_fF == pytest.approx(0.2, rel=1e-12)


# --- golden fixture: the real sung_2021_device 6-terminal Maxwell matrix -----
# Gmsh + ElmerFEM on the reproduced device (mesh min 2 um / max 30 um), fF.
# Row/col order: QB1_top, QB1_bot, CPLR_top, CPLR_bot, QB2_top, QB2_bot.
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


def _sung_cap() -> CapacitanceResult:
    return CapacitanceResult(
        postpro_dir=Path("."), available=True,
        terminals=tuple(TerminalBinding(i + 1, g, 11 + i)
                        for i, g in enumerate(_SUNG_PADS)),
        maxwell=_SUNG_MAXWELL)


def _sung_qubits(differential: bool) -> list[JunctionInput]:
    out = []
    for k, name in enumerate(("QB1", "CPLR", "QB2")):
        pads = (_SUNG_PADS[2 * k], _SUNG_PADS[2 * k + 1])
        out.append(JunctionInput(name, pads if differential else pads[:1],
                                 E_J=_SUNG_EJ_GHZ[name] * 1e9 * H_PLANCK))
    return out


def test_sung_device_differential_matches_lom2():
    """Golden: three FLOATING transmons on the measured 6x6 Maxwell matrix.

    Cross-check targets (session log 2607280204 §3):
      * qiskit-metal LOM 2.0 (CompositeSystem/CircuitGraph, junction across both
        pads = the same change of variables, but via a full network reduction):
        E_C = 857.4 / 567.7 / 857.0 MHz  -> we must agree to well under 5%;
      * the hand series estimate c_tb + c_t0||c_b0 = 22.04 / 33.14 / 22.05 fF,
        which neglects the ~1 fF of stray capacitance to the *other* qubits'
        pads and so runs ~2.5% low.
    """
    r = solve_circuit_model(_sung_cap(), _sung_qubits(differential=True))
    got_c = [q.C_sigma_fF for q in r.qubits]
    got_ec = [q.E_C_GHz for q in r.qubits]
    # exact values of the implemented transformation
    assert got_c == pytest.approx([22.593002, 34.123189, 22.601826], rel=1e-6)
    assert got_ec == pytest.approx([0.8573554, 0.5676558, 0.8570206], rel=1e-6)
    # vs LOM 2.0 (MHz) — the same transformation, independent implementation
    assert [e * 1e3 for e in got_ec] == pytest.approx([857.4, 567.7, 857.0],
                                                      rel=0.001)
    # vs the hand series estimate (documented ~2.5% low)
    assert got_c == pytest.approx([22.04, 33.14, 22.05], rel=0.03)
    # The single-island reading of the SAME device (bottom pads silently
    # grounded) is the #20 bug: 1.70x on C_Sigma here.  (The session log quotes
    # 40.88 fF / 1.85x — that used the coarser setting-A mesh matrix, not this
    # setting-C one; the *differential* 22.0 fF there is the setting-C number.)
    wrong = solve_circuit_model(_sung_cap(), _sung_qubits(differential=False))
    assert wrong.qubits[0].C_sigma_fF == pytest.approx(38.358282, rel=1e-6)
    assert wrong.qubits[0].E_C_GHz == pytest.approx(0.5049817, rel=1e-6)
    assert (wrong.qubits[0].C_sigma_fF
            / r.qubits[0].C_sigma_fF) == pytest.approx(1.698, rel=0.01)


def test_sung_device_differential_coupling_capacitance():
    """C_g of two differential qubits = 1/4|c_aa + c_bb - c_ab - c_ba|."""
    r = solve_circuit_model(_sung_cap(), _sung_qubits(differential=True))
    by_pair = {(c.qubit_a, c.qubit_b): c for c in r.couplings}
    assert set(by_pair) == {("QB1", "CPLR"), ("QB1", "QB2"), ("CPLR", "QB2")}

    def diff_diff(i: int, j: int) -> float:
        a_i, b_i, a_j, b_j = 2 * i, 2 * i + 1, 2 * j, 2 * j + 1
        return abs(0.25 * (_SUNG_MAXWELL[a_i][a_j] + _SUNG_MAXWELL[b_i][b_j]
                           - _SUNG_MAXWELL[a_i][b_j] - _SUNG_MAXWELL[b_i][a_j]))

    assert by_pair[("QB1", "CPLR")].C_g_fF == pytest.approx(diff_diff(0, 1),
                                                            rel=1e-12)
    assert by_pair[("CPLR", "QB2")].C_g_fF == pytest.approx(diff_diff(1, 2),
                                                            rel=1e-12)
    assert by_pair[("QB1", "QB2")].C_g_fF == pytest.approx(diff_diff(0, 2),
                                                           rel=1e-12)
    # concrete numbers (fF)
    assert by_pair[("QB1", "CPLR")].C_g_fF == pytest.approx(0.0487, rel=1e-3)
    assert by_pair[("CPLR", "QB2")].C_g_fF == pytest.approx(0.0487, rel=1e-3)
    assert by_pair[("QB1", "QB2")].C_g_fF == pytest.approx(0.000675, rel=1e-3)
    # ...and NOT the raw node-node value (which is ~11x larger for QB1-QB2)
    assert by_pair[("QB1", "QB2")].C_g_fF != pytest.approx(
        abs(_SUNG_MAXWELL[0][4]), rel=0.1)
    # g is computed from [C'^-1] of the branch coordinates, same order as
    # LOM 2.0's compute_gs (9.79 / 9.79 / 0.216 MHz).
    assert by_pair[("QB1", "CPLR")].g_MHz == pytest.approx(10.53, rel=0.01)
    assert by_pair[("QB1", "QB2")].g_MHz == pytest.approx(0.1466, rel=0.01)


# ---------------------------------------------------------------------------
# (1) solver error handling
# ---------------------------------------------------------------------------

def test_solve_requires_maxwell_matrix():
    cap = CapacitanceResult(postpro_dir=Path("."), available=True,
                            terminals=(TerminalBinding(1, "A_pad_sfs", 11),),
                            maxwell=[], mutual=[[10.0]])
    with pytest.raises(DesignDslError, match="Maxwell"):
        solve_circuit_model(cap, [JunctionInput("A", ("A_pad_sfs",), L_J=10e-9)])


def test_island_not_a_terminal_lists_available():
    with pytest.raises(DesignDslError, match=r"not a capacitance terminal.*A_pad_sfs"):
        solve_circuit_model(_two_pads(),
                            [JunctionInput("X", ("ZZ_sfs",), L_J=10e-9)])


def test_more_than_two_islands_rejected():
    """3+ islands = 2+ junctions, which one L_J/E_J cannot express -> raise."""
    cap = CapacitanceResult(
        postpro_dir=Path("."), available=True,
        terminals=(TerminalBinding(1, "A_pad_sfs", 11),
                   TerminalBinding(2, "B_pad_sfs", 12),
                   TerminalBinding(3, "C_pad_sfs", 13)),
        maxwell=[[30.0, -2.0, -1.0], [-2.0, 31.0, -1.5], [-1.0, -1.5, 29.0]])
    with pytest.raises(DesignDslError, match="only 1 island .* or 2 islands"):
        solve_circuit_model(cap, [JunctionInput(
            "ABC", ("A_pad_sfs", "B_pad_sfs", "C_pad_sfs"), L_J=10e-9)])


def test_two_qubits_same_island_rejected():
    with pytest.raises(DesignDslError, match="same capacitance terminal"):
        solve_circuit_model(_two_pads(),
                            [JunctionInput("A", ("A_pad_sfs",), L_J=10e-9),
                             JunctionInput("A2", ("A_pad_sfs",), L_J=10e-9)])


def test_one_qubit_repeating_an_island_rejected():
    """islands=(a, a) would give theta = 0 (a singular transformation)."""
    with pytest.raises(DesignDslError, match="same capacitance terminal"):
        solve_circuit_model(_two_pads(), [JunctionInput(
            "AA", ("A_pad_sfs", "A_pad_sfs"), L_J=10e-9)])


def test_isolated_floating_pair_is_rejected_as_singular():
    """A floating island pair with NO capacitance to ground has a zero
    common-mode capacitance -> C' is singular, must raise (not invert to junk)."""
    cap = CapacitanceResult(
        postpro_dir=Path("."), available=True,
        terminals=(TerminalBinding(1, "A_pad_sfs", 11),
                   TerminalBinding(2, "B_pad_sfs", 12)),
        maxwell=[[8.0, -8.0], [-8.0, 8.0]])   # only pad-pad, nothing to ground
    with pytest.raises(DesignDslError, match="singular or ill-conditioned"):
        solve_circuit_model(cap, [JunctionInput(
            "AB", ("A_pad_sfs", "B_pad_sfs"), L_J=10e-9)])


def test_empty_qubits_rejected():
    with pytest.raises(DesignDslError, match=">=1 qubit"):
        solve_circuit_model(_two_pads(), [])


def test_near_singular_capacitance_matrix_rejected():
    """An ill-conditioned / singular Maxwell submatrix must raise, not invert
    to garbage. Regression for the review finding: the old absolute pivot floor
    (|pivot| < 1e-300) never fired at farad scale (~1e-15), so a near-singular
    matrix produced a nonsense C^-1 / E_C / f01 silently. The guard is now
    scale-relative."""
    cap = CapacitanceResult(
        postpro_dir=Path("."), available=True,
        terminals=(TerminalBinding(1, "A_pad_sfs", 11),
                   TerminalBinding(2, "B_pad_sfs", 12)),
        # rank-deficient: row1 == -row0 -> det = 0 (perfectly correlated islands)
        maxwell=[[100.0, -100.0], [-100.0, 100.0]])
    qubits = [JunctionInput("A", ("A_pad_sfs",), L_J=10e-9),
              JunctionInput("B", ("B_pad_sfs",), L_J=10e-9)]
    with pytest.raises(DesignDslError, match="singular or ill-conditioned"):
        solve_circuit_model(cap, qubits)


def test_non_transmon_regime_raises_designdslerror_not_valueerror():
    """Deep non-transmon regime (E_J/E_C < 1/8 -> perturbative f01<=0) must raise a
    clear DesignDslError, not leak a bare math-domain ValueError from the coupling."""
    cap = CapacitanceResult(
        postpro_dir=Path("."), available=True,
        terminals=(TerminalBinding(1, "Q_pad_sfs", 11),),
        maxwell=[[0.05]])  # tiny C_sigma -> huge E_C
    with pytest.raises(DesignDslError, match="non-transmon regime"):
        # huge L_J -> tiny E_J -> f01 < 0
        solve_circuit_model(cap, [JunctionInput("Q", ("Q_pad_sfs",), L_J=1e-3)])


# ---------------------------------------------------------------------------
# (1) JunctionInput validation
# ---------------------------------------------------------------------------

def test_junction_input_requires_exactly_one_of_lj_ej():
    with pytest.raises(DesignDslError, match="exactly one of L_J / E_J"):
        JunctionInput("Q", ("g",), L_J=1e-9, E_J=1e-23)
    with pytest.raises(DesignDslError, match="exactly one of L_J / E_J"):
        JunctionInput("Q", ("g",))


def test_junction_input_rejects_empty_islands_and_nonpositive():
    with pytest.raises(DesignDslError, match="islands must be non-empty"):
        JunctionInput("Q", (), L_J=1e-9)
    with pytest.raises(DesignDslError, match="L_J must be > 0"):
        JunctionInput("Q", ("g",), L_J=-1e-9)
    with pytest.raises(DesignDslError, match="E_J must be > 0"):
        JunctionInput("Q", ("g",), E_J=0.0)


# ---------------------------------------------------------------------------
# (1) result dataclass shape
# ---------------------------------------------------------------------------

def test_result_units_and_method():
    r = solve_circuit_model(_single(135.0),
                            [JunctionInput("Q", ("Q_pad_sfs",), L_J=10e-9)])
    assert isinstance(r, CircuitModelResult)
    assert r.method == "lumped_oscillator_inverse_cap"
    assert "perturbative transmon" in r.validity
    assert r.units["capacitance"] == "fF" and r.units["coupling"] == "MHz"
    assert isinstance(r.qubits[0], QubitResult)


# ---------------------------------------------------------------------------
# (2) circuit_model sidecar block — parse / schema / unit scaling
# ---------------------------------------------------------------------------

_GEO = Path(__file__).parent / "fixtures" / "two_pads.geo"


def _sidecar(tmp_path: Path, circuit_block: str) -> Path:
    text = (
        "schema: qiskit-metal/design-dsl/3\n"
        f"geo: {_GEO}\n"
        "vars: {}\n"
        "simulation:\n"
        "  gmsh:\n"
        "    layer_stack:\n"
        "      1: {kind: metal, thickness: 2, z: 0, material: pec}\n"
        "      3: {kind: dielectric, thickness: -100, z: 0, eps_r: 11.45}\n"
        "    airbox: {top: 120, bottom: 120, side_buffer: 80}\n"
        "    mesh: {max_size: 40, min_size: 4}\n"
        f"{circuit_block}"
    )
    p = tmp_path / "x.meta.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_circuit_block_parses_and_scales_units(tmp_path):
    meta = parse_geo_meta_sidecar(_sidecar(tmp_path,
        "circuit_model:\n"
        "  qubits:\n"
        "    - {name: A, island: A_pad_sfs, L_J: 10nH}\n"
        "    - {name: B, islands: [B_pad_sfs], E_J: 16GHz}\n"))
    qs = meta["circuit_model"]["qubits"]
    assert [q["name"] for q in qs] == ["A", "B"]
    assert qs[0]["islands"] == ("A_pad_sfs",)        # scalar island -> 1-tuple
    assert qs[0]["L_J"] == pytest.approx(10e-9)       # 10nH -> Henry
    assert qs[0]["E_J"] is None
    assert qs[1]["islands"] == ("B_pad_sfs",)
    assert qs[1]["E_J"] == pytest.approx(16e9 * H_PLANCK)  # 16GHz -> Joule (×h)
    assert qs[1]["L_J"] is None


def test_shipped_two_pads_sidecar_wires_islands_and_lj(tmp_path):
    """GH #20 (stale half): the shipped fixture authors the SCALAR ``island:`` key
    and ``L_J: 10nH``; the parser must hand ``geo_build``/``JunctionInput`` an
    ``islands`` TUPLE and L_J in Henry (not the literal string).  Exercises the
    real fixture + the exact geo_build wiring, so the fix stays fixed."""
    meta = parse_geo_meta_sidecar(Path(__file__).parent / "fixtures"
                                  / "two_pads.meta.yaml")
    qs = meta["circuit_model"]["qubits"]
    assert [q["islands"] for q in qs] == [("A_pad_sfs",), ("B_pad_sfs",)]
    assert [q["L_J"] for q in qs] == [pytest.approx(10e-9), pytest.approx(10e-9)]
    assert all(q["E_J"] is None for q in qs)
    # ...and the geo_build wiring block, verbatim, then a real solve:
    junctions = [JunctionInput(name=q["name"], islands=tuple(q["islands"]),
                               L_J=q.get("L_J"), E_J=q.get("E_J")) for q in qs]
    r = solve_circuit_model(_two_pads(), junctions)
    assert [q.name for q in r.qubits] == ["A", "B"]
    assert r.qubits[0].E_J_GHz == pytest.approx(
        josephson_energy_joule(10e-9) / H_PLANCK / 1e9, rel=1e-12)


def test_circuit_block_absent_yields_none(tmp_path):
    meta = parse_geo_meta_sidecar(_sidecar(tmp_path, ""))
    assert meta["circuit_model"] is None


def test_circuit_structured_island_token_normalizes(tmp_path):
    meta = parse_geo_meta_sidecar(_sidecar(tmp_path,
        "circuit_model:\n  qubits:\n"
        '    - {name: A, island: "metal::1::A::pad", L_J: 10nH}\n'))
    assert meta["circuit_model"]["qubits"][0]["islands"] == ("A_pad_sfs",)


def test_circuit_structured_island_non_metal_role_rejected(tmp_path):
    # only metal conductor surfaces become qubit-island terminals
    with pytest.raises(DesignDslError, match="role 'metal'"):
        parse_geo_meta_sidecar(_sidecar(tmp_path,
            "circuit_model:\n  qubits:\n"
            '    - {name: A, island: "ground::1::chip::gnd", L_J: 10nH}\n'))


@pytest.mark.parametrize("block, match", [
    ("circuit_model:\n  qubits:\n    - {name: A, L_J: 10nH}\n",
     "exactly one of 'island'"),
    ("circuit_model:\n  qubits:\n    - {name: A, island: A_pad_sfs}\n",
     "exactly one of 'L_J'"),
    ("circuit_model:\n  qubits:\n    - {name: A, island: A_pad_sfs, L_J: 10nH, E_J: 16GHz}\n",
     "exactly one of 'L_J'"),
    ("circuit_model:\n  qubits:\n    - {name: A, island: A_pad_sfs, L_J: 10nH, bogus: 1}\n",
     "[Uu]nknown"),
    ("circuit_model:\n  qubits: []\n", "non-empty list"),
    ("circuit_model:\n  qubits:\n"
     "    - {name: A, island: A_pad_sfs, L_J: 10nH}\n"
     "    - {name: A, island: B_pad_sfs, L_J: 10nH}\n", "reused"),
    ("circuit_model:\n  qubits:\n"
     "    - {name: A, island: A_pad_sfs, L_J: 10nH}\n"
     "    - {name: B, island: A_pad_sfs, L_J: 10nH}\n", "already bound"),
    ("circuit_model:\n  qubits:\n    - {name: A, island: A_pad_sfs, L_J: 10}\n",
     "explicit unit"),
    ("circuit_model:\n  qubits:\n    - {name: A, island: A_pad_sfs, L_J: 10mH-bad}\n",
     "must be"),
])
def test_circuit_block_invalid_raises(tmp_path, block, match):
    with pytest.raises(DesignDslError, match=match):
        parse_geo_meta_sidecar(_sidecar(tmp_path, block))


def test_unit_value_henry_variants():
    assert _parse_unit_value("10nH", _HENRY_UNITS, owner="x") == 10e-9
    assert _parse_unit_value("5pH", _HENRY_UNITS, owner="x") == 5e-12
    assert _parse_unit_value("1H", _HENRY_UNITS, owner="x") == 1.0
    with pytest.raises(DesignDslError, match="unsupported unit"):
        _parse_unit_value("10kH", _HENRY_UNITS, owner="x")
    # explicit unit required — a bare number is a footgun (10 H vs 10 nH)
    with pytest.raises(DesignDslError, match="explicit unit"):
        _parse_unit_value(10, _HENRY_UNITS, owner="x")
    with pytest.raises(DesignDslError, match="explicit unit"):
        _parse_unit_value("10", _HENRY_UNITS, owner="x")


def test_ej_parse_freq_and_energy_and_joule():
    assert _parse_ej_joule("16GHz", owner="x") == pytest.approx(16e9 * H_PLANCK)
    assert _parse_ej_joule("16000MHz", owner="x") == pytest.approx(16e9 * H_PLANCK)
    assert _parse_ej_joule("1.06e-23J", owner="x") == pytest.approx(1.06e-23)
    # explicit unit required for E_J too
    with pytest.raises(DesignDslError, match="explicit unit"):
        _parse_ej_joule(1.06e-23, owner="x")


# ---------------------------------------------------------------------------
# (3) results write-back — tier 2 + hamiltonian section + regression guards
# ---------------------------------------------------------------------------

def _attrs():
    return {"Q1_pad_sfs": 11, "Q2_pad_sfs": 12, "substrate_layer3": 30,
            "vacuum": 40, "vacuum_outer": 41}


_MAXWELL_CSV = (
    "        i,                C[i][1] (F),                C[i][2] (F)\n"
    " 1.00e+00,        +1.354305474059e-10,        -3.306523790651e-11\n"
    " 2.00e+00,        -3.306523790651e-11,        +1.354665489642e-10\n"
)
_MUTUAL_CSV = (
    "        i,              C_m[i][1] (F),              C_m[i][2] (F)\n"
    " 1.00e+00,        +1.023653094993e-10,        +3.306523790651e-11\n"
    " 2.00e+00,        +3.306523790651e-11,        +1.024013110577e-10\n"
)


def _cap(tmp_path) -> CapacitanceResult:
    postpro = tmp_path / "postpro"
    postpro.mkdir(parents=True, exist_ok=True)
    (postpro / "terminal-C.csv").write_text(_MAXWELL_CSV, encoding="utf-8")
    (postpro / "terminal-Cm.csv").write_text(_MUTUAL_CSV, encoding="utf-8")
    return parse_capacitance_matrix(postpro, terminals=terminal_bindings(_attrs()))


def test_writeback_with_circuit_model_is_tier2_with_hamiltonian(tmp_path):
    cap = _cap(tmp_path)
    cm = solve_circuit_model(cap, [
        JunctionInput("Q1", ("Q1_pad_sfs",), L_J=10e-9),
        JunctionInput("Q2", ("Q2_pad_sfs",), L_J=10e-9)])
    out = write_results_sidecar(cap, tmp_path / "chip.results.yaml", circuit_model=cm)
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert doc["tier"] == 2                                  # descending ladder
    assert "lower = more derived" in doc["tier_meaning"]
    ham = doc["hamiltonian"]
    assert ham["method"] == "lumped_oscillator_inverse_cap"
    assert [q["name"] for q in ham["qubits"]] == ["Q1", "Q2"]
    assert ham["qubits"][0]["E_C_GHz"] > 0
    assert ham["qubits"][0]["anharmonicity_MHz"] < 0
    assert ham["qubits"][0]["islands"] == ["Q1_pad_sfs"]     # tuple -> YAML list
    assert len(ham["couplings"]) == 1
    assert {ham["couplings"][0]["qubit_a"], ham["couplings"][0]["qubit_b"]} == {"Q1", "Q2"}
    # capacitance section still present alongside the Hamiltonian
    assert doc["capacitance"]["available"] is True


def test_writeback_without_circuit_model_stays_tier3(tmp_path):
    out = write_results_sidecar(_cap(tmp_path), tmp_path / "r.yaml")
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert doc["tier"] == 3
    assert "hamiltonian" not in doc


def test_results_with_hamiltonian_is_not_a_valid_meta_sidecar(tmp_path):
    """Outputs (incl. the derived Hamiltonian) never re-enter as a Layer-1 input."""
    cap = _cap(tmp_path)
    cm = solve_circuit_model(cap, [
        JunctionInput("Q1", ("Q1_pad_sfs",), L_J=10e-9),
        JunctionInput("Q2", ("Q2_pad_sfs",), L_J=10e-9)])
    out = write_results_sidecar(cap, tmp_path / "chip.results.yaml", circuit_model=cm)
    with pytest.raises(DesignDslError):
        parse_geo_meta_sidecar(out)


# ---------------------------------------------------------------------------
# purity — circuit_model must not pull gmsh / gdstk / scqubits
# ---------------------------------------------------------------------------

def test_circuit_model_import_is_pure():
    # gmsh/gdstk: the CLAUDE.md contract (optional backends, never eager).
    # scqubits: the design deliberately avoids it (closed-form only).
    # (qutip/pyEPR/matplotlib are pulled by the BASE qiskit-metal import, which
    #  is out of circuit_model's control, so they're not asserted here.)
    code = (
        "import quantum_dsl.dsl.circuit_model, sys\n"
        "bad=[m for m in ('gmsh','gdstk','scqubits') if m in sys.modules]\n"
        "print(','.join(bad))\n"
        "sys.exit(1 if bad else 0)\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, env=env)
    assert r.returncode == 0, f"circuit_model pulled heavy deps: {r.stdout!r} {r.stderr!r}"


# ---------------------------------------------------------------------------
# optional adversarial cross-check against qiskit-metal's exact CPB diagonaliser
# (heavy import: pyEPR/qutip/matplotlib — gated like the gmsh/gdstk tests)
# ---------------------------------------------------------------------------

def test_closed_form_vs_exact_cpb_diagonalisation():
    tcb = pytest.importorskip(
        "qiskit_metal.analyses.hamiltonian.transmon_charge_basis")
    # in-regime transmon (EJ/EC ~ 114) for a clean perturbative-vs-exact compare
    q = solve_circuit_model(_single(135.0),
                            [JunctionInput("Q", ("Q_pad_sfs",), L_J=10e-9)]).qubits[0]
    H = tcb.Hcpb(nlevels=15, Ej=q.E_J_GHz * 1e3, Ec=q.E_C_GHz * 1e3, ng=0.5)  # MHz
    f01_exact_GHz = H.fij(0, 1) / 1e3
    anh_exact_MHz = H.anharm()
    # closed-form f01 within ~1% of the exact diagonalisation
    assert q.f01_GHz == pytest.approx(f01_exact_GHz, rel=0.01)
    # anharmonicity: negative, same order, magnitude >= |E_C| (perturbative -E_C
    # underestimates) and within ~1.5x
    assert anh_exact_MHz < 0
    assert abs(anh_exact_MHz) == pytest.approx(abs(q.anharmonicity_MHz), rel=0.5)
