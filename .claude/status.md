# Quantum-DSL v4 — Current Status

**greenfield 重写, TDD, 从空白开始。** 每个 session 开工前读这份 + [`plan.md`](plan.md)。

## At a glance

| | |
|---|---|
| 分支 | `v4`(orphan, worktree `~/quantum_dsl-v4`;v3 在主 worktree `~/quantum_dsl` 的 `main`) |
| 契约 | [`SPEC.md`](../SPEC.md) + `tests/test_spec.py`(N0–N14 可执行需求) |
| 实现进度 | **未开始**(契约套件全红, 除 N0)—— 但物理管线已 **de-risk 并定架构**: 金属按零厚度片 imprint(v3 "Palace 拒内部面 Terminal" 系误诊, 本机实证推翻), 设计文档 [`physics-pipeline.md`](physics-pipeline.md); 原型对 N7 golden 实测 0.04–1.5%(`proto/`); V4-3 数学对 golden 逐位复算通过 |
| 测试跑法 | `~/miniconda3/envs/qdsl313/bin/python -m pytest tests/ -q`(Python 3.13;live 加 `QDSL_RUN_PALACE=1`) |
| 完成定义 | 契约 0 failed + N7 live 两条通过(two_pads C 对 `[[24.7288,-1.976],[-1.976,24.7293]]` fF <2%) |

## 硬约束(继承自 v3 的教训)

- ⚠ MPI/Palace 必须 `HWLOC_COMPONENTS=-gl`(qdsl313 已持久化;新 env 必须照做)。
- 无 qiskit_metal、无 `.metal.yaml`、无 v3 模板引擎;`import quantum_dsl` 不拉 gmsh/gdstk。
- 内部单位 µm;GDS µm verbatim;不双重缩放。JJ 是集总元件(进 GDS 不进静电网格)。
- **V4-2/V4-3/V4-6 实现者必读 [`physics-pipeline.md`](physics-pipeline.md)**
  (物理图像 → 架构决策 → 单位/收敛实测 → 失效防线)。原仓 issues #1–#28 的
  原始调研在 [`v3-issue-survey.md`](v3-issue-survey.md)(追出处时查);
  旧仓「已了结, 别重新踩」表大半对应 v3 挖空架构, v4 零厚度片路线下已结构性
  消失, 读 pipeline §4 再决定是否需要它。
