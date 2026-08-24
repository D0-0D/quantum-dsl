检索日期：2026-08-24。源码结论固定到 Qiskit Metal `422fc05`、KQCircuits `b879b4c`、SQDMetal `b712277`，避免分支漂移。

**1. Qiskit Metal composite / LOM 2.0**

结论：是同构方案，即“独立 cell Maxwell 矩阵 + 同名节点拼装求和 + Schur 补约化”；但“未共同求解的直接互容必丢”是由数学与源码推出的限制，论文没有逐字警告。

- 论文 §I–II 把物理版图划为 “strictly disjoint cell modules”，各 cell 独立仿真；元件严格分属 cell，而节点集合允许 “potential overlap”。式 (5) 定义全局矩阵为 \(\mathbf C=\sum_n\mathbf C_{n,\mathrm{cell}}\)，式 (7b) 明称 Schur complement。[LOM 论文 §II、Eq. 5、7b](https://arxiv.org/html/2103.10344)

- `Cell` 接受单个 cell 的 Maxwell `cap_mat` 和 `node_rename`；`_rename_nodes_in_df` 直接替换行列标签。[Cell L1246–1298](https://github.com/qiskit-community/qiskit-metal/blob/422fc05bf6f40c741b3110275dca6d769c3ebb43/src/qiskit_metal/analyses/quantization/lom_core_analysis.py#L1246-L1298)、[rename L747–760](https://github.com/qiskit-community/qiskit-metal/blob/422fc05bf6f40c741b3110275dca6d769c3ebb43/src/qiskit_metal/analyses/quantization/lom_core_analysis.py#L747-L760)

- 每个局部矩阵先转成带节点名的邻接表；全局矩阵从全零开始，只把出现过的 `(n1,n2,w)` 逐项 `+=`。[邻接表 L214–224](https://github.com/qiskit-community/qiskit-metal/blob/422fc05bf6f40c741b3110275dca6d769c3ebb43/src/qiskit_metal/analyses/quantization/lom_core_analysis.py#L214-L224)、[嵌入和累加 L508–551](https://github.com/qiskit-community/qiskit-metal/blob/422fc05bf6f40c741b3110275dca6d769c3ebb43/src/qiskit_metal/analyses/quantization/lom_core_analysis.py#L508-L551)

- `CompositeSystem` 用 `np.unique` 合并所有 cell 的节点名，并把所有 `cap_mat` 交给同一 `CircuitGraph`；约化代码正是 \(C-C S_r(S_r^TCS_r)^{-1}S_r^TC\)。[汇总 L1371–1391](https://github.com/qiskit-community/qiskit-metal/blob/422fc05bf6f40c741b3110275dca6d769c3ebb43/src/qiskit_metal/analyses/quantization/lom_core_analysis.py#L1371-L1391)、[Schur 补 L713–731](https://github.com/qiskit-community/qiskit-metal/blob/422fc05bf6f40c741b3110275dca6d769c3ebb43/src/qiskit_metal/analyses/quantization/lom_core_analysis.py#L713-L731)

- 教程给出最直接的绑定示例：两个独立 Q3D cell 的 `coupler_connector_pad_Q1`、`coupler_connector_pad_Q2` 都改名为 `"coupling"`，然后装入一个 `CompositeSystem`。[两 cell 重命名 L362–388](https://github.com/qiskit-community/qiskit-metal/blob/422fc05bf6f40c741b3110275dca6d769c3ebb43/docs/tut/4-Analysis/4.05-New-LOM-and-Two-Coupled-Transmon-Example-with-sequence.ipynb#L362-L388)、[CompositeSystem L454–459](https://github.com/qiskit-community/qiskit-metal/blob/422fc05bf6f40c741b3110275dca6d769c3ebb43/docs/tut/4-Analysis/4.05-New-LOM-and-Two-Coupled-Transmon-Example-with-sequence.ipynb#L454-L459)

- 源码推论：若 A、B 从未在任一 `cap_mat` 中共现，拼装前 \(C_{AB}=0\)。Schur 补可以通过已存在的共享非地节点产生 A–B 的间接等效项，但不能恢复从未求解过的直接电场互容；若两部分除 datum/ground 外没有网络路径，矩阵保持分块。

- 切块原则没有被论文写成“必须同 cell”的硬规则；但 Fig. 1 的 qubit cell 明确同时放入 qubit pads、相邻 CPW 段和 coupler pads，实验模型也纳入 “neighboring CPW structures” 及 “all ... coupler structures attached to the qubit”。作者只称约 `100 μm` 对其 transmon 版图合理，并明确未得到普适长度。[论文 §IV](https://arxiv.org/html/2103.10344)

因此你们更准确的契约措辞应是：**欲保留 A–B 的直接 Maxwell 互容，A、B 必须至少在一次局部 EM solve 中共现；共享节点只能提供网络中介路径。**

**2. 误差量化与直接耦合量级**

结论：未检索到超导版图中“同一几何的 cell 拼装 vs 整片 Maxwell 求解”公开通用 benchmark；现有数据只能证明边界尺寸可收敛，以及被漏掉的直接腿可能从可忽略到决定消耦点。

- 最接近的是 LOM 论文 Table 1：cell bounding-box length 对平均 \(\chi_{qr}\) 实验符合度影响 `<0.5%`，超过约 `100 μm` 越来越小；padding 超过约 `100 μm` 后 negligible。但这不是拼装矩阵与整片 FEM 的逐项 \(\Delta C\) 对比。[LOM Table 1](https://arxiv.org/html/2103.10344)

- 同论文中，把 qubit cell 内全部直接 CPW–CPW coupling Hamiltonians 纳入后，\(\chi_{qr}\) 约下降 `5%`。这说明多个弱直接项合计可能不可忽略，但仍不是“跨块丢项”的专门基准。[LOM §IV](https://arxiv.org/html/2103.10344)

- 一个理论 double-transmon-coupler 设计取直接 Q1–Q2 \(C_{12}=0.025\) fF、\(g_{12}/2\pi=1.7\) MHz；主要 q–coupler 腿 \(C_{13}=6\) fF、\(g_{13}/2\pi=239\) MHz，即约 `0.4%` 的 C、`0.7%` 的 g。其传统单-transmon对照又采用 \(g_{12}=25\) MHz、\(g_{1c}=g_{2c}=250\) MHz，即 `10%`。[Goto 2022，Table I 与 Appendix E](https://journals.aps.org/prapplied/pdf/10.1103/PhysRevApplied.18.034038)

- Floating-coupler 公开设计给出 \(g_{12}/2\pi=-12\) MHz 对 \(g_{1c}=-79\)、\(g_{2c}=98\) MHz；另一构型为 `-5.8` 对 `-85/-85` MHz。其式 (5) 是 \(g=g_{12}-g_{\rm eff}\)，所以漏掉固定 q–q 腿会直接移动甚至消灭 zero-coupling 点。[Sete 2021，Eq. 5、参数 L105–106](https://arxiv.org/html/2103.07030)

- IQM 的 1.96 mm 长距结构实测拟合 \(g_{12}/2\pi=3.7\) MHz、\(g_{1c}=51.5\)、\(g_{2c}=53.9\) MHz；显式由 direct capacitance 算出的对角 NNN \(g_{13}<30\) kHz，比 intended NN 小至少两阶，但在 `500 μm` pitch 时论文称 NNN 与 NN 同量级。[Marxer 2023，P2–P3](https://journals.aps.org/prxquantum/pdf/10.1103/PRXQuantum.4.010314)

所以不存在可信的单一“典型值”：公开设计里直接腿约为主要 q–coupler 腿的 `<1%`、`7%–15%` 或 `10%` 都有。且 \(g\) 来自约化/求逆后的矩阵，不能一般地写成 \(\Delta g/g=\Delta C/C\)，特别是在相消型 coupler 附近。

**3. 经典 EDA 的窗口化处理**

结论：经典 PEX 也截断远场，但通常有显式 interaction distance、重叠上下文、误差界或全 3D 校准；只靠人工切块纪律不算完整的工业防线。

- ICCAD 综述称 interaction region 用来决定哪些 coupling 保留或丢弃；区域包含 overlapping central conductors 及各层最近邻，scanband 宽度取最大 coupling distance；pattern 缺失时局部解 Laplace，关键网再用 full 3D solver 校准/验证。[Kamon–McCormick–Shepard 1999，P2 L160–195](https://www.cecs.uci.edu/~papers/compendium94-03/papers/1999/iccad99/pdffiles/04b_1.pdf)

- BEM windowing 文献明确研究“窗口外导体被忽略”的误差：普通 windowing 与 shift-truncate 给 self/mutual capacitance 的相反上下界，并据上下界差自适应选择窗口；不同参考导体的窗口还可能造成原始总矩阵不对称。[Beattie–Pileggi 1997](https://www.cecs.uci.edu/~papers/compendium94-03/papers/1997/dac97/pdffiles/07_2.pdf)

- Silvaco Hipex 的公开例子把版图切成 box 时显式配置 `SizeX/Y=200`、`VicinityX/Y=40`，并把不同区域/solver 的结果合成共同 netlist。[Hipex Mix & Match](https://silvaco.com/examples/hipex/section1/example16/index.html)

- Pattern-matching PEX 的公开专利也不是裸裁块：3D bounding box 外仍计算 box 与 surrounding shapes 的 2.5D 参数，使用唯一 stitch nodes 重建 composite netlist，并按 interaction range 扩展上下文。[US8732641B1，尤其段落 302–317、321–325](https://patents.google.com/patent/US8732641B1/en)

- FastCap 本身是全局多导体 BEM，以 multipole 加速全局势场计算，不是“硬窗口外直接置零”的算法。[Nabors–White 1991](https://www.rle.mit.edu/cpg/publications/pub19.pdf)

可直接搬用的廉价措施是：`core + halo/vicinity`，只让 core 拥有输出；对几何近邻块做 pair-union solve；用 `R`/`2R` halo 比较作为收敛 canary；关键 qubit–coupler cluster 抽样整域求解。重叠域的完整 Maxwell 矩阵不能盲目相加，否则会双计数；pair 修正应替换受影响子块，或经校准做 inclusion-exclusion，并复查对称性、符号和正定/半正定性。

**4. KQCircuits、SQDMetal 等工具**

结论：KQCircuits 和 SQDMetal 都能求整芯片或用户选定的局部 domain，但每次是在该 domain 内产生完整矩阵；在公开源码中未发现 LOM 式多矩阵节点拼装或邻块 pair 补互容。

- KQCircuits 的一个 `Simulation` 对应一个 3D geometry 和一个 `box`；文档明确说 box 可限制仿真面积，也可模拟 “full chips or portions of the chip”，面积应逐案选择。[Simulation object 文档](https://iqm-finland.github.io/KQCircuits/user_guide/simulation/simulation_objects.html)

- 其 capacitance simulation 输出当前 simulation object 内 signal islands 的 mutual matrix，signal islands 由 ports 确定。[Capacitance matrix 文档](https://iqm-finland.github.io/KQCircuits/user_guide/simulation/simulation_features.html)；仓库还直接提供 [`XMonsDirectCouplingFullChipSim`](https://github.com/iqm-finland/KQCircuits/blob/b879b4c9a58a828dc93c8a69ba4d9972905cab9e/klayout_package/python/kqcircuits/simulations/xmons_direct_coupling_full_chip_sim.py#L29)，说明关键 direct coupling 的公开做法之一是整域建模。

- SQDMetal/Palace 把当前 mesh 中每个 `contiguous_metal_mapping` 建成 terminal，然后运行一个 `Electrostatic` problem。[Palace L106–114、L161–210](https://github.com/sqdlab/SQDMetal/blob/b712277e252f228fbd1a7202f87f9ec9d1ee1e94/SQDMetal/PALACE/Capacitance_Simulation.py#L106)

- SQDMetal/COMSOL 同样在一个模型中为全部 conductors 建 terminals，逐 terminal sweep 填满同一矩阵的各列。[COMSOL L46–114](https://github.com/sqdlab/SQDMetal/blob/b712277e252f228fbd1a7202f87f9ec9d1ee1e94/SQDMetal/COMSOL/SimCapacitance.py#L46)

- SQDMetal 论文 Table 2 比较的是同一个完整 transmon–resonator geometry 在 Palace、COMSOL、Q3D 间的结果，差异 `<0.3%`；不是分块与整片比较。[SQDMetal §III.2、Table 2](https://arxiv.org/html/2511.01220)

截至上述文档、固定源码和论文的检索范围，**没有找到公开超导 EDA 工具实现“邻近块成对求解后补 cross-block mutual”**；不能据此断言厂商内部流程或未公开代码也没有。

**5. 节点命名与绑定**

结论：同名 net 表示同一电气节点是标准惯例，但成熟工具通常配合层次作用域、显式 object-to-net assignment 或 connectivity 识别，不把任意组件显示名直接当无保护的全局主键。

- ngspice `.SUBCKT` 的调用把形式端口映射到调用方实际节点；未列在 `.SUBCKT` 行的内部节点严格 local，只有 ground 和显式 `.GLOBAL` 例外。[ngspice manual §2.6，P56–57](https://ngspice.sourceforge.io/docs/ngspice-manual.pdf)

- 展平嵌套 subcircuit 时，ngspice 自动生成 `xsub1.int1`、`xsub1.xsub2.int2` 等层次名，避免不同实例的局部同名碰撞。[同手册 P465–466](https://ngspice.sourceforge.io/docs/ngspice-manual.pdf)

- PyAEDT/Q3D 的 `assign_net` 是把一个 net 名显式绑定到一个或多个 geometry objects；也提供 solver 的 `auto_identify_nets()`。[assign_net](https://aedt.docs.pyansys.com/version/dev/API/_autosummary/ansys.aedt.core.q3d.Q3d.assign_net.html)、[auto_identify_nets](https://aedt.docs.pyansys.com/version/dev/API/_autosummary/ansys.aedt.core.q3d.Q3d.auto_identify_nets.html)

- Qiskit LOM 此版本的 `_rename_nodes_in_df` 只替换字符串，随后 `np.unique` 合并全局标签；在这些路径中未看到“同名但几何不连续”、rename 后重复标签或跨 cell 导体身份一致性的检查。[rename](https://github.com/qiskit-community/qiskit-metal/blob/422fc05bf6f40c741b3110275dca6d769c3ebb43/src/qiskit_metal/analyses/quantization/lom_core_analysis.py#L747-L760)、[global nodes](https://github.com/qiskit-community/qiskit-metal/blob/422fc05bf6f40c741b3110275dca6d769c3ebb43/src/qiskit_metal/analyses/quantization/lom_core_analysis.py#L1374-L1387)

建议内部身份使用 conductor UUID/层次路径，显示名只作 metadata；跨 cell 连接通过显式 alias 表，并验证 alias 后 cell 内标签唯一、同一 UUID 的层/材料/几何连续或 cut-port 关系一致。

**总裁决**

“共享节点拼装 + 未共同求解的直接跨块互容必丢 + 靠切块纪律保耦合”在数学上成立，也与 Qiskit Metal LOM 2.0 的公开实现一致，因此作为**明确披露的 quasi-lumped 近似**是合理的；但作为生产 EDA 契约仍不充分，防护水平低于经典窗口化 PEX。

最低成本应补五道防线：期望 coupling graph 的 solve-coverage 检查；几何近邻但结构性零的自动告警；core+halo 或相邻块 pair solve；`R/2R` 与抽样整域的 \(\Delta C,\Delta g,\Delta\chi\) 验收；UUID + 显式 alias + collision/continuity 校验。契约还应明确区分“缺失的直接 Maxwell 互容”与“Schur 补经共享节点产生的间接等效耦合”，并注明共享 ground/datum 本身不算可传播耦合的共享节点。