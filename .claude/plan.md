# quantum_dsl — Plan

Backlog 只放**尚未做**的事; 已落地的看 [`status.md`](status.md), 踩过的坑看文末「已了结」。按需立项, 不是排期。
Legend: `[ ]` not started · `[~]` in progress · `[x]` done。

## 方向（2026-09-17 与用户对齐）

1. **连接型路由收窄为直线, 其余形状手写 `.geo`。** 现状: `lib/cpw_meander` 与 `cpw_macros.geo` 里的蛇形算法, 是 8/27 工作树 `cpw-meander`
   的 `CPW_MEANDER` 加前缀搬进版图编排的; 「两口必须正对」也随之进了设计稿 §1.4、SPEC 与 grammar。用户 9/12 否的是「从坐标出发」,
   没否正对; 今天明确: 期望的状态是工作树内容不进 main, 连接型只剩直线, 其它自己拿 `.geo` 画（现成写法 `examples/chen_2025_3x3_hand`）。
2. **自动布线（2026-09-17 提出, 2026-09-18 落地）**: 两口只需同宽; 给目标长度（减两端等效长度）、可用区域、最小曲率半径,
   算法在区域内自动画出 CPW, 连接**不一定正对**的两口。实现 = `src/quantum_dsl/route.py`（Dubins CSC 四型 + 中段直段换蛇形, 纯 math）
   + 模板 `lib/cpw_route`（`planner: cpw`, `.geo` 按注入的原语列表 Call `LIB_CPW` / `LIB_CPW_ARC`）+ 步骤键 `region:`; 设计稿 `docs/design/auto-route.md`;
   例子 `cpw_route_demo`; 测试 `tests/test_route.py`。两口正对共线时与 `cpw_meander` 逐段相同（退化一致性有测试锚）。
   **待拍板**: ① 自动腿数取「能装进 region 的最小 n」（稀疏大振幅）还是最大 n（紧凑）—— 一行改; ② demo 不是 pad↔pad, 因为两岛端没有 net 命名规则（`_net` raise）,
   馈线类 pad↔pad 要先定规则; ③ 只做 CSC, 两口距 < 4R 时不保证最短（可行）。
   对方向 1 的影响: `LIB_CPW_ARC` 与 `length:` / 路由 `subsystems` 记账都有了消费者（`cpw_route`）→ 方向 1 的 ①③ 不必再删; 剩下的问题只是 `cpw_meander` 要不要退役（它已是 `cpw_route` 的退化情形, 但退化测试拿它当锚）。

## Backlog

- [ ] **连接型收窄为直线**（方向 1 的落地; ①③ 拍板后做 —— 注意方向 2 落地后 `LIB_CPW_ARC` / `length:` 已有消费者, ①③ 的「删」选项基本失效, 只剩 `cpw_meander` 退不退役）:
      ① 删 `lib/cpw_meander.{yaml,geo}`; `cpw_macros.geo` 只留 `LIB_CPW` / `LIB_CPW_ARC`（`disc_transmon.geo` 的爪用弧段）, 或连弧段一起删、爪改 OCC 原生画法 —— 拍板;
      ② 新连接型 `cpw_straight`（直段, 宽继承, 长度 = 两口距离）顶替; `xmon_readout` 例子改直段, 蛇形留给手写 `.geo` + `connect:`;
      ③ `length:` 定长闭合与路由 `subsystems` 记账没有了消费者 → 删, 或只留 `mode: fixed` 校验 —— 拍板; 端口 `leq` 保留（设计稿: 等效长度由 qubit 模板给）;
      ④ 正对检查保留（直段本来就要两口共线）, 文档改口: 不是「先用直段 / 弯把口摆正」（lib 里从没有过弯）, 而是「不正对就手写」;
      ⑤ 同步 grammar §4.1 / §4.2.5 / §4.3 / §5 #13、examples README、SPEC 行、测试减两条。
- [ ] **自动布线收尾**（方向 2 已落地, 见上）: 拍板 ①②③; 多边形区域 / 避障 / CCC 型 / taper 都标了 `# ponytail:` 天花板, 有需求再开。
- [~] **Chen 2025 phase 2**: ① 整片 42 导体一次解 —— **已做**（2026-09-18 c24a1, 100/4, 8.1 M 未知量, 69 GB, 86 min; physics §13.1 ⑤）, 中心比特与十字到 0.1 MHz 相同, 以后比特级量用十字;
      ② d 单量拟合 —— 改用实测 α 定 d（十字 d = 4.0 µm 命中）, 其余（g_qc / g_qq / 11 个 SI 电容）作预测; 用 C04 定 d 的方案作废（SI 电容与我们互差 ×0.4–1.45, 不是干净的锚）;
      ③ 网格两档 —— **已做**（十字 100/4 vs 80/3 E_C +0.3%; 3×3 100/4 vs 150/6 E_C −0.6%）; gap ±3 µm + 蓝宝石 ε 9.4/11.5 灵敏度未做（互容 ×0.4–0.5 的缺口在 gap）; ④ 读出爪（225°）/ 45° 方焊盘 / λ/4 谐振器 —— 谐振器形状按方向 1 手写或等方向 2, 等效长度来源仍开放;
      ⑤ 5 µm 薄板厚度方向的 Box 尺寸场（session 2609121024 的 G7, 粗网格实测能跑, 报数前再评估）。
- [ ] **`readout_pad.geo` demo 落仓**（2026-09-16 `.claude/session/2609161007.md`）: 9/14 演示过的 `{geo: readout_pad.geo, frame: Q00}` 文件没进仓, chen 版图头注引的就是它;
      `frame:` 至今无测试。做法: 文件进 `examples/`, chen 头注改「取消注释这一步即可」（不进正式步骤: 会多一个无结浮岛, 动 87 名 / 12 块 / 物理口径）, `tests/test_layout.py` 加一条 `frame:` 断言。
- [ ] **`targets:` 块**（issue #23）: meta 里声明期望的 C / E_C / g, `build(solve=True)` 在 results.yaml 里报偏差。sung 的「对论文 ±8%」现在写死在测试里, 应该是用户可声明的数据。
- [ ] **网格收敛扫描**（issue #26）: 每个报出的 C 值给两档网格的相对变化。实测依据: sung 契约配方（80/2）与粗档（160/10）跨 ~5.5%, 未收敛; two_pads 40/4 → 20/2 移 ~0.8%。
      可作为 `build(..., converge=True)` 或独立工具。
- [ ] **第二求解器后端**（issue #25）: ElmerFEM 交叉验证在 sung 翻案里已证明价值。2026-08-27 已验证可行路径: `ElmerGrid 14 2` 直接吃我们的 gmsh msh + `StatElecSolve`
      （P1, Calculate Capacitance Matrix, Coordinate Scaling 1e-6）, 与 Palace order-1 同网格整 3×3 相对差 1.9e-7（sif 在 `.claude/xmon-evidence/`）。剩下的只是产品化（SPICE→Maxwell 换算）。
- [ ] **Palace AMR 试点**: `Model.Refinement`（0.12 起支持 Electrostatic）是边缘 seed 网格之上的二次自适应, 不能取代 Distance/Threshold 尺寸场; 大网格（sung 级）再试,
      1–2 轮、设 MaxSize, 避开 `SaveAdaptMesh+SaveAdaptIterations` 组合（0.16.1 覆盖 bug）。
- [ ] **域尺寸扫**: sung 例子 airbox 取自 v3 实测档, two_pads 的 side=80 是刻意小型化; 给真实器件报数前应做 1×/1.5×/2× 扫（C 变化 <0.2–0.5% 验收）。
- [ ] **CI**: 默认 `pytest -q` 在 CI 上就是 39 passed / 2 skipped, 只需 Python 3.13 + `pip install -e '.[gmsh,gds,test]'`（gmsh 装得起, Palace 装不起——live 正好 skip）。
- [ ] **sung 求解产物缓存**: 一次 build 现已同时断言 C_Σ 与 β（不再重复求解）; 要在同一 results.yaml 上加断言, 直接读 `v4-dev` 分支 `.claude/n15-evidence/results_o2_contract.yaml` 归档件, 不必重跑。
- [ ] **sung 措辞订正两处**（2026-08-26 对照论文原文发现）: ① meta 头注与 physics §12 说论文 g 在「ω_c/2π=5.45 GHz 工作点」—— 论文 Table I 脚注 c 写明 g 是在 ω_1=ω_2=ω_c=4.16 GHz 处报的;
      我们 g_1c=106.8 MHz 折回 4.16 GHz 得 81.7 MHz（+13%, 与 β +8% 同源）, 频率因子解释不变、参考点要改。② physics §12 把 −4~6% 缺口归因「版图缺失」, 但几何是 v3 在 Elmer P1 上标定到论文值的 ——
      缺口首先是标定吸收 P1 正偏的必然结果（report 04 §6 ③）; 版图 / 拓扑差异解释的是「为何不该期待精确命中」。因果主次待改。
- [ ] **sung_2021_xmon 后续**（2026-08-27, `docs/report/Aug27/04` §8）: ① 描摹器亚像素边缘拟合 + 局部自适应阈值（阈值是主导测量误差: THR 143.5→120 ⇒ C_Σ +2.5/+4.0/+6.1%）;
      ② 参数化版若要再逼近描摹版, 补 Xmon 上臂旁的 L 形读出槽与 5 条走线（值 1–4% C_Σ, β 无关）; ③ 5 µm 地条的 FEM 敏感性——β 的 ±5–10% 估计未实测;
      ④ 合并时把 `.claude/xmon-evidence/`、`.claude/chen-evidence/` 迁到 v4-dev（sung 证据的惯例）; ⑤ 要不要给 xmon 加一条只记录不断言的 live 测试（它是预测不是判据）。

## 已了结, 别重新踩

- **契约编号 Nxx 已清除（2026-09-17）**: v4.0 收口时是有意保留的（`447590d` 提交信息明写「表的测试列改指新测试函数」, 编号照留）, 之后版图编排、Chen 模板又各叠了一个编号;
  现在 SPEC 条目按名字引用, 测试 docstring 写「契约「名」」。别再往 SPEC 加编号。session log 是历史, 不改。
- **「两口正对」的来历**: 8/27 工作树 `CPW_MEANDER_PORTS`（用户: cpw 起始角必须是 pad 的面）→ 设计稿 v3 §1.4 → `layout.py` `_connect_pose`。它是端点约束, 不是算法能力; 处置见「方向 1」。
- Palace order 2 多 rank「静默掉 rank」（v3 issue #22）: 64C 裸机 np=4/32 均 rc=0 且 C 一致到 1e-12 —— 是 v3 运行环境 / 构建问题, 不是 Palace bug, 不必为它保留分块降规模。
- OCC 共面布尔 / ε-nudge / fragment scale-ladder（v3 issues #18 #24）: 零厚度片 imprint 路线下没有布尔减, 这一整类失效结构性消失。
- 「Palace 拒绝内部面 Terminal」（v3 判断）: 误诊。根因是作者 Physical 组在 imprint 路径下存活并与实现组重叠 → 同一面两条边界元; 捕获后 `removePhysicalGroups()` 即愈。
- WSL 上 MPI_Init 挂死: hwloc gl 插件探测 X display; `HWLOC_COMPONENTS=-gl` 根治, 裸机不需要。
