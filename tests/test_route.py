# -*- coding: utf-8 -*-
"""自动布线 v2 (契约「自动布线」): ``route.plan_cpw`` (曼哈顿框架 / Dubins 骨架 + 逐弯精确余量的蛇形填充、多段分摊 + 矩形并集区域 + 自身净距, 纯 math) 与
``lib/cpw_route`` 模板 (``planner: cpw``: 两口不必正对, 位姿恒等, 原语按列表变量注入 .geo)。设计稿 docs/design/auto-route.md。"""
from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from conftest import EXAMPLES
from test_layout import LIB, _meta, _write

DEMO = EXAMPLES / "cpw_route_demo.meta.yaml"
R, W = 40.0, 22.0                                     # demo 的弯半径与 CPW 总宽 (10 + 2 × 6)
A_START, A_END = (210, 0, 0.0), (900, -690, -math.pi / 2)   # demo 一对桨: Q1.RO 朝 +x 出发, 驶入朝 +y 的 Q2.RO
REGION = [180, -720, 1000, 100]                      # demo R1 的 region
REGION_B = [[180, -720, 700, 100], [180, -720, 1000, -300]]   # demo R2 的 region (右上角挖掉), 平移前
NOTCH = [700, -300, 1000, 100]                       # REGION_B 挖掉的角


def _ends(p):
    """原语的 (起点, 起向, 终点, 终向)。"""
    if p[0] == "line":
        h = math.atan2(p[4] - p[2], p[3] - p[1])
        return (p[1], p[2]), h, (p[3], p[4]), h
    _, cx, cy, r, a0, a1 = p
    s = 1 if a1 > a0 else -1
    return ((cx + r * math.cos(a0), cy + r * math.sin(a0)), a0 + s * math.pi / 2,
            (cx + r * math.cos(a1), cy + r * math.sin(a1)), a1 + s * math.pi / 2)


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


def _dense(p, step=0.2):
    """原语密采 (直段两端 / 弧每 step µm 一点)。"""
    if p[0] == "line":
        return [(p[1], p[2]), (p[3], p[4])]
    _, cx, cy, r, a0, a1 = p
    n = max(2, int(abs(a1 - a0) * r / step))
    return [(cx + r * math.cos(a0 + (a1 - a0) * k / n), cy + r * math.sin(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]


def _strip(prims, half):
    """中心线密采后按半宽 buffer (平头) —— 独立于 route.py 的几何 oracle (shapely)。"""
    from shapely.geometry import LineString
    return LineString([q for p in prims for q in _dense(p)]).buffer(half, cap_style="flat")


def _union(rects):
    from shapely.geometry import box
    from shapely.ops import unary_union
    rects = rects if isinstance(rects[0], (list, tuple)) else [rects]
    return unary_union([box(*r) for r in rects])


def _turns(prims):
    """转弯数 = 弧段数, 相邻同圆同向的拆段算一个。"""
    n = 0
    for a, b in zip([None] + list(prims), prims):
        if b[0] == "arc" and not (a is not None and a[0] == "arc" and a[1:4] == b[1:4] and abs(a[5] - b[4]) < 1e-9):
            n += 1
    return n


# ---------------------------------------------------------------- 纯规划器: 曼哈顿框架 (默认)
def test_plan_cpw_manhattan_default_L_with_fitted_legs():
    """契约「自动布线」 R1–R3: 默认 axis 0 → 骨架横平竖直, demo 一对桨的最短骨架是 L (一个 90° 圆角); 定长时蛇形放在骨架直段上, 腿垂直于轴,
    每个弯按该处余量独立外推 → 上侧 (余量 ≈ 50) 腿短、下侧 (≈ 670) 腿长, 全部含缝宽落在 region 内 (shapely 独立 oracle); G1、记账 == 目标;
    腿数自动取最小可行 (== 显式 n_legs 4 的结果); lead 60 → 首末原语是沿端口法向长 60 的直段。"""
    from quantum_dsl.route import path_length, plan_cpw
    kw = dict(R=R, width=W, lead=60)
    short = plan_cpw(A_START, A_END, region=REGION, **kw)
    assert [p[0] for p in short] == ["line", "line", "arc", "line", "line"] and _turns(short) == 1     # 引出 + 横臂 + 圆角 + 竖臂 + 引出
    _assert_g1(short, A_START, A_END)
    prims = plan_cpw(A_START, A_END, length=3000, region=REGION, **kw)
    _assert_g1(prims, A_START, A_END)
    assert path_length(prims) == pytest.approx(3000, rel=1e-12)
    for p in prims:
        if p[0] == "line":
            assert min(abs(p[3] - p[1]), abs(p[4] - p[2])) < 1e-9                  # 横平竖直
        else:
            assert abs(abs(p[5] - p[4]) - math.pi / 2) < 1e-9                        # 全是 90° 段
    assert path_length(prims[:1]) == pytest.approx(60) and path_length(prims[-1:]) == pytest.approx(60)
    assert _strip(prims, W / 2).within(_union(REGION).buffer(1e-3))
    ys = [y for p in prims for _, y in _dense(p)]
    assert 0 < max(ys) < 100 - W / 2 and min(ys) < -300                             # 上侧小鼓包, 下侧长腿
    legs = sorted({round(abs(p[4] - p[2]), 6) for p in prims if p[0] == "line" and abs(p[3] - p[1]) < 1e-9} - {60.0})
    assert len(legs) >= 3                                                           # 腿不等长 (首末腿 / 中间腿 / 竖臂)
    assert plan_cpw(A_START, A_END, length=3000, region=REGION, n_legs=4, **kw) == prims
    with pytest.raises(Exception, match="fewer legs"):
        plan_cpw(A_START, A_END, length=3000, region=REGION, n_legs=20, **kw)


def test_plan_cpw_union_region_detours_and_gap_check():
    """契约「自动布线」 R5: region 是矩形并集; 挖掉 L 拐角所在的角 → L 淘汰, 最短骨架变 3 转弯绕过缺口 (原语与缺口不交, 落在并集内);
    定长同样成立; 两个不相接的矩形 (中间有缝) → 必须穿缝 → raise 报「cuts into the gap」(直段两端都在缝外, 取样点查不出, 精确距离查得出);
    并集里混进非 4 数 raise。"""
    from quantum_dsl import QuantumDslError
    from quantum_dsl.route import path_length, plan_cpw
    kw = dict(R=R, width=W, lead=60)
    notch = _union(NOTCH)
    short = plan_cpw(A_START, A_END, region=REGION_B, **kw)
    assert _turns(short) == 3 and not _strip(short, W / 2).intersects(notch)
    assert _strip(short, W / 2).within(_union(REGION_B).buffer(1e-3))
    prims = plan_cpw(A_START, A_END, length=3000, region=REGION_B, **kw)
    _assert_g1(prims, A_START, A_END)
    assert path_length(prims) == pytest.approx(3000, rel=1e-12)
    assert not _strip(prims, W / 2).intersects(notch) and _strip(prims, W / 2).within(_union(REGION_B).buffer(1e-3))
    with pytest.raises(QuantumDslError, match=r"cuts into the gap"):
        plan_cpw(A_START, A_END, region=[[180, -720, 700, 100], [750, -720, 1000, 100]], **kw)
    with pytest.raises(QuantumDslError, match="region must be"):
        plan_cpw(A_START, A_END, region=[[180, -720, 700, 100], [750, -720, 1000]], **kw)


def test_plan_cpw_rotated_frame_self_clearance_and_axis_errors():
    """契约「自动布线」 R4 + 自身净距: axis: 45 → 全部直段方向 ∈ {45°, 135°}; U 形 (两口同向、目标在后方) 的蛇形腿与引出 / 另一臂
    保持 ≥ 2R 净距 (密采两两距离, 只看相隔 ≥ 3 段的原语); axis 非数值非 free raise。"""
    from quantum_dsl import QuantumDslError
    from quantum_dsl.route import path_length, plan_cpw
    s45, e45 = (0, 0, math.pi / 4), (600, 600, math.pi / 4)
    prims = plan_cpw(s45, e45, R, width=W, length=1800, region=[-100, -100, 800, 800], axis=45)
    _assert_g1(prims, s45, e45)
    assert path_length(prims) == pytest.approx(1800, rel=1e-12)
    assert {round(math.degrees(math.atan2(p[4] - p[2], p[3] - p[1])) % 180, 6) for p in prims if p[0] == "line"} <= {45.0, 135.0}
    su, eu = (0, 0, 0.0), (-300, 300, math.pi)
    prims = plan_cpw(su, eu, R, width=W, lead=40, length=1400, region=[-400, -100, 300, 500])
    _assert_g1(prims, su, eu)
    pts = [_dense(p, 0.5) for p in prims]
    for i in (0, len(prims) - 1):                                                    # 两段引出
        dmin = min(math.hypot(a[0] - b[0], a[1] - b[1]) for j in range(len(prims)) if abs(j - i) >= 3
                   for a in pts[i] for b in pts[j])
        assert dmin >= 2 * R - 1e-6
    with pytest.raises(QuantumDslError, match="axis must be"):
        plan_cpw(su, eu, R, axis="diag")
    with pytest.raises(QuantumDslError, match="axis must be"):
        plan_cpw(su, eu, R, axis=float("nan"))


def _min_clearance(prims, R):
    """独立 oracle: 沿路间隔 (前者终点到后者起点的路长) ≥ πR 的任意两段原语, 中心线最小距离 (shapely, 密采 0.2 µm)。"""
    from shapely.geometry import LineString
    from quantum_dsl.route import path_length
    geoms = [LineString(_dense(p)) for p in prims]
    cum = [0.0]
    for p in prims:
        cum.append(cum[-1] + path_length([p]))
    return min((geoms[i].distance(geoms[j]) for i in range(len(prims)) for j in range(i + 1, len(prims))
                if cum[j] - cum[i + 1] >= math.pi * R - 1e-6), default=math.inf)


def test_plan_cpw_splits_meander_across_runs_with_clearance():
    """契约「自动布线」 多段分摊: L 形走廊 (两矩形拼成, 半宽 130 → 每条臂一块蛇形最多补 ≈ +1190 µm), 目标多出 ≈ +1820 → 蛇形分到两条臂
    (两臂都有腿), 记账 == 目标, 含缝宽落在并集内; 拐角处两块的腿互相垂直但不交叉 —— 沿路间隔 ≥ πR 的任意两段原语中心线距离 ≥ 2R
    (shapely 独立 oracle, 恰 = 2R 是蛇形腿距); 显式 n_legs 是**总腿数** (12 = 两块之和); 单段装得下时仍只放一块 (块数优先)。"""
    from quantum_dsl.route import path_length, plan_cpw
    kw = dict(start=(0, 0, 0.0), end=(700, -700, -math.pi / 2), R=R, width=W, lead=40,
              region=[[-30, -130, 760, 130], [570, -760, 830, 130]])

    def legs(prims):
        arm1 = [p for p in prims if p[0] == "line" and abs(p[3] - p[1]) < 1e-9 and p[1] < 690]     # 横臂上的竖腿
        arm2 = [p for p in prims if p[0] == "line" and abs(p[4] - p[2]) < 1e-9 and p[2] < -140]    # 竖臂上的横腿
        return arm1, arm2
    prims = plan_cpw(**kw, length=3200)
    _assert_g1(prims, kw["start"], kw["end"])
    assert path_length(prims) == pytest.approx(3200, rel=1e-12)
    a1, a2 = legs(prims)
    assert len(a1) >= 2 and len(a2) >= 2
    assert _strip(prims, W / 2).within(_union(kw["region"]).buffer(1e-3))
    assert _min_clearance(prims, R) >= 2 * R - 1e-3
    a1, a2 = legs(plan_cpw(**kw, length=3200, n_legs=12))
    assert len(a1) + len(a2) == 12 and min(len(a1), len(a2)) >= 2
    a1, a2 = legs(plan_cpw(**kw, length=2300))
    assert (len(a1) == 0) != (len(a2) == 0)                                                        # 只一块


def test_plan_cpw_legs_follow_the_region_profile_exactly():
    """契约「自动布线」 R2 逐弯余量: 正对两口, 区域 = 窄走廊 (半高 100) + 中段宽块 (半高 400):
    自动腿数时块整个落进宽块 (腿 > 500); 显式 8 腿时块横跨三段 → 窄段腿 ≤ 2 × 89、宽段腿 > 300 (「2×2 + 2×4 + 2×2 → 中间长腿」);
    宽块只在轴一侧时上长 (> 300) 下短 (≥ −89); 弯的肩部跨过台阶角: 余量用「角点 → 加厚半圆」的对偶射线精确算 —— 3 腿最多补 +841.16,
    +840 通过且含缝宽在并集内, +870 raise (只用取样点会按 +913 放行, 肩部出界 ≈ 24 µm)。"""
    from quantum_dsl import QuantumDslError
    from quantum_dsl.route import plan_cpw
    kw = dict(start=(0, 0, 0.0), end=(800, 0, 0.0), R=R, width=W, lead=40)
    step = [[-30, -100, 830, 100], [250, -400, 550, 400]]

    def vlegs(prims):
        return [(p[1], abs(p[4] - p[2])) for p in prims if p[0] == "line" and abs(p[3] - p[1]) < 1e-9]
    prims = plan_cpw(**kw, length=2600, region=step)
    assert _strip(prims, W / 2).within(_union(step).buffer(1e-3)) and _min_clearance(prims, R) >= 2 * R - 1e-3
    assert all(250 < x < 550 and L > 200 for x, L in vlegs(prims)) and max(L for _, L in vlegs(prims)) > 500
    prims = plan_cpw(**kw, length=2600, region=step, n_legs=8)
    assert _strip(prims, W / 2).within(_union(step).buffer(1e-3))
    narrow = [L for x, L in vlegs(prims) if not 250 < x < 550]
    wide = [L for x, L in vlegs(prims) if 250 < x < 550]
    assert narrow and wide and max(narrow) <= 2 * 89 + 1e-6 and max(wide) > 300
    prims = plan_cpw(**kw, length=2400, region=[[-30, -100, 830, 100], [250, -100, 550, 450]])
    ys = [y for p in prims if p[0] == "line" and abs(p[3] - p[1]) < 1e-9 for y in (p[2], p[4])]
    assert max(ys) > 300 and min(ys) >= -89 - 1e-6
    ex = dict(start=(0, 0, 0.0), end=(320, 0, 0.0), R=R, width=W, lead=40, region=[[-30, -90, 350, 90], [100, -400, 300, 400]])
    prims = plan_cpw(**ex, length=320 + 840)
    assert _strip(prims, W / 2).within(_union(ex["region"]).buffer(1e-3))
    with pytest.raises(QuantumDslError, match=r"3 legs reach at most \+841\.1"):
        plan_cpw(**ex, length=320 + 870)


def test_plan_cpw_rejects_paths_that_approach_themselves():
    """契约「自动布线」 自身净距: 两口相距 50 µm 同向 (回头连接的两条引出平行相距 50 < 2R = 80): 每条骨架都被自身净距检查淘汰,
    raise 报「segments #i and #j come within 50 um」; 净距规则对骨架与蛇形一致 (沿路间隔 ≥ πR 的两段 ≥ 2R)。"""
    from quantum_dsl import QuantumDslError
    from quantum_dsl.route import plan_cpw
    with pytest.raises(QuantumDslError, match=r"come within 50 um of each other \(< 2R = 80\)"):
        plan_cpw((0, 0, 0.0), (0, 50, math.pi), R, width=W, lead=40, region=[-300, -200, 400, 300])


def test_plan_cpw_auto_radius_is_the_largest_that_fits():
    """契约「自动布线」 R 自动: auto_radius 在整数区间 [⌈width⌉, min(外框短边, 两口距离)/2] 上二分, 返回最大可行弯半径 —— demo 一对桨 +
    3000 µm 得 70: R = 70 装得下、71 装不下, 且 71 的报错提示「R <= 70 um would fit」; plan_cpw(R="auto") == plan_cpw(R=70);
    无 length 时最短骨架能容最大的 R (外框短边一半 = 410, 一个大圆角); 拼接走廊 (半宽 130) 得 59; 搜索区间为空 / 最小半径也不行 → raise。"""
    from quantum_dsl import QuantumDslError
    from quantum_dsl.route import auto_radius, plan_cpw
    kw = dict(width=W, lead=60, length=3000, region=REGION)
    assert auto_radius(A_START, A_END, **kw) == 70.0
    assert plan_cpw(A_START, A_END, "auto", **kw) == plan_cpw(A_START, A_END, 70, **kw)
    with pytest.raises(QuantumDslError, match=r"R <= 70 um would fit \(R: auto picks it\)"):
        plan_cpw(A_START, A_END, 71, **kw)
    assert auto_radius(A_START, A_END, width=W, lead=60, region=REGION) == 410.0
    corridor = dict(width=W, lead=40, length=3200, region=[[-30, -130, 760, 130], [570, -760, 830, 130]])
    assert auto_radius((0, 0, 0.0), (700, -700, -math.pi / 2), **corridor) == 59.0
    with pytest.raises(QuantumDslError, match="search range is empty"):
        auto_radius((0, 0, 0.0), (30, 0, 0.0), width=W)
    with pytest.raises(QuantumDslError, match=r"even R = 22 um .* fails"):                       # 两口相距 40 < 2 × 22
        auto_radius((0, 0, 0.0), (0, 40, math.pi), width=W, lead=40, region=[-300, -200, 400, 300], R_max=100)


# ---------------------------------------------------------------- 纯规划器: 自由角 (axis: free = v1 的 Dubins)
def test_plan_cpw_free_axis_dubins_four_types_g1_and_bookkeeping():
    """契约「自动布线」 axis: free: 四型 CSC 都会被选中 (首弧 / 末弧转向的四种组合); 每条路 G1 连续、端点位姿精确、弧段 ≤ π/2;
    定长时记账长度 == 目标 (相对 1e-12), 蛇形侧向按区域余量选 (选出的变体同样 G1); 最短路 (无 length) 长度 ≥ 两口直线距离;
    lead > 0 时首末原语是沿端口法向、长 lead 的直段, 弧从其后开始; 区域校验对弧是精确的 (真实包围盒恰好包住 → 过, 任一边再收 1e-3 µm → raise)。"""
    from quantum_dsl import QuantumDslError
    from quantum_dsl.route import path_length, plan_cpw
    F = dict(axis="free")
    seen = set()
    poses = [((0, 0, 0), (300, 300, math.pi / 2)), ((0, 0, 0), (300, -300, -math.pi / 2)),
             ((0, 0, 0), (200, 50, 0)), ((0, 0, 0), (200, -50, 0)),
             ((0, 0, 0), (-300, 300, math.pi)), ((0, 0, math.pi / 3), (120, -400, -math.pi / 2)),
             ((10, 5, 0.3), (600, 400, 2.5))]
    for start, end in poses:
        prims = plan_cpw(start, end, R, **F)
        _assert_g1(prims, start, end)
        arcs = [p for p in prims if p[0] == "arc"]
        seen.add(("L" if arcs[0][5] > arcs[0][4] else "R", "L" if arcs[-1][5] > arcs[-1][4] else "R"))
        assert math.hypot(end[0] - start[0], end[1] - start[1]) <= path_length(prims) + 1e-9
        L = path_length(prims) + 1500.0                                               # 定长: 显式 2 腿, 无区域 → 等腿, 记账闭合
        m = plan_cpw(start, end, R, length=L, n_legs=2, **F)
        _assert_g1(m, start, end)
        assert path_length(m) == pytest.approx(L, rel=1e-12)
    assert seen == {("L", "L"), ("L", "R"), ("R", "L"), ("R", "R")}

    s3, e3 = (10, 5, 0.3), (600, 400, 2.5)
    m = plan_cpw(s3, e3, R, lead=30, **F)
    _assert_g1(m, s3, e3)
    assert [p[0] for p in m[:2]] == ["line", "arc"] and [p[0] for p in m[-2:]] == ["arc", "line"]
    assert path_length(m[:1]) == pytest.approx(30) and path_length(m[-1:]) == pytest.approx(30)
    L = path_length(m) + 900.0
    m = plan_cpw(s3, e3, R, length=L, n_legs=2, lead=30, **F)
    _assert_g1(m, s3, e3)
    assert path_length(m) == pytest.approx(L, rel=1e-12) and path_length(m[:1]) == pytest.approx(30)
    with pytest.raises(QuantumDslError, match="lead must be"):
        plan_cpw(s3, e3, R, lead=-1, **F)

    # 蛇形侧向: 区域只在轴的一侧留出余量 → 弯只能在那一侧 (n_legs: 2 单侧鼓包)
    start, end = (0, 0, 0), (600, 0, 0)
    up = plan_cpw(start, end, R, length=1200, n_legs=2, region=[-10, -10, 610, 1000], **F)
    dn = plan_cpw(start, end, R, length=1200, n_legs=2, region=[-10, -1000, 610, 10], **F)
    assert max(y for p in up if p[0] == "line" for y in (p[2], p[4])) > R
    assert min(y for p in dn if p[0] == "line" for y in (p[2], p[4])) < -R
    _assert_g1(up, start, end)
    _assert_g1(dn, start, end)
    # 自动腿数 = 能装进区域的最小 n; 区域越窄余量越小腿越多
    wide = plan_cpw(start, end, R, length=2400, region=[-10, -400, 610, 400], **F)
    narrow = plan_cpw(start, end, R, length=2400, region=[-10, -200, 610, 200], **F)
    assert sum(p[0] == "line" for p in narrow) > sum(p[0] == "line" for p in wide)
    assert path_length(narrow) == pytest.approx(2400, rel=1e-12)
    _assert_g1(wide, start, end)
    _assert_g1(narrow, start, end)
    assert _strip(narrow, 1e-3).within(_union([-10, -200, 610, 200]).buffer(2e-3))     # 宽 0: 中心线本身在区域内

    # 区域校验精确: 最短路的真实包围盒 (弧按 0.01° 密采) 恰好包住 → 通过; 任一边再收 1e-3 µm → raise (弧顶点不在端点上也抓)
    prims = plan_cpw(s3, e3, R, **F)
    pts = [pt for p in prims if p[0] == "line" for pt in ((p[1], p[2]), (p[3], p[4]))]
    for p in prims:
        if p[0] == "arc":
            _, cx, cy, Ra, a0, a1 = p
            pts += [(cx + Ra * math.cos(a0 + (a1 - a0) * k / 9000), cy + Ra * math.sin(a0 + (a1 - a0) * k / 9000))
                    for k in range(9001)]
    bbox = [min(x for x, _ in pts), min(y for _, y in pts), max(x for x, _ in pts), max(y for _, y in pts)]
    assert plan_cpw(s3, e3, R, region=bbox, **F) == prims
    for i, d in enumerate((1e-3, 1e-3, -1e-3, -1e-3)):
        tight = list(bbox)
        tight[i] += d
        with pytest.raises(QuantumDslError, match=r"leaves the region by 0\.00[01]"):
            plan_cpw(s3, e3, R, region=tight, **F)

    # raise, 不静默: 余量不够目标 / 目标短于骨架 / 多出的不够最小蛇形 / 腿太多 / 自动腿数没区域 / 非法区域 / 非法 R / 弯内径 ≤ 0
    with pytest.raises(QuantumDslError, match=r"reach at most"):
        plan_cpw(start, end, R, length=2400, n_legs=2, region=[-10, -100, 610, 100], **F)
    with pytest.raises(QuantumDslError, match="shorter than"):
        plan_cpw(start, end, R, length=500, n_legs=2, **F)
    with pytest.raises(QuantumDslError, match="add at least"):
        plan_cpw(start, end, R, length=700, n_legs=6, **F)
    with pytest.raises(QuantumDslError, match="fewer legs"):
        plan_cpw(start, end, R, length=3000, n_legs=20, **F)
    with pytest.raises(QuantumDslError, match="needs a region"):
        plan_cpw(start, end, R, length=2400, **F)
    with pytest.raises(QuantumDslError, match="region must be"):
        plan_cpw(start, end, R, region=[0, 0, -1, 1], **F)
    with pytest.raises(QuantumDslError, match="R must be"):
        plan_cpw(start, end, 0, **F)
    with pytest.raises(QuantumDslError, match=r"must be >= 0 and < 2\*R"):       # 弯内径 <= 0, 不留给 gmsh 宏去报
        plan_cpw(start, end, 10, width=22, **F)
    with pytest.raises(QuantumDslError, match=r"every leg count 2\.\.S/2R was tried"):   # 自动腿数全失败: hint 不叫人加腿
        plan_cpw(start, end, R, length=2400, region=[-10, -100, 610, 100], **F)


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
    """契约「自动布线」 退化一致性 (回归锚): 两口正对共线 + 同 R / n_legs / L 且 lead: 0、无 region (余量无限 → 等腿, 块居中) 时,
    cpw_route (曼哈顿骨架退化为一条直段 → 蛇形) 与 cpw_meander (LIB_CPW_MEANDER 闭式) 画出的长度记账相等 (≤1e-9 相对),
    GDS 多边形 (包围盒 + 面积) 逐个相同。"""
    pair = _pair(tmp_path)
    route = ("- {template: %s, name: C, from: A.E, to: B.E, params: {R: 25, n_legs: 4, gap: 6%s}, "
             "length: {mode: fixed, L: 800um}}\n")
    lay_m, m = _compile(tmp_path, pair + route % ("cpw_meander", ""))
    shapes_m = _gds_shapes(lay_m, m, tmp_path / "m.gds")
    lay_r, m = _compile(tmp_path, pair + route % ("cpw_route", ", lead: 0"))
    shapes_r = _gds_shapes(lay_r, m, tmp_path / "r.gds")
    assert lay_r.subsystems[0]["length_drawn_um"] == pytest.approx(lay_m.subsystems[0]["length_drawn_um"], rel=1e-9)
    assert lay_r.subsystems[0]["length_drawn_um"] == pytest.approx(800.0)
    assert lay_r.subsystems[0]["route_primitives"] == 14           # 引入 + 90° + 4 腿 + 3×2 半弯 + 90° + 引出
    assert shapes_r == pytest.approx(shapes_m, rel=1e-9, abs=1e-6)
    assert lay_r.ports["A.E"].net == "C" and lay_r.ports["B.E"].net == "C"


def test_cpw_route_discipline_raises(tmp_path):
    """契约「自动布线」 纪律: 非 planner 模板写 region: / axis: / params R: auto raise; planner 模板写 mirror: raise; 两口宽不同 raise (taper 未实现);
    n_legs: 0 (自动) 没给 region raise; 步骤显式给 n_legs 却没 length: raise (不静默忽略); axis 取值非法 raise (带步骤名);
    模板 planner: 取值 / kind / 必需参数不对 raise; 规划失败的信息带步骤名。"""
    from quantum_dsl import QuantumDslError
    pair = _pair(tmp_path)
    L = "length: {mode: fixed, L: 800um}"
    with pytest.raises(QuantumDslError, match="region: is only for planner templates"):
        _compile(tmp_path, pair + f"- {{template: cpw_meander, name: C, from: A.E, to: B.E, {L}, region: [0, -100, 500, 100]}}")
    with pytest.raises(QuantumDslError, match="axis: is only for planner templates"):
        _compile(tmp_path, pair + f"- {{template: cpw_meander, name: C, from: A.E, to: B.E, {L}, axis: 0}}")
    with pytest.raises(QuantumDslError, match="mirror: has no meaning"):
        _compile(tmp_path, pair + f"- {{template: cpw_route, name: C, from: A.E, to: B.E, params: {{n_legs: 4}}, {L}, mirror: x}}")
    with pytest.raises(QuantumDslError, match="widths differ"):
        _compile(tmp_path, _pair(tmp_path, w=20) + f"- {{template: cpw_route, name: C, from: A.E, to: B.E, params: {{n_legs: 4}}, {L}}}")
    with pytest.raises(QuantumDslError, match=r"step #2 C \(cpw_route.yaml\): route: n_legs: 0 \(auto\) needs a region"):
        _compile(tmp_path, pair + f"- {{template: cpw_route, name: C, from: A.E, to: B.E, {L}}}")
    with pytest.raises(QuantumDslError, match="n_legs: given but no length"):
        _compile(tmp_path, pair + "- {template: cpw_route, name: C, from: A.E, to: B.E, params: {n_legs: 4}}")
    with pytest.raises(QuantumDslError, match=r"step #2 C \(cpw_route.yaml\): route: axis must be"):
        _compile(tmp_path, pair + "- {template: cpw_route, name: C, from: A.E, to: B.E, axis: diag}")
    with pytest.raises(QuantumDslError, match=r"param 'R' must be a finite number, got 'auto'"):       # R: auto 只给 planner 模板
        _compile(tmp_path, pair + f"- {{template: cpw_meander, name: C, from: A.E, to: B.E, params: {{R: auto}}, {L}}}")
    # 不正对 + 非 planner 模板: 仍 raise, 提示改用 cpw_route
    with pytest.raises(QuantumDslError, match="face each other.*cpw_route"):
        _compile(tmp_path, pair.replace("rot: 180", "rot: 90") + f"- {{template: cpw_meander, name: C, from: A.E, to: B.E, {L}}}")
    # 同一对不正对端口, cpw_route 通过 (最短骨架, 无 length), 默认横平竖直 / 自由角都行
    for extra in ("", ", axis: free", ", axis: 30"):
        lay, _ = _compile(tmp_path, pair.replace("rot: 180", "rot: 90") + f"- {{template: cpw_route, name: C, from: A.E, to: B.E{extra}}}")
        assert lay.used == {"A.E", "B.E"} and lay.subsystems == []
    # 模板侧: planner 只认 cpw、须 kind: connect、须声明 R / n_legs / gap / lead
    base = yaml.safe_load((LIB / "cpw_route.yaml").read_text(encoding="utf-8"))
    for over, msg in (({"planner": "astar"}, "only planner is 'cpw'"), ({"kind": None}, "needs kind: connect"),
                      ({"params": {"R": 40, "gap": 6, "lead": 60}}, r"missing \['n_legs'\]")):
        _write(tmp_path / "bad.yaml", yaml.safe_dump({**base, **over}))
        (tmp_path / "bad.geo").write_text((LIB / "cpw_route.geo").read_text(encoding="utf-8").replace(
            'Include "cpw_macros.geo";', f'Include "{(LIB / "cpw_macros.geo").as_posix()}";'), encoding="utf-8")
        with pytest.raises(QuantumDslError, match=msg):
            _compile(tmp_path, pair + "- {template: bad, name: C, from: A.E, to: B.E}")


# ---------------------------------------------------------------- 版图集成: demo (三条路)
ROUTES = {   # 步骤名: (region, 两只比特中心, from 口面外 lead/2 处, to 口面外 lead/2 处, 必须避开的矩形)
    "R1": ([REGION], ((0, 0), (900, -900)), (240.0, 0.0), (900.0, -660.0), None),
    "R2": ([[x + 1500 if i % 2 == 0 else x for i, x in enumerate(r)] for r in REGION_B], ((1500, 0), (2400, -900)),
           (1740.0, 0.0), (2400.0, -660.0), [2200, -300, 2500, 100]),
    "R3": ([[3180, -720, 4000, 100]], ((3000, 0), (3900, -900)), (3240.0, 0.0), (3900.0, -660.0), None),
    "R4": ([[4680, -720, 5500, 100]], ((4500, 0), (5400, -900)), (4740.0, 0.0), (5400.0, -660.0), None),
}


def test_cpw_route_demo_builds_inside_region(tmp_path):
    """契约「自动布线」 版图集成: cpw_route_demo (四对 xmon 的读出桨, 每对 Q_odd.RO 朝 +x → Q_even.RO 朝 +y, fixed 3000 µm, n_legs 自动,
    lead 60; R1 默认横平竖直 / R2 拼接 region 绕开挖掉的角 / R3 axis: free / R4 params R: auto) compile_layout + build(solve=False) 通过;
    每条总线 net = 步骤名, subsystems 记 length_drawn_um == 3000 − Σleq、route_primitives 与 R_um (R4 的 R_um = 70 = 同环境下最大可行整数半径,
    R1–R3 为 40); 八个端口 used; GDS 里每条总线 (两只桨 + CPW) 的多边形落在其 region 并集内 (shapely), R2 的 CPW 与挖掉的角不交;
    CPW 在两个端口面外 lead/2 处仍在端口法向上; region 太小 (挡住端口本身) → 规划失败, 报段号与建议, 不静默。"""
    import gdstk
    from shapely.geometry import Polygon

    from quantum_dsl import build, load_meta
    m = load_meta(DEMO)
    r = build(m, tmp_path / "demo", solve=False)
    lay = r["layout"]
    subs = {s["name"]: s for s in lay.subsystems}
    assert set(subs) == set(ROUTES) and lay.used == {f"Q{i}.RO" for i in range(1, 9)}
    assert {k: subs[k]["R_um"] for k in subs} == {"R1": 40.0, "R2": 40.0, "R3": 40.0, "R4": 70.0}
    (cell,) = gdstk.read_gds(str(r["gds"])).top_level()
    polys = [p for p in cell.polygons if p.layer == 1]                 # GDS 按 Physical 组各出一块: 地 / 岛 / 桨 / CPW
    ground = max(polys, key=lambda p: p.area())
    for k, (name, (rects, centres, pa, pb, avoid)) in enumerate(ROUTES.items()):
        qa, qb = lay.ports[f"Q{2 * k + 1}.RO"], lay.ports[f"Q{2 * k + 2}.RO"]
        sub = subs[name]
        assert sub["route"] == name and sub["mode"] == "fixed" and sub["route_primitives"] >= 5
        assert sub["length_drawn_um"] == pytest.approx(3000.0 - qa.leq - qb.leq)
        assert qa.net == name == qb.net and abs(math.sin(qa.a - qb.a - math.pi)) > 1e-9      # 两口确实不正对
        union = _union(rects)
        (bx0, by0, bx1, by1) = union.bounds
        bus = [p for p in polys if p is not ground and not any(p.contain(c) for c in centres)
               and bx0 - 1e-6 <= p.bounding_box()[0][0] and p.bounding_box()[1][0] <= bx1 + 1e-6
               and by0 - 1e-6 <= p.bounding_box()[0][1] and p.bounding_box()[1][1] <= by1 + 1e-6]
        assert len(bus) == 3                                                                   # 两只桨 + CPW
        cpw = max(bus, key=lambda p: p.area())
        assert cpw.area() == pytest.approx(10.0 * 3000.0, rel=2e-4)                            # 中心导体面积 = w·L
        assert cpw.contain(pa) and cpw.contain(pb)                                             # 引出是直的
        shape = Polygon(cpw.points)
        assert shape.within(union.buffer(1e-3))
        if avoid is not None:
            assert not shape.intersects(_union(avoid))
    assert Path(r["mesh"]).exists() and Path(r["gds_png"]).exists()
    # region 太小 → 规划失败, 报段号与建议, 不静默
    from quantum_dsl import QuantumDslError, compile_layout
    doc = yaml.safe_load(m.layout_path.read_text(encoding="utf-8"))
    doc["templates"] = [LIB.as_posix()]
    doc["steps"][2]["region"] = [180, -720, 890, 100]        # x1 挡住 Q2.RO 口本身
    _write(tmp_path / "tight.layout.yaml", yaml.safe_dump(doc))
    meta_txt = DEMO.read_text(encoding="utf-8").replace("layout: cpw_route_demo.layout.yaml", "layout: tight.layout.yaml")
    with pytest.raises(QuantumDslError, match=r"(?s)R1 .*no feasible CPW path.*leaves the region"):   # 口在区域外: 任何 R 都不行, 无 R 提示
        compile_layout(load_meta(_write(tmp_path / "tight.meta.yaml", meta_txt)))
