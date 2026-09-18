# quantum_dsl v4 — 契约

本文是 v4 的需求契约；`tests/` 是它的**可执行形式**——每条契约对应一到数条测试，
测试 docstring 首行写「契约「条目名」」回指。加需求 = 先在这里加一行、再加测试。物理依据在
[`docs/physics.md`](docs/physics.md)，语法在 [`docs/grammar.md`](docs/grammar.md)。

## 目标与边界

- **做**: native Gmsh `.geo`（OpenCASCADE, µm）+ `*.meta.yaml` sidecar → { GDS（gdstk）·
  mesh（gmsh）→ Palace 静电 → 电容矩阵 } → 拼装（共享节点 + Schur）→ 电路模型
  （逆电容 LOM: E_C/f01/α/g、SQUID、TL 谐振器 + χ、CPW 解析）→ 结果/清单落盘。
  外加: 参数化**圆角多边形** cell → `.geo`。
  **版图编排**（2026-09-12）: 模板 = 局部坐标 `.geo` + yaml 接口（岛 / 外挂面 / 蚀刻 / 结 / 端口 / 层槽位），
  实例化在 `*.layout.yaml` 有序步骤（放置 / 连接 / 手写 `.geo`）里，全部写进**同一个 gmsh 模型**；层按芯片 `layers:` 表
  重定位；路由从端口出发、定长、并 net；编排器生成 `circuit_model.qubits` / `subsystems`。设计稿 `docs/design/component-library.md`。
- **不做**（v3 舍弃项）: qiskit_metal 依赖（任何形式）、`.metal.yaml` 纯 YAML→QDesign 路径、
  emit-yaml 老库、v3 组件模板引擎（YAML 几何原语 DSL）。不发射 `.geo` 文本作模板、不 fork gmsh。
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
geo: two_pads.geo                    # Layer-2 几何 (或 layout: x.layout.yaml + layers: {m1: {kind: conductor, gds: [1, 0]}, ...}, 见 grammar §4)
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
| import 纯度（平台） | `import quantum_dsl` 轻量; py≥3.13; 无 qiskit_metal | `test_pipeline.py::test_import_is_light_and_metal_free` |
| 单位 | `parse_length("0.5mm")→500.0(µm)`; `parse_quantity("10nH")→1e-8(SI)` | `test_frontend.py::test_parse_length_to_um`, `::test_parse_quantity_to_si_requires_unit` |
| .geo 加载 | `load_geo(path) → Geo(.physicals[Physical(name,role,layer,component,primitive)], .bbox_um)` | `test_frontend.py::test_load_geo_*` |
| meta 加载 | `load_meta(path) → Meta`（上表词汇; 未知顶层键 raise） | `test_frontend.py::test_load_meta_*` |
| GDS | `build_gds(source, meta, out) → Path`（µm verbatim; source = `.geo` 路径或 Layout; 映射按 `layers` 表或 by_role） | `test_pipeline.py::test_build_gds_two_pads_roundtrip` |
| 网格 | `build_mesh(source, meta, out) → Mesh(.labels, .conductor_groups, .num_cells…)`（零厚度导体片 imprint 为边界面组; 空网格 raise） | `test_pipeline.py::test_build_mesh_two_pads` |
| Palace | `palace_config(mesh, meta, out) → dict`; `parse_capacitance(postpro, labels) → Cap(.labels, .maxwell_fF, .mutual_fF)` | `test_pipeline.py::test_palace_config_shape`, `::test_parse_capacitance_verbatim_csv_and_nan_guard` |
| two_pads 锚（live 解） | `build(meta, out, solve=True)`（gate `QDSL_RUN_PALACE=1`）C 对 golden <2%, f01 <3% | `test_live.py::test_two_pads_end_to_end` |
| 电路模型 | `solve_circuit_model(labels, maxwell_fF, junctions) → .qubits/.couplings(g, β)`（dict 入参; 浮动双岛差模约化; SQUID; nan 拒绝） | `test_physics.py::test_single_island_closed_form` 等 6 条 |
| 拼装 | `assemble(cells, keep) → (.labels, .maxwell_fF)`（共享节点累加 + Schur 消元） | `test_physics.py::test_assemble_*` |
| CPW | `guided_wavelength(...)`/`lumped_cpw(...)`（AGM 椭圆积分; **自洽集**: Z0/λ_g 由总 L′=Lext+Lk 导出） | `test_physics.py::test_cpw_*` |
| 子系统 | `resonator_lumped_lc(f, Z0, mode)`; `dispersive_shift_hz(g, f_r, f01, f12)` | `test_physics.py::test_resonator_lumped_lc_half_and_quarter_wave`, `::test_dispersive_shift_golden` |
| 圆角 cell | `rounded_polygon(points, radius_um) → [(x,y)]`; `emit_geo(cells) → str`（load_geo 可回读） | `test_frontend.py::test_rounded_polygon_area`, `::test_emit_geo_roundtrip` |
| build 编排 | `build(meta, out, solve=False) → {gds, gds_png, mesh, config, manifest}`（manifest 带输入 sha256 与全部产物；`<stem>.gds.png` = GDS 预览） | `test_pipeline.py::test_build_no_solve_artifacts_and_manifest` |
| 分块 | `extract.blocks` → 落盘 `block_<name>.geo`（只含该块 component）+ 各块 config（各自的 `postpro_block_<name>`）; 跨块邻近告警 + 块集合重叠告警; `build(blocks=[...])` 只做指定块（跳过整片网格，`solve=True` 时逐块求解并写 `block_<name>.results.yaml`，schema 同整片） | `test_pipeline.py::test_extract_blocks_derived_and_scoped`、`::test_build_blocks_only_skips_the_whole_chip` |
| sung 外部锚（外部物理验证） | sung 例子（PRX 11.021058）live 解: C_Σ ×3 对论文 ±8%（2026-08-25 翻案: 原 ±5% 锚的 Elmer P1 档系偏置抵消产物, 账见例子 meta 头注与 `docs/physics.md` §12）, β_qc ±20%（gate `QDSL_RUN_PALACE_SUNG=1`; 排除项见例子 meta） | `test_live.py::test_sung_2021_against_paper` |
| 版图编排 | `compile_layout(meta) → Layout`（可调用几何源, `.qubits/.subsystems/.ports/.inputs`）; meta `layout:`+`layers:`; 模板 `.geo`+yaml; 手写 `.geo` 步骤只增不改; 路由只接正对端口（`planner: cpw` 模板除外, 见「自动布线」）、宽度继承、定长闭合 `guided_wavelength`; 编排器纪律全部 raise（NaN 置毒含 `port(i)` 简写 / 短路 / 未认领面 / 未连接外挂面 / 外挂端口背后无面 / 全名唯一 / 层 kind / 模板子字典键与 `kind` 取值 / `if:` 指向未声明参数 / `body:` 非岛键 / 连接型的 `at:`·`rot:`·`mirror: y` / 步骤键按类型查 / 路由体与手写金属须碰到每一端 / merge 文件里的 Macro / 手写 `etch` 的 `layers:`）；手写步骤 `connect: {net: [端口]}` 认领外挂面（与连接型同一条路）；`inputs` 含 `.geo` 递归 `Include` 到的宏库 | `test_layout.py` 全部 8 条（等价性、混用 + 路由 + 地、嵌套再导出、纪律、守卫、词汇、手写 connect） |
| 自动布线 | `route.plan_cpw(start, end, R, length, region, n_legs, width, lead, axis) → [("line", …) \| ("arc", …)]`（纯 math，不拉 gmsh）：两端各先沿端口法向直走 `lead`；**骨架**默认走曼哈顿框架（横平竖直，`axis` 可转角；`axis: free` = Dubins CSC 四型），端弧 + 直 / Z / U / L / 三折模板，按（转弯数, 长度）排序，出区域的丢弃；`length` 时在骨架直段上放蛇形，**每个弯按该处余量独立外推（腿可不等长）**，余量 = 到 region 外框 / 矩形之间的缝 / 自身其它直段（净距 2R）的射线距离，腿数自动取最小可行；`region` = 矩形或**矩形并集**（外框取样点精确 + 缝的精确距离，含缝宽）；弧段 ≤ π/2、G1 连续、记账 == 目标；两口正对共线且无 region 时与 `cpw_meander` 逐段相同；装不下 / 出界 / 非法输入 raise 并逐骨架说明。模板 `lib/cpw_route`（`planner: cpw`，两口不必正对，位姿恒等，原语按列表变量注入 `.geo`）；步骤键 `region:` / `axis:`（仅 planner 模板）；`mirror:` 对 planner raise；例子 `cpw_route_demo`（三对 xmon：横平竖直 / 拼接区域绕路 / 自由角） | `test_route.py` 7 条（曼哈顿 L + 不等腿；拼接区域绕路 + 缝检查；转框架 + 自身净距 + axis 错误；自由角四型 / G1 / 记账 / lead / 精确包围盒 / raise；退化一致性；纪律；demo 三条路 + GDS 落在 region 并集内） |
| Chen 2025 模板（圆盘比特 → 3×3） | 模板 `disc_transmon`（两半盘 + 跨缝结 + 可选爪外挂面 E/N/W/S）与 `bar_coupler`（连接型: 条 + 五边形 + 结, 两端爪并入条的 net; 连接型步骤吃 `mirror:`）; 例子 `chen_2025_3x3.layout.yaml`（9 + 12 步, 21 个结条目自动生成, 载片地 = `airbox.top_um`, `extract.blocks` = 12 个 SI 口径 QCQ 块）; 几何 = `docs/design/paper-chen2025-geometry.md` 照片量出值; 对照件 `chen_2025_3x3_hand`（12 个耦合器换成一步手写 `.geo` + `connect:`, 结写在 meta, 几何逐点相同）; 十字例子 `chen_2025_cross`（中心比特 4 爪 + 4 臂比特各 1 爪 + 4 耦合器 = 18 导体 / 9 结, 整片一次解: 中心 = 真晶格口径 ↔ 实测 α, 臂 = SI §D 孤立 QCQ 口径） | `test_chen_2025.py` 4 条（几何 / 手性 / 记账一致; QCQ 块 = 6 terminal + 盒顶地; 手写 = 模板路线; 十字 = 18 导体 / 爪数 4+1×4） |

## 验收

1. Python 3.13 下 `pytest tests/ -q` **0 failed**（47 passed, live 两条默认 skip; v4.0 收口时 39, 版图编排 / Chen / 自动布线各加, 自动布线 v2 加 3）。
2. `QDSL_RUN_PALACE=1` 下 two_pads live 通过（Palace 0.16, WSL; ⚠ 必须 `HWLOC_COMPONENTS=-gl`）。
3. `QDSL_RUN_PALACE_SUNG=1` 下 sung live 通过（整片 order 2, 18.5M 未知量, 峰值内存 ~154 G,
   须 384G 级机器; two_pads 锚配方可复现, sung 锚论文真值——角色互补, 都要）。
4. 全程无 qiskit_metal —— 3.13 下它根本装不上, 平台即护栏。

**v4.0（2026-08-26）: 四条全部满足。** two_pads live 实测 123 s, C 与 golden 逐位相同; sung live 2026-08-25 实测通过
（C_Σ ×0.940–0.969, β_qc +8%）。

## 参考

旧实现在 `v3` 分支——算法可搬（逆电容 LOM、Schur、AGM-K）, 但**代码逐文件审后再搬**, 禁止把
qiskit_metal 依赖或 v3 模板引擎一起拖进来。v4 的开发过程（session logs、文献取证、sung 原始数据、
原型脚本）存档在 `v4-dev` 分支 `.claude/`。
