# -*- coding: utf-8 -*-
"""``geo_build`` 的分块编排 (M8 / P0): extract.blocks → assemble → circuit_model。

这些测试钉的是 **编排层的接线**, 不是各组件的物理 —— 后者各有自己的文件
(``test_assemble.py`` 对 4.05 的 golden、``test_circuit_model_subsystems.py`` 的 χ
交叉验算、``test_geo_block.py`` 的块几何、``test_cap_from_source.py`` 的矩阵注入)。
这里管的是「作者在 sidecar 里写的名字，能不能一路正确落到求解器上」。

⚠ 全部用 ``from: inline`` 的块 → **不需要 Palace / 不需要网格**, 只需要 gmsh 读一次
源 ``.geo`` 走 GDS 分支。所以这是 spec §4 P0-C 说的「零成本回归」: 拼装 + 电路模型的
接线可以在没有 FEM 的情况下完整回归。
"""

from __future__ import annotations

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("gmsh")
pytest.importorskip("gdstk")

from quantum_dsl.dsl.errors import DesignDslError            # noqa: E402
from quantum_dsl.dsl.geo_build import build_geo              # noqa: E402


# 两个 cell 的 Maxwell 矩阵 (fF, +对角 −非对角, 对角占优 → 正定)。
# cell A 的 terminal 序: A_top, A_bot, A_cpl, A_ro
_CELL_A = [
    [90.0, -30.0, -6.0, -4.0],
    [-30.0, 88.0, -5.0, -3.0],
    [-6.0, -5.0, 40.0, -2.0],
    [-4.0, -3.0, -2.0, 35.0],
]
# cell B 的 terminal 序: B_top, B_bot, B_cpl
_CELL_B = [
    [95.0, -32.0, -7.0],
    [-32.0, 92.0, -6.0],
    [-7.0, -6.0, 45.0],
]


def _sidecar(tmp_path, *, nodes_a=None, nodes_b=None, force_keep=None,
             subsystems=None, geo="two_pads.geo"):
    """写一份全 inline 的 sidecar; 默认 A/B 两 cell 共享 ``coupling`` 节点。

    共享节点名是 New LOM 唯一的跨 cell 连通机制 —— ``A_cpl`` 与 ``B_cpl`` 都被
    rename 成 ``coupling``, 于是两块的电容图在那个节点上叠加 (40+45 = 85 fF)。
    ``coupling`` 没有结支路 → 被 Schur 消掉 (而不是接地)。
    """
    doc = {
        "schema": "qiskit-metal/design-dsl/3",
        "geo": geo,
        "extract": {"blocks": [
            {"name": "cellA", "from": "inline",
             "matrix": {"terminals": ["A_top", "A_bot", "A_cpl", "A_ro"],
                        "maxwell": _CELL_A},
             "nodes": nodes_a if nodes_a is not None
             else {"A_cpl": "coupling", "A_ro": "readout_a"},
             "junctions": [{"name": "jA", "between": ["A_top", "A_bot"],
                            "E_J": "12GHz"}]},
            {"name": "cellB", "from": "inline",
             "matrix": {"terminals": ["B_top", "B_bot", "B_cpl"],
                        "maxwell": _CELL_B},
             "nodes": nodes_b if nodes_b is not None else {"B_cpl": "coupling"},
             "junctions": [{"name": "jB", "between": ["B_top", "B_bot"],
                            "E_J": "16GHz"}]},
        ]},
        "assemble": {"nodes_force_keep": (["readout_a"] if force_keep is None
                                          else force_keep)},
        "subsystems": subsystems if subsystems is not None else [
            {"name": "QA", "type": "transmon", "junction": "jA"},
            {"name": "QB", "type": "transmon", "junction": "jB"},
            {"name": "RO", "type": "tl_resonator", "node": "readout_a",
             "f_res": "7GHz"},
        ],
        "simulation": {"gmsh": {
            "layer_stack": {1: {"kind": "metal", "thickness": 2, "z": 0,
                                "material": "pec"},
                            3: {"kind": "dielectric", "thickness": -100, "z": 0,
                                "material": "silicon", "eps_r": 11.45}},
            "airbox": {"top": 120, "bottom": 120, "side_buffer": 80},
            "mesh": {"max_size": 40, "min_size": 4},
            "gds": {"lib_name": "t", "top_cell": "t",
                    "by_role": {"metal": {"layer": 1, "datatype": 0}}},
            "solver": {"type": "Electrostatic", "order": 2, "l0": 1.0},
        }},
    }
    # 源 .geo 只被 GDS 分支消费 (inline 块不碰几何), 所以复用现成的 two_pads.geo。
    src = tmp_path / "chip.meta.yaml"
    src.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    fixtures = __import__("pathlib").Path(__file__).parent / "fixtures"
    for name in {geo, "two_pads.geo"}:
        if (fixtures / name).is_file():
            (tmp_path / name).write_bytes((fixtures / name).read_bytes())
    return src


def _results(tmp_path, out_name="out", **kw):
    meta = _sidecar(tmp_path, **kw)
    res = build_geo(meta_path=meta, out_dir=tmp_path / out_name)
    assert res["results"] is not None, "assembly should have produced results"
    return res, yaml.safe_load(res["results"].read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 正路: 两 cell 共享节点 → 累加 → Schur → transmon + 谐振器
# ---------------------------------------------------------------------------

def test_inline_blocks_assemble_without_any_fem(tmp_path):
    """全 inline → 无网格、无 Palace, 但拼装 + 电路模型 + 结果产物全出。"""
    res, doc = _results(tmp_path)
    assert res["msh"] is None and res["palace_json"] is None   # 分块路径
    assert [b["name"] for b in res["blocks"]] == ["cellA", "cellB"]
    assert all(b["solved"] for b in res["blocks"])
    assert doc["tier"] == 2

    # 保留节点 = 4 个结焊盘 + 被 force_keep 的谐振器接入点; coupling 被消掉。
    groups = [t["group"] for t in doc["capacitance"]["terminals"]]
    assert groups == ["A_top", "A_bot", "readout_a", "B_top", "B_bot"]
    asm = doc["provenance"]["assembly"]
    assert asm["eliminated"] == ["coupling"]
    assert asm["nodes_force_keep"] == ["readout_a"]


def test_shared_node_capacitance_superposes_before_elimination(tmp_path):
    """共享节点处两 cell 的电容**叠加** (40+45=85), 不是块对角拼接。

    直接断在 ``audit`` 上 —— 这是拼装层唯一能证明「跨 cell 真的连通了」的地方,
    也是风险 R2 (共享节点名拼错 → 耦合静默丢失) 的取证面。
    """
    _res, doc = _results(tmp_path)
    audit = doc["provenance"]["assembly"]["audit"]
    assert audit["shared_nodes"] == ["coupling"]
    assert sorted(audit["nodes"]["coupling"]) == ["cellA", "cellB"]

    # coupling 被消掉 → 它中介的耦合出现在 QA↔QB 上 (不共享节点时必然为 0)。
    g = {(c["qubit_a"], c["qubit_b"]): c["g_MHz"]
         for c in doc["hamiltonian"]["couplings"]}
    assert g[("QA", "QB")] > 0.0


def test_no_shared_node_kills_the_cross_cell_coupling(tmp_path):
    """不共享节点名 = 不耦合, 语义自明 (spec §6: 不需要连接件模型)。"""
    _res, doc = _results(
        tmp_path,
        nodes_a={"A_cpl": "cplA", "A_ro": "readout_a"},
        nodes_b={"B_cpl": "cplB"},
        force_keep=["readout_a", "cplA", "cplB"],
        subsystems=[
            {"name": "QA", "type": "transmon", "junction": "jA"},
            {"name": "QB", "type": "transmon", "junction": "jB"},
            {"name": "RO", "type": "tl_resonator", "node": "readout_a",
             "f_res": "7GHz"},
            {"name": "RA", "type": "tl_resonator", "node": "cplA",
             "f_res": "8GHz"},
            {"name": "RB", "type": "tl_resonator", "node": "cplB",
             "f_res": "8GHz"},
        ])
    g = {(c["qubit_a"], c["qubit_b"]): c["g_MHz"]
         for c in doc["hamiltonian"]["couplings"]}
    assert g[("QA", "QB")] == pytest.approx(0.0, abs=1e-12)


def test_resonator_and_chi_reach_the_results_artifact(tmp_path):
    """P0-D 的产物真的被序列化出来 (f_bare/f_loaded 都要有, χ 要带方法标签)。"""
    _res, doc = _results(tmp_path)
    (ro,) = doc["hamiltonian"]["resonators"]
    assert ro["name"] == "RO" and ro["node"] == "readout_a"
    assert ro["f_bare_GHz"] == pytest.approx(7.0)
    # 爪子的实测电容加载谐振器 → 频率必然下降 (spec §4 P0-D 的语义陷阱 R5)。
    assert 0.0 < ro["f_loaded_GHz"] < ro["f_bare_GHz"]
    assert ro["mode"] == "half_wave" and ro["Z0_ohm"] == pytest.approx(50.0)

    chis = doc["hamiltonian"]["resonator_couplings"]
    assert {c["qubit"] for c in chis} == {"QA", "QB"}
    # χ 是 Koch (3.10) 的二阶微扰式, 近共振/强耦合失效 → 必须自报方法 (R6)。
    assert all(c["chi_method"] == "perturbative" for c in chis)
    assert all(c["g_MHz"] > 0.0 for c in chis)


def test_provenance_distinguishes_injected_from_solved(tmp_path):
    """R4: 一份全靠注入矩阵拼出来的结果**不许**自称实解。"""
    _res, doc = _results(tmp_path)
    assert doc["capacitance"]["source"] == "assembled:inline"
    cells = doc["provenance"]["assembly"]["cells"]
    assert [c["source"] for c in cells] == ["inline", "inline"]
    assert [c["junctions"] for c in cells] == [["jA"], ["jB"]]


def test_cpw_block_derives_f_res_analytically(tmp_path):
    """P0-F: 给 ``cpw:`` 而不给 ``f_res`` → 频率从解析 λ_g 反解出来。

    λ/2, 4200 µm 长, 10/6 µm 线宽缝隙, 750 µm 硅衬底 → 目标 λ_g = 8400 µm,
    ε_eff ≈ 6.3 → f ≈ c0/(8400 µm·√6.3) ≈ 14 GHz 量级的一半…… 这里不钉绝对值
    (那是 ``test_cpw_analytic.py`` 的事), 只钉「解出来了、量级合理、并且长度加倍
    频率减半」这个自洽关系。
    """
    def _subs(length):
        return [
            {"name": "QA", "type": "transmon", "junction": "jA"},
            {"name": "QB", "type": "transmon", "junction": "jB"},
            {"name": "RO", "type": "tl_resonator", "node": "readout_a",
             "cpw": {"line_width": 10, "line_gap": 6, "length": length,
                     "substrate_thickness": 750, "film_thickness": 0.2}},
        ]
    _r1, d1 = _results(tmp_path, out_name="o1", subsystems=_subs(4200))
    _r2, d2 = _results(tmp_path, out_name="o2", subsystems=_subs(8400))
    f1 = d1["hamiltonian"]["resonators"][0]["f_bare_GHz"]
    f2 = d2["hamiltonian"]["resonators"][0]["f_bare_GHz"]
    assert 1.0 < f1 < 100.0, f1
    # λ_g ∝ 1/f 且 ε_eff 对 f 只弱依赖 → 长度加倍 ⇒ 频率减半 (到 0.5% 内)。
    assert f2 == pytest.approx(f1 / 2.0, rel=5e-3)


# ---------------------------------------------------------------------------
# 报错路径 —— 每一条都是一个 silent-wrong-result 面
# ---------------------------------------------------------------------------

def test_mistyped_nodes_key_raises(tmp_path):
    """R2: ``nodes:`` 里拼错的键会静默丢掉耦合 → 必须报错, 不许忽略。"""
    meta = _sidecar(tmp_path, nodes_a={"A_cpl_TYPO": "coupling",
                                       "A_ro": "readout_a"})
    with pytest.raises(DesignDslError, match="match no capacitance terminal"):
        build_geo(meta_path=meta, out_dir=tmp_path / "out")


def test_unclaimed_kept_node_raises(tmp_path):
    """#20 的收尾守卫: force-keep 了一个节点却没给它 subsystem。

    那个节点会被 ``solve_circuit_model`` 静默接地, 杀掉它中介的耦合 —— 这正是
    ``status.md`` 缺口 ⑥。所以编排层 raise, 不 warn。
    """
    meta = _sidecar(tmp_path, subsystems=[
        {"name": "QA", "type": "transmon", "junction": "jA"},
        {"name": "QB", "type": "transmon", "junction": "jB"},
    ])   # readout_a 被 force-keep 但没有谐振器认领
    with pytest.raises(DesignDslError, match="SILENTLY GROUNDED"):
        build_geo(meta_path=meta, out_dir=tmp_path / "out")


def test_unknown_junction_in_subsystem_raises(tmp_path):
    meta = _sidecar(tmp_path, subsystems=[
        {"name": "QA", "type": "transmon", "junction": "nope"},
        {"name": "QB", "type": "transmon", "junction": "jB"},
        {"name": "RO", "type": "tl_resonator", "node": "readout_a",
         "f_res": "7GHz"},
    ])
    with pytest.raises(DesignDslError, match="not declared in any extract"):
        build_geo(meta_path=meta, out_dir=tmp_path / "out")


def test_unknown_resonator_node_raises(tmp_path):
    meta = _sidecar(tmp_path, subsystems=[
        {"name": "QA", "type": "transmon", "junction": "jA"},
        {"name": "QB", "type": "transmon", "junction": "jB"},
        {"name": "RO", "type": "tl_resonator", "node": "nowhere",
         "f_res": "7GHz"},
        {"name": "R2", "type": "tl_resonator", "node": "readout_a",
         "f_res": "7GHz"},
    ])
    with pytest.raises(DesignDslError, match="unknown node 'nowhere'"):
        build_geo(meta_path=meta, out_dir=tmp_path / "out")


# ---------------------------------------------------------------------------
# G1/G2: 块几何落盘 + --no-solve 只关求解不碰几何
# ---------------------------------------------------------------------------

def test_no_solve_still_writes_block_geo_and_registers_it(tmp_path):
    """G1: ``block_<name>.geo`` 落盘 + 进 manifest 带 sha256, 即便完全不求解。

    这条是 §7 那个「用 gmsh GUI 逐块目视确认 pocket 保留」验证的前提 —— 块几何必须
    是一份**存在的、可打开的文件**, 而不是运行时的内存视图 (风险 R11)。
    """
    from pathlib import Path
    fixtures = Path(__file__).parent / "fixtures"
    out = tmp_path / "out"
    res = build_geo(meta_path=fixtures / "two_pads_blocks.meta.yaml",
                    out_dir=out, no_solve=True)
    assert res["results"] is None          # 没有矩阵 → 不写系统级结果
    names = {b["name"] for b in res["blocks"]}
    assert names == {"A", "B"}
    for b in res["blocks"]:
        assert Path(b["geo"]).is_file()
        assert b["msh"] is None            # --no-solve: 不划网格
        assert not b["solved"]

    manifest = yaml.safe_load(res["manifest"].read_text(encoding="utf-8"))
    block_geos = {f["name"]: f for f in manifest["files"]
                  if f["role"] == "block-geo"}
    assert set(block_geos) == {"block_A.geo", "block_B.geo"}
    assert all(len(f["sha256"]) == 64 for f in block_geos.values())


def test_block_geo_keeps_the_authored_physical_names(tmp_path):
    """G1 契约: 块几何里的 physical 名与源 ``.geo`` 逐字相同 (下游一行不改)。"""
    from pathlib import Path
    fixtures = Path(__file__).parent / "fixtures"
    res = build_geo(meta_path=fixtures / "two_pads_blocks.meta.yaml",
                    out_dir=tmp_path / "out", no_solve=True)
    by_name = {b["name"]: Path(b["geo"]) for b in res["blocks"]}
    text_a = by_name["A"].read_text(encoding="utf-8")
    assert 'Physical Surface("metal::1::A::pad")' in text_a
    assert "metal::1::B::pad" not in text_a       # S1: 只保留入选 component
