# -*- coding: utf-8 -*-
"""M8 P0-D/P0-E — circuit-model subsystems: TL resonator + chi, junction C_j.

Pure Python (no gmsh/gdstk/numpy/scipy), so it runs in every env; the two
cross-check tests against qiskit-metal's OLD LOM are gated with
``pytest.importorskip`` on the module they actually need
(``qiskit_metal.analyses.quantization.lumped_capacitive``) — everything else
here is unconditional and pins the reference numbers as literals.

Reference implementation (Apache-2.0, read-only):
``~/metal/qiskit-metal/src/qiskit_metal/analyses/quantization/lumped_capacitive.py``
  * ``:238-250`` — the Cr/Lr equivalent-lumped block (incl. the lambda/4 correction)
  * ``:133-158`` — ``chi()``, Koch et al. 2007 eq. (3.9)/(3.10)
  * ``:320``     — ``Cq = tCSq + CJ`` (the OLD scalar C_j treatment, see below)
  * ``:402``     — the ``2 * chi(...)`` call site (total chi = the 0->1 splitting)

The golden literals below were produced by
``conda run -n quantum-metal python <scratchpad>/lom_old_ref.py`` (quantum-metal
0.7.6); qiskit_metal 0.5.1 in ``metal-env`` has a byte-identical ``chi()`` and
Cr/Lr block and reproduces them to ~1e-13 (its numerical CPB diagonaliser is
iterative, hence the loose tolerances on ``fQ``/``alpha`` only).
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from quantum_dsl.dsl.circuit_model import (
    ELEM_CHARGE,
    H_PLANCK,
    JunctionInput,
    QubitResonatorCoupling,
    ResonatorInput,
    ResonatorResult,
    dispersive_shift_hz,
    resonator_lumped_lc,
    solve_circuit_model,
)
from quantum_dsl.dsl.errors import DesignDslError
from quantum_dsl.dsl.palace_adapter import CapacitanceResult, TerminalBinding


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _cap(maxwell: list[list[float]], groups: tuple[str, ...]) -> CapacitanceResult:
    return CapacitanceResult(
        postpro_dir=Path("."), available=True,
        terminals=tuple(TerminalBinding(i + 1, g, 11 + i)
                        for i, g in enumerate(groups)),
        maxwell=maxwell)


# --- the M6 golden fixture, copied verbatim from tests/test_circuit_model.py --
# (that file is the untouchable golden; duplicating the literals here keeps this
#  file self-contained and lets us assert bit-identity against its numbers.)
_SUNG_MAXWELL = [
    [38.3635, -6.8074, -0.5407, -0.4427, -0.0628, -0.0615],
    [-6.8074, 38.3940, -0.4435, -0.5403, -0.0615, -0.0629],
    [-0.5407, -0.4435, 57.3523, -10.9032, -0.5404, -0.4436],
    [-0.4427, -0.5403, -10.9032, 57.3349, -0.4432, -0.5413],
    [-0.0628, -0.0615, -0.5404, -0.4432, 38.3767, -6.8111],
    [-0.0615, -0.0629, -0.4436, -0.5413, -6.8111, 38.4087],
]
_SUNG_PADS = ("QB1_pad_top_sfs", "QB1_pad_bot_sfs", "CPLR_pad_top_sfs",
              "CPLR_pad_bot_sfs", "QB2_pad_top_sfs", "QB2_pad_bot_sfs")
_SUNG_EJ_GHZ = {"QB1": 12.2, "CPLR": 71.0, "QB2": 15.8}
# the recorded golden of tests/test_circuit_model.py::
# test_sung_device_differential_matches_lom2
_SUNG_C_SIGMA_GOLDEN = [22.593002, 34.123189, 22.601826]


def _sung_qubits(c_j: float = 0.0, **kw) -> list[JunctionInput]:
    return [JunctionInput(name, (_SUNG_PADS[2 * k], _SUNG_PADS[2 * k + 1]),
                          E_J=_SUNG_EJ_GHZ[name] * 1e9 * H_PLANCK, C_j=c_j, **kw)
            for k, name in enumerate(("QB1", "CPLR", "QB2"))]


# --- differential transmon + one readout claw (the chi cross-check system) ----
# Physical capacitances (fF): pad_top-ground 45, pad_bot-ground 45,
# pad_top-pad_bot 60 (the shunt), pad_top-claw 8, pad_bot-claw 0.5,
# claw-ground 30.  Maxwell form with ground implicit (= our convention):
_RD_MAXWELL = [[113.0, -60.0, -8.0],
               [-60.0, 105.5, -0.5],
               [-8.0, -0.5, 38.5]]
_RD_PADS = ("Q_top_sfs", "Q_bot_sfs", "RD_claw_sfs")
_RD_L_J = 10e-9
_RD_F_RES = 7.0e9          # BARE readout frequency (Hz)

# Our own numbers for that system (regression pins, C_j = 0, half_wave, Z0=50).
_OURS = dict(C_sigma_fF=84.46662263277662, E_C_GHz=0.22932406577770107,
             f01_GHz=5.246854069748924, Cr_fF=714.2857142857143,
             Lr_nH=0.7237227403024126, f_loaded_GHz=6.822603843205575,
             g_MHz=41.190719092148356, chi_MHz=-0.2291871462281004)

# Old-LOM reference for the SAME system (extract_transmon_coupled_Noscillator
# with N=1, fr=7.0 GHz, Ic=phi0/L_J, CJ=0; see the module docstring).
_OLD_LOM = dict(Cq_fF=84.48223883829345, fQ_GHz=5.235537599557561,
                alpha_MHz=-256.28502892891396, gbus_MHz=43.06517790777625,
                chi_MHz=-0.27309861667090973,
                # chi() re-evaluated with THEIR g but OUR perturbative spectrum
                # (f01 = 5.246390311135003 GHz from THEIR Cq, alpha = -E_C):
                chi_their_g_our_spectrum_MHz=-0.25035833834113286,
                f01_from_their_Cq_GHz=5.246390311135003,
                alpha_from_their_Cq_MHz=-229.2816761371046)


def _rd_solve(c_j: float = 0.0, mode: str = "half_wave", **res_kw):
    return solve_circuit_model(
        _cap(_RD_MAXWELL, _RD_PADS),
        [JunctionInput("Q", ("Q_top_sfs", "Q_bot_sfs"), L_J=_RD_L_J, C_j=c_j)],
        resonators=[ResonatorInput("RD", "RD_claw_sfs", _RD_F_RES, mode=mode,
                                   **res_kw)])


# ===========================================================================
# P0-E — junction capacitance C_j
# ===========================================================================

def test_c_j_defaults_to_zero_and_leaves_the_m6_golden_bit_identical():
    """C_j is opt-in: omitted == 0.0 == the recorded M6 golden, bit for bit."""
    cap = _cap(_SUNG_MAXWELL, _SUNG_PADS)
    default = solve_circuit_model(cap, _sung_qubits())          # C_j omitted
    explicit = solve_circuit_model(cap, _sung_qubits(c_j=0.0))  # C_j = 0.0
    assert default == explicit                                  # frozen dataclasses
    got = [q.C_sigma_fF for q in default.qubits]
    assert got == pytest.approx(_SUNG_C_SIGMA_GOLDEN, rel=1e-6)
    # exact literals of the transformation (same as the untouched golden file)
    assert got == [22.593001787855712, 34.12318915759456, 22.60182634765305]
    # with no C_j the geometric and the effective capacitance are THE SAME float
    for q in default.qubits:
        assert q.C_sigma_geometric_fF == q.C_sigma_fF
    # and the P0-D fields stay empty -> old consumers see no change
    assert default.resonators == () and default.resonator_couplings == ()


def test_c_j_on_an_isolated_island_matches_the_closed_form():
    """1x1 matrix: C_j is a plain parallel capacitance -> E_C = e^2/(2(C+C_j))."""
    cap = _cap([[135.0]], ("Q_pad_sfs",))
    base = solve_circuit_model(
        cap, [JunctionInput("Q", ("Q_pad_sfs",), L_J=10e-9)]).qubits[0]
    with_cj = solve_circuit_model(
        cap, [JunctionInput("Q", ("Q_pad_sfs",), L_J=10e-9, C_j=2e-15)]).qubits[0]
    assert base.C_sigma_fF == 135.0
    assert with_cj.C_sigma_fF == pytest.approx(137.0, rel=1e-12)
    assert with_cj.C_sigma_geometric_fF == pytest.approx(135.0, rel=1e-12)
    # E_C = e^2/(2 C_Sigma) -> the drop is exactly the capacitance ratio
    assert with_cj.E_C_GHz == pytest.approx(base.E_C_GHz * 135.0 / 137.0,
                                            rel=1e-12)
    assert with_cj.E_C_GHz == pytest.approx(
        ELEM_CHARGE ** 2 / (2.0 * 137e-15) / H_PLANCK / 1e9, rel=1e-12)


def test_c_j_theta_diagonal_fold_equals_the_node_basis_fold():
    """C_j folded on the junction-branch diagonal == New LOM's node-basis fold.

    New LOM folds ``cj_dict`` into the capacitance GRAPH
    (``lom_core_analysis.py:228`` ``_cj_dict_to_adj_list``), i.e. in the NODE
    basis: ``C_aa += C_j``, ``C_bb += C_j``, ``C_ab = C_ba -= C_j``.  Pushing that
    through ``C' = B^T dC B`` leaves exactly ``C'_theta,theta += C_j`` and zero
    everywhere else (sigma-sigma: C_j + C_j - C_j - C_j = 0; theta-sigma:
    0.5 - 0.5 - 0.5 + 0.5 = 0).  So folding one number on the theta diagonal
    needs no knowledge of the cell topology — and this test proves it on a real
    3-qubit coupled matrix, to the last bit (C_Sigma *and* every g).
    """
    c_j = 2e-15
    c_j_fF = c_j / 1e-15
    hand = [list(row) for row in _SUNG_MAXWELL]
    for k in range(3):
        a, b = 2 * k, 2 * k + 1
        hand[a][a] += c_j_fF
        hand[b][b] += c_j_fF
        hand[a][b] -= c_j_fF
        hand[b][a] -= c_j_fF
    node_basis = solve_circuit_model(_cap(hand, _SUNG_PADS), _sung_qubits())
    theta_basis = solve_circuit_model(_cap(_SUNG_MAXWELL, _SUNG_PADS),
                                      _sung_qubits(c_j=c_j))
    for a, b in zip(node_basis.qubits, theta_basis.qubits):
        assert a.C_sigma_fF == b.C_sigma_fF      # bit-identical, not approx
        assert a.E_C_GHz == b.E_C_GHz
        assert a.f01_GHz == b.f01_GHz
    for a, b in zip(node_basis.couplings, theta_basis.couplings):
        assert (a.qubit_a, a.qubit_b) == (b.qubit_a, b.qubit_b)
        assert a.g_MHz == b.g_MHz


def test_c_j_renormalises_the_coupling_not_only_the_charging_energy():
    """Why C_j must go in BEFORE the inverse: it changes g, not just E_C.

    The old-LOM scalar recipe (``Cq = tCSq + CJ``,
    ``lumped_capacitive.py:320``) only touches C_Sigma, so g would come out
    unchanged.  Folding C_j into C' before inverting also renormalises the
    off-diagonals: measured here on the sung 3-qubit matrix with C_j = 2 fF on
    all three junctions, g(QB1-CPLR) drops 10.53 -> 9.49 MHz (-9.85%) — the
    physically right direction (more shunt capacitance = weaker coupling).

    On the diagonal the two recipes very nearly agree for this weakly-coupled
    device (Sherman-Morrison makes them identical when only ONE junction carries
    C_j; with all three it is a rank-3 update, measured deviation +1.6e-7
    relative) — small here, but it is not an identity, and the coupling term is
    not small at all.
    """
    cap = _cap(_SUNG_MAXWELL, _SUNG_PADS)
    base = solve_circuit_model(cap, _sung_qubits())
    with_cj = solve_circuit_model(cap, _sung_qubits(c_j=2e-15))
    # g is renormalised downwards by ~10%
    g0 = {(c.qubit_a, c.qubit_b): c.g_MHz for c in base.couplings}
    g1 = {(c.qubit_a, c.qubit_b): c.g_MHz for c in with_cj.couplings}
    assert g0[("QB1", "CPLR")] == pytest.approx(10.529684360002658, rel=1e-9)
    assert g1[("QB1", "CPLR")] == pytest.approx(9.49211879568466, rel=1e-9)
    assert g1[("QB1", "CPLR")] / g0[("QB1", "CPLR")] == pytest.approx(0.90151,
                                                                     rel=1e-4)
    # C_g is a purely geometric quantity -> untouched by C_j
    cg0 = {(c.qubit_a, c.qubit_b): c.C_g_fF for c in base.couplings}
    cg1 = {(c.qubit_a, c.qubit_b): c.C_g_fF for c in with_cj.couplings}
    assert cg0 == cg1
    # the diagonal is NOT exactly the naive scalar sum, and the reported
    # geometric value is the real C_j-free solve (not "effective minus C_j")
    for b, w in zip(base.qubits, with_cj.qubits):
        assert w.C_sigma_geometric_fF == b.C_sigma_fF        # bit-identical
        scalar = b.C_sigma_fF + 2.0
        assert w.C_sigma_fF == pytest.approx(scalar, rel=1e-6)
        assert w.C_sigma_fF != scalar
        assert w.C_sigma_fF - scalar > 0                     # rank-3 cross term


@pytest.mark.parametrize("bad", [-1e-15, float("nan"), float("inf"),
                                 float("-inf")])
def test_c_j_rejects_negative_and_non_finite(bad):
    with pytest.raises(DesignDslError, match="C_j must be >= 0 and finite"):
        JunctionInput("Q", ("Q_pad_sfs",), L_J=10e-9, C_j=bad)


# ===========================================================================
# P0-D — TL resonator equivalent lumped LC
# ===========================================================================

def test_resonator_lumped_lc_goldens():
    """Cr = pi/(2 wr Z0), Lr = 1/(wr^2 Cr) — literals from the reference block."""
    c_r, l_r = resonator_lumped_lc(7.0e9, 50.0)
    assert c_r == pytest.approx(7.142857142857143e-13, rel=1e-15)
    assert l_r == pytest.approx(7.237227403024126e-10, rel=1e-15)
    # closed form, independent of the literals
    omega = 2.0 * math.pi * 7.0e9
    assert c_r == pytest.approx(math.pi / (2.0 * omega * 50.0), rel=1e-15)
    assert l_r == pytest.approx(1.0 / (omega ** 2 * c_r), rel=1e-15)
    # ...and it really is the resonance: 1/(2 pi sqrt(Lr Cr)) == f_res
    assert 1.0 / (2.0 * math.pi * math.sqrt(l_r * c_r)) == pytest.approx(7.0e9,
                                                                        rel=1e-12)


def test_quarter_wave_halves_cr_and_doubles_lr():
    """Direction check (``lumped_capacitive.py:246-250``: Cr /= 2, Lr *= 2).

    A lambda/4 resonator has HALF the effective capacitance of the lambda/2 case
    at the SAME resonance frequency (and hence twice the inductance) — not the
    other way round.
    """
    half = resonator_lumped_lc(7.0e9, 50.0, "half_wave")
    quarter = resonator_lumped_lc(7.0e9, 50.0, "quarter_wave")
    assert quarter[0] == half[0] / 2.0
    assert quarter[1] == half[1] * 2.0
    assert quarter == (3.5714285714285717e-13, 1.4474454806048253e-09)
    # same resonance frequency in both modes
    for c_r, l_r in (half, quarter):
        assert 1.0 / (2.0 * math.pi * math.sqrt(l_r * c_r)) == pytest.approx(
            7.0e9, rel=1e-12)
    # Z0 enters Cr linearly (inverse) -> a 100 ohm line has half the Cr
    assert resonator_lumped_lc(7.0e9, 100.0)[0] == pytest.approx(half[0] / 2.0,
                                                                 rel=1e-15)
    with pytest.raises(DesignDslError, match="is not one of"):
        resonator_lumped_lc(7.0e9, 50.0, "lambda_over_3")


# ===========================================================================
# P0-D — the solve: loading, f_bare vs f_loaded, g and chi
# ===========================================================================

def test_resonator_result_shape_and_regression_pins():
    r = _rd_solve()
    assert len(r.resonators) == 1 and len(r.resonator_couplings) == 1
    res, rc = r.resonators[0], r.resonator_couplings[0]
    assert isinstance(res, ResonatorResult)
    assert isinstance(rc, QubitResonatorCoupling)
    assert (res.name, res.node, res.Z0_ohm, res.mode) == (
        "RD", "RD_claw_sfs", 50.0, "half_wave")
    assert (rc.qubit, rc.resonator) == ("Q", "RD")
    assert rc.chi_method == "perturbative"       # spec R6 — analytic, not exact
    assert res.Cr_fF == pytest.approx(_OURS["Cr_fF"], rel=1e-12)
    assert res.Lr_nH == pytest.approx(_OURS["Lr_nH"], rel=1e-12)
    assert res.f_bare_GHz == 7.0
    assert res.f_loaded_GHz == pytest.approx(_OURS["f_loaded_GHz"], rel=1e-12)
    assert rc.g_MHz == pytest.approx(_OURS["g_MHz"], rel=1e-9)
    assert rc.chi_MHz == pytest.approx(_OURS["chi_MHz"], rel=1e-9)
    q = r.qubits[0]
    assert q.C_sigma_fF == pytest.approx(_OURS["C_sigma_fF"], rel=1e-12)
    assert q.f01_GHz == pytest.approx(_OURS["f01_GHz"], rel=1e-12)
    # the claw is a REAL conductor in the matrix, so it must not be silently
    # grounded: solving without the resonator gives a different C_Sigma
    without = solve_circuit_model(
        _cap(_RD_MAXWELL, _RD_PADS),
        [JunctionInput("Q", ("Q_top_sfs", "Q_bot_sfs"), L_J=_RD_L_J)])
    assert without.qubits[0].C_sigma_fF != pytest.approx(q.C_sigma_fF, rel=1e-9)
    assert without.resonators == ()


def test_loading_lowers_the_frequency_by_the_capacitance_ratio():
    """f_loaded < f_bare, and exactly = f_bare sqrt(Cr / Cr_eff).

    The claw's measured capacitance sits in parallel with the analytic Cr on the
    same node, so C_r,eff > Cr and the mode softens.  ``f_bare`` is the INPUT
    (the bare line, old-LOM ``freq_readout`` semantics); New LOM's ``f_res`` is
    the DRESSED frequency instead — different meaning, spec R5.
    """
    res = _rd_solve().resonators[0]
    assert res.f_loaded_GHz < res.f_bare_GHz
    # C_r,eff back out of the reported frequencies (Lr is fixed by f_bare/Z0)
    c_eff_fF = res.Cr_fF * (res.f_bare_GHz / res.f_loaded_GHz) ** 2
    # claw self-capacitance is 38.5 fF; the differential pads shunt part of it,
    # so the loading is a bit less than a naive Cr + 38.5
    assert c_eff_fF == pytest.approx(res.Cr_fF + 37.8, abs=0.5)
    assert res.f_loaded_GHz / res.f_bare_GHz == pytest.approx(
        math.sqrt(res.Cr_fF / c_eff_fF), rel=1e-12)
    # a quarter-wave line has half the Cr, so the same claw loads it MORE
    q4 = _rd_solve(mode="quarter_wave").resonators[0]
    assert q4.f_loaded_GHz < res.f_loaded_GHz
    assert q4.f_loaded_GHz == pytest.approx(6.658045212384812, rel=1e-12)


def test_dispersive_shift_is_homogeneous_so_hz_needs_no_2pi():
    """chi() is degree-1 in frequency -> feeding Hz returns Hz.

    The reference passes rad/s and divides the result by 2*pi at the call site
    (``lumped_capacitive.py:402``); we pass Hz throughout, which is the same
    number without the round trip.
    """
    args = (40e6, 7.0e9, 5.2e9, 5.2e9 - 230e6)
    base = dispersive_shift_hz(*args)
    scaled = dispersive_shift_hz(*(2.0 * math.pi * a for a in args))
    assert scaled == pytest.approx(2.0 * math.pi * base, rel=1e-12)


def test_dispersive_shift_rejects_exact_resonance():
    with pytest.raises(DesignDslError, match="diverges on resonance"):
        dispersive_shift_hz(40e6, 5.2e9, 5.2e9, 4.97e9)      # f01 == f_res
    with pytest.raises(DesignDslError, match="diverges on resonance"):
        dispersive_shift_hz(40e6, 4.97e9, 5.2e9, 4.97e9)      # f12 == f_res


def test_chi_scales_as_g_squared_and_keeps_its_sign():
    """chi ~ g^2 (leading order) and is negative for a qubit below the cavity."""
    r1 = _rd_solve()
    rc1 = r1.resonator_couplings[0]
    assert rc1.chi_MHz < 0 and r1.qubits[0].f01_GHz < r1.resonators[0].f_bare_GHz
    # doubling g at fixed detuning quadruples chi
    args = (rc1.g_MHz * 1e6, _RD_F_RES, r1.qubits[0].f01_GHz * 1e9,
            r1.qubits[0].f01_GHz * 1e9 + r1.qubits[0].anharmonicity_MHz * 1e6)
    assert 2.0 * dispersive_shift_hz(*args) / 1e6 == pytest.approx(rc1.chi_MHz,
                                                                  rel=1e-12)
    doubled = dispersive_shift_hz(2.0 * args[0], *args[1:])
    assert doubled == pytest.approx(4.0 * dispersive_shift_hz(*args), rel=1e-12)


# ===========================================================================
# P0-D — cross-check against the OLD LOM (gated: needs qiskit-metal)
# ===========================================================================

def _old_lom_capmatrix():
    """The same device as ``_RD_MAXWELL`` but in the old LOM's node order.

    ``extract_transmon_coupled_Noscillator`` wants the FULL Maxwell matrix with
    an EXPLICIT ground row/column, ordered
    ``[bus1..busN-1, ground, qubit_pad1, qubit_pad2, readout]``; with N=1 that is
    ``[ground, top, bot, readout]``.  Our convention keeps ground implicit, so
    ``_RD_MAXWELL`` is exactly this matrix with the ground row/col dropped.
    """
    caps = {(0, 1): 45.0, (0, 2): 45.0, (0, 3): 30.0,       # to ground
            (1, 2): 60.0, (1, 3): 8.0, (2, 3): 0.5}         # between conductors
    mat = [[0.0] * 4 for _ in range(4)]
    for (i, j), c in caps.items():
        mat[i][j] = mat[j][i] = -c
    for i in range(4):
        mat[i][i] = -sum(mat[i][j] for j in range(4) if j != i)
    # sanity: dropping ground reproduces our fixture
    assert [row[1:] for row in mat[1:]] == _RD_MAXWELL
    return mat


def test_dispersive_shift_matches_the_reference_chi_bit_for_bit():
    """Our ``dispersive_shift_hz`` IS the reference ``chi()`` (same inputs)."""
    lc = pytest.importorskip(
        "qiskit_metal.analyses.quantization.lumped_capacitive")
    g_hz = _OLD_LOM["gbus_MHz"] * 1e6
    f01 = _OLD_LOM["f01_from_their_Cq_GHz"] * 1e9
    f12 = f01 + _OLD_LOM["alpha_from_their_Cq_MHz"] * 1e6
    mine = dispersive_shift_hz(g_hz, _RD_F_RES, f01, f12)
    theirs = lc.chi(g_hz, _RD_F_RES, f01, f12)
    assert mine == pytest.approx(theirs, rel=1e-15)
    # and the recorded literal (so the number is pinned even without qiskit-metal)
    assert 2.0 * mine / 1e6 == pytest.approx(
        _OLD_LOM["chi_their_g_our_spectrum_MHz"], rel=1e-12)


def test_chi_cross_check_against_old_lom_extract():
    """End-to-end chi vs ``extract_transmon_coupled_Noscillator``.

    ⚠ **The spec's <5% criterion is NOT met: the measured deviation is -16.1%**
    (ours -0.22919 MHz vs old LOM -0.27310 MHz).  It is not a bug; it factors
    cleanly into the two known definitional gaps, and neither is closeable
    without leaving this module pure Python:

      * **g: -4.35%** (ours 41.191 vs theirs 43.065 MHz) — different definitions,
        exactly as the spec anticipated: we take g from the full inverse
        capacitance matrix, the old LOM from its voltage-division ratio ``bbus``
        (``lumped_capacitive.py:334`` + ``:341``).  chi ~ g^2, so this alone is
        **-8.50%**.
      * **the qubit spectrum: -8.33%** — the old LOM's f01/alpha come from a
        NUMERICAL CPB diagonalisation (``levels_vs_ng_real_units``), ours from
        the leading-order transmon expansion.  At E_J/E_C = 71 here the exact
        |alpha| is 256.3 MHz vs our -E_C = 229.3 MHz (+11.8%), which moves the
        ``f12 - f_res`` denominator of Koch eq. (3.10).  Feeding THEIR g with OUR
        spectrum into the reference ``chi()`` reproduces this -8.33% exactly
        (see ``_OLD_LOM["chi_their_g_our_spectrum_MHz"]``).  Closing it needs the
        exact diagonaliser = P1-H, deferred (and scqubits is explicitly not
        adopted, spec §6).

    0.9150 * 0.9167 = 0.8388 -> -16.1%, which is what we measure.  The
    capacitance reduction itself agrees to **0.018%** (C_Sigma 84.467 vs their
    Cq 84.482 fF), i.e. nothing in the C-matrix handling contributes.
    """
    lc = pytest.importorskip(
        "qiskit_metal.analyses.quantization.lumped_capacitive")
    import numpy as np

    phi0 = H_PLANCK / (2.0 * math.pi) / (2.0 * ELEM_CHARGE)
    cap_si = np.asarray(_old_lom_capmatrix()) * 1e-15
    old = lc.extract_transmon_coupled_Noscillator(
        cap_si, phi0 / _RD_L_J, 0.0, 1, [], _RD_F_RES / 1e9,
        res_L4_corr=None, print_info=False)
    old_chi = float(np.asarray(old["chi_in_MHz"]).ravel()[0])
    old_g = float(np.asarray(old["gbus"]).ravel()[0])
    # the reference itself is reproducible (its CPB diagonaliser is iterative,
    # hence rel=1e-6 rather than exact equality)
    assert old_chi == pytest.approx(_OLD_LOM["chi_MHz"], rel=1e-6)
    assert old_g == pytest.approx(_OLD_LOM["gbus_MHz"], rel=1e-9)

    r = _rd_solve()
    ours = r.resonator_couplings[0]
    # C_Sigma: 0.018% — the capacitance side is effectively identical
    cq_fF = (ELEM_CHARGE ** 2 / 2.0
             / (old["EC"] * 1e6 * H_PLANCK) / 1e-15)
    assert r.qubits[0].C_sigma_fF == pytest.approx(cq_fF, rel=2e-4)
    # g: the documented definitional gap (inverse-cap vs bbus)
    assert ours.g_MHz == pytest.approx(old_g, rel=0.05)
    assert ours.g_MHz / old_g == pytest.approx(0.95647, rel=1e-3)
    # chi: same sign, right order, measured -16.1% (see the docstring)
    assert ours.chi_MHz < 0 and old_chi < 0
    assert ours.chi_MHz / old_chi == pytest.approx(0.8392, rel=1e-3)
    assert ours.chi_MHz == pytest.approx(old_chi, rel=0.20)   # NOT 0.05
    # the deviation is the product of the two factors, nothing else
    g_factor = (ours.g_MHz / old_g) ** 2
    spectrum_factor = _OLD_LOM["chi_their_g_our_spectrum_MHz"] / _OLD_LOM["chi_MHz"]
    assert ours.chi_MHz / old_chi == pytest.approx(g_factor * spectrum_factor,
                                                  rel=2e-3)


def test_c_j_cross_check_against_old_lom_scalar_sum():
    """C_j = 2 fF: the old LOM's ``Cq = tCSq + CJ`` and our fold agree here.

    With a SINGLE junction carrying C_j, Sherman-Morrison makes the theta
    diagonal of the folded inverse exactly ``1/(1/[C'^-1]_theta + C_j)`` — so the
    +2 fF shows up as a plain +2 fF (matching ``lumped_capacitive.py:320``), and
    the fold-before-inverse only differs in the off-diagonals (-> g).  This pins
    that agreement against the reference implementation.
    """
    lc = pytest.importorskip(
        "qiskit_metal.analyses.quantization.lumped_capacitive")
    import numpy as np

    phi0 = H_PLANCK / (2.0 * math.pi) / (2.0 * ELEM_CHARGE)
    cap_si = np.asarray(_old_lom_capmatrix()) * 1e-15
    q_ours = _rd_solve(c_j=2e-15).qubits[0]
    old = lc.extract_transmon_coupled_Noscillator(
        cap_si, phi0 / _RD_L_J, 2e-15, 1, [], _RD_F_RES / 1e9,
        res_L4_corr=None, print_info=False)
    cq_fF = ELEM_CHARGE ** 2 / 2.0 / (old["EC"] * 1e6 * H_PLANCK) / 1e-15
    assert cq_fF == pytest.approx(86.4822389646101, rel=1e-9)     # their +2 fF
    assert q_ours.C_sigma_fF == pytest.approx(cq_fF, rel=2e-4)    # ours: +2 fF
    assert q_ours.C_sigma_fF - q_ours.C_sigma_geometric_fF == pytest.approx(
        2.0, rel=1e-12)


# ===========================================================================
# P0-D — error paths
# ===========================================================================

def test_resonator_node_must_be_a_capacitance_terminal():
    with pytest.raises(DesignDslError) as exc:
        solve_circuit_model(
            _cap(_RD_MAXWELL, _RD_PADS),
            [JunctionInput("Q", ("Q_top_sfs", "Q_bot_sfs"), L_J=_RD_L_J)],
            resonators=[ResonatorInput("RD", "nope_sfs", _RD_F_RES)])
    msg = str(exc.value)
    assert "is not a capacitance terminal" in msg
    assert "RD_claw_sfs" in msg and "Q_top_sfs" in msg      # available names


def test_resonator_node_cannot_be_a_qubit_island():
    with pytest.raises(DesignDslError, match="same capacitance terminal"):
        solve_circuit_model(
            _cap(_RD_MAXWELL, _RD_PADS),
            [JunctionInput("Q", ("Q_top_sfs", "Q_bot_sfs"), L_J=_RD_L_J)],
            resonators=[ResonatorInput("RD", "Q_bot_sfs", _RD_F_RES)])


def test_two_resonators_cannot_share_a_node():
    with pytest.raises(DesignDslError, match="another resonator's claw"):
        solve_circuit_model(
            _cap(_RD_MAXWELL, _RD_PADS),
            [JunctionInput("Q", ("Q_top_sfs",), L_J=_RD_L_J)],
            resonators=[ResonatorInput("A", "RD_claw_sfs", _RD_F_RES),
                        ResonatorInput("B", "RD_claw_sfs", 8.0e9)])


@pytest.mark.parametrize("name", ["RD", "Q"])
def test_resonator_name_must_be_unique(name):
    with pytest.raises(DesignDslError, match="already used by another"):
        solve_circuit_model(
            _cap(_RD_MAXWELL, _RD_PADS),
            [JunctionInput("Q", ("Q_top_sfs",), L_J=_RD_L_J)],
            resonators=[ResonatorInput("RD", "Q_bot_sfs", _RD_F_RES),
                        ResonatorInput(name, "RD_claw_sfs", 8.0e9)])


@pytest.mark.parametrize("bad", [0.0, -7.0e9, float("nan"), float("inf")])
def test_resonator_f_res_must_be_positive_and_finite(bad):
    with pytest.raises(DesignDslError, match="f_res must be > 0 and finite"):
        ResonatorInput("RD", "RD_claw_sfs", bad)


@pytest.mark.parametrize("bad", [0.0, -50.0, float("nan"), float("inf")])
def test_resonator_z0_must_be_positive_and_finite(bad):
    with pytest.raises(DesignDslError, match="Z0 must be > 0 and finite"):
        ResonatorInput("RD", "RD_claw_sfs", _RD_F_RES, Z0=bad)


def test_resonator_mode_must_be_known():
    with pytest.raises(DesignDslError, match="is not one of"):
        ResonatorInput("RD", "RD_claw_sfs", _RD_F_RES, mode="half-wave")


@pytest.mark.parametrize("kwargs", [dict(name=""), dict(node="")])
def test_resonator_name_and_node_must_be_non_empty(kwargs):
    args = dict(name="RD", node="RD_claw_sfs", f_res=_RD_F_RES)
    args.update(kwargs)
    with pytest.raises(DesignDslError, match="non-empty string"):
        ResonatorInput(**args)
