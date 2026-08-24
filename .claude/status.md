# Quantum-DSL v4 — Current Status

**greenfield 重写, TDD, 从空白开始。** 每个 session 开工前读这份 + [`plan.md`](plan.md)。

## At a glance

| | |
|---|---|
| 分支 | `v4`(orphan, worktree `~/quantum_dsl-v4`;v3 在主 worktree `~/quantum_dsl` 的 `main`) |
| 契约 | [`SPEC.md`](../SPEC.md) + `tests/test_spec.py`(N0–N14 可执行需求) |
| 实现进度 | **V4-1 + V4-3 完成**(N0–N3、N8–N11 全绿; 30 passed / 4 skipped(live 门)/ 10 failed 全是未开工组)。**下一步 V4-2 几何分叉**(N4–N6, 先读 pipeline §4–§6), 然后 V4-4/V4-5/V4-6。物理管线已 de-risk 定架构(零厚度片 imprint), 设计文档 [`physics-pipeline.md`](physics-pipeline.md); N7 golden 按该配方重钉(pipeline §7) |
| 测试跑法 | `~/miniconda3/envs/qdsl313/bin/python -m pytest tests/ -q`(Python 3.13;live 加 `QDSL_RUN_PALACE=1`) |
| 完成定义 | 契约 0 failed + N7 live 两条(回归锚: two_pads C 对 `[[24.5324,-1.9472],[-1.9472,24.5353]]` fF <2%)+ **N15 两条(外部物理锚: sung 对 PRX 11.021058 论文值, C_Σ ±5%, gate `QDSL_RUN_PALACE_SUNG=1`, V4-6 收尾跑)** |

## 硬约束(继承自 v3 的教训)

- ⚠ MPI/Palace 必须 `HWLOC_COMPONENTS=-gl`(qdsl313 已持久化;新 env 必须照做)。
- 无 qiskit_metal、无 `.metal.yaml`、无 v3 模板引擎;`import quantum_dsl` 不拉 gmsh/gdstk。
- 内部单位 µm;GDS µm verbatim;不双重缩放。JJ 是集总元件(进 GDS 不进静电网格)。
- **V4-2/V4-3/V4-6 实现者必读 [`physics-pipeline.md`](physics-pipeline.md)**
  (物理图像 → 架构决策 → 单位/收敛实测 → 失效防线)。原仓 issues #1–#28 的
  原始调研在 [`v3-issue-survey.md`](v3-issue-survey.md)(追出处时查);
  旧仓「已了结, 别重新踩」表大半对应 v3 挖空架构, v4 零厚度片路线下已结构性
  消失, 读 pipeline §4 再决定是否需要它。
