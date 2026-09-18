# -*- coding: utf-8 -*-
"""自动布线 (契约「自动布线」): ``route.plan_cpw`` (Dubins CSC 四型 + 定长蛇形 + 矩形区域校验, 纯 math) 与
``lib/cpw_route`` 模板 (``planner: cpw``: 两口不必正对, 位姿恒等, 原语按列表变量注入 .geo)。
设计稿 docs/design/auto-route.md。"""
from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from conftest import EXAMPLES
from test_layout import LIB, _meta, _write

DEMO = EXAMPLES / "cpw_route_demo.meta.yaml"
REGION = [180, -760, 1000, 100]          # 与 cpw_route_demo.layout.yaml 里的 region 相同


def _ends(p):
    """原语的 (起点, 起向, 终点, 终向)。"""
    if p[0] == "line":
        h = math.atan2(p[4] - p[2], p[3] - p[1])
        return (p[1], p[2]), h, (p[3], p[4]), h
    _, cx, cy, R, a0, a1 = p
    s = 1 if a1 > a0 else -1
    return ((cx + R * math.cos(a0), cy + R * math.sin(a0)), a0 + s * math.pi / 2,
            (cx + R * math.cos(a1), cy + R * math.sin(a1)), a1 + s * math.pi / 2)


def _assert_g1(prims, start, end):
    """相邻段首尾点重合、切向连续; 整条路从 start 位姿出发、以 end 位姿驶入; 每段弧 ≤ π/2。"""
    def same_dir(u, v):
        return abs(math.sin(u - v)) < 1e-9 and math.cos(u - v) > 0
    p0, h0, _, _ = _ends(prims[0])
    _, _, p1, h1 = _ends(prims[-1])
    assert p0 == pytest.approx(start[:2], abs=1e-9) and same_dir(h0, start[2])
    assert p1 == pytest.approx(end[:2], abs=1e-9) and same_dir(h1, end[2])
    for a, b in zip(prims, prims[1:]):
        _, _, pa, ha = _ends(a)
        pb, hb, _, _ = _ends(b)
        assert pa == pytest.approx(pb, abs=1e-9) and same_dir(ha, hb)
    for p in prims:
        if p[0] == "arc":
            assert abs(p[5] - p[4]) <= math.pi / 2 + 1e-12 and p[3] > 0


# ---------------------------------------------------------------- 纯规划器
def test_plan_cpw_dubins_four_types_g1_and_bookkeeping():
    """契约「自动布线」: 四型 CSC 都会被选中 (首弧 / 末弧转向的四种组合); 每条路 G1 连续、端点位姿精确、弧段 ≤ π/2;
    定长时记账长度 == 目标 (相对 1e-12), 蛇形侧向按区域选; 最短路 (无 length) 长度 = R·Σ|Δa| + S。"""
    from quantum_dsl import QuantumDslError
    from quantum_dsl.route import path_length, plan_cpw
    R = 40.0
    seen = set()
    poses = [((0, 0, 0), (300, 300, math.pi / 2)), ((0, 0, 0), (300, -300, -math.pi / 2)),
             ((0, 0, 0), (200, 50, 0)), ((0, 0, 0), (200, -50, 0)),
             ((0, 0, 0), (-300, 300, math.pi)), ((0, 0, math.pi / 3), (120, -400, -math.pi / 2)),
             ((10, 5, 0.3), (600, 400, 2.5))]
    for start, end in poses:
        prims = plan_cpw(start, end, R)
        _assert_g1(prims, start, end)
        arcs = [p for p in prims if p[0] == "arc"]
        seen.add(("L" if arcs[0][5] > arcs[0][4] else "R", "L" if arcs[-1][5] > arcs[-1][4] else "R"))
        # 最短 CSC 不会比「两口直线距离」短, 也不会比「先原地转 ≤ 2π 再直走再转」长
        assert math.hypot(end[0] - start[0], end[1] - start[1]) <= path_length(prims) + 1e-9
        # 定长: 目标 = 最短路 + 1500, 显式 2 腿, 无区域 → 记账闭合
        L = path_length(prims) + 1500.0
        m = plan_cpw(start, end, R, length=L, n_legs=2)
        _assert_g1(m, start, end)
        assert path_length(m) == pytest.approx(L, rel=1e-12)
    assert seen == {("L", "L"), ("L", "R"), ("R", "L"), ("R", "R")}

    # 蛇形侧向: 区域只在轴的一侧留出空间 → 自动选那一侧 (n_legs: 2 单侧鼓包)
    start, end = (0, 0, 0), (600, 0, 0)
    up = plan_cpw(start, end, R, length=1200, n_legs=2, region=[-10, -10, 610, 1000])
    dn = plan_cpw(start, end, R, length=1200, n_legs=2, region=[-10, -1000, 610, 10])
    assert max(y for p in up if p[0] == "line" for y in (p[2], p[4])) > R
    assert min(y for p in dn if p[0] == "line" for y in (p[2], p[4])) < -R
    # 自动腿数 = 能装进区域的最小 n; 区域越窄腿越多
    wide = plan_cpw(start, end, R, length=2400, region=[-10, -400, 610, 400])
    narrow = plan_cpw(start, end, R, length=2400, region=[-10, -200, 610, 200])   # 蛇形外沿 = amp + R
    assert sum(p[0] == "line" for p in narrow) > sum(p[0] == "line" for p in wide)
    assert path_length(narrow) == pytest.approx(2400, rel=1e-12)

    # raise, 不静默: 出界 (报段号与超出量) / 目标短于最短路 / 振幅装不下 / 腿太多 / 自动腿数没区域 / 非法区域
    with pytest.raises(QuantumDslError, match=r"leaves the region by"):
        plan_cpw(start, end, R, length=2400, n_legs=2, region=[-10, -100, 610, 100])
    with pytest.raises(QuantumDslError, match="shorter than the shortest"):
        plan_cpw(start, end, R, length=500, n_legs=2)
    with pytest.raises(QuantumDslError, match="amplitude"):
        plan_cpw(start, end, R, length=700, n_legs=6)
    with pytest.raises(QuantumDslError, match="fewer legs"):
        plan_cpw(start, end, R, length=3000, n_legs=20)
    with pytest.raises(QuantumDslError, match="needs a region"):
        plan_cpw(start, end, R, length=2400)
    with pytest.raises(QuantumDslError, match="region must be"):
        plan_cpw(start, end, R, region=[0, 0, -1, 1])
    with pytest.raises(QuantumDslError, match="R must be"):
        plan_cpw(start, end, 0)


# ---------------------------------------------------------------- 退化一致性 + 版图纪律
def _compile(tmp_path, steps: str, ground="none"):
    from quantum_dsl import compile_layout, load_meta
    layers = {"m": {"kind": "conductor", "gds": [1, 0]}}
    doc = {"schema": "quantum-dsl/layout/1", "templates": [".", LIB.as_posix()],
           "steps": yaml.safe_load(steps), "ground": yaml.safe_load(ground)}
    (tmp_path / "chip.layout.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    m = load_meta(_meta(tmp_path, "chip.layout.yaml", layers))
    return compile_layout(m), m


def _pair(tmp_path, w=10):
    """模板 t: 岛 (0..w) + 外挂面 (w+5..2w+5) + 端口 E 在外挂面外沿朝 +x。两实例相对 → 两外挂端, net = 步骤名。"""
    _write(tmp_path / "t.yaml", yaml.safe_dump({
        "schema": "quantum-dsl/template/1", "params": {"w": 10}, "layers": {"metal": "conductor"},
        "islands": {"i": {"faces": "f()", "layer": "metal"}},
        "external": {"E": {"faces": "g()", "layer": "metal"}}, "ports": {"E": "port(0)"}}))
    _write(tmp_path / "t.geo", """
        SetFactory("OpenCASCADE");
        s = news; Rectangle(s) = {0, -w/2, 0, w, w};  f() = {s};
        e = news; Rectangle(e) = {w + 5, -w/2, 0, w, w};  g() = {e};
        port_x() = {2*w + 5};  port_y() = {0};  port_a() = {0};  port_w() = {w};
        """)
    return ("- {template: t, name: A, layers: {metal: m}}\n"
            f"- {{template: t, name: B, layers: {{metal: m}}, at: [500, 0], rot: 180, params: {{w: {w}}}}}\n")


def _gds_shapes(lay, m, out):
    import gdstk

    from quantum_dsl import build_gds
    (cell,) = gdstk.read_gds(str(build_gds(lay, m, out))).top_level()
    return sorted((tuple(round(v, 6) for pt in p.bounding_box() for v in pt), round(p.area(), 6))
                  for p in cell.polygons)


def test_cpw_route_degenerates_to_cpw_meander_when_ports_face(tmp_path):
    """契约「自动布线」 退化一致性 (回归锚): 两口正对共线 + 同 R / n_legs / L 时, cpw_route (Dubins 退化为零弧 + 直段 → 蛇形)
    与 cpw_meander (LIB_CPW_MEANDER 闭式) 画出的长度记账相等 (≤1e-9 相对), GDS 多边形 (包围盒 + 面积) 逐个相同。"""
    pair = _pair(tmp_path)
    route = ("- {template: %s, name: C, from: A.E, to: B.E, params: {R: 25, n_legs: 4, gap: 6}, "
             "length: {mode: fixed, L: 800um}}\n")
    lay_m, m = _compile(tmp_path, pair + route % "cpw_meander")
    shapes_m = _gds_shapes(lay_m, m, tmp_path / "m.gds")
    lay_r, m = _compile(tmp_path, pair + route % "cpw_route")
    shapes_r = _gds_shapes(lay_r, m, tmp_path / "r.gds")
    assert lay_r.subsystems[0]["length_drawn_um"] == pytest.approx(lay_m.subsystems[0]["length_drawn_um"], rel=1e-9)
    assert lay_r.subsystems[0]["length_drawn_um"] == pytest.approx(800.0)
    assert lay_r.subsystems[0]["route_primitives"] == 14           # 引入 + 90° + 4 腿 + 3×2 半弯 + 90° + 引出
    assert shapes_r == pytest.approx(shapes_m, rel=1e-9, abs=1e-6)
    assert lay_r.ports["A.E"].net == "C" and lay_r.ports["B.E"].net == "C"


def test_cpw_route_discipline_raises(tmp_path):
    """契约「自动布线」 纪律: 非 planner 模板写 region: raise; planner 模板写 mirror: raise; 两口宽不同 raise (taper 未实现);
    n_legs: 0 (自动) 没给 region raise; 模板 planner: 取值 / kind / 必需参数不对 raise; 规划失败的信息带步骤名。"""
    from quantum_dsl import QuantumDslError
    pair = _pair(tmp_path)
    L = "length: {mode: fixed, L: 800um}"
    with pytest.raises(QuantumDslError, match="only for planner templates"):
        _compile(tmp_path, pair + f"- {{template: cpw_meander, name: C, from: A.E, to: B.E, {L}, region: [0, -100, 500, 100]}}")
    with pytest.raises(QuantumDslError, match="mirror: has no meaning"):
        _compile(tmp_path, pair + f"- {{template: cpw_route, name: C, from: A.E, to: B.E, params: {{n_legs: 4}}, {L}, mirror: x}}")
    with pytest.raises(QuantumDslError, match="widths differ"):
        _compile(tmp_path, _pair(tmp_path, w=20) + f"- {{template: cpw_route, name: C, from: A.E, to: B.E, params: {{n_legs: 4}}, {L}}}")
    with pytest.raises(QuantumDslError, match=r"step #2 C \(cpw_route.yaml\): route: n_legs: 0 \(auto\) needs a region"):
        _compile(tmp_path, pair + f"- {{template: cpw_route, name: C, from: A.E, to: B.E, {L}}}")
    # 不正对 + 非 planner 模板: 仍 raise, 提示改用 cpw_route
    with pytest.raises(QuantumDslError, match="face each other.*cpw_route"):
        _compile(tmp_path, pair.replace("rot: 180", "rot: 90") + f"- {{template: cpw_meander, name: C, from: A.E, to: B.E, {L}}}")
    # 同一对不正对端口, cpw_route 通过 (最短路, 无 length)
    lay, _ = _compile(tmp_path, pair.replace("rot: 180", "rot: 90") + "- {template: cpw_route, name: C, from: A.E, to: B.E}")
    assert lay.used == {"A.E", "B.E"} and lay.subsystems == []
    # 模板侧: planner 只认 cpw、须 kind: connect、须声明 R / n_legs / gap
    base = yaml.safe_load((LIB / "cpw_route.yaml").read_text(encoding="utf-8"))
    for over, msg in (({"planner": "astar"}, "only planner is 'cpw'"), ({"kind": None}, "needs kind: connect"),
                      ({"params": {"R": 40, "gap": 6}}, r"missing \['n_legs'\]")):
        _write(tmp_path / "bad.yaml", yaml.safe_dump({**base, **over}))
        (tmp_path / "bad.geo").write_text((LIB / "cpw_route.geo").read_text(encoding="utf-8").replace(
            'Include "cpw_macros.geo";', f'Include "{(LIB / "cpw_macros.geo").as_posix()}";'), encoding="utf-8")
        with pytest.raises(QuantumDslError, match=msg):
            _compile(tmp_path, pair + "- {template: bad, name: C, from: A.E, to: B.E}")


# ---------------------------------------------------------------- 版图集成: demo
def test_cpw_route_demo_builds_inside_region(tmp_path):
    """契约「自动布线」 版图集成: cpw_route_demo (xmon 读出桨朝 +x → pad 北口朝 +y, 错位数百 µm, fixed 3000 µm, n_legs 自动)
    compile_layout + build(solve=False) 通过; subsystems 记 length_drawn_um == 3000 − Σleq 与 route_primitives; 两端口 used;
    GDS 里读出腔 net (桨 + CPW + 焊盘并成一块) 的多边形整体落在 region 内; 网格标签 = 两个 net。"""
    import gdstk

    from quantum_dsl import build, load_meta
    m = load_meta(DEMO)
    r = build(m, tmp_path / "demo", solve=False)
    lay = r["layout"]
    (sub,) = lay.subsystems
    leq = lay.ports["Q1.RO"].leq + lay.ports["F0.N"].leq
    assert sub["name"] == "F0" and sub["route"] == "R1" and sub["mode"] == "fixed"
    assert sub["length_drawn_um"] == pytest.approx(3000.0 - leq) and sub["route_primitives"] >= 3
    assert lay.used == {"Q1.RO", "F0.N"} and lay.ports["Q1.RO"].net == "F0"
    assert not (abs(math.sin(lay.ports["Q1.RO"].a - lay.ports["F0.N"].a - math.pi)) < 1e-9)   # 两口确实不正对
    (cell,) = gdstk.read_gds(str(r["gds"])).top_level()
    polys = [p for p in cell.polygons if p.layer == 1]                 # GDS 按 Physical 组各出一块: 地 / 岛 / 桨 / CPW / 焊盘
    ground = max(polys, key=lambda p: p.area())
    f0 = [p for p in polys if p is not ground and not p.contain((0.0, 0.0))]
    assert len(f0) == 3 and any(p.contain((900.0, -700.0)) for p in f0)
    for p in f0:
        (x0, y0), (x1, y1) = p.bounding_box()
        assert REGION[0] <= x0 and REGION[1] <= y0 and x1 <= REGION[2] and y1 <= REGION[3]
    assert max(p.area() for p in f0) == pytest.approx(10.0 * 3000.0, rel=2e-4)                # 中心导体面积 = w·L (弧采样 ≲1e-4)
    assert Path(r["mesh"]).exists() and Path(r["gds_png"]).exists()
    # region 太小 → 规划失败, 报段号与建议, 不静默
    from quantum_dsl import QuantumDslError, compile_layout
    doc = yaml.safe_load(m.layout_path.read_text(encoding="utf-8"))
    doc["templates"] = [LIB.as_posix()]
    doc["steps"][2]["region"] = [180, -760, 890, 100]        # x1 挡住 F0.N 口本身
    _write(tmp_path / "tight.layout.yaml", yaml.safe_dump(doc))
    meta_txt = DEMO.read_text(encoding="utf-8").replace("layout: cpw_route_demo.layout.yaml", "layout: tight.layout.yaml")
    with pytest.raises(QuantumDslError, match=r"(?s)R1 .*no feasible CPW path.*leaves the region"):
        compile_layout(load_meta(_write(tmp_path / "tight.meta.yaml", meta_txt)))
