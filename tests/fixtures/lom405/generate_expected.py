# -*- coding: utf-8 -*-
"""Reproduce qiskit-metal tutorial 4.05 (New LOM, two coupled transmons) and
dump every input + reference output needed as a golden fixture for
quantum_dsl's P0-B assembly layer.

Run (from anywhere):
    conda run -n quantum-metal python tests/fixtures/lom405/generate_expected.py

Writes ``expected.yaml`` next to this script. Only needed if the upstream tutorial
changes — see SOURCE.md. NOT a test: it needs the reference env `quantum-metal`
(quantum-metal 0.7.6 + scqubits), which the suite never runs in.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import yaml

import qiskit_metal
from qiskit_metal.analyses.quantization.lom_core_analysis import (
    Cell, CompositeSystem, Subsystem)
from qiskit_metal.analyses.quantization.lumped_capacitive import (
    load_q3d_capacitance_matrix)

TUT = (Path.home() / "metal/qiskit-metal/tutorials/4 Analysis"
       / "A. Core - EM and quantization")
OUT = Path(__file__).resolve().parent / "expected.yaml"

c_light = 299792458.0


def _fl(x):
    """np scalar/array -> plain python float/list (so yaml stays clean)."""
    if isinstance(x, np.ndarray):
        return [_fl(v) for v in x]
    if isinstance(x, (list, tuple)):
        return [_fl(v) for v in x]
    return float(x)


path1 = TUT / "Q1_TwoTransmon_CapMatrix.txt"
path2 = TUT / "Q2_TwoTransmon_CapMatrix.txt"
ta_mat, _, _, _ = load_q3d_capacitance_matrix(str(path1))
tb_mat, _, _, _ = load_q3d_capacitance_matrix(str(path2))

opt1 = dict(
    node_rename={
        "coupler_connector_pad_Q1": "coupling",
        "readout_connector_pad_Q1": "readout_alice",
    },
    cap_mat=ta_mat,
    ind_dict={("pad_top_Q1", "pad_bot_Q1"): 10},     # nH
    jj_dict={("pad_top_Q1", "pad_bot_Q1"): "j1"},
    cj_dict={("pad_top_Q1", "pad_bot_Q1"): 2},       # fF
)
cell_1 = Cell(opt1)

opt2 = dict(
    node_rename={
        "coupler_connector_pad_Q2": "coupling",
        "readout_connector_pad_Q2": "readout_bob",
    },
    cap_mat=tb_mat,
    ind_dict={("pad_top_Q2", "pad_bot_Q2"): 12},     # nH
    jj_dict={("pad_top_Q2", "pad_bot_Q2"): "j2"},
    cj_dict={("pad_top_Q2", "pad_bot_Q2"): 2},       # fF
)
cell_2 = Cell(opt2)

transmon_alice = Subsystem(name="transmon_alice", sys_type="TRANSMON",
                           nodes=["j1"])
transmon_bob = Subsystem(name="transmon_bob", sys_type="TRANSMON",
                         nodes=["j2"])
res_alice = Subsystem(name="readout_alice", sys_type="TL_RESONATOR",
                      nodes=["readout_alice"],
                      q_opts=dict(f_res=8, Z0=50, vp=0.404314 * c_light))
res_bob = Subsystem(name="readout_bob", sys_type="TL_RESONATOR",
                    nodes=["readout_bob"],
                    q_opts=dict(f_res=7.6, Z0=50, vp=0.404314 * c_light))

composite_sys = CompositeSystem(
    subsystems=[transmon_alice, transmon_bob, res_alice, res_bob],
    cells=[cell_1, cell_2],
    grd_node="ground_main_plane",
    nodes_force_keep=["readout_alice", "readout_bob"],
)

cg = composite_sys.circuitGraph()
print(cg)

hilbertspace = composite_sys.create_hilbertspace()
hilbertspace = composite_sys.add_interaction()
ham = composite_sys.hamiltonian_results(hilbertspace, evals_count=30)

gs = composite_sys.compute_gs()

# --- second reference run, cj_dict DROPPED ---------------------------------
# quantum_dsl folds C_j on the junction-basis diagonal inside circuit_model
# (cprime[k][k] += C_j), not into the node-basis capacitance graph the way New LOM's
# cj_dict does. The two are algebraically identical, but it means the ASSEMBLY layer's
# own output must be compared against a cj-free reference. This run provides it; the
# with-cj numbers above then validate the C_j identity end-to-end.
opt1_nocj = {k: v for k, v in opt1.items() if k != "cj_dict"}
opt2_nocj = {k: v for k, v in opt2.items() if k != "cj_dict"}
composite_nocj = CompositeSystem(
    subsystems=[Subsystem(name="transmon_alice", sys_type="TRANSMON", nodes=["j1"]),
                Subsystem(name="transmon_bob", sys_type="TRANSMON", nodes=["j2"]),
                Subsystem(name="readout_alice", sys_type="TL_RESONATOR",
                          nodes=["readout_alice"],
                          q_opts=dict(f_res=8, Z0=50, vp=0.404314 * c_light)),
                Subsystem(name="readout_bob", sys_type="TL_RESONATOR",
                          nodes=["readout_bob"],
                          q_opts=dict(f_res=7.6, Z0=50, vp=0.404314 * c_light))],
    cells=[Cell(opt1_nocj), Cell(opt2_nocj)],
    grd_node="ground_main_plane",
    nodes_force_keep=["readout_alice", "readout_bob"],
)
cg_nocj = composite_nocj.circuitGraph()
print(cg_nocj)

doc = {
    "provenance": {
        "generated_by": str(Path(__file__).resolve()),
        "qiskit_metal_version": qiskit_metal.__version__,
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "tutorial": ("tutorials/4 Analysis/A. Core - EM and quantization/"
                     "4.05 New LOM and Two Coupled Transmon Example.ipynb"),
        "note": ("Reference values produced by qiskit-metal / quantum-metal "
                 "(Apache-2.0, (C) IBM). Constants there are CODATA-2014 "
                 "(e=1.60217657e-19, h=6.62606957e-34); quantum_dsl uses exact "
                 "SI-2019 -> ~2e-7 relative offset on E_C, far below the 0.1% "
                 "acceptance band."),
    },
    # --- inputs, already parsed (so our test needs no Q3D txt parser) ---
    "cells": [
        {
            "name": "qb1",
            "file": path1.name,
            "raw_terminals": [str(n) for n in ta_mat.columns.values],
            "node_rename": dict(opt1["node_rename"]),
            "terminals": [str(n) for n in cell_1.cap_mat.columns.values],
            "maxwell_fF": _fl(cell_1.cap_mat.values),
            "ind_dict_nH": {"|".join(k): v for k, v in opt1["ind_dict"].items()},
            "jj_dict": {"|".join(k): v for k, v in opt1["jj_dict"].items()},
            "cj_dict_fF": {"|".join(k): v for k, v in opt1["cj_dict"].items()},
        },
        {
            "name": "qb2",
            "file": path2.name,
            "raw_terminals": [str(n) for n in tb_mat.columns.values],
            "node_rename": dict(opt2["node_rename"]),
            "terminals": [str(n) for n in cell_2.cap_mat.columns.values],
            "maxwell_fF": _fl(cell_2.cap_mat.values),
            "ind_dict_nH": {"|".join(k): v for k, v in opt2["ind_dict"].items()},
            "jj_dict": {"|".join(k): v for k, v in opt2["jj_dict"].items()},
            "cj_dict_fF": {"|".join(k): v for k, v in opt2["cj_dict"].items()},
        },
    ],
    "assemble": {
        "grd_node": "ground_main_plane",
        "nodes_force_keep": ["readout_alice", "readout_bob"],
    },
    # --- reference outputs ---
    "reference": {
        "orig_node_basis": [str(n) for n in cg.orig_node_basis],
        "node_jj_basis": [str(n) for n in cg.node_jj_basis],
        "nodes_keep": [str(n) for n in cg.get_nodes_keep()],
        "nodes_remove": [str(n) for n in cg.get_nodes_remove()],
        # C_n = accumulated Maxwell matrix in the node basis (ground removed),
        # cj_dict already folded in.  Order = orig_node_basis.
        "C_n_fF": _fl(np.asarray(cg.C_n)),
        # C = S_n^T C_n S_n, node-junction basis.  Order = node_jj_basis.
        "C_fF": _fl(np.asarray(cg.C)),
        # eq 7b Schur complement, order = nodes_keep
        "C_k_fF": _fl(np.asarray(cg.C_k)),
        "C_inv_k_per_fF": _fl(np.asarray(cg.C_inv_k)),
        "L_inv_k_per_nH": _fl(np.asarray(cg.L_inv_k)),
        "transmon_alice_h_params": {
            k: _fl(v) for k, v in transmon_alice.h_params["j1"].items()
            if k in ("EJ", "EC")},
        "transmon_bob_h_params": {
            k: _fl(v) for k, v in transmon_bob.h_params["j2"].items()
            if k in ("EJ", "EC")},
        "fQ_in_GHz": {k: _fl(v) for k, v in ham["fQ_in_Ghz"].items()},
        "chi_in_MHz": {
            "names": list(composite_sys.names),
            "matrix": _fl(np.asarray(ham["chi_in_MHz"])),
        },
        "gs_in_MHz": {"nodes": [str(n) for n in cg.get_nodes_keep()],
                      "matrix": _fl(np.asarray(gs))},
    },
    # same case with cj_dict dropped -- this is what the assembly layer alone
    # (which never touches C_j) must reproduce.
    "reference_no_cj": {
        "orig_node_basis": [str(n) for n in cg_nocj.orig_node_basis],
        "node_jj_basis": [str(n) for n in cg_nocj.node_jj_basis],
        "nodes_keep": [str(n) for n in cg_nocj.get_nodes_keep()],
        "nodes_remove": [str(n) for n in cg_nocj.get_nodes_remove()],
        "C_n_fF": _fl(np.asarray(cg_nocj.C_n)),
        "C_k_fF": _fl(np.asarray(cg_nocj.C_k)),
        "C_inv_k_per_fF": _fl(np.asarray(cg_nocj.C_inv_k)),
    },
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(yaml.safe_dump(doc, sort_keys=False, default_flow_style=None,
                              allow_unicode=True), encoding="utf-8")
print("wrote", OUT)
