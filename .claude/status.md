# quantum_dsl — Current Status

每个 session 开工前读这份 + [`plan.md`](plan.md)。

## At a glance

| | |
|---|---|
| 版本 | **v4.0 已发布**(tag `v4.0`, 2026-08-26)。`main` = v4 产品分支;`v3` = 旧实现(qiskit_metal 时代, 只读参考);`v4-dev` = v4 的 TDD 开发痕迹与原始调研存档(session logs / codex 取证 / N15 原始 CSV / 原型脚本) |
| 契约 | [`SPEC.md`](../SPEC.md)(N0–N15 需求索引)↔ `tests/`(30 passed / 2 skipped;live 两条各自实测通过一次) |
| 文档 | [`docs/README.md`](../docs/README.md) 是入口;物理口径与数值决策在 `docs/physics.md`,汇报材料在 `docs/report/` |
| 测试跑法 | `~/miniconda3/envs/qdsl313/bin/python -m pytest tests/ -q`;live 加 `QDSL_RUN_PALACE=1`(~4 min);sung 加 `QDSL_RUN_PALACE_SUNG=1 PALACE_BIN=tools/palace_remote.sh QDSL_REMOTE_HOST=<64C+/384G 机> QDSL_PALACE_NP=32`(峰值内存 154 G, 128G 机必 OOM) |
| 实测锚 | two_pads C 对 `[[24.5324,-1.9472],[-1.9472,24.5353]]` fF <2%;sung 对 PRX 11.021058: C_Σ ×0.940–0.969(±8% 内), β_qc +8%(±20% 内) |

## 硬约束

- ⚠ MPI/Palace 必须 `HWLOC_COMPONENTS=-gl`(qdsl313 已持久化;`build()` 也会注入;新 env 必须照做)。
- 无 qiskit_metal(3.13 下装不上, 平台即护栏)、无 `.metal.yaml`、无 v3 模板引擎;`import quantum_dsl` 不拉 gmsh/gdstk。
- 内部单位 µm;GDS µm verbatim;唯一 µm→m 换算点 = Palace config `Model.L0=1e-6`。JJ 是集总元件(进 GDS 不进静电网格)。
- `Solver.Order=2` 是承重件(同网格 order 1 偏 +7.3%);golden 不锚参考实现, 只锚物理与闭式。
- gmsh session 进程级共享、从不 finalize(`.geo` Macro 是进程级永久状态);每个调用点显式设全 gmsh.option。
