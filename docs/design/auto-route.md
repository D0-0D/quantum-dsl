# 自动布线：`cpw_route`（`planner: cpw`）

> 一页设计稿。需求（2026-09-17）：两个**不必正对**的 CPW 端口之间，给目标总长、可用区域、最小弯半径，在区域内自动画出 CPW。
> 实现 = `src/quantum_dsl/route.py`（纯 math 规划器）+ `examples/lib/cpw_route.{yaml,geo}`（模板）+ `layout.py` 的 `planner:` 分支；
> 契约条目「自动布线」↔ `tests/test_route.py`；例子 `examples/cpw_route_demo.{layout,meta}.yaml`。语法见 [`../grammar.md`](../grammar.md) §4.1 / §4.2 / §4.3。

## 输入

| 来源 | 量 | 说明 |
|---|---|---|
| 两个端口（`from` / `to`） | 位置、外法向、宽、`leq`、层 | 只要求**同宽、同层**，不要求正对。`from` 口外法向 = 出发行进方向；`to` 口外法向 + π = 驶入方向 |
| 步骤 `length:` | 目标总长 | 沿用现有机制（`fixed` / `quarter_wave` / `half_wave`，减两端 `leq` 后注入 `L`）；不给 = 最短路 |
| 步骤 `region:` | `[x0, y0, x1, y1]` | 芯片坐标矩形，可选；给了就校验全部原语（弧按 ≤5° 采样）**含缝宽**（内缩 `w/2 + gap`）落在其内 |
| 模板参数 | `R` 最小弯半径、`n_legs` 腿数（0 = 自动）、`gap` 缝宽 | `planner: cpw` 模板必须声明这三个参数（加载时查） |

## 输出

中心线原语序列，**只用 `.geo` 宏库已有的两种形状**：`("line", x1, y1, x2, y2)` → `LIB_CPW`；`("arc", cx, cy, R, a0, a1)` → `LIB_CPW_ARC`
（每段 |a1 − a0| ≤ π/2，长弧拆段；a0 → a1 增 = 逆时针）。Python 不发射 `.geo` 文本，只把原语按列展开成 gmsh 解析器**列表变量**注入：
`_rt_n` 段数、`_rt_kind(k)` 0 直段 / 1 弧、`_rt_p0(k)…_rt_p4(k)` = 直段 (x1, y1, x2, y2, 0) / 弧 (cx, cy, R, a0, a1)；
`cpw_route.geo` 用 `For` 循环逐段 `Call` 宏，先 `_lib_w = w` 画中心导体，再 `_lib_w = w + 2·gap` 画缝工具面，`cpw_length` 累加
直段长与 `R·|Δa|`。记账走现有 `outputs.length` 闭合（画出长度 ≠ 注入 `L` 即 raise）；`subsystems` 那条多出 `route_primitives`。

位姿 = **恒等**：规划在芯片坐标里做（两口坐标直接喂规划器），所以 `region` 不必变换；`mirror:` 对它无意义 → raise。

## 算法（`route.plan_cpw(start, end, R, length, region, n_legs, width)`）

1. **Dubins CSC 四型**：出口位姿与入口位姿各挂左 / 右两个半径 `R` 的圆，LSL / RSR 取外公切线、LSR / RSL 取内公切线（圆心距 < 2R 时无解跳过），
   得四条「弧 – 直段 – 弧」候选，按长度升序。
2. **定长**：给了 `length` 时把中间直段 `S` 换成蛇形——与 `cpw_macros.geo` 的 `LIB_CPW_MEANDER` **同一闭式**：引入直段
   `lead = (S − 2Rn)/2`、90° 弧、n 条垂直腿（首末腿 `amp − R`，中间腿 `2·amp`）、腿间 180° 弯（两段 90°）、90° 弧回轴、引出直段；
   振幅 `amp = (L − S + 2Rn − nπR + 2R) / (2(n − 1))`，`L` = 目标减去两端弧长。先弯向轴的哪一侧两种都试（有 `region` 时），取落在区域内的一侧。
   `n_legs: 0` = 从 2 起递增，取**第一个**（即最小的）能落进区域的 n（振幅随 n 单调减，所以最小 n 即最大振幅可行解）；没给 `region` 则必须显式给 `n_legs`。
3. **区域**：候选按长度顺序逐条实现并校验；第一条全部原语（含缝宽内缩）落在矩形内的胜出。
4. **全部失败 → raise `QuantumDslError`**，逐候选列出原因：哪一段出界多少 µm、目标短于最短路、振幅 ≤ R（装不下）、腿太多（`2Rn > S`），并给建议（加腿 / 缩 R / 放大区域 / 加长目标）。
   非法输入（`R ≤ 0`、`region` 非 4 数或反向、`n_legs` 非整数）同样 raise，不修成默认值。

## 限制（`route.py` 顶部 `# ponytail:` 注释同步列出）

- 只做**矩形**区域，不做多边形区域、不避障（升级路径：区域改为多边形做 point-in-polygon 采样，接口不变）。
- 只做 CSC 四型，不做 CCC（LRL / RLR）：两口距离 < 4R 时 CSC 不一定最短，但仍可行。
- 不做 taper / 变宽：两口必须同宽（`_connect_pose` 查）；不做多路由避让（两条 `cpw_route` 交叉由现有短路检查抓，不会静默）。
- 蛇形只在 Dubins 的中间直段上展开，两端弧不参与定长调节；直段太短装不下时 raise，不会自动改变 Dubins 类型以外的东西。

## 与手写 `.geo` 的分工

| 要画的 | 用什么 |
|---|---|
| 两口正对共线的定长蛇形 | `cpw_meander`（局部坐标模板，仍保留） |
| 两口**不正对**、区域内、可定长、G1 连续的 CPW | `cpw_route`（本稿） |
| 其它任何形状（多段折线、绕障、变宽、非 CPW 连接） | 手写 `.geo` 步骤 + `connect:`（grammar §4.1；例 `chen_2025_3x3_hand`） |

自动布线不取代手写：它只回答「两口之间、区域内、定长」这一个问题，答案是直段 + 圆弧序列；用户看不顺眼随时可以把同一对端口改成手写路线。

## 退化一致性（回归锚）

两口正对共线时四型 Dubins 都退化为零弧 + 直段 `S = D`，蛇形闭式又与 `LIB_CPW_MEANDER` 逐项相同，所以同 `R` / `n_legs` / `L` 下
`cpw_route` 与 `cpw_meander` 画出**逐段相同**的几何：`tests/test_route.py::test_cpw_route_degenerates_to_cpw_meander_when_ports_face`
断言两者记账长度相等（≤ 1e-9 相对）且 GDS 多边形（包围盒 + 面积）逐个相同。改 `LIB_CPW_MEANDER` 或 `_meander_along` 任一侧的闭式都会把这条测试打红。
