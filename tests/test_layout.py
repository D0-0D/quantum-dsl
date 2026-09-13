# -*- coding: utf-8 -*-
"""版图编排 (契约 N16): 模板 (.geo + yaml) + 有序步骤 → 一个 gmsh 模型; 手写 .geo 混用;
层槽位映射; 端口 → 定长路由 → net 认领; ground: sheet; 编排器纪律 (全部 raise)。
设计稿 docs/design/component-library.md v3.1。"""
from __future__ import annotations

import math
import textwrap
from pathlib import Path

import pytest
import yaml

from conftest import EXAMPLES

LIB = EXAMPLES / "lib"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def _meta(tmp_path: Path, layout: str, layers: dict, extra: str = "") -> Path:
    return _write(tmp_path / "chip.meta.yaml", f"""
        schema: quantum-dsl/meta/1
        layout: {layout}
        layers: {yaml.safe_dump(layers, default_flow_style=True).strip()}
        materials: {{substrate: {{eps_r: 11.45, thickness_um: 100}}}}
        airbox: {{top_um: 120, bottom_um: 120, side_um: 80}}
        mesh: {{max_size_um: 40, min_size_um: 4}}
        {extra}
        """)


# ---------------------------------------------------------------- N16 等价性
def test_two_pads_layout_equals_hand_written_geo(tmp_path):
    """契约 N16: two_pads.layout.yaml (两个 pad 模板实例, 槽位 metal → 芯片层 1) 产出的 Physical 名、
    GDS 多边形与网格标签与手写 two_pads.geo 逐字相同; build() 走版图路线: manifest 记录版图 + 模板文件,
    meta 手写的 circuit_model 原样保留。"""
    import gdstk

    from quantum_dsl import build, build_gds, load_geo, load_meta
    m = load_meta(EXAMPLES / "two_pads_layout.meta.yaml")
    hand = load_meta(EXAMPLES / "two_pads.meta.yaml")

    def boxes(gds):
        (cell,) = gdstk.read_gds(str(gds)).top_level()
        return sorted(tuple(round(v, 6) for pt in p.bounding_box() for v in pt)
                      for p in cell.polygons), {(p.layer, p.datatype) for p in cell.polygons}

    r = build(m, tmp_path / "lay", solve=False)
    assert r["layout"].ports["A.E"].w == 80 and r["layout"].ports["B.W"].a == pytest.approx(math.pi)
    assert boxes(r["gds"]) == boxes(build_gds(hand.geo_path, hand, tmp_path / "hand.gds"))
    assert {p.name for p in load_geo(r["layout"]).physicals} == {"metal::1::A::pad", "metal::1::B::pad"}
    manifest = yaml.safe_load(Path(r["manifest"]).read_text(encoding="utf-8"))
    names = {Path(e["path"]).name for e in manifest["inputs"]}
    assert {"two_pads_layout.meta.yaml", "two_pads.layout.yaml", "pad.yaml", "pad.geo"} <= names
    assert Path(r["mesh"]).exists() and Path(r["gds_png"]).exists()


# ---------------------------------------------------------------- N16 混用 + 路由 + 地
def test_xmon_readout_layout_mixes_template_handwritten_and_route(tmp_path):
    """契约 N16: xmon 模板 (岛 + moat 蚀刻 + 结 → circuit_model.qubits 自动生成 + 读出桨外挂面) + 手写
    发射焊盘 (.geo 自打名, 声明端口/蚀刻) + 定长蛇形路由 (λ/4 @ 7 GHz, 宽度继承端口) + ground: sheet。
    (a) 路由 net = 唯一岛端 F0: 桨、蛇形、焊盘三组面同 component; (b) 记账长度 = cpw.guided_wavelength 的
    λ_g/4, GDS 中心导体面积 = w·L (圆弧采样 ≲1e-4); (c) 地是带孔面 (面积 < 外接矩形); (d) 网格标签 = 两个 net。"""
    import gdstk

    from quantum_dsl import build_gds, build_mesh, compile_layout, guided_wavelength, load_geo, load_meta
    m = load_meta(EXAMPLES / "xmon_readout.meta.yaml")
    lay = compile_layout(m)
    assert lay.qubits == [{"name": "Q1", "island": "Q1", "E_J": pytest.approx(12.2e9)}]
    assert lay.ports["Q1.RO"].net == "F0" and lay.ports["Q1.RO"].ext is None
    (sub,) = lay.subsystems
    lam_um = guided_wavelength(7e9, 10e-6, 6e-6, 500e-6, 200e-9).lambda_g * 1e6
    assert sub["name"] == "F0" and sub["route"] == "R1"
    assert sub["length_drawn_um"] == pytest.approx(lam_um / 4, rel=1e-9)
    assert {p.name for p in load_geo(lay).physicals} == {
        "metal::m1::Q1::island", "metal::m1::F0::RO", "metal::m1::F0::cpw",
        "metal::m1::F0::launch", "jj::jj::Q1::jj", "ground::m1::GND::sheet"}

    (cell,) = gdstk.read_gds(str(build_gds(lay, m, tmp_path / "x.gds"))).top_level()
    polys = sorted(cell.polygons, key=lambda p: -p.area())
    ground, cpw = polys[0], polys[1]
    (x0, y0), (x1, y1) = ground.bounding_box()
    assert ground.area() < (x1 - x0) * (y1 - y0) * 0.95            # 带孔
    assert cpw.area() == pytest.approx(10.0 * lam_um / 4, rel=2e-4)
    assert {p.layer for p in polys} == {1, 20}

    mesh = build_mesh(lay, m, tmp_path / "x.msh")
    assert mesh.labels == ("F0", "Q1") and "ground" in mesh.boundary_groups


# ---------------------------------------------------------------- N16 嵌套 + 再导出 + 镜像
def test_nested_template_reexports_ports_and_externals(tmp_path):
    """契约 N16: 无 .geo 的模板只由 steps 组成 (两个 pad 子实例, 一个镜像); 父模板再导出子端口
    (ports: {E: R.E}) 与子岛为外挂面 (external: {C: {inst: R}}); 整体旋转 90° 放置; 一条固定长度
    路由从外挂端口出发, 外挂面并入岛端的 net。component 加实例前缀 (P_L), 层槽位经父模板映射。"""
    from quantum_dsl import compile_layout, load_geo, load_meta
    _write(tmp_path / "pair.yaml", """
        schema: quantum-dsl/template/1
        layers: {metal: conductor}
        steps:
          - {template: pad, name: L, at: [-100, 0], params: {w: 40, h: 20}}
          - {template: pad, name: R, at: [100, 0],  params: {w: 40, h: 20}, mirror: x}
        ports: {E: R.E, W: L.W}
        external: {C: {inst: R}}
        """)
    _write(tmp_path / "chip.layout.yaml", f"""
        schema: quantum-dsl/layout/1
        templates: [., {LIB.as_posix()}]
        steps:
          - {{template: pair, name: P, at: [0, 0], rot: 90}}
          - {{template: pad, name: T, at: [0, 600], params: {{w: 40, h: 20}}, rot: 90}}
          - {{template: cpw_meander, name: R0, from: P.E, to: T.W, params: {{R: 25, n_legs: 4, gap: 6}},
             length: {{mode: fixed, L: 900um}}}}
        ground: none
        """)
    m = load_meta(_meta(tmp_path, "chip.layout.yaml", {"metal": {"kind": "conductor", "gds": [1, 0]}}))
    lay = compile_layout(m)
    e = lay.ports["P.E"]
    assert (e.x, e.y, e.a) == (pytest.approx(0.0), pytest.approx(120.0), pytest.approx(math.pi / 2))
    assert e.net == "T" and e.w == 20                               # 外挂面已并入岛端 T 的 net
    assert lay.ports["P_L.E"].net == "P_L"                           # 未再导出的子端口按子实例名可寻址
    assert {p.name for p in load_geo(lay).physicals} == {
        "metal::metal::P_L::pad", "metal::metal::T::C", "metal::metal::T::pad", "metal::metal::T::cpw"}
    assert lay.subsystems[0]["length_drawn_um"] == pytest.approx(900.0)


# ---------------------------------------------------------------- N16 纪律
def test_layout_discipline_raises_not_silent(tmp_path):
    """契约 N16: 编排器拒绝静默 —— 手写步骤删/改模板面; 画了外挂面却没人接; 不同 net 导体相交 (短路);
    两口不正对; 模板 .geo 漏设输出变量 (NaN 置毒); 未知参数; 层槽位 kind 不兼容。"""
    from quantum_dsl import QuantumDslError, compile_layout, load_meta
    layers = {"m": {"kind": "conductor", "gds": [1, 0]}, "j": {"kind": "junction", "gds": [20, 0]}}

    def compile_steps(steps: str, ground: str = "none", **kw):
        doc = {"schema": "quantum-dsl/layout/1", "templates": [".", LIB.as_posix()],
               "steps": yaml.safe_load(steps), "ground": yaml.safe_load(ground)}
        (tmp_path / "chip.layout.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
        return compile_layout(load_meta(_meta(tmp_path, "chip.layout.yaml", layers, **kw)))

    # 手写步骤对模板面做布尔 → 增量原则
    _write(tmp_path / "cut.geo", 'SetFactory("OpenCASCADE");\n'
           "h = news; Disk(h) = { A_E_x - 20, 0, 0, 10 };\n"
           "r() = BooleanDifference{ Surface{ 1 }; Delete; }{ Surface{ h }; Delete; };\n"
           'Physical Surface("metal::m::X::hole") = { r() };\n')
    with pytest.raises(QuantumDslError, match="only ADD"):
        compile_steps("- {template: pad, name: A, layers: {metal: m}}\n- {geo: cut.geo}")
    # 外挂面无人连接
    with pytest.raises(QuantumDslError, match="nothing connects"):
        compile_steps("- {template: xmon, name: Q, layers: {metal: m, jj: j}, E_J: 12GHz}")
    # 不同 net 的导体相交 = 短路
    with pytest.raises(QuantumDslError, match="short"):
        compile_steps("- {template: pad, name: A, layers: {metal: m}}\n"
                      "- {template: pad, name: B, layers: {metal: m}, at: [50, 0]}")
    # 两口不正对
    with pytest.raises(QuantumDslError, match="face each other"):
        compile_steps("- {template: pad, name: A, layers: {metal: m}}\n"
                      "- {template: pad, name: B, layers: {metal: m}, at: [500, 0]}\n"
                      "- {template: cpw_meander, name: R, from: A.E, to: B.E, length: {mode: fixed, L: 800um}}")
    # 模板 .geo 漏设输出 → 置毒 NaN 被抓
    _write(tmp_path / "lazy.geo", 'SetFactory("OpenCASCADE");\ns = news; Rectangle(s) = {0,0,0,w,w};\nf() = {s};\n')
    _write(tmp_path / "lazy.yaml", """
        schema: quantum-dsl/template/1
        params: {w: 10}
        layers: {metal: conductor}
        islands: {i: {faces: f(), layer: metal}}
        ports: {E: {x: px, y: 0, a: 0, w: w}}
        """)
    with pytest.raises(QuantumDslError, match="unset"):
        compile_steps("- {template: lazy, name: A, layers: {metal: m}}")
    # 未知参数 / 层 kind 不兼容
    with pytest.raises(QuantumDslError, match="unknown param"):
        compile_steps("- {template: pad, name: A, layers: {metal: m}, params: {width: 3}}")
    with pytest.raises(QuantumDslError, match="needs a conductor layer"):
        compile_steps("- {template: pad, name: A, layers: {metal: j}}")
    # 结能量缺失
    with pytest.raises(QuantumDslError, match="E_J / L_J / squid"):
        compile_steps("- {template: xmon, name: Q, layers: {metal: m, jj: j}, params: {ro: 0}}")
    # 正例: 关掉读出桨的 xmon 单独成片 (无外挂面), ground sheet 减去 moat
    lay = compile_steps("- {template: xmon, name: Q, layers: {metal: m, jj: j}, params: {ro: 0}, E_J: 12GHz}",
                        ground="{sheet: {layer: m, margin_um: 100}}")
    assert lay.qubits[0]["island"] == "Q" and "Q.RO" not in lay.ports


# ---------------------------------------------------------------- N3/N2 词汇扩展
def test_meta_layers_table_and_identifier_layer_segment(tmp_path):
    """契约 N16 词汇: meta 'geo'/'layout' 二选一, 'layout' 必须配 'layers'; 层表 kind 受限、未知键 (如 z) raise;
    Physical 名第 2 段可以是标识符 (芯片层 id), 非数字非标识符 raise。"""
    from quantum_dsl import QuantumDslError, load_meta, parse_physical_name
    assert parse_physical_name("metal::m1::A::pad").layer == "m1"
    assert parse_physical_name("metal::7::A::pad").layer == 7
    with pytest.raises(QuantumDslError):
        parse_physical_name("metal::m-1::A::pad")
    base = "schema: quantum-dsl/meta/1\nmaterials: {substrate: {eps_r: 11.45, thickness_um: 100}}\n"
    p = tmp_path / "m.meta.yaml"
    for body, msg in ((base + "geo: a.geo\nlayout: b.layout.yaml\n", "exactly one"),
                      (base + "layout: b.layout.yaml\n", "requires a 'layers'"),
                      (base + "geo: a.geo\nlayers: {a: {kind: metal}}\n", "kind"),
                      (base + "geo: a.geo\nlayers: {a: {kind: conductor, z_um: 5}}\n", "unknown key")):
        p.write_text(body, encoding="utf-8")
        with pytest.raises(QuantumDslError, match=msg):
            load_meta(p)
    p.write_text(base + "geo: a.geo\nlayers: {a: {kind: conductor, gds: [1, 0]}, e: {kind: junction}}\n",
                 encoding="utf-8")
    m = load_meta(p)
    assert m.layers == {"a": {"kind": "conductor", "gds": (1, 0)}, "e": {"kind": "junction"}}
