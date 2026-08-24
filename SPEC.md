# quantum_dsl v4 — 契约

超导量子芯片版图 DSL 的 greenfield 重写。**从空白开始**;`tests/test_spec.py` 是本契约的
**可执行形式**——每个测试 = 一条待实现需求,全部翻绿 + gated live 解通过 = v4 完成。

## 目标与边界

- **做**: native Gmsh `.geo`(OpenCASCADE, µm)+ `*.meta.yaml` sidecar → { GDS(gdstk)·
  mesh(gmsh)→ Palace 静电 → 电容矩阵 } → 拼装(共享节点 + Schur)→ 电路模型
  (逆电容 LOM: E_C/f01/α/g、SQUID、TL 谐振器 + χ、CPW 解析)→ 结果/清单落盘。
  外加:参数化**圆角多边形** cell → `.geo`。
- **不做**(v3 舍弃项): qiskit_metal 依赖(任何形式)、`.metal.yaml` 纯 YAML→QDesign 路径、
  emit-yaml 老库(`build_design`/`export_ir_to_metal`)、v3 组件模板引擎(YAML 模板 DSL)。
  qubit 参数化 cell 库(transmon_pocket 等)不进本契约——以后需要时按新 cells API 另立项。
- **平台**: Python ≥ 3.13。核心依赖只有 `pyyaml`/`shapely`/`numpy`;`gmsh`/`gdstk` 是
  optional extra,`import quantum_dsl` 不得拉起它们。

## 从 v3 继承的三样东西(其余全部重新设计)

1. **`.geo` 作者约定**(不变,fixtures 直接复用): OpenCASCADE、µm、每个语义面挂一个
   Physical 名 `"<role>::<layer>::<component>::<primitive>"`,role ∈
   {metal, ground, jj, substrate, port, symmetry}。JJ 是集总元件: 进 GDS、不进静电网格。
2. **内部单位 µm**: 几何一律 µm;mesh/Palace 边界换算 SI 由实现自理,GDS µm verbatim
   (`unit=1e-6`)。**不双重缩放**。
3. **物理 golden**(锚点与实现无关, 见测试内数值): two_pads 实测 C 矩阵与哈密顿量
   (2026-08-24 起为 v4 零厚度片配方实测, 见 `.claude/physics-pipeline.md` §7)、
   逆电容 LOM 闭式值、CPW 参考值、Koch(3.9)/(3.10) χ、λ/4 等效 LC、Schur 手算。

## Layer-1 词汇(`*.meta.yaml`, schema `quantum-dsl/meta/1`)

新词汇, 扁平化(v3 的 `simulation.gmsh.*` 嵌套废弃):

```yaml
schema: quantum-dsl/meta/1
geo: two_pads.geo                    # Layer-2 几何(除非有 extract 或 cells)
materials:
  substrate: {eps_r: 11.45, thickness_um: 100}
airbox: {top_um: 120, bottom_um: 120, side_um: 80}
mesh: {max_size_um: 40, min_size_um: 4}
solver: {type: electrostatic, order: 2}
gds:
  by_role:
    metal: {layer: 1, datatype: 0}
circuit_model:
  qubits:
    - {name: A, island: A, L_J: 10nH}     # island = .geo 名的 component 段
extract:                              # 可选: 分块
  blocks:
    - {name: A, components: [A]}
subsystems: [...]                     # 可选: TL_RESONATOR 等
```

**绑定键 = component 段**: 电容矩阵行列标签、circuit_model 的 island、assemble 的节点名,
一律用 `.geo` Physical 名的第 3 段(同名 = 同导体; 跨块共享 = 同一 component 显式列入
多个 block 的 `components:`)。分块是 **quasi-lumped 近似**(qiskit-metal LOM 2.0 同款,
机制同构证据见 `.claude/assemble-lit-survey.md`): 两导体要有**直接** Maxwell 互容,
必须**在至少一次求解中共现**; 共享节点只提供网络中介路径, 共享 ground 不算耦合路径。
跨块直接互容 = 结构性零, 且不总是小量(相消型 coupler 的零耦合点对它敏感)——
切块纪律: 有意直接耦合的导体对必须同块共现。

## 公共 API(顶层扁平; 内部模块组织自由)

| 需求          | API                                                                                                                 | 测试类                 |
| ------------- | ------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| N0 平台/纯度  | `import quantum_dsl` 轻量; py≥3.13; 无 qiskit_metal                                                              | `TestN0Platform`     |
| N1 单位       | `parse_length("0.5mm")→500.0(µm)`; `parse_quantity("10nH")→1e-8(SI)`                                         | `TestN1Units`        |
| N2 geo 加载   | `load_geo(path) → Geo(.physicals[Physical(name,role,layer,component,primitive)], .bbox_um)`                      | `TestN2LoadGeo`      |
| N3 meta 加载  | `load_meta(path) → Meta`(上表词汇; 未知顶层键 raise)                                                             | `TestN3LoadMeta`     |
| N4 GDS        | `build_gds(geo_path, meta, out) → Path`(µm verbatim, by_role 映射)                                              | `TestN4Gds`          |
| N5 mesh       | `build_mesh(geo_path, meta, out) → Mesh(.groups, .num_cells)`(零厚度导体片 imprint 为边界面组; 空网格 raise)     | `TestN5Mesh`         |
| N6 Palace     | `palace_config(mesh, meta, out) → dict`; `parse_capacitance(postpro) → Cap(.labels, .maxwell_fF, .mutual_fF)` | `TestN6Palace`       |
| N7 live 解    | `build(meta, out, solve=True)`(gate `QDSL_RUN_PALACE=1`)C 对 golden <2%                                         | `TestN7Live`         |
| N8 电路模型   | `solve_circuit_model(labels, maxwell_fF, junctions) → .qubits/.couplings`(dict 入参; SQUID; nan 拒绝)            | `TestN8CircuitModel` |
| N9 拼装       | `assemble(cells, keep) → (.labels, .maxwell_fF)`(共享节点累加 + Schur 消元)                                      | `TestN9Assemble`     |
| N10 CPW       | `guided_wavelength(...)`/`lumped_cpw(...)`(AGM 椭圆积分, 含动力学电感)                                          | `TestN10Cpw`         |
| N11 子系统    | `resonator_lumped_lc(f, Z0, mode)`; `dispersive_shift_hz(g, f_r, f01, f12)`                                     | `TestN11Subsystems`  |
| N12 圆角 cell | `rounded_polygon(points, radius_um) → [(x,y)]`; `emit_geo(cells) → str`(load_geo 可回读)                      | `TestN12Cells`       |
| N13 编排      | `build(meta, out, solve=False) → {gds, mesh, config, manifest}`(manifest 带输入 sha256)                          | `TestN13Build`       |
| N14 分块      | `extract.blocks` → 落盘 `block_<name>.geo`(只含该块 component)+ 各块 config                                    | `TestN14Extract`     |

## 验收

1. `qdsl313` env(Python 3.13)下 `pytest tests/ -q` **0 failed**(live 两条默认 skip)。
2. `QDSL_RUN_PALACE=1` 下 N7 两条通过(Palace 0.16, WSL;⚠ 必须 `HWLOC_COMPONENTS=-gl`)。
3. 全程无 qiskit_metal —— 3.13 下它根本装不上, 平台即护栏。

## 参考

旧实现在主 worktree `~/quantum_dsl`(main)—— 算法可搬(逆电容 LOM、Schur、AGM-K、
carve/fragment 的坑都趟过), 但**代码逐文件审后再搬**, 禁止把 qiskit_metal 依赖或
v3 模板引擎一起拖进来。坑清单见旧仓 `.claude/status.md` 的「已了结, 别重新踩」表
(hwloc/MPI 挂死、OCC 共面布尔、ε-nudge、fragment shape-heal 等)。
