# chen-evidence — Chen 2025 3×3 首批本机求解产物 (2026-09-13, session 2609131337)

`examples/chen_2025_3x3.meta.yaml` 的 QCQ 块 **H01** (Q01_a/b + H01 + H01_pent + Q11_a/b, 6 terminal), 网格 100/4, order 2,
75.3 万 tets / 105 万未知量, 本机 (WSL2, 22 核 15 G) Palace 0.16.0 `-np 8`, 573 s。
`solve_block.py` 是跑法 (PYTHONPATH=src, env PALACE_BIN / NP / TOP=airbox.top_um 覆盖); 网格 40 M 未存, 重跑 25 s。

| 文件 | 内容 |
|---|---|
| `H01_d5_results.yaml` | d = 5 µm: 6×6 Maxwell / mutual (fF) + `solve_circuit_model` 哈密顿量 |
| `H01_d5_config.json` | 对应 Palace config |
| `H01_d7_*` | d = 7 µm 复算 (检验「d 是唯一旋钮」: 对地 C 应 ×~5/7, 互容应上升) |

对 SI §D 11 个电容的逐项对照与解读在 `.claude/session/2609131337.md`。按 sung 证据惯例, 合并时可迁到 v4-dev。

## 2026-09-18 上云: 十字例子整片解 + 3×3 整片解 (session 2609180210, c24a1 64c/128G, Palace 0.16 spack)

`examples/chen_2025_cross.meta.yaml` (中心 Q11 四爪 + 4 臂比特各一爪 + 4 耦合器 = 18 terminal, 无分块) 与 `examples/chen_2025_3x3.meta.yaml` 整片 (42 terminal)。
网格本机出 (`build(..., solve=False)` 或改 `airbox.top_um` / `mesh` 后 `build_mesh` + `palace_config`), `rr -p` 推上去, 远端 `run_palace2.sh <dir> <np> <cfg>` 跑并采样内存, 拉回 `postpro/` 后
`postpro.py` (会话 scratchpad, 逻辑 = `parse_capacitance` + `solve_circuit_model`, 结从 `Layout.qubits` 取) 出 results.yaml。

| 文件 | 内容 |
|---|---|
| `cross_d5_100_4_results.yaml` / `_config.json` / `_terminal-C.csv` | 十字 d = 5 µm, 100/4, order 2, 3.34 M 未知量, np=24 1140 s, 峰值 28.6 GB: 18×18 Maxwell + 9 结哈密顿量。中心 Q11 E_C 214.5 MHz (实测 α −192 ± 6, SI 闭合 209), 臂比特 219.9 (= H01 块解 220) |
| `cross_d7_100_4_results.yaml` | 同上 d = 7 µm (1123 s, 28.1 GB): 中心 E_C 250.4 / 臂 259.0 MHz; 与 d=5 两点给 E_C ∝ d^0.46 |
| `cross_d4_100_4_results.yaml` | 同上 d = 4 µm (1158 s, 28.3 GB): 中心 **E_C 190.7 MHz ↔ 实测 α −192 ± 6 命中**; 臂 194.5; g_qc 55 / g_qq 2.6 MHz |
| `full3x3_d5_100_4_results.yaml` / `_config.json` / `_terminal-C.csv` | 3×3 整片 42 terminal, d = 5, 100/4, 8.12 M 未知量, np=32 5158 s, 峰值 69.2 GB: E_C 角/边/中心 218.1 / 216.3 / 214.5 MHz (中心 = 十字), 最近邻 g_qq 3.7, 对角 0.03–0.05 MHz |
| `cross_d5_80_3_results.yaml` | 十字 d = 5 第二档网格 80/3 (5.02 M tets / 6.94 M 未知量, np=32 1405 s, 59 GB): 对 100/4 E_C +0.3%, 互容 −0.5～−1.1% → 单网格结论成立 |
| `full3x3_d5_150_6_results.yaml` | 3×3 粗档 150/6 (2.00 M tets / 2.82 M 未知量, 32 min, 25.7 GB): 对 100/4 E_C −0.5～−0.6%, 互容 +1～2% —— 降内存的杠杆与代价 |
| `cloud_runs_2609180210_summaries.txt` | 9 次远端运行的 np / 用时 / 采样峰值 / Palace 自报峰值一览（含 np=16、AMG 激进粗化两个只测峰值的变体） |
