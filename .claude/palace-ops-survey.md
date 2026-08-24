> **性质: 原始参考资料**(codex gpt-5.6-sol xhigh, 152 次检索, 2026-08-24;
> 另有 gpt-5.5 独立跑(72 次检索)交叉验证, 两份结论一致, 本文取 5.6 版)。
> 设计结论的落点在 [physics-pipeline.md](physics-pipeline.md) §12。

## 1. 多 rank Order-2 问题的上游证据

**结论：没有检索到 Palace/MFEM 上游精确复现“Electrostatic + Order=2 + 多 MPI rank + 第二个 terminal 静默丢 rank/挂死”的报告，也没有任何 release 声称修复过该组合；ZZ/RT 路径有相关正确性和 AMR 故障，但不足以证明就是历史问题的根因。**

- Palace 0.16 静电源码只构造一次 Laplace 矩阵和 `KspSolver`，随后顺序遍历 terminal：生成新 RHS、`ksp.Mult`、后处理、再调用 `GradFluxErrorEstimator::AddErrorIndicator`。所以各 terminal 是独立 RHS/解，但复用矩阵和 KSP/预条件器；即使 `Refinement.MaxIts=0`，每个 terminal 后仍执行误差估计。[0.16 electrostaticsolver.cpp](https://github.com/awslabs/palace/blob/v0.16.0/palace/drivers/electrostaticsolver.cpp)
- Palace 数学参考明确使用 ZZ estimator，将电通量投影到 Raviart–Thomas `H(div)` smooth space；因此 Order=2 大网格确实会额外创建较大的 RT 空间和全局质量矩阵求解，但“可能耗尽内存/卡通信”仍只是与现象一致的假设。[误差估计公式](https://github.com/awslabs/palace/blob/main/docs/src/reference.md)
- 当前 resolved config 中 estimator 自有 `EstimatorTol=1e-6`、`EstimatorMaxIts=10000`、`EstimatorMG=false`；官方 quick-start 的计时/内存表也显示 estimator construction/solve 是独立的显著内存阶段。[配置参考](https://awslabs.github.io/palace/stable/config/reference/)；[quick-start 完整输出](https://awslabs.github.io/palace/stable/quick/)
- 最接近的 Palace 故障是 [#675](https://github.com/awslabs/palace/issues/675)：`v0.15.0-73`、4 MPI ranks、开启 AMR 后 rank 0 SIGSEGV、无 Palace 诊断；以及 [#569](https://github.com/awslabs/palace/issues/569)：CPW 在第 4 轮 AMR 后 MFEM `STable3D` abort。两者仍为 open，且都不是静电第二 terminal。
- MFEM [#5125](https://github.com/mfem/mfem/issues/5125) 是直接相关但不等价的 open bug：refine/rebalance 后 ND/RT 误差从约 `1e-14` 变成 `8.27/11`，H1/L2 不受影响；它是数据迁移正确性问题，不是 hang，也没有已发布修复版本。
- 已修的静电 estimator 问题在 0.13：更换 smooth-flux space 以改善材料界面性能，以及非共形 AMR 内边界上带 face DOF 的非齐次 Dirichlet 投影错误，后者只针对 `p>3`。[CHANGELOG](https://github.com/awslabs/palace/blob/main/CHANGELOG.md)；[PR #236](https://github.com/awslabs/palace/pull/236)
- 0.16.1 的“ND order ≥2 并行 face-DOF orientation”修复属于 lumped-port tangent projection，不是静电 H1/RT estimator；该 direct-interpolation 路径后来还因物理投影不等价被回滚，不能视为本问题修复。[PR #684](https://github.com/awslabs/palace/pull/684)

## 2. Palace AMR

**结论：solution-based AMR 从 0.12.0 起支持 Electrostatic，但应作为 Gmsh 边缘 seed mesh 之上的二次自适应，不能取代导体边缘的初始尺寸场。**

- 0.12.0 引入 flux estimator 和 `Model.Refinement`，当时除 transient 外均可用；当前文档仍说明除 time-domain driven 外所有问题类型可用，包含 Electrostatic。[CHANGELOG](https://github.com/awslabs/palace/blob/main/CHANGELOG.md)；[模型指南](https://awslabs.github.io/palace/stable/guide/model/)
- 当前关键默认值：`MaxIts=0` 关闭 AMR、`Tol=0.01`、`MaxSize=0` 不限 DoF、`UpdateFraction=0.7`、`Nonconformal=true`、`MaxNCLevels=1`；纯四面体可以设 `Nonconformal=false` 做 conformal AMR。[配置参考](https://awslabs.github.io/palace/stable/config/reference/)

```json
"Model": {
  "Refinement": {
    "MaxIts": 2,
    "Tol": 0.01,
    "MaxSize": 5000000,
    "UpdateFraction": 0.7,
    "Nonconformal": false,
    "SaveAdaptIterations": true,
    "SaveAdaptMesh": false
  }
}
```

- 官方 transmon 示例用 `MaxIts=2, Order=3`，但误差只从 `0.3455 → 0.2762 → 0.2123`，并非两轮即收敛。[Palace transmon AMR](https://awslabs.github.io/palace/stable/examples/transmon/)
- SQDMetal 论文明确写道 AMR 仍需要 “reasonably well-refined initial seed mesh”；其 API 同时暴露 `fine_mesh_components` 和 Palace refinement，直接否定“完全删掉 Gmsh edge field”的做法。[arXiv:2511.01220](https://arxiv.org/pdf/2511.01220)；[SQDMetal Palace 文档](https://sqdlab.github.io/SQDMetal/simulations/simpalace.html)
- 正面经验：SQDMetal 的静电 Palace AMR O2 跑到 `71,442,078 DoF`，五个电容项与 COMSOL/Ansys 的差异均低于 `0.3%`。[论文 Table II](https://arxiv.org/pdf/2511.01220)
- 风险经验：[Palace #444](https://github.com/awslabs/palace/issues/444) 的 microstrip 10 轮从 `12,304` 增至 `6,611,416` unknowns，indicator 仍为 `0.02483`、GPU 占 48 GB；[#589](https://github.com/awslabs/palace/issues/589) 报告 refine 峰值内存约为稳定 solve 的 `3–4×`。
- 截至 2026-08-24，0.16.1 引入的 move/symlink 逻辑存在 open bug：同时启用 `SaveAdaptMesh` 和 `SaveAdaptIterations` 会覆盖历史 mesh，试点时应避开该组合。[#887](https://github.com/awslabs/palace/issues/887)

## 3. 版本与升级路径

**结论：建议并行部署 0.17.0 做回归后升级，但不能把升级当成 Order-2 MPI hang 的既有修复；0.16 之后没有 electrostatic/ZZ 对应修复。**

- 当前最新正式版是 **0.17.0，2026-06-28 发布**。[release](https://github.com/awslabs/palace/releases/tag/v0.17.0)
- 0.16.1 增加分阶段内存表、优化 AMR I/O、加强 schema 校验，并包含上述 ND 高阶 port-projection 条目；没有静电或 ZZ/MPI 修复。[CHANGELOG 0.16.1](https://github.com/awslabs/palace/blob/main/CHANGELOG.md)
- 0.17.0 与本任务较相关的变化是：所有 problem type 支持 2D mesh、conformal AMR 后打印 mesh statistics、修复 waveport + nonconformal AMR 错结果、周期网格上的 `RefineCrackElements` 失败、impedance cracking 按 attribute 缩放；仍没有静电 terminal/estimator hang 修复。[CHANGELOG 0.17.0](https://github.com/awslabs/palace/blob/main/CHANGELOG.md)
- `CrackInternalBoundaryElements` 的关键正确性修复其实在 0.15.0，0.16 已包含：部分 lumped-port 条件结果错误，以及 impedance `Rs/Ls/Cs` cracking 缩放错误；0.15 还修复了 periodic Gmsh mesh 和历史 nonconformal adapted mesh 的读取。[CHANGELOG 0.15.0](https://github.com/awslabs/palace/blob/main/CHANGELOG.md)
- `main` 的 “In progress” 已有“大型 nonconformal mesh 的 MPI broadcast overflow”修复，但它是 **0.17 后未发布内容**，不能算 0.17 能力。[主分支 CHANGELOG](https://github.com/awslabs/palace/blob/main/CHANGELOG.md)
- 官方对用户推荐 Spack；开发者或指定 tag 用源码 CMake；容器也是用 Spack 生成并自行构建 Docker/Apptainer。[安装文档](https://awslabs.github.io/palace/stable/install/)
- Spack 确实滞后：截至查询时其 `develop` recipe 只列 `0.16.0/0.15.0/...` 和 `develop`，没有 0.16.1/0.17.0。[Spack package.py](https://github.com/spack/spack-packages/blob/develop/repos/spack_repo/builtin/packages/palace/package.py)
- 官方 FAQ 承认 recipe 可能尚未收录最新版本，并建议多版本共存；`@develop` 不推荐生产。[FAQ](https://awslabs.github.io/palace/stable/faq/)
- 未检索到官方 conda 包或 release 二进制；官方安装页只列 Spack、源码和自建容器，且明确不提供 Windows 预编译 binary，WSL 仅 best effort，并提醒检查 WSL 内存/CPU/磁盘限制。[FAQ](https://awslabs.github.io/palace/stable/faq/)

## 4. 静电求解器设置

**结论：你们的 `BoomerAMG + CG, Tol=1e-8, Order=2, Device=CPU` 与官方实践一致；Order=2 是合理精度档，但 CPU partial assembly 是否更快必须在本机 A/B，官方没有四面体 O2 的定量保证。**

- 官方 spheres 静电 quick-start 使用 `Order=3, Device=CPU, BoomerAMG, CG, Tol=1e-8, MaxIts=100`；配置 schema 的通用默认则是较保守的 `Order=1, Tol=1e-6`，不等于精度推荐。[quick-start](https://awslabs.github.io/palace/stable/quick/)；[配置参考](https://awslabs.github.io/palace/stable/config/reference/)
- 官方 transmon 示例称 O2 改 O1 可快约 `30×`，但误差增加、频率明显偏离收敛值，因此准确计算通常推荐 O2 或更高。[transmon 示例](https://awslabs.github.io/palace/stable/examples/transmon/)
- `Device=CPU` 是默认；`Backend` 通常应省略，让 Palace 自动选择。`PartialAssemblyOrder < Order` 才启用 libCEED partial assembly，所以 O2 下 `PartialAssemblyOrder=1` 是 partial，设为 `2` 可作为 full-assembly 对照。[并行与 GPU 指南](https://awslabs.github.io/palace/stable/guide/parallelism/)
- CPU 默认常见为 `/cpu/self/xsmm/blocked`；libCEED 说明它用 LIBXSMM 向量化，每批处理 8 个交错元素，适合元素数很多的网格，而 serial backend 更适合少量高阶元素。[libCEED backend 文档](https://libceed.org/en/latest/gettingstarted/)
- 未找到 Palace 对 CPU、四面体、Order=2 partial/full assembly 的公开加速比；官方只承诺 partial assembly 有更好的渐近存储/算子应用成本，尤其强调 GPU 收益。
- 多 terminal 不是并行同时求解：每次一个 terminal 置 1 V，其余 terminal 接地，顺序求解；矩阵、KSP 和预条件器复用，解向量保留后通过能量内积形成完整 Maxwell C 矩阵，每次 solve 后还执行 estimator。[源码](https://github.com/awslabs/palace/blob/v0.16.0/palace/drivers/electrostaticsolver.cpp)；[数学参考](https://github.com/awslabs/palace/blob/main/docs/src/reference.md)

## 5. 域尺寸与边界条件

**结论：静电“接地盒”和“开放域”是不同物理问题，Palace 没有静电 Absorbing/PML；公开资料给出了工程几何起点，但未检索到超导平面芯片上盒体与无限域的直接百分比对照。**

- 静电外边界只有 `Ground`（`V=0` Dirichlet）和 `ZeroCharge`（`n·D=0`，零法向电势梯度）；`Absorbing` 仅支持 eigenmode/frequency/time-domain，PML 也未实现。[Palace 边界文档](https://awslabs.github.io/palace/stable/guide/boundaries/)
- SQDMetal benchmark 模拟真实金属 sample holder：全部外表面 PEC，盒总高为芯片厚度 `2×`，XY 长宽各比芯片大 `20%`，衬底居中放在盒底并接地。这是接地盒基线，不是无限域法则。[arXiv:2511.01220](https://arxiv.org/pdf/2511.01220)
- KQCircuits 4.9.12 的通用默认是 `10×10 mm` XY box、`upper_box_height=1000 µm`、`lower_box_height=0`、substrate `[550,375] µm`；`Simulation.from_cell` 默认在 cell bbox 每侧扩 `300 µm`。[KQCircuits Simulation](https://iqm-finland.github.io/KQCircuits/api/kqcircuits.simulations.simulation.html)
- Yale 超导 qubit 论文/学位论文明确指出片上和片下 ground 都参与 transmon/resonator capacitance，Maxwell 的外边界是人工 ground，必须放到足够远才能近似 infinity；但未给距离或误差百分比。[Yale thesis](https://cpb-us-w2.wpmucdn.com/campuspress.yale.edu/dist/2/3627/files/2020/10/Kurtis_ImprovingCoherenceSuperconductingQubits.pdf)
- 未检索到可信的超导芯片公开数据直接比较“真实接地盒 Cij”与“无限开放域 Cij”，也未找到通用 airbox-size 百分比规则；因此不能宣称“3×特征尺寸”之类是已验证标准。
- 对称面可公开成立：偶对称电势使用 `ZeroCharge`，奇对称电势使用 `Ground`；Palace 维护者也建议 2D 静电挤出面的法向边界用 `ZeroCharge`。[Palace #140](https://github.com/awslabs/palace/issues/140) COMSOL 官方定义同样是电场对称面 `E_n=0`，并有只建半模型的静电实例。[COMSOL symmetry](https://doc.comsol.com/6.3/doc/com.comsol.help.acdc/acdc_ug_electric_fields.07.015.html)
- 但完整 C 矩阵逐 terminal 的单位激励经常破坏几何对称性；只有几何、材料、外边界以及该次 terminal 激励都满足相应偶/奇对称时才能减半，不能仅因版图看起来对称就套用。

## 运维裁决

建议保留 0.16 环境，同时从 **0.17.0 tag** 建第二套固定版本；用同一 mesh/config 做 `np=1/2/4/8` 回归，电容矩阵、迭代数、峰值 RSS 和终止位置通过后再切生产。升级值得，因为它带来当前 schema、resolved config、分阶段内存报告和网格修复，但没有证据表明它治愈历史 hang，生产不要直接用 `@develop`。

Order-2 当前可靠绕法仍是 **单 rank**；多 rank 先用 Order-1 做预览。定位时依次 A/B：`PartialAssemblyOrder=1/2`、`EstimatorMG=false/true`、`InitialGuess=true/false`、0.16/0.17，并记录最后一个 `KSP residual`、`Updating solution error estimates` 和 WSL/Windows OOM 事件。注意 `MaxIts=0` 并不会跳过 estimator。若必须并行化 terminal，可做独立单-terminal 作业并通过各导体 `SurfaceFlux` 组装 C 列，但这是自定义流程，必须用对称性、总电荷和标准 `terminal-C.csv` 做交叉验证。

AMR 值得小规模接入，但保留 Gmsh Distance/Threshold 边缘 seed；四面体先用 `Nonconformal=false`、1–2 轮、明确 `MaxSize`，按稳定 solve 内存的至少 `4×` 预留 refine 峰值，并暂避 `SaveAdaptMesh + SaveAdaptIterations`。

域默认建议写成两种模式：有真实封装时直接采用实测 sample-box 尺寸和 ground；没有盒体而要近似孤立结构时，初始采用“每侧 `max(300 µm, 10%芯片跨度)`、顶部 `max(1 mm, 1×衬底厚度)`”，随后自动跑 `1×/1.5×/2×` 域 sweep，要求所有关注的 `Cij` 变化 `<0.2%` 才验收。这里 `300 µm/1 mm/10%` 分别取自 KQCircuits 与 SQDMetal 的公开起点，`0.2%` 是建议写入你们运维规范的收敛门槛，不是 Palace 官方定律。