# -*- coding: utf-8 -*-
"""自动布线规划器 v2 (契约「自动布线」, 设计稿 docs/design/auto-route.md): 两个**不必正对**的 CPW 端口之间, 在**矩形并集**区域内,
画一条 G1 连续、可定长的中心线 = 直段 + 圆弧序列。纯 math, 不碰 gmsh (import 纯度): 原语由模板 ``lib/cpw_route.geo`` 用
``LIB_CPW`` / ``LIB_CPW_ARC`` 逐段画成面, Python 只注入数字。

流程 = **引出 → 骨架 → 填充 → 自检**:

* **引出** ``lead``: 两端各先沿端口法向直走 ``lead`` µm (from 口出发 / to 口驶入), 其后的一切在引出后的位姿之间做; 端口面上永远是一段直 CPW。
* **骨架** (不含蛇形的连接):
  - ``axis`` = 角度 (deg, 默认 0 = 横平竖直): **曼哈顿框架** —— 两端各用一段端弧转到框架的四个方向之一 (≤ 5 个位姿 / 端), 中间用
    直 / Z / U / L / 三折模板 (90° 圆角; 自由参数取居中 / 贴紧, 再加 region 网格格子中心的投影 —— 中段能挑走廊) 相连; 全部候选按 **(转弯数, 长度)** 排序 —— 曼哈顿单调路径多拐一次反而短
    (2 − π/2)R, 按长度排会选三折不选 L。
  - ``axis="free"``: v1 的 Dubins CSC 四型 (LSL / RSR / LSR / RSL), 一条中间直段。
  - 出区域 (含总宽/2) 的骨架丢弃。同 (转弯数, 长度) 的一组骨架由填充结果 (腿少、余量大) 定胜负。
* **填充** (给了 ``length``): 在骨架的直段上放蛇形块 (块首 90° 弧 + n 条垂直腿 + 腿间 180° 弯 + 块尾 90° 弧)。每个弯 k 有自己的
  外推量 u_k ≥ R, 腿因此**不等长、随沿轴的可用宽度变**: 弯的**余量** room_k = 基准半圆沿法向可推多远才碰界, **精确**算 (半圆取样点射线
  + 界的角点 / 端点沿反向射进加厚半圆 + 两弧外切; 界 = region 外框、矩形之间的缝、本条路自己的其它直段与弧 (净距 2R)、已放好的其它块)。
  u_k = R + λ (room_k − R), λ 由目标解出; 腿数从 2 起取首个能装下的; 摆放沿直段按 R/2 网格扫、先弯左 / 右都试, 取余量最大者。
  单段装不下 → **多段分摊**: 按各段容量比例把长度分到 2, 3, … 条直段, 容量小的先放, 先放好的块进后面块的障碍集 (拐角处两块的腿互相垂直
  也不交叉), 最大的一段吃精确余数; 显式 n_legs 是总腿数, 多段时按容量分。记账: M = S − 2Rn + nπR + 2Σu_k − 2R, 多出 E = M − S,
  全 u_k = R 时 E_min = R (nπ − 4)。没给 region 时 (须显式 n_legs) 腿等长。
* **自身净距**: 骨架与填好的路都查 —— 沿路间隔 ≥ πR 的任意两段原语中心线距离 ≥ 2R (间隔更短的是同一个弯的两侧, 天然贴着); 过不了的
  骨架淘汰 (回头路穿过自己的引出等), 过不了的填充换摆放。
* **区域** ``region`` = ``[x0, y0, x1, y1]`` 或若干个这样的矩形 (并集, 可拼成 L / T / 回字): 全部原语含总宽/2 落在并集内 —— 外框 (凸) 查取样点
  (直段两端, 弧两端 + 落在弧内的 0/90/180/270° 点, 对轴对齐矩形是精确极值), 外框内不属于任何矩形的格子 (缝) 查原语到格子的**精确距离** ≥ 总宽/2。
* **自检**: 输出前整条路重跑区域检查、记账与目标比对; 不过 → ``internal:`` raise (抓实现 bug, 不静默)。
* 装不下 / 出界 / 非法输入一律 raise ``QuantumDslError``, 逐骨架说明原因并给改法。

原语 (与 ``LIB_CPW_ARC`` 同约定, 每段弧 |a1 − a0| ≤ π/2, 长弧拆段): ``("line", x1, y1, x2, y2)`` / ``("arc", cx, cy, R, a0, a1)`` (a0 → a1 增 = 逆时针)。

# ponytail: 区域 = 矩形并集, 不做多边形 (升级: 多边形边当直线障碍, 外框检查改 point-in-polygon); 曼哈顿模板到三折为止 (升级: region 网格上
#   的最少转弯 Dijkstra), 自由参数只试规则值 + 格子中心; 多段分摊按容量比例顺序放、不做联合优化; 不做 CCC 型 Dubins / taper / 分端 lead;
#   不同 cpw_route 之间不互避 (重叠由短路检查 raise)。
"""

from __future__ import annotations

import math
from itertools import combinations

from .errors import QuantumDslError

__all__ = ["plan_cpw", "auto_radius", "path_length"]

_HALF_PI = math.pi / 2
_TWO_PI = 2 * math.pi
_EPS = 1e-9
_TOL = 1e-6          # 几何容差 (µm)
_PLACEMENTS = 9      # 蛇形块沿直段扫的摆放点数 (含中点)
_MAX_REPORT = 8      # 失败汇总最多列几条骨架的原因


# ---------------------------------------------------------------- 原语
def path_length(prims) -> float:
    """原语序列的中心线总长 (µm), 与模板 ``.geo`` 里 ``cpw_length`` 的累加口径相同 (弧拆不拆段都一样)。"""
    total = 0.0
    for p in prims:
        if p[0] == "line":
            total += math.hypot(p[3] - p[1], p[4] - p[2])
        else:
            total += p[3] * abs(p[5] - p[4])
    return total


def _arc(cx, cy, R, a0, a1) -> list[tuple]:
    """一段弧拆成 |Δ| ≤ π/2 的若干段 (零长弧丢弃)。"""
    d = a1 - a0
    if abs(d) < _EPS:
        return []
    m = max(1, math.ceil(abs(d) / _HALF_PI - 1e-12))
    return [("arc", cx, cy, R, a0 + d * k / m, a0 + d * (k + 1) / m) for k in range(m)]


def _line(x1, y1, x2, y2) -> list[tuple]:
    return [("line", x1, y1, x2, y2)] if math.hypot(x2 - x1, y2 - y1) > _EPS else []


def _emit(parts) -> list[tuple]:
    """未拆段的部件 → 原语 (弧拆 ≤ π/2, 零长丢弃)。"""
    out: list[tuple] = []
    for p in parts:
        out += _line(*p[1:]) if p[0] == "line" else _arc(*p[1:])
    return out


def _turns(parts) -> int:
    return sum(1 for p in parts if p[0] == "arc")


# ---------------------------------------------------------------- 距离 / 射线 (纯几何)
def _dist_pt_seg(px, py, ax, ay, bx, by) -> float:
    ex, ey = bx - ax, by - ay
    L2 = ex * ex + ey * ey
    t = 0.0 if L2 < _EPS else max(0.0, min(1.0, ((px - ax) * ex + (py - ay) * ey) / L2))
    return math.hypot(px - ax - t * ex, py - ay - t * ey)


def _in_arc(a, a0, a1) -> bool:
    """角 a 是否落在弧 [a0, a1] (任一方向) 的扫过范围内。"""
    lo, hi = min(a0, a1), max(a0, a1)
    return (a - lo) % _TWO_PI <= hi - lo + 1e-9


def _dist_pt_arc(px, py, cx, cy, R, a0, a1) -> float:
    if _in_arc(math.atan2(py - cy, px - cx), a0, a1):
        return abs(math.hypot(px - cx, py - cy) - R)
    return min(math.hypot(px - cx - R * math.cos(t), py - cy - R * math.sin(t)) for t in (a0, a1))


def _dist_seg_seg(ax, ay, bx, by, cx, cy, dx, dy) -> float:
    def orient(px, py, qx, qy, rx, ry):
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)
    if (orient(ax, ay, bx, by, cx, cy) * orient(ax, ay, bx, by, dx, dy) < 0
            and orient(cx, cy, dx, dy, ax, ay) * orient(cx, cy, dx, dy, bx, by) < 0):
        return 0.0                                       # 严格相交; 端点接触 / 共线由下面的端点距离给 0
    return min(_dist_pt_seg(ax, ay, cx, cy, dx, dy), _dist_pt_seg(bx, by, cx, cy, dx, dy),
               _dist_pt_seg(cx, cy, ax, ay, bx, by), _dist_pt_seg(dx, dy, ax, ay, bx, by))


def _dist_arc_seg(cx, cy, R, a0, a1, ax, ay, bx, by) -> float:
    """弧与线段的最小距离 (精确): 相交 → 0; 否则在「弧端点 – 线段」「线段端点 – 弧」「圆心到线段的垂足方向上的两个圆上点」里取最小。"""
    ex, ey = bx - ax, by - ay
    L = math.hypot(ex, ey)
    if L < _EPS:
        return _dist_pt_arc(ax, ay, cx, cy, R, a0, a1)
    ex, ey = ex / L, ey / L
    fx, fy = ax - cx, ay - cy
    b = fx * ex + fy * ey                                # 线段参数 t 处的点 = a + t e; |a + t e − c|² = R²
    disc = b * b - (fx * fx + fy * fy - R * R)
    if disc >= 0:
        for t in (-b - math.sqrt(disc), -b + math.sqrt(disc)):
            if -_EPS <= t <= L + _EPS:
                px, py = ax + t * ex, ay + t * ey
                if _in_arc(math.atan2(py - cy, px - cx), a0, a1):
                    return 0.0
    cands = [_dist_pt_seg(cx + R * math.cos(t), cy + R * math.sin(t), ax, ay, bx, by) for t in (a0, a1)]
    cands += [_dist_pt_arc(ax, ay, cx, cy, R, a0, a1), _dist_pt_arc(bx, by, cx, cy, R, a0, a1)]
    t = -b                                               # 垂足参数
    if 0 <= t <= L:
        qx, qy = ax + t * ex, ay + t * ey
        h = math.hypot(qx - cx, qy - cy)
        if h > _EPS:
            ang = math.atan2(qy - cy, qx - cx)
            for a in (ang, ang + math.pi):
                if _in_arc(a, a0, a1):
                    cands.append(abs(h - R) if a == ang else h + R)
    return min(cands)


def _dist_arc_arc(cx, cy, Ra, a0, a1, ex, ey, Rb, b0, b1) -> float:
    """两段弧的最小距离 (精确): 相交 → 0; 否则在「端点 – 另一弧」与「圆心连线方向上的圆上点对」里取最小
    (两圆曲线的距离驻点只在圆心连线上; 落在弧外的驻点由端点接管)。"""
    cands = [_dist_pt_arc(cx + Ra * math.cos(t), cy + Ra * math.sin(t), ex, ey, Rb, b0, b1) for t in (a0, a1)]
    cands += [_dist_pt_arc(ex + Rb * math.cos(t), ey + Rb * math.sin(t), cx, cy, Ra, a0, a1) for t in (b0, b1)]
    d = math.hypot(ex - cx, ey - cy)
    if d < _EPS:                                          # 同心: 角度范围重叠 → 半径差
        for t in (a0, a1):
            if _in_arc(t, b0, b1):
                cands.append(abs(Ra - Rb))
        return min(cands)
    ux, uy = (ex - cx) / d, (ey - cy) / d
    if abs(Ra - Rb) <= d <= Ra + Rb:                      # 两圆相交: 交点同时落在两弧上 → 0
        a = (Ra * Ra - Rb * Rb + d * d) / (2 * d)
        h = math.sqrt(max(0.0, Ra * Ra - a * a))
        for sg in (1, -1):
            qx, qy = cx + a * ux - sg * h * uy, cy + a * uy + sg * h * ux
            if _in_arc(math.atan2(qy - cy, qx - cx), a0, a1) and _in_arc(math.atan2(qy - ey, qx - ex), b0, b1):
                return 0.0
    phi = math.atan2(uy, ux)
    for ta in (phi, phi + math.pi):
        for tb in (phi, phi + math.pi):
            if _in_arc(ta, a0, a1) and _in_arc(tb, b0, b1):
                cands.append(math.hypot(cx + Ra * math.cos(ta) - ex - Rb * math.cos(tb),
                                        cy + Ra * math.sin(ta) - ey - Rb * math.sin(tb)))
    return min(cands)


def _dist_prim_prim(p, q) -> float:
    """两条原语 (直段 / 弧) 中心线的最小距离 (精确)。"""
    if p[0] == "line" and q[0] == "line":
        return _dist_seg_seg(*p[1:], *q[1:])
    if p[0] == "arc" and q[0] == "arc":
        return _dist_arc_arc(*p[1:], *q[1:])
    arc, seg = (p, q) if p[0] == "arc" else (q, p)
    return _dist_arc_seg(*arc[1:], *seg[1:])


def _self_clear(prims, R, clr):
    """路径自身净距: 沿路间隔 (前者终点到后者起点的路长) ≥ πR 的两段原语, 中心线距离须 ≥ clr − 1e-6 —— 间隔更短的两段是同一个弯
    的两侧 (180° 弯两腿恰间隔 πR、相距 2R), 天然更近, 不算冲突。返回首个违规 (i, j, 距离) 或 None。"""
    cum = [0.0]
    for p in prims:
        cum.append(cum[-1] + path_length([p]))
    for i in range(len(prims)):
        for j in range(i + 1, len(prims)):
            if cum[j] - cum[i + 1] < math.pi * R - _TOL:
                continue
            d = _dist_prim_prim(prims[i], prims[j])
            if d < clr - _TOL:
                return i, j, d
    return None


def _dist_prim_rect(p, rect) -> float:
    """原语到轴对齐矩形的距离; 原语起点在矩形内或与边相交 → 0。"""
    x0, y0, x1, y1 = rect
    sx, sy = (p[1], p[2]) if p[0] == "line" else (p[1] + p[3] * math.cos(p[4]), p[2] + p[3] * math.sin(p[4]))
    if x0 < sx < x1 and y0 < sy < y1:
        return 0.0
    sides = ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0))
    if p[0] == "line":
        return min(_dist_seg_seg(p[1], p[2], p[3], p[4], *s) for s in sides)
    return min(_dist_arc_seg(p[1], p[2], p[3], p[4], p[5], *s) for s in sides)


def _ray_disc(px, py, dx, dy, cx, cy, r) -> float:
    """射线 p + u·d (|d| = 1) 首次进入圆盘 (c, r) 的 u; 起点已在内 → 0; 不交 → inf。"""
    fx, fy = px - cx, py - cy
    b = fx * dx + fy * dy
    c = fx * fx + fy * fy - r * r
    if c <= 0:
        return 0.0
    disc = b * b - c
    if disc < 0:
        return math.inf
    u = -b - math.sqrt(disc)
    return u if u >= 0 else math.inf


def _ray_slab(px, py, dx, dy, x0, y0, x1, y1) -> float:
    """射线首次进入轴对齐矩形 (含边界) 的 u; 起点在内 → 0; 不交 → inf。"""
    lo, hi = 0.0, math.inf
    for q0, dq, qmin, qmax in ((px, dx, x0, x1), (py, dy, y0, y1)):
        if abs(dq) < _EPS:
            if not (qmin - _EPS <= q0 <= qmax + _EPS):
                return math.inf
        else:
            u1, u2 = (qmin - q0) / dq, (qmax - q0) / dq
            lo, hi = max(lo, min(u1, u2)), min(hi, max(u1, u2))
    return lo if lo <= hi + _EPS else math.inf


def _ray_exit_rect(px, py, dx, dy, x0, y0, x1, y1) -> float:
    """射线离开轴对齐矩形的 u (起点在内); 起点在外 → 负 / −inf。"""
    u = math.inf
    for q, dq, lo, hi in ((px, dx, x0, x1), (py, dy, y0, y1)):
        if dq > _EPS:
            u = min(u, (hi - q) / dq)
        elif dq < -_EPS:
            u = min(u, (lo - q) / dq)
        elif not (lo - _TOL <= q <= hi + _TOL):
            return -math.inf
    return u


def _ray_capsule(px, py, dx, dy, ax, ay, bx, by, r) -> float:
    """射线首次进入「线段 ab 外扩 r」(胶囊) 的 u。"""
    u = min(_ray_disc(px, py, dx, dy, ax, ay, r), _ray_disc(px, py, dx, dy, bx, by, r))
    ex, ey = bx - ax, by - ay
    L = math.hypot(ex, ey)
    if L < _EPS:
        return u
    ex, ey = ex / L, ey / L
    nx, ny = -ey, ex
    s0, w0 = (px - ax) * ex + (py - ay) * ey, (px - ax) * nx + (py - ay) * ny
    return min(u, _ray_slab(s0, w0, dx * ex + dy * ey, dx * nx + dy * ny, 0.0, -r, L, r))


def _ray_arc(px, py, dx, dy, cx, cy, Ra, a0, a1, r) -> float:
    """射线首次进入「弧外扩 r」(环带扇形 ∪ 两端圆; r = 0 即弧曲线本身) 的 u; 起点在内 → 0; 不交 → inf。
    扇形的两条径向边落在端圆的直径上, 所以边界 = 外圆弧 + 内圆弧 (角度在范围内) + 端圆。"""
    u = min(_ray_disc(px, py, dx, dy, cx + Ra * math.cos(a0), cy + Ra * math.sin(a0), r),
            _ray_disc(px, py, dx, dy, cx + Ra * math.cos(a1), cy + Ra * math.sin(a1), r))
    fx, fy = px - cx, py - cy
    d0 = math.hypot(fx, fy)
    if r > 0 and Ra - r <= d0 <= Ra + r and _in_arc(math.atan2(fy, fx), a0, a1):
        return 0.0
    b = fx * dx + fy * dy
    for rad in (Ra + r, Ra - r):
        if rad <= 0:
            continue
        disc = b * b - (fx * fx + fy * fy - rad * rad)
        if disc < 0:
            continue
        s = math.sqrt(disc)
        for t in (-b - s, -b + s):
            if 0 <= t < u:
                qx, qy = px + t * dx, py + t * dy
                if _in_arc(math.atan2(qy - cy, qx - cx), a0, a1):
                    u = t
    return u


def _prim_ends(p):
    if p[0] == "line":
        return (p[1], p[2]), (p[3], p[4])
    _, cx, cy, R, a0, a1 = p
    return (cx + R * math.cos(a0), cy + R * math.sin(a0)), (cx + R * math.cos(a1), cy + R * math.sin(a1))


# ---------------------------------------------------------------- 区域: 矩形并集
def _samples(p):
    """原语上的检查点 (对轴对齐矩形是精确极值): 直段两端; 弧两端 + 落在弧内的 0 / 90 / 180 / 270° 点。"""
    if p[0] == "line":
        return [(p[1], p[2]), (p[3], p[4])]
    _, cx, cy, R, a0, a1 = p
    lo, hi = min(a0, a1), max(a0, a1)
    angs = [a0, a1] + [k * _HALF_PI for k in range(math.ceil(lo / _HALF_PI), math.floor(hi / _HALF_PI) + 1)]
    return [(cx + R * math.cos(a), cy + R * math.sin(a)) for a in angs]


class _Region:
    """矩形并集 = 外框 (凸, 内缩 inset 查取样点) − 缝 (外框内不属于任何矩形的格子, 外扩 inset 查精确距离 / 射线)。"""

    def __init__(self, rects, inset):
        self.rects, self.inset = rects, inset
        xs = sorted({v for r in rects for v in (r[0], r[2])})
        ys = sorted({v for r in rects for v in (r[1], r[3])})
        self.bbox = (xs[0], ys[0], xs[-1], ys[-1])
        self.gaps = [(xs[i], ys[j], xs[i + 1], ys[j + 1]) for i in range(len(xs) - 1) for j in range(len(ys) - 1)
                     if not any(r[0] <= (xs[i] + xs[i + 1]) / 2 <= r[2] and r[1] <= (ys[j] + ys[j + 1]) / 2 <= r[3]
                                for r in rects)]

    def violation(self, prims) -> str | None:
        x0, y0, x1, y1 = (v + s * self.inset for v, s in zip(self.bbox, (1, 1, -1, -1)))
        for i, p in enumerate(prims):
            worst = max(max(x0 - x, x - x1, y0 - y, y - y1) for x, y in _samples(p))
            if worst > _TOL:
                return (f"segment #{i} ({p[0]}) leaves the region by {worst:.6g} um "
                        f"(region {self._label()} inset by half the CPW width {self.inset:.6g})")
        for i, p in enumerate(prims):
            for g in self.gaps:
                d = _dist_prim_rect(p, g)
                if d < self.inset - _TOL:
                    return (f"segment #{i} ({p[0]}) cuts into the gap {[round(v, 6) for v in g]} between the region's "
                            f"rectangles by {self.inset - d:.6g} um (CPW half width {self.inset:.6g})")
        return None

    def ray_exit(self, px, py, dx, dy) -> float:
        """射线离开内缩外框的 u。"""
        x0, y0, x1, y1 = self.bbox
        i = self.inset
        return _ray_exit_rect(px, py, dx, dy, x0 + i, y0 + i, x1 - i, y1 - i)

    def ray_gap_edges(self, px, py, dx, dy, g) -> float:
        """射线首次进入缝 g 外扩 inset 的两条直边 slab 的 u (圆角部分由 _room 用角点对半圆的对偶射线精确算)。"""
        x0, y0, x1, y1 = g
        i = self.inset
        return min(_ray_slab(px, py, dx, dy, x0 - i, y0, x1 + i, y1), _ray_slab(px, py, dx, dy, x0, y0 - i, x1, y1 + i))

    @staticmethod
    def gap_label(g) -> str:
        return f"the gap {[round(c, 6) for c in g]} between the region's rectangles"

    def _label(self) -> str:
        return str([list(r) for r in self.rects]) if len(self.rects) > 1 else str(list(self.rects[0]))


def _parse_region(region):
    """None | [x0, y0, x1, y1] | [[…], […], …] → 矩形列表 (float) 或 None; 非法 raise。"""
    if region is None:
        return None
    bad = QuantumDslError(f"route: region must be [x0, y0, x1, y1] (x0 < x1, y0 < y1) or a list of such "
                          f"rectangles (their union), got {region!r}")
    if not isinstance(region, (list, tuple)) or not region:
        raise bad
    rects = region if isinstance(region[0], (list, tuple)) else [region]
    out = []
    for r in rects:
        ok = (isinstance(r, (list, tuple)) and len(r) == 4
              and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in r)
              and r[0] < r[2] and r[1] < r[3])
        if not ok:
            raise bad
        out.append(tuple(float(v) for v in r))
    return out


# ---------------------------------------------------------------- 骨架: Dubins (axis="free")
def _dubins_csc(start, end, R) -> list[tuple]:
    """四型 CSC 候选, 每条 = (总长, 类型, 弧1 (cx, cy, a0, a1), 直段 (x1, y1, x2, y2), 弧2)。按总长升序。"""
    x0, y0, t0 = start
    x1, y1, t1 = end
    out = []
    for kind in ("LSL", "RSR", "LSR", "RSL"):
        s0, s1 = (1 if kind[0] == "L" else -1), (1 if kind[2] == "L" else -1)   # +1 逆时针 (左), −1 顺时针 (右)
        csx, csy = x0 - s0 * R * math.sin(t0), y0 + s0 * R * math.cos(t0)          # 圆心 = 位姿点 + R · (左法向 · s)
        cex, cey = x1 - s1 * R * math.sin(t1), y1 + s1 * R * math.cos(t1)
        dx, dy = cex - csx, cey - csy
        D = math.hypot(dx, dy)
        if s0 == s1:                                   # 外公切线, 与圆心连线平行
            phi = math.atan2(dy, dx) if D > _EPS else t0
            S = D
        else:                                          # 内公切线, 需要 D ≥ 2R
            if D < 2 * R - _EPS:
                continue
            phi = math.atan2(dy, dx) + s0 * math.asin(min(1.0, 2 * R / D))
            S = math.sqrt(max(0.0, D * D - 4 * R * R))
        a_s0, a_s1 = t0 - s0 * _HALF_PI, phi - s0 * _HALF_PI     # 行进方向 φ 在左圆上位于 φ − π/2, 右圆上位于 φ + π/2
        a_e0, a_e1 = phi - s1 * _HALF_PI, t1 - s1 * _HALF_PI
        d1 = (s0 * (a_s1 - a_s0)) % _TWO_PI
        d2 = (s1 * (a_e1 - a_e0)) % _TWO_PI
        d1 = 0.0 if d1 > _TWO_PI - 1e-9 else d1
        d2 = 0.0 if d2 > _TWO_PI - 1e-9 else d2
        p1 = (csx + R * math.cos(a_s1), csy + R * math.sin(a_s1))
        p2 = (cex + R * math.cos(a_e0), cey + R * math.sin(a_e0))
        out.append((R * (d1 + d2) + S, kind, (csx, csy, a_s0, a_s0 + s0 * d1), (p1[0], p1[1], p2[0], p2[1]),
                    (cex, cey, a_e0, a_e0 + s1 * d2)))
    return sorted(out, key=lambda c: c[0])


def _dubins_skeletons(s2, e2, R) -> list[tuple[str, list[tuple]]]:
    out = []
    for _, kind, (cx, cy, a0, a1), seg, (ex, ey, b0, b1) in _dubins_csc(s2, e2, R):
        parts: list[tuple] = []
        if abs(a1 - a0) > _EPS:
            parts.append(("arc", cx, cy, R, a0, a1))
        parts += _line(*seg)
        if abs(b1 - b0) > _EPS:
            parts.append(("arc", ex, ey, R, b0, b1))
        out.append((kind, parts))
    return out


# ---------------------------------------------------------------- 骨架: 曼哈顿框架
def _end_arcs(pose, headings, R, arrive=False):
    """从位姿转到各框架方向的端弧: [(部件, 转后位姿)]。arrive=True 是到达端: 弧倒着算, 返回 (部件, 弧起点位姿)。
    每个方向取转角较小的一侧; 恰 180° 两侧都算 (发夹); 零转角只记一次。"""
    x, y, th = pose
    out = []
    for h in headings:
        for s in (1, -1):
            phi = (s * ((th - h) if arrive else (h - th))) % _TWO_PI
            if phi > math.pi + 1e-9:
                continue
            if phi < 1e-9:
                if s == 1:
                    out.append(([], (x, y, h)))
                continue
            cx, cy = x - s * R * math.sin(th), y + s * R * math.cos(th)
            if arrive:
                a1 = th - s * _HALF_PI
                a0 = a1 - s * phi
                out.append(([("arc", cx, cy, R, a0, a1)], (cx + R * math.cos(a0), cy + R * math.sin(a0), h)))
            else:
                a0 = th - s * _HALF_PI
                a1 = a0 + s * phi
                out.append(([("arc", cx, cy, R, a0, a1)], (cx + R * math.cos(a1), cy + R * math.sin(a1), h)))
    return out


def _connectors(P1, P2, R, centres=()) -> list[list[tuple[float, float]]]:
    """P1 (x, y, h1) → P2 (x, y, h2) (两朝向都在同一曼哈顿框架里) 的折线拐角候选 (芯片坐标)。
    在 h1 = +x 的框架里: 直 / Z / U / L / 三折 (顺向 · 回头 × 同向 · 反向)。自由参数 (Z / U / 三折的 m, 三折的 q) 取「居中 / 贴紧」
    的规则值, 再加 ``centres`` (region 网格各格子中心, 芯片坐标) 投影到框架里落在可行范围内的值 —— 让中段能挑一条走廊走, 由区域检查筛。"""
    x1, y1, h1 = P1
    x2, y2, h2 = P2
    c, s = math.cos(h1), math.sin(h1)
    dx, dy = (x2 - x1) * c + (y2 - y1) * s, -(x2 - x1) * s + (y2 - y1) * c
    us = [(px - x1) * c + (py - y1) * s for px, py in centres]
    vs = [-(px - x1) * s + (py - y1) * c for px, py in centres]

    def pick(rule, vals, lo, hi=math.inf):
        return sorted({round(v, 9) for v in [rule] + [v for v in vals if lo - _EPS <= v <= hi + _EPS]})
    r = round(((h2 - h1) % _TWO_PI) / _HALF_PI) % 4
    cands: list[list[tuple[float, float]]] = []
    if r == 0:
        if abs(dy) < _TOL and dx >= -_TOL:
            cands.append([])
        elif dx >= 2 * R - _EPS and abs(dy) >= 2 * R - _EPS:
            cands += [[(m, 0.0), (m, dy)] for m in pick(dx / 2, us, R, dx - R)]              # Z
    elif r == 2:
        if abs(dy) >= 2 * R - _EPS:
            cands += [[(m, 0.0), (m, dy)] for m in pick(max(R, dx + R), us, max(R, dx + R))]  # U
    else:
        sg = 1 if r == 1 else -1
        if dx >= R - _EPS and sg * dy >= R - _EPS:
            cands.append([(dx, 0.0)])                                                        # L
        for third in (1, -1):                                                                # 三折: (m, 0), (m, q), (dx, q)
            if third == 1:
                if dx < 3 * R - _EPS:
                    continue
                ms = pick((dx - R) / 2, us, R, dx - 2 * R)
            else:
                ms = pick(max(R, dx + 2 * R), us, max(R, dx + 2 * R))
            qs: list[float] = []
            if sg * dy - R >= 2 * R - _EPS:                                                  # 第二段与末段同向, q 居中
                qs += pick(sg * (2 * R + sg * dy - R) / 2,
                           [v for v in vs if 2 * R - _EPS <= sg * v <= sg * dy - R + _EPS], -math.inf)
            if sg * dy + 2 * R >= R - _EPS:                                                  # 第二段反向, q 贴紧
                qs += pick(-sg * 2 * R, [v for v in vs if sg * v <= -2 * R + _EPS], -math.inf)
            cands += [[(m, 0.0), (m, q), (dx, q)] for m in ms for q in qs]
    return [[(x1 + u * c - v * s, y1 + u * s + v * c) for u, v in corners] for corners in cands]


def _fillet_path(P1, corners, P2, R):
    """P1 位姿 → 各拐角 → P2 位姿: 直段 + 拐角处的圆角 (进向 a、出向 b: 切点 C − R a 与 C + R b, 圆心 C − R a + R b)。
    直段负长 → None。"""
    pts = [(P1[0], P1[1])] + list(corners) + [(P2[0], P2[1])]
    parts: list[tuple] = []
    cur = pts[0]
    for i in range(1, len(pts) - 1):
        (px, py), (cx, cy), (nx, ny) = pts[i - 1], pts[i], pts[i + 1]
        la, lb = math.hypot(cx - px, cy - py), math.hypot(nx - cx, ny - cy)
        if la < _EPS or lb < _EPS:
            return None
        ax, ay, bx, by = (cx - px) / la, (cy - py) / la, (nx - cx) / lb, (ny - cy) / lb
        t1 = (cx - R * ax, cy - R * ay)
        if (t1[0] - cur[0]) * ax + (t1[1] - cur[1]) * ay < -_TOL:
            return None
        parts += _line(cur[0], cur[1], t1[0], t1[1])
        turn = 1 if ax * by - ay * bx > 0 else -1
        a0 = math.atan2(-by, -bx)
        parts.append(("arc", cx - R * ax + R * bx, cy - R * ay + R * by, R, a0, a0 + turn * _HALF_PI))
        cur = (cx + R * bx, cy + R * by)
    hx, hy = math.cos(P2[2]), math.sin(P2[2])
    if (P2[0] - cur[0]) * hx + (P2[1] - cur[1]) * hy < -_TOL:
        return None
    parts += _line(cur[0], cur[1], P2[0], P2[1])
    return parts


def _manhattan_skeletons(s2, e2, R, alpha, reg) -> list[tuple[str, list[tuple]]]:
    H = [alpha + k * _HALF_PI for k in range(4)]
    centres: list[tuple[float, float]] = []
    if reg is not None:                                # region 网格各格子的中心: 中段直段的候选位置 (走廊)
        xs = sorted({v for r in reg.rects for v in (r[0], r[2])})
        ys = sorted({v for r in reg.rects for v in (r[1], r[3])})
        centres = [((xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2) for i in range(len(xs) - 1) for j in range(len(ys) - 1)]
    out = []
    for parts1, P1 in _end_arcs(s2, H, R):
        for parts2, P2 in _end_arcs(e2, H, R, arrive=True):
            for corners in _connectors(P1, P2, R, centres):
                mid = _fillet_path(P1, corners, P2, R)
                if mid is not None:
                    parts = parts1 + mid + parts2
                    out.append((f"{_turns(parts)}-turn path via {len(corners)} corner(s)", parts))
    return out


# ---------------------------------------------------------------- 填充
def _e_min(R, n) -> float:
    """n 条腿的最小蛇形 (全部 u_k = R) 比原直段多出的长度。"""
    return R * (n * math.pi - 4)


def _obstacles(full, i, extra=()):
    """直段 i 的障碍 = 本条路其它部件 (直段与弧, 含引出), 除去与它共端点的 (相邻圆角 / 端弧 / 零弧相接的共线邻段 —— 它们和这段
    一起构成同一个弯, 天然贴着); 再加已放好的其它蛇形块 ``extra``。返回 [(名字, 部件)]。"""
    a, b = _prim_ends(full[i])
    obs = []
    for j, p in enumerate(full):
        if j == i:
            continue
        if any(math.hypot(e[0] - q[0], e[1] - q[1]) < _TOL for e in _prim_ends(p) for q in (a, b)):
            continue
        obs.append((f"the route's own segment #{j}", p))
    return obs + [("another meander block", p) for p in extra]


class _Run:
    """一条直段上放蛇形块的工作台: 几何、障碍、逐位置的余量缓存。摆放网格 = R/2 (加居中与贴末端), 所有腿数共用同一套位置,
    余量 (只依赖位置与侧) 只算一次。"""

    def __init__(self, full, i, R, region, clr, extra=()):
        _, ax, ay, bx, by = full[i]
        self.i, self.ax, self.ay, self.R, self.region, self.clr = i, ax, ay, R, region, clr
        self.S = math.hypot(bx - ax, by - ay)
        self.th = math.atan2(by - ay, bx - ax)
        self.tx, self.ty = math.cos(self.th), math.sin(self.th)
        self.n_max = int(self.S / (2 * R) + 1e-9)
        self.obstacles = _obstacles(full, i, extra)
        self._cache: dict = {}

    def places(self, n) -> list[float]:
        free = self.S - 2 * self.R * n
        step = self.R / 2
        vals = {round(k * step, 9) for k in range(int(free / step + 1e-9) + 1)} | {round(free / 2, 9), round(free, 9)}
        return sorted(v for v in vals if -_TOL <= v <= free + _TOL)

    def rooms(self, l_in, n, sigma1) -> list[tuple[float, str]]:
        """弯 k = 1..n−1 (轴向 ℓ_in + 2kR, 侧 σ₁·(−1)^(k−1)) 的余量。"""
        return [self.room(l_in + 2 * k * self.R, sigma1 if k % 2 else -sigma1) for k in range(1, n)]

    def room(self, c, sigma) -> tuple[float, str]:
        key = (round(c, 9), sigma)
        if key not in self._cache:
            self._cache[key] = self._room(c, sigma)
        return self._cache[key]

    def _room(self, c, sigma) -> tuple[float, str]:
        """圆心在轴上 (轴向 c)、开口朝 −σn 的基准半圆, 沿 σn 可外推的最大距离与限制者。**精确**: 每种界都取「半圆 → 界」与「界的角点 /
        端点 → 半圆」两个方向的射线 (后者 = 点沿 −σn 进入加厚半圆), 两圆弧体–体接触用外切。"""
        R, th = self.R, self.th
        ox, oy = self.ax + c * self.tx, self.ay + c * self.ty
        nx, ny = -self.ty * sigma, self.tx * sigma                       # 外推方向 σn
        a0, a1 = th + math.pi, th + math.pi - sigma * math.pi             # 半圆: 从 th+π 经 th+σπ/2 到 th

        def pt(a):
            return ox + R * math.cos(a), oy + R * math.sin(a)
        base = [pt(a) for a in (a0, a1, th + sigma * _HALF_PI)]
        base += [pt(a) for a in (0.0, _HALF_PI, math.pi, 3 * _HALF_PI) if _in_arc(a, a0, a1)]
        best = [math.inf, "nothing"]

        def hit(u, why):
            if u < best[0]:
                best[0], best[1] = u, why
        reg = self.region
        if reg is not None:
            for px, py in base:
                hit(reg.ray_exit(px, py, nx, ny), "the region edge")
            for g in reg.gaps:
                lab = reg.gap_label(g)
                for px, py in base:
                    hit(reg.ray_gap_edges(px, py, nx, ny, g), lab)
                for gx in (g[0], g[2]):
                    for gy in (g[1], g[3]):
                        hit(_ray_arc(gx, gy, -nx, -ny, ox, oy, R, a0, a1, reg.inset), lab)
        clr = self.clr - _TOL                                            # 开集: 恰等于净距的放行
        for lab, p in self.obstacles:
            if p[0] == "line":
                _, ax, ay, bx, by = p
                beta = math.atan2(by - ay, bx - ax)
                pts = [pt(a0), pt(a1)] + [pt(a) for a in (beta + _HALF_PI, beta - _HALF_PI) if _in_arc(a, a0, a1)]
                for px, py in pts:
                    hit(_ray_capsule(px, py, nx, ny, ax, ay, bx, by, clr), lab)
                for qx, qy in ((ax, ay), (bx, by)):
                    hit(_ray_arc(qx, qy, -nx, -ny, ox, oy, R, a0, a1, clr), lab)
            else:
                _, cx, cy, Rb, b0, b1 = p
                for px, py in (pt(a0), pt(a1)):
                    hit(_ray_arc(px, py, nx, ny, cx, cy, Rb, b0, b1, clr), lab)
                for qx, qy in _prim_ends(p):
                    hit(_ray_arc(qx, qy, -nx, -ny, ox, oy, R, a0, a1, clr), lab)
                fx, fy = ox - cx, oy - cy                                # 体–体: 两圆外切 (弧都同半径, 内切不会先发生)
                rad = R + Rb + clr
                bq, cq = fx * nx + fy * ny, fx * fx + fy * fy - rad * rad
                disc = bq * bq - cq
                if cq > 0 and disc >= 0:
                    u = -bq - math.sqrt(disc)
                    if 0 <= u < best[0]:
                        phi = math.atan2(cy - (oy + u * ny), cx - (ox + u * nx))
                        if _in_arc(phi, a0, a1) and _in_arc(phi + math.pi, b0, b1):
                            hit(u, lab)
        return best[0], best[1]


def _meander_parts(ax, ay, th, S, R, l_in, us, sigma1) -> list[tuple]:
    """直段 (ax, ay) → 沿 th 长 S 上的蛇形块 (未拆段部件): ℓ_in 直段, 块首 90° 弧, 腿 / 180° 弯交替 (弯 k 外推 u_k), 块尾 90° 弧, 剩余直段。"""
    tx, ty = math.cos(th), math.sin(th)
    nx, ny = -ty, tx
    n = len(us) + 1

    def P(c, v):
        return (ax + c * tx + v * nx, ay + c * ty + v * ny)
    parts: list[tuple] = [("line", ax, ay, *P(l_in, 0.0))]
    parts.append(("arc", *P(l_in, sigma1 * R), R, th - sigma1 * _HALF_PI, th))
    cur, sigma = sigma1 * R, sigma1
    for k, u in enumerate(us, start=1):
        c = l_in + (2 * k - 1) * R
        parts.append(("line", *P(c, cur), *P(c, sigma * u)))
        parts.append(("arc", *P(c + R, sigma * u), R, th + math.pi, th + math.pi - sigma * math.pi))
        cur, sigma = sigma * u, -sigma
    c = l_in + (2 * n - 1) * R
    parts.append(("line", *P(c, cur), *P(c, -sigma * R)))                    # 末腿回到轴旁 R (在上一个弯的那一侧)
    parts.append(("arc", *P(c + R, -sigma * R), R, th + math.pi, th + math.pi - sigma * _HALF_PI))
    parts.append(("line", *P(l_in + 2 * n * R, 0.0), *P(S, 0.0)))
    return parts


def _fill(run: _Run, X, n_legs):
    """在 run 上放一块蛇形补 X µm (n_legs = 0 → 从 2 起取首个装得下的腿数)。可行 → ((n, 余量, 块部件), None); 否则 (None, 原因)。"""
    R, S = run.R, run.S
    tag = f"straight run #{run.i} ({S:.6g} um)"
    if run.n_max < 2:
        return None, f"{tag}: shorter than 4R = {4 * R:.6g} um, no room for a meander"
    if n_legs and n_legs > run.n_max:
        return None, (f"{tag}: {n_legs} legs need 2*R*n = {2 * R * n_legs:.6g} um of run but only {S:.6g} fits "
                      f"({run.n_max} legs at most) — fewer legs (n_legs) or smaller R")
    last = ""
    for n in ((n_legs,) if n_legs else range(2, run.n_max + 1)):
        e_min = _e_min(R, n)
        if X < e_min - _TOL:
            return None, (f"{tag}: {last + '; ' if last else ''}{n} legs add at least {e_min:.6g} um but only {X:.6g} um "
                          f"is needed — lengthen the target, shorten lead or use fewer legs")
        free = S - 2 * R * n
        best, best_e, tight = None, -math.inf, ""
        for l_in in run.places(n):
            for sigma1 in (1, -1):
                rk = run.rooms(l_in, n, sigma1)
                short = [(r, why) for r, why in rk if r < R - _TOL]
                if short:
                    r, why = min(short)
                    tight = f"a bend of radius {R:.6g} has only {max(r, 0):.6g} um beside {why}"
                    continue
                if run.region is None:
                    u = (X + 2 * R - R * (n * math.pi - 2 * n)) / (2 * (n - 1))      # 无区域: 等腿
                    over = [r for r, _ in rk if u > r + _TOL]
                    if over:
                        tight = f"equal legs of {u:.6g} um hit the route's own path (room {min(over):.6g} um)"
                        continue
                    us, e_max = [u] * (n - 1), math.inf
                else:
                    e_max = 2 * sum(r for r, _ in rk) - 2 * R + R * (n * math.pi - 2 * n)
                    best_e = max(best_e, e_max)
                    if X > e_max + _TOL:
                        continue
                    lam = 0.0 if e_max - e_min < _EPS else min(1.0, max(0.0, (X - e_min) / (e_max - e_min)))
                    us = [R + lam * (r - R) for r, _ in rk]
                key = (e_max - X, -abs(l_in - free / 2), sigma1)
                if best is None or key > best[0]:
                    best = (key, l_in, sigma1, us)
        if best is not None:
            (slack, _, _), l_in, sigma1, us = best
            return (n, slack, _meander_parts(run.ax, run.ay, run.th, S, R, l_in, us, sigma1)), None
        last = (f"{n} legs reach at most +{best_e:.6g} um, {X:.6g} needed" if best_e > -math.inf
                else tight or f"no placement fits {n} legs")
    return None, f"{tag}: {'' if n_legs else 'even '}{last}"


def _capacity(run: _Run, n_legs) -> float:
    """run 上一块蛇形最多能补多少 (腿数 / 摆放 / 先弯侧取最大); 无可行 → −inf; 无区域又不碰自身 → inf。"""
    R = run.R
    if n_legs and n_legs > run.n_max:
        return -math.inf
    cap = -math.inf
    for n in ((n_legs,) if n_legs else range(2, run.n_max + 1)):
        for l_in in run.places(n):
            for sigma1 in (1, -1):
                rk = run.rooms(l_in, n, sigma1)
                if any(r < R - _TOL for r, _ in rk):
                    continue
                cap = max(cap, 2 * sum(r for r, _ in rk) - 2 * R + R * (n * math.pi - 2 * n))
    return cap


def _assemble(full, blocks) -> list[tuple]:
    out: list[tuple] = []
    for idx, p in enumerate(full):
        out += blocks.get(idx, [p])
    return out


def _split_legs(total, weights):
    """总腿数按权重分给各段 (最大余数法), 每段 ≥ 2; 分不开 → None。"""
    k = len(weights)
    if total < 2 * k:
        return None
    spare, w = total - 2 * k, sum(weights)
    raw = [spare * wi / w for wi in weights]
    base = [int(r) for r in raw]
    for i in sorted(range(k), key=lambda i: raw[i] - base[i], reverse=True)[:spare - sum(base)]:
        base[i] += 1
    return [2 + b for b in base]


def _finite(c) -> float:
    return c if math.isfinite(c) else 1e12


def _fill_subset(full, sub, caps, R, X, n_legs, region, clr, reasons):
    """把 X 分到 sub 里的几条直段: 容量小的先放 (占的地方少), 每段的份额 = 剩余 × 该段当前容量 / 剩余各段当前容量之和 (容量随已放的块
    重算), 最大的一段最后吃精确余数; 先放好的块进后面块的障碍集 → 拐角处两块的腿互相垂直也不会交叉。"""
    order = sorted(sub, key=lambda i: caps[i])
    names = ", ".join(f"#{i}" for i in order)
    if n_legs:
        split = _split_legs(n_legs, [_finite(caps[i]) for i in order])
        if split is None:
            reasons.append(f"runs {names}: {n_legs} legs cannot give every run >= 2")
            return None
        legs = dict(zip(order, split))
    else:
        legs = {i: 0 for i in order}
    rem, extra, blocks, total_legs, slack = X, [], {}, 0, math.inf
    for idx, i in enumerate(order):
        rest = order[idx:]
        runs_now = {j: _Run(full, j, R, region, clr, extra) for j in rest}
        caps_now = {j: _capacity(runs_now[j], legs[j]) for j in rest}
        dead = [j for j, c in caps_now.items() if c == -math.inf]
        if dead:
            reasons.append(f"runs {names}: run #{dead[0]} has no room left once the other blocks are placed")
            return None
        if sum(caps_now.values()) < rem - _TOL:
            reasons.append(f"runs {names}: together they reach at most +{X - rem + sum(caps_now.values()):.6g} um, "
                           f"{X:.6g} needed")
            return None
        tot = sum(_finite(c) for c in caps_now.values())
        share = rem if idx == len(order) - 1 else rem * _finite(caps_now[i]) / tot
        got, why = _fill(runs_now[i], share, legs[i])
        if got is None:
            reasons.append(f"runs {names}: {why}")
            return None
        n, sl, parts = got
        blocks[i] = parts
        extra = extra + parts
        rem -= share
        total_legs += n
        slack = min(slack, sl)
    new_full = _assemble(full, blocks)
    viol = _self_clear(_emit(new_full), R, clr)
    if viol is not None:
        reasons.append(f"runs {names}: the meanders come within {viol[2]:.6g} um of each other or of the path (< 2R)")
        return None
    return len(order), total_legs, slack, new_full


def _fill_runs(full, R, X, n_legs, region, clr, lead_idx, errors, label):
    """给骨架 full 补 X µm: 先试单段 (腿最少、余量最大者胜), 单段都装不下再把 X 分到 2, 3, … 段 (按容量之和从大到小试子集)。
    可行 → (块数, 总腿数, 最小余量, 新部件列表); 否则 None 并把原因记进 errors。显式 n_legs = 总腿数, 多段时按容量分。"""
    runs = [i for i, p in enumerate(full)
            if p[0] == "line" and i not in lead_idx and math.hypot(p[3] - p[1], p[4] - p[2]) >= 4 * R - _EPS]
    if not runs:
        errors.append(f"{label}: no straight run >= 4R = {4 * R:.6g} um to meander on")
        return None
    base = {i: _Run(full, i, R, region, clr) for i in runs}
    reasons: list[str] = []
    singles = []
    for i in runs:
        got, why = _fill(base[i], X, n_legs)
        if got is None:
            reasons.append(why)
        else:
            singles.append((got[0], -got[1], i, got[2]))
    for n, neg, i, parts in sorted(singles):
        new_full = _assemble(full, {i: parts})
        viol = _self_clear(_emit(new_full), R, clr)
        if viol is None:
            return 1, n, -neg, new_full
        reasons.append(f"straight run #{i}: its meander comes within {viol[2]:.6g} um of segment #{viol[1]} (< 2R)")
    caps = {i: _capacity(base[i], 0) for i in runs}
    pool = sorted((i for i in runs if caps[i] > 0), key=lambda i: -caps[i])
    for k in range(2, len(pool) + 1):
        for sub in sorted(combinations(pool, k), key=lambda s: -sum(_finite(caps[i]) for i in s)):
            got = _fill_subset(full, sub, caps, R, X, n_legs, region, clr, reasons)
            if got is not None:
                return got
    total = sum(_finite(caps[i]) for i in pool)
    errors.append(f"{label}: no single straight run holds +{X:.6g} um"
                  + (f", and splitting it across all {len(pool)} runs reaches at most +{total:.6g} um" if len(pool) > 1 else "")
                  + " — " + "; ".join(reasons[:3]))
    return None


# ---------------------------------------------------------------- 入口
def plan_cpw(start, end, R, length=None, region=None, n_legs=0, width=0.0, lead=0.0, axis=0.0) -> list[tuple]:
    """两位姿之间的 CPW 中心线原语。``start`` / ``end`` = ``(x, y, heading)`` **行进方向** (rad):
    start 的 heading = from 口外法向, end 的 heading = to 口外法向 + π (驶入 to 口)。
    ``R`` = 弯半径 (µm) 或 ``"auto"`` (取最大可行的整数半径, 见 ``auto_radius``)。
    ``length`` = 目标画出长度 (µm, 已减两端等效长度, 含两段引出), None = 最短骨架。``region`` = 矩形或矩形列表 (并集)。
    ``n_legs`` 只在给 ``length`` 时有意义, 0 = 自动 (须给 region); 多段分摊时是总腿数。``width`` = CPW 总宽 (中心导体 + 两缝), 区域检查内缩其半。
    ``lead`` = 两端各先沿端口法向直走的长度 (µm), 弧只在其后开始; 0 = 弧从端口面起。
    ``axis`` = 曼哈顿框架角度 (deg, 默认 0 = 横平竖直) 或 ``"free"`` (Dubins 自由角)。
    装不下时 raise 并逐骨架说明; 给定的 R 装不下而更小的 R 装得下时, 提示里给出能装下的最大 R。"""
    if isinstance(R, str) and R == "auto":
        R = auto_radius(start, end, length, region, n_legs, width, lead, axis)
    return _plan_impl(start, end, R, length, region, n_legs, width, lead, axis, with_hint=True)


def auto_radius(start, end, length=None, region=None, n_legs=0, width=0.0, lead=0.0, axis=0.0, R_max=None) -> float:
    """**最大可行弯半径** (整数 µm)。可行性对 R 单调递减 (R 越小越好装: 骨架条件 dx ≥ R 等放松、腿装得更多、余量 ≥ R 更容易), 所以唯一有
    意义的最优是「能装下的最大 R」—— 弯越缓寄生越小。在整数区间 [⌈width⌉, ⌊R_max⌋] 上二分, 每步跑一次完整规划 (~10 步);
    ``R_max`` 默认 = min(region 外框短边, 两口距离) / 2。下界 ⌈width⌉ (弯内径 ≥ 半个总宽) 都不行 → raise 带那次的原因。"""
    if isinstance(width, bool) or not (isinstance(width, (int, float)) and math.isfinite(width) and width >= 0):
        raise QuantumDslError(f"route: CPW total width must be a finite number >= 0, got {width!r}")
    dist = math.hypot(end[0] - start[0], end[1] - start[1])
    if R_max is None:
        rects = _parse_region(region)
        R_max = dist / 2
        if rects is not None:
            xs = [v for r in rects for v in (r[0], r[2])]
            ys = [v for r in rects for v in (r[1], r[3])]
            R_max = min(R_max, (min(max(xs) - min(xs), max(ys) - min(ys))) / 2)
    lo, hi = max(1, math.ceil(width - 1e-9)), math.floor(R_max + 1e-9)
    if hi < lo:
        raise QuantumDslError(f"route: R: auto — the search range is empty: the smallest sane radius {lo} um (>= the CPW "
                              f"width {width:.6g}) exceeds R_max {R_max:.6g} um (half the region's short side / port distance)")
    last_err: list[str] = []

    def ok(R) -> bool:
        try:
            _plan_impl(start, end, float(R), length, region, n_legs, width, lead, axis, with_hint=False)
            return True
        except QuantumDslError as exc:
            last_err[:] = [str(exc)]
            return False
    if not ok(lo):
        raise QuantumDslError(f"route: R: auto — even R = {lo} um (the smallest sane radius, >= the CPW width) fails: "
                              + last_err[0].removeprefix("route: "))
    while lo < hi:                                     # 不变量: ok(lo); 找最大的 ok
        mid = (lo + hi + 1) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid - 1
    return float(lo)


def _plan_impl(start, end, R, length, region, n_legs, width, lead, axis, with_hint) -> list[tuple]:
    if not (isinstance(R, (int, float)) and not isinstance(R, bool) and math.isfinite(R) and R > 0):
        raise QuantumDslError(f"route: R must be a positive finite number or 'auto', got {R!r}")
    if length is not None and not (math.isfinite(length) and length > 0):
        raise QuantumDslError(f"route: length must be positive, got {length!r}")
    if isinstance(width, bool) or not (isinstance(width, (int, float)) and math.isfinite(width) and 0 <= width < 2 * R):
        raise QuantumDslError(f"route: CPW total width {width!r} um (centre + 2 gaps) must be >= 0 and < 2*R = {2 * R:.6g} "
                              f"— a bend's inner edge would have radius <= 0; larger R or a narrower CPW")
    if isinstance(n_legs, bool) or n_legs != int(n_legs) or n_legs < 0:
        raise QuantumDslError(f"route: n_legs must be an integer >= 0 (0 = auto), got {n_legs!r}")
    n_legs = int(n_legs)
    rects = _parse_region(region)
    if length is not None and n_legs == 0 and rects is None:
        raise QuantumDslError("route: n_legs: 0 (auto) needs a region: to size the meander against — give region: "
                              "or an explicit n_legs")
    if isinstance(lead, bool) or not (isinstance(lead, (int, float)) and math.isfinite(lead) and lead >= 0):
        raise QuantumDslError(f"route: lead must be a finite number >= 0, got {lead!r}")
    free_axis = isinstance(axis, str) and axis == "free"
    if not free_axis and (isinstance(axis, bool) or not (isinstance(axis, (int, float)) and math.isfinite(axis))):
        raise QuantumDslError(f"route: axis must be an angle in degrees (Manhattan frame, 0 = horizontal/vertical) "
                              f"or 'free' (Dubins), got {axis!r}")
    if math.hypot(end[0] - start[0], end[1] - start[1]) < _EPS:
        raise QuantumDslError("route: start and end coincide")

    (x0, y0, t0), (x1, y1, t1) = start, end
    s2 = (x0 + lead * math.cos(t0), y0 + lead * math.sin(t0), t0)      # 引出后的位姿: 骨架在 s2 → e2 之间做
    e2 = (x1 - lead * math.cos(t1), y1 - lead * math.sin(t1), t1)
    pre, post = _line(x0, y0, s2[0], s2[1]), _line(e2[0], e2[1], x1, y1)
    reg = _Region(rects, width / 2) if rects is not None else None
    clr = 2 * R
    skels = _dubins_skeletons(s2, e2, R) if free_axis else _manhattan_skeletons(s2, e2, R, math.radians(axis), reg)
    ranked = sorted(((_turns(p), path_length(p), lab, p) for lab, p in skels), key=lambda c: (c[0], c[1]))

    errors: list[str] = []
    k = 0
    while k < len(ranked):                                             # 同 (转弯数, 长度) 的一组由填充结果定胜负
        group = [ranked[k]]
        while k + len(group) < len(ranked) and ranked[k + len(group)][0] == group[0][0] \
                and abs(ranked[k + len(group)][1] - group[0][1]) < _TOL:
            group.append(ranked[k + len(group)])
        k += len(group)
        best = None
        for turns, skel_len, lab, parts in group:
            full = pre + parts + post
            label = f"{lab}, {skel_len + path_length(pre) + path_length(post):.6g} um"
            sk = _emit(full)
            why = reg.violation(sk) if reg is not None else None
            if why is not None:
                errors.append(f"{label}: {why}")
                continue
            viol = _self_clear(sk, R, clr)
            if viol is not None:
                errors.append(f"{label}: segments #{viol[0]} and #{viol[1]} come within {viol[2]:.6g} um of each other "
                              f"(< 2R = {clr:.6g})")
                continue
            total = path_length(full)
            if length is None or abs(length - total) <= _TOL:
                cand = (0, 0, math.inf, full)
            elif length < total:
                errors.append(f"{label}: target {length:.6g} um is shorter than this path (incl. 2 x lead {lead:.6g}) — "
                              f"lengthen the target, shorten lead or move the ports")
                continue
            else:
                lead_idx = {0 if pre else -1, len(full) - 1 if post else -1}
                cand = _fill_runs(full, R, length - total, n_legs, reg, clr, lead_idx, errors, label)
                if cand is None:
                    continue
            if best is None or (cand[0], cand[1], -cand[2]) < (best[0], best[1], -best[2]):   # 块少 → 腿少 → 余量大
                best = cand
        if best is not None:
            prims = _emit(best[3])
            why = reg.violation(prims) if reg is not None else None
            if why is not None:
                raise QuantumDslError(f"route: internal: planned path fails its own region check — {why}")
            viol = _self_clear(prims, R, clr)
            if viol is not None:
                raise QuantumDslError(f"route: internal: planned path fails its own clearance check — segments #{viol[0]} "
                                      f"and #{viol[1]} are {viol[2]:.6g} um apart (< 2R)")
            if length is not None and abs(path_length(prims) - length) > _TOL:
                raise QuantumDslError(f"route: internal: drawn length {path_length(prims):.9g} != target {length:.9g}")
            return prims
    if length is None:
        hint = "smaller R / a larger region / another axis / a shorter lead"
    elif n_legs:
        hint = "more or fewer legs (n_legs) / smaller R / a larger region / another axis"
    else:
        hint = ("smaller R / a larger region / a longer or shorter target / another axis "
                "(every leg count 2..S/2R was tried on every straight run and on every split across runs)")
    shown = errors[:_MAX_REPORT] + ([f"... and {len(errors) - _MAX_REPORT} more candidate(s)"] if len(errors) > _MAX_REPORT else [])
    if with_hint and R > math.ceil(width - 1e-9):
        try:                                           # 更小的 R 装得下吗? 给出能装下的最大整数 R (只在失败路径上多跑几次规划)
            fit = auto_radius(start, end, length, region, n_legs, width, lead, axis, R_max=math.ceil(R) - 1)
            hint = f"R <= {fit:.0f} um would fit (R: auto picks it); otherwise " + hint
        except QuantumDslError:
            pass
    raise QuantumDslError("route: no feasible CPW path between the ports — " + hint + ":\n  " + "\n  ".join(shown))
