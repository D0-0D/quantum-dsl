# -*- coding: utf-8 -*-
"""几何分叉与编排 (需要 gmsh/gdstk, 不需要 Palace): import 纯度 (N0)、
GDS (N4)、mesh (N5)、Palace config 与 CSV 解析 (N6)、build 编排 (N13)、
分块提取 (N14)。"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import BLOCKS_META, EXAMPLES, FIXTURES, SRC, TWO_PADS_META


# ---------------------------------------------------------------- N0 纯度
def test_import_is_light_and_metal_free():
    """契约 N0: ``import quantum_dsl`` 不得拉起 qiskit_metal / gmsh / gdstk /
    matplotlib。在子进程里查 —— 本进程的其他测试早已 import 过 gmsh, 与
    测试顺序无关。"""
    code = ("import sys, quantum_dsl; "
            "bad = {'qiskit_metal', 'gmsh', 'gdstk', 'matplotlib'} & set(sys.modules); "
            "sys.exit('import quantum_dsl pulled %r' % sorted(bad) if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code],
                       env={**os.environ, "PYTHONPATH": str(SRC)},
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr.strip()


# ---------------------------------------------------------------- N4 GDS
def test_build_gds_two_pads_roundtrip(tmp_path):
    """契约 N4: GDS µm verbatim (unit=1e-6), by_role 映射 layer/datatype,
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


# ---------------------------------------------------------------- N5/N6 mesh + Palace
@pytest.fixture(scope="module")
def two_pads_mesh(tmp_path_factory):
    """two_pads 网格化一次, N5 与 N6 config 共用 (秒级, 但没必要跑两遍)。"""
    from quantum_dsl import build_mesh, load_meta
    out = tmp_path_factory.mktemp("two_pads")
    meta = load_meta(TWO_PADS_META)
    return meta, build_mesh(EXAMPLES / "two_pads.geo", meta, out / "chip.msh")


def test_build_mesh_two_pads(two_pads_mesh):
    """契约 N5: 零厚度导体片 imprint 为边界面组, 按 component 命名可寻址
    (Palace Terminal 的绑定键); 有 3D 体网格 (真空 + 衬底)。"""
    _, mesh = two_pads_mesh
    assert mesh.path.exists() and mesh.path.stat().st_size > 1000
    assert set(mesh.conductor_groups) == {"A", "B"}
    assert mesh.labels == ("A", "B")
    assert mesh.num_cells > 0
    assert mesh.num_volume_cells > 0


def test_palace_config_shape(two_pads_mesh, tmp_path):
    """契约 N6: Electrostatic, order 2, 每个导体一个 Terminal。"""
    from quantum_dsl import palace_config
    meta, mesh = two_pads_mesh
    cfg = palace_config(mesh, meta, tmp_path / "chip.json")
    assert (tmp_path / "chip.json").exists()
    assert cfg["Problem"]["Type"] == "Electrostatic"
    assert cfg["Solver"]["Order"] == 2
    assert cfg["Model"]["L0"] == 1e-6          # 仓库唯一的 µm→m 换算点
    assert len(cfg["Boundaries"]["Terminal"]) == 2


def test_parse_capacitance_verbatim_csv_and_nan_guard(tmp_path):
    """契约 N6: 吃 Palace 0.16 的 verbatim terminal-C.csv (SI 法拉 → fF ×1e15);
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


# ---------------------------------------------------------------- N13 编排
def test_build_no_solve_artifacts_and_manifest(tmp_path):
    """契约 N13: build(solve=False) 产 gds/mesh/config/manifest 四件,
    manifest 记录输入的真 sha256。"""
    from quantum_dsl import build
    r = build(TWO_PADS_META, tmp_path, solve=False)
    for key in ("gds", "mesh", "config", "manifest"):
        assert Path(r[key]).exists(), key
    manifest = yaml.safe_load(Path(r["manifest"]).read_text(encoding="utf-8"))
    geo_sha = hashlib.sha256((EXAMPLES / "two_pads.geo").read_bytes()).hexdigest()
    assert geo_sha in {e["sha256"] for e in manifest["inputs"]}


# ---------------------------------------------------------------- N14 分块
def test_extract_blocks_derived_and_scoped(tmp_path):
    """契约 N14: extract.blocks → block_<name>.geo 只含该块 component 的
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
