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

## 已了结, 别重新踩

- Palace order 2 多 rank「静默掉 rank」(v3 issue #22): 64C 裸机 np=4/32 均 rc=0 且
  C 一致到 1e-12 —— 是 v3 运行环境/构建问题, 不是 Palace bug, 不必为它保留分块降规模。
- OCC 共面布尔 / ε-nudge / fragment scale-ladder(v3 issues #18 #24): 零厚度片
  imprint 路线下没有布尔减, 这一整类失效结构性消失。
- 「Palace 拒绝内部面 Terminal」(v3 判断): 误诊。根因是作者 Physical 组在 imprint
  路径下存活并与实现组重叠 → 同一面两条边界元;捕获后 `removePhysicalGroups()` 即愈。
- WSL 上 MPI_Init 挂死: hwloc gl 插件探测 X display;`HWLOC_COMPONENTS=-gl` 根治,
  裸机不需要。
