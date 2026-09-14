# quantum_dsl — Current Status

每个 session 开工前读这份 + [`plan.md`](plan.md)。快照日期 **2026-09-13**。

## 最新动态（给刚接手的人：5 分钟版）

1. **产品在哪**：`main` = v4 产品（tag `v4.0`，2026-08-26）。手写 `.geo` + `*.meta.yaml` → GDS / 3D 网格 / Palace 静电 / 电容矩阵 /
   哈密顿量（逆电容 LOM），只有 Python API（入口 `quantum_dsl.build`）。契约 = `SPEC.md` N0–N17 ↔ `tests/`。
2. **最近两天新增两层**：
   - **N16 版图编排**（2026-09-12）：`*.layout.yaml` 顶替手写 `.geo` 作几何源——一张有序步骤表，实例化模板（`examples/lib/<name>.geo`
     局部坐标几何 + `<name>.yaml` 接口）或混入手写 `.geo` 步骤，全部写进**同一个 gmsh 模型**；meta 照旧，只多一张 `layers:` 表（模板层槽位 → 芯片层）。
     实现 `src/quantum_dsl/layout.py`（≈870 行），语法 `docs/grammar.md` §4，设计稿 `docs/design/component-library.md`。
   - **N17 Chen 2025 圆盘比特 3×3**（2026-09-13）：模板 `disc_transmon`（两半盘 + 跨缝结 + 可选爪）/ `bar_coupler`（连接型：条 + 五边形 + 结）
     + 例子 `examples/chen_2025_3x3.{layout,meta}.yaml`（9 比特 + 12 耦合器，21 个结条目自动生成；**无读出结构**）。几何全部是论文
     Fig. 1a 照片量出值（`docs/design/paper-chen2025-geometry.md`，≤15 µm 的量 ±30–50%）。flip-chip：顶片无地 `ground: none`，载片地 = `airbox.top_um: 5`。
     `extract.blocks` = 12 个 SI §D 口径的孤立 QCQ 块（6 terminal）。
3. **首批数字**（本机 Palace，QCQ 块 H01，75 万 tets order 2，8 rank 570 s，**单网格未收敛**）：对 SI §D 的 11 个电容——对地项随 d 5→7 µm
   从 ×1.1–1.45 落到 ×0.9–1.2；互容始终只有 SI 的一半（×0.4–0.5）⇒ 缺口在缝 / 间隙几何或 SI 模型口径，**不在 d**。派生 E_C(q) 220→259 MHz、
   g_qc 66→85 MHz，夹住 SI 自身闭合值（209 / 71）与设计值（185 / 90）——量级检验，不是命中。账 `.claude/session/2609131337.md`，
   产物 `.claude/chen-evidence/`，物理口径 `docs/physics.md` §13。
4. **怎么跑**：`~/miniconda3/envs/qdsl313/bin/python -m pytest tests/ -q` → **35 passed / 2 skipped**（~25 s；live 两条要 Palace）。
   Chen 例子：`compile_layout` 0.7 s、`build_gds` 1 s、单块网格 22 s；整片 `build(solve=False)` 会按 100/4 给全片出网格（~9M tets），
   看图请直接 `build_gds` + `render_gds_png`（`build/chen_2025_3x3/*.png` 是本次渲染）。
5. **下一步**（`plan.md`「Chen 2025 phase 2」）：缝宽 / 盘–爪 / 条–板间隙灵敏度 → 再谈 d 单量拟合；整片 42 导体上云一次解
   （QCQ 块两两共享比特几何，**不能** `assemble()` 叠加）；读出爪 / 45° 焊盘 / λ/4 蛇形；网格两档收敛。
6. **开放决策**：等效长度 / 爪电容来源（依赖工艺栈）；读出焊盘进不进版图（浮岛无结，静电前须 Schur 消掉或标 `ground::`）。

## At a glance

| | |
|---|---|
| 版本 | **v4.0 已发布**(tag `v4.0`, 2026-08-26) + N16(2026-09-12) + N17(2026-09-13)。`main` = 产品;`v3` = 旧实现(只读参考);`v4-dev` = 开发痕迹与原始调研存档(session logs / codex 取证 / N15 原始 CSV / 原型脚本) |
| 契约 | [`SPEC.md`](../SPEC.md)(N0–N17 需求索引)↔ `tests/`(35 passed / 2 skipped;live 两条各自实测通过一次) |
| 文档 | [`docs/README.md`](../docs/README.md) 是入口;物理口径与数值决策在 `docs/physics.md`(§13 = flip-chip 与 Chen 首解),汇报材料在 `docs/report/`(04 = sung 论文验证闭环账) |
| 测试跑法 | `~/miniconda3/envs/qdsl313/bin/python -m pytest tests/ -q`;live 加 `QDSL_RUN_PALACE=1`(~4 min);sung 加 `QDSL_RUN_PALACE_SUNG=1 PALACE_BIN=tools/palace_remote.sh QDSL_REMOTE_HOST=<64C+/384G 机> QDSL_PALACE_NP=32`(峰值内存 154 G, 128G 机必 OOM) |
| 实测锚 | two_pads C 对 `[[24.5324,-1.9472],[-1.9472,24.5353]]` fF <2%;sung 对 PRX 11.021058: C_Σ ×0.940–0.969(±8% 内), β_qc +8%(±20% 内);Chen QCQ 对 SI §D: 见上 3 |
| 论文真版图(无调参) | `examples/sung_2021_xmon`(接地 Xmon×2 + 梳齿 coupler, 照片量出 ~20 个参数): C_Σ = 论文 ×0.874/0.701/0.873, β_qc +12~17%, **不命中**——与被 Elmer 标定过的 sung_2021_device(±3~6%)对照, 分清「标定命中」与「预测精度」; 账在 `docs/report/04` §8 |

## 硬约束

- ⚠ MPI/Palace 必须 `HWLOC_COMPONENTS=-gl`(qdsl313 已持久化;`build()` 也会注入;新 env 必须照做)。
- 无 qiskit_metal(3.13 下装不上, 平台即护栏)、无 `.metal.yaml`、无 v3 模板引擎;`import quantum_dsl` 不拉 gmsh/gdstk。
- 内部单位 µm;GDS µm verbatim;唯一 µm→m 换算点 = Palace config `Model.L0=1e-6`。JJ 是集总元件(进 GDS 不进静电网格)。
- `Solver.Order=2` 是承重件(同网格 order 1 偏 +7.3%);golden 不锚参考实现, 只锚物理与闭式。
- gmsh session 进程级共享、从不 finalize(`.geo` Macro 是进程级永久状态);每个调用点显式设全 gmsh.option。
