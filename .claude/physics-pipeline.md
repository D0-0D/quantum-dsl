# v4 物理管线设计: 从版图到哈密顿量

> 本文取代早先的 physics-pitfalls.md(那份是事故清单的复述, 缺整体图像)。
> 读者: V4-2(mesh/palace)、V4-3(数学内核)、V4-6(live 验证)的实现 agent。
> 所有"本机实测"均为 2026-08-24 在 WSL2 + gmsh 4.15.2 + Palace 0.16 + qdsl313
> 上完成, 可用 `.claude/proto/` 下两个脚本复算。

## 术语(先统一语言)

| 术语 | 含义 |
|---|---|
| OCC | OpenCASCADE, gmsh 的 CAD 几何内核(布尔运算/fragment 都是它做的) |
| fragment | OCC 操作: 把一组重叠/相邻的几何体互相切开并缝合成共形拓扑(共享界面), 2D 面作为工具参与时等价于把面"印"(imprint)进所在界面 |
| N0–N14 | `tests/test_spec.py` 里的契约测试组, 每组 = 一条可执行需求(SPEC.md 有表) |
| golden | 契约测试里钉死的参考数值。三种来源: 闭式手算 / v3 同物理输入的实测 / Palace 逐字输出样本。**live golden 是回归锚点, 不是绝对真值**(见 §6) |
| order | Palace `Solver.Order` = FEM 基函数多项式阶数(1=线性单元, 2=二次单元) |
| L0 | Palace `Model.L0` = 网格坐标单位折算米的系数(网格写 µm 则 L0=1e-6) |
| Maxwell 矩阵 | 静电电容矩阵 C: 对角正(自电容), 非对角负(−互容), 对称。Palace 写 `terminal-C.csv`; 另有 SPICE 互容矩阵 `terminal-Cm.csv`(全正, Cm_ii=Σ_j C_ij=对地电容) |
| LOM | lumped-oscillator model: 用 C⁻¹ + 约瑟夫森电感推 qubit 参数 |
| PEC | 理想电导体(perfect electric conductor) |

## 1. 我们在做什么

超导量子芯片 = 硅衬底上的平面金属图形(焊盘/共面波导, 膜厚 ~100–200 nm)+
约瑟夫森结。设计者关心的不是几何而是哈密顿量参数: 每个 qubit 的 E_C、f01、
非谐性 α, qubit 间耦合 g, 读出腔色散位移 χ。v4 的物理管线就是这条推导链:

```
.geo(版图, µm) ──┐
                 ├─→ 计算域构建 ─→ 3D 网格(gmsh) ─→ 静电 FEM(Palace) ─→ Maxwell C 矩阵
meta.yaml ───────┘                                                          │
(材料/域/网格/结声明)          (可选: 分块提取 → 共享节点累加 + Schur 消元) ←┘
                                                                            │
                    E_C, f01, α, g, χ  ←── 逆电容 LOM + L_J(V4-3, 纯数学) ←─┘
```

**为什么静电就够**: 工作频率 5–10 GHz → 波长厘米级, 芯片特征 10²–10³ µm ≪ λ,
准静态近似成立——电磁问题退化为"提取集总电容 + 集总电感"。约瑟夫森结是唯一的
非线性/电感元件, 作为**集总参数**(L_J)直接进电路模型, **不进静电网格**
(把结当导体桥会短路两块焊盘, C 矩阵失去意义)。

**FEM 求解的问题**: 在域 Ω(衬底 ε_r=11.45 + 真空 ε=1)上解 ∇·(ε∇φ)=0;
第 i 个导体面 φ=1 V、其余导体 0 V(Dirichlet, Palace 叫 Terminal), 逐导体解
N 次; 由感应电荷得 C 的第 i 列。域外边界: 接地(φ=0, 模拟接地屏蔽盒)或
开放(∂φ/∂n=0, 近似自由空间)。

## 2. 物理图像: 导体是边界条件, 不是材料

超导金属的伦敦穿透深度 ~90 nm——场不穿透, 整块金属是等势体(PEC)。静电问题里
导体**内部无场、无自由度**, 所以它在 FEM 里的正确身份是**边界条件**(在导体
表面钉电位), 而不是一块要网格化的材料。这一条决定了 §4 的全部架构讨论。

C 矩阵到哈密顿量(V4-3)。公式口径已双重验证: 对契约 golden 逐位复算 +
codex 双跑文献核对(5.6-sol 202 检索 / 5.5 68 检索, 原始报告
[`lom-conventions-survey.md`](lom-conventions-survey.md)):

- 对称化 `(C+Cᵀ)/2` 后求逆——这只是清理求解器的微小反对称残差, **不是物理
  步骤**: 先记录 `‖C−Cᵀ‖/‖C‖`, 残差不小(>1e-6 量级)说明解有问题, 不能靠
  对称化掩盖(§8 防线)。
- `C_Σ,i = 1/[C⁻¹]_ii`(dressed 有效电容), `E_C = e²/(2C_Σ)`——**不是**
  Maxwell 对角元(LOM 论文 Eq. 8/11a 同口径; N8 有反例测试)。
- `E_J = (ħ/2e)²/L_J`; transmon 微扰式 `f01 = (√(8E_C·E_J) − E_C)/h`, `α = −E_C/h`。
- 耦合 `β = |C⁻¹_ij|/√(C⁻¹_ii·C⁻¹_jj)`, `g = ½·β·√(f01_i·f01_j)`。
  **这是文献真实分叉处, 契约钉死了其中一支**: 谐振子零点涨落推导(Blais RMP
  Eq. 133/134、qiskit 旧 LOM 的 Z_qp)给裸等离子频率 `f_p=√(8E_C E_J)/h`;
  Krantz 书写(Eq. 105)与 v3/契约用修正后 `f01 = f_p − E_C/h`。两者之比
  `√Π(1−1/√(8·EJ/EC))`: EJ/EC=20 时 f01 口径**低 7.9%**, =50 时低 5.0%
  (composite LOM 用带符号 C⁻¹QQ 数值对角化绕开选择)。跨文献比对 g 时先对
  口径; 别"顺手改进"。另: `|·|` 只适合输出耦合强度, 若将来做多路径/环路
  哈密顿量必须保留 C⁻¹_ij 符号。
- SQUID: `E_J(φ) = (E_J1+E_J2)·hypot(cos πφ, d·sin πφ)`, `d=(E_J1−E_J2)/(E_J1+E_J2)`
  ——标准(≡ Koch 2007 Eq. 2.17/2.18 吸收相位支路后的幅值; Krantz Eq. 22
  直接用此形); 无奇点(tan 写法在 φ=0.5 除零)。Koch 的 d 符号定义相反,
  幅值不受影响。
- χ(N11): `chi_0/chi_1` 两式是**非 RWA 三能级二阶**结果(含反旋转分母),
  文献依据是 Zhu et al. arXiv:1210.1605 Eq. (11)–(14) 取三能级;
  ⚠ **不要**再引成 Koch (3.9)/(3.10)——Koch 原式是 RWA 版(无 ω+ω_r 项),
  qiskit-metal 源码注释就是这处误引的源头。文档要写明 χ 定义是单边
  cavity pull(本实现 = (chi_1−chi_0)/2), 不是 2χ。
- 浮动双岛(将来实现时): 结支路变换后**完整求逆取 θθ 块**
  `(A−BD⁻¹Bᵀ)⁻¹`——Yanay et al. (npj QI 2020) Eq. 50–57 与 composite LOM
  同口径; "删共模行列再求逆"= A⁻¹, 仅 B=0 时等价。全浮动时 C 有规范零模
  奇异, 求逆前必须选 datum。
- 常数: e/h/Φ0 在 SI-2019 下精确(e=1.602176634e-19 C, h=6.62607015e-34 J·s);
  μ0/ε0 自 2019 起带实验不确定度(~1e-10, 对本工具无实际影响, 但措辞别写
  "全部常数精确")。
- CPW 解析(N10): 椭圆积分共形映射是标准谱系(Wen 1969 / Simons ch.2 /
  Göppl), AGM 只是 K(k) 的数值法; 动力学电感 L_k(Clem 2013, 薄膜 t<2λ 用
  Pearl 长度 Λ=2λ²/t)加进总 `L' = L_g' + L_k'` 后, **Z0/相速/λ_g 必须由
  总 L'C' 重算**, 不能再用 c/√ε_eff——从 v3 搬运时验证这一点。有限衬底厚
  (h 不再 ≫ w+2s)用 sinh 分支修正; 背面接地版图是 tanh 分支, 不可混用。
  v3 `cpw_analytic.py`/`circuit_model.py` 对 golden 命中 1e-16/精确,
  **审后原样搬运**, 审的重点即上述口径点。

## 3. 计算域怎么建

`.geo` 里作者只画金属面(µm, OCC); 衬底与真空由 `build_mesh` 按 meta 合成:

```
z=+120 ┌───────────────────────────────┐ ← airbox.top
       │           vacuum  ε=1         │
z=0    │   ▬▬▬A▬▬▬         ▬▬▬B▬▬▬     │ ← 金属片 = 界面上的 Dirichlet 边界
       ├───────────────────────────────┤
       │        substrate  ε=11.45     │
z=-100 ├───────────────────────────────┤ ← −materials.substrate.thickness_um
       │           vacuum              │
z=-120 └───────────────────────────────┘ ← −airbox.bottom
        ←—— 金属 bbox ± airbox.side ——→
```

- airbox 的 top/bottom 从 **z=0(芯片面)** 起算; bottom(120) > 衬底厚(100)
  → 衬底下方留 20 µm 真空, 域外边界六面全是盒壁。
- 外边界接地 = "芯片装在接地屏蔽盒里"。开放边界(不给盒壁挂 Ground)更接近
  自由空间, 与 qiskit-metal/Elmer 的 FarField 口径一致——但**没有任何金属地时
  问题奇异**(电位无参考), 必须强制接地盒壁。two_pads golden 用接地盒。
- 域大小影响: 旧仓受控实验显示 ground 范围对 C 影响 <0.5%, 远小于网格效应;
  但开放边界 + 导体贴近盒壁会过耦合(qm4q 的 connector +13~17%)——盒壁离导体
  至少一个"缝宽的几十倍"量级。

## 4. 金属的表示——核心架构决策(v4 与 v3 的分道处)

静电里导体没有体自由度(§2), 那金属在**网格**里长什么样? 三个候选:

| 方案 | 做法 | 代价/收益 |
|---|---|---|
| **(a) 零厚度片**(v4 默认) | 焊盘 2D 面直接 fragment(imprint)进衬底/真空界面, Terminal 挂内部边界面 | 无布尔减 → 无 ε-nudge、无 scale ladder、无腔壁归位; 天然精确共面; 更接近真实膜厚; 管线最短 |
| (b) 薄板挖空(v3 "Approach A") | 面 extrude 成 2 µm 板 → 从真空布尔减掉 → 腔壁 = 域外边界, Terminal 挂腔壁 | 引入 OCC 共面布尔的全部失效类(见下); 多一个"金属厚度"物理参数; golden 的出处 |
| (c) 金属网格化为实体 | 金属体 + 高对比材料 | 静电里纯浪费(内部无场), 高对比伤条件数——排除 |

**外部证据一边倒支持 (a)**(codex 文献取证, 出处见
[`palace-lit-survey.md`](palace-lit-survey.md)): Palace 官方 CPW 例的金属
就是 "infinitely thin, perfectly conducting boundary surface"(网格脚本默认
metal_height=0); transmon 例 PEC 面、材料域只有 vacuum/substrate;
KQCircuits(IQM)默认 metal_height=0; SQDMetal 2026 Palace/COMSOL/Q3D
基准用 zero-thickness PEC(三求解器互差 <0.3%); Ansys Q3D 惯例是
thin conductor(200 nm)。膜厚定量(CPW 一阶修正 Δ=(1.25t/π)(1+ln(4πW/t))):
真实 100–200 nm 膜 ≈1.0–1.8% 几何因子, **1 µm 人工板厚 ≈7.6%** ——
用 1–2 µm 板"代表"薄膜不是无害近似。

**v3 为什么选 (b)**: 当年断言"Palace 拒绝内部面上的 Terminal"。
**本机复检推翻了这个断言**: Palace 0.16 对方案 (a) 直接可解(实测见 §6)。
v3 当年看到的 abort 几乎可以肯定是**误诊**——我们在 (a) 路径上复现了同签名的
崩溃 `"A non-periodic face cannot have multiple boundary elements"`, 根因是
`.geo` 作者写的 Physical 组在 imprint 路径下**存活**到最终网格, 与实现自己加的
组重叠 → 同一几何面写出两条边界元。捕获作者组后 `removePhysicalGroups()` 即愈。
(carve 路径下焊盘面被 extrude/cut **消耗**, 作者组变空, 所以 v3 从未踩到——
这也解释了两条路径的"玄学"差异。)

**ε-nudge 的来龙去脉**(为什么 v4 可以让它不存在): 方案 (b) 里带 ground 的
设计要做"2 µm 金属板 与 衬底顶面 精确共面"的布尔减——OCC 对精确共面布尔要么
失败要么静默损坏拓扑, v3 的对策是把衬底顶面**下移 ε 塞一层真空缝**躲开共面。
这层缝是纯粹的工具妥协, 却是一等一的物理误差源: ε=1 µm 时 C 偏低 29%、耦合
偏低 40%(旧仓受控实验), 且 ε 不单调(0.5 µm 反而产损坏拓扑), v3 最终缓解到
ε=0.01 µm。方案 (a) **根本没有布尔减**——金属片印在界面上, 共面是构造性精确,
整个 ε-nudge 问题类连同 fragment scale ladder(dilate 往返 shape-heal 的
经验性阶梯)一起消失。这是 v4 采用 (a) 的决定性理由。

**内部边界在 Palace 里的机制**(源码取证, 出处 survey §1): Palace 有官方的
`CrackInternalBoundaryElements`(默认开)——对内部 **PEC/Ground** 面复制节点、
解耦两侧(正是零厚度 PEC 该有的行为), 所以将来带 ground plane 的设计走的是
官方支持路径; **Terminal** 不在 crack 属性集合里, 作为 essential Dirichlet
直接生效(静电里等势面两侧共节点无影响——本机实测可解且与挖空细网格一致
~0.1%)。文档只明确禁止 wave port 在内部面, 未禁 Terminal/Ground。

方案 (b) 保留为对照工具(`proto/two_pads_pipeline.py`): 需要复算 v3 golden
或研究膜厚效应时用, 不进 v4 产品代码。

## 5. 单位与 Palace config

- **仓库内部长度一律 µm**(SPEC 契约), 网格文件坐标也写 µm, Palace 端用
  `Model.L0 = 1e-6` 声明"网格单位 = 1e-6 米"。这不是风格偏好: 另一条路
  (先把模型 dilate 到米、L0=1)v3 用过, `occ.dilate` 是 GTransform 全量
  几何重建(有损的意外 shape-heal), 对部分几何是静默损伤——µm+L0 方案
  实测精度相同(§6 变体 A vs B)且根除该失效类。**唯一换算点在 config 的
  L0**, 别处不乘不除(不双重缩放, N4 GDS 也是 µm verbatim)。
- `Solver.Order = 2` 是**承重件**不是可调优化: 同网格 order 1 实测偏 +7.3%
  (3.6× 契约容差); 电容收敛对 p 加密远比 h 加密敏感(边缘场奇异, 见 §6)。
- config 骨架(全部字段原型脚本里有活样例):
  `Problem.Type=Electrostatic`; `Model{L0, Mesh}`;
  `Domains.Materials=[{Attributes:[衬底组], Permittivity:11.45},
  {Attributes:[真空组], Permittivity:1.0}]`(attribute = gmsh physical 组号);
  `Boundaries.Ground{Attributes:[外边界组]}`,
  `Boundaries.Terminal=[{Index:i, Attributes:[导体组]}...]`(Index = C 矩阵
  行列号, 1 起, 绑定顺序是矩阵标签的唯一真相源);
  `Solver{Order:2, Linear:{BoomerAMG+CG, Tol 1e-8}}`。
- 场输出(Paraview/GridFunction/Save)默认**关**: 电容工作流只消费
  `terminal-C.csv`, 场输出是大网格上最慢最占盘的一段。
- 运行环境: `PALACE_BIN` 定位二进制, **必须 `HWLOC_COMPONENTS=-gl`**
  (hwloc 的 gl 插件 TCP 探测 X display 会把 MPI_Init 挂死在 WSL2 上);
  cwd = config 目录, `Model.Mesh` 写相对文件名。two_pads 规模 `-np 1` 足够。

## 6. 网格与收敛(实测数据)

导体边缘电场奇异(∝ r^(−1/2)), 电容误差集中在边缘 → 用 Distance+Threshold
尺寸场对**所有导体边缘曲线**细化(two_pads 配方: 4→40 µm 渐变于距边缘
10→130 µm, Sigmoid; 电容缝隙两侧的导体面都要进细化源——v3 漏掉 carve 腔壁
曾使一切带 ground 的设计网格必炸)。网格生成默认 Delaunay, **每条出口都要过
空网格守卫**(gmsh 对失败可能不抛异常而静默返回空网格),失败回退
HXT(Algorithm3D=10; 不能当全局默认, 部分几何反而失败)。

two_pads 全部实测。⚠ 下表"偏差"列以 **v3 旧 golden**
`[[24.7288,−1.976],[−1.976,24.7293]]` 为参照(测量先于 §7 的重钉;
现行 golden = C 行的值本身):

| # | 表示 | 网格 max/min µm | order | C_AA (fF) | C_AB (fF) | 对旧 golden 最大偏差 |
|---|---|---|---|---|---|---|
| A | (b) 2µm 板挖空, dilate+L0=1 | 40/4 | 2 | 24.722 | −1.976 | 0.038% ✓ |
| B | (b) 同上, **µm+L0=1e-6** | 40/4 | 2 | 24.733 | −1.975 | 0.072% ✓ |
| A′ | (b), 网格加密(33k→244k 节点) | 20/2 | 2 | 24.557 | −1.953 | 1.18% ✓ |
| A″ | (b), 降阶 | 40/4 | 1 | 25.769 | −2.119 | **7.25% ✗** |
| C | **(a) 零厚度片 = 现行 golden** | 40/4 | 2 | 24.532 | −1.947 | 1.46% |
| C′ | (a), 网格加密 | 20/2 | 2 | 24.342 | −1.919 | 2.87% |

解读:
- **golden 自带 ~+1% 网格偏置**(A→A′ 移 −0.7~−1.2%; C→C′ 同幅): 它是
  v3 配方(2 µm 板 + 40/4 + 接地盒)的实测锚点, 物理收敛值在其下方 ≈1%。
- **2 µm 板厚效应是真实物理, 不是离散误差**: 同网格下 (b)−(a) 差
  ≈0.8%(对角)/ ≈1.6%(非对角), 粗细两档一致。真实器件膜厚 100–200 nm,
  (a) 才是更忠实的模型。
- C′ 离旧 golden 2.87% 不是 (a) 的缺陷, 而是旧 golden 绑定了 v3 的 2 µm 板
  + 粗网格两个工件偏置——这正是 §7 重钉 golden 的动机。
- 报告任何 C 值都应给出两档网格的相对变化——单网格数字在复杂几何上带
  6–21% 不确定度(旧仓 sung/Elmer 实测)。
- **order 2 多 rank 在干净环境无恙**(2026-08-24, 64C/128G 裸机实测): C′ 同款
  20/2 网格(~1.7M 未知量, 即 v3 issue #22 的问题规模)在 spack 全新构建的
  Palace 0.16 + openmpi 5.0.10 上, np=4 与 np=32 均 rc=0, C 矩阵一致到
  1e-12 且与 WSL 实测 C′ 逐位吻合——issue #22 的静默掉 rank 是 v3 运行
  环境/构建问题, 不是 Palace bug; **不必**为多 rank 保留"分块降规模"的
  防御。另: 裸机不加 `HWLOC_COMPONENTS=-gl` MPI_Init 正常, 该 hang 确系
  WSL 特有。

## 7. N7 golden 重钉(已执行, 2026-08-24 经用户批准)

旧 golden `[[24.7288, −1.976], [−1.976, 24.7293]]` 是 v3 配方(2 µm 板 +
40/4 网格)的产物: 实测(§6)零厚度片收敛值离它 2.9%, 差值 = 板厚工件
(~0.8%/1.6%, CPW 修正公式估 1 µm 板 ≈7.6%——survey §3)+ 网格偏置(~1%)。
"物理上更收敛反而离 golden 更远"的倒挂不可接受, 且 golden 的意义在
"可复现的实测锚点"而非历史配方——**已重钉为 v4 产品路径(零厚度片,
40/4, order 2, 接地盒)的实测值**:

- `LIVE_MAXWELL_GOLDEN = [[24.5324, −1.9472], [−1.9472, 24.5353]]` fF
  (全精度 24.53243335381 / −1.947218428813 / 24.53533214664)
- N7 f01 golden 由新 C + 10 nH 闭式重算: `[9.3989, 9.3984]` GHz(容差 3% 不变)
- N8 的 `N8_MAXWELL` 是纯数学输入, 与 Palace 无关, 不动。

实现按 fixture 配方(mesh 40/4, order 2)应落在 golden ~0.1% 内; 2% 容差
吸收网格器版本波动。

## 8. 失效防线(与表示无关的通用断言, 每条都便宜)

这些不是 v3 机器的复刻, 是任何实现都该带的安全网——每条背后都有一次
"无报错出错解"的实案:

1. fragment 之后断言拓扑不变量: 衬底恰 1 体; 无负 mass 实体; Σ体积 ≤ 模型
   bbox 体积×1.001。(实案: OCC 静默复制衬底体/产负面积面/整张界面误标 ground。)
2. 3D 网格每条出口过非空断言。(实案: gmsh 静默空网格 → Palace 无信息 abort。)
3. 捕获 `.geo` 作者 Physical 组后立即 `removePhysicalGroups()`, 实现自己的组
   是唯一输出。(实案: 本次 §4 的双边界元 abort。)
4. 面归属(imprint 后找回焊盘面)用 fragment 的 out_map 直接映射——(a) 方案
   天然免去 bbox 猜测; 若将来仍需几何归位, 质心判据必须加范围包含校验。
5. config 写出前校验所有 `Attributes` 引用的组号存在于网格。
6. 输入卫生: CSV 与 L_J/E_J 拒 NaN/Inf(`not (isfinite(v) and v>0)`——1e400
   溢出成 inf 能绕过 `<=0`); C 求逆前**先查反对称残差** `‖C−Cᵀ‖/‖C‖`
   (超阈值即解本身有病, raise 而非对称化掩盖)再 `(C+Cᵀ)/2`; 奇异判据用
   尺度相对量。
7. 语义完整性: 未被任何 junction/subsystem 认领的 Terminal **禁止静默接地**
   (实案: 静默接地把中介耦合 25 MHz 删成 0)——要么 Schur 消掉要么 raise。
   N8 的 `islands` 长度 >1 时(浮动双岛)在实现差分约化前先 raise, 不静默取
   第一个(实案: 双岛当单岛 C_Σ 错 1.70× 且测试全绿)。

## 9. 参考锚点(扩展验证用, 均在旧仓 ~/quantum_dsl)

- **LOM 代数 parity**(零 FEM): qiskit-metal LOM 2.0 双 transmon golden,
  v3 Schur C_k 偏差 7.7e-16——搬 assemble/约化时的自检器。
  spec: 旧仓 `.claude/lom-parity-spec.md`。
- **qm4q**(qiskit-metal 同几何 Elmer 对照): 单 transmon pocket + ground;
  Elmer 参考 pad 电容 ~110 fF 级, v3 最好达 −5.5%(共面+开放边界+order 2)。
  文件: `examples/dsl/geo/qm4q_transmon_cell.*`, `examples/qiskit_metal_ref/`。
- **sung**(论文对照, PRX 11 021058): 3 浮动双岛 transmon; C_Σ 对 Elmer
  +1~3%; 直接 q-q 互容 C_12 未复现(0.003 vs 0.125 fF, 差分远场相消);
  引用其数字前必读旧仓 session 2607280204(有两个大误差反向抵消的坑)。
- Elmer 侧口径: 输出是 SPICE 互容且需 ×ε0; 禁用 qiskit-metal 的 pandas
  后处理(pandas≥2 下静默错), 从原始 `cap_matrix.txt` 自建。

## 10. 外部文献取证摘要(codex, 158 次检索; 全文带出处 → [`palace-lit-survey.md`](palace-lit-survey.md))

- **金属表示**: Palace CPW/transmon 官方例、KQCircuits 默认、SQDMetal 基准、
  Q3D thin-conductor 惯例全部 = 零厚度 PEC 面(§4 已引用)——(a) 是业界默认,
  (c) 仅在要建有限电导/动力学电感等特殊物理时才考虑。
- **内部边界机制**: `CrackInternalBoundaryElements`(默认 true)crack 内部
  PEC/Ground 面; Terminal 不在 crack 集合, 走 essential Dirichlet(§4)。
- **官方语义确认**: `Model.L0` = 网格单位相对 1 米的比例; `Solver.Order` =
  FEM 阶数(默认 1); Electrostatic 逐 terminal 解 Laplace 由场能得 C;
  输出 `terminal-C.csv`(Maxwell)/`terminal-Cm.csv`(mutual, 非对角=−C_ij)/
  **`terminal-Cinv.csv`(官方免费输出, 可对照自家求逆做零成本交叉校验)**。
- **精度参照系**: Palace spheres 例对解析解 0.57–3.5%; SQDMetal:
  Palace/COMSOL/Q3D 电容互差 <0.3%, 但对**实验**频率 RMSE ~6%/3.5%、
  g RMSE ~24.5%(材料/制程/省略物理)——仿真间一致性 ≠ 对器件预测精度。
- **收敛常识**: 光滑区 p 加密指数收敛, 奇异点附近 h 加密更有效——边缘细化
  不可被升阶替代; KQCircuits 默认 p=3, Q3D 默认目标 0.5%。

## 11. 分块拼装(N9/N14)的适用边界(codex 取证 86 次检索 → [`assemble-lit-survey.md`](assemble-lit-survey.md))

v4 的"逐块提取 → 同名节点累加 → Schur 消元"与 qiskit-metal composite LOM
(LOM 2.0)**机制同构**(源码行号级证据: 节点 rename → 邻接表 += 累加 →
Schur 补 C−C·S(SᵀCS)⁻¹SᵀC; v3 曾对其 golden 命中 7.7e-16)。这是**明确披露
的 quasi-lumped 近似**, 合理; 但要认清边界:

- **数学性质**: 两导体的直接 Maxwell 互容, 只在它们于同一次求解中共现时存在;
  共享节点只能提供网络中介路径; **共享 ground 不算耦合路径**(datum 不传播)。
- **丢掉的量不总是小**: 公开设计里直接 q–q 腿相对 q–coupler 腿从 <1%
  (Goto 2022 DTC: 0.4%)到 ~10–15%(常规单 coupler: g_12=25 vs g_1c=250 MHz)
  都有; 相消型 coupler 的零耦合点 g = g_12 − g_eff **直接依赖**直接腿——
  切错块会移动甚至消灭零点。"跨块直接互容天然可忽略"不成立。
- **业界对照**: KQCircuits/SQDMetal 不做分块拼装, 整域(或用户选定单域)求解;
  经典 EDA 窗口化提取(Hipex vicinity、BEM windowing 上下界、pattern+stitch)
  都带显式作用距离/重叠/误差界——裸切块纪律的防护水平低于它们。
- **LOM 论文自己的切块经验**: qubit cell 要装下 qubit pads + 相邻 CPW 段 +
  coupler pads; cell padding ~100 µm 后对 χ 的影响 <0.5%(仅对其版图成立,
  无普适值)。
- **v4 决议**: 契约措辞已收紧(SPEC "绑定键"段); 整片求解仍是默认(blocks
  可选)。廉价防线留给 V4-5 实现时: extract 时对"几何邻近(如间距 <
  airbox.side)但结构性零耦合"的导体对告警。core+halo、邻块 pair-solve、
  期望耦合图覆盖检查按需再上(YAGNI, 出处与做法见 survey §3)。

## 12. Palace 运行面: 版本/并行/AMR/域尺寸(codex 双跑取证 → [`palace-ops-survey.md`](palace-ops-survey.md))

gpt-5.6-sol(152 检索)+ gpt-5.5(72 检索)独立跑, 结论一致; 与 §6 裸机实测互洽。

- **多 rank order-2**: 上游无对应 bug 报告、无版本自称修复——与裸机实测
  "本来就不是 Palace bug"互洽。v3 的绕法(单 rank/分块降规模)在干净环境
  不必保留; WSL 上仍建议 `-np 1` 起步 + 盯内存。
- **每个 terminal 解完都跑误差估计器**(RT 通量恢复), 即使
  `Refinement.MaxIts=0` 也**不跳过**——大网格内存预算要把 estimator 阶段
  算进去(官方内存表单列此项; AMR refine 峰值可达稳定 solve 的 3–4×)。
- **多 terminal = 顺序单 RHS**: 矩阵/预条件器构建一次复用, N 导体 = N 次
  CG 解——terminal 数是线性成本, 不是矩阵重装成本。
- **AMR**(0.12 起支持 Electrostatic, `Model.Refinement`, 默认 MaxIts=0 关):
  是 gmsh 边缘 seed 网格**之上**的二次自适应, 不能取代 Distance/Threshold
  尺寸场(SQDMetal 明说且实践如此)。接入时: 1–2 轮、设 MaxSize、纯四面体可
  `Nonconformal=false`; 避开 `SaveAdaptMesh+SaveAdaptIterations` 组合
  (0.16.1 引入的覆盖 bug #887)。正面样本: SQDMetal AMR O2 到 71M DoF,
  对 COMSOL/Q3D <0.3%。**v4 契约不需要 AMR**(fixture 规模小), V4-6 大网格
  时再试点。
- **版本**: 最新 0.17.0(2026-06); spack 只到 0.16.0(本机/裸机同版)。
  0.16.1/0.17 带来的是诊断(分阶段内存表、resolved config)与 cracking/AMR
  修复, **无静电相关行为变化**——v4 留在 0.16 没有已知代价, 升级不紧迫;
  若升, 从源码 tag 构建并用 N7 golden 回归。
- **静电外边界只有两种**: `Ground`(Dirichlet 0)与 `ZeroCharge`(Neumann);
  **不写就是自然边界 ≡ ZeroCharge**——"开放边界"= 直接不给盒壁挂 Ground,
  无需任何特殊配置。无 Absorbing/PML。全接地导体版图 + 开放边界会奇异,
  此时必须接地盒壁(§3 已述)。
- **域尺寸无公认定律**, 公开起点: SQDMetal 接地盒 = 芯片高×2、XY +20%
  (模拟真实 sample holder); KQCircuits 默认 cell bbox 每侧 +300 µm。
  给真实器件报数时应做域尺寸扫(1×/1.5×/2×, 关注 C 变化 <0.2–0.5% 验收);
  two_pads fixture 的 side=80 µm 是刻意小型化的回归件, 不是物理推荐值。
- **对称面减半**: 偶对称用 ZeroCharge、奇对称用 Ground 在原理上可行, 但
  完整 C 矩阵的逐 terminal 单位激励通常破坏对称性——不做。
