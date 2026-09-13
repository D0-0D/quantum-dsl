# 元件库设计（框架稿 v3.1）：一个 gmsh 模型，`.geo` 与模板混用，层按映射重定位

> 只讲框架与规则，不讲实现拆分与测试。v3 → v3.1：模板默认形态改为「`.geo` + YAML」；新增层与工艺栈一节；
> 把一轮全面审视得到的规则写进 §1.4 / §1.6 / §1.7。每个机制都有探针实证（§4.4，scratchpad `probe2/`，未进仓）。
> Chen 2025 的几何与验证锚在 [`paper-chen2025-geometry.md`](paper-chen2025-geometry.md)（B 报告），本文只在 §3 说它怎么落进框架。2026-09-12。

> **落地状态（2026-09-12 晚）**：框架已实现为 `src/quantum_dsl/layout.py`（契约 N16，`tests/test_layout.py` 6 条；用户语法见
> [`grammar.md` §4](../grammar.md)）。首批模板 `examples/lib/`（`pad` / `xmon` / `cpw_meander` + `cpw_macros.geo`），例子
> `two_pads.layout.yaml`（与手写逐字等价）与 `xmon_readout.layout.yaml`（模板 + 手写 + 定长路由 + 地）。与本稿的实现偏差 / 收窄：
> ① 模板 `layers:` 写成 `slot: kind`（不是 `{kind: …}`）；② 连接型模板注入 `D` / `w` / `L` 三个保留变量，多岛时用 `body:` 指明路由体，
> 端口默认归 `body` 岛（多岛加 `island:`）；③ 省略层映射时先取同名芯片层，再取该 kind 唯一的芯片层，否则 raise；④ 手写步骤的
> 蚀刻用 `etch: <面表变量>`，端口用 `ports: {名: {port: f(0), net: <component>}}`；⑤ 单岛模板 component = 实例名，多岛 `<实例>_<岛键>`；
> ⑥ 嵌套再导出：`ports: {E: 子.E}`、`external: {C: {inst: 子}}`（无 `.geo` 的父模板）；⑦ **未做**：`py:` 逃生口、`nets:` 覆盖、taper、
> 端口面 tag 表注入（增量原则下无用）、多张 ground sheet 之外的 ground 角色输出、Chen 模板（下一步）。开放问题 §2 不变。

---

## 0. 一句话

**版图 = 一个 gmsh 模型。** 往里写几何的还是 `.geo`：手写的顶层 `.geo`（今天的用法，原样保留）和**模板**（一份局部坐标的 `.geo` + 一份 YAML 接口，
和项目本身的两层结构同构，可嵌套；Python 只是需要算法时的逃生口）。两者在**同一个模型**里混用，靠 gmsh 本来就有的三条通道过界：
解析器变量、OCC tag、Physical 名。**层是模板的局部命名空间**，实例化时映射到芯片的层表，层的性质由芯片决定。
「库」= 一批模板 + 一个很薄的编排器（按顺序执行版图步骤，做映射、校验与记账）。下游 GDS / mesh / Palace / LOM 不改。

```
                 ┌──────────── 版图 = 有序步骤 (YAML) ───────────┐
                 │ 1. template: disc_transmon  Q0  at (0,0)      │  模板 = .geo + yaml → 设变量, merge, 变换到位, 映射层, 挂名
                 │ 2. template: pad           P1  at (900,0)    │  同上
                 │ 3. geo: flux_lines.geo      frame: Q0         │  手写补画 (只增不改) → 端口/面 tag 已在变量里, merge
                 │ 4. route: cpw_meander  Q0.RO → P1.W  f_r 7GHz │  连接型模板 → 从端口出发, 定长, 两端并成一个 net
                 │ 5. ground: sheet                              │  策略步 → 大矩形 − 所有蚀刻工具面 (平面工艺); flip-chip 无
                 └───────────────────────┬───────────────────────┘
                                         ▼
                              一个 gmsh 模型 (2D Physical 面, 四段名, 层 = 芯片层表的 id)
                                         ▼
                 geo_model → build_gds / build_mesh / palace_config / solve_circuit_model   (现有, 不改)
                                         +
                 编排器顺手产出: circuit_model.qubits (岛 + 结) · subsystems (谐振器长度记账)
```

今天的用法就是这张表**只有一步** `geo: chip.geo`——`meta.geo:` 不变，仍然合法。

---

## 1. 框架

### 1.1 汇合点：一个 gmsh 模型

下游三个消费者（`load_geo` / `build_gds` / `build_mesh`）只做「进模型 → 读 2D Physical 组」，从不读 `.geo` 文本。
所以几何从哪来对下游透明。`.geo` 用 `gmsh.merge` 进**已有**模型：新面加进来，旧面还在；Python 用 `gmsh.model.occ` 写同一个模型。
两边建的都是同一个 OCC 内核里的面。

### 1.2 三条过界通道（全部实测，§4.4）

| 通道 | 方向 | 用途 |
|---|---|---|
| 解析器变量：Python `gmsh.parser.setNumber/setString` → `.geo` 直接当变量用 | Python → `.geo` | 模板参数、实例端口（`Q0_E_x/y/a/w`）、面 tag 表（`Q0_a()`） |
| `.geo` 里赋的值 → Python `gmsh.parser.getNumber` | `.geo` → Python | `.geo` 算出的面 tag 表、端口、蚀刻工具面、记账长度 |
| OCC tag | 双向 | Python 用 merge 前后 `getEntities(2)` 的差集拿到 `.geo` 新建的面；`.geo` 能读到 API 面的 tag（但见 §1.4 增量原则） |
| Physical 名 | 双向 | 两边各自挂组，**累积**不冲突；同一 net 的多块面 = 同 component、不同 primitive（mesh 已按 component 合并） |

探针踩出的三条注意：① 全名重复时 API 侧**静默**给空名、`.geo` 侧 raise——编排器统一校验重名；② `removePhysicalGroups()` 之后同名重挂不可靠——
编排器**不删不重挂**，只累积；③ `.xao` 导入的组会被后续 `.geo` 的 `Physical` 语句抹掉——`.xao` 只作 GUI 导出格式。

### 1.3 模板 = 一份 `.geo` + 一份 YAML，和项目本身同构

模板的默认形态**和整个项目一样是两层文件**：`.geo` 画几何（局部坐标、**不打 Physical 名**，沿用 qlib「宏不打名、调用点打」的老契约），
YAML 声明接口与语义。编排器就是那个「调用点」。

```
xmon/                        （或平铺 xmon.geo + xmon.yaml）
├── xmon.geo                 # 局部坐标 (0,0) 画; 读 arm_w/arm_L/gap 等变量; 把面 tag 与端口写进输出变量
└── xmon.yaml
    params:   {arm_w: 30, arm_L: 340, gap: 32, jj_w: 2, claw_RO: 1}      # 默认值 (µm / 开关), 实例可覆盖
    layers:   {metal: {kind: conductor}, jj: {kind: junction}}            # 槽位: 只声明要求, 不声明性质 (§1.5)
    islands:  {island: {faces: faces_island(), layer: metal}}             # 输出变量 → 岛 (接地单岛; 浮动写 a/b 两条)
    external: {RO: {faces: faces_claw(), layer: metal, if: claw_RO}}      # 由本模板画、电学归别人的面; 键 = 端口名; 可选部件
    etch:     [moat()]                                                    # 负形: 平面工艺下由 ground: sheet 策略统一减去
    junction: {a: island, b: ground, x1: jj_x1, y1: jj_y1, x2: jj_x2, y2: jj_y2, width: jj_w, layer: jj}
    ports:    {RO: {x: port_x(0), y: port_y(0), a: port_a(0), w: port_w(0), leq: 0, if: claw_RO}}
```

实例化 = 编排器把 `params`（实例覆盖后）`setNumber` 进解析器 → `merge` 该 `.geo` → 差集拿到新面、按实例位姿（`at / rot / mirror`）变换 →
读 YAML 指名的输出变量（面 tag 表、端口、结坐标、蚀刻工具）并同样变换 → 层槽位按实例的层映射换成芯片层 id、component 加实例名前缀 →
挂 Physical（`metal::a::Q0::island`、`jj::e::Q0::jj`）→ 登记岛 / 结 / 端口 / 蚀刻。变量全局没关系：一次只实例化一个，读完即走。

**模板可以嵌套**：模板 YAML 也可以有 `steps:`（§1.4 同一套语法）。一个 qubit 模板 = 圆盘 `.geo` 步 + 四个爪子模板实例 + 结；
它对外的端口 / 岛 / 外挂面用 **再导出** 写法引用子步骤的输出（`ports: {E: claw_E.out}`、`external: {E: claw_E.faces}`）；
子模板的层槽位映到父模板的槽位（同名默认恒等），层映射与 component 前缀随嵌套复合。整块芯片 = 没有参数的顶层模板。

**逃生口**：`steps` 里允许 `py: 模块.函数` 一步——需要解方程或循环的几何（定长蛇形、任意折线圆角）在 `.geo` 里写得难受时用 Python 画，
输出同一套东西。它是补充，不是默认。

模板形态的取舍（都可行，选默认）：

| 形态 | 好 | 差 |
|---|---|---|
| **`.geo` + YAML**（默认） | 几何仍是用户熟悉的 `.geo`；接口显式（默认值、岛 / 端口 / 层槽位一目了然）；可嵌套；与项目两层结构同构；可单独构建 | 一次只能实例化一个（顺序）；接口与 `.geo` 输出变量要对得上 |
| 仅 `.geo` + 变量命名约定 | 少一个文件 | 接口隐含，没有默认值 / 文档 / 校验位置 |
| Python 函数 | 真参数、循环、求解、单测 | 用户得写 Python；与手写 `.geo` 风格断裂 |
| 现状（宏 + `Include`） | 零新东西 | 带不动语义（岛 / 结 / 端口 / 层），几十个参数不可维护 |

**模板可单独构建**：模板 = 小项目，`build` 它自己就能看 GDS 图。模板 YAML 允许附一张仅供独立构建的层表。

### 1.4 版图 = 有序步骤

```yaml
schema: quantum-dsl/layout/1
templates: [./lib, examples/chen2025]              # 模板搜索目录 (每个模板 = <name>.geo + <name>.yaml, 或同名子目录)
steps:
  - {template: disc_transmon, name: Q0, at: [0, 0],    layers: {metal: a, jj: e}, squid: {E_J1: 20GHz, E_J2: 20GHz}}
  - {template: disc_transmon, name: Q1, at: [1383, 0], layers: {metal: a, jj: e}, squid: {E_J1: 20GHz, E_J2: 20GHz}}
  - {template: bar_coupler,   name: C01, from: Q0.E, to: Q1.W, squid: {…}}        # 连接型: 吃两个端口; 层映射默认恒等 (§1.5)
  - {template: pad, name: P1, at: [0, -900], rot: 90, mirror: x, params: {w: 80, h: 40}}
  - {geo: flux_lines.geo, frame: Q0}                 # 手写补画, 在 Q0 局部坐标; 可读 Q0_* 变量; 只增不改
  - {geo: launch.geo, ports: {F0: {x: f0_x, y: f0_y, a: f0_a, w: f0_w}}}          # 手写几何也能声明端口
  - {route: cpw_meander, name: R0, from: Q0.RO, to: F0, length: {mode: quarter_wave, f_r: 7GHz}}
  - {geo: marks.geo}                                 # 顶层手写: 对准标记、任何东西 (名字里直接写芯片层 id)
ground: sheet: {layer: a, margin_um: 250}            # 或 none (flip-chip)
```

- **三种步骤**：`template`（放置型 `at / rot / mirror`，或连接型 `from / to`）、`geo`（手写 `.geo`，可挂 `frame:` 在某实例局部坐标下画，
  可声明 `ports:`）、`route`（连接型模板的语法糖）。`ground:` 是收尾策略，不是步骤。
- **编排器每步做三件事**：执行前把此前所有实例的端口 / 面 tag 与**本模板的参数**放进解析器变量；执行（merge 或调 `py:`）；执行后收集新面、
  输出变量，登记岛 / 结 / 端口 / 蚀刻。步骤顺序 = 依赖顺序，作者自己排；引用不到的端口 raise。模板自己的 `steps:` 递归执行，坐标系叠加。
- **增量原则（已定）**：手写 `geo:` 步骤**只增不改**——不用 `Delete`，不对模板给的面做布尔。原因：OCC 布尔会替换实体，登记的 tag 可能失效，
  分裂出的新面没有名会被 `build_mesh` 当孤儿**静默删掉**。编排器在每个手写步骤前后快照已有面（tag、面积、bbox），有变化即 raise。
  要改模板的形状，给模板加参数。
- **负形**：模板与路由都可输出 `etch:`（moat / pocket / CPW 缝工具面）。`ground: sheet` 在所有步骤之后建大矩形并一次减去全部工具面，
  挂 `ground::<layer>::GND::sheet`；`ground: none`（flip-chip）时工具面丢弃。模板自带的接地面（bump 接地的焊盘）用 `ground` 角色输出，与策略地并存。
- **连接型模板的局部坐标**：原点在 `from` 端口、x 轴指向 `to` 端口，两口距离 `D` 作为隐含参数注入；两口不正对（法向不共线）→ raise，
  作者先用直段 / 拐点步骤把路引到正对位置。
- **单位**：长度 µm；YAML 里角度写度，注入 `.geo` 前转弧度。
- 实例级物理量（`E_J` / `L_J` / `squid`）写在步骤上，编排器据此生成 `circuit_model.qubits`；meta 里若也手写了且不一致 → raise。

### 1.5 层与工艺栈

- **层是模板的局部命名空间**。模板 YAML 只声明**槽位**（名字 + `kind` 要求）。实例上写 `layers: {metal: a, jj: e}` 把槽位映到芯片层；
  芯片层表里有同名层且 kind 兼容时可省略（恒等映射）；对不上或 kind 不兼容 → raise。嵌套时映射复合。同一模板可在同一芯片上映到不同层。
- **映射之后就是芯片的层，没有特殊性**。模板落在 a 上的面与手写 `Physical Surface("metal::a::F0::feed")` 加进去的面进同一 GDS 层、
  同一 z 平面、同一套性质。端口也带层，路由默认沿出发端口的层画。
- **层的性质由芯片项目决定，模板只提要求**。meta 加一张 `layers:` 表——工艺栈是 process 的属性，不是元件的：

  ```yaml
  layers:
    a: {kind: conductor, gds: [1, 0]}                   # 进静电网格, z = 0 (今天唯一支持的导体平面)
    e: {kind: junction,  gds: [20, 0]}                  # 集总元件: 进 GDS, 从网格删除 (= 今天 role jj 的行为)
    m: {kind: drawing,   gds: [63, 0]}                  # 只进 GDS: 对准标记 / 切割道 / 空气桥 / bump, 不进模型
  ```

  它接管 `gds.by_role` 的职能（GDS 按层而非按 role）；`materials.substrate`、`airbox`、`outer_boundary` 仍留在 meta——它们是计算域与衬底，
  不是掩膜层。载片地暂仍是 `airbox.top_um = d`；层表给 z ≠ 0 的导体层留位，但**现在一律 raise**：模拟器只有 z = 0 一个导体平面，不假装支持。
- **`role` 保留，且必须与层 kind 一致**：`metal` / `ground` 是同一导体层上的 net 级区分，层 kind 管不了；`jj` 面只能落在 `junction` 层。
  编排器与 `load_geo` 都查。Physical 名的层段放宽为标识符（今天只允许整数；无层表时仍是自由整数）。
- **重叠规则**：不同 net 的导体面在同一 z 平面重叠 = 短路 → 编排器做一次 2D 相交检查，raise。同 net 重叠放行（imprint 会 fragment，GDS 的 union 无碍）。
  `drawing` 层不参与检查。
- **无层表 = 今天的行为**（层段自由整数、GDS 按 role），现有三个例子零改动。

### 1.6 端口、路由与 net

- **端口** = 端面中点 + 外法向 + 宽（+ 缝）+ 所在层 + 等效长度。谁画了那块面谁给端口：qubit 的爪、pad 的四条边、手写 `.geo` 里声明的锚点。
- **路由只接端口，不接坐标**：沿 `from` 外法向出发、逆 `to` 外法向到达，垂直端面。宽度继承 `from` 端口；两端宽不同必须显式 `taper`。
- **路由是电连接**：一条路由把两端端口所在的面和自己的面并成一个 net（读出腔 = 爪 + 蛇形 + 发射焊盘 = `R0`；耦合器 = 条 + 两端爪 = `C01_bar`）。
  电容耦合不是路由，只是靠近。`nets:` 只用于极少数覆盖场景。
- **连接结构归画它的模板**（爪由 qubit 画，它知道盘径与间隙），电学归属由路由 / 连接决定。画了却没人接的外挂面 → raise「Q2.E 无连接」，
  不静默并入地；边缘 qubit 用参数不画那只爪。
- **等效长度**：Δl = arctan(ωZ0C)/β ≈ C/C′（§4.2）。路由定长时 L_drawn = L_target − Σ 端口 leq，三者进 `subsystems`。leq 的来源见开放问题 1。

### 1.7 编排器纪律（全部 raise，不静默）

| 事项 | 规则 |
|---|---|
| 参数被内层覆盖 | 该模板每个 `.geo` 步骤执行前**重新注入**它的参数（嵌套子模板会改写同名全局变量） |
| 输出变量陈旧值 | 每步执行前把声明的输出变量全部置 NaN；读回是 NaN → raise。不用 `parser.clear()`（它清掉 include guard，宏库二次包含即炸） |
| 可选部件 | `if:` 未启用的输出不读；启用了却缺 → raise |
| 全名唯一 | 跨手写与模板统一查 Physical 全名与 component 名（API 侧重名是静默空名） |
| 面的归属 | 每步之后模型里每块非 `drawing` 面必须恰被一个 net 认领；手写步骤前后已有面原样存在 |
| 层 | 槽位映射存在且 kind 兼容；role 与 kind 一致；不同 net 同平面不相交 |
| 端口 | 引用存在、至多被一条路由使用、宽度匹配或有 taper、正对 |
| 错误定位 | `.geo` 解析错误前缀「实例路径 / 模板文件 / 行号」 |
| 可复现 | manifest 输入 sha256 覆盖版图、所有模板文件、所有 `geo:` 步骤文件、`py:` 模块 |
| 分块 | 版图路线按 component 在模型内过滤面；旧 `.geo` 路线保留文本过滤 |

### 1.8 与现状的关系

- **手写 `.geo` 不变、不搬、不冻结。** `qlib.geo` 之类是用户自己的宏库，怎么用是用户的事；软件只保证它们能在同一模型里与模板共存、
  拿到端口变量、把自己的面挂上名。
- **meta 词汇**：新增 `layout:`（与 `geo:` 二选一）与 `layers:` 表；其余不变。`circuit_model.qubits` / `subsystems` 可由编排器生成，也可手写。
- **下游不改。** 需要新写的只有：编排器（步骤执行 + 过界通道 + 层映射 + 校验 + 记账 + `ground: sheet`）、端口 / 等效长度的数据结构与 helper、
  首批模板（`.geo` + YAML）。几百行量级。
- **不 fork gmsh**（§4.3）；**不发射 `.geo` 文本**；不再往 `.geo` 宏里塞库。

---

## 2. 开放问题

1. **等效长度 / 爪电容的来源**：它依赖工艺栈（介电常数、flip-chip 间隙），不是模板本身的量。模板存标定值并标注标定时的栈，还是芯片级现算。暂不定。
2. **Chen 3×3 两项**沿用 B 报告：直接 Q–Q 耦合保不保；读出结构进不进 phase 1。

已关闭：模板 `.geo` 不打名、由 YAML 指名输出（§1.3）；同 net 重叠放行、跨 net raise（§1.5）；手写步骤只增不改（§1.4）；不做纯 gmsh 无 Python 的 `.xao` 用法。

---

## 3. Chen 2025 落进框架（数字见 B 报告）

| 步骤 | 内容 |
|---|---|
| `disc_transmon`（`.geo` + YAML；圆盘切缝 + 五个爪子模板嵌套） | 岛 `a/b`；爪 E/N/W/S/RO 为外挂面（参数开关，边缘比特不画），端口在爪外弧中点（宽 = 条宽 30）；结在圆心跨缝；槽位 metal / jj |
| `bar_coupler`（连接型） | 条 port→port + 五边形 + 结；路由规则把两端爪并入条的 net；纵向键 = 横向键 `rot 90 + mirror` |
| 读出 | `route: cpw_meander from Q.RO`，λ/4 定长减 leq；焊盘（bump 接地）作模板的 `ground` 角色输出或 `geo:` 步手写 |
| 3×3 | 9 + 12 个模板步骤的显式列表；`ground: none`；层表 `{a: conductor, e: junction}`；`airbox.top_um: 5` = 载片地 |
| 验证 | SI §D 的 6×6 Maxwell，`d` 唯一拟合量（B 报告 §5） |

---

## 4. 查实

### 4.1 业界的端口契约

qiskit-metal（源码 2026-09-12 抓取）：pin = `points`（端面两端点）+ `middle` + `normal`（指离元件）+ `width` + `gap`（`base.py:843–880`）；
`TransmonCross` 的爪 + 引出短线由 **qubit 组件**画，pin 打在短线末端、宽 = `claw_cpw_width`（`transmon_cross.py:234–280`）；
`QRoute` 从 pin 出发、沿法向，但线宽是路由自己的选项、不检查不匹配（`qroute.py:85,143,261–293`）——本框架改成继承 + raise/taper。
KQCircuits：`Element.add_port(name, pos, direction)` + "corner" 参考点定波导方向；Swissmon 持有 `cpl_*` 与 `port_width`；
`WaveguideComposite.length_before` 插蛇形定长。结论：连接结构归 qubit，端口 = 有宽度的边 + 法向，路由从端口出发。

### 4.2 等效长度的物理

开路端挂负载 C：λ/4 的共振条件 tan(βl) = 1/(ωZ0C)，λ/2 的 tan(βl) = −ωZ0C，两者被吃掉的长度都是
**Δl = arctan(ωZ0C)/β ≈ C/C′**（一个端电容 = 一段电容相同的线）。Göppl 2008 JAP 104, 113904 集总口径同一结论：Eq.(12) C = C_ℓl/2、
Eq.(15) C* = C_κ/(1+ω²C_κ²R_L²)、Eq.(18) ω_n* = 1/√(L_n(C+2C*))，一阶展开 δω/ω = −C*/(C_ℓl) 与 Δl = C*/C_ℓ 一致。
量级（`lumped_cpw`，7 GHz，10/6 CPW，Si 500 µm：C′ = 0.1635 fF/µm）：5 fF → 31 µm ≈ 50 MHz；10 fF → 61 µm ≈ 100 MHz；
flip-chip d = 5 µm 时读出爪平行板下界 ≈16 fF → 百余 MHz。所以这项记账是把读出腔放到目标频率的必要项，不是精修。
边界：准静态、爪 ≪ λ；qubit 的色散推移另算（`dispersive_shift_hz`）；均匀短线按几何长计。

### 4.3 `.geo` 语言边界与 fork gmsh 评估

手册 §5.1.7：宏无参数、变量全局；§1.5 复杂几何请用 API。subagent 读 gmsh 5.0-dev 源码（报告 scratchpad `gmshfork/REPORT.md`）：
`Gmsh.y` 7 882 行 bison 直译无 AST，宏 = `fgetpos/fsetpos` 跳转，符号表三张全局 map；语句级带参 + 局部作用域约 3–4 人周，
**表达式级返回值做不出**（与列表下标语法冲突）；官方 wheel 是 CI 自编静态 OCCT 打包，fork = 永久私有构建链；手册把「无私有变量、宏无参数」
写成已知局限并指向 API；API 与 `.geo` 是同一个 `OCC_Internals`，无能力缺口。→ 不 fork。`.geo` 的弱点（无参数、无作用域、无返回值）
由「YAML 接口 + 编排器设变量 / 读变量 / 挂名」在 `.geo` 之外补齐；真要算法的地方走 `py:` 逃生口。

### 4.4 混用探针（scratchpad `probe2/`，gmsh 4.x pip wheel，qdsl313）

| 验证项 | 结果 |
|---|---|
| API 建圆盘双岛后 `merge` 手写 `.geo`：`.geo` 用 `Q0_E_*` 变量在端口外接线、对 API 面 `Q0_a(0)` 做 `BooleanDifference` | 通过；新面加入，旧面保留，布尔结果 tag 可回读（布尔改面随后被增量原则禁掉，机制本身可行） |
| `.geo` 算的端口 `F0_*` 由 Python `getNumber` 回读 | 通过 |
| 局部坐标 `.geo` 片段：merge → 差集拿新面 → `rotate/translate` | 通过，bbox 与手算一致 |
| `.geo` 当模板：`setNumber` 参数 + `setString("inst")`，`StrCat` 拼 Physical 名，`out_port_*()` 输出；同一文件两次实例化 | 通过，两组名字正确、端口正确 |
| API 先挂组，再 merge 带 `Physical` 的 `.geo` | 通过，组累积 |
| 全名重复 | API 侧静默空名；`.geo` 侧 raise → 编排器统一校验 |
| `removePhysicalGroups()` 后同名重挂 | 不可靠（空名 / 丢组）→ 不删不重挂 |
| `.xao` 导入的组 + 后续 `.geo` `Physical` 语句 | 组被抹掉 → `.xao` 只作导出 |
| `.brep` 往返面 tag 顺序 | 简单例保持顺序（未作一般性结论） |

---

## 5. 暂不做，记一笔

自动避障路由；YAML 参数表达式（`arm_L: 2*R`，让 `.geo` 内部自己算）；模板版本号；载片作为独立芯片面的翻转放置与 z ≠ 0 导体层；
`targets` 挂到实例上（backlog #23 的归宿）。
