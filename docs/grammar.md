# 语法参考：`.geo` 与 `*.meta.yaml`

> **本文档的定位**：给**写版图 / 写 sidecar** 的人看的参考书。每个语法元素一段说明 + 一个最小片段，
> 不引代码行号（语法比实现稳定）。为什么这些字段是这个物理含义，见 [`physics.md`](physics.md)；
> 字段的加载/校验代码在 `src/quantum_dsl/meta.py`、`geo.py`、`mesh.py`、`palace.py`。
> 例子全部可跑：[`../examples/`](../examples/README.md)。

---

## 1. 设计模型：两层输入

| 层 | 文件 | 写什么 | 不写什么 |
|---|---|---|---|
| Layer-2 几何 | `<name>.geo` | 金属图形（面）、Physical 名、可复用宏 | 衬底、真空盒、网格尺寸——由 `build_mesh` 按 meta 合成 |
| Layer-1 物理 | `<name>.meta.yaml` | 材料、计算域、网格、求解器、GDS 图层映射、结参数、分块 | 任何坐标 |

一份 meta 引用一份 geo（`geo:` 键，相对 meta 所在目录）。多份 meta 可以指向同一份 geo（例：
`two_pads.meta.yaml` 与 `two_pads_blocks.meta.yaml`）。

## 2. `.geo` 作者约定

### 2.1 基本规则

- **OpenCASCADE 内核**：第一行 `SetFactory("OpenCASCADE");`。
- **单位 µm**：所有坐标就是微米，不做任何缩放（GDS 也 µm 逐字输出）。
- 只画**金属面**（2D `Plane Surface` / `Rectangle` / 布尔结果）。z = 0 就是芯片表面；衬底在 z < 0，真空盒由 meta 合成。
- 每个语义面挂一个 **Physical Surface**，名字四段：

```
Physical Surface("<role>::<layer>::<component>::<primitive>") = { <面 tag> };
```

| 段 | 约束 | 含义 |
|---|---|---|
| `role` | `metal` · `ground` · `jj`（`substrate` / `port` / `symmetry` 语法合法，但 v4.0 的 `build_mesh` 不接受） | metal → 静电 Terminal；ground → 接地导体面；jj → 集总元件，只进 GDS，**从静电几何中删除** |
| `layer` | 整数 | 图层分组信息（GDS 映射按 role 走，layer 段仅注释） |
| `component` | 非空标识符 | **电学岛（net）**。同名 = 同导体。它是电容矩阵行列标签、`circuit_model` 的 `island(s)`、`extract.blocks.components` 的键 |
| `primitive` | 非空标识符 | 注释性质（pad / cpw / lead …） |

不合约定的名字（段数 ≠ 4、role 不在集合里、layer 不是整数、空段）在 `load_geo` 就 raise。

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

两个 component（A、B）→ 2×2 电容矩阵，行序 `sorted(component)` = `(A, B)`。

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
只能用默认的接地盒。

### 2.5 宏库 `Include`

`examples/qlib.geo` 提供纯几何宏（`PAD` / `CPW` / `JUNCTION` / `GROUND_CUTOUT`），调用后把面 tag 写进全局变量 `sret`，
**Physical 名由调用点打**，同一几何宏可被任意 role 复用：

```geo
Include "qlib.geo";
cx = 0; cy = 100; w = 360; h = 180;
Call PAD;
Physical Surface("metal::1::QB1_t::pad") = { sret };
```

`Include` 相对被包含文件所在目录解析；宏库带 include guard（`_QLIB_INCLUDED`），可安全多次 Include。

### 2.6 `.geo` 里能写什么、不能写什么

- ✅ 变量、算式、`news`、宏（`Macro`/`Call`）、`Include`、OCC 布尔（`BooleanDifference` 等）、注释。
  解析用 gmsh 本体，`.geo` 的全部语法可用。
- ❌ 不要自己建衬底 / 真空盒 / 3D 体——`build_mesh` 会合成并要求"衬底恰 1 体"。
- ❌ 不要给面之外的实体挂 Physical（v4.0 只读 2D Physical 组）。
- ⚠ 分块（`extract.blocks`）派生 `block_<name>.geo` 时只按**行**过滤 `Physical Surface("…")` 语句（`//` 注释里的不算），
  几何语句原样保留；含 `Include` 的版图分块时块文件与源同目录才可解析。

## 3. `*.meta.yaml` 字段参考

顶层只允许这 10 个键，出现别的键（typo）直接 raise：
`schema` `geo` `materials` `airbox` `mesh` `solver` `gds` `circuit_model` `extract` `subsystems`。

### 3.1 骨架（`examples/two_pads.meta.yaml`）

```yaml
schema: quantum-dsl/meta/1                    # 必填, 逐字
geo: two_pads.geo                             # 必填, 相对本文件目录

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

### 3.2 逐字段

| 键 | 类型 / 取值 | 必填 | 含义 |
|---|---|---|---|
| `schema` | `quantum-dsl/meta/1` | ✅ | 版本标识，其它值 raise |
| `geo` | 文件名 | ✅ | Layer-2 几何，相对 meta 目录 |
| `materials.substrate.eps_r` | float | ✅（`palace_config`） | 衬底相对介电常数（低温硅 11.45） |
| `materials.substrate.thickness_um` | float | ✅（`build_mesh`） | 衬底厚度，衬底占 z ∈ [−thickness, 0] |
| `airbox.top_um` | float | ✅ | 真空盒顶 z = +top |
| `airbox.bottom_um` | float | ✅ | 真空盒底 z = −bottom（> thickness 时衬底下方留真空） |
| `airbox.side_um` | float | ✅ | xy 方向：导体（含 ground）包围盒每侧外扩 side |
| `mesh.max_size_um` | float | ✅ | 远场单元尺寸 |
| `mesh.min_size_um` | float | ✅ | 导体边缘单元尺寸（Distance+Threshold 场，10 → 130 µm 渐变） |
| `solver.type` | `electrostatic` | 默认 | v4.0 只做静电 |
| `solver.order` | int | 默认 `2` | Palace FEM 阶数。**2 是承重件**：同网格 order 1 偏 +7.3%（见 physics.md） |
| `solver.outer_boundary` | `ground` / `open` | 默认 `ground` | `ground` = 接地屏蔽盒（盒壁 Dirichlet 0）；`open` = 盒壁不挂 BC，须有 `ground::` 面 |
| `gds.by_role.<role>.layer` | int | 写 gds 段则必填 | 该 role 的所有面 → 此 GDS layer |
| `gds.by_role.<role>.datatype` | int | 默认 `0` | |
| `circuit_model.qubits[].name` | str | ✅ | 器件名（结果里的 qubit 名） |
| `circuit_model.qubits[].island` / `islands` | component 名 / 两个 component 名的列表 | 二选一 | 接地单岛 / 浮动双岛。**每个 metal component 必须被恰好一个 qubit 认领**，否则 `solve_circuit_model` raise |
| `circuit_model.qubits[].L_J` | 带单位字串（`10nH`） | 三选一 | 结电感 → `E_J = (ħ/2e)²/L_J` |
| `circuit_model.qubits[].E_J` | 带单位频率（`12.2GHz`） | 三选一 | 论文惯例 E_J/h；加载成 Hz，`build` 接线时 ×h |
| `circuit_model.qubits[].squid` | `{E_J1: 46GHz, E_J2: 25GHz, flux: 0.0}` | 三选一 | 非对称 SQUID，`flux` = Φ/Φ₀（无量纲，默认 0） |
| `extract.blocks[]` | `{name: A, components: [A, ...]}` | 可选 | 分块提取：派生 `block_<name>.geo` 只含这些 component 的 Physical 组 |
| `subsystems` | list | 可选 | v4.0 **接受但不消费**（预留给 TL 谐振器等；对应计算器 `resonator_lumped_lc` / `dispersive_shift_hz` 需手动调用） |

单位解析规则（`units.py`）：长度键以 `_um` 后缀命名、裸数即 µm；带量纲的量（`L_J` / `E_J*`）**必须带单位**
（`nH` `pH` `fF` `GHz` `MHz`… SI 词头 f…T），裸数 `10` 会被拒绝——裸数没有量纲。

### 3.3 分块例子（`examples/two_pads_blocks.meta.yaml`）

```yaml
extract:
  blocks:
    - {name: A, components: [A]}
    - {name: B, components: [B]}
```

产出 `block_A.geo/.msh/.json`、`block_B.*`。切块纪律：**有意直接耦合的导体对必须同块共现**——跨块直接互容
在拼装模型里是结构性零（不是小量，见 physics.md「分块拼装」）。`build()` 对"几何邻近（bbox 间距 < `airbox.side_um`）
却从不共现"的导体对发 `UserWarning`；本例 A↔B 相距 80 µm 就会触发。

### 3.4 外部验证例子的 sidecar（`examples/sung_2021_device.meta.yaml`）

展示了全部高级用法：`thickness_um: 750` 真实衬底、`outer_boundary: open` + `ground::` sheet、`jj` 进 GDS layer 20、
三个浮动 transmon（`islands` 列表）、`E_J` 用论文频率写法。文件头注是该例子"哪些量可对论文断言、哪些结构性排除"
的单一出处。

## 4. 常见坑

1. **浮动 pad 写成同一 component** → 结被短路，C_Σ 错 1.7×，无报错。写成 `X_t` / `X_b`，meta 里 `islands: [X_t, X_b]`。
2. **`L_J: 10`（无单位）** → raise。写 `10nH`。
3. **`open` 边界但没有 `ground::` 面** → `palace_config` raise（全悬浮问题奇异）。加 ground sheet 或用默认接地盒。
4. **meta 键拼错**（`meshh`）→ raise 并列出合法键。
5. **`airbox.side_um` 太小**：导体贴近盒壁会过耦合（旧仓实测 connector +13–17%）；盒壁离导体至少缝宽的几十倍。
   two_pads 的 80 µm 是刻意小型化的回归件，不是推荐值。
6. **报单网格数字**：复杂几何单网格带百分位级不确定度，报数前做两档网格（如 40/4 与 20/2）看相对变化。
7. **`.geo` 注释里写示例 Physical 名**：可以（分块派生跳过 `//` 注释），但不要写成未注释的语句。
8. **JJ 画成 metal**：会当导体桥把两块 pad 短路。role 用 `jj`（自动从静电几何删除）。
