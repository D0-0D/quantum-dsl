# quantum_dsl — Current Status

每个 session 开工前读这份 + [`plan.md`](plan.md)。快照 **2026-09-18**。硬约束与跑法在 `CLAUDE.md`, 这里不重复。

## 现在有什么

- **v4.0 产品**（tag `v4.0`, 2026-08-26）: 手写 `.geo` + `*.meta.yaml` → GDS / 3D 网格 / Palace 静电 / 电容矩阵 / 逆电容 LOM 哈密顿量; 只有 Python API（`quantum_dsl.build`）。
  契约 `SPEC.md`（条目按名字）↔ `tests/`。`main` = 产品; `v3` = 旧实现（只读参考）; `v4-dev` = 开发痕迹与原始调研存档。
- **版图编排**（2026-09-12/13, `src/quantum_dsl/layout.py` ≈1 000 行）: `*.layout.yaml` 有序步骤实例化模板（`examples/lib/<name>.geo` 局部坐标 + `<name>.yaml` 接口）
  或混入手写 `.geo`, 全部写进同一个 gmsh 模型; meta 多一张 `layers:` 表。语法 `docs/grammar.md` §4, 设计稿 `docs/design/component-library.md`。
- **Chen 2025 圆盘比特 3×3**（2026-09-13）: 模板 `disc_transmon` / `bar_coupler`, 例子 `examples/chen_2025_3x3.*`（9 比特 + 12 耦合器, 21 个结条目自动生成;
  flip-chip: `ground: none`, 载片地 = `airbox.top_um: 5`）, `extract.blocks` = 12 个 SI §D 口径的孤立 QCQ 块（6 terminal）。
- **手写步骤 `connect:`**（2026-09-16）: 手写 `.geo` 认领模板画的外挂面（爪）, 与连接型模板同一条路; 对照件 `examples/chen_2025_3x3_hand`
  与模板路线 Physical 名 / GDS 多边形逐点相同。同批堵掉的静默路径: 路由体没碰到端口那一端、步骤键不按类型查、merge 文件里定义 Macro（同进程二次跑段错误）、
  分块删手写 Physical 组留残名（出网格崩）。
- **自动布线 `cpw_route` v2**（2026-09-18 下午重做, `src/quantum_dsl/route.py` 993 行 + `lib/cpw_route`, `planner: cpw`）: 两个不正对的同宽端口之间, 骨架默认走曼哈顿框架（横平竖直; 步骤键 `axis:` 转角, `axis: free` = v1 的 Dubins）, 定长时在骨架直段上放蛇形, **每个弯按该处精确余量独立外推 → 腿不等长、随沿轴可用宽度变**（余量 = 半圆到 region 外框 / 缝 / 自身直段与弧 / 已放的块的首触距离, 取样点射线 + 角点端点对偶射线 + 两弧外切, 净距 2R）, 腿数自动取最小可行, **单段装不下按容量比例分摊到多段**（先放的块进后面块的障碍集, 拐角不交叉; `n_legs` = 总腿数）; 骨架与成品都查**自身净距**（沿路间隔 ≥ πR 的两段 ≥ 2R）; **`R: auto`** = 整数二分的最大可行弯半径（失败时提示能装下的最大 R; `subsystems.R_um`）; `region:` 是矩形或**矩形并集**（缝就是障碍, L 拐角落进缝就绕路）;
  规划在芯片坐标, Python 只注入原语列表, `.geo` 用 `LIB_CPW` / `LIB_CPW_ARC` 画。**`lead`（2026-09-18 review 后加, 默认 60 µm, 步骤 `params:` 可调）**: 两端各先沿端口法向直走 lead 再拐弯, 端口面上永远是直段（之前弧从端口面起, 图上像斜着接）。
  正对共线、lead: 0 且无 region 时与 `cpw_meander` 逐段相同。设计稿 `docs/design/auto-route.md`（v2, 含五个已定决定与天花板）, 例子 `cpw_route_demo`（四对 xmon: R1 横平竖直不等腿 / R2 拼接区域绕路 / R3 自由角 / R4 `R: auto` → 70, 一张图四条路）, 测试 `test_route.py` 11 条; 调试画廊 `tools/route_gallery.py` 30 场景。
- **Chen 2025 十字例子**（2026-09-18, `examples/chen_2025_cross`）: 中心 Q11 四爪 + 4 臂比特各一爪 + 4 耦合器 = 18 导体整片一次解; 中心 = 真晶格口径 ↔ 实测 α, 臂 = SI 孤立 QCQ 口径。
  上云 (c24a1) 三档 d: **d = 4 µm 时中心 α = −190.7 MHz 命中实测 −192 ± 6**; 环境效应只 −2.5%（`docs/physics.md` §13.1）。
- **已知偏差**: QCQ 块解删掉块内比特伸向块外耦合器的爪 → 只影响多爪比特, 且只有 −2.5% E_C（十字实测, §13.1）; 互容仍是 SI 的 0.4–0.5 倍, 与 d / 环境无关, 是几何（缝 / 间隙）的账。

## 怎么跑

- 全套: `~/miniconda3/envs/qdsl313/bin/python -m pytest tests/ -q` → **51 passed / 2 skipped**（~3 min; live 两条要 Palace）。
- Chen: `compile_layout` 0.7 s、`build_gds` 1 s、单块网格 22 s。只要块就 `build(m, out, solve=True, blocks=["H01"])`（本机 8 rank ~10 min, 75 万 tets order 2）;
  不带 `blocks=` 会先给全片出 ~9M tets 网格。PNG 在 gitignore 的 `build/` 下, 本地跑一次即有。
- 上云跑法（2026-09-18 实测, c24a1 64c/128G 有 spack Palace 0.16、无 gmsh）: 本机 `build(..., solve=False)` 出 msh + json → `rr -p` 推 → 远端 `palace -np N cfg`（`OMPI_ALLOW_RUN_AS_ROOT=1`, mpirun 在 spack openmpi bin）→ `rr -f` 拉 `postpro/` → `parse_capacitance` + `solve_circuit_model`。
  规模: 十字 100/4 = 2.39 M tets / 3.34 M 未知量 / np=24 19 min / 峰值 28 GB; 3×3 整片 100/4 = 5.82 M tets / 8.12 M 未知量 / np=32 常驻 65 GB（**128 G 机装得下**）; 经验 8.5–10 GB / 百万未知量。
- sung 外部锚: `QDSL_RUN_PALACE_SUNG=1 PALACE_BIN=tools/palace_remote.sh QDSL_REMOTE_HOST=<64C+/384G 机> QDSL_PALACE_NP=32`（峰值内存 154 G, 128 G 机必 OOM）。

## 实测锚

| 例子 | 结果 |
|---|---|
| two_pads（live 回归锚） | C 对 `[[24.5324,-1.9472],[-1.9472,24.5353]]` fF <2%; 实测 123 s, 逐位相同 |
| sung_2021_device（外部锚, Elmer 标定过的替代几何） | 对 PRX 11.021058: C_Σ ×0.940–0.969（±8% 内）, β_qc +8%（±20% 内） |
| sung_2021_xmon（真版图, 无调参, 不断言） | C_Σ = 论文 ×0.874/0.701/0.873, β_qc +12~17%, **不命中**; 账 `docs/report/Aug27/04` §8 |
| **Chen 十字 d = 4 µm（整片 18 导体, 100/4 单网格）** | 中心比特 α = −190.7 MHz ↔ 实测 12 只 −192 ± 6 **命中**; f01 4.16 GHz（实测 4.03–4.25）; g_qc 55 / g_qq 2.6 MHz（设计 90 / 5）偏低 = 互容缺口; d 三点 4 / 5 / 7 → E_C 191 / 215 / 250, ∝ d^0.49; 外部锚 d = 5 ± 0.4 差 2.5σ; 网格两档 100/4 → 80/3 E_C 只移 +0.3%（§13.1） |
| Chen 3×3 整片（42 导体, d = 5, 100/4, 69 GB / 86 min） | 中心 Q11 E_C 214.5 = 十字; 角 / 边 / 中心 218.1 / 216.3 / 214.5（每爪 −1.8 MHz）; 最近邻 g_qq 3.7, 对角次近邻 0.03–0.05 MHz（SI 实测残余 ~2 MHz 非静电直接项） |
| Chen QCQ 块 H01（单网格未收敛） | 对 SI §D 11 个电容: 对地项随 d 5→7 µm 从 ×1.1–1.45 落到 ×0.9–1.2, 互容只有 SI 一半（×0.4–0.5）⇒ 缺口不在 d; E_C(q) 220→259 MHz、g_qc 66→85 MHz 夹住 SI 闭合值（209 / 71）与设计值（185 / 90）。账 `.claude/session/2609131337.md`, 产物 `.claude/chen-evidence/` |

## 开放决策

- 自动布线 v1 遗留拍板（pad↔pad 的 net 命名、CCC; 腿数已定为最小可行）; v2 天花板见设计稿 §13; 方向 1 只剩 `cpw_meander` 退不退役（`plan.md`「方向」）。
- Chen: d 标定 4.0 vs 外部锚 5 ± 0.4 的缺口归因（读出爪 / 间隙照片误差 / 网格收敛）; 互容 ×0.4–0.5 要不要做 gap ±3 µm 灵敏度。
- 等效长度 / 爪电容的来源（依赖工艺栈）; 读出焊盘进不进版图（浮岛无结, 静电前须 Schur 消掉或标 `ground::`）。

## 文档入口

`docs/README.md`; 物理口径与数值决策 `docs/physics.md`（§13 = flip-chip 与 Chen 首解, §13.1 = 十字整片解与 d 标定）; 汇报材料 `docs/report/`（04 = sung 论文验证闭环账）。
