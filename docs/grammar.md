# 语法参考：`.geo`、`*.meta.yaml`、`*.layout.yaml` 与模板

> **本文档的定位**：给**写版图 / 写 sidecar / 写模板**的人看的参考书。每个语法元素一段说明 + 一个最小片段，
> 不引代码行号（语法比实现稳定）。为什么这些字段是这个物理含义，见 [`physics.md`](physics.md)；
> 字段的加载 / 校验代码在 `src/quantum_dsl/meta.py`、`geo.py`、`layout.py`、`mesh.py`、`gds.py`、`palace.py`。
> 例子全部可跑：[`../examples/`](../examples/README.md)。本文对照 2026-09-16 的 `main` 逐条核过。
>
> **总纪律：拒绝静默。** 未知键、拼错的枚举值、漏赋的输出变量、没人认领的面、没人连的端口、短路、NaN——
> 一律 raise 并说明原因，从不"修"成默认值。看到报错先照错误信息改输入，不要绕。

---

## 1. 设计模型：两层输入

| 层           | 文件                                                            | 写什么                                                                                 | 不写什么                                                |
| ------------ | --------------------------------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| Layer-2 几何 | `<name>.geo`（§2）**或** `<name>.layout.yaml`（§4） | 金属图形（面）、Physical 名、可复用宏；版图 = 模板实例 + 手写`.geo` 步骤 + 路由 + 地 | 衬底、真空盒、网格尺寸——由`build_mesh` 按 meta 合成 |
| Layer-1 物理 | `<name>.meta.yaml`（§3）                                     | 材料、计算域、网格、求解器、芯片层表 / GDS 图层映射、结参数、分块                      | 任何坐标                                                |

一份 meta 引用一份几何源（`geo:` 或 `layout:` 键，**二选一**，两个都给 raise；路径相对 meta 所在目录）。多份 meta 可以指向同一份几何
（例：`two_pads.meta.yaml` 与 `two_pads_blocks.meta.yaml`）。**要在模板版图上手写微调，不是 meta 里再加 `geo:`，而是版图里加一个
`geo:` 步骤（§4.1）**——微调和模板落在同一个 gmsh 模型里，步骤顺序、增量原则、短路检查都管得到；meta 层面只认一个入口。
版图路线下编排器还会**生成**一部分 Layer-1 内容：模板里的结自动进 `circuit_model.qubits`，定长路由自动进 `subsystems`（§4.6）。

管线：几何源 → { GDS · 3D 网格 → Palace 静电 → C 矩阵 } → 逆电容 LOM → `results.yaml`。**C 矩阵的行列标签 =
Physical 名的 component 段**（= 电学岛 / net），它是全链路的绑定键。

## 2. `.geo` 作者约定

### 2.1 基本规则

- **OpenCASCADE 内核**：第一行 `SetFactory("OpenCASCADE");`。
- **单位 µm**：所有坐标就是微米，不做任何缩放（GDS 也 µm 逐字输出；唯一 µm→m 换算点是 Palace config 的 `Model.L0`）。
- 只画**金属面**（2D `Plane Surface` / `Rectangle` / `Disk` / 布尔结果）。z = 0 就是芯片表面；衬底在 z < 0，真空盒由 meta 合成。
- 每个语义面挂一个 **Physical Surface**，名字四段：

```
Physical Surface("<role>::<layer>::<component>::<primitive>") = { <面 tag> };
```

| 段            | 约束                                                                                                          | 含义                                                                                                                                                                                |
| ------------- | ------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `role`      | `metal` · `ground` · `jj`（`substrate` / `port` / `symmetry` 解析合法，但 `build_mesh` 拒绝） | metal → 静电 Terminal；ground → 接地导体面；jj → 集总元件，只进 GDS，**从静电几何中删除**                                                                                  |
| `layer`     | 非负整数，或标识符`[A-Za-z_]\w*`                                                                            | 芯片层 id。meta 有`layers:` 表时**必须在表里**，GDS 按层映射、role 须与层 kind 一致（`drawing` 层例外：任何 role 都收，只进 GDS 不进网格）；无层表时仅注释（GDS 按 role） |
| `component` | 非空                                                                                                          | **电学岛（net）**。同名 = 同导体。它是电容矩阵行列标签、`circuit_model` 的 `island(s)`、`extract.blocks.components` 的键                                                |
| `primitive` | 非空                                                                                                          | 注释性质（pad / cpw / lead …）                                                                                                                                                     |

不合约定的名字（段数 ≠ 4、role 不在集合里、layer 既非整数也非标识符、空段）在 `load_geo` 就 raise。
电容矩阵行序 = `sorted(component)`。

### 2.2 最小例子（`examples/two_pads.geo`）

```geo
SetFactory("OpenCASCADE");

padA = news;
Rectangle(padA) = { -120, -40, 0, 80, 80 };   // x[-120,-40] y[-40,40], µm
Physical Surface("metal::1::A::pad") = { padA };

padB = news;
Rectangle(padB) = { 40, -40, 0, 80, 80 };
Physical Surface("metal::1::B::pad") = { padB };
```

两个 component（A、B）→ 2×2 电容矩阵，行序 `(A, B)`。

### 2.3 浮动（差分）transmon 怎么写

结桥接两块 pad、两块都不接地时，**两块 pad 必须是不同 component**：

```geo
Physical Surface("metal::1::QB1_t::pad") = { top };
Physical Surface("metal::1::QB1_b::pad") = { bot };
Physical Surface("jj::20::QB1::junction") = { jj };   // 器件名; 不进网格, 只进 GDS
```

再在 meta 里把它们归为一个器件：`circuit_model.qubits: [{name: QB1, islands: [QB1_t, QB1_b], E_J: 12.2GHz}]`。
写成同一 component 会被并成一个 Terminal = 把结短路，C_Σ 错 1.70×（v3 实案），且没有任何报错。

### 2.4 ground 与开放边界

有片上 ground 时，用 `ground` role 挂 ground sheet（可以是布尔差挖出 CPW gap 的带孔面）：

```geo
Physical Surface("ground::1::GND::sheet") = { gnd };
```

配合 meta `solver: {outer_boundary: open}`，盒壁不挂边界条件（Palace 自然边界 ≡ ZeroCharge），电位参考由
ground sheet 提供——更接近自由空间。**没有任何 ground 的版图不能用 open**（全悬浮问题奇异，`palace_config` 会 raise），
只能用默认的接地盒。ground 面参与计算域 bbox 与边缘细化，但不是 Terminal（不占 C 矩阵行）。

### 2.5 宏库 `Include`

仓里两套宏库，都是**纯几何**：宏只建面、把 tag 写进输出变量，**Physical 名由调用点打**，同一几何宏可被任意 role 复用。

| 库                              | 宏                                                                                                              | 输出                                                         | 用在哪                                              |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ | --------------------------------------------------- |
| `examples/qlib.geo`           | `PAD` `POLY` `XMON` `CPW` `JUNCTION` `GROUND_CUTOUT`（入参是裸名全局变量 `cx, cy, w, h, x1, …`） | 面 tag →`sret`（XMON 另出 moat → `mret`）              | 手写`.geo`（sung 例子）                           |
| `examples/lib/cpw_macros.geo` | `LIB_CPW` `LIB_CPW_ARC` `LIB_CPW_MEANDER`（入参 `_lib_x1, _lib_w, …`）                                 | `_lib_s` / `_lib_faces()` / `_lib_len` / `_lib_mlen` | 模板`.geo`（`cpw_meander` / `disc_transmon`） |

```geo
Include "qlib.geo";
cx = 0; cy = 100; w = 360; h = 180;
Call PAD;
Physical Surface("metal::1::QB1_t::pad") = { sret };
```

- `Include` 相对被包含文件所在目录解析。两套库都带 include guard（`_QLIB_INCLUDED` / `_CPW_MACROS_INCLUDED`），可安全多次 Include。
- ⚠ **`Call X;` 必须独占一行**：gmsh 解析器会把同一行 `Call` 之后的语句在宏体执行前吃掉（`Call PAD; s = sret;` → "Unknown variable 'sret'"）。
- ⚠ gmsh 的 **Macro 与变量都是进程级全局**，session 从不 finalize（`_gmsh.py`）。所以：两套库不能有同名宏（`qlib` 的 `CPW` 与 `lib` 的
  `LIB_CPW` 因此分家——重名会 "Redefinition of function" 炸掉整个 session）；**自己写模板宏库请照 `LIB_` / `_lib_` 前缀**，
  裸名入参会活到后续手写步骤里，漏设一个就读到上一个实例的陈旧值而不报错。

### 2.6 `.geo` 里能写什么、不能写什么

- ✅ 变量、算式、`news`、宏（`Macro`/`Call`）、`Include`、`If`/`For`、OCC 布尔（`BooleanDifference` 等）、`Error(...)` 前置守卫、注释。
  解析用 gmsh 本体，`.geo` 的全部语法可用。
- ❌ 不要自己建衬底 / 真空盒 / 3D 体——`build_mesh` 会合成并要求"衬底恰 1 体"。
- ❌ 不要给面之外的实体挂 Physical（只读 2D Physical 组）。
- ⚠ 分块（`extract.blocks`）从手写 `.geo` 派生 `block_<name>.geo` 时只按**行**过滤 `Physical Surface("…")` 语句（`//` 注释里的不算），
  几何语句原样保留、被删名的面成孤儿由 `build_mesh` 清掉；含 `Include` 的版图分块时块文件与源同目录才可解析。
  版图路线不派生 `.geo`，直接在模型内按 component 过滤（§3.3）。

## 3. `*.meta.yaml` 字段参考

顶层只允许这 12 个键，出现别的键（typo）直接 raise：
`schema` `geo` `layout` `layers` `materials` `airbox` `mesh` `solver` `gds` `circuit_model` `extract` `subsystems`。

### 3.1 骨架（`examples/two_pads.meta.yaml`）

```yaml
schema: quantum-dsl/meta/1                    # 必填, 逐字
geo: two_pads.geo                             # 必填 (与 layout 二选一), 相对本文件目录

materials:
  substrate: {eps_r: 11.45, thickness_um: 100} # 两项都必填 (eps_r 给 Palace, thickness 给 mesh)

airbox: {top_um: 120, bottom_um: 120, side_um: 80}   # 三项必填, 从 z=0 (芯片面) 起算

mesh: {max_size_um: 40, min_size_um: 4}       # 两项必填

solver: {type: electrostatic, order: 2}       # 可选; 默认就是这两个值

gds:
  by_role:
    metal: {layer: 1, datatype: 0}             # role → GDS layer/datatype; 不写 gds 段 = 不出 GDS

circuit_model:
  qubits:
    - {name: A, island: A, L_J: 10nH}
    - {name: B, island: B, L_J: 10nH}
```

版图路线的骨架只差两处（`examples/two_pads_layout.meta.yaml`）：`geo:` 换成 `layout: two_pads.layout.yaml`，加一张
`layers:` 表；有层表时 `gds.by_role` 不再参与，GDS 图层写在层表里。

### 3.2 逐字段

| 键                                              | 类型 / 取值                                    | 必填                                  | 含义                                                                                                                                                                                                                              |
| ----------------------------------------------- | ---------------------------------------------- | ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `schema`                                      | `quantum-dsl/meta/1`                         | ✅                                    | 版本标识，其它值 raise                                                                                                                                                                                                            |
| `geo` / `layout`                            | 文件名                                         | 二选一                                | Layer-2 几何：手写`.geo`，或版图 `*.layout.yaml`（§4；`layout` 必须配 `layers`）。两个都给 raise；版图上的手写微调写成版图内的 `geo:` 步骤（§4.1），meta 不再加 `geo:`                                              |
| `layers.<id>.kind`                            | `conductor` / `junction` / `drawing`     | `layout` 时整表必填；`geo` 时可选 | 芯片层表，id 可为整数或标识符（= Physical 名第 2 段）。conductor 进静电网格（z = 0，目前唯一支持的导体平面）；junction 集总，进 GDS 不进网格；drawing 只进 GDS（任何 role 都收）。别的键（如`z_um`）raise                       |
| `layers.<id>.gds`                             | `[layer, datatype]` 或 `{layer, datatype}` | 可选                                  | 该层 → GDS 图层，datatype 默认 0。有层表时 GDS 按层映射（`gds.by_role` 被忽略）；**没给 gds 的层不进 GDS**；全表都没给 = 不出 GDS                                                                                        |
| `materials.substrate.eps_r`                   | float                                          | ✅（`palace_config`）               | 衬底相对介电常数（低温硅 11.45；蓝宝石各向异性取标量近似 ~10）                                                                                                                                                                    |
| `materials.substrate.thickness_um`            | float                                          | ✅（`build_mesh`）                  | 衬底厚度，衬底占 z ∈ [−thickness, 0]                                                                                                                                                                                            |
| `airbox.top_um`                               | float                                          | ✅                                    | 真空盒顶 z = +top。flip-chip 时就是到载片地的间隙 d（`chen_2025_3x3`: 5）                                                                                                                                                       |
| `airbox.bottom_um`                            | float                                          | ✅                                    | 真空盒底 z = −bottom（> thickness 时衬底下方留真空）                                                                                                                                                                             |
| `airbox.side_um`                              | float                                          | ✅                                    | xy 方向：导体（含 ground）包围盒每侧外扩 side；也是分块「几何邻近」告警的阈值                                                                                                                                                     |
| `mesh.max_size_um`                            | float                                          | ✅                                    | 远场单元尺寸                                                                                                                                                                                                                      |
| `mesh.min_size_um`                            | float                                          | ✅                                    | 导体边缘单元尺寸（Distance+Threshold 场，10 → 130 µm 渐变）                                                                                                                                                                     |
| `solver.type`                                 | `electrostatic`                              | 默认                                  | 只做静电                                                                                                                                                                                                                          |
| `solver.order`                                | int                                            | 默认`2`                             | Palace FEM 阶数。**2 是承重件**：同网格 order 1 偏 +7.3%（见 physics.md）                                                                                                                                                   |
| `solver.outer_boundary`                       | `ground` / `open`                          | 默认`ground`                        | `ground` = 接地屏蔽盒（盒壁 Dirichlet 0）；`open` = 盒壁不挂 BC，须有 `ground::` 面                                                                                                                                         |
| `gds.by_role.<role>.layer`                    | int                                            | 写 gds 段则必填                       | 无层表时：该 role 的所有面 → 此 GDS layer（jj 要进 GDS 就映射 jj）                                                                                                                                                               |
| `gds.by_role.<role>.datatype`                 | int                                            | 默认`0`                             |                                                                                                                                                                                                                                   |
| `circuit_model.qubits[].name`                 | str                                            | ✅                                    | 器件名（结果里的 qubit 名），唯一                                                                                                                                                                                                 |
| `circuit_model.qubits[].island` / `islands` | component 名 / 两个 component 名的列表         | 二选一                                | 接地单岛 / 浮动双岛。**每个 metal component 必须被恰好一个 qubit 认领**，否则 `solve_circuit_model` raise（未认领 = 静默接地）                                                                                            |
| `circuit_model.qubits[].L_J`                  | 带单位字串（`10nH`）                         | 三选一                                | 结电感 →`E_J = (ħ/2e)²/L_J`                                                                                                                                                                                                  |
| `circuit_model.qubits[].E_J`                  | 带单位频率（`12.2GHz`）                      | 三选一                                | 论文惯例 E_J/h；加载成 Hz，`build` 接线时 ×h                                                                                                                                                                                   |
| `circuit_model.qubits[].squid`                | `{E_J1: 46GHz, E_J2: 25GHz, flux: 0.0}`      | 三选一                                | 非对称 SQUID，`flux` = Φ/Φ₀（无量纲，默认 0），两支都必填                                                                                                                                                                    |
| `extract.blocks[]`                            | `{name: A, components: [A, ...]}`            | 可选                                  | 分块提取（§3.3）：每块只含这些 component 的 Physical 组                                                                                                                                                                          |
| `subsystems`                                  | list                                           | 可选                                  | 记账用：**原样透传**进 `results.yaml` 的 `subsystems` 段，不驱动任何计算（TL 谐振器 / χ 的计算器 `resonator_lumped_lc` / `dispersive_shift_hz` 需手动调用）。版图路线的定长路由会往这里**追加**条目（§4.6） |

版图路线下 meta 手写的 `circuit_model.qubits` 与编排器生成的合并：同名条目必须**逐字段一致**，否则 raise（要么删掉 meta 里的，要么改成一致）。

单位解析规则（`units.py`）：长度键以 `_um` 后缀命名、裸数即 µm；带量纲的量（`L_J` / `E_J*`）**必须带单位**
（`nH` `pH` `fF` `GHz` `MHz`… SI 词头 f…T），裸数 `10` 会被拒绝——裸数没有量纲。

### 3.3 分块（`examples/two_pads_blocks.meta.yaml`）

```yaml
extract:
  blocks:
    - {name: A, components: [A]}
    - {name: B, components: [B]}
```

- 默认 `build(m, out)`：整片 + 每块各出网格与 config（手写路线派生 `block_<name>.geo/.msh/.json`；版图路线不派生 `.geo`，
  `Layout.for_block` 在模型内只给块内 component 挂名，其余面成孤儿被 `build_mesh` 删掉）。每块 Palace 输出目录 `postpro_block_<name>`。
- 只要某几块：`build(m, out, blocks=["A"])` 或 `blocks="all"`——**跳过整片网格与 config**（整片可能比单块大两个数量级），
  `solve=True` 时逐块跑 Palace 并写 `block_<name>.results.yaml`（schema 与整片相同；`hamiltonian` / `subsystems` 只含全部岛都落在块内的条目）。
  块名不在 `extract.blocks` 里 raise；派生几何的 metal net 集合 ≠ `components` 也 raise（拼错名）。
- 块集合**重叠**（同一导体整块出现在多块里）会告警——那样的块只能单独读，不能 `assemble()`（会重复计入自电容）。
- 切块纪律：**有意直接耦合的导体对必须同块共现**——跨块直接互容在拼装模型里是结构性零（见 physics.md §11）。
  整片建网格时 `build()` 对"几何邻近（bbox 间距 < `airbox.side_um`）却从不共现"的导体对发 `UserWarning`；two_pads 的 A↔B 相距 80 µm 就会触发，
  `chen_2025_3x3` 的 24 条耦合器–耦合器告警属实且由设计（SI 孤立 QCQ 口径），不消音。
- ⚠ 块把块外的**一切**面都删了，包括块内导体伸向块外的爪 / 桨——对地项会系统性偏低（Chen H01 块的账见 physics.md §13）。

### 3.4 外部验证例子的 sidecar（`examples/sung_2021_device.meta.yaml`）

展示了手写路线的全部高级用法：`thickness_um: 750` 真实衬底、`outer_boundary: open` + `ground::` sheet、`jj` 进 GDS layer 20、
三个浮动 transmon（`islands` 列表）、`E_J` 用论文频率写法。文件头注是该例子"哪些量可对论文断言、哪些结构性排除"
的单一出处。flip-chip 口径的 sidecar 看 `examples/chen_2025_3x3.meta.yaml`（无片上地、`top_um` = 间隙、12 个 QCQ 块）。

## 4. 版图与模板（`*.layout.yaml`，schema `quantum-dsl/layout/1`）

`*.layout.yaml` 是**几何源**，在 meta 里以 `layout:` 顶替 `geo:`；sidecar 其余字段照旧，只是 `layers:` 表变成必填。
两个文件缺一不可：版图管几何与电学归属，meta 管物理与计算域。

**版图 = 一个 gmsh 模型。** 步骤按顺序写进同一模型：模板实例（放置型 `at/rot/mirror` 或连接型 `from/to`）、手写 `.geo`
（只增不改）、最后按 `ground:` 建地。手写 `.geo` 与模板靠 gmsh 本来就有的三条通道过界：**解析器变量**（编排器把参数、
已放置实例的端口 `Q1_RO_x/y/a/w` 放进去，`.geo` 直接当变量用；`.geo` 算出的面表 / 端口 / 长度编排器读回）、**OCC tag**、
**Physical 名**（两边各挂，累积）。设计依据：[`design/component-library.md`](design/component-library.md)。

例子：`examples/two_pads.layout.yaml`（与手写 `two_pads.geo` 逐字等价）、`examples/xmon_readout.layout.yaml`
（模板 + 手写 + 定长路由 + 平面地）、`examples/chen_2025_3x3.layout.yaml`（9 比特 + 12 耦合器阵列，flip-chip 无片上地）。
模板库 `examples/lib/`：`pad` · `xmon` · `cpw_meander`（连接型）· `cpw_route`（连接型 + 自动布线 `planner: cpw`，两口不必正对，横平竖直 / 拼接区域 / 自由角）· `disc_transmon`（多岛 + 可选外挂面）· `bar_coupler`（连接型多岛）。

### 4.1 版图文件

顶层只有四个键：`schema` `templates` `steps` `ground`。

```yaml
schema: quantum-dsl/layout/1
templates: [lib]                                   # 模板搜索目录, 相对本文件; 省略 = 本文件所在目录
steps:                                             # 非空有序表: 步骤顺序 = 依赖顺序, 引用不到的端口 / frame raise
  - {template: xmon, name: Q1, at: [0, 0], rot: 0, layers: {metal: m1, jj: jj}, E_J: 12.2GHz}   # 放置型
  - {geo: xmon_readout_launch.geo, ports: {F0: {port: f0(0), net: F0}}, etch: f0_etch()}        # 手写 .geo (只增不改)
  - {template: cpw_meander, name: R1, from: Q1.RO, to: F0, params: {R: 40, n_legs: 6, gap: 6},   # 连接型 (route: 同义)
     length: {mode: quarter_wave, f_r: 7GHz, film_nm: 200}}
ground: {sheet: {layer: m1, margin_um: 200}}       # 见下
```

模板查找：对 `templates` 里每个目录依次找 `<dir>/<name>.yaml`、`<dir>/<name>/<name>.yaml`；同名 `.geo` 放在 yaml 旁边。

**步骤键**（合法集合就这些，别的 raise）：

| 步骤键                        | 适用             | 含义                                                                                                                                                                                                                                                                                                                                                                           |
| ----------------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `template` / `route`      | 模板步骤         | 模板名（`route` 是连接型的同义写法）。`name` 必填、须是标识符、全版图唯一；它就是 component 名（多岛模板为 `<name>_<岛键>`；嵌套加父前缀 `<父>_<子>`）                                                                                                                                                                                                                 |
| `at` `rot` `mirror`     | **放置型** | 位姿：`at: [x, y]` µm（默认 `[0, 0]`）、`rot` **度**（默认 0）、`mirror: x` / `y`（先沿局部轴镜像再转）。连接型步骤写 `at` / `rot` 即 raise（位姿由两个端口给定）                                                                                                                                                                                         |
| `from` `to`               | **连接型** | 两个端口`实例.端口`（或手写步骤声明的端口名）。局部坐标原点 = from 口、+x 轴指向 to 口；两口必须同宽、同层，且各只能被连一次；**正对**是普通连接型模板的要求，`planner: cpw` 模板（`cpw_route`）不要求正对、位姿恒等（在芯片坐标里规划）。连接型只吃 `mirror: x`（模板翻到轴另一侧，如 `bar_coupler` 的五边形侧）；`mirror: y` 会翻转 from→to 轴本身，raise                                                                                                                 |
| `params`                    | 模板步骤         | 覆盖模板`params` 默认值；未知参数 raise；值必须是有限数（布尔拒绝）                                                                                                                                                                                                                                                                                                          |
| `layers`                    | 模板步骤         | 槽位 → 芯片层。省略时先取同名芯片层；没有同名且该 kind 的芯片层唯一时取它；否则 raise。kind 不兼容 raise。嵌套时值可以是父模板的槽位名                                                                                                                                                                                                                                        |
| `E_J` / `L_J` / `squid` | 模板步骤         | 模板有`junction` 时必给恰一个 → 自动进 `circuit_model.qubits`（§4.6）                                                                                                                                                                                                                                                                                                    |
| `length`                    | 连接型           | 定长：`{mode: quarter_wave \| half_wave, f_r: 7GHz, film_nm: 200}`（`cpw.guided_wavelength`：中心导体宽 = 端口宽，缝 = 模板参数 `gap`，衬底 ε 与厚度取 meta）或 `{mode: fixed, L: 900um}`（裸数 = µm）；减去两端端口等效长度 `leq` 后注入模板变量 `L`；模板须以 `outputs.length` 回报画出的长度，与目标不符 raise；记入 `subsystems`                          |
| `region`                    | 连接型（仅 `planner:` 模板） | `[x0, y0, x1, y1]` 芯片坐标矩形（µm）**或矩形列表（并集，可拼成 L / T / 回字）**：自动布线的全部原语**含缝宽**须落在并集内，否则 raise（报哪一段出外框多少 / 切进哪条缝多少）；矩形之间的缝就是障碍，L 拐角落在缝里时骨架自动绕路；模板参数 `n_legs: 0`（自动腿数）必须配它。非 planner 模板写它 raise。设计稿 [`design/auto-route.md`](design/auto-route.md) |
| `axis`                      | 连接型（仅 `planner:` 模板） | 自动布线骨架的方向框架：数值 = 曼哈顿框架角度（deg，**默认 0 = 横平竖直**，如 `axis: 45` 让全部直段走 45° / 135°）；`free` = Dubins 自由角（v1 行为，斜轴）。非 planner 模板写它 raise |
| `geo`                       | 手写步骤         | `.geo` 路径（相对版图文件；嵌套时相对模板目录）。可选 `frame: <实例全名>` 在该实例局部坐标下画；`ports:` 用输出变量声明端口（须 `net:`）；`etch:` 声明蚀刻工具面表；`layers: <芯片层 id>` 指明蚀刻面所在层（本步骤挂名的面不止一层时必填；不在层表 raise）；`connect: {<net>: [端口, …]}` 把模板画的外挂面（爪 / 桨）归入本步骤挂名的 component（下文与 §4.3） |

步骤键按步骤类型查：模板步骤写 `frame:` / `connect:`、手写步骤写 `at:` / `params:` 都 raise。

**`ground`**（省略 = `none`）：

| 写法                                            | 含义                                                                                                                                                                                                            |
| ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `none`                                        | 不建地（flip-chip：地是载片，= 接地盒顶`airbox.top_um`）。全部蚀刻工具面丢弃                                                                                                                                  |
| `{sheet: {layer: m1, margin_um: 200}}`        | 在该导体层建地：矩形 = 该层**metal** 面的 bbox ± margin（默认 0），减去该层全部蚀刻工具面（模板 `etch` + 手写 `etch:`）→ `ground::m1::GND::sheet`。层上没有 metal 面、或蚀刻把整张地吃光 → raise |
| `{sheet: [{layer: m1, …}, {layer: m2, …}]}` | 多层各建一张；没建地的层上的蚀刻面丢弃                                                                                                                                                                          |

**手写步骤的规则**：

- **增量原则**：只能加面——不 `Delete`、不对已有面做布尔。编排器快照前后已有面（质量 + 包围盒），变了就 raise。要改模板的形状，给模板加参数。
- 文件里自己打 Physical 名（§2.1 四段），层段必须是芯片层 id，role 须与层 kind 一致（drawing 层例外）；名字全版图唯一；只能给本步骤新建的面挂名，一面一组。
- 端口声明 `ports: {F0: {port: f0(0), net: F0}}` 或 `{x: …, y: …, a: …, w: …, leq: 0, net: F0}`：`net` 必须是已有面的 component 且只在一层；
  端口名是**扁平**的（不带 `实例.` 前缀），全版图唯一。
- 合并前编排器把此刻已存在的全部端口写成变量 `<实例>_<端口>_x/y/a/w`（点换下划线：`Q1.RO` → `Q1_RO_x`），手写 `.geo` 直接读。
- 每块新面必须被 Physical 名或 `etch:` 之一认领，否则 raise。
- **认领外挂面** `connect: {H00: [Q00.E, Q10.W]}`：本步骤以 `H00` 挂名的金属接在这两个端口上——端口背后的外挂面改挂 `H00`（名字变成 `metal::ta::H00::E`），端口记为已用。
  与连接型模板走同一条路：每一端都必须被 `H00` 的面真碰到（隔着缝 raise）；端口若属于某岛（如 `pad` 的 `P.E`），net 必须就是那个岛的 component（`connect: {P: [P.E]}`，手写面命名 `metal::m::P::stub`）。
  例 `chen_2025_3x3_hand.layout.yaml`：12 个 `bar_coupler` 换成一步手写 `.geo`，爪照旧由 `disc_transmon` 画，与模板路线出同一套 Physical 名与 GDS 多边形。
- **文件里不能定义 Macro**（编排器 raise）：手写步骤文件是 merge 进模型的，解析完即关闭，宏体随之失效；同进程第二次跑版图（`build()` 出 GDS / 网格 / 分块时必然发生）会在 `Call` 处炸掉 gmsh。
  宏放单独文件加 `If (!Exists(…))` 守卫，由手写文件 `Include`（gmsh 不关 Include 的文件；例 `chen_2025_3x3_bar_macros.geo`）。

### 4.2 模板文件（`lib/<name>.yaml` + `lib/<name>.geo`）

一个模板 = **同名两个文件**，放在 `templates:` 列出的目录里：`lib/<name>.yaml` + `lib/<name>.geo`，或子目录 `lib/<name>/<name>.yaml` + `.geo`。
YAML 是接口（参数、层槽位、哪些输出面是岛 / 外挂 / 蚀刻、结、端口、记账量），`.geo` 是**局部坐标**的几何。没有 `.geo` 的模板必须有 `steps:`（§4.5）。
编排器就是调用点：置毒输出变量 → 写入参数 → `merge` `.geo` → 差集拿到新面 → 按实例位姿变换 → 读回输出变量 → 层槽位映射到芯片层 → 按实例名挂 Physical。

#### 4.2.1 最小完整例子（`lib/pad.yaml` + `lib/pad.geo`）

```yaml
# pad — 矩形焊盘 (一个岛, 四个边中点端口)。几何在 pad.geo (局部坐标), 这里是接口。
schema: quantum-dsl/template/1
params: {w: 80, h: 80, gap: 0}                 # µm; gap > 0 时出蚀刻 pocket (接地芯片用)
layers: {metal: conductor}                     # 槽位 → 实例上 layers: {metal: <芯片层>} 重定位
islands: {pad: {faces: pad_faces(), layer: metal}}
etch: [{faces: pocket(), layer: metal, if: gap}]
ports: {E: port(0), N: port(1), W: port(2), S: port(3)}   # 简写 = {x: port_x(i), y: port_y(i), a: port_a(i), w: port_w(i)}
```

```geo
// pad — 矩形焊盘模板 (局部坐标, 中心在原点)。接口见 pad.yaml。
SetFactory("OpenCASCADE");
_s = news; Rectangle(_s) = { -w/2, -h/2, 0, w, h };          // 参数 w, h 由编排器写进解析器变量
pad_faces() = { _s };                                        // 输出: 面表 (yaml islands.pad.faces)
port_x() = { w/2, 0, -w/2, 0 };   port_y() = { 0, h/2, 0, -h/2 };
port_a() = { 0, Pi/2, Pi, -Pi/2 }; port_w() = { h, w, h, w };  // 输出: 端口四列表, 索引 = yaml port(i)
If (gap > 0)
  _p = news; Rectangle(_p) = { -w/2 - gap, -h/2 - gap, 0, w + 2*gap, h + 2*gap };
  pocket() = { _p };                                         // 条件输出: yaml 侧同一个开关 if: gap
EndIf
```

实例 `{template: pad, name: A, at: [-80, 0], layers: {metal: 1}}` → `metal::1::A::pad`、端口 `A.E` … `A.S`（与手写 `two_pads.geo` 逐字等价，`tests/test_layout.py` 断言）。

#### 4.2.2 YAML 接口

顶层键（别的 raise）：`schema` `kind` `planner` `params` `layers` `islands` `external` `etch` `junction` `ports` `outputs` `body` `steps`。

| 段           | 条目键                                                               | 规则                                                                                                                                                                                                                                                                                                                                      |
| ------------ | -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `schema`   | —                                                                   | `quantum-dsl/template/1`，逐字                                                                                                                                                                                                                                                                                                          |
| `kind`     | `connect`                                                          | 连接型：注入`D`（两口距离）、`w`（端口宽）、`L`（给了 `length:` 才有）；`params` **不得**同名声明这三个。放置型不写 `kind`                                                                                                                                                                                              |
| `planner`  | `cpw`                                                              | 自动布线（须 `kind: connect`）：编排器不要求两口正对、位姿恒等，用 `route.plan_cpw` 在芯片坐标里规划中心线（骨架 = 曼哈顿框架的端弧 + 直 / Z / U / L / 三折模板，或 `axis: free` 的 Dubins；定长时在骨架直段上放蛇形，每个弯按 region 外框 / 缝 / 自身直段与弧的余量独立外推（精确），腿可不等长；单段装不下时按容量比例分摊到多段，拐角处不交叉；骨架与成品都查自身净距 2R），按列表变量 `_rt_n` / `_rt_kind(k)` / `_rt_p0(k)…_rt_p4(k)` 注入（直段 x1, y1, x2, y2, 0 / 弧 cx, cy, R, a0, a1）；`params` 必须声明 `R` `n_legs` `gap` `lead`（`R` 可写 `auto` = 最大可行整数弯半径，解出的数记进 `subsystems.R_um`；`n_legs` 是总腿数，0 = 自动；`lead` = 两端各先沿端口法向直走的长度，弧从其后开始，端口面上永远是直段；0 = 关掉）；步骤可给 `region:`（矩形或并集）/ `axis:`；`mirror:` raise。样板 `lib/cpw_route`，设计稿 [`design/auto-route.md`](design/auto-route.md) |
| `params`   | 任意标识符 → 数                                                     | 默认值，必须是有限数（0/1 当开关）；实例`params:` 覆盖，未知名 raise。⚠ 别叫 `on` / `off` / `yes` / `no`（YAML 1.1 读成布尔）                                                                                                                                                                                                  |
| `layers`   | 槽位 →`conductor` / `junction` / `drawing`                    | 模板的局部层命名空间；实例上`layers:` 重定位到芯片层，kind 不符 raise                                                                                                                                                                                                                                                                   |
| `islands`  | `faces` `layer`                                                  | 面表变量 → 岛。component 名：单岛 = 实例名；多岛 =`<实例>_<岛键>`；连接型的 `body` 岛 = net 名（§4.3）。Physical 名 `metal::<层>::<component>::<岛键>`                                                                                                                                                                            |
| `external` | `faces` `layer` `if` `inst`                                  | 外挂面：模板画、电学归属由连到同名端口的路由决定（连上后 component = 路由 net，Physical 名`metal::<层>::<net>::<外挂键>`）。画了没人连 → raise。`inst` 只用于嵌套再导出（§4.5）                                                                                                                                                     |
| `etch`     | `faces` `layer` `if`                                           | **列表**；蚀刻工具面按层记账，`ground: sheet` 时减去，`none` 时丢弃                                                                                                                                                                                                                                                             |
| `junction` | `a` `b` `x1` `y1` `x2` `y2` `width` `layer`          | 前七个必填；`a` / `b` 是岛键，`b` 可为 `ground`（→ `island:` 单岛条目，否则 `islands: [a, b]` 浮动条目）；层槽位须映射到 junction 层；长度 0 或宽 ≤ 0 raise。矩形面 `jj::<层>::<实例>::jj`，只进 GDS                                                                                                                      |
| `ports`    | `port` `x` `y` `a` `w` `layer` `leq` `if` `island` | 端口。简写`"port(0)"` = `{x: port_x(0), y: port_y(0), a: port_a(0), w: port_w(0)}`，可与其它键并用 `{port: port(0), if: claw_E}`。`layer` 默认第一个声明的槽位；`leq` 默认 0。键名等于某个 `external` 键 → 外挂端口（net 待连接步骤定）；否则归 `island:` 指定的岛（默认 `body` / 单岛），多岛模板不写 `island:` raise |
| `outputs`  | 名 → 变量                                                           | 记账；`length` 参与定长闭合（连接型画出长度必须 == 注入的 `L`）                                                                                                                                                                                                                                                                       |
| `body`     | 岛键                                                                 | 连接型多岛必填：哪个岛是路由体（其 component = net 名）                                                                                                                                                                                                                                                                                   |
| `if`       | 参数名                                                               | 可选部件开关：参数非零才读该条目（`external` / `etch` / `ports` 都支持）；指向未声明的参数 raise。端口的 `if` 与其外挂面的 `if` 必须同一个参数                                                                                                                                                                                  |
| `steps`    | 子步骤表                                                             | 嵌套（§4.5）                                                                                                                                                                                                                                                                                                                             |

值可以是数字或 `.geo` 变量引用：`name`（标量）、`name(i)`（列表第 i 项）、`name()`（整个列表，给 `faces`）。

#### 4.2.3 `.geo` 侧协议

| 方向 | 变量                                                         | 谁写             | 说明                                                                                       |
| ---- | ------------------------------------------------------------ | ---------------- | ------------------------------------------------------------------------------------------ |
| 入   | `params` 各键（`w` `gap` `ro` …）                   | 编排器           | 默认值被实例`params:` 覆盖后写入解析器，`.geo` 直接当变量读                            |
| 入   | `D` `w` `L`                                            | 编排器（连接型） | 从 from 口（原点）沿 +x 到 to 口`(D, 0)`；`w` = 端口宽；`L` = 目标画出长度           |
| 出   | 面表`xxx() = { tags }`                                     | `.geo`         | yaml`faces:` 引用；只能含本次 merge 新建的面；一个岛可以是多块面（OCC 并不保证合并）     |
| 出   | `port_x()` `port_y()` `port_a()` `port_w()`          | `.geo`         | 四个平行列表，索引 = yaml`port(i)`；或任意标量（`ro_x`）。`a` 是**弧度**外法向 |
| 出   | 结端点（`jj_x1` … `jj_y2`）、记账标量（`cpw_length`） | `.geo`         | 名字任意，yaml`junction:` / `outputs:` 里指名                                          |
| 内部 | `_xxx`                                                     | `.geo`         | 临时量一律`_` 前缀——gmsh 变量是进程级全局，裸名会串到别的模板 / 手写步骤               |

规则（违反即 raise 或炸 session）：

- 首行 `SetFactory("OpenCASCADE");`；宏库 `Include "cpw_macros.geo";`（相对模板目录，include guard 保证多实例安全）。
- **不打 Physical 名**（名字由编排器按 yaml 生成）；**不定义 `Macro`**（第二次实例化 "Redefinition of function"）。
- 置毒：merge 前编排器把 yaml 引用的全部输出变量设 NaN，读回仍是 NaN → raise（漏赋值不静默）。条件输出放 `If (flag != 0) … EndIf`，yaml 对应条目挂同一个 `if: flag`。
- 前置守卫用 `Error("…", 值)`：几何自相矛盾在 gmsh 层就停（`bar_coupler` 的五边形超出条）。
- `Call X;` 独占一行（§2.5）。

#### 4.2.4 放置型全功能样板（`lib/xmon.yaml`）

```yaml
# xmon — 接地 Xmon: 十字岛 + 同形 moat (蚀刻) + 北臂端结 + 可选读出耦合桨 (外挂面 RO, 电学归读出腔)。
schema: quantum-dsl/template/1
params: {arm_w: 30, arm_L: 340, gap: 32, jj_w: 2, ro: 1, ro_gap: 20, ro_pad_w: 20, ro_pad_h: 120, ro_w: 10}
layers: {metal: conductor, jj: junction}
islands: {island: {faces: island(), layer: metal}}
external: {RO: {faces: ro_pad(), layer: metal, if: ro}}           # 由本模板画, net 由连到 RO 口的路由决定
etch:
  - {faces: moat(), layer: metal}
  - {faces: ro_pocket(), layer: metal, if: ro}
junction: {a: island, b: ground, x1: jj_x1, y1: jj_y1, x2: jj_x2, y2: jj_y2, width: jj_w, layer: jj}
ports: {RO: {x: ro_x, y: 0, a: 0, w: ro_w, if: ro}}               # 端面中点 (局部), 外法向 rad, 宽 = CPW 宽
```

`xmon.geo` 输出 `island()`（两矩形 `BooleanUnion`）、`moat()`（同形外扩 `gap`）、`jj_x1..jj_y2`（北臂端 → 地）；`If (ro != 0)` 内出 `ro_pad()`、`ro_pocket()`、`ro_x`。
实例 `{template: xmon, name: Q1, layers: {metal: m1, jj: jj}, E_J: 12.2GHz}` → `metal::m1::Q1::island`、`jj::jj::Q1::jj`、外挂面待连 `Q1.RO`；
`circuit_model.qubits` 得 `{name: Q1, island: Q1, E_J: …}`。`params: {ro: 0}` 关掉桨（无外挂面，可独立成片）。

#### 4.2.5 连接型样板（`lib/cpw_meander`、`lib/bar_coupler`）

```yaml
# cpw_meander — 端口到端口的定长蛇形 CPW (连接型: from/to 两个正对端口, 宽度继承端口)。
schema: quantum-dsl/template/1
kind: connect
params: {R: 40, n_legs: 8, gap: 6}
layers: {metal: conductor}
islands: {cpw: {faces: cpw_centre(), layer: metal}}     # 单岛 = 路由体: 与两端并成一个 net
etch: [{faces: cpw_etch(), layer: metal}]
outputs: {length: cpw_length}                           # 步骤给 length: 时必须 == 注入的 L
```

```geo
// cpw_meander — 从原点 (from 口) 沿 +x 到 (D, 0) (to 口) 的定长蛇形。注入 D, w, L; 参数 R, n_legs, gap。
SetFactory("OpenCASCADE");
Include "cpw_macros.geo";
_lib_x1 = 0; _lib_y1 = 0; _lib_x2 = D; _lib_y2 = 0; _lib_w = w;
_lib_R = R; _lib_n = n_legs; _lib_L = L;
Call LIB_CPW_MEANDER;
cpw_centre() = _lib_faces();  cpw_length = _lib_mlen;
_lib_w = w + 2*gap;
Call LIB_CPW_MEANDER;
cpw_etch() = _lib_faces();                              // 同一路径、宽 w + 2 gap 的缝工具面
```

多岛连接型（`lib/bar_coupler.yaml`）：`body:` 指明路由体，另一个岛照常 `<步骤名>_<岛键>`，结可以跨两岛：

```yaml
schema: quantum-dsl/template/1
kind: connect
params: {pent_w: 378, pent_wall: 125, pent_h: 300, pent_gap: 75, pent_off: 273, jj_w: 5}
layers: {metal: conductor, jj: junction}
body: bar
islands: {bar: {faces: bar(), layer: metal}, pent: {faces: pent(), layer: metal}}
junction: {a: bar, b: pent, x1: jj_x1, y1: jj_y1, x2: jj_x2, y2: jj_y2, width: jj_w, layer: jj}
```

步骤 `{template: bar_coupler, name: H00, from: Q00.E, to: Q10.W, …, E_J: 21.1GHz}` → 条 + 两只爪 = `H00`，五边形 = `H00_pent`，
结条目 `{name: H00, islands: [H00, H00_pent]}`。五边形画在局部 +y 侧，`mirror: x` 翻到另一侧（纵向耦合器）。

#### 4.2.6 多岛 + 可选外挂面（`lib/disc_transmon.yaml`）

```yaml
schema: quantum-dsl/template/1
params: {dia: 390, slot: 70, slot_deg: -45, jj_w: 5,
         claw_E: 1, claw_N: 1, claw_W: 1, claw_S: 1, gap: 12, claw_t: 40, claw_deg: 20, stub: 20, bar_w: 30}
layers: {metal: conductor, jj: junction}
islands: {a: {faces: half_a(), layer: metal}, b: {faces: half_b(), layer: metal}}     # component = <实例>_a / <实例>_b
external:
  E: {faces: faces_E(), layer: metal, if: claw_E}          # 爪由本模板画 (与盘共形), 电学归连上来的 bar_coupler
  N: {faces: faces_N(), layer: metal, if: claw_N}
  W: {faces: faces_W(), layer: metal, if: claw_W}
  S: {faces: faces_S(), layer: metal, if: claw_S}
junction: {a: a, b: b, x1: jj_x1, y1: jj_y1, x2: jj_x2, y2: jj_y2, width: jj_w, layer: jj}   # 浮动: islands: [<实例>_a, <实例>_b]
ports: {E: {port: port(0), if: claw_E}, N: {port: port(1), if: claw_N},
        W: {port: port(2), if: claw_W}, S: {port: port(3), if: claw_S}}                   # 与 external 同键 → 外挂端口
```

`.geo` 里 `For _k In {0:3}` 按 `_on() = { claw_E, claw_N, claw_W, claw_S }` 条件画爪，`port_*()` 四列表无条件赋值；yaml 靠同一个 `if:` 决定读哪几个。
外圈比特没邻居的方向 `params: {claw_W: 0}` 关掉，否则「画了没人连」raise。

#### 4.2.7 宏库文件（`lib/cpw_macros.geo`）

```geo
SetFactory("OpenCASCADE");
If (!Exists(_CPW_MACROS_INCLUDED))        // include guard: 每实例化一次就 Include 一次, 不能重定义
_CPW_MACROS_INCLUDED = 1;

Macro LIB_CPW                              // 入参 _lib_x1 _lib_y1 _lib_x2 _lib_y2 _lib_w → 输出 _lib_s (面), _lib_len
  ...
Return

Macro LIB_CPW_ARC                          // _lib_cx _lib_cy _lib_R _lib_a0 _lib_a1 _lib_w → _lib_s
  ...
Return

Macro LIB_CPW_MEANDER                      // _lib_x1.._lib_y2 _lib_w _lib_R _lib_n _lib_L → _lib_faces(), _lib_mlen, _lib_amp
  ...
Return
EndIf
```

- 纯几何：只建面、写输出变量，不打 Physical 名。
- **宏名 `LIB_` 前缀、入参出参 `_lib_` 前缀**：宏与变量都是进程级全局；与用户宏库（`qlib.geo` 的 `CPW`）重名会炸 session，裸名入参会把陈旧值漏给后续手写步骤。
- 自检用 `Error(...)`（`LIB_CPW_ARC` 拒绝 |Δ角| ≥ π、内径 ≤ 0）。

### 4.3 端口、路由与 net

- 端口 = 端面中点 + 外法向 + 宽 + 层 + 等效长度；谁画了那块面谁给端口。放置后端口按实例位姿变换（含镜像、旋转）。
- 路由只接端口，宽度继承，两端宽不同 raise（taper 未实现）；两口不正对用 `cpw_route`（`planner: cpw`：曼哈顿框架 / Dubins 骨架 + 逐弯精确余量蛇形（可多段分摊）的自动布线，可定长、`region:` 可拼接、`axis:` 定方向、`R: auto` 取最大可行弯半径，[`design/auto-route.md`](design/auto-route.md)）或手写 `.geo` + `connect:`，普通连接型模板（`cpw_meander` / `bar_coupler`）不正对 raise；每个端口只能被连一次。
- **路由是电连接**：路由体 + 两端外挂面并成一个 net，路由体必须真碰到每一端（外挂面或岛），隔着缝 raise。net 名：恰一个岛端 → 该岛；零岛端 → 步骤名；两个岛端 → raise
  （两块命名岛的电气合并没有唯一名，把一端改成外挂面或画成一个实例）。路由体（`body:` 岛）的 component **就是** net 名，
  模板里其它岛仍是 `<步骤名>_<岛键>`。例：`bar_coupler` 步骤 `H00` 连两只爪（外挂面）→ 条 + 两爪 = `H00`，五边形 = `H00_pent`，
  结条目 `islands: [H00, H00_pent]`；`xmon_readout` 的 `R1` 从桨（外挂）到手写焊盘 `F0`（岛）→ 桨 + 蛇形 + 焊盘 = `F0`。
- 手写步骤也能接：`connect: {net: [端口…]}`（§4.1）把外挂面归入手写挂名的 net，net 名就是 Physical 名的 component 段。
- 不同 net 的导体面同层相交 / 相切（距离 ≤ 1e-6 µm）= 短路 → raise（缺蚀刻或缝）。同 net 重叠放行。
- 每块面必须被岛 / 外挂 / 蚀刻 / 结 / 手写 Physical 名之一认领，否则 raise；外挂面没人连也 raise。
- 端口表 `Layout.ports` 的键：模板端口 `实例全名.端口`（如 `Q1.RO`、嵌套的 `P_L.E`），手写端口就是声明名（`F0`）。

### 4.4 生成的 Physical 名一览

| 来源             | 名字                                                                                           |
| ---------------- | ---------------------------------------------------------------------------------------------- |
| 模板岛           | `metal::<芯片层>::<component>::<岛键>`（`metal::ta::Q00_a::a`、`metal::m1::Q1::island`） |
| 外挂面（连上后） | `metal::<芯片层>::<net>::<外挂键>`（`metal::ta::H00::E`、`metal::m1::F0::RO`）           |
| 路由体           | `metal::<芯片层>::<net>::<岛键>`（`metal::ta::H00::bar`、`metal::m1::F0::cpw`）          |
| 结               | `jj::<芯片层>::<实例全名>::jj`                                                               |
| 地               | `ground::<芯片层>::GND::sheet`                                                               |
| 手写步骤         | 文件里写的原样                                                                                 |

全名唯一；编排器生成的名与手写的撞名 raise。分块 `for_block(components)` 只给 `components` 里的 component 挂名。

### 4.5 嵌套模板与再导出

模板可以没有 `.geo`、只由 `steps:` 组成（子步骤语法同 §4.1，`templates` 搜索路径 = 模板所在目录 + 父级搜索路径）。
子实例名 = `<父>_<子>`，子步骤的 `layers:` 值可以写父模板的槽位名（经父映射到芯片层）。**无 `.geo` 的父模板**可以再导出：

```yaml
schema: quantum-dsl/template/1
layers: {metal: conductor}
steps:
  - {template: pad, name: L, at: [-100, 0], params: {w: 40, h: 20}}
  - {template: pad, name: R, at: [100, 0],  params: {w: 40, h: 20}, mirror: x}
ports: {E: R.E, W: L.W}            # 子端口 P_R.E 改名为 P.E (原名不再可用)
external: {C: {inst: R}}           # 子实例 R 的岛面变成父的外挂面 (等人来连); 其端口随之变外挂端口
```

顶层 `{template: pair, name: P, at: [0, 0], rot: 90}` 后：`P.E` 可作路由端点，未再导出的 `P_L.E` 仍按子实例名可寻址，
component 为 `P_L`（`metal::<层>::P_L::pad`）。带 `.geo` 的模板也能加 `steps:`（`.geo` 先、子步骤后），但不支持点号 / `inst` 再导出。

### 4.6 编排器生成的记账（`compile_layout(meta)` → `Layout`）

| 属性                      | 内容                                                                                                                                                                                                                                                            |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `qubits`                | 每个带`junction` 的实例一条：`{name: <实例全名>, island: <comp>}` 或 `{islands: [a, b]}`，加 `E_J`（Hz）/ `L_J`（H）/ `squid: {E_J1, E_J2, flux}`。`build()` 与 meta 手写条目合并（同名须一致）                                                   |
| `subsystems`            | 每条`length:` 路由一条：`{name: <net>, route: <步骤名>, kind: cpw_resonator, mode, width_um, length_total_um, equiv_length_um, length_drawn_um}`，波长模式另有 `f_r_hz, lambda_g_um, gap_um, film_nm`。追加到 meta `subsystems` 后写进 `results.yaml` |
| `ports`                 | 全部端口（§4.3），已连接的带`net`                                                                                                                                                                                                                            |
| `inputs`                | 版图 + 用到的模板 yaml /`.geo` + 手写 `.geo` + 它们递归 `Include` 的宏库，全部进 manifest（改宏库即改哈希）                                                                                                                                               |
| `for_block(components)` | 分块视图（§3.3）                                                                                                                                                                                                                                               |

`Layout` 本身是可调用几何源，`load_geo` / `build_gds` / `build_mesh` / `build` 直接吃它；公共 API 见 [`architecture.md`](architecture.md)。

## 5. 常见坑

1. **浮动 pad 写成同一 component** → 结被短路，C_Σ 错 1.7×，无报错。写成 `X_t` / `X_b`，meta 里 `islands: [X_t, X_b]`（模板路线自动做对）。
2. **`L_J: 10`（无单位）** → raise。写 `10nH`。
3. **`open` 边界但没有 `ground::` 面** → `palace_config` raise（全悬浮问题奇异）。加 ground sheet 或用默认接地盒。
4. **meta / 版图 / 模板键拼错**（`meshh`、`iff`、`connnect`）→ raise 并列出合法键。模板子条目的键也查。
5. **`airbox.side_um` 太小**：导体贴近盒壁会过耦合（旧仓实测 connector +13–17%）；盒壁离导体至少缝宽的几十倍。
   two_pads 的 80 µm 是刻意小型化的回归件，不是推荐值。
6. **报单网格数字**：复杂几何单网格带百分位级不确定度，报数前做两档网格（如 40/4 与 20/2）看相对变化。
7. **`.geo` 注释里写示例 Physical 名**：可以（分块派生跳过 `//` 注释），但不要写成未注释的语句。
8. **JJ 画成 metal**：会当导体桥把两块 pad 短路。role 用 `jj`（自动从静电几何删除）。
9. **版图里两块金属挨上了**（pad 直接落在地上、忘了 `gap` / 蚀刻）→ 编排器报 short。给模板 `gap` 参数或加 `etch`。
10. **模板或手写步骤 `.geo` 里定义 Macro** → 编排器 raise（merge 的文件关掉后宏体失效，同进程第二次跑会炸 gmsh；没有守卫则 "Redefinition of function"）。宏放 include-guard 库并 `Include`，名字加 `LIB_` / `_lib_` 前缀（§2.5）。
11. **`Call X;` 后面同一行接语句** → "Unknown variable"。`Call` 独占一行。
12. **YAML 1.1 布尔**：`on` / `off` / `yes` / `no` 会被读成 `True` / `False`——别拿它们当参数名或槽位名；数值参数写 `1` / `0`。
13. **连接型步骤写 `at:` / `rot:` / `mirror: y`** → raise；位姿由两个端口决定，只有 `mirror: x` 有意义。
14. **`templates:` 漏了 `lib`** → "template 'xmon' not found"；路径相对版图文件。
15. **`if:` 指向的参数没在 `params` 里声明** → raise（不是"关闭"）。端口与外挂面的 `if` 要同一个参数。
16. **画了爪 / 桨却没人连**（`disc_transmon` 外圈比特、`xmon` 没接读出）→ "nothing connects"。用 `params: {claw_W: 0}` / `{ro: 0}` 关掉。
17. **只想跑一块却调 `build(m, out)`** → 先给整片出网格（Chen 整片 ~9M tets）。用 `build(m, out, blocks=["H01"])`。
18. **接了端口却没碰到**（手写 `connect:` 的条差几 µm 够不到爪、模板路由体没画到 from 口）→ "not touched by" / "does not touch island"。之前会把悬空的爪静默记进 net。
