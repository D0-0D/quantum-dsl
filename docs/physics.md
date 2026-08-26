# 物理口径与数值决策：从版图到哈密顿量

> **本文档的定位**：v4 每一个"为什么这么算"的依据——物理图像、核心架构决策（零厚度片 imprint）、单位、
> 网格收敛实测、每条公式的文献出处、失效防线、分块拼装的适用边界、对论文的外部验证与容差账、Palace 运行面。
> 读者：碰 `mesh.py` / `palace.py` / `circuit_model.py` / `cpw.py`、改容差、或要给真实器件报数的人。
> 所有"实测"均为 2026-08-24/25 在 WSL2 + gmsh 4.15.2 + Palace 0.16.0（two_pads）与 96 核 / 384 G 远端机（sung）完成，
> 原始 CSV 归档在 `v4-dev` 分支 `.claude/n15-evidence/`。文献列表在文末 §14。

---

## 术语

| 术语 | 含义 |
|---|---|
| OCC | OpenCASCADE，gmsh 的 CAD 内核（布尔、fragment 都是它做的） |
| fragment / imprint | OCC 操作：把一组几何体互相切开并缝合成共形拓扑；2D 面作为工具参与时等价于把面"印"进它所在的界面 |
| Maxwell 矩阵 | 静电电容矩阵 C：对角正（自电容）、非对角负（−互容）、对称。Palace 写 `terminal-C.csv`；SPICE 互容矩阵（全正，对角 = 对地电容）由它代数导出 |
| order (p) | Palace `Solver.Order` = FEM 基函数多项式阶数 |
| L0 | Palace `Model.L0` = 网格坐标单位折算米的系数 |
| LOM | lumped-oscillator model：用 C⁻¹ + 约瑟夫森电感推 qubit 参数 |
| PEC | 理想电导体 |
| N0–N15 | 契约条目编号（[`../SPEC.md`](../SPEC.md)），测试 docstring 首行回指 |

## 1. 我们在算什么，为什么静电就够

超导量子芯片 = 硅衬底上的平面金属图形（焊盘 / 共面波导，膜厚 ~100–200 nm）+ 约瑟夫森结。设计者关心的不是几何，
是哈密顿量参数：每个 qubit 的 E_C、f01、非谐 α，qubit 间耦合 g，读出腔色散位移 χ。

工作频率 5–10 GHz → 波长厘米级，芯片特征 10²–10³ µm ≪ λ，**准静态近似成立**：电磁问题退化为"提取集总电容 +
集总电感"。约瑟夫森结是唯一的非线性 / 电感元件，作为集总参数（L_J 或 E_J）直接进电路模型，**不进静电网格**
（把结当导体桥会短路两块焊盘，C 矩阵失去意义）。

FEM 解的问题：在域 Ω（衬底 ε_r = 11.45 + 真空 ε = 1）上解 ∇·(ε∇φ) = 0；第 i 个导体面 φ = 1 V、其余 0 V
（Dirichlet，Palace 叫 Terminal），逐导体解 N 次，由感应电荷得 C 的第 i 列。外边界接地（模拟屏蔽盒）或
开放（∂φ/∂n = 0，近似自由空间）。

## 2. 导体是边界条件，不是材料

超导金属伦敦穿透深度 ~90 nm，场不穿透，整块金属是等势体。静电里导体**内部无场、无自由度**，它在 FEM 里的
正确身份是**边界条件**（在导体表面钉电位），不是一块要网格化的材料。这一条决定了 §4 的全部架构讨论。

## 3. 计算域怎么建

`.geo` 里作者只画金属面（µm）；衬底与真空由 `build_mesh` 按 meta 合成：

```
z = +top    ┌──────────────────────────────────┐  airbox.top_um
            │            vacuum  ε = 1          │
z = 0       │   ▬▬▬▬A▬▬▬▬          ▬▬▬▬B▬▬▬▬     │  金属片 = 界面上的 Dirichlet 边界 (零厚度)
            ├──────────────────────────────────┤
            │        substrate  ε = 11.45       │
z = −thick  ├──────────────────────────────────┤  −materials.substrate.thickness_um
            │            vacuum                 │
z = −bottom └──────────────────────────────────┘  −airbox.bottom_um
             ◄── 导体 bbox ± airbox.side_um ──►
```

**读法**：top / bottom 从 z = 0（芯片面）起算；bottom > thickness 时衬底下方留一层真空；六面全是盒壁。
真空盒在 xy 方向比衬底再外扩 1 µm（`mesh.py:39`），与回归锚配方一致。

- **外边界接地**（默认）= 芯片装在接地屏蔽盒里。**开放**（不给盒壁挂 Ground）更接近自由空间，与 qiskit-metal /
  Elmer 的 FarField 口径一致——但**没有任何金属地时问题奇异**（电位无参考），`palace_config` 会 raise。
- 域大小：旧仓受控实验 ground 范围对 C 影响 <0.5%，远小于网格效应；但开放边界 + 导体贴近盒壁会过耦合
  （qm4q connector +13～17%）。盒壁离导体至少"缝宽的几十倍"。公开起点：SQDMetal 接地盒 = 芯片高 ×2、XY +20%；
  KQCircuits 默认每侧 +300 µm。给真实器件报数应做 1× / 1.5× / 2× 域尺寸扫（C 变化 <0.2–0.5% 验收）。

## 4. 金属的表示——核心架构决策

静电里导体没有体自由度（§2），那金属在**网格**里长什么样？三个候选：

| 方案 | 做法 | 代价 / 收益 |
|---|---|---|
| **(a) 零厚度片**（v4） | 焊盘 2D 面直接 fragment（imprint）进衬底/真空界面，Terminal 挂内部边界面 | 无布尔减 → 无 ε-nudge、无 scale-ladder、无腔壁归位；天然精确共面；更接近真实膜厚；管线最短 |
| (b) 薄板挖空（v3） | 面 extrude 成 2 µm 板 → 从真空布尔减 → 腔壁 = 域外边界，Terminal 挂腔壁 | 引入 OCC 共面布尔的全部失效类；多一个人为"金属厚度"参数 |
| (c) 金属网格化为实体 | 金属体 + 高对比材料 | 静电里纯浪费（内部无场），高对比伤条件数——排除 |

**外部证据一边倒支持 (a)**：Palace 官方 CPW 例的金属就是 "infinitely thin, perfectly conducting boundary
surface"（网格脚本默认 `metal_height = 0`）；transmon 例 PEC 面、材料域只有 vacuum / substrate；
KQCircuits（IQM）默认 `metal_height = 0`；SQDMetal 2026 基准用 zero-thickness PEC，Palace / COMSOL / Q3D 三求解器
互差 <0.3%；Ansys Q3D 惯例是 thin conductor。膜厚定量：CPW 一阶修正 Δ = (1.25t/π)(1 + ln(4πW/t))，真实 100–200 nm
膜 ≈ 1.0–1.8% 几何因子，**1 µm 人工板厚 ≈ 7.6%**——用 1–2 µm 板"代表"薄膜不是无害近似。

**v3 为什么选 (b)**：当年断言"Palace 拒绝内部面上的 Terminal"。本机复检推翻了这个断言：Palace 0.16 对方案 (a)
直接可解。v3 看到的 abort（`"A non-periodic face cannot have multiple boundary elements"`）在 (a) 路径上复现了，
根因是 `.geo` 作者写的 Physical 组在 imprint 路径下**存活**到最终网格，与实现自己加的组重叠 → 同一几何面写出两条
边界元。捕获作者组后 `removePhysicalGroups()` 即愈（`mesh.py:115`）。挖空路径下焊盘面被 extrude/cut **消耗**，
作者组变空，所以 v3 从未踩到——这也解释了两条路径的"玄学"差异。

**ε-nudge 的来龙去脉**（为什么 v4 可以让它不存在）：方案 (b) 里带 ground 的设计要做"2 µm 金属板与衬底顶面精确
共面"的布尔减——OCC 对精确共面布尔要么失败要么静默损坏拓扑，v3 的对策是把衬底顶面下移 ε 塞一层真空缝躲开
共面。这层缝是纯粹的工具妥协，却是一等一的物理误差源：ε = 1 µm 时 C 偏低 29%、耦合偏低 40%（旧仓受控实验），
且 ε 不单调（0.5 µm 反而产损坏拓扑），v3 最终缓解到 ε = 0.01 µm。方案 (a) **根本没有布尔减**——金属片印在界面上，
共面是构造性精确，整个 ε-nudge 问题类连同 fragment scale ladder 一起消失。

**内部边界在 Palace 里的机制**（源码取证，出处 §14 [P1]–[P3]）：Palace 有 `CrackInternalBoundaryElements`
（默认开）——对内部 **PEC / Ground** 面复制节点、解耦两侧，所以带 ground plane 的设计走的是官方支持路径；
**Terminal** 不在 crack 属性集合里，作为 essential Dirichlet 直接生效（静电里等势面两侧共节点无影响——本机实测可解
且与挖空细网格一致 ~0.1%）。文档只明确禁止 wave port 在内部面，未禁 Terminal / Ground。

## 5. 单位与 Palace config

- **仓库内部长度一律 µm**，网格文件坐标也写 µm，Palace 端用 `Model.L0 = 1e-6` 声明"网格单位 = 10⁻⁶ 米"
  （`palace.py:76`，**仓库唯一的换算点**）。另一条路（先把模型 `occ.dilate` 到米、`L0 = 1`）v3 用过：`dilate` 是
  GTransform 全量几何重建，对部分几何是静默损伤；µm + L0 方案实测精度相同（§6 变体 A vs B）且根除该失效类。
  GDS 也 µm verbatim（`unit = 1e-6`）——不双重缩放。
- **`Solver.Order = 2` 是承重件不是可调优化**：同网格 order 1 实测偏 +7.3%（3.6× 契约容差，§6 A″）。电容收敛对
  p 加密远比 h 加密敏感（边缘场奇异）。
- config 骨架（`palace.py:74-94`）：`Problem.Type = Electrostatic`；`Model{L0, Mesh}`；`Domains.Materials`
  = [{衬底组, ε_r}, {真空组, 1.0}]；`Boundaries.Ground{Attributes: [外边界组(, ground 组)]}`；
  `Boundaries.Terminal = [{Index: i, Attributes: [导体组]}]`（Index = C 矩阵行列号，1 起，顺序 = `Mesh.labels`）；
  `Solver{Order: 2, Linear: {BoomerAMG + CG, Tol 1e-8}}`。
- 场输出（Paraview / Save）默认**关**：电容工作流只消费 `terminal-C.csv`，场输出是大网格上最慢最占盘的一段。
- 运行环境：`PALACE_BIN` 定位二进制；**WSL 必须 `HWLOC_COMPONENTS=-gl`**（`build.py:64` 注入；hwloc gl 插件 TCP
  探测 X display 会挂死 `MPI_Init`，裸机不需要）；cwd = config 目录，`Model.Mesh` 写相对文件名；`QDSL_PALACE_NP`
  控 rank 数，默认 1。

## 6. 网格与收敛（实测）

导体边缘电场奇异（∝ r^(−1/2)），电容误差集中在边缘 → Distance + Threshold 尺寸场对**所有导体边缘曲线**细化
（`mesh.py:233-247`：min → max 渐变于距边缘 10 → 130 µm，Sigmoid；metal 与 ground 都进细化源——v3 漏掉 carve
腔壁曾使一切带 ground 的设计网格必炸，见 issue #18）。网格默认 Delaunay，**每条出口都过空网格守卫**（gmsh 对失败
可能不抛异常而静默返回空网格），失败回退 HXT（不能当全局默认，部分几何反而失败）。

two_pads 实测（Palace 0.16，接地盒）。"偏差"列以 **v3 旧 golden** `[[24.7288, −1.976], [−1.976, 24.7293]]` 为参照：

| # | 表示 | 网格 max/min µm | order | C_AA (fF) | C_AB (fF) | 对旧 golden 最大偏差 |
|---|---|---|---|---|---|---|
| A | (b) 2 µm 板挖空，dilate + L0 = 1 | 40/4 | 2 | 24.722 | −1.976 | 0.038% |
| B | (b) 同上，**µm + L0 = 1e-6** | 40/4 | 2 | 24.733 | −1.975 | 0.072% |
| A′ | (b)，网格加密（33k → 244k 节点） | 20/2 | 2 | 24.557 | −1.953 | 1.18% |
| A″ | (b)，**降阶** | 40/4 | **1** | 25.769 | −2.119 | **7.25%** |
| **C** | **(a) 零厚度片 = 现行回归锚** | 40/4 | 2 | 24.532 | −1.947 | 1.46% |
| C′ | (a)，网格加密 | 20/2 | 2 | 24.342 | −1.919 | 2.87% |

解读：
- 旧 golden 自带 ~+1% 网格偏置（A → A′ 移 −0.7～−1.2%；C → C′ 同幅）：物理收敛值在其下方 ≈ 1%。
- **2 µm 板厚效应是真实物理，不是离散误差**：同网格下 (b) − (a) 差 ≈ 0.8%（对角）/ ≈ 1.6%（非对角），粗细两档一致。
  真实器件膜厚 100–200 nm，(a) 才是更忠实的模型。
- C′ 离旧 golden 2.87% 不是 (a) 的缺陷，而是旧 golden 绑定了 v3 的板厚 + 粗网格两个工件偏置——这正是 §7 重钉的动机。
- **报任何 C 值都应给两档网格的相对变化**——单网格数字在复杂几何上带 6–21% 不确定度（旧仓 sung / Elmer 实测）。
- **order 2 多 rank 在干净环境无恙**（64 核 / 128 G 裸机实测）：C′ 同款 20/2 网格（~1.7M 未知量）在 spack 全新构建
  的 Palace 0.16 + openmpi 5.0.10 上 np = 4 与 np = 32 均 rc = 0，C 一致到 1e-12 且与 WSL 实测逐位吻合——v3 issue #22
  的"静默掉 rank"是运行环境 / 构建问题，不是 Palace bug。
- 光滑区 p 加密指数收敛，奇异点附近 h 加密更有效——边缘细化不可被升阶替代。KQCircuits 默认 p = 3；Q3D 默认目标 0.5%。

## 7. 回归锚（two_pads golden）

契约 N7 的 live golden 是**可复现的实测锚点，不是绝对真值**：

- `LIVE_MAXWELL_GOLDEN = [[24.5324, −1.9472], [−1.9472, 24.5353]]` fF（全精度 24.53243335381 / −1.947218428813 /
  24.53533214664），配方 = v4 产品路径：零厚度片，mesh 40/4，order 2，接地盒。
- f01 golden 由它 + 10 nH 闭式重算：`[9.3989, 9.3984]` GHz，容差 3%。
- 实现按 fixture 配方应落在 golden ~0.1% 内；2% 容差吸收网格器版本波动。2026-08-26 复测：一次求解 123 s，通过。

它曾是 v3 配方的实测值 `[[24.7288, −1.976], …]`；2026-08-24 因"物理上更收敛反而离 golden 更远"的倒挂不可接受，
重钉为 v4 产品路径实测值。**golden 不锚参考实现，只锚物理与闭式**。

## 8. 电容矩阵 → 哈密顿量（逆电容 LOM）

`circuit_model.py`，公式口径经双重验证：对契约闭式 golden 逐位复算 + 文献核对（两轮独立检索，结论一致）。

**约化与求逆**（`circuit_model.py:355-379`）：取被引用岛的子矩阵 C_S（契约要求全部 label 被认领，故 = 全矩阵），
组结支路变换 φ = Bξ：接地单岛 θ = φ_a（选择列）；浮动双岛 θ = φ_a − φ_b 外加共模 σ = (φ_a + φ_b)/2。
`C′ = Bᵀ C_S B` → **完整求逆取 θθ 块**：共模电荷守恒 = 0 的正确约化只在完整逆里体现（θθ 块的逆 ≠ 逆的 θθ 块；
"删共模行列再求逆" = A⁻¹，仅 B = 0 时等价）——Yanay et al. [L4] Eq. 50–57 同口径。闭式检查点：岛 a, b 对地
50/40 fF、岛间 30 fF → C_eff = 30 + 50·40/90 = 52.222… fF；把 b 静默接地会得 67.14 fF（v3 在 sung 上错 1.70×）。
全浮动时 C 有规范零模奇异，求逆前必须选 datum。

**参数**：
- `C_Σ,k = 1/[C′⁻¹]_θθ,kk`（dressed 有效电容，**不是** Maxwell 对角元——LOM 论文 [L1] Eq. 8/11a 同口径；N8 有反例测试：
  two_pads 的 24.57 fF 既不是对角 24.73 也不是对地 22.75）。
- `E_C = e²/(2C_Σ)`；`E_J = (ħ/2e)²/L_J`；`f01 = (√(8E_C·E_J) − E_C)/h`；`α = −E_C/h`。
- **对称化 `(C + Cᵀ)/2` 只是清理求解器残差，不是物理步骤**：先查 `‖C − Cᵀ‖_F/‖C‖_F`，>1e-6 说明解有病，raise 而非
  掩盖（`circuit_model.py:299-307`）。
- 耦合 `β = |C′⁻¹_ij|/√(C′⁻¹_ii·C′⁻¹_jj)`（纯几何，与磁通 / E_J 无关——sung 对论文断言的就是它），
  `g = ½·β·√(f01_i·f01_j)`。**这是文献真实分叉处，契约钉死了其中一支**：谐振子零点涨落推导（Blais [L3] Eq. 133/134、
  qiskit 旧 LOM 的 Z_qp）给裸等离子频率 `f_p = √(8E_C E_J)/h`；Krantz [L2] Eq. 105 与 v3 / 契约用修正后
  `f01 = f_p − E_C/h`。两者之比 √Π(1 − 1/√(8·EJ/EC))：EJ/EC = 20 时 f01 口径**低 7.9%**，= 50 时低 5.0%。
  跨文献比 g 先对口径，别"顺手改进"。`|·|` 只适合输出耦合强度，多路径 / 环路哈密顿量必须保留 C⁻¹_ij 符号。
- **SQUID**：`E_J(φ) = (E_J1 + E_J2)·hypot(cos πφ, d·sin πφ)`，`d = (E_J1 − E_J2)/(E_J1 + E_J2)`——Koch [L5] Eq. 2.17/2.18
  吸收相位支路后的幅值，Krantz Eq. 22 直接用此形；无奇点（教科书 `|cos|·√(1 + d²tan²)` 在 φ = 0.5 是 0×∞ → nan）。
  检查点：E_J1/E_J2 = 12/8 GHz，φ = 0 → 20，φ = 0.5 → 4 GHz。
- **χ（N11）**：`chi_0 = −2g²·f01/(f01² − f_r²)`，`chi_1 = g²·(1/(f01−f_r) − 2/(f12−f_r) + 1/(f01+f_r) − 2/(f12+f_r))`，
  `χ = (chi_1 − chi_0)/2`——**非 RWA 三能级二阶**结果（含反旋转分母），依据 Zhu et al. [L6] Eq. (11)–(14) 取三能级。
  ⚠ **不要**引成 Koch (3.9)/(3.10)——Koch 原式是 RWA 版（无 ω + ω_r 项），qiskit-metal 源码注释就是这处误引的源头。
  返回**单边 cavity pull**（不是 2χ）；共振时分母为零 → raise。
- **TL 谐振器等效 LC**：`C_r = π/(2ω_r Z0)`，`L_r = 1/(ω_r² C_r)`；λ/4 在同频下 C_r **减半**、L_r 加倍（方向别记反）。
- 常数：e / h / Φ₀ 在 SI-2019 下精确（e = 1.602176634e-19 C，h = 6.62607015e-34 J·s），ħ 派生不硬编码；
  μ0 / ε0 自 2019 起带实验不确定度（~1e-10，无实际影响，但措辞别写"全部常数精确"）。
- **适用域**：微扰式要求 EJ/EC ≫ 1；two_pads 例子 EJ/EC ≈ 20.6，首阶展开带几个百分点误差——测试钉的是**自洽性**
  （rel 1e-9），不是物理精度到第 9 位。`f01 ≤ 0`（EJ/EC < 1/8）raise。

## 9. CPW 解析（`cpw.py`）

**自洽公式集**，每一式有独立文献出处：

| 量 | 公式 | 出处 |
|---|---|---|
| k0 / k1 | k0 = s/(s+2w) 共面；k1 = sinh(πs/4h)/sinh(π(s+2w)/4h) 有限衬底、开放上空间（**sinh** 分支；背面接地版图是 tanh 分支，不可混用） | Simons [C2] Eq. (2.37)/(2.38) |
| C′, ε_eff | C′ = 2ε0(ε_r−1)K(k1)/K(k1′) + 4ε0 K(k0)/K(k0′)；q = ½·K(k1)K(k0′)/(K(k1′)K(k0))；ε_eff = 1 + q(ε_r − 1) ≡ C′/(4ε0 K0/K0′) | Göppl [C1] Eq. (2)–(5)（源流 Wen 1969） |
| L_g′ | (μ0/4)·K(k0′)/K(k0)，纯几何外电感 | 同上 |
| L_k′ | Mohebbi & Majedi 薄膜拟合式（`cpw.py:181-189`），窄线超导 CPW 里与 L_g 同量级，**不是修正项** | [C3]，对 Clem [C4] 核定 |
| Z0, λ_g | 总 L′ = L_g′ + L_k′；**Z0 = √(L′/C′)，λ_g = 1/(f·√(L′C′))** | Clem [C4] Eq. (35)：加入 L_k 后相速 / 阻抗必须由总 L′C′ 重算，不能再用 c/√ε_eff |

K(k) 用 AGM：K(m) = π/(2·agm(1, √(1−m)))，参数约定 m = k²（与 scipy 一致）。⚠ **接口单位是 SI 米 / Hz**，
10 µm 线宽写 `10e-6`。

**翻案记录（2026-08-24）**：v3 = qiskit-metal `cpw_calculations.py` 逐行搬运，V4-3 首版把它的输出钉为 golden——那套
Z0/λ_g 不含 Lk，ε_eff 打了膜厚 + TE 色散补丁而 C 没打（差 ~2.6%，Lext = Z0²C 连带失真），常数还是截断值。契约改锚
自洽集后典型工况（5 GHz，s = 10 µm，w = 6 µm，h = 760 µm，t = 200 nm）差值：Z0 −1.08%（撤色散补丁 −1.35% + 补 Lk
+0.28%）、λ_g −1.56%、ε_eff +2.63%、Lext −2.70%；C 与 Lk 公式不变。弃掉的膜厚 ε 修正 / TE 色散在本仓工况
（t/w ≲ 0.03，f ≲ 0.2·f_TE）均 <3% 且是不自洽根源；>20 GHz 或厚膜再议，路径是 2D/3D EM 而不是加回补丁。
现行 golden：Z0 = 51.045 Ω，ε_eff = 6.2248，λ_g = 23.965 mm，且测试断言 λ_g·f·√(L′C′) ≡ 1。

## 10. 失效防线（每条背后都有一次"无报错出错解"）

| # | 防线 | 代码 | 实案 |
|---|---|---|---|
| 1 | fragment 后拓扑不变量：衬底恰 1 体；无负 mass；Σ体积 ≤ bbox 体积 ×1.001 | `mesh.py:159-183` | OCC 静默复制衬底体 / 产负面积面 / 整张界面误标 ground |
| 2 | 3D 网格每条出口过非空断言（Delaunay → HXT 回退 → raise） | `mesh.py:258-275` | gmsh 静默空网格 → Palace 无信息 abort |
| 3 | 捕获作者 Physical 组后立即 `removePhysicalGroups()`，实现自己的组是唯一输出 | `mesh.py:115` | §4 的双边界元 abort |
| 4 | 面归属用 fragment 的 `out_map` 直接映射，不做 bbox 猜测；导体面不得泄漏到外边界 | `mesh.py:184-216` | 质心判据误归位；airbox 没包住导体 |
| 5 | config 引用的组号来自同一次 `build_mesh` 返回值 | `palace.py:62-88` | attribute 不存在于网格 |
| 6 | 输入卫生：CSV 与 L_J/E_J 拒 NaN/Inf（`not (isfinite(v) and v > 0)`——1e400 溢出成 inf 能绕过 `<= 0`）；C 求逆前查反对称残差；奇异判据尺度相对（pivot ≤ 1e-12·max|C|） | `palace.py:126-130`, `circuit_model.py:216-222, 299-307, 163-174` | nan 静默写出整条结果 |
| 7 | 语义完整性：未被任何 junction 认领的 Terminal **禁止静默接地**——要么 Schur 消掉要么 raise；`islands` 长度只能 1 或 2 | `circuit_model.py:346-352` | 静默接地把中介耦合 25 MHz 删成 0；双岛当单岛 C_Σ 错 1.70× 且测试全绿 |

## 11. 分块拼装的适用边界（N9 / N14）

v4 的"逐块提取 → 同名节点累加 → Schur 消元"与 qiskit-metal composite LOM（LOM 2.0 [L1]）**机制同构**：
节点 rename → 邻接表 `+=` 累加 → Schur 补 `C − C·S(SᵀCS)⁻¹SᵀC`（v3 曾对其 golden 命中 7.7e-16）。这是**明确披露
的 quasi-lumped 近似**，合理；但要认清边界：

- **数学性质**：两导体的直接 Maxwell 互容，只在它们于同一次求解中共现时存在；共享节点只能提供网络中介路径；
  **共享 ground 不算耦合路径**（datum 不传播）。
- **丢掉的量不总是小**：公开设计里直接 q–q 腿相对 q–coupler 腿从 <1%（Goto 2022 双 transmon coupler：0.4%）到
  ~10–15%（常规单 coupler：g_12 = 25 vs g_1c = 250 MHz）都有；相消型 coupler 的零耦合点 g = g_12 − g_eff **直接依赖**
  直接腿——切错块会移动甚至消灭零点。"跨块直接互容天然可忽略"不成立。
- **业界对照**：KQCircuits / SQDMetal 不做分块拼装，整域求解；经典 EDA 窗口化提取（vicinity / BEM windowing /
  pattern + stitch）都带显式作用距离 / 重叠 / 误差界。LOM 论文自己的切块经验：cell 要装下 qubit pads + 相邻 CPW 段 +
  coupler pads，cell padding ~100 µm 后对 χ 影响 <0.5%（仅对其版图成立）。
- **v4 决议**：**切块纪律——有意直接耦合的导体对必须同块共现**；整片求解是默认（`build(solve=True)` 只解整片），
  blocks 可选。廉价防线：`build()` 对"不同块且从不共现、bbox 间距 < `airbox.side_um`"的导体对发 `UserWarning`
  （`build.py:125-142`）。core + halo、邻块 pair-solve、期望耦合图覆盖检查按需再上。
- Schur 消元的物理含义：被消节点**电荷恒为零的正确积掉，不是接地**。`keep` 拼错 raise。

## 12. 外部物理验证：Sung et al. PRX 11, 021058（N15）

two_pads 是自参照回归锚（钉配方可复现）；sung 例子才锚**外部真相**（论文 / 跨求解器）。器件：三体 tunable-coupler
（QB1 — CPLR — QB2），三个浮动 transmon，简化版图（无 junction leads / 读出爪 / 控制线）。论文报告值与判据的
单一出处在 [`../examples/sung_2021_device.meta.yaml`](../examples/sung_2021_device.meta.yaml) 头注。

契约配方：mesh 80/2，order 2，开放边界 + ground sheet，14.1M tets / **18.5M H1 未知量**。实测：

| 口径 | QB1 | CPLR | QB2 | 对论文 |
|---|---|---|---|---|
| 论文（设计仿真 + 对实测频率拟合） | 99.3 | 227.9 | 101.9 | — |
| v3 Elmer 档（P1，6.87M tets） | 102.1 | 232.8 | 102.1 | 1.00–1.03 |
| 本配方 **order 1**（同网格） | 101.4 | 232.6 | 101.3 | +2.1 / −0.6% |
| 本配方 **order 2**（契约） | **95.83** | **220.72** | **95.82** | **0.965 / 0.969 / 0.940** |
| 粗网格 160/10，order 2 | 101.2 | 231.0 | 101.1 | +1.4～+1.9% |

（单位 fF，C_Σ）。β_qc：order 2 实测 0.0393，论文 0.0364（+8%），Elmer 0.0390。

**容差翻案（2026-08-25，±5% → ±8%）**：原 ±5% 按 Elmer 档标定。同网格 order 1 对 Elmer <1%——两独立求解器同 P1
同答案 = **管线正确性的外部确证**；同时揭穿 Elmer 档"对论文 ±3%"是 **P1 离散正偏（+5.4～5.8%，与 two_pads o1 +7.3%
同类）与简化版图结构性缺失（−4～6%）相互抵消**的产物，不再作容差依据。版图对称 ⇒ QB1/QB2 必然同值，论文 99.3/101.9
的不对称结构性无法同时命中（QB2 的 −6.0% 因此是三条里最紧的）。粗细两档跨 ~5.5% ⇒ 契约配方**尚未收敛**，更细只会
更低（离散从上方收敛）。锚（论文值）不动，容差 ±8% = 版图缺失 4～6% + 网格 / 求解波动 ~2%。**诊断参照**：若失败，
先在同网格跑 order 1 比对 Elmer 档，再怀疑物理。⚠ v3 自己的 "Palace 分块 o2 对 Elmer −3%" 同样是抵消产物
（分块抬 C_Σ +12～15%，order 1 → 2 压 −20～22%）。

**结构性排除项**（不是精度问题，不断言）：C_12 / β_12——直接 q–q 互容 0.125 fF 在本简化版图不存在（三个矩形 pad
差分远场相消，Elmer 也只解出 0.003 fF），`circuit_model` 报的 q–q 耦合走 coupler 中介路径（β_12 = 0.0016），数值接近
论文纯属巧合；绝对 g 与 CPLR/QB2 的 f01——论文在磁通工作点（ω_c/2π = 5.45 GHz），本模型无磁通旋钮坐零磁通（~6.8 GHz），
g 系统性偏高 ~1.4×。

**精度参照系**（业界）：Palace spheres 例对解析解 0.57–3.5%；SQDMetal 三求解器互差 <0.3%，但对**实验**频率 RMSE
~6% / 3.5%、g RMSE ~24.5%（材料 / 制程 / 省略物理）——仿真间一致性 ≠ 对器件预测精度。

## 13. Palace 运行面

- **内存**：每个 terminal 解完都跑误差估计器（RT 通量恢复），即使 `Refinement.MaxIts = 0` 也不跳过——大网格内存预算
  要把 estimator 阶段算进去。sung 规模实测：np = 32 峰值 **154 G**（64 核 / 128 G 机在多重网格层级组装处被 OOM 杀，
  signal 9 无一字诊断——大网格失败先想内存），96 核 / 384 G 机 20 min 完成（串行 mesh 预处理 6 min + 盘 IO 4 min；
  o1 同网格 11 min）。Palace 自报的 "current memory" 在组装前打印，远低于后续峰值，不能当预算依据。
- **多 terminal = 顺序单 RHS**：矩阵 / 预条件器构建一次复用，N 导体 = N 次 CG 解——terminal 数是线性成本。
- **多 rank order 2**：上游无对应 bug 报告；裸机实测无恙（§6）。WSL 上仍建议 `-np 1` 起步 + 盯内存。
- **AMR**（0.12 起支持 Electrostatic，`Model.Refinement`，默认 `MaxIts = 0` 关）：是 gmsh 边缘 seed 网格**之上**的二次
  自适应，不能取代 Distance/Threshold 尺寸场。接入时 1–2 轮、设 MaxSize、纯四面体可 `Nonconformal = false`；避开
  `SaveAdaptMesh + SaveAdaptIterations` 组合（0.16.1 引入的覆盖 bug #887）。正面样本：SQDMetal AMR O2 到 71M DoF，
  对 COMSOL/Q3D <0.3%。v4.0 契约不需要 AMR。
- **版本**：最新 0.17.0（2026-06）；spack 只到 0.16.0（本机同版）。0.16.1 / 0.17 带来的是诊断（分阶段内存表、resolved
  config）与 cracking / AMR 修复，**无静电相关行为变化**——留在 0.16 没有已知代价；若升，从源码 tag 构建并用 N7 golden 回归。
- **静电外边界只有两种**：`Ground`（Dirichlet 0）与 `ZeroCharge`（Neumann）；不写就是自然边界 ≡ ZeroCharge——
  "开放边界" = 直接不给盒壁挂 Ground。无 Absorbing / PML。
- **对称面减半**：偶对称 ZeroCharge、奇对称 Ground 原理可行，但完整 C 矩阵的逐 terminal 单位激励通常破坏对称性——不做。
- 官方额外输出 `terminal-Cinv.csv` 可对照自家求逆做零成本交叉校验（v4.0 未接）。

## 14. 参考文献与出处

**LOM / 电路量子化**
- [L1] Minev, Z. K. et al., "Circuit quantum electrodynamics (cQED) with modular quasi-lumped models", arXiv:2103.10344
  （qiskit-metal LOM 2.0；Eq. 5 全局矩阵求和、Eq. 7b Schur 补、Eq. 8/11a 逆电容口径）。
- [L2] Krantz, P. et al., "A quantum engineer's guide to superconducting qubits", Appl. Phys. Rev. 6, 021318 (2019)
  （Eq. 22 SQUID 幅值；Eq. 105 耦合 g 频率因子）。
- [L3] Blais, A. et al., "Circuit quantum electrodynamics", Rev. Mod. Phys. 93, 025005 (2021)（Eq. 23–25 零点涨落；Eq. 133/134 g 用 f_p）。
- [L4] Yanay, Y. et al., "Two-dimensional hard-core Bose–Hubbard model with superconducting qubits", npj Quantum Inf. 6, 58 (2020)
  （Eq. 50–57 浮动 transmon 的完整求逆约化）。
- [L5] Koch, J. et al., "Charge-insensitive qubit design derived from the Cooper pair box", Phys. Rev. A 76, 042319 (2007)
  （Eq. 2.17/2.18 SQUID；(3.9)/(3.10) 是 RWA 版 χ——**不要**引作本实现出处）。
- [L6] Zhu, G. et al., "Circuit QED with fluxonium qubits: theory of the dispersive regime", arXiv:1210.1605
  （Eq. (11)–(14) 非 RWA 三能级 χ）。

**CPW**
- [C1] Göppl, M. et al., "Coplanar waveguide resonators for circuit quantum electrodynamics", J. Appl. Phys. 104, 113904 (2008)（Eq. 2–5）。
- [C2] Simons, R. N., *Coplanar Waveguide Circuits, Components, and Systems* (Wiley, 2001)（Eq. 2.37/2.38 有限衬底 sinh 分支）。
- [C3] Mohebbi, H. R. & Majedi, A. H., "Analysis of series-connected discrete Josephson transmission line", Supercond. Sci. Technol. 22, 125028 (2009)（薄膜 L_k 拟合式）。
- [C4] Clem, J. R., "Inductances and attenuation constant for a thin-film superconducting coplanar waveguide resonator",
  J. Appl. Phys. 113, 013910 (2013) / arXiv:1210.5929（Eq. 35 总 L′ 重算相速；Pearl 长度 Λ = 2λ²/t）。
- Wen, C. P., "Coplanar waveguide: a surface strip transmission line…", IEEE Trans. MTT 17, 1087 (1969)（共形映射源流）。

**外部验证器件**
- [S1] Sung, Y. et al., "Realization of High-Fidelity CZ and ZZ-Free iSWAP Gates with a Tunable Coupler",
  Phys. Rev. X 11, 021058 (2021) / arXiv:2011.01261（补充材料：E_J、E_C、电容表、g）。
- Goto, H., "Double-transmon coupler: Fast two-qubit gate with no residual coupling for highly detuned superconducting qubits",
  Phys. Rev. Applied 18, 034038 (2022)（直接 q–q 腿 0.4% 的样本）。

**Palace（awslabs/palace，源码与文档）**
- [P1] `scripts/schema/config-schema.json`：`CrackInternalBoundaryElements`（默认 true）。
- [P2] `palace/utils/configfile.cpp`：`Ground` 与 `PEC` 进同一数据结构；`BoundaryData::attributes` 不收集 `terminal`（cracking 从该集合出发）。
- [P3] `palace/models/laplaceoperator.cpp`：Electrostatic 把 Ground/PEC 与 Terminal 都加入 essential Dirichlet，对当前 terminal 投影 V = 1。
- `docs/src/guide/boundaries.md`：只禁止 wave port 在内部面。
- `examples/cpw/`、`examples/transmon/`：金属为零厚度 PEC 面，材料域只有 vacuum / substrate。
- issue #887：0.16.1 `SaveAdaptMesh + SaveAdaptIterations` 覆盖 bug。

**同行工具**
- KQCircuits (IQM)：Elmer/Palace 导出默认 `metal_height = 0`，默认 p = 3，cell bbox 每侧 +300 µm。
- SQDMetal (2026)：Palace / COMSOL / Q3D 零厚度 PEC 基准，互差 <0.3%；对实验 RMSE 频率 ~6% / g ~24.5%；接地盒 = 芯片高 ×2、XY +20%。
