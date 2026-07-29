# Change spec — 对标 qiskit-metal 补齐 LOM 基本功能（M8）

**状态**: 待评审 · **日期**: 2026-07-29 · **前置**: M3 / M5a / M6 / M7 已完成
**目标**: 让 `meta.yaml + .geo` 路径具备 qiskit-metal LOM 流程的基本功能面，
**架构照抄 New LOM（LOM 2.0），不自创**。唯一受支持的输入是 `meta.yaml + .geo`
（含 `cells:`）；`.metal.yaml` legacy 路径明确标为不再维护。

> **修订记录（重要）**
> - v1 `partitioned-lom-spec.md`：判断「需要拼装层」✅ 对，但机制自创
>   （`cross` 块 / `links:` 解析连接件 / 强制 `unlinked:` / 把 Schur 列入「不做」）❌。
> - v2：断言「qiskit-metal 没有拼装层」❌ **事实错误** —— 只看了老 LOM（4.01），
>   漏了 New LOM（`lom_core_analysis.py`，tutorial 4.04/4.05）。
> - **v3（本文）**：拼装层加回，机制改为 New LOM 的真实做法（Cell + 共享节点名 +
>   电容图累加 + Schur 消元）。证据见 §1.2。

---

## 1. 对标基线

参考实现在本机 `~/metal/qiskit-metal`（quantum-metal 0.7.6，conda env `quantum-metal`，
可直接跑交叉验算）。**有两代 LOM，架构差别很大，都要看。**

### 1.1 老 LOM（tutorial 4.01）— 单块，解析公式

```python
c1 = LOManalysis(design, "q3d")
c1.sim.run(components=["Q1"],                                  # 只渲染一个 qubit
           open_terminations=[("Q1","readout"), ("Q1","bus1")])
c1.setup.junctions    = Dict(Lj=12.31, Cj=2)
c1.setup.freq_readout = 7.0                                    # 谐振器频率是「输入」
c1.run_lom()                                # → E_C/E_J/f01/α/g/χ/T1/dispersion
```

- **CPW 从不进静电仿真**：等效 `Cr/Lr` 由给定频率 + 假设 `Z0=50Ω` 反推
  （`lumped_capacitive.py:238-240`）。进 FEM 的只有 qubit 岛 + 耦合爪子。
- 单 cell、无拼装、解析归约（`tCSq`/`bbus` 那一套，`lumped_capacitive.py:265-320`）。
- 只支持**单 transmon、正好 2 个 pad**（`qubit_index` 硬编码，矩阵尺寸强制 `N+3`）。

### 1.2 New LOM / LOM 2.0（tutorial 4.04/4.05）— 多 cell 拼装 ← **本 spec 的目标架构**

`analyses/quantization/lom_core_analysis.py`，理论依据 **arXiv:2103.10344**
（代码 5 处直接引用方程号：`:252` S_n 变换、`:560` eq 5、`:702` eq 7a、`:717` eq 7b）。

| 类 | 位置 | 职责 |
|---|---|---|
| `Cell` | `:1255` | **一次 EM 提取的产物** — 一个 `cap_mat` + 本 cell 的 `ind_dict`/`jj_dict`/`cj_dict` |
| `Subsystem` | `:801` | 一个量子自由度（`TRANSMON`/`FLUXONIUM`/`TL_RESONATOR`），映射到节点 |
| `CompositeSystem` | `:1303` | 拼装 + Schur 消元 + Hilbert 空间 + 耦合对角化 |

**真实工作流 —— 4.05 的头两行就是证据**：

```python
# loading alice's simulation results
ta_mat, _, _, _ = load_q3d_capacitance_matrix("./Q1_TwoTransmon_CapMatrix.txt")
# loading bob's simulation results
tb_mat, _, _, _ = load_q3d_capacitance_matrix("./Q2_TwoTransmon_CapMatrix.txt")

opt1 = dict(node_rename={"coupler_connector_pad_Q1": "coupling", ...},   # ← 共享节点名
            cap_mat=ta_mat, ind_dict={("pad_top_Q1","pad_bot_Q1"): 10},
            jj_dict={("pad_top_Q1","pad_bot_Q1"): "j1"},
            cj_dict={("pad_top_Q1","pad_bot_Q1"): 2})
opt2 = dict(node_rename={"coupler_connector_pad_Q2": "coupling", ...}, ...)  # ← 同一个名字

composite = CompositeSystem(subsystems=[tmon_a, tmon_b, res_a, res_b],
                            cells=[Cell(opt1), Cell(opt2)],
                            grd_node="ground_main_plane",
                            nodes_force_keep=["readout_alice","readout_bob"])
```

**两个 qubit 分别仿真、两份独立 C 矩阵文件，通过把各自的耦合爪子重命名成同一个节点名
`"coupling"` 而连通。** 拼装的四个环节：

1. **电容图并联累加** — `_df_cmat_to_adj_list`（`:216`）把每个 cell 的 Maxwell 矩阵转成
   邻接表，`_adj_list_to_mat`（`:510-522`）在全局节点索引上 **`mat[r,c] += w`**。
   共享同名节点处电容叠加。**不是块对角拼接。**
2. **S_n 变换**到 node-junction 基（eq 5，`:587-598`）—— 结的磁通显式进基。
3. **Schur 消元**非动力学节点（eq 7b，`:715-732`）:
   `C_k = S_kᵀ (C − C S_r (S_rᵀ C S_r)⁻¹ S_rᵀ C) S_k`；
   `nodes_force_keep` 保留想留的节点（4.05 里保留了两个谐振器接入点）。
4. **scqubits** `HilbertSpace` → `add_interaction` → `hamiltonian_results`
   → `chi_in_MHz`（**从数值对角化出来，不是解析近似**）。

谐振器仍**不进 FEM**：`Subsystem(sys_type="TL_RESONATOR", q_opts={f_res, Z0, vp})`
（`:841-849`）。`vp="use_design"` 时从 `line_width`/`line_gap`/`substrate_thickness`/
`film_thickness` 算相速度 —— **即调 `lumped_cpw()`**。所以 CPW 解析计算器不是可选附属
工具，是 `TL_RESONATOR` 的内部依赖。

### 1.3 结论：拼装层是基本功能，不是高级特性

「一次仿真解整片」在 qiskit-metal 里**不是**推荐工作流。4.05 的做法是分别提取 + 拼装，
这也是 arXiv:2103.10344 的核心主张（模块化）。本仓库现状（整片解、单一 C 矩阵、
无 cell 概念、无共享节点、无 Schur）**落在老 LOM 之前**。

> `status.md` 那句「与 qiskit-metal **LOM 2.0** 独立吻合 <0.1%」对标的正是 New LOM ——
> 但只对上了它的**单 cell 退化情形**。

---

## 2. 功能对标矩阵

| # | qiskit-metal 功能 | 参考位置 | quantum_dsl 现状 | 级别 |
|---|---|---|---|---|
| 1 | `sim.run(components=[...])` 子集渲染 | `analyses/simulation/lumped_elements.py:103` | 🔴 只能整片解 | **P0-A** |
| 2 | `open_terminations` 开路端 endcap | `renderer_ansys/ansys_renderer.py:1389` | 🔴 无等价物（S2 就是它，§4.1） | **P0-A** |
| 3 | **`Cell` 多份 C 矩阵** | `lom_core_analysis.py:1255` | 🔴 只有单一 C 矩阵 | **P0-B** |
| 4 | **`node_rename` 共享节点名连通 cell** | `:1282`, 用例 4.05 | 🔴 无 | **P0-B** |
| 5 | **电容图并联累加拼装** | `:216` + `:510-522` | 🔴 无 | **P0-B** |
| 6 | **Schur 消元非动力学节点**（eq 7b） | `:715-732` | 🔴 无（非 qubit 端子被**硬接地** = `status.md` #20/缺口⑥） | **P0-B** |
| 7 | `nodes_force_keep` | `:1345` | 🔴 无 | **P0-B** |
| 8 | 从**文件**读 C 矩阵（4.05 的标准入口） | `load_q3d_capacitance_matrix` | 🔴 必须跑 Palace | **P0-C** |
| 9 | `TL_RESONATOR` 子系统（`f_res`/`Z0`/`vp`） | `:841-849`, `:1112` | 🔴 无「已知频率谐振器」概念 | **P0-D** |
| 10 | `chi_in_MHz` 色散位移 χ | New: `hamiltonian_results`；老: `lumped_capacitive.py:402` (Koch 3.10, `chi()` `:133`) | 🔴 缺 | **P0-D** |
| 11 | `cj_dict` 结电容 | `:1297`；老: `Cq = tCSq + CJ` (`lumped_capacitive.py:320`) | 🔴 只有 `L_J`/`E_J`/`squid` | **P0-E** |
| 12 | `lumped_cpw()`（含动力学电感） | `analyses/em/cpw_calculations.py:97` | 🔴 缺 — 但 #9 依赖它 | **P0-F** |
| 13 | `guided_wavelength()` 长度↔频率 | `analyses/em/cpw_calculations.py:46` | 🔴 缺 | **P0-F** |
| 14 | `T1`/`T1bus` Purcell | `lumped_capacitive.py:370-380` | 🔴 缺 | P1-G |
| 15 | 精确 CPB 数值对角化 → `dispersion`/`tphi` | `lumped_capacitive.py:438`；New 用 scqubits | 🟡 只有解析 `√(8E_C E_J)−E_C` | P1-H |
| 16 | `FLUXONIUM` 子系统 | `:1036` | 🔴 缺 | P2-I |
| 17 | 参数扫描 | `sweep_and_optimize/sweeping.py:1036` | 🔴 缺 | P2-J |
| 18 | `capacitance_all_passes` + `plot_convergence` | `lumped_oscillator_model.py:103/206` | 🔴 缺（Palace 无 adaptive pass；等价物=网格扫描，缺口④） | P2-K |
| 19 | `df_reorder_matrix_basis` | `lumped_capacitive.py` | 🟢 **不需要** — 按 group 名寻址 | — |
| 20 | `E_C/E_J/f01/α` + 成对 `g` | `lumped_oscillator_model.py:141` | ✅ M6 已有 | — |

### 2.1 已经领先的部分 — 补功能时不要弄丢

| 能力 | 说明 |
|---|---|
| inverse-cap 量化对 N≥3 严谨 | 老 LOM 的 naive Maxwell 对角 double-count 耦合电容（M6 physics review 抓到） |
| 浮动/差分多岛 transmon | `C' = BᵀC_S B` → 求逆取 θθ 块；与 LOM 2.0 单 cell 吻合 **<0.1%** |
| SQUID 磁通可调 | Koch 2007 **无奇点**形式；教科书的 `\|cos\|·√(1+d²tan²)` 在 Φ=0.5Φ₀ 发散成 nan |
| provenance / sha256 / manifest | qiskit-metal 完全没有 |
| 全开源求解链 | Palace + gmsh，不需要 Ansys license |

**P0-B 的 Schur 消元要建在 M6 已有的 `C' = BᵀC_S B` 结基之上**，是它的推广
（结基变换 = New LOM 的 `S_n`），不是替换。

---

## 3. 分层与设计理念约束

### 3.0 硬约束：几何去 Python 化 + 一次确定性几何

本仓库的核心设计理念（native-geo pivot 的立项理由）：

> **几何用 `.geo` 声明式地写，不用 Python 程序化构造；每次 build 消费的几何是
> 一份一次性确定、可检视、可归档、可 diff 的文件。**

M5a 已经确立了这个理念的落地手法：`cells:` 块不是运行时的几何 API，而是被
`elaborate_cells` **降解成一份扁平的 `<stem>.elaborated.geo` 落盘**，emit_geo
「运行在 `load_geo` **严格上游**；nothing below `load_geo` changes」
（`plan.md` M5a）。Python 只在上游跑一次，产物是一份 `.geo`。

**本 spec 的所有几何相关改动必须遵循同一手法。** 三条推论：

| 推论 | 含义 |
|---|---|
| **G1** | 块的几何**落盘为 `block_<name>.geo`**，不是内存里的 tracker 过滤。`load_geo` 及其下游一行不改（与 M5a 同构） |
| **G2** | 命令行/环境变量**不得改动几何参数**。几何与其参数的真值源永远是 `.geo` + `meta.yaml`，可归档、可 sha256、可 diff |
| **G3** | 一次 build = 一份确定几何。需要多份几何（扫参）时，是 **N 次独立 build**，每次自带完整的输入快照，不是一次 build 内的几何变形 |

G1 有一个额外的、很实际的收益：**S2（§4.1 的头号风险）变成肉眼可验证的** ——
`block_qb1.geo` 可以直接用 gmsh GUI 打开，看 pocket 有没有正确保留。
不再只靠单元测试。

### 3.1 分层

```
Layer 1  <stem>.meta.yaml    物理元数据 +【新】extract: / assemble: / subsystems:
Layer 2  <stem>.geo   （或 cells: --emit_geo--> <stem>.elaborated.geo）
         ══ 完整芯片几何，单一真值源，声明式，一次确定 ══
              │
    ┌─────────┴───────────────────────────────────────┐
 GDS fork（一行不改）                     Mesh/Palace fork
 完整图，全部 component            【新】emit_block_geo  →  block_<k>.geo   ← G1
    ↓                              （严格在 load_geo 上游，与 emit_geo 同构）
 chip.gds                                        ↓
                                     load_geo(block_<k>.geo) → 下游一行不改
                                        → block_<k>.msh → Palace → C_k
                                                 ↓
                            【新】Layer 3.5  assemble（§4.2，纯数据层）
                                  {C_k} 按共享节点名累加 → S_n → Schur → C_reduced
                                                 ↓
                            circuit_model（M6 扩展）+ subsystems
                                                 ↓
                                  chip.results.yaml（系统级，tier 2）
```

「GDS 完整图 vs Palace 分块」：**几何的真值源只有一份完整芯片。** 块几何是从它
**派生并落盘**的确定产物（`block_<k>.geo`），不是运行时的内存视图。
与 qiskit-metal `components=["Q1"]` 语义同构，但落地方式契合本仓库的 geo-first 理念 ——
qiskit-metal 那边是 Python 运行时选择，我们这边是派生出一份可检视的 `.geo`。

拼装层（Layer 3.5）**完全不碰几何**，只消费电容矩阵 + Layer-1 的节点/结/子系统声明，
所以它天然符合 G1–G3。

**与 v1 的关键差别**：v1 让每块独立产出 results、不拼装（或用自创的 cross 块/links 拼）。
v3 是**一份系统级 results**，拼装按 New LOM 的共享节点 + Schur。

### 3.2 切割面只能落在 component 边界

`status.md` 记着 `occ.fragment` 对近邻不重叠几何本身就退化（pocket 重叠 30/40 µm 干净，
重叠 10 µm 与完全不重叠都抛 `Boolean fragments failed`，scale 1/1e2/1e3 皆然）。
**不引入任何新的 OCC 布尔切割** —— 块边界 = component 名的集合边界，几何层只做
「渲染 / 不渲染」。CPW 本来就是独立 component，所以「排除 CPW」是天然可得的切割面。
写进 `examples/dsl/README.md`：**想在哪切，就在那里分 component。**

---

## 4. P0 — 基本功能下限

### P0-A：子集提取（派生 `block_<name>.geo`）+ ground pocket 保留

**按 G1 实现为一个 emitter，不是运行时过滤器。** 新增
`emit_block_geo(src_geo, *, components, out_path) -> Path`
（拟置于 `dsl/geo_emit.py`，与 `emit_geo`/`elaborate_cells` 并列 —— 它们是同一类
「`load_geo` 上游的 `.geo` 生成器」）。产物 `block_<name>.geo` 落在 `out_dir`，
`load_geo` 及其下游**一行不改**。

| # | 规则 | 理由 |
|---|---|---|
| S1 | `metal::`/`jj::`：只保留 `component ∈ components` | 块的定义 |
| S2 | **`ground::` 的 subtract 图元：保留块 bbox 内全部，不论 component 是否入选** | ⚠ 见下 |
| S3 | ground sheet extent：按块 bbox + `side_buffer` | 块外 ground 是白算的未知量 |
| S4 | airbox：按块 bbox 重算 | **省算力的主要来源** |
| S5 | `port::`/`symmetry::`：随 S1 过滤 | 静电用不到（M5a 决策 #2） |

S3/S4 是**参数派生**而非几何改写：ground sheet 与 airbox 本来就不在 `.geo` 里画 ——
ground 由 emit_geo 按 `compute_chip_bbox_from_geo` 合成（M5a 决策 #1）、airbox 由
sidecar 的 `airbox:` 参数生成。按块 bbox 重算它们与既有做法同类，且结果**写进
`block_<name>.geo` 的显式几何里**，可检视。

⚠ 实现约束：`emit_block_geo` 的输入是**已解析的完整几何**（`load_geo` 的产物 tracker），
输出是 `.geo` 文本 —— 所以它需要 gmsh 读一次源几何。这与 `emit_geo`（纯 shapely，
不需要 gmsh）不同，是可接受的：它处理的是「已经存在的 `.geo` 的子集」，而不是
「从 IR 造几何」。`chip.manifest.yaml` 逐块登记 `block_<name>.geo` 的 sha256。

#### ⚠ S2 是本改动的头号 silent-wrong-result 风险

M5a 决策 #1：一张 chip-wide ground，聚合**所有** `subtract:true` 图元做一次
`BooleanDifference`。若分块时按 component 过滤这个集合，被排除 component 的 pocket
就不会被挖 → **ground 金属侵入本该是真空腔的区域 → 留下来的 component 对地电容静默
偏高，管线全绿。**

正确行为：pocket 是「ground 上的洞」，洞在哪与哪个导体入选无关。被排除的 component
留下一个**有洞、没金属的空真空腔**。

> 这正是 qiskit-metal `add_endcaps()` 的等价物（`ansys_renderer.py:1400-1418`：在
> open pin 处从地平面减掉 `gap × (width+2·gap)` 的矩形，加进 `chip_subtract_dict`）。
> 两边都是「金属移走、地平面开口留下」——**这就是对标 #2 的落地方式**，不需要新概念。
> docstring 里点明这个对应。

**必须有 live 回归测试**：同设计 `keep_all_subtractive=True/False` 两解，断言 False 的
对地电容显著更高，记录实测比值。测试的存在本身防止后人「优化」掉 S2。

### P0-B：拼装层 — Cell + 共享节点 + Schur

**这是本 spec 的核心，照 §1.2 抄。**

```yaml
extract:                       # 每个 block 一次 EM 提取 = 一个 Cell
  blocks:
    - name: qb1
      components: [QB1]
      nodes:                   # = New LOM 的 node_rename
        metal::1::QB1::coupler_pad: coupling      # ← 共享节点名
        metal::1::QB1::readout_pad: readout_qb1
      junction:                # 本 cell 的结（= jj_dict/ind_dict/cj_dict）
        between: [metal::1::QB1::pad_top, metal::1::QB1::pad_bot]
        name: j1
        E_J: 12.2GHz
        C_j: 2fF
    - name: qb2
      components: [QB2]
      nodes:
        metal::1::QB2::coupler_pad: coupling      # ← 同一个名字 → 与 qb1 连通
        metal::1::QB2::readout_pad: readout_qb2
      junction: {between: [...], name: j2, E_J: 15.8GHz, C_j: 2fF}

assemble:
  ground_node: ground::1::chip::gnd
  nodes_force_keep: [readout_qb1, readout_qb2]    # 谐振器接入点不许被消掉

subsystems:
  - {name: QB1, type: transmon, node: j1}
  - {name: QB2, type: transmon, node: j2}
  - {name: RO1, type: tl_resonator, node: readout_qb1, f_res: 7.0GHz, Z0: 50ohm, mode: half_wave}
  - {name: RO2, type: tl_resonator, node: readout_qb2, f_res: 7.6GHz, Z0: 50ohm, mode: half_wave}
```

新模块 `dsl/assemble.py`（**纯 Python**，复用 `circuit_model._invert_matrix`）：

1. **累加**：每个 `C_k` → 邻接表（节点对 → 电容），在全局节点索引上 `+=`。
   共享名的节点自动叠加。对照 `lom_core_analysis.py:216` + `:510-522`。
2. **结基变换**：复用 M6 已有的 `C' = BᵀC_S B`（`circuit_model.py` 的 `_congruence`）——
   这就是 New LOM 的 `S_n`，M6 已经在单 cell 上验证过。
3. **Schur 消元**：`C_k = S_kᵀ(C − C S_r (S_rᵀ C S_r)⁻¹ S_rᵀ C) S_k`，eq 7b。
   `S_r` = 只接电容的非动力学节点（减去 `nodes_force_keep`）。
   矩阵 ≤ ~10×10，纯 Python Gauss-Jordan 够用。
4. **审计**：provenance 记录每个节点来自哪些 cell、哪些节点被消掉、拼装后矩阵。

> **这条直接解掉 `status.md` 的缺口 ⑥ / #20**：现在非 qubit 端子被**硬接地**，
> 杀掉了 bus 中介耦合；status.md 自己写着「必须正确积掉（消元会重整化 qubit-qubit
> 耦合）」。Schur 消元就是那个欠的东西 —— 不是额外特性，是修一个已知的物理错误。

**不做 scqubits `HilbertSpace` 数值对角化**（§6），χ 走解析式（P0-D）。

### P0-C：从文件读 C 矩阵 —— 是主流程，不是旁路

4.05 的标准入口就是从文件读（`load_q3d_capacitance_matrix`），两份矩阵都是文件。
所以这不是「调试便利」，是**拼装层的正常输入方式**。

```yaml
extract:
  blocks:
    - name: qb1
      from: file                       # file | solve（默认 solve）
      path: measured/QB1_CapMatrix.csv # Palace CSV 或 Q3D txt
      # 或 inline:
      # matrix: {terminals: [...], maxwell: [[...],[...]]}
      # units: fF
      nodes: {...}
      junction: {...}
```

价值三条：
1. **`sung` 的 Elmer 矩阵已经在手上** —— 可以立刻拼装、对照，不等 Palace。
2. **混合来源**：一块用 Palace 解、一块读 Elmer/文献矩阵，拼在一起。
3. **零成本回归**：拼装+电路模型的测试不需要跑 FEM。

⚠ provenance 必须能区分实解与文件注入（`source: solved|file|inline` + sha256），
否则成了新的 silent-wrong-result 面。新 CLI `--no-solve`（只拼装+电路模型）。

### P0-D：`TL_RESONATOR` + χ

对标 #9/#10。谐振器**不进 FEM**：

1. 谐振器的耦合爪子是真实导体，在某个 cell 的 C 矩阵里（一个 terminal）。
2. 等效 `Cr = π/(2 ω_r Z0)`、`Lr = 1/(ω_r² Cr)`；λ/4 时 `Cr /= 2, Lr *= 2`
   （对照 `lumped_capacitive.py:238-250`）。
3. 谐振器作为**一个额外节点**并进拼装矩阵：自电容 = 解析 `Cr` + 爪子实测电容（**加载**）。
4. `g` 从 `[C_k⁻¹]` 的 qubit-θ ↔ 谐振器元素取（沿用 M6 的 inverse-cap 机制）。
5. `χ = 2·chi(g, ω_r, ω_01, ω_12)`，Koch eq. (3.10) —— 对照 `lumped_capacitive.py:133-158`。

⚠ **两个必须写进 docstring + 示例注释的语义陷阱**：

- `f_res` 在 New LOM 里叫 **dressed frequency**（4.05 注释：`f_res=8, # resonator
  dressed frequency in GHz`），而老 LOM 的 `freq_readout` 是**裸频率**（`tCSbus > Cr`，
  `lumped_capacitive.py:295-303`）。**两者语义不同，必须选一个并标注。**
  本 spec 选**裸频率**（与老 LOM 一致，且加载效应由拼装矩阵自然给出），
  results 里 **`f_bare` 与 `f_loaded` 都输出**。
- `Z0=50Ω` 与 `mode` 是假设。给了 `cpw:` 子块（P0-F）时优先用解析值。

### P0-E：`C_j` 结电容

对标 #11。4.05 里 `cj_dict={('pad_top_Q1','pad_bot_Q1'): 2}` 是标配；老 LOM
`Cq = tCSq + CJ`（`lumped_capacitive.py:320`），默认 2 fF。现在 `JunctionInput`
（`circuit_model.py:103`）只有 `L_J`/`E_J`/`squid`，结电容隐含当 0 → **E_C 系统性偏高**。

加在结分支上：`C_Σ,eff = 1/[C_k⁻¹]_θθ + C_j`。**默认 0**（不静默移动任何现有数值）。

### P0-F：CPW 解析计算器

对标 #12/#13。**不是可选附属工具** —— `TL_RESONATOR` 的 `vp="use_design"`
（`lom_core_analysis.py:1115-1121`）内部就依赖它。且回答「`f_res` 从哪来」。

新模块 `dsl/cpw_analytic.py`（**纯 math**，与 `circuit_model.py` 同纯度）:
`lumped_cpw(freq, line_width, line_gap, substrate_thickness, film_thickness, eps_r,
london_penetration_depth)` → `(Lk, Lext, C, G, Z0, eps_eff)`，外加
`guided_wavelength()`。**必须含动力学电感 `Lk`** —— 窄线超导 CPW 不可忽略。
对照 `analyses/em/cpw_calculations.py:97/46`，gated 数值交叉验算。

```yaml
subsystems:
  - name: RO1
    type: tl_resonator
    node: readout_qb1
    cpw: {line_width: 10um, line_gap: 6um, length: 4200um}   # → f_res 解析算出
    # 或直接给 f_res:
```

---

## 5. P1 / P2

| 级别 | 项 | 内容 |
|---|---|---|
| **P1-G** | Purcell `T1` | `T1_bus = (ω_r²−ω_q²)²/(4κg²ω_q²)`，`κ=ω_r/Q`。对照 `lumped_capacitive.py:370-380`。⚠ `Q` 是用户猜的（qiskit-metal 硬编码 `Qreadout=1e4`），results 标注依赖项；不给 `Q` 就不输出 |
| **P1-H** | 精确 CPB 对角化 → `dispersion`/`tphi` | 现在 `f01=√(8E_C E_J)−E_C`（`circuit_model.py:262`）在 `E_J/E_C ≲ 20` 偏差可观。qiskit-metal 用电荷基 81×81 对角化（`lumped_capacitive.py:438`）。⚠ 与 `circuit_model.py` 的「无 numpy」约定冲突 → 隔离到新模块 `dsl/cpb_numeric.py`（numpy 可选、lazy；无 numpy 回退解析并标 `method: asymptotic`）。验收：对 `Hcpb` <0.1% |
| **P2-I** | `FLUXONIUM` 子系统 | `lom_core_analysis.py:1036`。schema 已能容纳（`subsystems[].type`） |
| **P2-J** | 参数扫描 | ⚠ 必须遵守 **G2/G3** —— **不能**用 `--sweep 'cells.QB1.params.pad_width=[...]'` 这种命令行改几何参数的形式（那会把几何真值源挪到命令行，不可归档、不可 diff）。正确形式：扫描声明**写在 sidecar 里**（`sweep: {var: vars.pad_width, values: [400,425,450]}`），`geo_build` 为每个值**物化一份完整的 `meta.yaml` 快照 + 一次独立 build**（`out_dir/<value>/`，各自的 `.elaborated.geo` / `block_*.geo` / manifest / sha256），顶层再写 `sweep.results.yaml` 汇总。每次 build 内部仍是「一份确定几何」。**P0-A 的最大受益者**：整片解跑一次都困难，块小了才扫得起 |
| **P2-K** | 网格收敛扫描 | = `status.md` 缺口 ④（实测 5/50→2/30 差 **6%**，而 `tier` 只描述完整度不描述精度）。`--converge`，判据相邻档 <2% |

---

## 6. 明确不做（及为什么）

| 不做 | 理由 |
|---|---|
| **scqubits / qutip `HilbertSpace` 数值对角化** | New LOM 用它算 `chi_in_MHz`（`:1448-1469`）。代价：numpy+scipy+qutip+h5py 重依赖（qiskit-metal 自己要给 h5py 打 monkey patch，`:16`），与 `circuit_model.py` 的纯度约定冲突。**取舍**：χ 走 Koch eq.(3.10) 解析式（老 LOM 就用它）。⚠ **诚实代价**：强耦合 / 近共振（\|Δ\| ≲ g）时解析式不如数值对角化 —— results 必须标 `chi_method: perturbative` 并在 docstring 写明适用范围。若将来要更准，加在 P1-H 的可选 numpy 模块里 |
| **v1 的 `links:` 解析连接件框架** | §1.2：跨 cell 连通靠**共享节点名**，不需要通用连接件模型。CPW 的作用由 `TL_RESONATOR` 承担 |
| **v1 的 `cross` 块 / 强制 `unlinked:`** | 同上。共享节点自动产生耦合；没共享节点就是不耦合，语义自明 |
| 新的 OCC 布尔切割 | §3.1，`fragment` 已知脆弱 |
| eigenmode / driven / lumped ports | 仍是 M4，deferred |
| 块的并行求解 | gmsh 进程全局状态（`geo_build.py:177-187` 的 SESSION OWNERSHIP 注释）；需要进程级隔离 |
| `mesh.conductor_mode: void\|volume`（缺口 ③） | 独立议题。⚠ 但记住那个 1 µm ε-nudge 按代码自述**压低所有电容 ~30%**（`_gmsh_geo_source.py:546`）：它在分块与整片两侧同样存在，别误读成分块引入的误差；§7 所有对照都在同一 nudge 下做，偏差可比 |

---

## 7. 验证 — 逐项对 qiskit-metal 数值交叉验算

已有成功先例：M6 对 LOM 2.0 <0.1%、`sung` 对 Elmer。沿用同一手法，
env `quantum-metal`（quantum-metal 0.7.6 + ElmerFEM 9.0 `~/opt/elmer`）。

| 项 | 验证方式 | 判据 |
|---|---|---|
| P0-A | `two_pads` 分块 vs 整片（已有实解 `[[24.7288,-1.976],[-1.976,24.7293]]` fF） | 对角 **< 2%** |
| P0-A | **`sung` 首次解得完** — 整片 6 terminal / 2,242,111 未知量从没解完（SIGTERM，`status.md` 欠账 2）；分块后对 Elmer `C_Σ 102.1/232.8/102.1` fF | **< 5%**，且记录墙钟对比 |
| P0-A/S2 | ① `keep_all_subtractive=False` 对地电容偏高（live 护栏，记录实测比值）；② **`block_*.geo` 用 gmsh GUI 打开逐块目视确认 pocket 保留**（G1 带来的、单元测试给不了的验证） | 比值记录在案 + 目视确认写进 session log |
| P0-A/G1 | `block_*.geo` 的 `assign_physical_groups` 输出名与整片解 **byte-identical**（M5a 同契约） | 逐字节相等 |
| **P0-B** | **端到端复现 4.05**：用它的两份 `*_CapMatrix.txt` 走我们的 `extract.from: file` + 共享节点 + Schur，对 `CompositeSystem` 的 `C_k` 与 `chi_in_MHz` | `C_k` **< 0.1%**（同一数学）；χ **< 5%**（解析 vs 数值对角化，差异要**解释**不是掩盖） |
| P0-B | Schur 消元 vs 硬接地（现状）在 `chip_layout.geo` 的浮动 bus 上 | 定量记录 bus 中介耦合的差别 = #20 的收尾证据 |
| P0-C | 注入 `sung` 的 Elmer 矩阵 → 复现已记录的 `E_C 0.190/0.083/0.190` | 逐位一致 |
| P0-D | 同一 C 矩阵 + 同一 `f_bare` → χ 对老 LOM `extract_transmon_coupled_Noscillator` | **< 5%**（g 定义不同：inverse-cap vs `bbus`） |
| P0-E | `C_j=0` 与现状**逐位不变**；`C_j=2fF` 时 E_C 降幅符合 `1/(C_Σ+C_j)` | 解析可验 |
| P0-F | 对 `lumped_cpw()` / `guided_wavelength()` | **< 1%** |
| P1-H | 对 `Hcpb` | `f01`/`α` **< 0.1%** |
| P2-K | `two_pads` 三档网格 | 相邻档 < 2% |

**P0-B 那行是本 spec 的关键验收** —— 4.05 提供了完整的输入 + 参考输出，是一个现成的
端到端 golden case。拿它对上了，拼装层的正确性就有了独立证据。

⚠ 跑套件不要 export `QDSL_MESH_ALGO3D`；Palace 必须 `HWLOC_COMPONENTS=-gl`
（`CLAUDE.md` 两条 ⚠）。新增 gated 测试**逐个确认 `skipif` marker 落对** ——
`status.md` 记着 marker 错位那次事故（挂到不需要 Palace 的 manifest 测试上，
真正的活解测试反而没 gate）。

---

## 8. Legacy 路径退役

### 8.1 退的是输入路径，不是 v3 引擎

`build_ir` / `PrimitiveIR` **不能删** —— M5a 的 `emit_geo` / `elaborate_cells`
（`cells:` 路径）建在 v3 前端之上。

| 组件 | 处置 |
|---|---|
| `.metal.yaml` 作为**用户输入** | 🔴 不再维护 |
| `build_design` → qiskit-metal `QDesign` | 🔴 不再维护 |
| `export_ir_to_metal` | 🔴 不再维护 |
| `gmsh_adapter.build_mesh`（slab，非 `_from_geo`） | 🔴 不再维护 — 与 conductors-as-voids 不一致，曾**静默写空网格** |
| `design_dsl.py`（顶层 facade） | 🔴 不再维护 — 纯 re-export |
| `build_ir` / `PrimitiveIR` / `parsers/` / `component_templates` / `template_*` | 🟢 保留维护，**降级为内部库** |
| `geo_build.build_geo` + `build_mesh_from_geo` | 🟢 唯一受支持入口 |

⚠ 命名冲突要处理：`cells:`（M5a 的**几何** cell 实例）与本 spec 的 `extract.blocks`
（**电学** Cell = 一次 EM 提取）是两个概念。**沿用 `extract.blocks` 这个名字，
不要把 New LOM 的 `Cell` 直接叫 `cells`** —— 否则 sidecar 里两个 `cells:` 撞车。
docs 里明确对照表。

### 8.2 「不再维护」的具体含义 — 不做半死不活的东西

`status.md` 记着一次真实事故：legacy YAML→gmsh 路径**静默写空网格**很久没人发现，
直到 2607021950 的空网格守卫把它**暴露**出来（当时 8 failed / 2 errors）。
**没人看的活代码比删掉的代码危险。** 所以：

1. **测试继续在 CI 跑** — 打 `@pytest.mark.legacy`，默认执行（不是 skip）。腐烂即失败。
2. **模块 docstring 顶部统一横幅**：
   ```
   ⚠ UNMAINTAINED (2026-07-29, M8): the .metal.yaml input path is no longer
   maintained.  The supported input is meta.yaml + .geo (or a `cells:` block).
   Kept for reference + regression only — bugs here are NOT fixed, features are
   NOT added.  Rationale + removal criteria: .claude/lom-parity-spec.md §8.
   ```
3. **一次性运行时 warning**：`build_design`/`build_mesh`/`export_ir_to_metal` 首次
   调用时 `logger.warning` 一行。不用 `DeprecationWarning`（会污染测试输出）。
4. **文档同步**：`README.md` / `AGENTS.md` / `CLAUDE.md` 的 "Two geometry front-ends"
   段改写 —— 现在是**一个**受支持前端 + 一个历史路径。`CLAUDE.md` §Project 第 1 条重写。
5. **删除判据（写死）**：当 ① `examples/` 与 `tests/fixtures/` 中不再有 `.metal.yaml`
   被**非 legacy** 测试引用，且 ② `emit_geo` 不再需要 `build_design`/`export_ir_to_metal`
   的任何符号 → 整体删除。目前 ② 已满足，① 未满足
   （`chain_2q_native.metal.yaml`、`transmon_pocket_2q.metal.yaml` 仍被 legacy 测试引用）。

### 8.3 本 spec 只服务 geo 路径

`select_block` / `assemble` / `subsystems` / `C_j` 全部只加在 `_from_geo` 分支。
legacy slab 路径不做任何适配 —— 与 M3（conductors-as-voids 只做 geo path）同一先例。

---

## 9. 代码变更清单

| 文件 | 变更 | 纯度 | 级别 |
|---|---|---|---|
| `dsl/geo_emit.py` | **新** `emit_block_geo()` → `block_<name>.geo`（G1：与 `emit_geo`/`elaborate_cells` 并列的上游 emitter） | gmsh（读源几何） | P0-A |
| **新** `dsl/assemble.py` | 电容图累加 + S_n + **Schur 消元**(eq 7b) + 审计 | **纯** | P0-B |
| `dsl/schema.py` | `GEO_META_ROOT_KEYS` += `extract`, `assemble`, `subsystems`, `sweep` | 纯 | P0/P2 |
| `dsl/parsers/simulation.py` | `_parse_extract` / `_parse_assemble` / `_parse_subsystems` / `_parse_sweep` | 纯 | P0/P2 |
| `dsl/circuit_model.py` | `SubsystemInput`（transmon/tl_resonator）+ χ + `C_j`；消费拼装后矩阵；`island:`/`islands:` 兼容（#20 接线 bug） | 纯 | P0-B/D/E |
| `dsl/palace_adapter.py` | `terminal_bindings` 支持块内子集；`CapacitanceResult` 支持文件/inline 构造 | — | P0-A/C |
| **新** `dsl/cpw_analytic.py` | CPW 解析集总（含动力学电感） | **纯 math** | P0-F |
| `dsl/geo_build.py` | 编排：`extract.blocks` 循环（emit → load → solve）→ assemble → circuit_model；`--no-solve`；`--converge`；`sweep:` 物化 N 份快照 + N 次 build | gmsh | P0/P2 |
| **新** `dsl/cpb_numeric.py` | 电荷基精确对角化（numpy 可选，lazy） | numpy | P1-H |
| legacy 六处 | §8.2 横幅 + warning + `@pytest.mark.legacy` | — | — |
| `examples/dsl/geo/sung_2021_device.meta.yaml` | 改成 3 个 `extract.blocks` + 共享 coupler 节点 + `subsystems:` | — | — |
| **新** `tests/fixtures/lom405/` | 4.05 的两份 `*_CapMatrix.txt` + 期望 `C_k`/χ（golden） | — | P0-B 验收 |
| `tests/fixtures/two_pads.meta.yaml` | `island:` → `islands:` | — | — |
| `README.md`/`AGENTS.md`/`CLAUDE.md`/`docs/` | 文档同步 + 对标矩阵 + `cells:` vs `extract.blocks` 对照 | — | — |

### 9.1 `geo_build` 编排骨架

```python
extract = meta.get("extract")
if not extract:                                   # 向后兼容：整片解，与今天逐字节相同
    ...current path...
else:
    cells = []
    for blk in extract["blocks"]:
        if blk.get("from") in ("file", "inline"):          # P0-C：无几何参与
            cap = capacitance_from_source(blk)
        else:                                              # P0-A
            # G1: 派生并落盘一份确定的块几何, 再走完全不变的下游管线
            blk_geo = emit_block_geo(geo, components=blk["components"],
                                    out_path=out_dir / f"block_{blk['name']}.geo")
            msh = build_mesh_from_geo(blk_geo, sim_gmsh, output_path=...)   # 下游一行不改
            run_palace(...); cap = parse_capacitance_matrix(...)
        cells.append(ExtractedCell(cap, nodes=blk["nodes"], junction=blk["junction"]))

    assembled = assemble(cells, meta["assemble"])           # P0-B：累加 + S_n + Schur（纯数据）
    cm = solve_circuit_model(assembled, meta["subsystems"])  # P0-B/D/E
    write_results_sidecar(assembled, out_dir / "chip.results.yaml", circuit_model=cm, ...)
```

**每个 `block_<name>.geo` 都是一份可用 gmsh GUI 打开检视的确定几何**，进 manifest
带 sha256。`emit_block_geo` 严格在 `load_geo` 上游，`_gmsh_geo_source.py` /
`carve_conductors` / `fragment` / `assign_physical_groups` **全部不改** —— 与 M5a
「nothing below `load_geo` knows the difference」同一契约，所以 Palace 的 physical
group 名保持 byte-identical。

---

## 10. 里程碑

| 子里程碑 | 内容 | 完成判据 |
|---|---|---|
| **M8a** | P0-A 子集提取（`emit_block_geo` → `block_*.geo`）+ S2 pocket 保留 | `two_pads` <2%；**`sung` 首次解完**且对 Elmer <5%；S2 护栏测试 + **`block_*.geo` 落盘、进 manifest、GUI 目视确认、physical-group 名 byte-identical** |
| **M8b** | P0-C 文件/inline 输入 | 注入 `sung` Elmer 矩阵复现 `E_C 0.190/0.083/0.190` 逐位一致 |
| **M8c** | **P0-B 拼装层**（累加 + S_n + Schur + 审计） | **端到端复现 4.05**：`C_k` <0.1%；Schur vs 硬接地在 `chip_layout` 上的差别定量记录（#20 收尾） |
| **M8d** | P0-D `TL_RESONATOR` + χ；P0-E `C_j`；P0-F CPW 解析 | χ 对 4.05 <5%（差异有解释）；`f_bare`/`f_loaded` 都输出；`C_j=0` 时现有数值不动；CPW 对 `lumped_cpw()` <1% |
| **M8e** | P1-G Purcell + P1-H 精确 CPB | 对 `Hcpb` <0.1% |
| **M8f** | P2-J 扫描 + P2-K 收敛 | `two_pads` 三档 <2% |
| **M8g** | §8 legacy 退役 + 文档 | 横幅/warning/mark 就位；全套仍 368+ passed |

**M8c 是核心** —— 4.05 提供了现成的 golden case（两份输入矩阵 + 参考 `C_k`/χ），
拿它对上就有了拼装层正确性的独立证据；同时收尾 `status.md` 的缺口 ⑥/#20
（硬接地 → Schur 消元）。

**M8a 的「`sung` 首次解完」是最直接的可交付价值**，顺带清掉 `status.md` 欠账 2。

P0（M8a–d）是「基本功能」的下限。P1/P2 可切后续 phase。

落地时按 `CLAUDE.md` §Project-journaling：更新 `status.md`（headline + 测试数）、
`plan.md`（M8 条目 + Session-logs 索引）、写 `session/<yyMMddHHmm>.md`。

---

## 11. 风险

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | **S2 写错 → ground 侵入 → 对地电容静默偏高** | 🔴 silent wrong | §4 P0-A；live 护栏测试 |
| R2 | 拼装的**共享节点名拼错** → 耦合静默丢失或虚增 | 🔴 silent wrong | 拼装审计（每节点来自哪些 cell）；未被任何 `subsystems` 或 `nodes_force_keep` 引用的共享节点 → 警告 |
| R3 | Schur 的 `S_r` 判定错（把动力学节点当非动力学消掉） | 🔴 物理错误 | 照 New LOM 用 `L_inv` 零空间判定；`nodes_force_keep` 兜底；对 4.05 的 `get_nodes_keep()` 逐项比对 |
| R4 | 文件注入与实解在 results 里分不清 | 🔴 溯源污染 | `source: solved\|file\|inline` + sha256 强制 |
| R5 | `f_res` 的裸/dressed 语义混用（New LOM 是 dressed，老 LOM 是裸） | 🟡 设计偏差 | §4 P0-D 选裸频率并标注；两个频率都输出 |
| R6 | χ 解析式在强耦合/近共振失效 | 🟡 精度 | `chi_method: perturbative` 标注 + docstring 写明适用范围 |
| R7 | 切割面太近 → 块内电容偏差超容差 | 🟡 精度 | §7 两条实测对照 |
| R8 | 分块后总墙钟没降 | 🟡 动机不成立 | M8a 强制记录墙钟；不达标就重评估 |
| R9 | legacy 标记后腐烂，重演空网格事故 | 🟡 | §8.2.1 测试继续跑；§8.2.5 写死删除判据 |
| R10 | `cells:`（几何）与 Cell（电学）命名撞车 | 🟡 可用性 | §8.1 用 `extract.blocks`；docs 对照表 |
| R11 | **实现时把块几何做成运行时内存过滤器**（省事但违背 G1），几何不再可检视/可归档 | 🔴 理念侵蚀 | §3.0 G1 写死；`block_*.geo` 必须落盘且进 manifest；§7 的 byte-identical 与目视验证都依赖它存在 |
| R12 | 后续加功能时用命令行/env 改几何参数（违背 G2） | 🔴 理念侵蚀 | §3.0 G2 写死；P2-J 已按此改写；review 时把「几何参数只来自 `.geo`+`meta.yaml`」当硬门槛 |

---

## 12. 待确认

1. **scqubits 要不要引**（§6）：spec 选**不引**，χ 走 Koch 解析式，代价是强耦合/
   近共振精度不如 New LOM 的数值对角化（会标注）。若你要与 4.05 的 χ 完全一致，
   就得引 scqubits + qutip + numpy，且与 `circuit_model.py` 的纯度约定冲突。
2. **Schur 消元的实现**（§4 P0-B）：New LOM 用 sympy 求 `L_inv` 零空间（`:645`）。
   纯 Python 版需要自己判定非动力学节点（「只接电容不接电感」在我们的 schema 里是
   可直接判定的结构信息，不必求零空间）—— 但要确认这个简化对所有拓扑成立。
3. **4.05 的两份矩阵能否直接拿来当 fixture**：它们在 qiskit-metal 的 tutorial 目录下，
   许可 Apache-2.0。若不便拷入本仓库，M8c 的 golden case 要换成自己造的两 cell 算例
   （验收强度会下降 —— 就没有独立参考输出了）。
4. **`emit_block_geo` 需要 gmsh 读源几何**（§4 P0-A 的实现约束）：它与 `emit_geo`
   （纯 shapely、从 IR 造几何）不同类 —— 处理的是「已存在 `.geo` 的子集」，所以要先
   `load_geo` 一次源几何再写出块几何。放 `geo_emit.py`（按职责=上游 emitter 归类）
   还是放 `_gmsh_geo_source.py`（按依赖=需要 gmsh 归类）？spec 选前者，因为 G1 的
   契约「严格在 `load_geo` 上游」是它最重要的性质。
