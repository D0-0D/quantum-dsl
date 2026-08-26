# quantum_dsl v4 — 契约

本文是 v4 的需求契约；`tests/` 是它的**可执行形式**——每条契约（N0–N15）对应一到数条测试，
测试 docstring 首行回指编号。加需求 = 先在这里加一行、再加测试。物理依据在
[`docs/physics.md`](docs/physics.md)，语法在 [`docs/grammar.md`](docs/grammar.md)。

## 目标与边界

- **做**: native Gmsh `.geo`（OpenCASCADE, µm）+ `*.meta.yaml` sidecar → { GDS（gdstk）·
  mesh（gmsh）→ Palace 静电 → 电容矩阵 } → 拼装（共享节点 + Schur）→ 电路模型
  （逆电容 LOM: E_C/f01/α/g、SQUID、TL 谐振器 + χ、CPW 解析）→ 结果/清单落盘。
  外加: 参数化**圆角多边形** cell → `.geo`。
- **不做**（v3 舍弃项）: qiskit_metal 依赖（任何形式）、`.metal.yaml` 纯 YAML→QDesign 路径、
  emit-yaml 老库、v3 组件模板引擎（YAML 模板 DSL）。
  qubit 参数化 cell 库（transmon_pocket 等）不进本契约——以后需要时按 cells API 另立项。
- **平台**: Python ≥ 3.13。核心依赖只有 `pyyaml`/`shapely`; `gmsh`/`gdstk` 是
  optional extra, `import quantum_dsl` 不得拉起它们。

## 从 v3 继承的三样东西（其余全部重新设计）

1. **`.geo` 作者约定**: OpenCASCADE、µm、每个语义面挂一个 Physical 名
   `"<role>::<layer>::<component>::<primitive>"`, role ∈ {metal, ground, jj, substrate, port, symmetry}。
   JJ 是集总元件: 进 GDS、不进静电网格。
2. **内部单位 µm**: 几何一律 µm; mesh/Palace 边界换算 SI 由实现自理（唯一换算点 = Palace config
   `Model.L0 = 1e-6`）, GDS µm verbatim（`unit=1e-6`）。**不双重缩放**。
3. **物理 golden**（锚点与实现无关, 见测试内数值）: two_pads 实测 C 矩阵与哈密顿量
   （零厚度片配方实测, 见 `docs/physics.md` §7）、逆电容 LOM 闭式值、CPW 自洽集、非 RWA χ、
   λ/4 等效 LC、Schur 手算。**golden 不锚参考实现, 只锚物理与闭式。**

## Layer-1 词汇（`*.meta.yaml`, schema `quantum-dsl/meta/1`）

扁平词汇（v3 的 `simulation.gmsh.*` 嵌套废弃）; 全字段参考见 `docs/grammar.md` §3:

```yaml
schema: quantum-dsl/meta/1
geo: two_pads.geo                    # Layer-2 几何
materials:
  substrate: {eps_r: 11.45, thickness_um: 100}
airbox: {top_um: 120, bottom_um: 120, side_um: 80}
mesh: {max_size_um: 40, min_size_um: 4}
solver: {type: electrostatic, order: 2}      # 可选 outer_boundary: ground|open（默认 ground=接地盒; open=盒壁不挂 BC, 须版图自带 ground）
gds:
  by_role:
    metal: {layer: 1, datatype: 0}
circuit_model:
  qubits:
    - {name: A, island: A, L_J: 10nH}     # island = .geo 名的 component 段
    # 浮动（差分）transmon: islands 列表, 结桥接两岛; 结能量给 L_J 或 E_J（如 12.2GHz）二选一
    # - {name: QB1, islands: [QB1_t, QB1_b], E_J: 12.2GHz}
extract:                              # 可选: 分块
  blocks:
    - {name: A, components: [A]}
subsystems: [...]                     # 可选: 预留（v4.0 接受但不消费）
```

**绑定键 = component 段**: 电容矩阵行列标签、circuit_model 的 island、assemble 的节点名,
一律用 `.geo` Physical 名的第 3 段（同名 = 同导体; 跨块共享 = 同一 component 显式列入
多个 block 的 `components:`）。**component 段 = 电学岛（net）, 不是器件**: 浮动
transmon 的两块 pad 必须用不同 component（如 `QB1_t`/`QB1_b`）, 否则被并成同一
Terminal 即双岛短路（v3 实测 C_Σ 错 1.70×）; 器件归组在 circuit_model 的
`islands:` 列表（jj:: 的 component 保持器件名, 不进网格）。分块是 **quasi-lumped 近似**
（qiskit-metal LOM 2.0 同款, 机制同构与边界见 `docs/physics.md` §11）: 两导体要有**直接**
Maxwell 互容, 必须**在至少一次求解中共现**; 共享节点只提供网络中介路径, 共享 ground 不算耦合路径。
跨块直接互容 = 结构性零, 且不总是小量（相消型 coupler 的零耦合点对它敏感）——
切块纪律: 有意直接耦合的导体对必须同块共现。

## 公共 API（顶层扁平; 内部模块组织自由）

| 需求 | API | 测试 |
|---|---|---|
| N0 平台/纯度 | `import quantum_dsl` 轻量; py≥3.13; 无 qiskit_metal | `test_pipeline.py::test_import_is_light_and_metal_free` |
| N1 单位 | `parse_length("0.5mm")→500.0(µm)`; `parse_quantity("10nH")→1e-8(SI)` | `test_frontend.py::test_parse_length_to_um`, `::test_parse_quantity_to_si_requires_unit` |
| N2 geo 加载 | `load_geo(path) → Geo(.physicals[Physical(name,role,layer,component,primitive)], .bbox_um)` | `test_frontend.py::test_load_geo_*` |
| N3 meta 加载 | `load_meta(path) → Meta`（上表词汇; 未知顶层键 raise） | `test_frontend.py::test_load_meta_*` |
| N4 GDS | `build_gds(geo_path, meta, out) → Path`（µm verbatim, by_role 映射） | `test_pipeline.py::test_build_gds_two_pads_roundtrip` |
| N5 mesh | `build_mesh(geo_path, meta, out) → Mesh(.labels, .conductor_groups, .num_cells…)`（零厚度导体片 imprint 为边界面组; 空网格 raise） | `test_pipeline.py::test_build_mesh_two_pads` |
| N6 Palace | `palace_config(mesh, meta, out) → dict`; `parse_capacitance(postpro, labels) → Cap(.labels, .maxwell_fF, .mutual_fF)` | `test_pipeline.py::test_palace_config_shape`, `::test_parse_capacitance_verbatim_csv_and_nan_guard` |
| N7 live 解 | `build(meta, out, solve=True)`（gate `QDSL_RUN_PALACE=1`）C 对 golden <2%, f01 <3% | `test_live.py::test_two_pads_end_to_end` |
| N8 电路模型 | `solve_circuit_model(labels, maxwell_fF, junctions) → .qubits/.couplings(g, β)`（dict 入参; 浮动双岛差模约化; SQUID; nan 拒绝） | `test_physics.py::test_single_island_closed_form` 等 6 条 |
| N9 拼装 | `assemble(cells, keep) → (.labels, .maxwell_fF)`（共享节点累加 + Schur 消元） | `test_physics.py::test_assemble_*` |
| N10 CPW | `guided_wavelength(...)`/`lumped_cpw(...)`（AGM 椭圆积分; **自洽集**: Z0/λ_g 由总 L′=Lext+Lk 导出） | `test_physics.py::test_cpw_*` |
| N11 子系统 | `resonator_lumped_lc(f, Z0, mode)`; `dispersive_shift_hz(g, f_r, f01, f12)` | `test_physics.py::test_resonator_lumped_lc_half_and_quarter_wave`, `::test_dispersive_shift_golden` |
| N12 圆角 cell | `rounded_polygon(points, radius_um) → [(x,y)]`; `emit_geo(cells) → str`（load_geo 可回读） | `test_frontend.py::test_rounded_polygon_area`, `::test_emit_geo_roundtrip` |
| N13 编排 | `build(meta, out, solve=False) → {gds, mesh, config, manifest}`（manifest 带输入 sha256） | `test_pipeline.py::test_build_no_solve_artifacts_and_manifest` |
| N14 分块 | `extract.blocks` → 落盘 `block_<name>.geo`（只含该块 component）+ 各块 config; 跨块邻近告警 | `test_pipeline.py::test_extract_blocks_derived_and_scoped` |
| N15 外部物理验证 | sung 例子（PRX 11.021058）live 解: C_Σ ×3 对论文 ±8%（2026-08-25 翻案: 原 ±5% 锚的 Elmer P1 档系偏置抵消产物, 账见例子 meta 头注与 `docs/physics.md` §12）, β_qc ±20%（gate `QDSL_RUN_PALACE_SUNG=1`; 排除项见例子 meta） | `test_live.py::test_sung_2021_against_paper` |

## 验收

1. Python 3.13 下 `pytest tests/ -q` **0 failed**（live 两条默认 skip）。
2. `QDSL_RUN_PALACE=1` 下 N7 通过（Palace 0.16, WSL; ⚠ 必须 `HWLOC_COMPONENTS=-gl`）。
3. `QDSL_RUN_PALACE_SUNG=1` 下 N15 通过（整片 order 2, 18.5M 未知量, 峰值内存 ~154 G,
   须 384G 级机器; N7 锚配方可复现, N15 锚论文真值——角色互补, 都要）。
4. 全程无 qiskit_metal —— 3.13 下它根本装不上, 平台即护栏。

**v4.0（2026-08-26）: 四条全部满足。** N7 实测 123 s, C 与 golden 逐位相同; N15 2026-08-25 实测通过
（C_Σ ×0.940–0.969, β_qc +8%）。

## 参考

旧实现在 `v3` 分支——算法可搬（逆电容 LOM、Schur、AGM-K）, 但**代码逐文件审后再搬**, 禁止把
qiskit_metal 依赖或 v3 模板引擎一起拖进来。v4 的开发过程（session logs、文献取证、N15 原始数据、
原型脚本）存档在 `v4-dev` 分支 `.claude/`。
