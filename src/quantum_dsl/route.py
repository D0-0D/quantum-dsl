# -*- coding: utf-8 -*-
"""自动布线规划器 (契约「自动布线」): 两个**不必正对**的 CPW 端口之间, 在矩形区域内, 画一条 G1 连续、
可定长的中心线 = 直段 + 圆弧序列。纯 math, 不碰 gmsh (import 纯度): 输出的原语由模板 ``lib/cpw_route.geo``
用 ``LIB_CPW`` / ``LIB_CPW_ARC`` 逐段画成面, Python 只注入数字, 不发射 ``.geo`` 文本。

算法:

* **Dubins CSC**: 出口 (from 口外法向) 与入口 (to 口外法向 + π, 「驶入」) 两个位姿, 半径 R 的 LSL / LSR / RSL / RSR
  四型各算一条, 按长度排序, 取第一条能实现 (装得下 / 落在区域内) 的。
* **定长**: 给了 ``length`` 时把中间直段 S 换成蛇形 —— 与 ``cpw_macros.geo`` 的 ``LIB_CPW_MEANDER`` 同一闭式
  (引入直段 + 90° 弧 + n 腿 + 180° 弯 + 引出直段, 振幅由 L 解出), 所以两口正对共线时输出与 ``cpw_meander`` 模板逐段相同
  (退化一致性, ``tests/test_route.py``)。``n_legs=0`` = 自动取 ≥2 中能落进区域的最小 n (须给 region); 蛇形先弯向哪一侧
  两种都试, 取落在区域内的那一侧。
* **区域**: ``region=[x0, y0, x1, y1]`` (芯片坐标矩形) 时全部原语 (弧按采样点) 内缩 ``width/2`` 后须落在矩形内,
  否则 raise (报哪一段、出界多少、怎么改)。装不下 (振幅 ≤ R / 目标短于最短路 / 腿太多) 同样 raise。

原语 (与 ``LIB_CPW_ARC`` 同约定, 每段弧 |a1 − a0| ≤ π/2, 长弧拆段):
``("line", x1, y1, x2, y2)`` / ``("arc", cx, cy, R, a0, a1)`` (a0 → a1 增 = 逆时针)。

# ponytail: 只做矩形区域 + CSC 四型 + 定长蛇形。天花板: 不做多边形区域 / 避障 (要的话换成对区域多边形做 point-in-polygon
#   采样, 接口不变), 不做 CCC 型 (两口距离 < 4R 时 CSC 不一定最短, 但仍可行), 不做 taper / 变宽 (两口必须同宽, layout.py 查)。
"""

from __future__ import annotations

import math

from .errors import QuantumDslError

__all__ = ["plan_cpw", "path_length"]

_HALF_PI = math.pi / 2
_EPS = 1e-9


def path_length(prims) -> float:
    """原语序列的中心线总长 (µm), 与模板 ``.geo`` 里 ``cpw_length`` 的累加口径相同。"""
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


def _dubins_csc(start, end, R) -> list[tuple]:
    """四型 CSC 候选, 每条 = (总长, 类型, 弧1 (cx, cy, a0, a1), 直段 (x1, y1, x2, y2), 弧2)。按总长升序。"""
    x0, y0, t0 = start
    x1, y1, t1 = end
    out = []
    for kind in ("LSL", "RSR", "LSR", "RSL"):
        s0, s1 = (1 if kind[0] == "L" else -1), (1 if kind[2] == "L" else -1)   # +1 逆时针 (左), −1 顺时针 (右)
        # 圆心 = 位姿点 + R · (左法向 · s)
        csx, csy = x0 - s0 * R * math.sin(t0), y0 + s0 * R * math.cos(t0)
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
        # 圆上位置角: 行进方向 φ 在左圆 (s=+1) 上位于 φ − π/2, 右圆上位于 φ + π/2
        a_s0, a_s1 = t0 - s0 * _HALF_PI, phi - s0 * _HALF_PI
        a_e0, a_e1 = phi - s1 * _HALF_PI, t1 - s1 * _HALF_PI
        d1 = (s0 * (a_s1 - a_s0)) % (2 * math.pi)     # 沿行进方向扫过的正角
        d2 = (s1 * (a_e1 - a_e0)) % (2 * math.pi)
        if d1 > 2 * math.pi - 1e-9:
            d1 = 0.0
        if d2 > 2 * math.pi - 1e-9:
            d2 = 0.0
        p1 = (csx + R * math.cos(a_s1), csy + R * math.sin(a_s1))
        p2 = (cex + R * math.cos(a_e0), cey + R * math.sin(a_e0))
        out.append((R * (d1 + d2) + S, kind,
                    (csx, csy, a_s0, a_s0 + s0 * d1), (p1[0], p1[1], p2[0], p2[1]),
                    (cex, cey, a_e0, a_e0 + s1 * d2)))
    return sorted(out, key=lambda c: c[0])


def _meander_along(x, y, th, S, L, R, n, sg) -> list[tuple]:
    """从 (x, y) 沿切向 th 出发、轴长 S、总长 L 的蛇形 —— 与 ``LIB_CPW_MEANDER`` 同一闭式 (引入直段 + 90° 弧 +
    n 腿 + 180° 弯 + 引出直段, 振幅 amp 由 L 解出); ``sg`` = +1 先弯向左 (宏的口径), −1 镜像到轴另一侧。装不下 raise。"""
    if n < 2 or n != int(n):
        raise QuantumDslError(f"route: n_legs = {n} must be an integer >= 2")
    if 2 * R * n > S + _EPS:
        raise QuantumDslError(
            f"route: {n} legs of radius {R} need 2*R*n = {2 * R * n:.6g} um of straight run but the shortest path "
            f"has only {S:.6g} um between its end arcs — fewer legs (n_legs) or smaller R")
    amp = (L - S + 2 * R * n - n * math.pi * R + 2 * R) / (2 * (n - 1))
    if amp <= R:
        raise QuantumDslError(
            f"route: target length {L:.6g} um too short for n_legs = {n}, R = {R} (meander amplitude {amp:.6g} <= R): "
            f"fewer legs, smaller R or a longer target")
    tx, ty = math.cos(th), math.sin(th)
    nx, ny = -ty * sg, tx * sg                       # 蛇形「左」法向 (sg = −1 时翻到轴另一侧)
    lead = (S - 2 * R * n) / 2
    prims: list[tuple] = []
    px, py = x + lead * tx, y + lead * ty
    prims += _line(x, y, px, py)
    cx, cy = px + R * nx, py + R * ny
    prims += _arc(cx, cy, R, th - sg * _HALF_PI, th)                 # 90° 弧转向 n
    px, py = cx + R * tx, cy + R * ty
    s = 1
    for k in range(1, n + 1):
        h = amp - R if k in (1, n) else 2 * amp
        qx, qy = px + s * h * nx, py + s * h * ny
        prims += _line(px, py, qx, qy)
        px, py = qx, qy
        cx, cy = px + R * tx, py + R * ty                            # 弯: 圆心在轴向前方 R 处
        a0, a1 = th + math.pi, th + math.pi - s * sg * _HALF_PI
        prims += _arc(cx, cy, R, a0, a1)
        if k < n:                                                    # 180° 弯的后半段, 掉头
            prims += _arc(cx, cy, R, a1, th + math.pi - s * sg * math.pi)
            px, py = cx + R * tx, cy + R * ty
            s = -s
    px, py = cx + s * R * nx, cy + s * R * ny                        # 最后一个 90° 弧回到轴上
    ex, ey = x + S * tx, y + S * ty
    prims += _line(px, py, ex, ey)
    return prims


def _samples(p):
    """原语上的检查点: 直段两端; 弧按 ≤ 5° 一点采样 (含两端)。"""
    if p[0] == "line":
        return [(p[1], p[2]), (p[3], p[4])]
    _, cx, cy, R, a0, a1 = p
    m = max(2, math.ceil(abs(a1 - a0) / math.radians(5)) + 1)
    return [(cx + R * math.cos(a0 + (a1 - a0) * k / (m - 1)), cy + R * math.sin(a0 + (a1 - a0) * k / (m - 1)))
            for k in range(m)]


def _check_region(prims, region, inset) -> str | None:
    """全部原语 (含宽度 inset) 落在矩形内 → None; 否则返回一句出界诊断。"""
    x0, y0, x1, y1 = region
    x0, y0, x1, y1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
    for i, p in enumerate(prims):
        worst = max(max(x0 - x, x - x1, y0 - y, y - y1) for x, y in _samples(p))
        if worst > 1e-6:
            return (f"segment #{i} ({p[0]}) leaves the region by {worst:.6g} um "
                    f"(region {list(region)} inset by half the CPW width {inset:.6g})")
    return None


def plan_cpw(start, end, R, length=None, region=None, n_legs=0, width=0.0) -> list[tuple]:
    """两位姿之间的 CPW 中心线原语。``start`` / ``end`` = ``(x, y, heading)`` **行进方向** (rad):
    start 的 heading = from 口外法向, end 的 heading = to 口外法向 + π (驶入 to 口)。
    ``length`` = 目标画出长度 (µm, 已减两端等效长度), None = 最短 CSC 路。``region`` = ``[x0, y0, x1, y1]``。
    ``n_legs`` 只在给 ``length`` 时有意义, 0 = 自动 (须给 region)。``width`` = CPW 总宽 (中心导体 + 两缝), 区域检查内缩其半。"""
    if not (isinstance(R, (int, float)) and math.isfinite(R) and R > 0):
        raise QuantumDslError(f"route: R must be a positive finite number, got {R!r}")
    if length is not None and not (math.isfinite(length) and length > 0):
        raise QuantumDslError(f"route: length must be positive, got {length!r}")
    if isinstance(n_legs, bool) or n_legs != int(n_legs) or n_legs < 0:
        raise QuantumDslError(f"route: n_legs must be an integer >= 0 (0 = auto), got {n_legs!r}")
    n_legs = int(n_legs)
    if region is not None:
        ok = (isinstance(region, (list, tuple)) and len(region) == 4
              and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in region)
              and region[0] < region[2] and region[1] < region[3])
        if not ok:
            raise QuantumDslError(f"route: region must be [x0, y0, x1, y1] with x0 < x1, y0 < y1, got {region!r}")
        region = [float(v) for v in region]
    if length is not None and n_legs == 0 and region is None:
        raise QuantumDslError("route: n_legs: 0 (auto) needs a region: to size the meander against — give region: "
                              "or an explicit n_legs")
    if math.hypot(end[0] - start[0], end[1] - start[1]) < _EPS:
        raise QuantumDslError("route: start and end coincide")
    cands = _dubins_csc(start, end, R)
    inset = width / 2
    errors: list[str] = []
    for total, kind, arc1, seg, arc2 in cands:
        head = _arc(arc1[0], arc1[1], R, arc1[2], arc1[3])
        tail = _arc(arc2[0], arc2[1], R, arc2[2], arc2[3])
        S = math.hypot(seg[2] - seg[0], seg[3] - seg[1])
        if length is None:
            variants = [head + _line(*seg) + tail]
        else:
            L = length - path_length(head) - path_length(tail)
            if L < S - _EPS:
                errors.append(f"{kind}: target {length:.6g} um is shorter than the shortest {kind} path "
                              f"{total:.6g} um — lengthen the target or move the ports")
                continue
            th = math.atan2(seg[3] - seg[1], seg[2] - seg[0]) if S > _EPS else start[2]
            variants = []
            ns = [n_legs] if n_legs else range(2, int(S // (2 * R)) + 1)
            for n in ns:
                try:
                    for sg in ((1, -1) if region is not None else (1,)):
                        variants.append(head + _meander_along(seg[0], seg[1], th, S, L, R, n, sg) + tail)
                except QuantumDslError as exc:
                    errors.append(f"{kind}: {exc}")
                    break                              # n 再大振幅只会更小 / 直段更不够
            if not variants and not n_legs and not errors:
                errors.append(f"{kind}: straight run {S:.6g} um fits no meander with R = {R} (2*R*2 > S)")
        why = None
        for prims in variants:
            why = _check_region(prims, region, inset) if region is not None else None
            if why is None:
                return prims
        if why is not None:
            errors.append(f"{kind}: {why}")
    hint = "more legs (n_legs) / smaller R / a larger region" if length is not None else "smaller R / a larger region"
    raise QuantumDslError("route: no feasible CPW path between the ports — " + hint + ":\n  " + "\n  ".join(errors))
