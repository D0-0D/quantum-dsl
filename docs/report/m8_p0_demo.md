# M8 P0 演示手册 — 分块提取 + New LOM 拼装（自用, 自成体系）

> 面向**你自己**的演示脚本 + 背景知识。对应 `.claude/lom-parity-spec.md` 的 P0-A…F
> （里程碑 M8a–M8d）, 落地记录 `.claude/session/2607290329.md`, review 记录
> `.claude/session/2607292213.md`。
> 全套测试基线: **619 passed, 3 skipped, 0 failed**（conda `metal-env`, 156.8 s, 本文写作时实测）。

---

## 0. 一句话 + 一张图

**M8 P0 之前**: 整片芯片一次静电解 → 一个大 Maxwell 电容矩阵 → transmon 参数。
**M8 P0 之后**: 可以把芯片**按 component 边界切成若干块**, 每块独立解（或直接读别人的矩阵文件）,
再把多份电容矩阵按**共享节点名**拼成一个系统, 消掉非动力学节点, 最后算 transmon + 谐振器 + χ。

```
              ┌────────────────────────── 完整芯片 .geo（单一真值源, 声明式, 一次确定）
              │
   ┌──────────┴───────────┐
   │                      │
 GDS fork              Mesh fork ── 有 extract: 时分岔 ↓
 (完整图, 一行没改)          │
   ↓                       ├─ block_qb1.geo ─→ mesh ─→ Palace ─→ C₁ ┐
 chip.gds                  ├─ block_cplr.geo ─→ mesh ─→ Palace ─→ C₂ ├─ 一份 C 矩阵 = 一个 Cell
                           └─ block_qb2.geo ─→ mesh ─→ Palace ─→ C₃ ┘
                              （或 from: file / inline 直接注入矩阵, 完全不碰几何）
                                              ↓
                              assemble(): 共享节点名累加 → Schur 消元      ← 纯数据层, 无几何
                                              ↓
                              circuit_model(): transmon + TL 谐振器 + χ + C_j
                                              ↓
                                    chip.results.yaml（系统级, tier 2）
```

三条**硬约束**（贯穿全部实现, 演示时要点出来）:

|              | 内容                                                            | 为什么                                                                                                    |
| ------------ | --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| **G1** | 块几何**落盘**为 `block_<name>.geo`, 不是内存里的过滤器 | 可用 gmsh GUI 打开肉眼验、可 diff、可归档、进 manifest 带 sha256。`load_geo` 及其下游**一行没改** |
| **G2** | 命令行/环境变量**不得改动几何参数**                       | 几何真值源永远是`.geo` + `meta.yaml`。`--no-solve` 只关求解, 不碰几何                               |
| **G3** | 一次 build = 一份确定几何                                       | 扫参是 N 次独立 build, 不是一次 build 内变形几何                                                          |

---

## 1. 背景知识（演示时会被问到的东西）

### 1.1 为什么是「电容矩阵」

超导 qubit 工作在 ~5 GHz, 对应自由空间波长 ~6 cm、硅中 ~1.8 cm; 而一个 transmon 的尺寸是
~100 µm。**尺寸 ≪ 波长 ⇒ 集总元件近似成立**, 电磁问题退化成「一堆导体之间的电容」这个纯静电问题。
于是流程是:

```
几何 → 静电 FEM → Maxwell 电容矩阵 C → 电路量子化 → qubit Hamiltonian (E_C, E_J, f01, α, g, χ)
```

电感来自约瑟夫森结（人给的 `L_J`/`E_J`）与传输线（解析算）, **不需要 FEM 解磁场**。这就是为什么
Palace 只跑 `Electrostatic`。

### 1.2 两种电容矩阵, 符号别搞反

|                              | 定义                                                    | 长相                                                                                          |
| ---------------------------- | ------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| **Maxwell 矩阵 C**     | `Q_i = Σ_j C_ij V_j`                                 | 对角**+**, 非对角 **−**; 对角 = 该导体对**所有**其它导体（含地）的电容之和 |
| **互容 / 集总矩阵 Cm** | `Cm[i][i]` = 对地电容, `Cm[i][j]` = i↔j 的物理电容 | **全正**                                                                                |

换算: `C[i][i] = Σ_j Cm[i][j]`（含 j=i）, `C[i][j] = −Cm[i][j]`。
本仓库**内部一律 Maxwell + fF**; Palace 写 `terminal-C.csv`（Maxwell, 单位 F）与 `terminal-Cm.csv`（互容）。
`palace_adapter._as_maxwell()` 读文件时**按符号显式判定**是哪一种, 混杂正负就报错拒绝猜。

### 1.3 inverse-cap LOM（为什么不能直接用对角）

朴素做法「`C_Σ = C[k][k]`」在 N≥3 时**重复计数**耦合电容。正确做法是取**逆矩阵**的对角:

```
C_Σ,k = 1 / [C⁻¹]_kk        E_C = e² / (2 C_Σ)        f01 = √(8 E_C E_J) − E_C      α = −E_C
g_ab/2π = ½ · |[C⁻¹]_ab| / √([C⁻¹]_aa [C⁻¹]_bb) · √(f_a f_b)
```

这是本仓库比老 LOM 领先的地方之一（老 LOM 的 naive Maxwell 对角在 N≥3 上会重复计耦合电容）。

### 1.4 浮动 / 差分 transmon: 结基变换 `C' = BᵀC_S B`

一个 transmon 的结跨**两片**焊盘（都不接地）时, 只有**差模** θ = φ_a − φ_b 是动力学自由度,
共模 σ 的电荷恒为 0。做法: 造一个变换矩阵 `B`, 把节点电位写成 `φ = B ξ`,
`ξ = (θ₀…θ_{n−1}, σ…, r…)`:

- 接地单岛: `B[a][k] = 1`（退化成选择行）
- 浮动双岛: `B[a][k] = +0.5`, `B[b][k] = −0.5`, 另加一个共模列（该两行全 1）
- 谐振器爪子: 一个**独立选择列**（它就是一个真实节点, 没有换基）

然后 `C' = BᵀC_S B`, **求完整逆**, 取 θθ 块。**取逆的 θθ 块本身就是对 σ 的 Schur 补** ——
这条等价性是 M8 能「Schur 放在 node 基而 M6 一行不改」的数学依据。
⚠ 单岛写法用在实际是浮动的器件上, 在 `sung` 上是 **1.70×** 的 C_Σ 误差。

### 1.5 老 LOM vs New LOM（M8 对标的是后者）

|          | 老 LOM（tutorial 4.01）                         | **New LOM / LOM 2.0（4.04/4.05）← M8 抄的是这个**                 |
| -------- | ----------------------------------------------- | ------------------------------------------------------------------------ |
| 结构     | 单 cell, 解析归约公式                           | 多`Cell` 拼装 + `Subsystem` + Schur                                  |
| 输入     | 一份 C 矩阵                                     | **多份**独立 C 矩阵（各自一个文件）                                |
| 连通机制 | 无                                              | **共享节点名**（`node_rename`）—— 就这一条, 没有别的连接件概念 |
| 谐振器   | `freq_readout` 反推 Cr/Lr（**裸**频率） | `Subsystem(TL_RESONATOR, {f_res, Z0, vp})`（**dressed** 频率）   |
| χ       | Koch eq.(3.10) 解析                             | scqubits`HilbertSpace` 数值对角化                                      |
| 理论     | —                                              | arXiv:2103.10344（代码 5 处直接引方程号）                                |

**4.05 的头两行就是全部证据**: 两个 qubit **分别仿真**、**两份独立矩阵文件**, 靠把各自的耦合爪子
`node_rename` 成同一个名字 `"coupling"` 而连通。所以「一次仿真解整片」在 qiskit-metal 里**不是**
推荐工作流 —— 这就是 M8 要补的功能面。

### 1.6 拼装的三件事

**(1) 电容图并联累加。** 每份 Maxwell 矩阵在**全局节点索引**上 `mat[r][c] += w`。
共享同名节点处电容**自动叠加**。**不是块对角拼接**。
`ground_node` 不进节点集（电势固定, 它对地的电容已经在每份矩阵的对角里）。

**(2) Schur 消元非动力学节点**（arXiv:2103.10344 eq 7b）。一个节点若**只接电容、不接任何
电感/结支路**, 它就不是自由度, 其电荷恒为 0:

```
Q_r = 0 = C_rk V_k + C_rr V_r   →   V_r = −C_rr⁻¹ C_rk V_k
Q_k = (C_kk − C_kr C_rr⁻¹ C_rk) V_k        ← 这就是 Schur 补, 必须「积掉」而不是接地
```

**接地 ≠ 消元**, 差别是定量的（实测数字见 §3 幕 3）: 接地把该节点中介的耦合**整条删掉**。
`nodes_force_keep` 用来强留想保的节点（谐振器接入点）。
判非动力学的判据本仓用**结构判定**（不出现在任何 `between` 里且不在 force_keep 里）,
不求 `L_inv` 零空间 —— 因为我们的 schema 里「哪些节点有结支路」是**显式声明**的。

**(3) 子系统。** 拼装后的矩阵上挂量子自由度: `transmon`（引用一个**结**名）/
`tl_resonator`（引用一个**节点**名）。

### 1.7 TL 谐振器为什么不进 FEM

分布式传输线在静电 FEM 里没有意义（它的模式是电磁的）。做法: 只有它的**耦合爪子**是真实导体、
在电容矩阵里占一行; 传输线本身用已知的 `(f_res, Z0, mode)` 折成等效集总 LC:

```
ω_r = 2π f_res        C_r = π / (2 ω_r Z0)        L_r = 1 / (ω_r² C_r)
λ/4 谐振器: C_r /= 2,  L_r *= 2        （方向别记反, 源码 lumped_capacitive.py:246-250 原文如此）
```

`C_r` 加到该节点的**对角**上 = 被爪子的实测电容**加载**, 于是
`f_loaded = 1/(2π√(L_r C_r,eff)) < f_bare`。

⚠ **语义陷阱**: New LOM 的 `f_res` 是 **dressed** 频率, 老 LOM 的 `freq_readout` 是**裸**频率。
本仓库选**裸**频率, 结果里 `f_bare_GHz` 与 `f_loaded_GHz` **都输出**。

### 1.8 结电容 `C_j` 与色散位移 χ

`C_j` = 结两片电极自身的平板电容, **并在结支路上**（工业实践默认 ~2 fF）。落地位置很关键:

```
cprime[k][k] += C_j        ← 结基对角, **求逆之前**
```

**不能**求逆后标量加（`C_Σ = 1/[C⁻¹]_θθ + C_j`, 老 LOM 的写法）—— 那只对**孤立**结成立;
耦合系统里 `C_j` 必须进矩阵才能参与耦合的重整化。实测: `sung` 三结各 2 fF 时
**g(QB1–CPLR) 10.530 → 9.492 MHz（−9.85%）**, 而老标量式对 g **完全无影响**。
本仓默认 `C_j = 0.0` → 既有数值逐位不动。

χ（色散位移）走 Koch 2007 eq.(3.9)/(3.10) 解析式, 结果标 `chi_method: perturbative`,
要求 `|f01 − f_res| ≫ g`。**不引 scqubits/qutip/numpy**（保 `circuit_model.py` 纯 stdlib）。

### 1.9 CPW 解析计算器为什么是必需品

New LOM 的 `TL_RESONATOR` 在 `vp="use_design"` 时内部就调 `guided_wavelength()`。
它同时回答「`f_res` 从哪来」/「谐振器该画多长」。共形映射闭式 + 第一类完全椭圆积分 K,
**必须含动力学电感 `Lk`**（窄线超导 CPW 里它能超过几何电感）。
本仓的 `complete_elliptic_k` 用 **AGM** 实现, 替掉 `scipy.special.ellipk`。

---

## 2. 代码架构（自成体系）

### 2.1 绑定键 —— 整个仓库的枢轴

作者在 `.geo` 里手写的一个**结构化 physical 名**:

```
"<role>::<layer>::<component>::<primitive>"
 role ∈ {metal, ground, jj, substrate}（面） / {port, symmetry}（1D marker）
```

例: `metal::1::QB1::pad_top`。它一路绑定几何 → GDS 层 → Palace terminal → Layer-1 元数据。
loader 把它映射到 `PHYSICAL_GROUP_NAMING`（sanitize 后如 `QB1_pad_top_sfs`）,
`assign_physical_groups` 在 `fragment` **之后**重新登记每个组, 所以输出名与 legacy 路径逐字节一致。

**M8 里同一个节点有三种合法写法**（`nodes:` / `between:` / `subsystems[].node`）:
结构化 geo 名 `metal::1::QB1::pad_top` · sanitize 后的 group 名 `QB1_pad_top_sfs` ·
`nodes:` rename 之后的共享名 `coupling`。解析在 `geo_build._cell_from_block` 做,
parser 层刻意只当字符串保留（存在性校验必须对着真实 `TerminalBinding` 才做得了）。

### 2.2 文件地图（行数为本文写作时实测）

```
src/quantum_dsl/dsl/
├── schema.py                 234   关键字/角色/枚举常量（EXTRACT_* / ASSEMBLE_KEYS / SUBSYSTEM_* / CPW_KEYS / RESONATOR_MODES）
├── parsers/simulation.py    1583   sidecar 解析 + 全部校验（_parse_extract / _parse_assemble / _parse_subsystems）
├── ir.py / builder.py / _units.py    v3 前端（内部单位 = µm, SI_PER_INTERNAL = 1e-6）
│
├── geo_emit.py               790   ★ .geo **生成器**, 全在 load_geo 上游
│                                    ├─ emit_geo         : IR → 扁平 .geo（纯 shapely）
│                                    ├─ elaborate_cells  : cells: → <stem>.elaborated.geo
│                                    └─ emit_block_geo   : 【M8/P0-A】完整 .geo → block_<name>.geo（惰性 import gmsh）
├── _gmsh_geo_source.py       614   load_geo / carve_conductors / surface_outline_um / compute_chip_bbox_from_geo
├── gmsh_adapter.py           695   build_mesh_from_geo（µm→m dilate, fragment, assign_physical_groups, mesh）
├── gds_adapter.py            405   gdstk → chip.gds（保持 µm）
│
├── assemble.py               366   ★【M8/P0-B】纯 stdlib: 累加 + Schur 消元 + 审计
├── circuit_model.py          828   ★ 纯 stdlib: C 矩阵 → transmon/谐振器/χ/C_j（B 矩阵、求逆、Koch 式）
├── cpw_analytic.py           411   ★【M8/P0-F】纯 math: lumped_cpw / guided_wavelength / complete_elliptic_k
├── palace_adapter.py        1178   Palace config/运行/CSV 解析 +【M8/P0-C】capacitance_from_file/_inline + results sidecar
└── geo_build.py              931   ★ 编排层（唯一受支持入口）+ CLI
```

### 2.3 纯度约定（谁能 import 什么）—— 演示时值得强调

| 模块                                    | 允许依赖                                                       | 理由                                              |
| --------------------------------------- | -------------------------------------------------------------- | ------------------------------------------------- |
| `circuit_model.py` · `assemble.py` | **只有 stdlib**（`math` + 本包）                       | 任何 env 都能算电路模型; 也是不引 scqubits 的原因 |
| `cpw_analytic.py`                     | **只有 `math`**                                        | 所以自己实现了 AGM 版椭圆积分                     |
| `geo_emit.py`                         | 模块级只 shapely;`emit_block_geo` **惰性** import gmsh | `import quantum_dsl.dsl.geo_emit` 不拉 gmsh     |
| `gmsh_adapter` / `_gmsh_*`          | gmsh                                                           | —                                                |
| `gds_adapter`                         | gdstk                                                          | —                                                |
| `import quantum_dsl`                  | **不得**拉 gmsh/gdstk                                    | 全部走`__getattr__` 惰性表                      |

⚠ **`assemble` 刻意不从 `quantum_dsl.dsl` 顶层导出**: 子模块 `quantum_dsl.dsl.assemble` 与函数
`assemble` 同名, 子模块一旦被 import, 属性查找会命中模块而非函数（PEP 562 的 `__getattr__`
只在正常查找失败时触发）。正确写法:

```python
from quantum_dsl.dsl.assemble import assemble, ExtractedCell, CellJunction
```

### 2.4 数据流与数据类

```
meta.yaml ──parse_geo_meta_sidecar──► {geo, cells, simulation, circuit_model, extract, assemble, subsystems}
                                                                    │
   ┌────────────────────────────────────────────────────────────────┘
   │ 每个 extract.blocks[]:
   │   from: solve  → emit_block_geo → build_mesh_from_geo → build_palace_config
   │                  → run_palace → parse_capacitance_matrix ─┐
   │   from: file   → capacitance_from_file  ──────────────────┤
   │   from: inline → capacitance_from_inline ─────────────────┤
   │                                                          ▼
   │                                            CapacitanceResult(maxwell, terminals,
   │                                                             source, sha256)
   │                                                          │  _cell_from_block(): 节点名解析 + rename
   │                                                          ▼
   │                                            ExtractedCell(name, terminals, maxwell,
   │                                                          junctions=(CellJunction…), source, sha256)
   │                                                          │  assemble(ground_node, nodes_force_keep)
   │                                                          ▼
   │                                            AssembledSystem(nodes, maxwell, junctions,
   │                                                            eliminated, audit)
   │                                                          │  .as_capacitance_result()
   │                                                          ▼
   └──────────► solve_circuit_model(cap, qubits=[JunctionInput…], resonators=[ResonatorInput…])
                                                              ▼
                CircuitModelResult(qubits=[QubitResult…], couplings, resonators, resonator_couplings)
                                                              ▼
                write_results_sidecar() → chip.results.yaml（tier 2）+ chip.manifest.yaml
```

关键设计: `AssembledSystem.as_capacitance_result()` 把拼装结果**包装成 `CapacitanceResult`**
（每个节点造一个 `TerminalBinding(index=i+1, group=node, attribute=0)`）, 于是
**M6 的求解器一行不改**就能消费拼装结果。这是「新增一层而不改下游」的关键接缝。

### 2.5 M8 P0 逐项 → 代码位置

| spec           | 内容                          | 落在哪                                                                               |
| -------------- | ----------------------------- | ------------------------------------------------------------------------------------ |
| **P0-A** | 子集提取 + ground pocket 保留 | `geo_emit.emit_block_geo()`; 编排在 `geo_build`                                  |
| **P0-B** | 拼装层（累加 + Schur + 审计） | **新** `dsl/assemble.py`                                                     |
| **P0-C** | 从文件/inline 读矩阵          | `palace_adapter.capacitance_from_file/_inline`; `--no-solve`                     |
| **P0-D** | `TL_RESONATOR` + χ         | `circuit_model.ResonatorInput` / `resonator_lumped_lc` / `dispersive_shift_hz` |
| **P0-E** | 结电容`C_j`                 | `circuit_model`（结基对角、求逆前）+ 两条 parser 路径                              |
| **P0-F** | CPW 解析                      | **新** `dsl/cpw_analytic.py`                                                 |

### 2.6 S1–S5: `emit_block_geo` 到底做了什么

| 规则         | 做法                                                                           | 备注       |
| ------------ | ------------------------------------------------------------------------------ | ---------- |
| S1           | `metal::`/`jj::`: 只保留 `component ∈ components`                       | 块的定义   |
| **S2** | `ground::`/`substrate::`: 整张面与「块窗口」**shapely 求交**         | ★ 见下    |
| S3           | 块窗口 = 入选导体并集 bbox +`side_buffer`                                    |            |
| S4           | airbox:**零代码** —— `compute_chip_bbox_from_geo(块几何)` 自动跟着缩 |            |
| S5           | `port::`/`symmetry::` dim-1 marker: 随 S1 过滤后原样重发                   | 静电用不到 |

**S2 是本改动的头号 silent-wrong-result 风险, 也是最漂亮的一处简化。**
源 `.geo` 里 ground 已经是一张**带孔面**（孔由 `.geo` 内的 `BooleanDifference` 挖好）,
所以 `ground_poly ∩ 窗口` **自动保留窗口内的全部孔**, 与那个孔属于哪个 component 无关 ——
风险从「要小心别写错」变成「**结构上写不错**」。

反面（**绝不能**这么做）: 按 component 过滤 pocket 集合 → 被排除 component 的 pocket 没挖 →
ground 金属侵入本该是真空腔的区域 → 留下来的导体**对地电容静默偏高, 管线全绿**。
正确语义: 被排除的 component 留下一个**有洞、没金属的空真空腔**。
这正是 qiskit-metal `add_endcaps()` 的等价物（在 open pin 处从地平面减掉一个矩形）。
`keep_all_subtractive=False` 是**故意错**的护栏路径, 只服务测试, 生产永远别传。

⚠ 实现细节: 有孔的面必须走 `BooleanDifference` 发出, **不能**用多环 `Plane Surface` ——
多环面在 OCC `extrude` 时孔会被**填实**（M5a 踩过的坑）。

---

## 3. 演示脚本（分幕）

### 幕 0 — 环境（30 秒）

```bash
conda activate metal-env          # qiskit_metal 0.5.1 + gmsh 4.11.1 + gdstk + shapely
cd ~/quantum_dsl
export PYTHONPATH=src
unset QDSL_MESH_ALGO3D            # ⚠ 跑测试套件时必须没有它（两个回退测试要走它绕过的路）
```

**要说的点**: Palace 需要 `HWLOC_COMPONENTS=-gl`, 已经用 `conda env config vars` 持久化进
`metal-env` 与 `quantum-metal` —— 不设它, 本机**任何** MPI 程序都在 `MPI_Init` 前零输出挂死
（hwloc 的 `gl` 插件通过 TCP 探测 X display, 127.0.0.1:6001 黑洞掉 SYN）。

```bash
python -m pytest tests/ -q        # 期望: 619 passed, 3 skipped（~2 分 40 秒）
```

---

### 幕 1 ★主菜 — 零 FEM 走完整条拼装链（2 秒, 复现 4.05）

**这一幕最值钱**: 它用 qiskit-metal tutorial 4.05 **自己的两份矩阵文件**走我们的管线, 2 秒出结果,
不需要 Palace、不需要 gmsh 解任何东西。

先造 demo 目录（用仓库里的 golden fixture 当输入）:

```bash
D=/tmp/m8demo && mkdir -p $D && cd $D
cp ~/quantum_dsl/tests/fixtures/two_pads.geo .          # 占位几何（GDS fork 总要一份）
cp ~/quantum_dsl/tests/fixtures/lom405/Q*.txt .          # 4.05 的两份 Q3D 矩阵
```

写 `lom405.meta.yaml`:

```yaml
schema: qiskit-metal/design-dsl/3
geo: two_pads.geo          # 占位: 本例的电容全部来自文件注入
vars: {}

extract:
  blocks:
    - name: qb1
      from: file
      path: Q1_TwoTransmon_CapMatrix.txt
      nodes:
        coupler_connector_pad_Q1: coupling        # ← 共享节点名
        readout_connector_pad_Q1: readout_alice
      junctions:
        - {name: j1, between: [pad_top_Q1, pad_bot_Q1], L_J: 10nH, C_j: 2fF}
    - name: qb2
      from: file
      path: Q2_TwoTransmon_CapMatrix.txt
      nodes:
        coupler_connector_pad_Q2: coupling        # ← 同一个名字 → 与 qb1 连通
        readout_connector_pad_Q2: readout_bob
      junctions:
        - {name: j2, between: [pad_top_Q2, pad_bot_Q2], L_J: 12nH, C_j: 2fF}

assemble:
  ground_node: ground_main_plane
  nodes_force_keep: [readout_alice, readout_bob]

subsystems:
  - {name: QB1, type: transmon, junction: j1}
  - {name: QB2, type: transmon, junction: j2}
  - {name: RO1, type: tl_resonator, node: readout_alice, f_res: 8.0GHz, Z0: 50ohm, mode: half_wave}
  - {name: RO2, type: tl_resonator, node: readout_bob,   f_res: 7.6GHz, Z0: 50ohm, mode: half_wave}

simulation:
  gmsh:
    layer_stack:
      1: {kind: metal, thickness: 2, z: 0, material: pec}
      3: {kind: dielectric, thickness: -100, z: 0, material: silicon, eps_r: 11.45}
    airbox: {top: 120, bottom: 120, side_buffer: 80}
    mesh: {max_size: 40, min_size: 4}
    gds:
      lib_name: demo
      top_cell: demo
      unit: 1.0e-6
      precision: 1.0e-9
      by_role: {metal: {layer: 1, datatype: 0}}
    solver: {type: Electrostatic, order: 2, l0: 1.0}
```

跑:

```bash
PYTHONPATH=~/quantum_dsl/src python -m quantum_dsl.dsl.geo_build lom405.meta.yaml --out-dir out
```

**实测输出**:

```
GDS         : .../out/chip.gds
MSH         : None                       ← 分块路径下 msh/palace_json 是「每块」的, 见 blocks
Palace JSON : None
Block       : qb1 (from=file, matrix=yes)
Block       : qb2 (from=file, matrix=yes)
Results     : .../out/chip.results.yaml
Manifest    : .../out/chip.manifest.yaml
```

**打开 `out/chip.results.yaml`, 逐段讲**:

1. `capacitance.source: assembled:file` ← **溯源**: 这份矩阵是拼装出来的, 且每个 cell 都来自文件。
   一份全靠注入拼出来的结果**绝不会**自称实解（风险 R4）。
2. `capacitance.terminals` 是 6 个: `pad_bot_Q1 pad_top_Q1 readout_alice pad_bot_Q2 pad_top_Q2 readout_bob`
   —— **`coupling` 不在里面**, 它被 Schur 消掉了。原始两份矩阵各 5×5（含 ground）, 拼装+消元后是 6×6。
3. `hamiltonian.qubits`:

   |     | C_sigma_fF | C_sigma_geometric_fF | E_C (GHz) | f01 (GHz) | E_J/E_C |
   | --- | ---------- | -------------------- | --------- | --------- | ------- |
   | QB1 | 63.0769    | 61.0767              | 0.307089  | 6.0299    | 53.2    |
   | QB2 | 84.1939    | 82.1936              | 0.230067  | 4.7771    | 59.2    |

   **`C_sigma − C_sigma_geometric = 2.000 fF` 精确等于 `C_j`** —— 「FEM 解出来的」与「工艺给的」
   在结果里可分辨。
4. `couplings`: QB1↔QB2 `g = 27.885 MHz`, `C_g = 0.717 fF`。
   **这个 g 完全来自 `coupling` 节点的 Schur 消元** —— 两份矩阵之间没有任何直接的互电容项。
5. `resonators`: RO1 `f_bare 8.0 → f_loaded 7.6725 GHz`, `Cr 625 fF`, `Lr 0.6333 nH`。
   加载来自爪子的实测电容。
6. `resonator_couplings`: QB1↔RO1 `g 139.27 MHz, χ −2.717 MHz`; QB1↔RO2 `g 3.67 MHz`
   （**串扰, 小三个数量级** —— 这是拼装矩阵自然给出的, 不是另加的模型）。
7. `provenance.assembly`: `method` 写明「累加 + eq 7b Schur, node 基」, `eliminated: [coupling]`,
   逐 cell 的 `source` + **`sha256`**, 以及 `audit`（每个节点来自哪些 cell / 哪些是共享节点 / 警告）。

**这一幕的三个金句**:

- 「跨块连通只有一条机制: **共享节点名**。改个名字就等于焊一根线。」
- 「`coupling` 被消掉了, 但它中介的耦合**留在了矩阵里** —— 这就是 Schur 与接地的区别。」
- 「全程没跑 FEM, 2 秒。所以拼装层与电路模型的回归测试是**零成本**的。」

> ⚠ **诚实提醒（必须自己知道）**: 这里的 `E_C = 307.09 MHz` 与 4.05 golden 的 **312.76 MHz** 差 1.8%,
> 因为我们把谐振器的解析 `Cr`（625 fF）折在了它节点的对角上 → 反过来抬高了 qubit 的 C_Σ。
> New LOM **不**把 `Cr` 加进电容图（谐振器是独立子系统）。仓库的 golden 断言
> （`test_lom405_charging_energy_matches_reference`, 偏差 7.6e-9）跑的是**不声明谐振器**的配置。
> 换句话说: **同一个设计, 声明了谐振器 E_C 就会变**。这是 spec §4 P0-D 第 3 条要求的建模选择,
> 但演示时不要说成「与 4.05 逐位吻合」。

---

### 幕 2 — G1: 块几何真的落盘了（2 秒）

```bash
cd ~/quantum_dsl
python -m quantum_dsl.dsl.geo_build examples/dsl/geo/sung_2021_device_blocks.meta.yaml \
       --out-dir /tmp/m8sung --no-solve
```

**实测 2.1 秒**, 输出三份 `block_qb1.geo` / `block_cplr.geo` / `block_qb2.geo` + `chip.gds` + manifest,
并打印 `note: 0/3 extract block(s) have a capacitance matrix — skipping assembly`
（**故意的**: 缺一个块就少一段电容图, 宁可不写结果）。

看头部注释（自解释, 且 `DO NOT EDIT`）:

```
// AUTO-GENERATED by quantum_dsl.dsl.geo_emit.emit_block_geo (P0-A).
// Block subset derived from: sung_2021_device.geo
// components      : CPLR
// side_buffer_um  : 200
// window (µm)     : ('-560', '-564', '560', '564')
// keep_all_subtractive: True
```

进 manifest 带 sha256:

```bash
grep -A 2 "role: block-geo" /tmp/m8sung/chip.manifest.yaml
#   → block_qb1.geo / block_cplr.geo / block_qb2.geo, 各带 sha256 + bytes + mtime
```

**肉眼验 S2**（G1 带来的、单元测试给不了的验证）:

```bash
gmsh /tmp/m8sung/block_cplr.geo        # 需要 WSLg / X server
```

看两件事: ①只有 CPLR 的金属在; ②**被排除的 QB1/QB2 位置上, 地平面的 pocket 还开着**
（有洞、没金属的空真空腔）。这一条就是 §2.6 说的头号风险的目视确认。

同时对 `two_pads` 做最小对照（`block_A.geo` 只有 24 行, 一眼看完）:

```bash
python -m quantum_dsl.dsl.geo_build tests/fixtures/two_pads_blocks.meta.yaml \
       --out-dir /tmp/m8tp --no-solve && cat /tmp/m8tp/block_A.geo
```

**要说的点**: 源 `sung_2021_device.geo` 123 行 → 块 74/84/74 行; `two_pads` 的 chip bbox 面积
19,200 → 6,400 µm²（`chip_layout` 是 680,000 → 275,080 µm², **降到 40.5%**）。
这个缩小是 **S4 零代码**白拿的。

---

### 幕 3 — Schur vs 硬接地: 定量差别（2 秒）

```bash
python -m pytest tests/test_assemble.py -q -k "lom405 or schur"      # 7 passed
```

然后直接给数字（`test_lom405_schur_vs_hard_grounding` 的 docstring 里写着实测值）:

|                         | **Schur 消元** | 硬接地（现状的整片路径）                       |
| ----------------------- | -------------------- | ---------------------------------------------- |
| `C_k[j1][j2]`         | −0.766012 fF        | **0.0**                                  |
| `g(j1, j2)`           | 25.1427 MHz          | **0.00**                                 |
| 其它跨 cell`g`        | 25–1696 MHz         | **0.00**                                 |
| `C_Σ(j1) / C_Σ(j2)` | 61.9338 / 82.6643 fF | 62.4888 / 83.4751（**+0.90% / +0.98%**） |

**金句**: 「接地不是『扰动』耦合, 是把它**整条删掉**; 而块内 `C_Σ` 只错约 1% ——
**后者才是会静默出货的那部分**。」

顺带讲验收强度: 我们的 `C_k` 对 4.05 参考的 eq-7b `C_k`（全 16 个元素）偏差 **7.7e-16**
（判据 <0.1%, 超出 13 个数量级）; golden 由 `tests/fixtures/lom405/generate_expected.py`
在参考 env `quantum-metal` 里跑**参考实现**生成, 带 provenance, 不是自证。

---

### 幕 4 — CPW 解析计算器（10 秒）

```bash
python -c "
from quantum_dsl.dsl.cpw_analytic import lumped_cpw
r = lumped_cpw(5e9, 10e-6, 6e-6, 760e-6, 200e-9)          # ⚠ SI 米!
print(f'Z0={r.Z0:.3f} ohm  eps_eff={r.eps_eff:.4f}  lambda_g={r.lambda_g*1e3:.4f} mm')
print(f'lambda/2 谐振器长度 = {r.lambda_g/2*1e6:.1f} um   Lk/Lext={r.Lk/r.Lext:.4f}')
n = lumped_cpw(5e9, 1e-6, 0.5e-6, 500e-6, 20e-9, london_penetration_depth=90e-9)
print(f'窄线 1/0.5um, 20nm 膜, lambda_L=90nm:  Lk/Lext={n.Lk/n.Lext:.4f}')
"
```

**实测**:

```
Z0=51.603 ohm  eps_eff=6.0654  lambda_g=24.3454 mm
lambda/2 谐振器长度 = 12172.7 um   Lk/Lext=0.0054
窄线 1/0.5um, 20nm 膜, lambda_L=90nm:  Lk/Lext=1.3994
```

**要说的点**:

- 典型 10/6 µm 硅上 CPW → `Z0 ≈ 51.6 Ω`, 5 GHz 的 λ/2 谐振器长 **12.17 mm** —— 这就是
  「谐振器该画多长」的答案, 也是 `subsystems[].cpw:` 子块能替代 `f_res:` 的原因。
- 窄线 + 薄膜 + 大伦敦深度时 **`Lk` 超过几何电感（1.40×）** —— 忽略动力学电感错 >100%。
  ⚠ 这个 1.4 依赖 `λ_L = 90 nm`（无序 NbN/颗粒铝那类）; 默认铌的 30 nm 下同几何只有 **0.19**。
- 对参考实现 `lumped_cpw()`/`guided_wavelength()` 的**最大相对偏差 9.2e-16**（判据 1%）。
- 三条「不要顺手修正」的已知不自洽（都有测试钉住）: `Z0 ≠ √((Lext+Lk)/C)`（参考的 Z0 来自共形映射,
  不含 Lk）; `λ_g ≠ 1/(f√(LC))`（λ_g 走 ε_eff, C 走 ε_r + 填充因子）;
  常数照抄参考实现字面值（`c0=2.9979e8`, `30π`）而不用 SI-2019 精确值 ——
  换了就没法逐位对齐, 而本模块的正确性定义**就是**参考实现本身。

---

### 幕 5 — 守卫演示: 故意写错（各 2 秒, 很有说服力）

拿幕 1 的 `lom405.meta.yaml` 改三处, 每次都该**报错而不是静默算错**:

**(a) 拼错 `nodes:` 的键**（`readout_connector_pad_Q1` → `..._Q9`）:

```
error: extract block 'qb1': nodes: key(s) ['readout_connector_pad_Q9'] match no
capacitance terminal of this block — a mistyped node name silently drops or invents
coupling. Addressable terminals: <none>
```

> 顺带演示了 review 的 **F4**: 守卫对了, 但 file/inline 块的「可寻址终端」提示是空的
> （应列 `cap.terminals` 的真名字）。一行可修。

**(b) 删掉 `RO2` 这个 subsystem**（让 `readout_bob` 没人认领）:

```
error: assembled node(s) ['readout_bob'] are not claimed by any subsystem — they would
be SILENTLY GROUNDED by the circuit-model solve, killing whatever coupling they mediate
(this is exactly issue #20). Either declare a subsystem on them, or drop them from
assemble.nodes_force_keep so Schur elimination integrates them out properly.
```

这条是 issue #20 的收尾守卫: **raise, 不 warn**。

**(c) 照 spec 原文写 `{name: QB1, type: transmon, node: j1}`**:

```
error: subsystems[0] (type 'transmon') does not accept key(s) ['node']; allowed:
['junction', 'name', 'type'] — a transmon names its JUNCTION via 'junction:',
a tl_resonator names its NODE via 'node:'
```

**金句**: 「spec 里那个写法用 `node:` 指一个**结**名, 与 tl_resonator 的 `node:` 撞语义。
我们**故意让它报错**, 而不是静默把结名当节点名查 —— 后者正是 R2 类静默错。」

---

### 幕 6 — 真解（可选, 要 Palace; 有时间预算才做）

```bash
# two_pads 分块 A/B（小, 几分钟量级）
python -m quantum_dsl.dsl.geo_build tests/fixtures/two_pads_blocks.meta.yaml \
       --out-dir build/tp_blocks --run-palace --np 8
```

```bash
# sung 三块 order 2（session 2607290329 实测: 3 块合计 132.1 s Palace 墙钟, 最大块 5.6 G 内存）
export QDSL_MESH_ALGO3D=10          # ⚠ 演示命令需要它; 跑测试套件时**不要**设
python -m quantum_dsl.dsl.geo_build examples/dsl/geo/sung_2021_device_blocks.meta.yaml \
       --out-dir build/sung_blocks --run-palace --np 8
```

**已记录的实解结果**（来自 `session/2607290329.md`, 不是本文实测）:

|                   | 整片基线   | 分块实解      | 偏差             |
| ----------------- | ---------- | ------------- | ---------------- |
| `two_pads` C_AA | 24.7288 fF | 24.98457      | **+1.03%** |
| `two_pads` C_BB | 24.7293 fF | 24.99032      | **+1.06%** |
| `two_pads` C_AB | −1.976 fF | **0.0** | 结构必然         |

`sung` 三块 order 2: C_Σ **98.856 / 226.160 / 98.835 fF**, 对 Elmer **−3.2% / −2.9% / −3.2%**（判据 <5%）。

⚠ **这一幕必须同时讲清三条不利事实**, 否则数字会被误读:

1. **`sung` 的「达标」是两个大误差反向抵消**: 同 order 下分块本身把 C_Σ 抬高 **+12~15%**（超判据）,
   order 1→2 又压低 ~21%。在 sung 上**无法干净分离**（整片 order 2 = issue #22 解不出来,
   order 1 离收敛还差 ~20% = #26）。**可信的分块误差只有 `two_pads` 的 +1.03%**。
2. **R8 成立: 总墙钟没降。** 分块 3 块合计 2.19 M 未知量 ≈ 整片 order 2 的 2.24 M
   （每块都要重划自己的衬底 + airbox, 抵消了 S3/S4 的节省）。真实收益是**单次求解规模
   2.24 M → 0.6~1.0 M, 于是 order 2 才跑得起**, 峰值内存也降。
3. **跨块耦合必然为 0**: 切割面落在 component 边界 ⇒ 两块分离焊盘之间的互电容被切掉。
   `sung_2021_device_blocks.meta.yaml` 的长头注释就是专门解释这一条的:
   **想保哪两个导体的耦合, 就把它们放进同一个块**（`components: [QB1, CPLR]`）。

---

## 4. 演示中会被戳的地方（诚实清单）

| # | 事                                                                            | 现状                                                                                                                                                                                                                                                |
| - | ----------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 | χ 对老 LOM**−16.1%**, 没达到 <5% 判据                                 | 已干净分解成两个**已知定义差**: g 定义（inverse-cap vs `bbus` 电压分压）−8.5% + 数值 CPB 谱 −8.3%, 乘积 0.8388 ≈ 实测 0.8392。**χ 公式本身对参考实现逐位一致**（rel 1e-15）, 全部偏差在入参上。关掉谱那一半 = P1-H（已 defer）    |
| 2 | S2 的**live Palace 护栏没跑**                                           | 需要一个 pocket**互不相连**的设计（`chip_layout` 的 6 个 pocket 被 OCC 合成 1 个连通孔, `keep_all_subtractive=False` 在它上面是 no-op）。现在 S2 由几何层的**点覆盖**断言 + 面积/孔数量化守着, 没有「两解对地电容比值」这条实解证据 |
| 3 | 网格收敛从来没测过                                                            | sung order 1→2 差 21%; Elmer 自己 5/50→2/30 就降 6%。`tier` 只描述完整度不描述精度 → issue **#26**, 当前最该做的一件                                                                                                                     |
| 4 | 声明谐振器会移动 qubit 的 E_C（幕 1 的 1.8%）                                 | 我们把解析`Cr` 折在节点对角上（spec §4 P0-D 第 3 条要求）, New LOM 不这么做。建模选择, 但要说清                                                                                                                                                  |
| 5 | 整片路径**没有** Schur                                                  | 不带`extract:` 的路径仍把未被引用的 Terminal 当接地电极（那条路径没有「哪些节点是动力学的」这个声明）。`chip_layout` 的浮动 bus 要享受 Schur, 得改写成 `extract.blocks` + `nodes_force_keep` = issue **#20** 的剩余一半               |
| 6 | `from: file` 读 **Palace CSV** 时终端名自动生成 `t1..tN`            | 两个这样的块会被当成共享节点**静默合并**（实测对角 20/30 → 40/60 fF, 零警告）= review 的 **F1**, 待修。Q3D 文件与 inline 都自带名字, 不受影响                                                                                          |
| 7 | 块窗口（S3）与 airbox（S4）复用**同一个** `airbox.side_buffer` 且叠加 | ⇒ 块的真空外延 = 金属 bbox + 2×side_buffer。调 airbox 会静默改动块的 ground 外延 = review 的**F2**。`two_pads` 不受影响（该 `.geo` 没有 `ground::`/`substrate::`）, 所以 +1.03% 仍成立                                              |
| 8 | 一份纯文件注入的 build 仍然要一个`.geo`                                     | GDS fork 无条件跑。幕 1 用`two_pads.geo` 当占位, 产物 `chip.gds` 与本次计算无关                                                                                                                                                                 |

---

## 5. 一页速查

```bash
# 唯一受支持入口
python -m quantum_dsl.dsl.geo_build <meta.yaml> --out-dir DIR \
       [--run-palace [--dry-run]] [--np N] [--no-solve] [--png [name.png]]
```

| 开关                       | 含义                                                                                                                                       |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `--no-solve`             | 跳过所有 FEM: 仍然派生并落盘每份`block_<name>.geo`（供 GUI 检视）, 但不划网格不跑 Palace。**只是求解开关, 永不改动几何参数**（G2） |
| `--run-palace --dry-run` | 只让 Palace 校验/试划分, 不求解 → 拿不到矩阵 → 不写 results                                                                              |
| `--np N`                 | Palace 的 MPI rank 数                                                                                                                      |

**sidecar 顶层键**: `schema` `geo` `vars` `simulation` `circuit_model` `cells`

+ 【M8】`extract` `assemble` `subsystems`

```yaml
extract:
  blocks:
    - name: <块名, 全局唯一>
      from: solve | file | inline          # 默认 solve
      components: [<comp>…]                # from: solve 必填
      path: <矩阵文件>                      # from: file 必填（Palace CSV 或 Q3D txt）
      matrix: {terminals: […], maxwell: [[…]]}   # from: inline 必填
      units: fF                            # file/inline 的兜底单位（文件自述优先）
      nodes: {<旧名>: <共享名>}              # = New LOM 的 node_rename, **先**生效
      junctions:
        - {name: <结名, 全局唯一>, between: [<1 或 2 个节点>],
           L_J|E_J|squid: …, C_j: 2fF}     # L_J/E_J/squid 恰选一个
assemble:
  ground_node: <参考地节点名>
  nodes_force_keep: [<不许被 Schur 消掉的节点>…]
subsystems:
  - {name: …, type: transmon,     junction: <结名>}
  - {name: …, type: tl_resonator, node: <节点名>,
     f_res: 7GHz | cpw: {line_width: 10um, line_gap: 6um, length: 4200um},   # 恰选一个
     Z0: 50ohm, mode: half_wave | quarter_wave}
```

**节点名三种写法都合法**: `metal::1::QB1::pad_top` · `QB1_pad_top_sfs` · `nodes:` rename 后的名字。

**测试速查**:

| 想验什么                                    | 命令                                                 |
| ------------------------------------------- | ---------------------------------------------------- |
| 拼装 + 4.05 golden + Schur vs 接地          | `pytest tests/test_assemble.py -q`                 |
| CPW 解析对参考                              | `pytest tests/test_cpw_analytic.py -q`             |
| `emit_block_geo` / S2 护栏 / G1 契约      | `pytest tests/test_geo_block.py -q`                |
| sidecar 的 extract/assemble/subsystems 校验 | `pytest tests/test_geo_meta_extract.py -q`         |
| 谐振器 / χ / C_j                           | `pytest tests/test_circuit_model_subsystems.py -q` |
| 文件/inline 注入                            | `pytest tests/test_cap_from_source.py -q`          |
| 编排层（全 inline, 零 FEM）                 | `pytest tests/test_geo_extract_pipeline.py -q`     |

**单位契约**（最容易出错的地方）:

| 层                                                | 单位                                                                                |
| ------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `.geo` / sidecar 的长度 / `cells:` / `cpw:` | **µm**                                                                       |
| `cpw_analytic` 的接口                           | **SI 米 + Hz**（`geo_build` 负责 ×1e-6, 只乘一次）                         |
| 电容矩阵（内部、results）                         | **fF**                                                                        |
| `L_J` / `E_J` / `C_j`（数据类内部）         | **SI**: 亨利 / 焦耳 / 法拉（sidecar 里可写 `10nH` / `12.2GHz` / `2fF`） |
| mesh 分支                                         | OCC 边界处 dilate µm→m, Palace`L0 = 1.0`                                        |
| GDS 分支                                          | 保持 µm（`gdstk.Library(unit=1e-6)`）                                            |
