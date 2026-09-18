# -*- coding: utf-8 -*-
"""Chen 2025 圆盘比特模板 → 3×3 (Chen 2025 模板契约): disc_transmon (两半盘 + 跨缝结 + 可选爪外挂面) 与 bar_coupler
(连接型: 条 + 五边形 + 结, 两端爪并入条的 net) 在版图编排框架上排成 9 比特 + 12 耦合器; 几何数字来自
docs/design/paper-chen2025-geometry.md; 载片地 = airbox.top_um。"""
from __future__ import annotations

import dataclasses
import math

import pytest

from conftest import EXAMPLES

META = EXAMPLES / "chen_2025_3x3.meta.yaml"
COARSE = {"max_size_um": 300, "min_size_um": 20}       # 测试用秒级网格; 例子 meta 里的 100/4 是报数配方


def test_chen_2025_3x3_layout_compiles_to_21_junctions_and_paper_geometry(tmp_path):
    """契约「Chen 2025 模板」: (a) 9 个浮动比特 (islands [Q_a, Q_b]) + 12 个浮动耦合器 (islands [C, C_pent]) 自动进 circuit_model,
    连接型模板的路由体 component 就是 net 名 (结记账与 Physical 名一致); (b) 24 个爪端口全部被耦合器消费;
    (c) GDS 面积对照片参数: 半盘 = 圆缺 195²·acos(35/195) − 35·√(195²−35²), 五边形 378×(125 + 175/2), 条 30×849, 24 只爪; (d) 手性: 横向
    五边形在条 +y 侧靠东侧比特, 纵向 (mirror: x) 在条 +x 侧靠上方比特, 中心距该比特 540。"""
    import gdstk

    from quantum_dsl import build_gds, compile_layout, load_geo, load_meta
    m = load_meta(META)
    lay = compile_layout(m)
    by = {q["name"]: q for q in lay.qubits}
    assert len(by) == 21
    assert by["Q00"]["islands"] == ["Q00_a", "Q00_b"] and by["Q00"]["E_J"] == pytest.approx(12.4e9)
    assert by["H00"]["islands"] == ["H00", "H00_pent"] and by["V21"]["islands"] == ["V21", "V21_pent"]
    comps = {p.component for p in load_geo(lay).physicals if p.role == "metal"}
    assert len(comps) == 42 and {c for q in lay.qubits for c in q["islands"]} == comps
    assert len(lay.ports) == 24 and all(p.net is not None and p.ext is None for p in lay.ports.values())
    assert lay.ports["Q00.E"].net == "H00" and lay.ports["Q01.S"].net == "V00"
    assert (lay.ports["Q11.N"].x, lay.ports["Q11.N"].y) == (pytest.approx(1383), pytest.approx(1383 + 267))

    (cell,) = gdstk.read_gds(str(build_gds(lay, m, tmp_path / "c.gds"))).top_level()
    metal = [p for p in cell.polygons if p.layer == 1]
    jj = [p for p in cell.polygons if p.layer == 20]
    assert len(metal) == 18 + 12 * 4 and len(jj) == 21
    half = 195 ** 2 * math.acos(35 / 195) - 35 * math.sqrt(195 ** 2 - 35 ** 2)   # 圆缺闭式: 弦距心 35
    def n_with_area(target, rel):
        return sum(abs(p.area() - target) <= rel * target for p in metal)
    assert n_with_area(half, 1e-3) == 18                                    # 圆弧采样 ≲0.1%
    assert n_with_area(378 * 125 + 378 * 175 / 2, 1e-6) == 12               # 五边形: 直边逐字
    assert n_with_area(30 * (1383 - 2 * 267), 1e-6) == 12                   # 条: 30 × 849
    assert n_with_area(40 * (2 * math.radians(20)) * 227 + 20 * 30, 2e-2) == 24   # 爪: 弧 (中心线半径 227) + 颈外段
    pents = [p.bounding_box() for p in metal if abs(p.area() - 80325) < 50]
    P = 1383
    horiz = [b for b in pents if b[1][0] - b[0][0] == pytest.approx(378)]      # 底沿 x → 横向耦合器
    vert = [b for b in pents if b[1][1] - b[0][1] == pytest.approx(378)]
    assert len(horiz) == 6 and len(vert) == 6
    for (x0, y0), (x1, y1) in horiz:          # 条 +y 侧 (底 y = 15 + 75), 中心距东侧比特 540
        assert y0 % P == pytest.approx(90) and y1 - y0 == pytest.approx(300)
        assert ((x0 + x1) / 2) % P == pytest.approx(P - 540)
    for (x0, y0), (x1, y1) in vert:           # mirror: x → 条 +x 侧, 中心距上方比特 540
        assert x0 % P == pytest.approx(90) and x1 - x0 == pytest.approx(300)
        assert ((y0 + y1) / 2) % P == pytest.approx(P - 540)

def test_chen_2025_qcq_block_is_si_isolated_qcq(tmp_path):
    """契约「Chen 2025 模板」: extract.blocks 的每块 = SI §D 孤立 QCQ 口径 (6 terminal: 两比特四半盘 + 条 + 板); 块网格标签
    = 这 6 个 component, 载片地 = 5 µm 盒顶 (Palace config Ground 只有 outer)。"""
    from quantum_dsl import build_mesh, compile_layout, load_meta
    from quantum_dsl.palace import palace_config
    m = load_meta(META)
    assert m.airbox["top_um"] == 5 and len(m.extract["blocks"]) == 12
    blk = m.extract["blocks"][0]
    lay = compile_layout(m)
    mesh = build_mesh(lay.for_block(blk["components"]), dataclasses.replace(m, mesh=COARSE), tmp_path / "b.msh")
    assert mesh.labels == tuple(sorted(blk["components"])) == ("H00", "H00_pent", "Q00_a", "Q00_b", "Q10_a", "Q10_b")
    cfg = palace_config(mesh, m, tmp_path / "b.json")
    assert cfg["Boundaries"]["Ground"]["Attributes"] == [mesh.boundary_groups["outer"]]
    assert len(cfg["Boundaries"]["Terminal"]) == 6 and cfg["Solver"]["Order"] == 2


def test_chen_2025_hand_written_bars_equal_template_route(tmp_path):
    """chen_2025_3x3_hand: 12 个 bar_coupler 模板步骤换成一步手写 .geo (端口变量起画 + ``connect:`` 认领爪, 结写在 meta),
    与模板路线的 Physical 名、GDS 多边形 (1 nm 取整) 与合并后的 circuit_model.qubits 逐项相同 —— 几何完全不变, 只改表述。"""
    import gdstk

    from quantum_dsl import build_gds, compile_layout, load_geo, load_meta
    from quantum_dsl.build import _merge_qubits

    def run(meta):
        m = load_meta(meta)
        lay = compile_layout(m)
        names = {p.name for p in load_geo(lay).physicals}
        (cell,) = gdstk.read_gds(str(build_gds(lay, m, tmp_path / (meta.stem + ".gds")))).top_level()
        polys = sorted((p.layer, tuple(sorted((round(x, 3), round(y, 3)) for x, y in p.points)))
                       for p in cell.polygons)
        qubits = sorted(_merge_qubits(list(m.circuit_model.get("qubits") or []), lay.qubits),
                        key=lambda q: q["name"])
        return names, polys, qubits, lay

    tpl, hand = run(META), run(EXAMPLES / "chen_2025_3x3_hand.meta.yaml")
    assert hand[0] == tpl[0] and len(tpl[0]) == 87
    assert hand[1] == tpl[1] and len(tpl[1]) == 87
    assert hand[2] == tpl[2] and len(tpl[2]) == 21 and len(hand[3].qubits) == 9      # 12 条耦合器结来自 meta
    assert hand[3].used == tpl[3].used and len(hand[3].used) == 24
    assert {"chen_2025_3x3_bars.geo", "chen_2025_3x3_bar_macros.geo"} <= {p.name for p in hand[3].inputs}


def test_chen_2025_cross_is_one_four_coordinated_qubit_solved_whole(tmp_path):
    """契约「Chen 2025 模板」: 十字例子 = 中心 Q11 四爪全开 + 四臂比特各一只朝中心的爪 + 4 耦合器 → 18 导体 / 9 浮动结, 整片一次解 (无 extract.blocks)。
    中心比特的 C_Σ 是真晶格口径 (↔ Table SI 实测 α), 臂比特只有一只爪 = SI §D 孤立 QCQ 的比特侧口径; 同一张网格作差 = 周边结构效应。"""
    import gdstk

    from quantum_dsl import build_gds, compile_layout, load_geo, load_meta
    m = load_meta(EXAMPLES / "chen_2025_cross.meta.yaml")
    assert not (m.extract or {}).get("blocks") and m.airbox["top_um"] == 5
    lay = compile_layout(m)
    comps = {p.component for p in load_geo(lay).physicals if p.role == "metal"}
    assert len(comps) == 18 and len(lay.qubits) == 9 and {c for q in lay.qubits for c in q["islands"]} == comps
    assert set(lay.ports) == {"Q11.E", "Q11.N", "Q11.W", "Q11.S", "Q01.E", "Q21.W", "Q10.N", "Q12.S"} == set(lay.used)
    (cell,) = gdstk.read_gds(str(build_gds(lay, m, tmp_path / "x.gds"))).top_level()
    metal = [p for p in cell.polygons if p.layer == 1]
    assert len(metal) == 10 + 4 * 2 + 8 and len([p for p in cell.polygons if p.layer == 20]) == 9
    claw = 40 * (2 * math.radians(20)) * 227 + 20 * 30
    claws = [p for p in metal if abs(p.area() - claw) <= 2e-2 * claw]
    assert len(claws) == 8
    centres = {"Q11": (1383, 1383), "Q01": (0, 1383), "Q21": (2766, 1383), "Q10": (1383, 0), "Q12": (1383, 2766)}
    def n_claws(cx, cy):          # 爪 bbox 中心离盘心 ≈ (207 + 267) / 2 = 237 < 300
        return sum(math.hypot((b[0][0] + b[1][0]) / 2 - cx, (b[0][1] + b[1][1]) / 2 - cy) < 300
                   for b in (p.bounding_box() for p in claws))
    assert n_claws(*centres["Q11"]) == 4 and all(n_claws(*centres[q]) == 1 for q in ("Q01", "Q21", "Q10", "Q12"))
