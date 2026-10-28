# -*- coding: utf-8 -*-
"""几何分叉与编排 (需要 gmsh/gdstk, 不需要 Palace): import 纯度、
GDS、mesh、Palace config 与 CSV 解析、build 编排、
分块提取。"""
from __future__ import annotations

import hashlib
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import BLOCKS_META, EXAMPLES, FIXTURES, SRC, TWO_PADS_META


# ---------------------------------------------------------------- 纯度
def test_import_is_light_and_metal_free():
    """契约「import 纯度」: ``import quantum_dsl`` 不得拉起 qiskit_metal / gmsh / gdstk /
    matplotlib / jax / supergrad。在子进程里查 —— 本进程的其他测试早已 import 过 gmsh, 与
    测试顺序无关。"""
    code = ("import sys, quantum_dsl; "
            "bad = {'qiskit_metal', 'gmsh', 'gdstk', 'matplotlib', 'jax', 'supergrad'} & set(sys.modules); "
            "sys.exit('import quantum_dsl pulled %r' % sorted(bad) if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code],
                       env={**os.environ, "PYTHONPATH": str(SRC)},
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr.strip()


# ---------------------------------------------------------------- GDS
def test_build_gds_two_pads_roundtrip(tmp_path):
    """契约「GDS」: GDS µm verbatim (unit=1e-6), by_role 映射 layer/datatype,
    pad A 的包围盒逐字是 (-120,-40)-(-40,40)。"""
    import gdstk

    from quantum_dsl import build_gds, load_meta
    out = build_gds(EXAMPLES / "two_pads.geo", load_meta(TWO_PADS_META),
                    tmp_path / "chip.gds")
    lib = gdstk.read_gds(str(out))
    assert lib.unit == pytest.approx(1e-6)
    (cell,) = lib.top_level()
    polys = cell.polygons
    assert len(polys) == 2
    assert all(p.layer == 1 and p.datatype == 0 for p in polys)
    boxes = sorted(tuple(round(v, 6) for pt in p.bounding_box() for v in pt)
                   for p in polys)
    assert boxes[0] == (-120.0, -40.0, -40.0, 40.0)
    assert boxes[1] == (40.0, -40.0, 120.0, 40.0)


# ---------------------------------------------------------------- mesh + Palace
@pytest.fixture(scope="module")
def two_pads_mesh(tmp_path_factory):
    """two_pads 网格化一次, 网格 与 Palace config 共用 (秒级, 但没必要跑两遍)。"""
    from quantum_dsl import build_mesh, load_meta
    out = tmp_path_factory.mktemp("two_pads")
    meta = load_meta(TWO_PADS_META)
    return meta, build_mesh(EXAMPLES / "two_pads.geo", meta, out / "chip.msh")


def test_build_mesh_two_pads(two_pads_mesh):
    """契约「网格」: 零厚度导体片 imprint 为边界面组, 按 component 命名可寻址
    (Palace Terminal 的绑定键); 有 3D 体网格 (真空 + 衬底)。"""
    _, mesh = two_pads_mesh
    assert mesh.path.exists() and mesh.path.stat().st_size > 1000
    assert set(mesh.conductor_groups) == {"A", "B"}
    assert mesh.labels == ("A", "B")
    assert mesh.num_cells > 0
    assert mesh.num_volume_cells > 0


def test_palace_config_shape(two_pads_mesh, tmp_path):
    """契约「Palace」: Electrostatic, order 2, 每个导体一个 Terminal。"""
    from quantum_dsl import palace_config
    meta, mesh = two_pads_mesh
    cfg = palace_config(mesh, meta, tmp_path / "chip.json")
    assert (tmp_path / "chip.json").exists()
    assert cfg["Problem"]["Type"] == "Electrostatic"
    assert cfg["Solver"]["Order"] == 2
    assert cfg["Model"]["L0"] == 1e-6          # 仓库唯一的 µm→m 换算点
    assert len(cfg["Boundaries"]["Terminal"]) == 2


def test_parse_capacitance_verbatim_csv_and_nan_guard(tmp_path):
    """契约「Palace」: 吃 Palace 0.16 的 verbatim terminal-C.csv (SI 法拉 → fF ×1e15);
    mutual 由 Maxwell 代数导出 (Cm_ii = Σ_j C_ij); NaN 一律拒绝。"""
    from quantum_dsl import QuantumDslError, parse_capacitance
    cap = parse_capacitance(FIXTURES / "palace_postpro", labels=("A", "B"))
    assert cap.labels == ("A", "B")
    m = cap.maxwell_fF
    assert m[0][0] == pytest.approx(135.4305474059)
    assert m[1][1] == pytest.approx(135.4665489642)
    assert m[0][1] == pytest.approx(-33.06523790651)
    assert m[0][1] == m[1][0]                          # 对称
    mu = cap.mutual_fF
    assert mu[0][1] == pytest.approx(+33.06523790651)  # mutual 全正
    assert mu[0][0] == pytest.approx(m[0][0] + m[0][1])

    p = tmp_path / "postpro"
    p.mkdir()
    (p / "terminal-C.csv").write_text(
        " i, C[i][1] (F), C[i][2] (F)\n 1, nan, 0\n 2, 0, 1e-15\n", encoding="utf-8")
    with pytest.raises(QuantumDslError):
        parse_capacitance(p, labels=("A", "B"))


# ---------------------------------------------------------------- 编排
def test_build_no_solve_artifacts_and_manifest(tmp_path):
    """契约「build 编排」: build(solve=False) 产 gds/gds_png/mesh/config/manifest,
    manifest 记录输入的真 sha256 与全部产物; PNG 里金属与缝两色都在。"""
    from PIL import Image

    from quantum_dsl import build
    r = build(TWO_PADS_META, tmp_path, solve=False)
    for key in ("gds", "gds_png", "mesh", "config", "manifest"):
        assert Path(r[key]).exists(), key
    manifest = yaml.safe_load(Path(r["manifest"]).read_text(encoding="utf-8"))
    geo_sha = hashlib.sha256((EXAMPLES / "two_pads.geo").read_bytes()).hexdigest()
    assert geo_sha in {e["sha256"] for e in manifest["inputs"]}
    assert str(r["gds_png"]) in {e["path"] for e in manifest["outputs"]}
    assert len(Image.open(r["gds_png"]).getcolors()) == 2


# ---------------------------------------------------------------- 分块
def test_extract_blocks_derived_and_scoped(tmp_path):
    """契约「分块」: extract.blocks → block_<name>.geo 只含该块 component 的
    Physical 组, 每块有自己的 Palace config。two_pads_blocks 的 A/B 相距 80 µm
    却从不共现 → 如设计触发「跨块直接互容 = 结构性零」告警。"""
    from quantum_dsl import build
    with pytest.warns(UserWarning, match="structurally ZERO"):
        r = build(BLOCKS_META, tmp_path, solve=False)
    a_text = (tmp_path / "block_A.geo").read_text(encoding="utf-8")
    assert "metal::1::A::pad" in a_text
    assert "metal::1::B::pad" not in a_text
    assert (tmp_path / "block_B.geo").exists()
    assert len(r["blocks"]) == 2
    for blk in r["blocks"]:
        assert Path(blk["config"]).exists()


def test_build_blocks_only_skips_the_whole_chip(tmp_path):
    """契约「分块」: ``build(blocks=[...])`` 只做指定的块 —— 跳过整片网格/config (整片可能比
    单块大两个数量级, 本机跑不动, 否则「单块可解」只能靠手抄脚本); 每块 Palace 输出目录
    互不覆盖; 块名拼错 raise。"""
    import json

    from quantum_dsl import QuantumDslError, build
    r = build(BLOCKS_META, tmp_path, blocks=["A"])
    assert "mesh" not in r and "config" not in r          # 整片被跳过
    assert not list(tmp_path.glob("two_pads*.msh"))
    assert [b["name"] for b in r["blocks"]] == ["A"] and r["blocks"][0]["labels"] == ("A",)
    assert json.loads((tmp_path / "block_A.json").read_text())["Problem"]["Output"] == "postpro_block_A"
    with pytest.raises(QuantumDslError, match="unknown block name"):
        build(BLOCKS_META, tmp_path / "x", blocks=["A", "Nope"])


# ---------------------------------------------------------------- targets / 收敛 (假 Palace)
def _fake_palace(monkeypatch, maxwell_fF):
    """把 build 里的 Palace 换成按 config 目录名写 verbatim terminal-C.csv 的桩 (fF → F)。"""
    def run(cfg):
        m = maxwell_fF(cfg.parent.name)
        p = cfg.parent / "postpro"
        p.mkdir()
        lines = [" i, " + ", ".join(f"C[i][{j + 1}] (F)" for j in range(len(m)))]
        lines += [f" {i + 1}, " + ", ".join(f"{v * 1e-15:.15e}" for v in row) for i, row in enumerate(m)]
        (p / "terminal-C.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules["quantum_dsl.build"], "_run_palace", run)


def _two_pads_meta(tmp_path, **extra) -> Path:
    doc = yaml.safe_load(TWO_PADS_META.read_text(encoding="utf-8"))
    doc["geo"] = str(EXAMPLES / "two_pads.geo")
    doc.update(extra)
    p = tmp_path / "t.meta.yaml"
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return p


def test_targets_validation_in_results(tmp_path, monkeypatch):
    """契约「targets」: meta ``targets:`` → results.yaml 的 validation 段 (期望 / 实测 / 偏差 / pass),
    未命中只 warn 不 raise; 拼错 qubit 名在网格化之前 raise。
    闭式: Maxwell [[25, −2], [−2, 25]] fF → C_Σ = (25² − 2²)/25 = 24.84 fF, β = 2/25。
    静态 ZZ (couplings.zz_MHz) 同样可核对; ``期望 x, tol 100%`` = 「0 … 2x」, 是单边上限的写法。"""
    from quantum_dsl import QuantumDslError, build
    _fake_palace(monkeypatch, lambda run: [[25.0, -2.0], [-2.0, 25.0]])
    meta = _two_pads_meta(tmp_path, targets={
        "source": "闭式",
        "qubits": {"A": {"C_sigma_fF": 24.84, "tol": "1%"}, "B": {"C_sigma_fF": 30, "tol": "5%"}},
        "couplings": [{"pair": ["A", "B"], "beta": 0.08, "zz_MHz": 1.0, "tol": {"beta": "1%", "zz_MHz": "100%"}}]})
    with pytest.warns(UserWarning, match=r"targets: 2/4 missed — B\.C_sigma_fF.*zz_MHz"):
        r = build(meta, tmp_path / "out", solve=True)
    doc = yaml.safe_load(Path(r["results"]).read_text(encoding="utf-8"))
    v = doc["validation"]
    zz = next(c for c in v["checks"] if c["field"] == "zz_MHz")    # 静态 ZZ 可核对 (两块焊盘强耦合: 远超 2 MHz)
    assert zz["actual"] == doc["hamiltonian"]["couplings"][0]["zz_MHz"] and zz["actual"] > 2.0 and not zz["pass"]
    v["checks"].remove(zz)
    assert v["source"] == "闭式" and v["passed"] is False
    rows = {(c.get("qubit") or tuple(c["pair"])): c for c in v["checks"]}
    assert rows["A"]["actual"] == pytest.approx(24.84) and rows["A"]["pass"]
    assert rows["A"]["deviation"] == pytest.approx(0.0, abs=1e-9)
    assert rows["B"]["deviation"] == pytest.approx(24.84 / 30 - 1) and not rows["B"]["pass"]
    assert rows[("A", "B")]["actual"] == pytest.approx(0.08) and rows[("A", "B")]["pass"]

    typo = _two_pads_meta(tmp_path, targets={"qubits": {"C": {"f01_GHz": 5, "tol": "5%"}}})
    with pytest.raises(QuantumDslError, match=r"unknown qubit\(s\) \['C'\]"):
        build(typo, tmp_path / "typo", solve=True)
    assert not list((tmp_path / "typo").glob("*.msh"))       # 网格化之前就拦下


def test_gates_stage_in_build_and_tune(tmp_path, monkeypatch):
    """契约「门仿真」: meta ``gates:`` → ``build(solve=True)`` 的整片 results 多 ``gates`` 段 (SuperGrad 门级演化,
    管线最后一段); max_error 未达标只 warn, pass = False; 门里的 qubit 名拼错在网格化之前 raise (build 与 tune 都是);
    ``tune`` 各轮不跑门, 只在终版 results 上跑一次; 门阶段出错时 results.yaml / tune.yaml 已落盘。(要 SuperGrad, 没装 skip)"""
    pytest.importorskip("supergrad")
    from quantum_dsl import QuantumDslError, build, tune
    _fake_palace(monkeypatch, lambda run: [[25.0, -2.0], [-2.0, 25.0]])
    gate = {"name": "XA", "kind": "x_drag", "qubit": "A", "t_gate": "10ns", "max_error": 1e-12}
    with pytest.warns(UserWarning, match=r"gates: 1/1 above max_error — XA"):
        r = build(_two_pads_meta(tmp_path, gates=[gate]), tmp_path / "out", solve=True)
    g = yaml.safe_load(Path(r["results"]).read_text(encoding="utf-8"))["gates"]
    assert [(x["name"], x["qubit"], x["t_gate_ns"], x["pass"]) for x in g] == [("XA", "A", 10.0, False)]
    assert 0 < g[0]["error"] < g[0]["gaussian_error"]

    typo = _two_pads_meta(tmp_path, gates=[{**gate, "qubit": "C"}])
    with pytest.raises(QuantumDslError, match=r"unknown qubit\(s\) \['C'\]"):
        build(typo, tmp_path / "typo", solve=True)
    assert not list((tmp_path / "typo").glob("*.msh"))

    meta = _meta_copy(tmp_path, "two_pads_layout.meta.yaml",
                      targets={"qubits": {"A": {"f01_exact_GHz": 6.0, "tol": "0.5%"}}},
                      tune={"knobs": [{"param": "A.L_J", "target": "A.f01_exact_GHz"}]},
                      gates=[{**gate, "max_error": 0.1}])
    t = tune(meta, tmp_path / "tuned")
    assert "gates" not in yaml.safe_load(Path(t["history"][0]["dir"], "results.yaml").read_text(encoding="utf-8"))
    final = yaml.safe_load(t["results"].read_text(encoding="utf-8"))
    assert final["gates"][0]["pass"] is True and final["gates"][0]["f01_GHz"] == pytest.approx(6.0, rel=1e-6)

    # 门阶段本身出错: results.yaml (tune 还有 tune.yaml) 已经落盘, FEM / 综合结果不丢
    def boom(*_):
        raise RuntimeError("gate stage blew up")
    monkeypatch.setattr(sys.modules["quantum_dsl.gates"], "simulate_gates", boom)
    with pytest.raises(RuntimeError, match="blew up"):
        build(_two_pads_meta(tmp_path, gates=[gate]), tmp_path / "boom", solve=True)
    assert "hamiltonian" in yaml.safe_load((tmp_path / "boom" / "results.yaml").read_text(encoding="utf-8"))
    with pytest.raises(RuntimeError, match="blew up"):
        tune(meta, tmp_path / "boom_tune")
    assert (tmp_path / "boom_tune" / "results.yaml").exists() and (tmp_path / "boom_tune" / "tune.yaml").exists()

    # tune 里门名拼错: 第一轮 build 在网格化之前就拦下 (各轮 meta 带 gates:, 只是 gates=False 不跑)
    typo_tune = _meta_copy(tmp_path, "two_pads_layout.meta.yaml",
                           targets={"qubits": {"A": {"f01_exact_GHz": 6.0, "tol": "0.5%"}}},
                           tune={"knobs": [{"param": "A.L_J", "target": "A.f01_exact_GHz"}]},
                           gates=[{**gate, "qubit": "C"}])
    with pytest.raises(QuantumDslError, match=r"unknown qubit\(s\) \['C'\]"):
        tune(typo_tune, tmp_path / "typo_tune")
    assert not list((tmp_path / "typo_tune").rglob("*.msh"))


def test_gates_missing_dependency_raises_before_fem(tmp_path, monkeypatch):
    """契约「门仿真」: meta 有 ``gates:`` 而没装 ``.[gates]`` → build(solve=True) / tune 在网格化之前 raise
    (门在管线最后, 不能等小时级求解完才发现)。"""
    from quantum_dsl import QuantumDslError, build, tune
    monkeypatch.setitem(sys.modules, "supergrad", None)          # = 没装
    _fake_palace(monkeypatch, lambda run: [[25.0, -2.0], [-2.0, 25.0]])
    gate = {"name": "XA", "kind": "x_drag", "qubit": "A", "t_gate": "10ns"}
    with pytest.raises(QuantumDslError, match="needs SuperGrad"):
        build(_two_pads_meta(tmp_path, gates=[gate]), tmp_path / "out", solve=True)
    assert not list((tmp_path / "out").glob("*.msh"))
    build(_two_pads_meta(tmp_path, gates=[gate]), tmp_path / "mesh_only")    # 不求解就不需要 SuperGrad
    meta = _meta_copy(tmp_path, "two_pads_layout.meta.yaml",
                      targets={"qubits": {"A": {"f01_exact_GHz": 6.0, "tol": "0.5%"}}},
                      tune={"knobs": [{"param": "A.L_J", "target": "A.f01_exact_GHz"}]}, gates=[gate])
    with pytest.raises(QuantumDslError, match="needs SuperGrad"):
        tune(meta, tmp_path / "tuned")
    assert not (tmp_path / "tuned").exists()


def test_converge_scales_mesh_and_diffs_finest_two(tmp_path, monkeypatch):
    """契约「网格收敛」: 每档 mesh 尺寸同比缩放、各自整片求解, convergence.yaml 记最细两档的
    相对变化 (细 − 次细)/|细|。桩: 细档 C_AA 25.25 vs 粗档 25 → (25.25 − 25)/25.25, 其余不变 = 0。"""
    from quantum_dsl import QuantumDslError, converge
    _fake_palace(monkeypatch, lambda run: [[25.25 if run == "mesh_x1" else 25.0, -2.0],
                                           [-2.0, 25.0]])
    r = converge(TWO_PADS_META, tmp_path, scales=(1, 2))
    doc = yaml.safe_load(r["convergence"].read_text(encoding="utf-8"))
    assert doc == r["doc"]
    assert [(x["scale"], x["max_size_um"], x["min_size_um"]) for x in doc["runs"]] == [
        (2.0, 80.0, 8.0), (1.0, 40.0, 4.0)]                  # 粗 → 细
    coarse, fine = (Path(run["mesh"]) for run in r["runs"])
    assert fine.stat().st_size > coarse.stat().st_size      # 缩放真的进了网格
    rel = doc["capacitance"]["maxwell_rel_change"]
    assert rel[0][0] == pytest.approx(0.25 / 25.25)
    assert rel[0][1] == rel[1][0] == rel[1][1] == 0.0
    qa = doc["hamiltonian"]["qubits"]["A"]
    assert qa["C_sigma_fF"] > 0 and qa["E_C_GHz"] < 0 and qa["E_J_GHz"] == 0.0
    assert set(doc["hamiltonian"]["couplings"][0]) == {"pair", "beta", "g_MHz", "zz_MHz"}
    with pytest.raises(QuantumDslError, match="distinct positive scales"):
        converge(TWO_PADS_META, tmp_path, scales=(1.0, 1))


def _meta_copy(tmp_path, name, **extra) -> Path:
    """examples 里的 meta 复制到 tmp (layout / geo 改绝对路径) 并加键。"""
    doc = yaml.safe_load((EXAMPLES / name).read_text(encoding="utf-8"))
    for k in ("layout", "geo"):
        if k in doc:
            doc[k] = str(EXAMPLES / doc[k])
    doc.update(extra)
    p = tmp_path / name
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return p


def test_readout_resonator_generated_from_layout_and_checked(tmp_path, monkeypatch):
    """契约「读出链路」: 版图里 λ/4 定长路由 R1 (net F0) 自动成 resonator 条目 (f_r = 画长的裸频率, Z0 = 截面自洽集),
    整片求解出 hamiltonian.resonators / readout; targets 的 resonators / readout 段按名核对; 拼错腔名网格化前 raise。"""
    from quantum_dsl import QuantumDslError, build, compile_layout, load_meta, solve_circuit_model
    from quantum_dsl.build import _resonators_from
    mat = [[700.0, -4.0], [-4.0, 94.0]]                      # 行序 = sorted: F0, Q1
    _fake_palace(monkeypatch, lambda run: mat)
    (res,) = _resonators_from(compile_layout(load_meta(EXAMPLES / "xmon_readout.meta.yaml")).subsystems)
    assert res["name"] == "R1" and res["net"] == "F0" and res["mode"] == "quarter_wave"
    assert res["f_r"] == pytest.approx(7e9) and res["Z0"] == pytest.approx(51.046, rel=1e-4)
    ref = solve_circuit_model(("F0", "Q1"), mat, [{"name": "Q1", "islands": ["Q1"], "E_J": 12.2e9 * 6.62607015e-34}],
                              resonators=[res])
    f_r, chi = ref.resonators[0].f_r_GHz, ref.readout[0].chi_MHz
    meta = _meta_copy(tmp_path, "xmon_readout.meta.yaml", targets={
        "resonators": {"R1": {"f_r_GHz": f_r, "tol": "0.1%"}},
        "readout": [{"pair": ["Q1", "R1"], "chi_MHz": chi, "tol": "0.1%"}]})
    r = build(meta, tmp_path / "out", solve=True)
    doc = yaml.safe_load(Path(r["results"]).read_text(encoding="utf-8"))
    (rr,), (ro,) = doc["hamiltonian"]["resonators"], doc["hamiltonian"]["readout"]
    assert rr["name"] == "R1" and rr["net"] == "F0" and rr["f_r_GHz"] < rr["f_bare_GHz"] == pytest.approx(7.0)
    assert rr["kappa_MHz"] == 0.0 and ro["T1_purcell_us"] == math.inf       # 没有 port = 没有衰减通道
    assert ro["qubit"] == "Q1" and ro["chi_MHz"] < 0
    v = doc["validation"]
    assert v["passed"] and [c.get("resonator") or c.get("readout") for c in v["checks"]] == ["R1", ["Q1", "R1"]]
    (tmp_path / "t").mkdir()
    typo = _meta_copy(tmp_path / "t", "xmon_readout.meta.yaml",
                      targets={"resonators": {"R9": {"f_r_GHz": 7, "tol": "1%"}}})
    with pytest.raises(QuantumDslError, match=r"unknown resonator\(s\) \['R9'\]"):
        build(typo, tmp_path / "typo", solve=True)


def test_feedline_port_gives_kappa_and_port_t1(tmp_path, monkeypatch):
    """契约「读出链路」: xmon_feedline —— cpw_route λ/2 读出腔两端都是外挂面 (桨 / feed_tap 焊盘) → net = 步骤名 R1;
    feed_tap 的馈线 FL 是独立导体, meta 声明成 port (R = Z0/2) → results 的 κ、T1_port、Purcell 有限, 且与同一矩阵上
    solve_circuit_model 的值逐位相同 (闭式锚在 test_physics)。桩矩阵 = 2026-10-14 真 Palace 粗网格值 (κ/2π ≈ 5.6 MHz)。"""
    from quantum_dsl import build, compile_layout, load_meta, solve_circuit_model
    from quantum_dsl.build import _resonators_from
    mat = [[475.43, -0.006, -23.22], [-0.006, 96.80, -4.27], [-23.22, -4.27, 2082.19]]   # 行序 FL, Q1, R1
    _fake_palace(monkeypatch, lambda run: mat)
    m = load_meta(EXAMPLES / "xmon_feedline.meta.yaml")
    (res,) = _resonators_from(compile_layout(m).subsystems)
    assert (res["name"], res["net"], res["mode"]) == ("R1", "R1", "half_wave") and res["f_r"] == pytest.approx(7e9)
    ref = solve_circuit_model(("FL", "Q1", "R1"), mat,
                              [{"name": "Q1", "islands": ["Q1"], "E_J": 12.2e9 * 6.62607015e-34}],
                              resonators=[res], ports=[{"name": "feed", "net": "FL", "R": 25.5}])
    doc = yaml.safe_load(Path(build(m, tmp_path / "out", solve=True)["results"]).read_text(encoding="utf-8"))
    (q,), (rr,), (ro,) = (doc["hamiltonian"][k] for k in ("qubits", "resonators", "readout"))
    assert rr["kappa_MHz"] == pytest.approx(ref.resonators[0].kappa_MHz, rel=1e-12)
    assert rr["kappa_MHz"] == pytest.approx(5.6, rel=0.02)
    assert math.inf > q["T1_port_us"] == pytest.approx(ref.qubits[0].T1_port_us, rel=1e-12)
    assert math.inf > ro["T1_purcell_us"] == pytest.approx(ref.readout[0].T1_purcell_us, rel=1e-12)


def test_tune_closes_the_loop_and_emits_a_plain_config(tmp_path, monkeypatch):
    """契约「tune」: 几何旋钮 A.w (pad 模板参数, 缺省 = 模板默认 80) 按比例律 C_Σ ∝ w (law 1) + 对数割线迭代,
    结旋钮 A.L_J (meta qubit) 在缓存的 C 上二分求根命中 f01_exact; 终版 = 普通 layout + meta (可再编译), 带 results / tune.yaml。
    桩: C_AA = 0.3·w + 2 fF, C_AB = −2, C_BB = 25 ⇒ C_Σ,A = C_AA − 4/25; 目标 30 fF ⇒ w* = 93.87 µm。
    律 1 一步到 92.88 (C_Σ −1.0%, 未过 0.5%), 观测指数 0.933 再一步命中 ⇒ 3 次 FEM。"""
    from quantum_dsl import compile_layout, load_meta, tune

    def maxwell(run):
        lay = yaml.safe_load((tmp_path / "out" / run / "two_pads.layout.yaml").read_text(encoding="utf-8"))
        w = next(s for s in lay["steps"] if s["name"] == "A").get("params", {}).get("w", 80)
        return [[0.3 * w + 2, -2.0], [-2.0, 25.0]]
    _fake_palace(monkeypatch, maxwell)
    meta = _meta_copy(tmp_path, "two_pads_layout.meta.yaml",
                      targets={"qubits": {"A": {"C_sigma_fF": 30.0, "f01_exact_GHz": 6.0, "tol": "0.5%"}}},
                      tune={"knobs": [{"param": "A.w", "target": "A.C_sigma_fF", "law": 1, "bounds": [40, 200]},
                                      {"param": "A.L_J", "target": "A.f01_exact_GHz"}]})
    r = tune(meta, tmp_path / "out")
    assert r["converged"] and r["iterations"] == 3
    assert [h["knobs"]["A.w"] for h in r["history"]] == pytest.approx([80, 92.88, 93.87], abs=0.01)
    final = load_meta(r["meta"])
    a = next(s for s in yaml.safe_load(r["layout"].read_text(encoding="utf-8"))["steps"] if s["name"] == "A")
    assert a["params"]["w"] == pytest.approx(93.87, abs=0.01)
    assert compile_layout(final).qubits == [] and final.circuit_model["qubits"][0]["L_J"] != 1e-8
    doc = yaml.safe_load(r["results"].read_text(encoding="utf-8"))
    qa = doc["hamiltonian"]["qubits"][0]
    assert qa["f01_exact_GHz"] == pytest.approx(6.0, rel=1e-6) and doc["validation"]["passed"]
    assert yaml.safe_load(r["tune"].read_text(encoding="utf-8"))["converged"] is True


def test_tune_ignores_noise_dominated_secant(tmp_path, monkeypatch):
    """契约「tune」: 观测指数只在与 law 同号且在其 ¼–4 倍内才用。桩同上一条 (C_Σ,A = 0.3·w + 2 − 0.16), 但第 1 轮注入
    「重网格噪声」: C_Σ 只到 26.2 (真值 29.70) → 观测指数 0.09 ≪ law 1 → 第 2 步必须退回 law (w 92.88 → 106.35),
    不能按 0.09 外推 (那一步会顶到 bounds 200)。xmon_feedline_tune 的 κ 实测过这种抖动 (2026-10-14)。"""
    from quantum_dsl import tune

    def maxwell(run):
        lay = yaml.safe_load((tmp_path / "out" / run / "two_pads.layout.yaml").read_text(encoding="utf-8"))
        w = next(s for s in lay["steps"] if s["name"] == "A").get("params", {}).get("w", 80)
        return [[26.36 if run == "iter_1" else 0.3 * w + 2, -2.0], [-2.0, 25.0]]
    _fake_palace(monkeypatch, maxwell)
    meta = _meta_copy(tmp_path, "two_pads_layout.meta.yaml",
                      targets={"qubits": {"A": {"C_sigma_fF": 30.0, "tol": "0.5%"}}},
                      tune={"knobs": [{"param": "A.w", "target": "A.C_sigma_fF", "law": 1, "bounds": [40, 200]}],
                            "max_iter": 3})
    with pytest.warns(UserWarning, match="not converged"):
        r = tune(meta, tmp_path / "out")
    assert [h["knobs"]["A.w"] for h in r["history"]] == pytest.approx([80, 92.88, 106.35], abs=0.01)
