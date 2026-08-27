# quantum_dsl — Plan

v4.0 契约(SPEC N0–N15)已全部满足并发布。下面是**尚未做**的方向, 都对应仍 open 的
GitHub issue 或 v4 实测中暴露的边界;按需立项, 不是排期。
Legend: `[ ]` not started · `[~]` in progress · `[x]` done。

## Backlog

- [ ] **`targets:` 块**(issue #23): meta 里声明期望的 C / E_C / g, `build(solve=True)`
      在 results.yaml 里报偏差。N15 的「对论文 ±8%」现在写死在测试里, 应该是用户
      可声明的数据。
- [ ] **网格收敛扫描**(issue #26): 每个报出的 C 值给两档网格的相对变化。实测依据:
      sung 契约配方(80/2)与粗档(160/10)跨 ~5.5%, 未收敛;two_pads 40/4 → 20/2 移
      ~0.8%。可作为 `build(..., converge=True)` 或独立工具。
- [ ] **第二求解器后端**(issue #25): ElmerFEM 交叉验证在 N15 翻案里已证明价值
      → 2026-08-27 已验证可行路径: `ElmerGrid 14 2` 直接吃我们的 gmsh msh + `StatElecSolve`(P1, Calculate Capacitance Matrix,
      Coordinate Scaling 1e-6), 与 Palace order-1 同网格整 3×3 相对差 1.9e-7(sif 在 `.claude/xmon-evidence/`)。剩下的只是产品化(输出约定 SPICE→Maxwell 换算)。
      (同网格 P1 两求解器 <1% = 管线正确性外证);目前只在 v3 的 scratchpad 里存在。
- [ ] **Palace AMR 试点**: `Model.Refinement`(0.12 起支持 Electrostatic)是边缘
      seed 网格之上的二次自适应, 不能取代 Distance/Threshold 尺寸场;大网格
      (sung 级)再试, 1–2 轮、设 MaxSize, 避开 `SaveAdaptMesh+SaveAdaptIterations`
      组合(0.16.1 覆盖 bug)。
- [ ] **域尺寸扫**: sung 例子 airbox 取自 v3 实测档, two_pads 的 side=80 是刻意
      小型化;给真实器件报数前应做 1×/1.5×/2× 扫(C 变化 <0.2–0.5% 验收)。
- [ ] **CI**: 默认 `pytest -q` 在 CI 上就是 30 passed / 2 skipped, 只需 Python 3.13 +
      `pip install -e '.[gmsh,gds,test]'`(gmsh 装得起, Palace 装不起——live 正好 skip)。
- [ ] **N15 求解产物缓存**: 一次 build 现已同时断言 C_Σ 与 β(不再重复求解);
      若要在同一 results.yaml 上加更多断言, 直接读 `v4-dev` 分支
      `.claude/n15-evidence/results_o2_contract.yaml` 归档件即可, 不必重跑。

- [ ] **sung 措辞订正两处**(写 `docs/report/04` 时对照论文原文发现, 2026-08-26): ① meta 头注与 physics §12 说论文 g
      在「ω_c/2π=5.45 GHz 工作点」—— 论文 Table I 脚注 c 写明 g 是在 ω_1=ω_2=ω_c=4.16 GHz 处报的; 我们 g_1c=106.8 MHz
      折回 4.16 GHz 得 81.7 MHz(+13%, 与 β +8% 同源), 频率因子解释不变、参考点要改。② physics §12 把 −4~6% 缺口归因
      「版图缺失」, 但几何是 v3 在 Elmer P1 上标定到论文值的 —— 缺口大小/符号首先是标定吸收 P1 正偏的必然结果(04 §6 ③);
      版图/拓扑差异(论文是接地 Xmon + 弯折 coupler, 本版图是浮动双 pad)解释的是「为何不该期待精确命中」。因果主次待改。

- [ ] **sung_2021_xmon 后续**(2026-08-27, 见 `docs/report/04` §8): ① 描摹器亚像素边缘拟合 + 局部自适应阈值(阈值是主导测量误差:
      THR 143.5→120 ⇒ C_Σ +2.5/+4.0/+6.1%); ② 参数化版若要再逼近描摹版, 补 Xmon 上臂旁的 L 形读出槽与 5 条走线(值 1–4% C_Σ, β 无关);
      ③ 5 µm 地条(qubit moat 与 coupler moat 之间)的 FEM 敏感性——β 的 ±5–10% 估计未实测; ④ 合并时把 `.claude/xmon-evidence/` 按 N15 惯例迁到 v4-dev;
      ⑤ 要不要给 xmon 加一条只记录不断言的 live 测试(它是预测不是判据)。

## 已了结, 别重新踩

- Palace order 2 多 rank「静默掉 rank」(v3 issue #22): 64C 裸机 np=4/32 均 rc=0 且
  C 一致到 1e-12 —— 是 v3 运行环境/构建问题, 不是 Palace bug, 不必为它保留分块降规模。
- OCC 共面布尔 / ε-nudge / fragment scale-ladder(v3 issues #18 #24): 零厚度片
  imprint 路线下没有布尔减, 这一整类失效结构性消失。
- 「Palace 拒绝内部面 Terminal」(v3 判断): 误诊。根因是作者 Physical 组在 imprint
  路径下存活并与实现组重叠 → 同一面两条边界元;捕获后 `removePhysicalGroups()` 即愈。
- WSL 上 MPI_Init 挂死: hwloc gl 插件探测 X display;`HWLOC_COMPONENTS=-gl` 根治,
  裸机不需要。
