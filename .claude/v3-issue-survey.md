# 原仓(D0-0D/quantum-dsl)物理仿真问题调研 — 原始报告

> **性质: 原始参考资料**(调研 agent 产物, 2026-08-24, 全量读 issues #1–#28 +
> 旧仓 session 取证)。设计结论请读 [`physics-pipeline.md`](physics-pipeline.md);
> 本文只在需要追溯出处(issue 号 / 具体数字 / 旧仓文件路径)时查。
> 注意: 其中 A2/A4 等"规则"是 v3 挖空架构下的对策; v4 已改零厚度片路线,
> 这些坑大半结构性消失——见 physics-pipeline.md §4。
> 另: 报告断言"Palace 拒绝内部面 Terminal"(v3 的判断)已被 v4 本机实测推翻。

## A. 问题目录(按对 gmsh+Palace 静电管线重写的相关度排序)

**A1. ε-nudge(衬底顶面下移躲共面布尔)— 最大单一误差源**
- 出处: session 2607290110 §7; issue #24; 常量 `_gmsh_geo_source.CARVED_GROUND_SUBSTRATE_GAP_SI`
- 症状: carved-ground 设计电容系统性偏低 ~30%。
- 量化(受控实验, 唯一变量 ε): ε=1 µm → C_AA −29.1% / C_AB −40.3%(vs ε=0.001 µm)。
  ε=0.01 µm 代价仅 −0.03%/−0.04%。耦合比自电容敏感得多。
- 非单调陷阱: ε=0 fragment 失败; ε=0.5 µm 产损坏拓扑(2 体重叠); 0.001–0.1 µm 单调收敛。
- v3 状态: 缓解(默认 0.01 µm); 根治 = #24 volume 模式(未做)。

**A2. OCC 共面布尔(carve/fragment)尺度条件化 + 非单调脆弱**
- 出处: session 2607280204(`ee55521`/`6db8134`); issue #24
- fragment 失败模式随几何/坐标尺度漂移, 无单一好 scale; dilate 往返"治病"是
  GTransform 意外 shape-heal(非单位换算), 对另外 6 个设计是纯损伤。
- v3 绕过: `FRAGMENT_SCALE_LADDER=(1.0, 1e2)`, 首档不 dilate, boolean 抛异常才升档。
- 已否掉: 按 bbox 推 scale、OCC fuzzy boolean(`Geometry.ToleranceBoolean` 无效)。

**A3. fragment 后静默损坏拓扑 → 静默错解(最危险一类)**
- 出处: session 2607280204 结论 B; 修复 `ee55521`
- 实测形态: 衬底体复制成 2 个; 负面积 face(−700800 µm²); 整张 z=0 界面
  (1.6e6 µm²)被误标 `gnd_layer1_sfs` → 整个衬底顶面接地, 无报错。
- 根因: 面归属只做质心-in-bbox。v3 修法: 拓扑不变量断言 + 范围包含校验。

**A4. carved-ground 面缺网格细化 → 网格失败 + 电容有偏(issue #18)**
- ground 腔壁(2 µm 高)漏出细化源 → 三共线点零面积三角形 →
  "Invalid boundary mesh (overlapping facets)", 一切 carved-ground 设计必中。
- 根因: `_conductor_surface_tags` 漏 `tracker.ground_faces`。修复 `ab94a13`。

**A5. 网格收敛从未量化(issue #26, open)**
- sung 上 order 1→2 移动 C_Σ −21%; Elmer 网格加密 −6%; Palace(o1) vs
  Elmer 差 +8.4–8.7%(系统性)。单网格数字带 6–21% 不确定度。

**A6. Palace order 2 多 rank 崩溃(issue #22, open)**
- sung 网格(1.54M tets, p=2 → 2.24M 未知量)多 rank 总在第 2 个 terminal
  静默掉 rank; order 1 / 8 rank 干净。怀疑 ZZ 误差估计器的 RT 空间(H1 的 6×)。
- 已排除: 场输出、OOM、vader/CMA。绕过 = 分块降规模。
- **v4 复判(2026-08-24, 64C/128G 裸机)**: 同规模件(two_pads 20/2, ~1.7M
  未知量, order 2)在 spack 干净构建的 Palace 0.16 + openmpi 5.0.10 上
  np=4 / np=32 全 rc=0, C 一致到 1e-12——不可复现, 定性为 v3 运行环境/
  构建问题, 非 Palace bug(pipeline §6)。

**A7. 浮动/双岛 transmon 被当单岛 → C_Σ 错 1.70×(issue #20, 已修 `a8e3ed7`)**
- sung: 单岛写法 C_Σ 38.36 vs 正确差分 22.59 fF; 全绿静默通过。
- 正解: 结支路坐标 `C'=BᵀC_S B`(θ=φa−φb, σ=共模), **求完整 C' 逆取 θθ 块**
  (只删 σ 行列有非对称反例); 全接地时 B=I, 旧值不变。
- 独立验证: 同一 Elmer 矩阵 vs qiskit-metal LOM 2.0, E_C 吻合 <0.1%。

**A8. 浮动 bus/coupler 被硬接地 → 中介耦合整条删掉(issue #20 剩余, 整片路径 open)**
- Schur 消元 g=25.1427 MHz / C_k=−0.766 fF; 硬接地 → 0(删除, 非扰动);
  块内 C_Σ 只错 +0.9%(会静默出货)。
- v3 分块路径已用 Schur 解掉(对 4.05 golden C_k 偏差 7.7e-16); 整片路径仍 open。

**A9. Palace↔Elmer↔论文三方对照口径坑(issue #25)**
- Elmer 输出 SPICE 互容, sif `Permittivity of Vacuum=1` → 需 ×ε0
  (源码 `StatElecSolve.F90:509-519`)。
- qiskit-metal `QElmerRenderer._get_capacitance_matrix` 的 pandas 链式赋值在
  pandas≥2 CoW 下静默失效 → 从原始 `cap_matrix.txt` 自建。
- ground 范围对 C <0.5%, 网格细化 ~6% — 先对齐网格再谈边界。
- ElmerFEM 9.0 装在 `~/opt/elmer`(gfortran 13 需把 `DCRComplexSolve.F90` 改名跳过)。

**A10. 静默空网格 / 守卫绕过(session 2607021950/2607280204)**
- gmsh 对共面 PLC 失败不抛异常, 静默空网格; `QDSL_MESH_ALGO3D` 覆盖分支曾绕过守卫。
- 3D 算法: HXT(10)/Frontal(4) 能划共面界面, Delaunay 报 "PLC Error"。

**A11. hwloc gl 插件挂死一切 MPI(已解)**
- `hwloc_gl.so` TCP 探测 X display(与 DISPLAY 无关), WSL2 SYN 黑洞 →
  MPI_Init 前永久阻塞。修法 `HWLOC_COMPONENTS=-gl`。零输出挂死直接 strace。

**A12. 回归测试只断结构不断数值(issue #28, open)**
- v3 live 测试电容漂 30% 也能过。`terminal-Cinv.csv` 是免费交叉校验点, 从未解析。
- v4: N7 已断数值; #23 的 `targets:`/`validation:` 思路备将来。

**A13. Palace 运行层粗糙点(issue #27, open)**
- 场输出硬编码常开(大网格最慢一段); dry_run 吞 num_procs; 双分支 launch 不一致。

**A14. 数值卫生(issues #19/#15/#21)**
- 求逆前未对称化(未修, v4 应 `(C+Cᵀ)/2`); 近奇异守卫绝对 1e-300 → 已改尺度相对;
  NaN/Inf 拒收已修(`not (isfinite(v) and v>0)`); g 公式口径差 ~E_C/h 几个 %
  (#15, 契约钉 v3 口径); Terminal 前缀匹配丢导体(#19, 未修)。

**A15. gmsh 版本风险(qm4q-repro-spec.md L91-94)**
- 同一 qiskit-metal Elmer 脚本: gmsh 4.11.1 出正定矩阵、4.15.2 出病态
  (物理组 13→7, 负自电容)。该退化在 QGmshRenderer 路径; v4 自己的路径
  在 two_pads 上实测无恙, 但拓扑断言是唯一暴露手段。

**A16. 分块/拼装固有口径(M8 P0, session 2607290329)**
- 同 order/网格/airbox 下分块本身: C_Σ +1.03%/+1.06%, 跨块互容结构性归零。
- "分块 o2 对 Elmer −3%" 是 +12~15% 与 −21% 反向抵消, 别当精度证据。
- χ Koch (3.10) 对老 LOM −16.1% = g 定义 −8.5% + 数值 CPB 谱 −8.3%。

## B. 可复现对照案例

**B1. two_pads**: v3 唯一整片实解 golden(见契约); 无 ground → 从不触发 ε-nudge;
golden 网格扰动 spread 0.202%。tier-2: C_Σ 24.571 fF, E_C 0.7883 GHz,
f01 9.365 GHz, g 374.2 MHz。

**B2. sung_2021_device**(Sung et al. PRX 11 021058 / arXiv:2011.01261):
- 文件: 旧仓 `examples/dsl/geo/sung_2021_device.{geo,meta.yaml}`(header 是
  对照表); 论文 PDF 在旧仓根目录同名文件夹。
- 几何: 3 浮动双岛 transmon(QB1/CPLR/QB2), 焊盘 360×180 / 720×360 µm,
  对地缝 8/30 µm, ground 1900×1100 µm, silicon −750 µm; airbox 890/1650/200;
  mesh 2/80; `substrate_gap_um: 0`。
- 论文值: C_1=95, C_c=228, C_2=98, C_1c=C_2c=5.36, C_12=0.125 fF;
  E_C/h=0.195/0.085/0.190 GHz(→C_Σ=99.3/227.9/101.9 fF); ω/2π=4.16/5.45/4.00 GHz;
  g_1c/g_2c/g_12=72.5/71.5/5.0 MHz。
- Elmer 权威档(min2/max30, 6.87M tets): C_Σ 102.1/232.8/102.1(论文比 1.00–1.03);
  C_12 未复现(0.0030 vs 0.125 fF, ×0.02——差分远场相消); g 偏高 1.4–1.5×
  (无磁通工作点)。Palace 整片 o1: 110.7/252.8/111.0(vs Elmer +8.4–8.7%)。
- 陷阱: circuit_model 的 g_12=3.4 MHz 接近论文 5.0 是巧合(coupler 中介路径主导)。

**B3. qm4q_transmon_cell**(qiskit-metal tutorial 1.3 单 TransmonPocket 的
Elmer 对照):
- 文件: 旧仓 `examples/dsl/geo/qm4q_transmon_cell.*` + `qlib.geo`;
  参考 notebook `examples/qiskit_metal_ref/qm4q_transmon_cell_ref.ipynb`
  (kernel=metal-env, 可 nbconvert 重跑); spec `.claude/qm4q-repro-spec.md`。
- 几何: pad 450×90 ×2, pocket 650×650, ground 1250×1050, 4 connector +
  折线引线, JJ 20 µm; pec 2 µm@z0, silicon −750 µm εr=11.45。
- Elmer 参考(P1, min5/max50, 7×7): pad_top 109.8, pad_bot 114.6,
  conn 63.3/63.5/74.9/67.3, pad 互容 −36.0 fF。
- v3 误差演化: 1 µm 缝+接地 −30% → 共面+接地 +41% → 共面+开放 o1 +44%
  (欠收敛)→ 共面+开放+o2 −5.5%(conn +13~17%, 引线贴 airbox 过耦合)。

**B4. qiskit-metal 4.05 双 transmon LOM golden**(纯代数, 零 FEM):
- spec: 旧仓 `.claude/lom-parity-spec.md`。C_Σ=61.933825477/82.664266834 fF;
  E_C=312.756869/234.324093 MHz; g=25.1427 MHz; C_k=−0.766012 fF。
- v3: C_k 偏差 7.7e-16; E_C 偏差 7.6e-9(常数代差)。

**B5. Elmer 交叉验算脚本链**(sung): 在 v3 会话 scratchpad, 未进仓(#25)。
