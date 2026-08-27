# sung_2021_xmon 原始证据归档 (2026-08-26/27)

Palace 0.16 `postpro/terminal-C.csv` 原件 (法拉, 行序 = labels = `CPLR, QB1, QB2`) 与配套 results/config。远端 gpu4
(96C/384G, np=32) 解完由 `tools/palace_remote.sh` 拉回, 远端目录即删、机器已关——本目录是唯一存续副本。
判读: `docs/report/04` §8; 例子头注: `examples/sung_2021_xmon.meta.yaml` / `sung_2021_xmon_traced.meta.yaml`。
(合并到 main 时可按 N15 惯例迁到 v4-dev 分支。)

| 文件 | 几何 / 配方 | 来源路径 | 结论 |
|---|---|---|---|
| `param_o2_80-2_{terminal-C.csv,results.yaml,manifest.yaml,palace_config.json}` | 参数化版, 80/2 order-2 | **`build(solve=True)` 产品路径**, 46 min | C_Σ 86.74/159.83/88.97 fF = 论文 ×0.874/0.701/0.873; β_qc 0.0425/0.0409 |
| `traced_o2_80-2_{terminal-C.csv,results.yaml,palace_config.json}` | 描摹版, 80/2 order-2, 15.4M tets, 峰值 168 G | 手工重建 Mesh + palace_remote (省重划) | 87.78/160.57/91.20 fF; β_qc 0.0429/0.0414 |
| `traced_o2_160-10_results.yaml` | 描摹版, 160/10 order-2 | 本机 build(solve=True) | 92.0/169.3/95.6 (粗→细降 4~5%, 从上收敛) |
| `traced_o1_160-10_terminal-C.csv` | 描摹版, 160/10 order-1 | 本机 Palace | 108.45/204.62/113.36 —— Elmer 同网格交叉的 Palace 侧 |
| `traced_160-10_elmer_cap.{sif,dat}` | 同上网格, ElmerFEM StatElecSolve P1 | ElmerGrid 14 2 转换 + ElmerSolver | SPICE 矩阵; 换算后与 Palace o1 整 3×3 相对差 1.9e-7 |
| `traced_THR120_o1_160-10_results.yaml` | 描摹版但阈值 120 (基线 143.5), 160/10 o1 | 本机 build | C_Σ +2.5/+4.0/+6.1%, β −2.9/−5.8% → 阈值是主导测量误差 |
| `param_o1_160-10_results.yaml` | 参数化版, 160/10 order-1 | 本机 build | 对描摹版 −2.1/−1.2/−4.2%, β_qc +0.4% |
