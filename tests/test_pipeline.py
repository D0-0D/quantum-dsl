# -*- coding: utf-8 -*-
"""几何分叉与编排 (需要 gmsh/gdstk, 不需要 Palace): import 纯度、
GDS、mesh、Palace config 与 CSV 解析、build 编排、
分块提取。"""
from __future__ import annotations

import hashlib
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
    matplotlib。在子进程里查 —— 本进程的其他测试早已 import 过 gmsh, 与
    测试顺序无关。"""
    code = ("import sys, quantum_dsl; "
            "bad = {'qiskit_metal', 'gmsh', 'gdstk', 'matplotlib'} & set(sys.modules); "
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
    闭式: Maxwell [[25, −2], [−2, 25]] fF → C_Σ = (25² − 2²)/25 = 24.84 fF, β = 2/25。"""
    from quantum_dsl import QuantumDslError, build
    _fake_palace(monkeypatch, lambda run: [[25.0, -2.0], [-2.0, 25.0]])
    meta = _two_pads_meta(tmp_path, targets={
        "source": "闭式",
        "qubits": {"A": {"C_sigma_fF": 24.84, "tol": "1%"}, "B": {"C_sigma_fF": 30, "tol": "5%"}},
        "couplings": [{"pair": ["A", "B"], "beta": 0.08, "tol": "1%"}]})
    with pytest.warns(UserWarning, match=r"targets: 1/3 missed — B\.C_sigma_fF"):
        r = build(meta, tmp_path / "out", solve=True)
    v = yaml.safe_load(Path(r["results"]).read_text(encoding="utf-8"))["validation"]
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
    assert set(doc["hamiltonian"]["couplings"][0]) == {"pair", "beta", "g_MHz"}
    with pytest.raises(QuantumDslError, match="distinct positive scales"):
        converge(TWO_PADS_META, tmp_path, scales=(1.0, 1))
