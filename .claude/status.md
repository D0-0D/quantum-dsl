# Quantum-DSL v4 — Current Status

**greenfield 重写, TDD, 从空白开始。** 每个 session 开工前读这份 + [`plan.md`](plan.md)。

## At a glance

| | |
|---|---|
| 分支 | `v4`(orphan, worktree `~/quantum_dsl-v4`;v3 在主 worktree `~/quantum_dsl` 的 `main`) |
| 契约 | [`SPEC.md`](../SPEC.md) + `tests/test_spec.py`(N0–N14 可执行需求) |
| 实现进度 | **✅ v4 完成(2026-08-25)**: V4-1…V4-6 全部落地, 40 passed / 4 skipped(live 闸, 两组均已实测通过)。N7 live 通过(C 对 golden <2%, 238s); **N15 live 通过**(gpu4 96C/384G 远端解, 1h12m, C_Σ 对论文 0.940–0.969 / β_qc +8%)。翻案记录: N10(V4-3 期)、N6 fixture 指数(CSV F→fF ×1e15 物理口径)、**N15 容差 ±5%→±8%**(Elmer P1 档系偏置抵消产物, 账见 sung meta 头注 + pipeline §9) |
| 测试跑法 | `~/miniconda3/envs/qdsl313/bin/python -m pytest tests/ -q`(Python 3.13;live 加 `QDSL_RUN_PALACE=1`; sung 加 `QDSL_RUN_PALACE_SUNG=1` + `PALACE_BIN=.claude/proto/palace_remote.sh QDSL_REMOTE_HOST=<64C+机> QDSL_PALACE_NP=32`——**峰值内存 154G, 128G 机必 OOM**, pipeline §12) |
| 完成定义 | ~~契约 0 failed + N7 两条 + N15 两条~~ **全部满足**(N7 回归锚: two_pads C 对 `[[24.5324,-1.9472],[-1.9472,24.5353]]` fF <2%; N15 外部锚: sung 对 PRX 11.021058, C_Σ ±8% + β_qc ±20%) |

## 硬约束(继承自 v3 的教训)

- ⚠ MPI/Palace 必须 `HWLOC_COMPONENTS=-gl`(qdsl313 已持久化;新 env 必须照做)。
- 无 qiskit_metal、无 `.metal.yaml`、无 v3 模板引擎;`import quantum_dsl` 不拉 gmsh/gdstk。
- 内部单位 µm;GDS µm verbatim;不双重缩放。JJ 是集总元件(进 GDS 不进静电网格)。
- **V4-2/V4-3/V4-6 实现者必读 [`physics-pipeline.md`](physics-pipeline.md)**
  (物理图像 → 架构决策 → 单位/收敛实测 → 失效防线)。原仓 issues #1–#28 的
  原始调研在 [`v3-issue-survey.md`](v3-issue-survey.md)(追出处时查);
  旧仓「已了结, 别重新踩」表大半对应 v3 挖空架构, v4 零厚度片路线下已结构性
  消失, 读 pipeline §4 再决定是否需要它。
