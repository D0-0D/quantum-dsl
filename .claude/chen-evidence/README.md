# chen-evidence — Chen 2025 3×3 首批本机求解产物 (2026-09-13, session 2609131337)

`examples/chen_2025_3x3.meta.yaml` 的 QCQ 块 **H01** (Q01_a/b + H01 + H01_pent + Q11_a/b, 6 terminal), 网格 100/4, order 2,
75.3 万 tets / 105 万未知量, 本机 (WSL2, 22 核 15 G) Palace 0.16.0 `-np 8`, 573 s。
`solve_block.py` 是跑法 (PYTHONPATH=src, env PALACE_BIN / NP / TOP=airbox.top_um 覆盖); 网格 40 M 未存, 重跑 25 s。

| 文件 | 内容 |
|---|---|
| `H01_d5_results.yaml` | d = 5 µm: 6×6 Maxwell / mutual (fF) + `solve_circuit_model` 哈密顿量 |
| `H01_d5_config.json` | 对应 Palace config |
| `H01_d7_*` | d = 7 µm 复算 (检验「d 是唯一旋钮」: 对地 C 应 ×~5/7, 互容应上升) |

对 SI §D 11 个电容的逐项对照与解读在 `.claude/session/2609131337.md`。按 N15 惯例, 合并时可迁到 v4-dev。
