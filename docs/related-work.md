# 同类工作与定位（结论）

> 2026-09-27 调研，10-04 精简。完整说明与 10 篇外部工具引用文档（含正式引用与来源，经独立代理逐条复核）在分支 `related-work` 的 `docs/related-work/`。

## 1. 「国内没有完整链路的软件」不成立

- 国内：EDA-Q（开源，IEEE TCAD 2026；版图 → Ansys Q3D 电容 → E_C / E_J，论文有按电学指标迭代尺寸的「器件映射」）、本源坤元（商用，称可做千万级网格建模与参数计算）、量旋天乙（Web 端版图 + 自动布线）、清华 PalaceForCQED（开源，基于 Palace 的电磁特征提取）。
- 国外：Qiskit Metal、KQCircuits、gdsfactory + QPDK、DeviceLayout.jl（AWS，Palace）、SQDMetal（Palace）、SQuADDS、QDesignOptimizer、Keysight QuantumPro。
- 对外措辞保留「据公开资料」「就我们所知」，不写「国内没有」「首个」。Palace、Gmsh 都不是国产，卖点是开源、免商业许可。

## 2. 站得住的差异点在 DSL

一份声明式配置同时写清几何、电学节点、求解口径和验收判据，并自动核对结果。同类里只有 gdsfactory / QPDK 用配置文件描述整片设计（`.pic.yml`，GDSFactory+ v2 改为 `.gsch`），且只含实例、放置、连接、布线，不含材料、结参数、求解设置、目标值；DeviceLayout.jl 自 v1.14 可把参数放进 YAML，结构仍写在 Julia 里；其余是代码或 GUI。

- 「比手画强」对所有代码化工具都成立，不是创新点。配置相对 API 多出的是：网格化前就能做静态检查；能被综合器 / 优化器直接生成，可 diff，manifest 哈希可追溯；设计与验收（`targets:`）写在一处。
- 代价：YAML 没有循环和表达式（复杂几何退回 `.geo`）、没有 JSON Schema、不能导入 GDS。格式的价值要靠「同一器件在几种工具里怎么写」的对照来证明。
- 不能算独有：按 f_r 定谐振腔长度（SQDMetal、QPDK、SQuADDS、DeviceLayout.jl、QDesignOptimizer 都有某种形式）；网格收敛（Ansys 系工具自带自适应收敛判据）。

## 3. 发表：现状够工具类期刊，冲 Quantum 还缺两样

- 验证现状：Palace 与 Elmer 同网格电容矩阵相对差 1.9×10⁻⁷；Sung 2021 按照片量出的真版图、零调参，C_Σ 为论文的 0.87 / 0.70 / 0.87 倍；Chen 2025 的 α 命中（−190.7 vs 实测 −192 ± 6 MHz）靠 flip-chip 间隙 d 按 α 标定，取外部锚 d = 5 ± 0.4 µm 时偏 +11.7%。
- 审稿人的参照：SQDMetal 8 只 transmon，RMS f 6.0%、α 13.3%、g 24.5%；SQuADDS 6 只，α 4.1%、g 10.4%。两者都有真实 GDS，但也含标定。
- 缺：参数→版图的自动综合；一块已知真实 GDS + 实测参数的器件做盲验证。
- 期刊：工具论文投 IEEE TQE（APC $2,160）/ EPJ Quantum Technology / JOSS（要求公开开发满 6 个月等）；工具 + 综合 + 验证投 Quantum（收 software showcase，€600，先例 scqubits、SQcircuit、SQuADDS）或 Quantum Sci. Technol.；布线算法投 DAC 2027（DES6.4，全文 2026-11-18 截止）或 IEEE TCAD。ACM TQC 范围含 design automation，但未检索到版图 / 电磁类工具论文先例。

## 4. 下一步：补 feature

做「参数→版图综合」（别叫 QDA，那是领域统称）：先做器件级、FEM 在环的最小版本，配置文件当综合输出。

1. 电路模型接纳无结导体：读出谐振腔作为集总 LC 节点进模型（`resonator_lumped_lc`、`lumped_cpw` 已有，未接入 build），给出比特–谐振腔 g 与 χ。
2. `targets:` 支持 f_r / χ / κ；加 f01 → E_J 反推。
3. 单比特综合：规格（比特类型 + f01、α）→ 生成配置 → build → 按偏差用割线法调一个旋钮（如 xmon 的 `arm_L`）。
4. 第二个旋钮（读出耦合）用牛顿法；谐振腔 f_r → 长度 → `cpw_route`；再到 2–4 比特小芯片示例。
5. 验证：找真实 GDS + 实测参数的器件，报 RMS 误差。

暂不做整片放置、频率分配、串扰优化，以及本征模 / EPR。差异化目标：全开源栈上的自动 FEM 在环，加上对独立实测器件的定量误差（调研里没有工具同时做到）；另一个空白是带不确定度的规格，把 d 这类未知工艺量传到目标容差上。
