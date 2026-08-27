# quantum_dsl — Current Status

每个 session 开工前读这份 + [`plan.md`](plan.md)。

## At a glance

| | |
|---|---|
| 版本 | **v4.0 已发布**(tag `v4.0`, 2026-08-26)。`main` = v4 产品分支;`v3` = 旧实现(qiskit_metal 时代, 只读参考);`v4-dev` = v4 的 TDD 开发痕迹与原始调研存档(session logs / codex 取证 / N15 原始 CSV / 原型脚本) |
| 契约 | [`SPEC.md`](../SPEC.md)(N0–N15 需求索引)↔ `tests/`(30 passed / 2 skipped;live 两条各自实测通过一次) |
| 文档 | [`docs/README.md`](../docs/README.md) 是入口;物理口径与数值决策在 `docs/physics.md`,汇报材料在 `docs/report/`（04 = sung 论文验证闭环账 + §8 照片真版图无调参对照与测量误差账，2026-08-27）|
| 测试跑法 | `~/miniconda3/envs/qdsl313/bin/python -m pytest tests/ -q`;live 加 `QDSL_RUN_PALACE=1`(~4 min);sung 加 `QDSL_RUN_PALACE_SUNG=1 PALACE_BIN=tools/palace_remote.sh QDSL_REMOTE_HOST=<64C+/384G 机> QDSL_PALACE_NP=32`(峰值内存 154 G, 128G 机必 OOM) |
| 实测锚 | two_pads C 对 `[[24.5324,-1.9472],[-1.9472,24.5353]]` fF <2%;sung 对 PRX 11.021058: C_Σ ×0.940–0.969(±8% 内), β_qc +8%(±20% 内) |
| 论文真版图(无调参) | `examples/sung_2021_xmon`(接地 Xmon×2 + 梳齿 coupler, ~20 个从 Fig. 1(c) 照片量出的参数; 描摹版 `_traced` 作参照)。产品路径 `build(solve=True)` 80/2 o2 (gpu4, 12.8M tets, 46 min): C_Σ = 86.7/159.8/89.0 fF = 论文 ×0.874/0.701/0.873, β_qc 0.0425/0.0409(+12~17%)。**不命中论文**——与被 Elmer 标定过的 sung_2021_device(±3~6%)对照, 分清「标定命中」与「预测精度」; Elmer 同网格交叉 1.9e-7 证明差距是几何不是求解器。账在 `docs/report/04` §8, 原始 CSV 在 `.claude/xmon-evidence/`(2026-08-27) |

## 硬约束

- ⚠ MPI/Palace 必须 `HWLOC_COMPONENTS=-gl`(qdsl313 已持久化;`build()` 也会注入;新 env 必须照做)。
- 无 qiskit_metal(3.13 下装不上, 平台即护栏)、无 `.metal.yaml`、无 v3 模板引擎;`import quantum_dsl` 不拉 gmsh/gdstk。
- 内部单位 µm;GDS µm verbatim;唯一 µm→m 换算点 = Palace config `Model.L0=1e-6`。JJ 是集总元件(进 GDS 不进静电网格)。
- `Solver.Order=2` 是承重件(同网格 order 1 偏 +7.3%);golden 不锚参考实现, 只锚物理与闭式。
- gmsh session 进程级共享、从不 finalize(`.geo` Macro 是进程级永久状态);每个调用点显式设全 gmsh.option。
