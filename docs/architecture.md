# 架构：从版图到哈密顿量

> **本文档的定位**：给要**改代码**的人看。数据流、模块地图与依赖、把所有阶段串起来的绑定键、公共 API、
> `build()` 的产物，以及几条不写就会被再踩一遍的设计原则。物理口径与数值依据在
> [`physics.md`](physics.md)，输入文件语法在 [`grammar.md`](grammar.md)。
> 行数与 `文件:行号` 为 v4.0（2026-08-26）实测。

---

## 1. 一句话

`quantum_dsl` 把一颗超导量子芯片拆成**两层输入**——几何（native Gmsh `.geo`，**µm**）与物理参数
（`*.meta.yaml` sidecar）——一个 `build()` 调用同时产出**流片版图（GDS）**和**静电仿真网格**，
跑 **Palace** 解出 **Maxwell 电容矩阵**，再用**逆电容 LOM** 换算成 transmon 哈密顿量参数
（E_C、f01、非谐 α、耦合 g）。纯 Python，无 qiskit_metal。

## 2. 数据流

```
  examples/two_pads.geo ───────────────┐
  (几何: OCC, µm, 四段 Physical 名)     │
                                       ├──► build_gds ──► two_pads.gds          ① GDS 分叉 (µm verbatim, 旁路网格)
  examples/two_pads.meta.yaml ─────────┤
  (材料 / airbox / mesh / solver /     │
   gds.by_role / circuit_model /       ├──► build_mesh ──► two_pads.msh         ② 3D 网格 (零厚度导体片 imprint)
   extract.blocks)                     │        │
                                       │        └──► palace_config ──► two_pads.json   ③ Palace 静电 config
                                       │                    │
                                       │   solve=True ──► Palace ──► postpro/terminal-C.csv
                                       │                                  │
                                       │                    parse_capacitance ──► Cap (Maxwell fF)   ④ 电容矩阵
                                       │                                  │
                                       │   [extract.blocks: block_A.geo/.msh/.json ×N ──► assemble (共享节点累加 + Schur)]
                                       │                                  │
                                       └──► solve_circuit_model ◄─────────┘             ⑤ 逆电容 LOM
                                                    │
                                             results.yaml  {capacitance, hamiltonian: {qubits[E_C,f01,α], couplings[β,g]}}
                                             manifest.yaml {inputs/outputs sha256}
```

**读法**：左边两份文件是全部输入；①–③ 不需要 Palace，几秒完成；④⑤ 只在 `solve=True` 时发生。
`cpw` / `resonator_lumped_lc` / `dispersive_shift_hz` 是独立的解析计算器，不在这条链上（手动调用）。

## 3. 绑定键：`role::layer::component::primitive`

`.geo` 里每个语义面挂一个 Physical 名，四段用 `::` 分隔：

| 段 | 取值 | 谁消费 |
|---|---|---|
| `role` | `metal` / `ground` / `jj`（`substrate` / `port` / `symmetry` 保留，v4.0 的 mesh 不接受） | `build_mesh` 分拣：metal → Terminal，ground → 接地面，jj → 从几何删除；`gds.by_role` 映射 GDS 图层 |
| `layer` | 整数 | 只进 GDS 映射时用作分组信息 |
| **`component`** | 任意标识符 | **电学岛（net）**：电容矩阵行列标签、`circuit_model.island(s)`、`assemble` 的节点名、`extract.blocks.components` —— 全部用它 |
| `primitive` | 任意标识符（pad / cpw / …） | 仅注释性质 |

**component 段 = 电学岛，不是器件**。同名 = 同导体（多个面并成一个 Terminal）；浮动（差分）transmon 的
两块 pad 必须是不同 component（`QB1_t` / `QB1_b`），器件归组写在 meta 的 `circuit_model.qubits[].islands`。
把两块 pad 写成同一 component 会被并成一个 Terminal，等于把结短路——v3 实测这样 C_Σ 错 1.70× 而测试全绿。

C 矩阵行序 = `Mesh.labels` = `sorted(metal component)`，是全链唯一真相源（`mesh.py:47-49`）；
`palace_config` 的 `Terminal.Index`、`parse_capacitance` 的 labels、`solve_circuit_model` 的 labels 都以它对齐。

## 4. 模块地图

`src/quantum_dsl/`，14 个文件，1 950 行。顶层 API 扁平（`__init__.py` 全部再导出），内部按阶段分文件。

| 模块 | 行 | 职责 | 契约 |
|---|---|---|---|
| `errors.py` | 10 | 唯一异常 `QuantumDslError`（所有可预期失败：输入非法 / 解析失败 / 物理不适定） | N0 |
| `units.py` | 70 | `parse_length` → µm（裸数 = µm）；`parse_quantity` → SI（**必须带单位**） | N1 |
| `geo.py` | 80 | `parse_physical_name` 四段名校验；`load_geo` → `Geo(physicals, bbox_um)` | N2 |
| `_gmsh.py` | 54 | 进程级共享 gmsh session 的 `geo_model()` 上下文管理器（见 §7） | — |
| `meta.py` | 92 | `load_meta` → `Meta`；未知顶层键 raise；结参数加载时解析成数（`L_J` → H，`E_J` → Hz） | N3 |
| `gds.py` | 88 | `build_gds`：面 → gmsh 粗三角化 → gdstk 布尔并 → GDS（`unit=1e-6`，µm 逐字） | N4 |
| `mesh.py` | 286 | `build_mesh`：合成计算域、一次 `fragment` 把导体面 imprint 进 z=0 界面、边缘尺寸场、失效防线、写 msh 2.2 | N5 |
| `palace.py` | 135 | `palace_config`（`Model.L0=1e-6`，`Order=2`，Terminal 按 labels）；`parse_capacitance`（CSV 法拉 → fF，mutual 由 Maxwell 代数导出） | N6 |
| `circuit_model.py` | 423 | `solve_circuit_model` 逆电容 LOM（含浮动双岛差模约化、SQUID）；`resonator_lumped_lc`；`dispersive_shift_hz`；物理常数 | N8 N11 |
| `assemble.py` | 129 | `assemble(cells, keep)`：共享节点累加 + Schur 消元 | N9 |
| `cpw.py` | 215 | `lumped_cpw` / `guided_wavelength` / `complete_elliptic_k`（AGM），自洽公式集 | N10 |
| `cells.py` | 99 | `rounded_polygon`（shapely buffer 往返）；`emit_geo`（发射 OCC `.geo` 文本） | N12 |
| `build.py` | 223 | `build(meta, out_dir, solve)` 编排 + manifest + 分块派生 + 跑 Palace + 写 `results.yaml` | N13 N14 N7 N15 |
| `__init__.py` | 46 | 再导出；`import quantum_dsl` 不拉起 gmsh / gdstk / shapely | N0 |

### 依赖图

```
          errors ◄──────────────── 所有模块
             ▲
   units ◄── meta                         circuit_model ◄── assemble (借 _invert_matrix)
             ▲                                 ▲
   geo ◄── cells, gds, mesh                    │
    │                                          │
   _gmsh (惰性 import gmsh)                    │
             ▲                                 │
             └── gds, mesh, palace ────────────┴──► build   (唯一顶点)
   cpw  (孤立: 只被 __init__ 导出)
```

**读法**：箭头指向被依赖方。无环；`build` 是唯一编排者；`cpw` 与 `cells` 没有内部消费者。
第三方库全部在函数体内惰性 import：`gmsh`（geo / gds / mesh 经 `_gmsh`）、`gdstk`（gds）、`shapely`（cells）；
只有 `yaml` 是顶层 import。

## 5. 公共 API

| 函数 | 签名 → 返回 | 备注 |
|---|---|---|
| `parse_length(v)` | `"0.5mm"` / `5` → `500.0` / `5.0`（µm） | 裸数 = µm |
| `parse_quantity(s)` | `"10nH"` → `1e-8`（SI） | 裸数拒绝 |
| `load_geo(path)` | → `Geo(.physicals[Physical(name, role, layer, component, primitive)], .bbox_um)` | 用 gmsh 解析（fixtures 有变量/宏/Include） |
| `load_meta(path)` | → `Meta`（字段 = SPEC 词汇；`geo_path` 已相对 meta 目录解析） | |
| `build_gds(geo_path, meta, out)` | → `Path` | `gds.by_role` 是选择机制 |
| `build_mesh(geo_path, meta, out)` | → `Mesh(.path, .labels, .conductor_groups, .domain_groups, .boundary_groups, .num_cells, .num_volume_cells, .conductor_bbox_um)` | 空网格 raise |
| `palace_config(mesh, meta, out)` | → `dict`（同时写 JSON） | |
| `parse_capacitance(postpro_dir, labels)` | → `Cap(.labels, .maxwell_fF, .mutual_fF)` | NaN/Inf raise |
| `solve_circuit_model(labels, maxwell_fF, junctions)` | → `CircuitModelResult(.qubits[QubitResult], .couplings[CouplingResult])` | junction = `{name, islands:[1 或 2 个], L_J│E_J│squid}` |
| `assemble(cells, keep)` | → `AssembledMatrix(.labels, .maxwell_fF, .eliminated)` | keep 拼错 raise |
| `lumped_cpw(freq, line_width, line_gap, substrate_thickness, film_thickness, *, eps_r, loss_tangent, london_penetration_depth)` | → `CpwLumped(Lk, Lext, C, G, Z0, eps_eff, q, lambda_g)` | ⚠ 入参 **SI 米 / Hz** |
| `guided_wavelength(...)` | → `GuidedWavelength(lambda_g, eps_eff, q, Lk, Lext, C, G)` | 与 `lumped_cpw` 同一段计算 |
| `resonator_lumped_lc(f_res_hz, z0_ohm, mode)` | → `(C_r, L_r)` | `half_wave` / `quarter_wave` |
| `dispersive_shift_hz(g, f_r, f01, f12)` | → χ（单边 cavity pull，Hz） | 共振时 raise |
| `rounded_polygon(points, radius_um)` | → `[(x, y)]` | |
| `emit_geo(cells)` | → `str`（`load_geo` 可回读） | |
| `build(meta, out_dir, solve=False)` | → `{gds, mesh, config, manifest[, blocks][, capacitance, results]}` | 见 §6 |
| 常数 | `ELEM_CHARGE`, `H_PLANCK`, `HBAR`, `FLUX_QUANTUM_REDUCED` | SI-2019 |

## 6. `build()` 的产物

```
<out_dir>/
├── <stem>.gds            gds.by_role 非空时
├── <stem>.msh            msh 2.2, 坐标 µm
├── <stem>.json           Palace config (Model.Mesh 写相对文件名, cwd = 本目录)
├── manifest.yaml         {schema, inputs[{path, sha256}], outputs[{path, sha256}]}
├── block_<name>.geo/.msh/.json ×N        extract.blocks 时
├── postpro/terminal-C.csv (+ Cm/Cinv)    solve=True: Palace 输出 (SI 法拉)
└── results.yaml                          solve=True
```

`results.yaml`：

```yaml
capacitance: {labels: [A, B], maxwell_fF: [[..],[..]], mutual_fF: [[..],[..]]}
hamiltonian:
  method: lumped_oscillator_inverse_cap
  qubits:    [{name, islands, C_sigma_fF, E_C_GHz, E_J_GHz, f01_GHz, anharmonicity_MHz, EJ_over_EC}, ...]
  couplings: [{qubit_a, qubit_b, beta, g_MHz}, ...]
```

分块（`extract.blocks`）在 v4.0 里只做到**派生 + 各块 mesh/config**；把各块 Palace 结果喂给
`assemble()` 再喂 `solve_circuit_model()` 是调用方的事（`build(solve=True)` 只解整片）。

## 7. 设计原则（每条背后都有一次事故）

1. **`import quantum_dsl` 轻量**：gmsh / gdstk / shapely 只在用到的函数里 import。测试在子进程里查。
2. **内部长度一律 µm，唯一 µm→m 换算点是 Palace config 的 `Model.L0 = 1e-6`**（`palace.py:76`）。
   GDS 也 µm 逐字（`unit=1e-6`）。v3 曾用 `occ.dilate` 把模型缩放到米——那是全量几何重建，会静默损伤几何。
3. **gmsh session 进程级共享、从不 finalize**（`_gmsh.py`）：`.geo` 的 `Macro` 定义是进程级永久状态，
   `finalize` / `clear()` 清不掉它却会清掉 include-guard 变量 → 同一宏库二次解析必炸
   "Redefinition of function"。每次解析进一次性命名的新 model，用完 `remove`。代价：`gmsh.option` 全局，
   每个调用点显式设全自己依赖的选项（尤其 `Mesh.Algorithm3D`，HXT 回退后要复位）。
4. **拒绝静默**：meta 未知键 raise；`.geo` 名字不合约定 raise；未被 junction 认领的 label 禁止静默接地
   （v3 实案：静默接地把 25 MHz 中介耦合删成 0）；`assemble` 的 `keep` 拼错 raise；CSV / L_J 拒 NaN/Inf
   （`not (isfinite(v) and v > 0)`——nan 能穿过 `<= 0`）；C 求逆前先查反对称残差 `‖C−Cᵀ‖/‖C‖ > 1e-6` 即 raise，
   不靠对称化掩盖。
5. **显式而非推断**：`assemble` 用显式 `keep` 列表，不做 junction/动力学节点推断；分块 `components` 与派生几何
   的实际 metal net 不一致 raise（`build.py:179-183`）。
6. **golden 不锚参考实现，只锚物理与闭式**：N10 曾照抄 qiskit-metal 输出为 golden，把其已知错误锚成了需求，已翻案。

## 8. 与 v3 的差异

| | v3（`v3` 分支） | v4（`main`） |
|---|---|---|
| 平台 | Python 3.10 + qiskit_metal | Python ≥ 3.13，**无 qiskit_metal**（3.13 下装不上，平台即护栏） |
| 几何前端 | `.metal.yaml` → QDesign 路径 + native `.geo` 双前端 + YAML 模板引擎 | 只有 native `.geo`（+ `emit_geo` 从 Python 发射） |
| 金属表示 | 面 extrude 成 2 µm 板 → 从真空布尔减（挖空）→ ε-nudge / scale-ladder 对策 | **零厚度片 imprint**：无布尔减，共面构造性精确 |
| 单位 | 网格缩放到米，`L0 = 1` | 网格 µm，`L0 = 1e-6` |
| meta 词汇 | `simulation.gmsh.*` 嵌套 | 扁平 `quantum-dsl/meta/1` |
| 浮动 transmon | 不支持（issue #20） | 支持（`islands: [a, b]`，完整求逆取 θθ 块） |
| 电容拼装 | 推断 keep 节点 | 显式 `keep` |
| CPW | qiskit-metal 逐行（Z0/λ_g 不含 Lk） | 自洽集（Z0/λ_g 由总 L′C′ 导出） |
| 代码量 | ~9.8k 行测试 + 大量适配层 | 1 950 行 src + 5 个测试文件 |
