# 实现计划：把 `qlib.geo` 拓展成 geo 原生 QLibrary（对标 qiskit-metal 元件库）

> 配套分析见 [`qlibrary-geo-port-analysis.md`](qlibrary-geo-port-analysis.md)。本文件是**可执行的实现计划**：
> 把 `examples/dsl/geo/qlib.geo`（现有 5 个纯几何 OCC 宏）拓展成一套**有物理含义、尽可能覆盖
> qiskit-metal 元件库**的 geo 原生 cell 库，并补上 YAML 实例化层，使其经 `build_geo` 直达
> GDS + Palace 电容矩阵 + 电路模型。
>
> 遵循报告结论：**本阶段只做 T1–T3（自身几何的纯函数：qubit / lumped / coupler / termination /
> sample-shape）；T4 路由（RouteMeander 等）延后到"路由阶段"**（需 pin 注册表 + 网表 + Python 路由器）。

---

## 0. 目标与范围

- **In scope（本计划）**：静电电容矩阵阶段够用的 geo 原生元件库——参数化 OCC 宏 + YAML 实例化 +
  Physical 名绑定 + 圆角 + pin marker + 与 `circuit_model`(M6) 挂钩形成物理闭环。
- **Out of scope（延后）**：路由类（T4）、本征模/驱动求解（M4）、多层/flip-chip（M5b）。
- **不动的东西**：`load_geo` 及其下游（`carve_conductors` / `assign_physical_groups` / GDS / Gmsh /
  Palace）**完全不改**——新库只在 `load_geo` 上游生成 `.geo`，Physical 名契约字节级不变（与 emit_geo
  同一注入点）。
- **不扩 v3 YAML 模板**（`dsl_templates/`）：它不 geo 原生，保留做迁移参照。

---

## 1. 总体架构（三件套）

```
 meta.yaml (qcells: 块)                         qlib.geo (参数化 OCC 宏, 纯几何)
      │  cell_type/component/x/y/rot/layer/params      │  ROUNDED_RECT / TRANSMON_POCKET /
      ▼                                                 │  INTERDIG_CAP / TAPER_LAUNCH / ...
 ┌─────────────────────┐    查 registry     ┌───────────┴───────────┐
 │ geo cell registry   │◄──────────────────│ CellDescriptor:        │
 │ (Python 描述符)      │                    │  macro 名 + 默认参数    │
 │  = metal 的          │                    │  + surface→(role,prim) │
 │  default_options +   │                    │  + pins + island 声明   │
 │  make()→名字映射     │                    └────────────────────────┘
 └──────────┬──────────┘
            ▼
 ┌──────────────────────────┐   写出   ┌──────────────────────────────┐
 │ geo-macro Elaborator      │────────►│ <stem>.elaborated.geo         │
 │ (dsl/geo_cells.py, 新)    │          │  Include "qlib.geo";          │
 │  ground-first 编排        │          │  <参数赋值> Call <MACRO>       │
 │  + 调用点 author 物理名   │          │  Rotate/Translate{...}        │
 │  + 统一 ground 布尔差      │          │  Physical Surface("...")={...}│
 └──────────────────────────┘          └───────────────┬───────────────┘
                                                        ▼  load_geo (不改)
                                          GDS  +  Gmsh mesh → Palace → C 矩阵 → circuit_model
```

**三件套职责**：

1. **`qlib.geo` 宏（几何引擎）**= metal 的 `make()`。纯几何、写 `sret*` 全局返回、**不打** Physical 名。
   本计划给它加原语（圆角、叉指 `For` 循环、taper）和 cell 级复合宏。
2. **Python cell registry（描述符）**= metal 的 `default_options` + `make()`→qgeometry 映射。每个
   cell_type 一条 `CellDescriptor`：宏名、参数 schema/默认值、每个返回面的 `(role, primitive)`、pins、
   island 声明。
3. **geo-macro Elaborator（`dsl/geo_cells.py`）**= 把 YAML 实例 lower 成 `.geo`：ground-first 编排、
   调用宏、施加 placement、在调用点 author `Physical Surface("role::layer::comp::prim")`。

> 与现有 `emit_geo`（v3→shapely→.geo）**并列**：两者都在 `load_geo` 上游、都产 `<stem>.elaborated.geo`，
> 但本库**零 shapely**、纯 OCC 原生。

---

## 2. 关键设计决策

| # | 决策 | 理由 |
|---|---|---|
| **D1** | **Physical 名由 Elaborator 在调用点用 Python 拼好写进 `.geo`**（不在 `.geo` 里做 `StrCat`） | 沿用现有 emit_geo/qm4q 的成熟做法，规避 gmsh 版本对 Physical 名字符串表达式支持的不确定性；宏保持"纯几何、名字调用者打"的既有契约 |
| **D2** | **圆角 = `Rectangle ∪ 4×Disk`（OCC `Disk` + `BooleanUnion`），不用 shapely buffer** | 真正 geo 原生、2D/GDS/mesh 三处一致、顶点由 OCC 精确生成；避免 emit_geo 的预采样 buffer |
| **D3** | **ground-first 编排 + 统一 BooleanDifference**：先建每层一张 ground Rectangle，收集所有 cell 的 pocket/gap **工具面**，最后一次性 `BooleanDifference` 挖空 | 复刻 `qm4q_transmon_cell.geo:39-46` 的稳定模式（ground 先建、金属用高位 tag、boolean 先做完 → tag 稳定）；一次差分避免多次 cut 的 OCC 漏切 |
| **D4** | **placement：平移在 Python 传全局坐标；旋转用 geo `Rotate{}` 包住该 cell 全部返回面 + 其 ground 工具面** | 轴对齐 cell 直接给全局坐标最简；任意角度用 OCC `Rotate` 保 tag 不变；pocket 工具与金属一起转 → 挖孔位置正确 |
| **D5** | **新增 `qcells:` 顶层块，与 `cells:`（v3 桥）并存**，实例形状同（`cell_type/component/x/y/rot/layer/params`），但解析走新 registry + 新 Elaborator | 不动现有 `cells:` 测试、零回归风险；两条库可对照跑；长远可用 `source:` 判别符统一 |
| **D6** | **pin = `port::layer::comp::pin` dim-1 marker**（电容相不参与求解） | 沿用 emit_geo decision #2；为将来路由阶段占好名字与位置 |
| **D7** | **cell 声明自己的 island 物理名**，`circuit_model.qubits[].island` 直接引用 → C 矩阵 → 哈密顿量 | 让库"有物理含义"落到端到端：几何 → 电容 → 量子比特参数（闭 R1+R3） |

---

## 3. 元件目录（cell catalogue，本阶段目标）

角色缩写：M=metal（正性金属面）、G=ground carve（pocket/gap 工具）、J=jj（lumped，进 GDS 不网格化）、P=port marker。

| cell_type | 对标 metal | Tier | 角色/primitives | 关键参数（物理含义） |
|---|---|---|---|---|
| `transmon_pocket` | `TransmonPocket` | T1/T3 | M: pad_top/pad_bot(+N conn_pad+wire) · J: jj · G: pocket+每 conn CPW gap · P: 每 conn 一个 | pad_w/h, pad_gap（→C_Σ）, conn pad_w/h+cpw_w/gap（→耦合 C）, L_J（→E_J，经 circuit_model） |
| `transmon_cross` | `TransmonCross`(Xmon) | T1/T3 | M: 十字岛+4 臂 · J: jj · G: pocket+臂 gap · P: 4 | cross 臂长/宽, gap, claw 尺寸 |
| `cpw_straight` | `RouteStraight`（显式两端点） | T1 | M: 中心导体 · G: 两侧 gap · P: 2 端 | 端点(x1,y1)-(x2,y2), cpw_w, cpw_gap（→阻抗 Z0） |
| `launchpad` | `LaunchpadWirebond` | T1 | M: bondpad+taper+短 CPW · G: 对应 gap · P: 1 | pad_w/h, taper_len, lead cpw_w/gap |
| `open_to_ground` | `OpenToGround` | T1 | G: 端头开路 gap · P: 1 | cpw_w/gap, gap_len（open 端 15µm 惯例） |
| `short_to_ground` | `ShortToGround` | T1 | M: 端头与 ground 短接 · P: 1 | cpw_w |
| `interdigital_cap` | `Cap3/CapN Interdigital` | T1 | M: N 指叉指（`For` 循环）+两 bus · G: pocket · P: 2 | 指数 N, 指长/宽, 指间距（→耦合 C） |
| `coupler_tee` | `LineTee`/`CoupledLineTee` | T2 | M: 主线+支线 · G: gap · P: 3 | 主/支 cpw_w/gap, 位置 |
| `tunable_coupler` | `TunableCoupler01`/SQUID | T3 | M: 耦合岛 · J: SQUID 双结（2×JUNCTION） · G: pocket · P: 2–3 | 岛尺寸, 双结间距 |
| `sample_rect` / `sample_ngon` | Sample Shapes | T1 | M: 任意 · P: 0 | 多边形/圆角原语，供自定义 |

> `resonator`（谐振器）：**固定几何**（直/显式折线 waypoints）版归入 `cpw_straight`/新 `cpw_path`；
> **自动蛇形 + 长度匹配**属 T4，延后（见 §7）。

---

## 4. 里程碑分解

### P0 — 基础设施（先跑通一个最小 cell，端到端）
- **qlib.geo 新原语**：
  - `ROUNDED_RECT(cx,cy,w,h,r)` → `Rectangle ∪ 4×Disk`（r=0 退化为 `PAD`）。
  - `DISK(cx,cy,r)`、`TAPER(x0,y0,w0, x1,y1,w1)`（梯形，供 launchpad）。
  - `FINGERS`（`For i In {0:N-1}` 生成叉指，写 `sret_fingers[]` 面数组）。
  - 保持 `If(!Exists(_QLIB_INCLUDED))` include-guard 与"宏写 `sret`、名字调用者打"契约。
- **registry + descriptor**：新 `dsl/geo_cell_library.py`——`CellDescriptor`（frozen dataclass）+
  `GEO_CELL_REGISTRY: dict[str, CellDescriptor]`，含默认参数、surface→(role,prim)、pins、island。
- **Elaborator**：新 `dsl/geo_cells.py`——`elaborate_qcells(instances, *, chip_bbox, layer_grounds) -> str`：
  ground-first 编排（D3）、`Call` + placement（D4）、调用点 author 物理名（D1）、并置 `Include "qlib.geo"`
  （需把 `qlib.geo` 作为**包内资源**随 elaborated 文件一起可用——见 §6）。
- **schema/parser**：`schema.py` 加 `QCELL_KEYS`（复用 `CELL_KEYS` 形状）+ `GEO_META_ROOT_KEYS` 加
  `"qcells"`；`parsers/simulation.py` 加 `_parse_qcells`；`geo_build.py` 在 `cells:` 同位置分支到新
  Elaborator（`geo` 与 `qcells` 二选一/互斥校验）。
- **golden 测试骨架**：`tests/test_geo_cells.py`——先做 `sample_rect` 一个实例，断言产出的 `.geo` 与
  手写参照**字节级一致**（同 emit_geo 的 golden parity 思路）。
- **出口标准**：`build_geo(一个 sample_rect 的 meta.yaml)` → GDS + msh 成功；`import quantum_dsl` 仍不引
  gmsh/gdstk（purity）。

### P1 — 核心 cells（跑到电容矩阵 + 哈密顿量）
- 实现 `transmon_pocket`（含 N connection pads 的 `For` 生成）、`cpw_straight`、`launchpad`、
  `open_to_ground`、`short_to_ground`。
- **物理闭环**：写一个 `qcells` 版 transmon 示例 `examples/dsl/geo/qcells_transmon.meta.yaml`，其
  `circuit_model.qubits[].island` 引用 cell 的 island 物理名（D7）。
- **端到端验证**：`build_geo --run-palace` → C 矩阵 → tier-2 哈密顿量；与 `qm4q_transmon_cell.geo`
  手写基线对比（pad C 应 <2%，见 status 6/27、7/02 基线）。
- **出口标准**：transmon cell 的 C 矩阵与手写 qm4q cell 数值一致（同参数）；`two_pads` live 回归不变。

### P2 — 扩展 cells（覆盖面）
- `transmon_cross`、`interdigital_cap`（叉指 `For`）、`coupler_tee`、`tunable_coupler`(SQUID 双结)、
  `sample_ngon`。
- 一个"2 qubit + bus + 2 launchpad"的组合示例（对标 qiskit-metal 4-qubit 教程的子集），全 geo 原生。

### P3 — 打磨与文档
- 圆角全覆盖（所有金属 pad 默认 `fillet` 参数）；pin marker 全量发射并在 GDS 可视化中标注。
- 参数校验（每 cell 必填/默认/单位，registry 里声明；缺参/未知参报 `DesignDslError`）。
- `docs/report/` 增一页 **gallery**（每 cell 一图 + 参数表），对标 metal 的 qcomponents-gallery。
- 更新 `.claude/plan.md`（新里程碑）、`.claude/status.md`、写 session log。

---

## 5. 验证策略

1. **Golden 字节级 parity**：每个 cell 出一个手写参照 `.geo`，断言 Elaborator 产物逐字节一致
   （沿用 `test_geo_emit.py` 模式）。
2. **物理名契约**：断言 `load_geo` 后 `assign_physical_groups` 的名字集合 = 预期 `role::layer::comp::prim`
   集合（与 emit_geo 测试同法）。
3. **C 矩阵回归**：`two_pads` live 解不变（保护既有基线）；transmon cell 与手写 qm4q 基线 <2%。
4. **哈密顿量 sanity**：transmon cell → circuit_model → E_C/f01 落在物理合理区间（对齐 M6 golden）。
5. **纯度**：`geo_cells.py`/`geo_cell_library.py` **只依赖标准库**（不 import gmsh/gdstk/shapely）；
   `import quantum_dsl` purity 测试通过。
6. **全套**：conda `metal-env`，`$env:PYTHONPATH="src"; pytest tests/ -q` 无回归。
   ⚠ 跑 mesh/Palace 验证需 `export QDSL_MESH_ALGO3D=10`（见 status 7/02：新 gmsh 共面 PLC 失败不抛异常、
   HXT 回退问题）。

---

## 6. 文件改动清单

**新增**
- `src/quantum_dsl/dsl/geo_cell_library.py` — `CellDescriptor` + `GEO_CELL_REGISTRY`。
- `src/quantum_dsl/dsl/geo_cells.py` — `elaborate_qcells`（Elaborator，纯标准库）。
- `examples/dsl/geo/qcells_transmon.meta.yaml`（P1）、`qcells_2q_bus.meta.yaml`（P2）。
- `tests/test_geo_cells.py` — golden parity + 物理名 + purity + 端到端。

**修改**
- `examples/dsl/geo/qlib.geo` — 加 `ROUNDED_RECT/DISK/TAPER/FINGERS` + 各 cell 复合宏。
- `src/quantum_dsl/dsl/schema.py` — `QCELL_KEYS`；`GEO_META_ROOT_KEYS += {"qcells"}`。
- `src/quantum_dsl/dsl/parsers/simulation.py` — `_parse_qcells`。
- `src/quantum_dsl/dsl/geo_build.py` — 分支到 `elaborate_qcells`；`geo`/`cells`/`qcells` 互斥校验。
- `src/quantum_dsl/dsl/__init__.py` — 惰性导出。

**`qlib.geo` 分发问题**：现在它是 `examples/` 下的手写文件，靠 `Include "qlib.geo"`（相对路径）工作。
库化后 Elaborator 生成的 `.geo` 需能找到 qlib.geo → **决策**：把 `qlib.geo` 复制进包（如
`src/quantum_dsl/dsl_geo/qlib.geo`），Elaborator 生成时把它**内联**进 elaborated 文件头部，或写进
`out_dir` 再 `Include`（与 build 归档一致，见 6/30 的 `chip.manifest.yaml`）。推荐**内联**（自洽、无外部依赖）。

---

## 7. 边界、风险与未决

- **路由（T4）延后**：`RouteMeander/RoutePathfinder` 需 pin 注册表 + `routes:` 网表 + Python 路由器
  （长度匹配 / A\* 避障），本质是"读全局设计图 + 构建期算法"，不属静态 `.geo` 宏。见分析报告 §4/§6。
  → 单列"路由阶段"（与 M4 本征模同批）。
- **OCC 布尔稳定性**：叉指 / 十字 / 多 pocket 的 `BooleanUnion/Difference` 在 OCC 偶发退化
  （qm4q 已遇"neck 必须用 Rectangle 而非 CPW 面否则 union 退化成 fragment"，见 qlib.geo:134-135）。
  → golden 测试兜底 + 每 cell 单独 mesh smoke。
- **旋转 pocket 坐标**：任意角度 cell 的 ground 工具面必须和金属一起 `Rotate`，否则挖孔错位。
  → D4 已约束；测试覆盖一个 rot=90° 实例。
- **物理名唯一性**：`component` 必须跨 cell 唯一（`load_geo` 已有 duplicate guard）；Elaborator 预检并报错。
- **gmsh 版本**：metal-env(4.11.1) vs qmetal-src(4.15.2) 行为差异 + 空网格坑 → 验证统一带
  `QDSL_MESH_ALGO3D=10`（status 7/02）。
- **多岛/浮动 qubit 物理**：cell 几何可产多岛，但 tier-2 求解尚不支持浮动多岛 + bus Schur 消元
  （issue #20）——属电路模型边界，与库无关，本计划不碰。

---

## 8. 工作量与起步建议

- **P0 ≈ 0.5–1 天**（原语 + registry + elaborator 骨架 + 1 个 sample cell golden）。
- **P1 ≈ 1–2 天**（transmon + cpw + launchpad + 端到端 C 矩阵/哈密顿量对齐 qm4q 基线）。
- **P2 ≈ 1–2 天**（4–5 个扩展 cell + 组合示例）。
- **P3 ≈ 0.5–1 天**（圆角/pin/校验/gallery/journaling）。

**建议起步**：先做 **P0 + P1 的 `transmon_pocket` 一条竖切**——因为它同时踩到全部难点（多返回面、
pocket 差分、connection-pad `For` 循环、圆角、pin、island→circuit_model），一旦它端到端跑通且与手写
qm4q 基线数值一致，其余 cell 都是同模式的填充。
