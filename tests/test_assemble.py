# -*- coding: utf-8 -*-
"""P0-B / M8c — the assembly layer: Cell + shared node names + Schur elimination.

Four concerns, all pure Python (no gmsh/gdstk/numpy/scipy — runnable in any env):

  (1) the Schur complement itself, against a closed-form hand calculation;
  (2) the capacitance-graph accumulation: shared node names **superpose**, they are
      not block-diagonally stacked;
  (3) the end-to-end golden case — qiskit-metal tutorial **4.05** (New LOM, two
      coupled transmons): two independently extracted Maxwell matrices stitched
      through one shared node name, cross-checked against the reference
      ``CompositeSystem`` (fixture ``tests/fixtures/lom405/``, see its ``SOURCE.md``);
  (4) the audit / warning / error paths (risks R2 + R4).

Measured deviations vs the qiskit-metal reference (see the golden tests below):
``C_n`` bit-exact (0.0), ``C_k`` 7.7e-16, ``C_inv_k`` 8.7e-16, ``C_Sigma`` 1.7e-16,
``E_C`` 7.6e-9, ``E_J`` 8.1e-4 (the last two are the CODATA-2014 vs SI-2019 constants).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from quantum_dsl.dsl.assemble import (
    AssembledSystem,
    CellJunction,
    ExtractedCell,
    assemble,
)
from quantum_dsl.dsl import circuit_model as cm
from quantum_dsl.dsl.errors import DesignDslError


FIXTURES = Path(__file__).parent / "fixtures" / "lom405"
_NH = 1e-9      # nanohenry  → henry
_FF = 1e-15     # femtofarad → farad


# ---------------------------------------------------------------------------
# (1) Schur complement — closed-form hand calculation
# ---------------------------------------------------------------------------

def test_schur_matches_hand_calculation():
    """3 nodes: a junction across (a, b) + one purely capacitive middle node m.

    Branch capacitances (fF): c_a0=10, c_b0=20, c_m0=3, c_ab=1, c_am=4, c_bm=6.
    Maxwell (+diag, −offdiag) is then

        [[15, -1, -4],
         [-1, 27, -6],
         [-4, -6, 13]]        rows/cols = (a, b, m)

    ``m`` touches no junction and is not force-kept → it is the non-dynamic node,
    ``S_r = [m]``, and eq 7b reduces to the plain Schur complement

        C_kk − C_kr C_rr⁻¹ C_rk
          = [[15, -1], [-1, 27]] − (1/13)·[[-4],[-6]]·[[-4, -6]]
          = [[15 − 16/13, −1 − 24/13], [−1 − 24/13, 27 − 36/13]]
          = [[179/13, −37/13], [−37/13, 315/13]]

    Note the sign: the mediated term makes the a–b coupling **stronger** (−1 →
    −37/13 ≈ −2.846), which is exactly the bus-mediated coupling that hard
    grounding throws away (see the Schur-vs-ground test below).
    """
    cell = ExtractedCell(
        name="hand",
        terminals=("a", "b", "m"),
        maxwell=((15.0, -1.0, -4.0),
                 (-1.0, 27.0, -6.0),
                 (-4.0, -6.0, 13.0)),
        junctions=(CellJunction(name="j", between=("a", "b"), L_J=10 * _NH),),
        source="inline",
    )
    out = assemble([cell])

    assert out.nodes == ("a", "b")
    assert out.eliminated == ("m",)
    assert out.maxwell[0][0] == pytest.approx(179.0 / 13.0, rel=1e-15)
    assert out.maxwell[0][1] == pytest.approx(-37.0 / 13.0, rel=1e-15)
    assert out.maxwell[1][0] == pytest.approx(-37.0 / 13.0, rel=1e-15)
    assert out.maxwell[1][1] == pytest.approx(315.0 / 13.0, rel=1e-15)
    # the Maxwell sign convention survives the reduction
    assert out.maxwell[0][0] > 0 and out.maxwell[1][1] > 0
    assert out.maxwell[0][1] < 0


def test_force_keep_disables_the_elimination():
    """``nodes_force_keep`` keeps a purely capacitive node → matrix stays 3x3 raw."""
    cell = ExtractedCell(
        name="hand",
        terminals=("a", "b", "m"),
        maxwell=((15.0, -1.0, -4.0),
                 (-1.0, 27.0, -6.0),
                 (-4.0, -6.0, 13.0)),
        junctions=(CellJunction(name="j", between=("a", "b"), L_J=10 * _NH),),
    )
    out = assemble([cell], nodes_force_keep=("m",))
    assert out.nodes == ("a", "b", "m")
    assert out.eliminated == ()
    assert [list(r) for r in out.maxwell] == [[15.0, -1.0, -4.0],
                                             [-1.0, 27.0, -6.0],
                                             [-4.0, -6.0, 13.0]]


def test_ground_node_is_dropped_from_the_node_set():
    """The ground node never becomes a coordinate — its C is already on the diagonal."""
    cell = ExtractedCell(
        name="g",
        terminals=("a", "gnd", "b"),
        maxwell=((15.0, -5.0, -1.0),
                 (-5.0, 40.0, -7.0),
                 (-1.0, -7.0, 27.0)),
        junctions=(CellJunction(name="j", between=("a", "b")),),
    )
    out = assemble([cell], ground_node="gnd")
    assert out.nodes == ("a", "b")
    assert out.eliminated == ()
    assert out.ground_node == "gnd"
    assert [list(r) for r in out.maxwell] == [[15.0, -1.0], [-1.0, 27.0]]


def test_junction_capacitance_is_not_folded_here():
    """``C_j`` must NOT enter the assembled matrix — it is folded by ``circuit_model``.

    The assembled ``maxwell`` is the pure geometric/EM capacitance graph.
    ``CellJunction.C_j`` is only the carrier (sidecar → geo_build → circuit_model),
    which folds it onto the junction-basis diagonal (``cprime[k][k] += C_j``). New LOM
    instead folds it into the node basis (``_cj_dict_to_adj_list``); the two are
    algebraically identical (see the module docstring and the 4.05 identity test
    below), and doing it in exactly one place is what keeps C_j from double-counting.
    """
    base = dict(name="cj", terminals=("a", "b"),
                maxwell=((15.0, -1.0), (-1.0, 27.0)))
    zero = assemble([ExtractedCell(
        junctions=(CellJunction(name="j", between=("a", "b")),), **base)])
    two = assemble([ExtractedCell(
        junctions=(CellJunction(name="j", between=("a", "b"), C_j=2 * _FF),),
        **base)])
    assert [list(r) for r in zero.maxwell] == [[15.0, -1.0], [-1.0, 27.0]]
    assert [list(r) for r in two.maxwell] == [list(r) for r in zero.maxwell]
    # ...but the value is carried through untouched for the downstream consumer
    assert two.junctions[0].C_j == 2 * _FF


# ---------------------------------------------------------------------------
# (2) accumulation: shared names superpose, distinct names stay block-diagonal
# ---------------------------------------------------------------------------

def _two_cells(shared_name_in_b: str) -> list[ExtractedCell]:
    """Cell A = (x, s), cell B = (y, <name>). Same numbers, only the name differs."""
    return [
        ExtractedCell(name="A", terminals=("x", "s"),
                      maxwell=((10.0, -2.0), (-2.0, 20.0)),
                      junctions=(CellJunction(name="ja", between=("x",)),),
                      source="solved"),
        ExtractedCell(name="B", terminals=("y", shared_name_in_b),
                      maxwell=((30.0, -4.0), (-4.0, 40.0)),
                      junctions=(CellJunction(name="jb", between=("y",)),),
                      source="file", sha256="cafe"),
    ]


def test_shared_node_name_superposes_the_two_cells():
    """Same node name in two cells → that node's capacitances **add** (mat[r][c] += w).

    This is the whole cross-cell connectivity mechanism (New LOM ``node_rename``):
    ``s`` is force-kept so nothing is eliminated and the raw accumulated matrix is
    visible. Diagonal of ``s`` = 20 + 40 = 60.
    """
    out = assemble(_two_cells("s"), nodes_force_keep=("s",))
    assert out.nodes == ("x", "s", "y")           # first-appearance order
    assert [list(r) for r in out.maxwell] == [[10.0, -2.0, 0.0],
                                              [-2.0, 60.0, -4.0],
                                              [0.0, -4.0, 30.0]]
    assert out.audit["shared_nodes"] == ["s"]
    assert out.audit["nodes"]["s"] == ["A", "B"]
    assert out.audit["nodes"]["x"] == ["A"]


def test_distinct_node_names_stay_block_diagonal():
    """Rename B's node → NOT shared → block diagonal, and ``s`` keeps its own 20 fF.

    Contrast with the test above: the difference between 60 and 20 on that diagonal
    is the proof that assembly is a superposing capacitance-graph accumulation and
    not a block-diagonal concatenation of per-cell matrices.
    """
    out = assemble(_two_cells("t"), nodes_force_keep=("s", "t"))
    assert out.nodes == ("x", "s", "y", "t")
    assert [list(r) for r in out.maxwell] == [[10.0, -2.0, 0.0, 0.0],
                                              [-2.0, 20.0, 0.0, 0.0],
                                              [0.0, 0.0, 30.0, -4.0],
                                              [0.0, 0.0, -4.0, 40.0]]
    assert out.audit["shared_nodes"] == []
    # x–y stay uncoupled: no shared node → no coupling, the semantics are self-evident
    assert out.maxwell[0][2] == 0.0


# ---------------------------------------------------------------------------
# (3) the 4.05 golden case
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def lom405() -> dict:
    return yaml.safe_load((FIXTURES / "expected.yaml").read_text(encoding="utf-8"))


def _lom405_cells(doc: dict) -> list[ExtractedCell]:
    """Build our ``ExtractedCell``s straight from the fixture's parsed matrices.

    The Maxwell numbers + terminal order come from ``expected.yaml`` (post
    ``node_rename``, so ``coupler_connector_pad_Q{1,2}`` are already both named
    ``coupling`` — that shared name IS the coupling mechanism). Reading the raw Q3D
    txt is P0-C's job; this test deliberately does not re-implement a parser.
    """
    cells = []
    for spec in doc["cells"]:
        (pair, l_j_nh), = spec["ind_dict_nH"].items()
        (_, name), = spec["jj_dict"].items()
        (_, c_j_ff), = spec["cj_dict_fF"].items()
        cells.append(ExtractedCell(
            name=spec["name"],
            terminals=tuple(spec["terminals"]),
            maxwell=tuple(tuple(row) for row in spec["maxwell_fF"]),
            junctions=(CellJunction(name=name, between=tuple(pair.split("|")),
                                    L_J=l_j_nh * _NH, C_j=c_j_ff * _FF),),
            source="file",
            sha256=f"sha-of-{spec['file']}",
        ))
    return cells


def _lom405_assembled(doc: dict) -> AssembledSystem:
    return assemble(_lom405_cells(doc),
                    ground_node=doc["assemble"]["grd_node"],
                    nodes_force_keep=tuple(doc["assemble"]["nodes_force_keep"]))


# The four junction-flux / readout coordinates, in the order the JunctionInput list
# below puts them (circuit_model lays out theta columns first, then the sigmas).
_COORDS = ("j1", "j2", "readout_alice", "readout_bob")


def _lom405_qubits(c_j: float = 0.0) -> list[cm.JunctionInput]:
    """The 4.05 subsystems as ``JunctionInput``s (``c_j`` in farad, on the transmons).

    The two transmons are floating/differential (junction across the two pads) →
    ``islands=(pad_top, pad_bot)`` and theta = phi_top − phi_bot, which is *exactly*
    the reference's junction-flux coordinate ``j1``/``j2``.

    The two readout nodes are entered as single-island placeholders with a dummy
    ``L_J``. They are NOT qubits — the point is only that ``solve_circuit_model``
    treats every *unreferenced* terminal as a grounded electrode, and these two are
    ``nodes_force_keep`` precisely because they must stay dynamic (their inductor is
    the un-simulated resonator). Listing them keeps them in the matrix that gets
    inverted; only their own E_C/f01 are meaningless. P0-D replaces them with real
    ``TL_RESONATOR`` subsystems.
    """
    return [
        cm.JunctionInput(name="j1", islands=("pad_top_Q1", "pad_bot_Q1"),
                         L_J=10 * _NH, C_j=c_j),
        cm.JunctionInput(name="j2", islands=("pad_top_Q2", "pad_bot_Q2"),
                         L_J=12 * _NH, C_j=c_j),
        cm.JunctionInput(name="readout_alice", islands=("readout_alice",),
                         L_J=0.05 * _NH),
        cm.JunctionInput(name="readout_bob", islands=("readout_bob",),
                         L_J=0.05 * _NH),
    ]


def _junction_basis_c_k(assembled: AssembledSystem) -> list[list[float]]:
    """Our reduced node-basis matrix → the reference's ``C_k`` (fF), all 4 coordinates.

    WHY the two are comparable (this is the crux of the golden comparison):

    ``assemble()`` does the Schur elimination in the **node** basis (locked decision:
    no ``S_n`` mechanism here); the junction-basis change ``C' = BᵀC_S B`` plus the
    full inverse is ``circuit_model``'s job. The reference instead changes basis
    first (``C = S_nᵀ C_n S_n``) and then Schur-eliminates everything in the kernel of
    ``L_inv`` — which in the node-junction basis is ``coupling`` **plus one common-mode
    coordinate per junction pair** (``pad_bot_Q1``, ``pad_bot_Q2``).

    The two orders commute: ``S_n`` is the identity on ``coupling`` (block-diagonal
    w.r.t. the keep/remove split), and taking the θθ block of the *full* inverse IS
    the Schur complement of the common modes — see the ``circuit_model`` module
    docstring. Concretely, ``[C⁻¹]`` at coordinate ``j1`` is
    ``(e_top − e_bot)ᵀ C⁻¹ (e_top − e_bot)`` in **either** basis, because the linear
    functional defining ``j1`` is the same one; likewise ``readout_*`` are identity
    coordinates in both. So the 4x4 block of ``[C'⁻¹]`` over
    ``(j1, j2, readout_alice, readout_bob)`` is basis-choice independent, and
    inverting it reproduces the reference's eq-7b ``C_k`` exactly.

    Uses ``circuit_model``'s own ``_congruence``/``_invert_matrix`` (read-only) so the
    comparison runs through the same arithmetic the production path uses.
    """
    nodes = list(assembled.nodes)
    qubits = _lom405_qubits()
    # circuit_model's own sub-matrix ordering: island order of the qubit list
    idx = [nodes.index(island) for q in qubits for island in q.islands]
    sub = [[assembled.maxwell[a][b] for b in idx] for a in idx]

    n_theta = len(qubits)
    n_cols = n_theta + sum(1 for q in qubits if len(q.islands) == 2)
    b_mat = [[0.0] * n_cols for _ in idx]
    row, sigma_col = 0, n_theta
    for k, q in enumerate(qubits):
        if len(q.islands) == 1:
            b_mat[row][k] = 1.0
            row += 1
        else:
            b_mat[row][k] = 0.5
            b_mat[row][sigma_col] = 1.0
            b_mat[row + 1][k] = -0.5
            b_mat[row + 1][sigma_col] = 1.0
            row += 2
            sigma_col += 1

    c_inv = cm._invert_matrix(cm._congruence(sub, b_mat))      # per fF, 6x6
    n = len(_COORDS)
    return cm._invert_matrix([[c_inv[i][j] for j in range(n)] for i in range(n)])


def test_lom405_accumulation_is_bit_exact(lom405):
    """Step 2 alone: our accumulated node-basis matrix == the reference's ``C_n``.

    Force-keeping every node switches the elimination off, so this compares the pure
    accumulation against qiskit-metal's ``CircuitGraph.C_n``. Compared against the
    ``reference_no_cj`` run because C_j is not this layer's business.
    Measured: bit-exact (max relative deviation 0.0) — same additions, same order.

    Note the shared node: ``coupling``'s diagonal is 123.71405 = 59.19879 (cell qb1) +
    64.51526 (cell qb2) — the two independently extracted matrices superposing there.
    """
    ref = lom405["reference_no_cj"]
    basis = ref["orig_node_basis"]
    out = assemble(_lom405_cells(lom405),
                   ground_node=lom405["assemble"]["grd_node"],
                   nodes_force_keep=tuple(basis))
    assert set(out.nodes) == set(basis)
    assert out.eliminated == ()
    ours = {n: i for i, n in enumerate(out.nodes)}
    for i, ni in enumerate(basis):
        for j, nj in enumerate(basis):
            assert out.maxwell[ours[ni]][ours[nj]] == pytest.approx(
                ref["C_n_fF"][i][j], rel=1e-15, abs=1e-15), f"C_n[{ni}][{nj}]"
    assert out.maxwell[ours["coupling"]][ours["coupling"]] == pytest.approx(
        59.19879 + 64.51526, rel=1e-15)


def test_lom405_c_k_matches_reference(lom405):
    """§7 P0-B acceptance: our ``C_k`` vs qiskit-metal's eq-7b ``C_k`` — needs < 0.1 %.

    Against the ``reference_no_cj`` run: the assembly layer never touches ``C_j``, so
    the honest comparison is the same reference case with ``cj_dict`` dropped.
    Measured worst-case relative deviation: **7.7e-16** (machine epsilon), i.e. the
    two paths are the same arithmetic.
    """
    assembled = _lom405_assembled(lom405)
    ours = _junction_basis_c_k(assembled)
    keep = lom405["reference_no_cj"]["nodes_keep"]
    ref_c_k = lom405["reference_no_cj"]["C_k_fF"]

    worst = 0.0
    for i, ni in enumerate(_COORDS):
        for j, nj in enumerate(_COORDS):
            ref = ref_c_k[keep.index(ni)][keep.index(nj)]
            worst = max(worst, abs(ours[i][j] - ref) / abs(ref))
            assert ours[i][j] == pytest.approx(ref, rel=1e-9), f"C_k[{ni}][{nj}]"
    assert worst < 1e-3          # the spec's 0.1 % band; actually ~8e-16


def test_lom405_cj_folding_is_a_pure_junction_diagonal_shift(lom405):
    """The two C_j conventions are algebraically identical — the reference proves it.

    ``expected.yaml`` holds the same 4.05 case twice, with and without
    ``cj_dict={(pad_top, pad_bot): 2}``. New LOM folds it into the **node** basis
    (+2 on both pad diagonals, −2 off-diagonal: 92.99428 → 94.99428 and −30.61038 →
    −32.61038 for Q1). After ``S_n`` that lands as **exactly +C_j on the junction
    coordinate's diagonal and nothing else** — which is what ``circuit_model`` does
    directly (``cprime[k][k] += C_j``). Asserted here on the reference's own two runs,
    so it is not our arithmetic vouching for itself.
    """
    with_cj = lom405["reference"]
    no_cj = lom405["reference_no_cj"]
    assert with_cj["nodes_keep"] == no_cj["nodes_keep"] == list(_COORDS)
    for i, ni in enumerate(_COORDS):
        for j, nj in enumerate(_COORDS):
            shift = 2.0 if (i == j and ni in ("j1", "j2")) else 0.0
            assert with_cj["C_k_fF"][i][j] == pytest.approx(
                no_cj["C_k_fF"][i][j] + shift, rel=1e-12, abs=1e-12), f"{ni}/{nj}"
    # and the node-basis fold the reference actually performed, for the record
    basis = with_cj["orig_node_basis"]
    top, bot = basis.index("pad_top_Q1"), basis.index("pad_bot_Q1")
    assert with_cj["C_n_fF"][top][top] == pytest.approx(94.99428)
    assert no_cj["C_n_fF"][top][top] == pytest.approx(92.99428)
    assert with_cj["C_n_fF"][top][bot] == pytest.approx(-32.61038)
    assert no_cj["C_n_fF"][top][bot] == pytest.approx(-30.61038)


def test_lom405_charging_energy_matches_reference(lom405):
    """End-to-end: ``assemble()`` (no C_j) → ``as_capacitance_result()`` →
    ``solve_circuit_model(..., C_j=2 fF)`` vs the reference run **with** ``cj_dict``.

    This is the whole P0-B chain plus the C_j hand-off, and it is what makes the two
    C_j conventions verifiable rather than merely asserted: our C_j never touches the
    assembled matrix, the reference's does, and the derived ``C_sigma`` / ``E_C`` still
    agree. Measured deviation **7.6e-9** — that is the CODATA-2014 (qiskit-metal) vs
    exact SI-2019 (quantum_dsl) constant sets, nothing else. ``E_J`` differs by 8.1e-4
    for the same reason (metal's phi0 is the rounded 2.067e-15/2pi, ours is the
    derived hbar/2e).

    ``C_sigma_geometric_fF`` (= C_sigma − C_j) is checked against the cj-free
    reference, closing the loop from the other side.
    """
    assembled = _lom405_assembled(lom405)
    result = cm.solve_circuit_model(assembled.as_capacitance_result(),
                                    _lom405_qubits(c_j=2 * _FF))
    by_name = {q.name: q for q in result.qubits}
    keep = lom405["reference"]["nodes_keep"]
    ref_inv = lom405["reference"]["C_inv_k_per_fF"]
    ref_inv_no_cj = lom405["reference_no_cj"]["C_inv_k_per_fF"]

    for coord, key in (("j1", "transmon_alice_h_params"),
                       ("j2", "transmon_bob_h_params")):
        qubit = by_name[coord]
        k = keep.index(coord)
        assert qubit.C_sigma_fF == pytest.approx(1.0 / ref_inv[k][k], rel=1e-9)
        assert qubit.C_sigma_geometric_fF == pytest.approx(
            1.0 / ref_inv_no_cj[k][k], rel=1e-9)
        ref = lom405["reference"][key]
        assert qubit.E_C_GHz * 1e3 == pytest.approx(ref["EC"], rel=1e-6)
        assert qubit.E_J_GHz * 1e3 == pytest.approx(ref["EJ"], rel=1e-3)


def test_lom405_nodes_keep_matches_reference(lom405):
    """Empirical check of the *structural* non-dynamic criterion (spec §12 item 2).

    We decide "non-dynamic" structurally — a node in no ``CellJunction.between`` and
    not force-kept — instead of computing the kernel of ``L_inv``. Item-by-item
    against the reference's ``get_nodes_keep()`` / ``get_nodes_remove()``:

      reference removes ['pad_bot_Q1', 'pad_bot_Q2', 'coupling'] in the **node-
      junction** basis; reference keeps ['j1', 'j2', 'readout_alice', 'readout_bob'].

      * the only removed coordinate that is an actual circuit **node** is
        ``coupling`` → == our ``eliminated``. Exact match.
      * ``pad_bot_Q1`` / ``pad_bot_Q2`` are NOT the nodes of those names — in the
        node-junction basis ``S_n`` replaced ``pad_top_Qk`` by the junction flux
        ``jk``, and the pair's surviving label ``pad_bot_Qk`` now denotes the residual
        **common-mode** coordinate. Per the locked decision those are eliminated one
        layer down, by ``circuit_model``'s ``C' = BᵀC_S B`` + full inverse (the
        theta-theta block of the inverse IS their Schur complement). Both ends of
        every junction are therefore correctly kept HERE.
      * the two force-kept, junction-free nodes survive in both.

    The composition of the two layers is what the ``C_k`` test above verifies to
    ~8e-16 — that is the actual proof that the structural criterion is equivalent
    here. NOTE the difference is a basis difference, not a disagreement about which
    physical degrees of freedom survive.
    """
    assembled = _lom405_assembled(lom405)
    ref_keep = lom405["reference"]["nodes_keep"]
    ref_remove = lom405["reference"]["nodes_remove"]
    junction_nodes = {n for j in assembled.junctions for n in j.between}
    junction_names = {j.name for j in assembled.junctions}

    # (a) removals that are genuine node coordinates == our eliminated set
    assert (set(ref_remove) - junction_nodes
            == set(assembled.eliminated) == {"coupling"})
    # (b) the rest are one label per junction pair = the common modes; we keep BOTH
    #     ends of every junction at this layer
    common_modes = set(ref_remove) & junction_nodes
    assert common_modes == {"pad_bot_Q1", "pad_bot_Q2"}
    for junction in assembled.junctions:
        assert len(set(junction.between) & common_modes) == 1
    assert junction_nodes <= set(assembled.nodes)
    # (c) the reference's kept coordinates: junction fluxes + the force-kept nodes
    assert set(ref_keep) - junction_names == set(
        lom405["assemble"]["nodes_force_keep"]) <= set(assembled.nodes)
    # (d) every node we keep is either a junction end or force-kept
    assert set(assembled.nodes) == junction_nodes | set(
        lom405["assemble"]["nodes_force_keep"])


def test_lom405_schur_vs_hard_grounding(lom405):
    """Schur elimination vs hard grounding — closes status.md gap 6 / issue #20.

    Same two cells, two treatments of the floating ``coupling`` island:

      * Schur (correct): ``coupling`` is integrated out; its charge is zero but its
        potential floats, so it **mediates** a qubit–qubit coupling.
      * hard ground (today's behaviour for non-qubit terminals): the row/column is
        simply deleted, i.e. the island is pinned to the ground potential.

    MEASURED on the 4.05 assembly:

        junction-basis C_k[j1][j2]:   Schur −0.766012 fF   vs   hard ground 0.0 fF
        [C⁻¹][j1][j2]:                Schur  1.3747e-4/fF  vs   hard ground 0.0
        g(j1, j2) from solve_circuit_model (C_j = 2 fF, i.e. the real 4.05 device):
                                      Schur  25.14 MHz     vs   hard ground 0.00 MHz
        every other cross-cell g (j1–readout_bob, j2–readout_alice, …) likewise
        25–60 MHz → exactly 0.00 MHz.
        C_Sigma(j1):                  Schur  61.9338 fF    vs   hard ground 62.4888 fF
        C_Sigma(j2):                  Schur  82.6643 fF    vs   hard ground 83.4751 fF

    The coupling ratio is not "a few percent" — it is **the entire coupling**: with the
    direct coupler grounded there is no other galvanic or capacitive path between the
    two cells (they were extracted separately), so grounding it zeroes every
    cross-cell interaction exactly. Hard grounding a floating coupler does not perturb
    the answer, it deletes the physics. Within each cell the damage is subtler and
    therefore worse: C_Sigma is off by only +0.90 % / +0.98 % (E_C low by the same),
    which is exactly the kind of error that ships unnoticed.
    """
    cells = _lom405_cells(lom405)
    schur = _lom405_assembled(lom405)
    ours = _junction_basis_c_k(schur)

    # hard grounding == deleting the row/col of `coupling` from every cell matrix
    grounded_cells = [
        ExtractedCell(
            name=c.name,
            terminals=tuple(t for t in c.terminals if t != "coupling"),
            maxwell=tuple(
                tuple(v for j, v in enumerate(row) if c.terminals[j] != "coupling")
                for i, row in enumerate(c.maxwell) if c.terminals[i] != "coupling"),
            junctions=c.junctions, source=c.source, sha256=c.sha256)
        for c in cells]
    hard = assemble(grounded_cells,
                    ground_node=lom405["assemble"]["grd_node"],
                    nodes_force_keep=tuple(lom405["assemble"]["nodes_force_keep"]))
    assert hard.eliminated == ()          # nothing left to eliminate
    theirs = _junction_basis_c_k(hard)

    assert ours[0][1] == pytest.approx(-0.7660116516, rel=1e-6)
    assert theirs[0][1] == pytest.approx(0.0, abs=1e-12)

    # C_j on the junction diagonal cannot recreate a coupling the graph does not have,
    # and (the identity again) reproduces the same 25.14 MHz as folding it node-side.
    qubits = _lom405_qubits(c_j=2 * _FF)
    g_schur = {(c.qubit_a, c.qubit_b): c.g_MHz for c in cm.solve_circuit_model(
        schur.as_capacitance_result(), qubits).couplings}
    g_hard = {(c.qubit_a, c.qubit_b): c.g_MHz for c in cm.solve_circuit_model(
        hard.as_capacitance_result(), qubits).couplings}
    assert g_schur[("j1", "j2")] == pytest.approx(25.1427, rel=1e-4)
    assert g_hard[("j1", "j2")] == pytest.approx(0.0, abs=1e-9)
    # every cross-cell pair dies, not just the qubit pair
    for pair in (("j1", "j2"), ("j1", "readout_bob"), ("j2", "readout_alice"),
                 ("readout_alice", "readout_bob")):
        assert g_schur[pair] > 20.0
        assert g_hard[pair] == pytest.approx(0.0, abs=1e-9)
    # ...and the in-cell C_Sigma is quietly off by ~1 %
    c_schur = {q.name: q.C_sigma_fF for q in cm.solve_circuit_model(
        schur.as_capacitance_result(), qubits).qubits}
    c_hard = {q.name: q.C_sigma_fF for q in cm.solve_circuit_model(
        hard.as_capacitance_result(), qubits).qubits}
    assert c_hard["j1"] / c_schur["j1"] == pytest.approx(1.0090, rel=1e-3)
    assert c_hard["j2"] / c_schur["j2"] == pytest.approx(1.0098, rel=1e-3)


# ---------------------------------------------------------------------------
# (4) audit + errors
# ---------------------------------------------------------------------------

def test_audit_records_provenance_and_contributors(lom405):
    """Risk R4: the audit must distinguish a live solve from an injected matrix."""
    assembled = _lom405_assembled(lom405)
    audit = assembled.audit
    assert audit["sources"] == {"qb1": "file", "qb2": "file"}
    assert audit["sha256"] == {"qb1": "sha-of-Q1_TwoTransmon_CapMatrix.txt",
                               "qb2": "sha-of-Q2_TwoTransmon_CapMatrix.txt"}
    assert audit["shared_nodes"] == ["coupling"]
    assert audit["nodes"]["coupling"] == ["qb1", "qb2"]
    assert audit["nodes"]["pad_top_Q1"] == ["qb1"]
    assert audit["eliminated"] == list(assembled.eliminated) == ["coupling"]


def test_audit_warns_about_an_unreferenced_shared_node(lom405):
    """Risk R2: a shared node nobody references is the typo signature — warn.

    It fires on 4.05's legitimate ``coupling`` too (a passive direct coupler is
    exactly "shared, no junction, not force-kept"), so the message says so and points
    at both readings: add it to ``nodes_force_keep`` if it should be a degree of
    freedom, or fix the name if the cells are coupled through the wrong node.
    """
    warnings = _lom405_assembled(lom405).audit["warnings"]
    assert len(warnings) == 1
    assert "'coupling'" in warnings[0]
    assert "qb1, qb2" in warnings[0]
    assert "nodes_force_keep" in warnings[0]

    # force-keeping it silences the warning (and keeps the node)
    kept = assemble(_lom405_cells(lom405),
                    ground_node=lom405["assemble"]["grd_node"],
                    nodes_force_keep=("readout_alice", "readout_bob", "coupling"))
    assert kept.audit["warnings"] == []
    assert "coupling" in kept.nodes

    # a private (non-shared) eliminated node is normal — no warning
    quiet = assemble([ExtractedCell(
        name="A", terminals=("a", "b", "m"),
        maxwell=((15.0, -1.0, -4.0), (-1.0, 27.0, -6.0), (-4.0, -6.0, 13.0)),
        junctions=(CellJunction(name="j", between=("a", "b")),))])
    assert quiet.audit["warnings"] == []


def _one_cell(**over) -> ExtractedCell:
    spec = dict(name="A", terminals=("a", "b"),
                maxwell=((15.0, -1.0), (-1.0, 27.0)),
                junctions=(CellJunction(name="j", between=("a", "b")),))
    spec.update(over)
    return ExtractedCell(**spec)


def test_error_paths():
    with pytest.raises(DesignDslError, match="needs >=1 ExtractedCell"):
        assemble([])
    with pytest.raises(DesignDslError, match="duplicate cell name"):
        assemble([_one_cell(), _one_cell(terminals=("c", "d"),
                                         junctions=(CellJunction(
                                             name="k", between=("c", "d")),))])
    with pytest.raises(DesignDslError, match="square and match its 2 terminals"):
        assemble([_one_cell(maxwell=((15.0, -1.0, 0.0), (-1.0, 27.0, 0.0)))])
    with pytest.raises(DesignDslError, match="square and match its 3 terminals"):
        assemble([_one_cell(terminals=("a", "b", "c"))])
    with pytest.raises(DesignDslError, match="not finite"):
        assemble([_one_cell(maxwell=((15.0, float("nan")),
                                     (float("nan"), 27.0)))])
    with pytest.raises(DesignDslError, match="terminals must be non-empty"):
        assemble([_one_cell(terminals=(), maxwell=())])

    with pytest.raises(DesignDslError, match="between node 'zz' is not an assembled"):
        assemble([_one_cell(junctions=(CellJunction(name="j",
                                                    between=("a", "zz")),))])
    with pytest.raises(DesignDslError, match="between must name 1 node"):
        assemble([_one_cell(junctions=(CellJunction(
            name="j", between=("a", "b", "a")),))])
    with pytest.raises(DesignDslError, match="same node twice"):
        assemble([_one_cell(junctions=(CellJunction(name="j",
                                                    between=("a", "a")),))])
    with pytest.raises(DesignDslError, match="C_j must be a finite"):
        assemble([_one_cell(junctions=(CellJunction(name="j", between=("a", "b"),
                                                    C_j=-1e-15),))])
    with pytest.raises(DesignDslError, match="both ends are the ground node"):
        assemble([_one_cell(junctions=(CellJunction(name="j", between=("g",)),))],
                 ground_node="g")

    with pytest.raises(DesignDslError, match="nodes_force_keep node 'zz'"):
        assemble([_one_cell()], nodes_force_keep=("zz",))
    with pytest.raises(DesignDslError, match="it is the ground node"):
        assemble([_one_cell(terminals=("a", "g"),
                            junctions=(CellJunction(name="j", between=("a",)),))],
                 ground_node="g", nodes_force_keep=("g",))

    with pytest.raises(DesignDslError, match="no dynamic node left"):
        assemble([_one_cell(junctions=())])
    with pytest.raises(DesignDslError, match="every terminal is the ground node"):
        assemble([_one_cell(terminals=("g", "g"))], ground_node="g")


def test_singular_elimination_submatrix_names_the_nodes():
    """A zero-capacitance node to eliminate → ``C_rr`` singular, named in the error."""
    cell = ExtractedCell(
        name="A", terminals=("a", "b", "ghost"),
        maxwell=((15.0, -1.0, 0.0), (-1.0, 27.0, 0.0), (0.0, 0.0, 0.0)),
        junctions=(CellJunction(name="j", between=("a", "b")),))
    with pytest.raises(DesignDslError, match="ghost"):
        assemble([cell])
