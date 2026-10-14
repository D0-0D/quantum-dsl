# quantum_dsl — Current Status

每个 session 开工前读这份 + [`plan.md`](plan.md)。快照 **2026-10-14**。硬约束与跑法在 `CLAUDE.md`, 这里不重复。

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
- **自动布线 `cpw_route` v2**（2026-09-18 下午重做, `src/quantum_dsl/route.py` 1084 行 + `lib/cpw_route`, `planner: cpw`）: 两个不正对的同宽端口之间, 骨架默认走曼哈顿框架（横平竖直; 步骤键 `axis:` 转角, `axis: free` = v1 的 Dubins）, 定长时在骨架直段上放蛇形, **每个弯按该处精确余量独立外推 → 腿不等长、随沿轴可用宽度变**（余量 = 半圆到 region 外框 / 缝 / 自身直段与弧 / 已放的块的首触距离, 取样点射线 + 角点端点对偶射线 + 两弧外切, 净距 2R）, 腿数自动取最小可行, **单段装不下按容量比例分摊到多段**（先放的块进后面块的障碍集, 拐角不交叉; `n_legs` = 总腿数）; 骨架与成品都查**自身净距**（沿路间隔 ≥ πR 的两段 ≥ 2R）; **`R: auto`** = 整数二分的最大可行弯半径（失败时提示能装下的最大 R; `subsystems.R_um`）; `region:` 是矩形或**矩形并集**（缝就是障碍, L 拐角落进缝就绕路）;
  规划在芯片坐标, Python 只注入原语列表, `.geo` 用 `LIB_CPW` / `LIB_CPW_ARC` 画。**`lead`（2026-09-18 review 后加, 默认 60 µm, 步骤 `params:` 可调）**: 两端各先沿端口法向直走 lead 再拐弯, 端口面上永远是直段（之前弧从端口面起, 图上像斜着接）。
  **轨道图兜底**（2026-10-01）: 模板（≤ 三折）全部不行时, 在 region 的 Hanan 式轨道图上跑 (节点, 朝向) 状态的最少转弯 Dijkstra（直段 ≥ 2R）→ 任意折数（S 形 / 迷宫走廊）; 模板能解的场景逐段不变。
  正对共线、lead: 0 且无 region 时与 `cpw_meander` 逐段相同。设计稿 `docs/design/auto-route.md`（v2, 含五个已定决定与天花板）, 例子 `cpw_route_demo`（四对 xmon: R1 横平竖直不等腿 / R2 拼接区域绕路 / R3 自由角 / R4 `R: auto` → 70, 一张图四条路）, 测试 `test_route.py` 12 条; 调试画廊 `tools/route_gallery.py` 31 场景。
- **Chen 2025 十字例子**（2026-09-18 立, **2026-10-14 新几何重做**, `examples/chen_2025_cross`）: 中心 Q11 四爪 + 读出爪 R11（`lib/readout_claw`, `resonators: drawn: claw`）+ 4 臂比特各一爪 + 4 耦合器 = 19 导体整片一次解;
  中心 = 真晶格口径 ↔ 实测 α, 臂 = SI 孤立 QCQ 口径。c24a1 三档 d: **d = 10 µm 时中心 α* = −193.0 MHz 命中实测 −192.4 ± 5.9 → d = 9.9 ± 0.7**（与 SI In bump ~10 µm 相容）;
  同 d 下 g_qc 85–97 ↔ 设计 90、g_qq 7.6 ↔ 设计 5（physics §13.2）。
- **`targets:` + 网格收敛**（2026-09-24, issue #23 / #26）: meta `targets:` 声明期望的 C_Σ / E_C / f01 / β / g + 百分比容差 → 整片 `results.yaml` 的 `validation` 段报偏差（未命中 warn, 拼错名网格化前 raise）; sung 的论文判据已搬进其 meta。`converge(meta, out, scales)` 各档同比缩放 mesh 尺寸整片求解, `convergence.yaml` = 最细两档相对变化; two_pads 80/8 → 40/4: 对角 −1.6%、非对角 +3.0%。#25（Elmer 后端）已关: 结论在 physics §12。
- **读出链路进电路模型**（2026-10-04, physics §8.1）: 无结导体三种显式处置 `circuit_model.resonators`（TL 等效 LC 节点; `drawn: full` 时 C_r 换掉 FEM 对地电容）/
  `ports`（AC 接地 + 互容给 Norton κ 与 `T1_port_us`）/ `floating`（Schur）, 不声明照旧 raise; results 多 `hamiltonian.resonators`（负载后 f_r、κ/2π、自检比 `C_gnd_fem_over_tl`）
  与 `readout`（g、χ 单边、单模 Purcell T1）; qubit 多 `f01_exact_GHz` / `anharmonicity_exact_MHz`（电荷基精确对角化, α = −E_C 在 E_J/E_C = 50 时偏 15%; 渐近 golden 不动）。
  版图波长定长路由自动生成 resonator（f_r = 画长裸频率）→ `xmon_readout` 现在 `solve=True` 能解（之前 F0 未认领 raise）; 真 Palace 13.6 s: g_qr 63 MHz, χ −0.116 MHz, f_r 6.959 GHz。
- **`tune:` FEM 在环综合**（2026-10-04, `src/quantum_dsl/tune.py`）: meta 声明旋钮 → targets 核对项（方阵）, 几何旋钮比例律 + 对数割线每轮一次 FEM, 结旋钮在缓存 C 上二分;
  终版 = 普通 layout + meta（配置即综合输出）。`examples/xmon_readout_tune.meta.yaml` 四旋钮（arm_L / ro_gap / length.f_r / E_J）真 Palace **4 次 FEM / 51 s 全部命中**。
- **馈线 κ + 两比特复用读出综合**（2026-10-14, 分支 `readout-followup`, session 2610141107）: 模板 `feed_tap`（耦合焊盘, 原点 = 馈线西沿）+ `pad` 长条馈线（meta `ports`, R = Z0/2）+ `cpw_route` **λ/2**
  （等势节点只在电压腹点对; λ/4 远端短路是电感耦合, 静电看不见）。`xmon_feedline` κ/2π 5.6 MHz / Purcell 107 µs; `xmon_feedline_tune` 五旋钮（含 `R1.length.f_r` on cpw_route、`T1.tap_h → κ`）6 次 FEM 收敛;
  `xmon_pair` 两比特臂尖直接耦合 + 两腔共馈线, 11 旋钮（g_qq 旋钮 = `Q1.at.1`, 旋钮路径可下钻列表）**7 次 FEM / 422 s 收敛**。
  同批: `transmon_from_spectrum`（f01, α → E_C, E_J; tune 第 0 步记 `closed_form`）、targets `tol:` 可逐字段、对数割线观测指数只在 law 的 ¼–4 倍内才用。
  **重网格噪声底实测**（200/20 演示网格平移重解）: κ σ ≈ 5 %、χ ≈ 3 %、C_Σ 0.3 % → tune 的 tol 须 ≥ 2σ（κ 5 % 时不收敛）; 细一档 κ −28 %（physics §8.1）。
- **已知偏差**: QCQ 块解删掉块内比特伸向块外耦合器的爪 → 只影响多爪比特（新几何: 三只爪 ≈ +5.7 fF C_Σ, 读出爪 +2.6 fF; physics §13.2）; 读出焊盘 / λ/4 蛇形 / 载片走线不画（焊盘凸台离盘边 181 µm）。
- **Chen 几何订正**（2026-10-14）: 旧几何（Nature 低清 JPEG + 标尺读错）整体偏小 ~22%; arXiv 原图 1.368 µm/px 重测 + subagent 复核 + λ/4 腔长独立印证标尺,
  模板与三个 chen 例子已按 `docs/design/paper-chen2025-geometry.md` §3.3 改（pitch 1770, 例子 d = 10）。**SI §D 电容表 ≈ 本几何在 d_eff 15–20 µm 下**, 与实测 α（d ≈ 10）不在同一 d → SI 表只作量级对照。

## 怎么跑

- 全套: `~/miniconda3/envs/qdsl313/bin/python -m pytest tests/ -q` → **64 passed / 3 skipped**（~4 min; live 两条要 Palace）。
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
| **Chen 十字 新几何（19 导体含读出爪, 100/4, 2026-10-14）** | d = 10: 中心 α* −193.0 ↔ 实测 −192.4 ± 5.9 **命中**（d = 9.9 ± 0.7）; g_qc 85–97 / g_qq 7.6 MHz ↔ 设计 90 / 5; 读出爪 E_C −2.4%; 块 + R11 网格 80/3 对照 E_C +0.3%（physics §13.2, `.claude/chen-evidence/v2_2610/`） |
| Chen 3×3 整片（**旧几何**, 42 导体, d = 5, 100/4, 69 GB / 86 min） | 中心 Q11 E_C 214.5 = 十字; 角 / 边 / 中心 218.1 / 216.3 / 214.5（每爪 −1.8 MHz）; 最近邻 g_qq 3.7, 对角次近邻 0.03–0.05 MHz（SI 实测残余 ~2 MHz 非静电直接项） |
| Chen QCQ 块 H01（新几何, d 扫 5–25） | 对 SI §D 11 个电容: d = 10 时对地 ×1.2–1.5、互容 ×0.67–0.86; 半盘对地 d ≈ 15 命中、条 / 板 d ≈ 19, 互容 @25 ×0.86–0.95 ⇒ SI 表 ≈ d_eff 15–20（旧几何时互容 ×0.4–0.5 的缺口是几何账） |

## 开放决策

- 自动布线 v1 遗留拍板（pad↔pad 的 net 命名、CCC; 腿数已定为最小可行）; v2 天花板见设计稿 §13; `cpw_meander` 退不退役待拍板（`plan.md` Backlog）。
- **Chen 3×3 要不要按新几何重做**（9 只读出爪 + 9 腔; 规模估 ~12 M 未知量 @100/4 ≈ 100 GB 贴 128 G 上限, 或 150/6 ≈ 40 GB）: 比特级量十字已给, 3×3 只多阵列级耦合。待用户拍板。
- 等效长度 / 爪电容的来源（依赖工艺栈）; 读出焊盘进不进版图（浮岛无结, 静电前须 Schur 消掉或标 `ground::`）。

## 文档入口

`docs/README.md`; 物理口径与数值决策 `docs/physics.md`（§13 / §13.1 = 旧几何账, **§13.2 = 新几何 d 标定与 SI 口径**）; 汇报材料 `docs/report/`（04 = sung 论文验证闭环账）。
