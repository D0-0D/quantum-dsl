# N15 原始证据归档(2026-08-25, sung 整片 live 解)

Palace 0.16 `postpro/terminal-C.csv` 原件(法拉, 行序 = labels =
`CPLR_b, CPLR_t, QB1_b, QB1_t, QB2_b, QB2_t`)。远端(gpu4, 96C/384G,
np=32)解完由 `proto/palace_remote.sh` 拉回, 远端目录即删、机器已关——
本目录是这批解的唯一存续副本。判读与容差翻案的完整账:
[`physics-pipeline.md`](../physics-pipeline.md) §9 与
[`session/2608242245.md`](../session/2608242245.md)。

| 文件 | 配方 | 结论 |
|---|---|---|
| `terminal-C_o2_contract.csv` | 契约配方: mesh 80/2, order 2(14.1M tets / 18.5M 未知量) | C_Σ = 95.83/220.72/95.82 fF = 论文 ×0.965/0.969/0.940; β_qc 0.0393。N15 两条 pytest 的输入(两次独立全管线 CSV **逐位一致**, 只归档一份) |
| `results_o2_contract.yaml` | 同上, build() 落盘的哈密顿量 | N15 断言直接消费的文件 |
| `terminal-C_o1_crosscheck.csv` | **同一网格**, order 1 | C_Σ = 101.4/232.6/101.3, 对 v3 Elmer P1 档(102.1/232.8/102.1)<1% —— 管线正确性外证 + 揭穿 ±5% 旧依据(P1 正偏与版图缺失抵消) |
| `terminal-C_o2_coarse160-10.csv` | mesh 160/10, order 2(WSL 本机可解) | C_Σ = 101.2/231.0/101.1(+1.4~1.9% 对论文)—— 网格灵敏度参照: 粗细两档跨 ~5.5%, 契约配方未收敛 |
