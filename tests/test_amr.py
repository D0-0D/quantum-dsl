# -*- coding: utf-8 -*-
"""Palace AMR 透传 (meta ``solver.amr`` → ``Model.Refinement``)。

config 级单测不需要 gmsh / Palace (假 mesh); live 用例 ``QDSL_RUN_PALACE=1`` 开闸。"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import LIVE_MAXWELL_GOLDEN, TWO_PADS_META, live

_MESH = SimpleNamespace(path=Path("chip.msh"), labels=("A", "B"),
                        boundary_groups={"outer": 1}, domain_groups={"substrate": 2, "vacuum": 3},
                        conductor_groups={"A": 4, "B": 5})


def _cfg(tmp_path, **solver):
    from quantum_dsl import load_meta, palace_config
    m = load_meta(TWO_PADS_META)
    out = tmp_path / "chip.json"
    return palace_config(_MESH, replace(m, solver={**m.solver, **solver}), out), out.read_bytes()


def test_amr_off_leaves_config_unchanged(tmp_path):
    """不写 amr = 不出 Refinement 键 (config 与加 AMR 前逐字节相同, 2026-10-29 对 HEAD 实测)。"""
    cfg, raw = _cfg(tmp_path)
    assert list(cfg["Model"]) == ["L0", "Mesh"]
    assert b"Refinement" not in raw


def test_amr_keys_map_to_refinement(tmp_path):
    cfg, _ = _cfg(tmp_path, amr={"max_its": 2, "tol": "1e-3", "max_size": "2e6",
                                 "update_fraction": 0.5, "nonconformal": False})
    assert cfg["Model"]["Refinement"] == {"MaxIts": 2, "Tol": 1e-3, "MaxSize": 2_000_000,
                                          "UpdateFraction": 0.5, "Nonconformal": False}
    assert cfg["Model"]["L0"] == 1e-6
    cfg, _ = _cfg(tmp_path, amr={"max_its": 1})                # 只透传写了的键
    assert cfg["Model"]["Refinement"] == {"MaxIts": 1}


@pytest.mark.parametrize("solver", [
    {"amr": {"max_it": 2}},                       # 子键拼错
    {"amr": {"tol": 1e-3}},                       # 缺 max_its
    {"amr": {"max_its": 2, "save_adapt_mesh": True}},   # 刻意不透传 (#887)
    {"amr": {"max_its": -1}}, {"amr": {"max_its": 1.5}}, {"amr": {"max_its": True}},
    {"amr": {"max_its": 1, "update_fraction": 1.0}}, {"amr": {"max_its": 1, "tol": 0}},
    {"amr": {"max_its": 1, "nonconformal": "no"}}, {"amr": 2},
    {"amrr": {"max_its": 2}},                     # solver 段拼错不再静默忽略
])
def test_amr_typos_raise(tmp_path, solver):
    from quantum_dsl import QuantumDslError
    with pytest.raises(QuantumDslError):
        _cfg(tmp_path, **solver)


@live
def test_two_pads_amr_live(tmp_path):
    """零厚度 imprint + 内部边界 Terminal 下 AMR 可解。Palace 0.16 输出布局 (2026-10-29 实测):
    ``postpro/iterationK`` = 第 K 次求解 (K = 1 是基础网格), 顶层 = 最后一次求解 —— build 读顶层即
    AMR 终值, parse_capacitance 不用改。基础轮 = golden 配方; 一轮 AMR 后自电容下移 (边缘加密)。"""
    from quantum_dsl import build, load_meta, parse_capacitance
    m = load_meta(TWO_PADS_META)
    r = build(replace(m, solver={**m.solver, "amr": {"max_its": 1}}), tmp_path, solve=True)
    base = parse_capacitance(tmp_path / "postpro" / "iteration1", labels=("A", "B")).maxwell_fF
    c = r["capacitance"].maxwell_fF
    for i in range(2):
        for j in range(2):
            assert base[i][j] == pytest.approx(LIVE_MAXWELL_GOLDEN[i][j], rel=0.02)
            assert c[i][j] == pytest.approx(LIVE_MAXWELL_GOLDEN[i][j], rel=0.02)
    assert c[0][0] < base[0][0] and c[1][1] < base[1][1]
