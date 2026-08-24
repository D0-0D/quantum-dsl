# -*- coding: utf-8 -*-
"""quantum_dsl v4 — 可执行需求规格 (契约测试, 见 SPEC.md 的 N0–N14 表)。

每个测试 = 一条待实现需求, 起点全部红 (ModuleNotFoundError)。
全部翻绿 + `QDSL_RUN_PALACE=1` 下 N7 通过 = v4 完成。

数值 golden 的三种来源, 都与实现无关:
  * 闭式可手验 (Schur 3×3、SQUID flux 甜点、λ/4 LC、E_C=e²/2C);
  * 同一物理输入上的实测/参考值 (two_pads C 矩阵 = v4 零厚度片配方 2026-08-24
    实测, 见 .claude/physics-pipeline.md; CPW、χ 沿用 v3 验证过的参考) ——
    这些是**物理**锚点, 不是 API 兼容锚点;
  * Palace 0.16 的 verbatim CSV 输出 (tests/fixtures/palace_postpro/)。
"""
from __future__ import annotations

import hashlib
import math
import os
import sys
from pathlib import Path

import pytest
import yaml

FIXTURES = Path(__file__).parent / "fixtures"
TWO_PADS_META = FIXTURES / "two_pads.meta.yaml"
SUNG_META = FIXTURES / "sung_2021_device.meta.yaml"
BLOCKS_META = FIXTURES / "two_pads_blocks.meta.yaml"

# two_pads 的实测 Maxwell 矩阵 (fF) — N7 的 live golden。
# 配方 = v4 产品路径: 零厚度金属片 imprint 进衬底/真空界面, µm 网格 +
# Model.L0=1e-6, mesh 40/4 µm, order 2, 接地盒 (Palace 0.16, 2026-08-24 实测;
# 见 .claude/physics-pipeline.md §6–§7 与 .claude/proto/two_pads_sheet.py)。
# 历史: v3 的 2 µm 板挖空配方给 [[24.7288,-1.976],[-1.976,24.7293]] —— 板厚
# 工件偏置 ~1%, 不是物理更优 (pipeline §7)。
LIVE_MAXWELL_GOLDEN = [[24.5324, -1.9472], [-1.9472, 24.5353]]
# N8 的纯数学输入 (golden 由它 + 10 nH 闭式导出, 与 Palace 无关, 数值无需跟随
# N7 golden 变动)。
N8_MAXWELL = [[24.73, -1.98], [-1.98, 24.72]]

live = pytest.mark.skipif(
    not os.environ.get("QDSL_RUN_PALACE"),
    reason="live Palace solve — enable with QDSL_RUN_PALACE=1")

# N15 单独闸门: sung 整片 order-2 是重解 (~百万级未知量, 分钟-小时级),
# 不挂在 N7 的快速 live 闸下; V4-6 收尾必须跑通一次 (可在多核真机跑)。
live_sung = pytest.mark.skipif(
    not os.environ.get("QDSL_RUN_PALACE_SUNG"),
    reason="sung paper-validation solve — enable with QDSL_RUN_PALACE_SUNG=1")


# =====================================================================
# N0 — 平台与纯度
# =====================================================================
class TestN0Platform:

    def test_python_313(self):
        assert sys.version_info >= (3, 13)

    def test_import_is_light_and_metal_free(self):
        import quantum_dsl  # noqa: F401
        for banned in ("qiskit_metal", "gmsh", "gdstk", "matplotlib"):
            assert banned not in sys.modules, f"import quantum_dsl pulled {banned}"

    def test_error_type_exported(self):
        from quantum_dsl import QuantumDslError
        assert issubclass(QuantumDslError, Exception)


# =====================================================================
# N1 — 单位 (内部长度单位 µm; 物理量为 SI)
# =====================================================================
class TestN1Units:

    def test_parse_length_to_um(self):
        from quantum_dsl import parse_length
        assert parse_length(5) == 5.0             # 裸数 = µm
        assert parse_length("5um") == 5.0
        assert parse_length("0.5mm") == 500.0
        assert parse_length("250nm") == pytest.approx(0.25)
        assert parse_length("1cm") == 10000.0
        assert parse_length("0.001m") == 1000.0

    def test_parse_length_rejects_junk(self):
        from quantum_dsl import parse_length, QuantumDslError
        for bad in ("abc", "5parsec", "", None, True, [1]):
            with pytest.raises(QuantumDslError):
                parse_length(bad)

    def test_parse_quantity_to_si(self):
        from quantum_dsl import parse_quantity
        assert parse_quantity("10nH") == pytest.approx(1e-8)
        assert parse_quantity("3fF") == pytest.approx(3e-15)
        assert parse_quantity("2GHz") == pytest.approx(2e9)

    def test_parse_quantity_requires_unit(self):
        from quantum_dsl import parse_quantity, QuantumDslError
        with pytest.raises(QuantumDslError):
            parse_quantity("10")  # 裸数没有量纲 — 必须带单位


# =====================================================================
# N2 — .geo 加载 + 四段 Physical 名解析
# =====================================================================
class TestN2LoadGeo:

    def test_two_pads_physicals(self):
        from quantum_dsl import load_geo
        geo = load_geo(FIXTURES / "two_pads.geo")
        names = {p.name for p in geo.physicals}
        assert names == {"metal::1::A::pad", "metal::1::B::pad"}
        pad_a = next(p for p in geo.physicals if p.component == "A")
        assert pad_a.role == "metal"
        assert pad_a.layer == 1
        assert pad_a.primitive == "pad"

    def test_bbox_um(self):
        from quantum_dsl import load_geo
        geo = load_geo(FIXTURES / "two_pads.geo")
        assert geo.bbox_um == pytest.approx((-120.0, -40.0, 120.0, 40.0))

    def test_malformed_physical_name_raises(self, tmp_path):
        from quantum_dsl import load_geo, QuantumDslError
        bad = tmp_path / "bad.geo"
        bad.write_text(
            'SetFactory("OpenCASCADE");\n'
            'r = news; Rectangle(r) = {0, 0, 0, 10, 10};\n'
            'Physical Surface("pad_without_role_segments") = { r };\n',
            encoding="utf-8")
        with pytest.raises(QuantumDslError):
            load_geo(bad)


# =====================================================================
# N3 — meta.yaml 加载 (词汇见 SPEC.md)
# =====================================================================
class TestN3LoadMeta:

    def test_two_pads_meta(self):
        from quantum_dsl import load_meta
        meta = load_meta(TWO_PADS_META)
        assert meta.geo_path == FIXTURES / "two_pads.geo"
        assert meta.materials["substrate"]["eps_r"] == pytest.approx(11.45)
        assert meta.materials["substrate"]["thickness_um"] == pytest.approx(100)
        assert meta.airbox["side_um"] == pytest.approx(80)
        assert meta.mesh["max_size_um"] == pytest.approx(40)
        assert meta.solver["type"] == "electrostatic"
        assert meta.solver["order"] == 2
        assert meta.gds["by_role"]["metal"]["layer"] == 1

    def test_circuit_model_block(self):
        from quantum_dsl import load_meta
        meta = load_meta(TWO_PADS_META)
        qubits = meta.circuit_model["qubits"]
        assert [q["name"] for q in qubits] == ["A", "B"]
        assert qubits[0]["island"] == "A"
        assert qubits[0]["L_J"] == pytest.approx(1e-8)  # "10nH" 已解析为 SI

    def test_unknown_top_level_key_raises(self, tmp_path):
        from quantum_dsl import load_meta, QuantumDslError
        bad = tmp_path / "bad.meta.yaml"
        bad.write_text("schema: quantum-dsl/meta/1\ngeo: x.geo\ntypo_key: 1\n",
                       encoding="utf-8")
        with pytest.raises(QuantumDslError):
            load_meta(bad)

    def test_wrong_schema_raises(self, tmp_path):
        from quantum_dsl import load_meta, QuantumDslError
        bad = tmp_path / "bad.meta.yaml"
        bad.write_text("schema: qiskit-metal/design-dsl/3\ngeo: x.geo\n",
                       encoding="utf-8")
        with pytest.raises(QuantumDslError):
            load_meta(bad)


# =====================================================================
# N4 — GDS 分叉 (µm verbatim, bypasses the mesh)
# =====================================================================
class TestN4Gds:

    def test_two_pads_gds_roundtrip(self, tmp_path):
        from quantum_dsl import build_gds, load_meta
        import gdstk

        out = build_gds(FIXTURES / "two_pads.geo", load_meta(TWO_PADS_META),
                        tmp_path / "chip.gds")
        lib = gdstk.read_gds(str(out))
        assert lib.unit == pytest.approx(1e-6)
        (cell,) = lib.top_level()
        polys = cell.polygons
        assert len(polys) == 2
        assert all(p.layer == 1 and p.datatype == 0 for p in polys)
        # µm verbatim: pad A 的包围盒逐字是 (-120,-40)-(-40,40)
        boxes = sorted(tuple(round(v, 6) for pt in p.bounding_box() for v in pt)
                       for p in polys)
        assert boxes[0] == (-120.0, -40.0, -40.0, 40.0)
        assert boxes[1] == (40.0, -40.0, 120.0, 40.0)


# =====================================================================
# N5 — 静电网格 (零厚度导体片 imprint 为边界面组; 空网格必须 raise)
# =====================================================================
class TestN5Mesh:

    def test_two_pads_mesh(self, tmp_path):
        from quantum_dsl import build_mesh, load_meta
        mesh = build_mesh(FIXTURES / "two_pads.geo", load_meta(TWO_PADS_META),
                          tmp_path / "chip.msh")
        assert mesh.path.exists() and mesh.path.stat().st_size > 1000
        # 导体面组按 component 命名可寻址 (Palace Terminal 的绑定键)
        assert set(mesh.conductor_groups) == {"A", "B"}
        assert mesh.num_cells > 0
        # JJ 不存在于本例; 有 3D 体网格 (真空 + 衬底)
        assert mesh.num_volume_cells > 0


# =====================================================================
# N6 — Palace: config 生成 + 电容 CSV 解析
# =====================================================================
class TestN6Palace:

    def test_config_shape(self, tmp_path):
        from quantum_dsl import build_mesh, palace_config, load_meta
        meta = load_meta(TWO_PADS_META)
        mesh = build_mesh(FIXTURES / "two_pads.geo", meta, tmp_path / "chip.msh")
        cfg = palace_config(mesh, meta, tmp_path / "chip.json")
        assert (tmp_path / "chip.json").exists()
        assert cfg["Problem"]["Type"] == "Electrostatic"
        assert cfg["Solver"]["Order"] == 2
        assert len(cfg["Boundaries"]["Terminal"]) == 2

    def test_parse_capacitance_verbatim_csv(self):
        from quantum_dsl import parse_capacitance
        cap = parse_capacitance(FIXTURES / "palace_postpro", labels=("A", "B"))
        assert cap.labels == ("A", "B")
        m = cap.maxwell_fF
        assert m[0][0] == pytest.approx(135.4305474059)
        assert m[1][1] == pytest.approx(135.4665489642)
        assert m[0][1] == pytest.approx(-33.06523790651)
        assert m[0][1] == m[1][0]                       # 对称
        mu = cap.mutual_fF
        assert mu[0][1] == pytest.approx(+33.06523790651)  # mutual 全正
        # 一致性: Cm[i][i] = C[i][i] + C[i][j]
        assert mu[0][0] == pytest.approx(m[0][0] + m[0][1])

    def test_parse_capacitance_rejects_nan(self, tmp_path):
        from quantum_dsl import parse_capacitance, QuantumDslError
        p = tmp_path / "postpro"
        p.mkdir()
        (p / "terminal-C.csv").write_text(
            " i, C[i][1] (F), C[i][2] (F)\n 1, nan, 0\n 2, 0, 1e-15\n",
            encoding="utf-8")
        with pytest.raises(QuantumDslError):
            parse_capacitance(p, labels=("A", "B"))


# =====================================================================
# N7 — live 端到端 (gated; Palace 0.16 in WSL, ⚠ HWLOC_COMPONENTS=-gl)
# =====================================================================
class TestN7Live:

    @live
    def test_two_pads_capacitance_matrix(self, tmp_path):
        from quantum_dsl import build
        result = build(TWO_PADS_META, tmp_path, solve=True)
        cap = result["capacitance"]
        assert cap.labels == ("A", "B")
        for i in range(2):
            for j in range(2):
                assert cap.maxwell_fF[i][j] == pytest.approx(
                    LIVE_MAXWELL_GOLDEN[i][j], rel=0.02)

    @live
    def test_two_pads_hamiltonian_in_results(self, tmp_path):
        from quantum_dsl import build
        result = build(TWO_PADS_META, tmp_path, solve=True)
        results_file = result["results"]
        doc = yaml.safe_load(Path(results_file).read_text(encoding="utf-8"))
        f01 = [q["f01_GHz"] for q in doc["hamiltonian"]["qubits"]]
        # 由 LIVE_MAXWELL_GOLDEN + 10 nH 闭式导出 (逆电容 LOM)
        assert f01 == pytest.approx([9.3989, 9.3984], rel=0.03)


# =====================================================================
# N8 — 电路模型: 逆电容 LOM (E_C = (e²/2)[C⁻¹]_ii, C_Σ = 1/[C⁻¹]_ii)
# =====================================================================
class TestN8CircuitModel:

    def _two_pads(self):
        from quantum_dsl import solve_circuit_model
        return solve_circuit_model(
            labels=("A", "B"), maxwell_fF=N8_MAXWELL,
            junctions=[{"name": "A", "islands": ["A"], "L_J": 10e-9},
                       {"name": "B", "islands": ["B"], "L_J": 10e-9}])

    def test_single_island_closed_form(self):
        """1×1 时必须精确退化为 e²/2C (闭式验证过的 golden)。"""
        from quantum_dsl import solve_circuit_model
        r = solve_circuit_model(
            labels=("Q",), maxwell_fF=[[135.0]],
            junctions=[{"name": "Q", "islands": ["Q"], "L_J": 10e-9}])
        (q,) = r.qubits
        assert q.C_sigma_fF == pytest.approx(135.0, rel=1e-12)
        assert q.E_C_GHz == pytest.approx(0.14348318018266015, rel=1e-9)
        assert q.E_J_GHz == pytest.approx(16.34615128067812, rel=1e-9)
        assert q.f01_GHz == pytest.approx(4.188165715559985, rel=1e-9)
        assert q.anharmonicity_MHz == pytest.approx(-143.48318018266016, rel=1e-9)
        assert q.EJ_over_EC == pytest.approx(113.92381504137822, rel=1e-9)

    def test_two_pads_inverse_cap_not_raw_diagonal(self):
        """C_Σ = 1/[C⁻¹]_ii — 不是 Maxwell 对角 24.73, 也不是对地 22.75。"""
        a, b = self._two_pads().qubits
        assert a.C_sigma_fF == pytest.approx(24.57140776699029, rel=1e-9)
        assert b.C_sigma_fF == pytest.approx(24.561471896482004, rel=1e-9)
        assert a.E_C_GHz == pytest.approx(0.7883239539364719, rel=1e-9)
        assert a.f01_GHz == pytest.approx(9.364926800074445, rel=1e-9)
        assert a.EJ_over_EC == pytest.approx(20.735322324095453, rel=1e-9)

    def test_floating_two_island_closed_form(self):
        """浮动双岛: 结桥接两岛, 都不接地 (sung/N15 依赖的数学)。

        手算 fixture: 岛 a,b 对地 50/40 fF, 岛间 30 fF
        → Maxwell = [[80,-30],[-30,70]] fF。
        结支路差模的有效电容 (完整求逆取 θθ 块, Yanay et al. npj QI 2020
        Eq. 56 同款闭式): C_eff = C_ab + C_ag·C_bg/(C_ag+C_bg)
                               = 30 + 50·40/90 = 52.2222… fF。
        错误口径参照: 把 b 静默接地 → 1/[C⁻¹]_aa = 67.14 fF (v3 实测这类
        错误在 sung 上放大成 1.70×); "删共模行列再求逆" = A⁻¹, 亦错。
        """
        from quantum_dsl import solve_circuit_model
        r = solve_circuit_model(
            labels=("a", "b"), maxwell_fF=[[80.0, -30.0], [-30.0, 70.0]],
            junctions=[{"name": "Q", "islands": ["a", "b"], "L_J": 10e-9}])
        (q,) = r.qubits
        assert q.C_sigma_fF == pytest.approx(52.22222222222223, rel=1e-9)
        assert q.E_C_GHz == pytest.approx(0.37091928494028104, rel=1e-9)
        assert q.f01_GHz == pytest.approx(6.593621041343882, rel=1e-9)
        assert q.EJ_over_EC == pytest.approx(44.06929470736441, rel=1e-9)

    def test_two_pads_coupling_g(self):
        r = self._two_pads()
        (c,) = r.couplings
        assert {c.qubit_a, c.qubit_b} == {"A", "B"}
        # β 是与磁通/E_J 无关的纯几何耦合度量 (N15 对论文断言的就是它);
        # g = ½·β·√(f01_a·f01_b) — 两条 golden 互为闭式一致性校验
        assert c.beta == pytest.approx(0.08008089142510777, rel=1e-9)
        assert c.g_MHz == pytest.approx(375.0105674523576, rel=1e-6)

    def test_anharmonicity_is_minus_e_c(self):
        (q, _) = self._two_pads().qubits
        assert q.anharmonicity_MHz == pytest.approx(-q.E_C_GHz * 1e3, rel=1e-12)

    def test_squid_flux_tuning_singularity_free(self):
        """非对称 SQUID 用无奇点形式 E_JΣ·√(cos²(πφ)+d²sin²(πφ)):
        φ=0 → E_J1+E_J2;φ=0.5 → |E_J1−E_J2| (教科书 tan 写法在这里发散)。"""
        from quantum_dsl import solve_circuit_model, H_PLANCK
        e1, e2 = 12e9 * H_PLANCK, 8e9 * H_PLANCK

        def f(flux):
            r = solve_circuit_model(
                labels=("Q",), maxwell_fF=[[100.0]],
                junctions=[{"name": "Q", "islands": ["Q"],
                            "squid": {"E_J1": e1, "E_J2": e2, "flux": flux}}])
            return r.qubits[0].E_J_GHz

        assert f(0.0) == pytest.approx(20.0, rel=1e-12)
        assert f(0.5) == pytest.approx(4.0, rel=1e-9)   # 甜点有限, 不是 nan/0

    def test_lj_nan_inf_rejected(self):
        from quantum_dsl import solve_circuit_model, QuantumDslError
        for bad in (float("nan"), float("inf"), 0.0, -1e-9):
            with pytest.raises(QuantumDslError):
                solve_circuit_model(
                    labels=("Q",), maxwell_fF=[[100.0]],
                    junctions=[{"name": "Q", "islands": ["Q"], "L_J": bad}])


# =====================================================================
# N9 — 拼装: 共享节点累加 + Schur 消元 (手算 golden)
# =====================================================================
class TestN9Assemble:

    def test_shared_node_accumulation(self):
        """块 1 (a,s) + 块 2 (s,b) → (a,s,b); 共享节点 s 的对角相加。"""
        from quantum_dsl import assemble
        out = assemble(
            cells=[{"name": "b1", "labels": ("a", "s"),
                    "maxwell_fF": [[5.0, -1.0], [-1.0, 4.0]]},
                   {"name": "b2", "labels": ("s", "b"),
                    "maxwell_fF": [[3.0, -2.0], [-2.0, 6.0]]}],
            keep=("a", "s", "b"))
        assert out.labels == ("a", "s", "b")
        # pytest.approx 不支持嵌套 list (构造期 TypeError) → 逐行比较;
        # golden 数值逐字不动 (2026-08-24 harness 修复)。
        expected = [[5.0, -1.0, 0.0], [-1.0, 7.0, -2.0], [0.0, -2.0, 6.0]]
        for row, exp in zip(out.maxwell_fF, expected, strict=True):
            assert row == pytest.approx(exp)

    def test_schur_elimination(self):
        """消掉未保留节点 g: C' = C_AA − C_AB·C_BB⁻¹·C_BA (手算可验)。"""
        from quantum_dsl import assemble
        out = assemble(
            cells=[{"name": "b1", "labels": ("a", "b", "g"),
                    "maxwell_fF": [[10.0, -2.0, -3.0],
                                   [-2.0, 8.0, -1.0],
                                   [-3.0, -1.0, 12.0]]}],
            keep=("a", "b"))
        assert out.labels == ("a", "b")
        # 同上: 嵌套 approx 不可用 → 逐行; golden 数值逐字不动。
        expected = [[10.0 - 9.0 / 12.0, -2.0 - 3.0 / 12.0],
                    [-2.0 - 3.0 / 12.0, 8.0 - 1.0 / 12.0]]
        for row, exp in zip(out.maxwell_fF, expected, strict=True):
            assert row == pytest.approx(exp)

    def test_unknown_keep_label_raises(self):
        """keep 里写错的名字必须 raise — 拼错 = 静默接地是 v3 踩过的坑。"""
        from quantum_dsl import assemble, QuantumDslError
        with pytest.raises(QuantumDslError):
            assemble(cells=[{"name": "b1", "labels": ("a",),
                             "maxwell_fF": [[5.0]]}],
                     keep=("a", "typo"))


# =====================================================================
# N10 — CPW 解析 (AGM 椭圆积分; 含动力学电感)
# =====================================================================
class TestN10Cpw:

    _TYPICAL = dict(freq=5e9, line_width=10e-6, line_gap=6e-6,
                    substrate_thickness=760e-6, film_thickness=200e-9)
    # 参考实现 (qiskit-metal cpw_calculations, Apache-2.0) 的输出 — 物理锚点
    _GOLDEN = dict(Lk=2.3681287381377575e-09, Lext=4.353629666360981e-07,
                   C=1.63492916307188e-10, Z0=51.60315696321091,
                   eps_eff=6.065432087076736, lambda_g=0.024345363624151843)

    def test_lumped_cpw_golden(self):
        from quantum_dsl import lumped_cpw
        r = lumped_cpw(**self._TYPICAL)
        for key in ("Lk", "Lext", "C", "Z0", "eps_eff"):
            assert getattr(r, key) == pytest.approx(self._GOLDEN[key], rel=1e-9), key

    def test_guided_wavelength_golden(self):
        from quantum_dsl import guided_wavelength
        r = guided_wavelength(**self._TYPICAL)
        assert r.lambda_g == pytest.approx(self._GOLDEN["lambda_g"], rel=1e-9)
        assert r.eps_eff == pytest.approx(self._GOLDEN["eps_eff"], rel=1e-9)

    def test_kinetic_inductance_can_dominate(self):
        """窄线 + 薄膜 + 大 λ_L → Lk > Lext (动力学电感不是修正项, 是主项)。"""
        from quantum_dsl import lumped_cpw
        r = lumped_cpw(freq=5e9, line_width=1e-6, line_gap=0.5e-6,
                       substrate_thickness=500e-6, film_thickness=20e-9,
                       london_penetration_depth=90e-9)
        assert r.Lk > r.Lext


# =====================================================================
# N11 — 子系统: TL 谐振器等效 LC + 色散位移 χ (非 RWA 三能级二阶式,
# Zhu et al. arXiv:1210.1605 eq. 11-14 取三能级; 注意 Koch 2007 (3.9)/(3.10)
# 是 RWA 版不含反旋转项, qiskit-metal 源码注释误引 — 见 physics-pipeline.md §2)
# =====================================================================
class TestN11Subsystems:

    def test_resonator_lumped_lc_half_wave(self):
        from quantum_dsl import resonator_lumped_lc
        c_r, l_r = resonator_lumped_lc(7.0e9, 50.0, mode="half_wave")
        omega = 2 * math.pi * 7.0e9
        assert c_r == pytest.approx(math.pi / (2 * omega * 50.0), rel=1e-12)
        assert l_r == pytest.approx(1.0 / (omega ** 2 * c_r), rel=1e-12)

    def test_resonator_lumped_lc_quarter_wave(self):
        """λ/4: 同频率下 C_r 减半、L_r 加倍 (方向别记反), 共振频率不变。"""
        from quantum_dsl import resonator_lumped_lc
        c_h, l_h = resonator_lumped_lc(7.0e9, 50.0, mode="half_wave")
        c_q, l_q = resonator_lumped_lc(7.0e9, 50.0, mode="quarter_wave")
        assert c_q == pytest.approx(c_h / 2, rel=1e-12)
        assert l_q == pytest.approx(l_h * 2, rel=1e-12)
        assert 1 / (2 * math.pi * math.sqrt(l_q * c_q)) == pytest.approx(7.0e9)

    def test_dispersive_shift_golden(self):
        """χ 微扰式 golden (g=41.19 MHz, f_r=7 GHz, f01=5.2, f12=4.95)。"""
        from quantum_dsl import dispersive_shift_hz
        chi = dispersive_shift_hz(41.19e6, 7.0e9, 5.2e9, 4.95e9)
        assert chi == pytest.approx(-117856.23947910377, rel=1e-9)


# =====================================================================
# N12 — 圆角多边形 cell → .geo
# =====================================================================
class TestN12Cells:

    def test_rounded_polygon_area(self):
        """100×100 方 + r=10 圆角 → 面积 10000 − (4−π)·r² (采样内接, 容 1%)。"""
        from quantum_dsl import rounded_polygon
        pts = rounded_polygon([(0, 0), (100, 0), (100, 100), (0, 100)],
                              radius_um=10.0)
        assert len(pts) > 8            # 角上有采样点, 不再是 4 顶点
        area = 0.5 * abs(sum(x1 * y2 - x2 * y1
                             for (x1, y1), (x2, y2)
                             in zip(pts, pts[1:] + pts[:1])))
        exact = 10000.0 - (4.0 - math.pi) * 100.0
        assert area == pytest.approx(exact, rel=0.01)

    def test_emit_geo_roundtrip(self, tmp_path):
        """emit 的 .geo 必须能被 load_geo 回读 (物理名契约闭环)。"""
        from quantum_dsl import emit_geo, load_geo
        text = emit_geo([{"component": "Q1", "layer": 1, "role": "metal",
                          "points": [(0, 0), (100, 0), (100, 100), (0, 100)],
                          "corner_radius_um": 10.0}])
        assert 'Physical Surface("metal::1::Q1::' in text
        p = tmp_path / "cells.geo"
        p.write_text(text, encoding="utf-8")
        geo = load_geo(p)
        (phys,) = geo.physicals
        assert phys.component == "Q1" and phys.role == "metal"


# =====================================================================
# N13 — 编排: build(meta, out_dir, solve=False)
# =====================================================================
class TestN13Build:

    def test_no_solve_produces_all_artifacts(self, tmp_path):
        from quantum_dsl import build
        r = build(TWO_PADS_META, tmp_path, solve=False)
        for key in ("gds", "mesh", "config", "manifest"):
            assert Path(r[key]).exists(), key

    def test_manifest_records_input_sha256(self, tmp_path):
        from quantum_dsl import build
        r = build(TWO_PADS_META, tmp_path, solve=False)
        manifest = yaml.safe_load(Path(r["manifest"]).read_text(encoding="utf-8"))
        geo_sha = hashlib.sha256(
            (FIXTURES / "two_pads.geo").read_bytes()).hexdigest()
        recorded = {e["sha256"] for e in manifest["inputs"]}
        assert geo_sha in recorded


# =====================================================================
# N14 — 分块提取: extract.blocks → block_<name>.geo 落盘
# =====================================================================
class TestN14Extract:

    def test_blocks_derived_and_scoped(self, tmp_path):
        from quantum_dsl import build
        r = build(BLOCKS_META, tmp_path, solve=False)
        block_a = tmp_path / "block_A.geo"
        block_b = tmp_path / "block_B.geo"
        assert block_a.exists() and block_b.exists()
        a_text = block_a.read_text(encoding="utf-8")
        assert "metal::1::A::pad" in a_text
        assert "metal::1::B::pad" not in a_text     # 块只含自己的 component
        # 每块有自己的 Palace config
        assert len(r["blocks"]) == 2
        for blk in r["blocks"]:
            assert Path(blk["config"]).exists()


# =====================================================================
# N15 — 外部物理验证: Sung et al. PRX 11.021058 (gated, 独立于 N7 闸门)
# N7 是自参照回归锚 (钉配方可复现); 本组才锚外部真相 (论文/跨求解器)。
# 判据出处、可复现边界与排除项: tests/fixtures/sung_2021_device.meta.yaml 头注。
# =====================================================================
class TestN15SungPaper:

    def _solve(self, tmp_path):
        from quantum_dsl import build
        result = build(SUNG_META, tmp_path, solve=True)
        return yaml.safe_load(
            Path(result["results"]).read_text(encoding="utf-8"))

    @live_sung
    def test_c_sigma_against_paper(self, tmp_path):
        """C_Σ ×3 对论文 ±5%。诊断参照 (v3 Elmer 6.87M tets 权威档):
        102.1/232.8/102.1 fF (对论文 1.00–1.03) — 若失败先比对它再怀疑物理。"""
        doc = self._solve(tmp_path)
        qubits = {q["name"]: q for q in doc["hamiltonian"]["qubits"]}
        paper = {"QB1": 99.3, "CPLR": 227.9, "QB2": 101.9}  # fF, 由论文 E_C 换算
        for name, ref in paper.items():
            assert qubits[name]["C_sigma_fF"] == pytest.approx(ref, rel=0.05)

    @live_sung
    def test_qubit_coupler_beta_against_paper(self, tmp_path):
        """无量纲 β = |C'⁻¹_ij|/√(C'⁻¹_ii·C'⁻¹_jj) 与磁通/E_J 无关, 可对论文
        断言 (v3 Elmer 得 0.0390, +7% 系简化版图所致 → 容差 ±20%)。
        排除项 (结构性, 见 meta 头注): β_12/C_12 (本版图无直接 q-q 路径,
        差分远场相消, Elmer 也只得论文的 2%), 绝对 g 与 CPLR/QB2 的 f01
        (论文在磁通工作点, 本模型坐零磁通)。"""
        doc = self._solve(tmp_path)
        betas = {frozenset((c["qubit_a"], c["qubit_b"])): c["beta"]
                 for c in doc["hamiltonian"]["couplings"]}
        assert betas[frozenset(("QB1", "CPLR"))] == pytest.approx(0.0364, rel=0.20)
        assert betas[frozenset(("QB2", "CPLR"))] == pytest.approx(0.0364, rel=0.20)
