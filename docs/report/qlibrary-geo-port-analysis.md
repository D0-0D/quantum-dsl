# qiskit-metal 元件库 → yaml+geo DSL 移植分析

> **主题**：qiskit-metal 的 QComponent 元件库（QLibrary）有什么功能、怎么构造；能否用本项目的
> **yaml + 原生 Gmsh `.geo`** DSL 做一个类似的库；以 `RouteMeander` 为例说明"一大堆方法"里
> 哪些能移植、哪些不能；其它 library 类逐层评估；给出**可实现的边界**。
>
> 面向 native-geo 路径（`meta.yaml` + `.geo` → GDS + Palace 静电电容矩阵）。参考：`.claude/plan.md`、
> `.claude/status.md`。**结论先行**：qiskit-metal 元件分两种本质——"自身几何的纯函数"与"读取整个
> 设计图 + 构建期算法"；前者能原生移植，后者不能塞进静态 `.geo`。

---

## 1. qiskit-metal 元件库：功能与构造

### 1.1 库的组织（7 大类）

`qiskit_metal/qlibrary/` 按物理角色分七类，基类链为
`QComponent → BaseQubit`（加 connection_pad 机制）/ `QRoute`（加 pin-to-pin 路由）。

| 类别 | 代表元件 |
|---|---|
| **Qubits** | `TransmonPocket` / `TransmonCross` / `TransmonInterdigitated` / `StarQubit` / `SNAIL` / `SQUID_LOOP` |
| **Couplers** | `CoupledLineTee` / `LineTee` / `CapNInterdigitalTee` / `TunableCoupler01` / `TunableCoupler02` |
| **Transmission Lines** | `RouteStraight` / `RouteMeander` / `RouteMixed` / `RouteAnchors` / `RoutePathfinder` / `RouteFramed` |
| **Resonators** | `ReadoutResFC` / `ResonatorLumped` |
| **Terminations** | `LaunchpadWirebond*` / `OpenToGround` / `ShortToGround` |
| **Lumped Elements** | `Cap3Interdigital` / `CapNInterdigital` / `ResonatorCoilRect` |
| **Sample Shapes** | `Rectangle` / `NGon` / `CircleRaster` / `NSquareSpiral` … |

### 1.2 一个 QComponent 是怎么"画"出来的（核心机制）

```python
class TransmonPocket(BaseQubit):
    default_options = Dict(pad_width='455um', pad_gap='30um', ...,   # ① 声明式参数（带单位）
                           _default_connection_pads=Dict(...))
    component_metadata = Dict(short_name='Pocket', _qgeometry_table_poly='True', ...)

    def make(self):                      # ② 唯一必须实现的方法
        p = self.p                       #    解析后的参数（单位已转数值）
        pad_top = draw.rectangle(p.pad_width, p.pad_height)          # ③ shapely 命令式画几何
        pad_top = draw.translate(pad_top, 0, +(p.pad_height+p.pad_gap)/2)
        rect_jj = draw.LineString([(0,-p.pad_gap/2),(0,p.pad_gap/2)])
        polys = draw.rotate([...], p.orientation, origin=(0,0))      # ④ 先在原点画，最后统一变换
        polys = draw.translate(polys, p.pos_x, p.pos_y)
        self.add_qgeometry('poly', dict(pad_top=pad_top, pad_bot=pad_bot))
        self.add_qgeometry('poly', dict(rect_pk=rect_pk), subtract=True)   # ⑤ 负性：从 ground 挖
        self.add_qgeometry('junction', dict(rect_jj=rect_jj), width=p.inductor_width)
        self.add_pin('a', points, width=...)                        # ⑥ 给路由用的连接点
```

要点：

- **几何是命令式 Python + shapely；参数是声明式 `default_options`**；两者解耦。
- `add_qgeometry(kind, {name: shape}, subtract=, width=, layer=, chip=)`，`kind ∈ {poly, path, junction}`。
- `QDesign` 汇总所有 component 的几何进 3 张 GeoPandas 表（poly/path/junction）；**renderer**
  （GDS / Ansys HFSS / Q3D / Gmsh …）各自消费这些表 → **几何与后端解耦**。

---

## 2. 本项目现有两套"库"，为何都还不是"yaml+geo 原生"

### 2.1 v3 YAML 模板 `src/quantum_dsl/dsl_templates/`（**不 geo 原生**）

它把 QComponent 的 `make()` **逐条声明式化**（对照 `qubits/transmon_pocket.yaml`）：

| QComponent | v3 YAML 模板字段 |
|---|---|
| `default_options` | `options:` |
| `add_qgeometry('poly', …)` | `primitives: type: poly.rectangle` |
| `subtract=True` | `subtract: true` |
| `add_qgeometry('junction', …, width=)` | `type: junction.line, width:` |
| connection_pads 循环 | `generators.connection_pads.for_each` |
| rotate + translate | `geometry.transform` |
| `add_pin` | `pins:` |

**但它走旧 shapely 路径**（`build_ir → shapely PrimitiveIR → QDesign`）。native-geo 路径靠
`src/quantum_dsl/dsl/geo_emit.py` 的 **emit_geo 桥**把它"下降"成 flat `.geo`（圆角靠**预采样 shapely
buffer**）。→ 这是**借道 shapely**，不是原生 geo。

### 2.2 `examples/dsl/geo/qlib.geo` 原生 OCC 宏（**geo 原生，但还不是"库"**）

`PAD / CPW / JUNCTION / GROUND_CUTOUT / GROUND_POCKET` 是纯几何 Macro，Physical 名由**调用点**打
（同一几何复用为不同 role）；`qm4q_transmon_cell.geo` 用 `Call PAD` / `Call GROUND_CUTOUT` 拼出
一个 transmon。**但缺**：YAML 参数层、库注册表、连接器顶点仍手算硬编码（`qm4q_transmon_cell.geo:59-69`）、
圆角未做。

> **现状一句话**：声明式的那套（2.1）不 geo 原生；geo 原生的那套（2.2）还没被封装成"库"。

---

## 3. 能否用 yaml+geo 做一个类似 QLibrary 的库？——能

核心是**照搬 qiskit-metal 的解耦**，把两半换成 geo 原生：

| qiskit-metal | yaml+geo 原生对应 |
|---|---|
| `make()`（命令式几何） | **`.geo` 宏**（OCC 原生，qlib.geo 已起头） |
| `default_options`（声明式参数） | **YAML**：cell 默认参数 + 实例 `params/x/y/rot/layer` |
| `add_qgeometry` 的 kind/name/subtract | Physical 名 **`role::layer::comp::prim`**（契约已存在） |
| renderer 消费 qgeometry 表 | `load_geo` 下游的 GDS/Gmsh/Palace（**完全不用改**） |

### 路线 1（推荐）：geo 宏库 + YAML 实例化

- 把 `qlib.geo` 扩成一组**参数化 Macro**（每个 cell 一个 Macro = 一个 QLibrary class）。
- YAML 复用现有 `cells:` 块（`cell_type + params + x/y/rot/layer`），`elaborate_cells` 赋值全局变量 →
  `Call <MACRO>` → 调用点打 Physical 名 → 拼 `<stem>.elaborated.geo`。
- **圆角**用 OCC 原生 `Fillet`（比 buffer 更原生、顶点更少）；**pin** 由宏产出 `port::` dim-1 marker。
- 收益：真正 geo 原生、**零 shapely**、Palace/GDS 名字契约字节不变，复用现有 Elaborator/`carve_conductors`。

### 路线 2：声明式 geo-cell schema（YAML 直接描 OCC 原语）

YAML 写 `Rectangle/Disk/Fillet/BooleanUnion/Difference + physical`，emitter 不经 shapely 生成 `.geo`。
更声明式，但要写一个 mini OCC-DSL 解释器（连接器那种 `for_each` 子结构循环得在 geo 层用 `For…EndFor` 重建）。

---

## 4. `RouteMeander` 深剖：它的"一大堆方法"能移植吗

### 4.1 方法按性质分两拨

`RouteMeander`（继承 `QRoute`）：

| 方法 | 干什么 | 性质 |
|---|---|---|
| `make_elements(pts)` | 把中心线折点 buffer 成 CPW 金属 + 两侧 gap(subtract) | **纯几何** ✅ |
| `set_pin` / `set_lead` / `set_lead_end` / `get_tip` | 把 `start_pin`/`end_pin` 解析成**别的元件的 pin 位置+朝向**(`QRoutePoint`)，接出 lead 直段 | **读全局设计图** ❌ |
| `connect_meandered()` | 按 distance/spacing 算**蛇形振荡个数**，按目标 `total_length` 反算**振幅**，生成上下交替折点 | **构建期算法** ❌ |
| `adjust_length()` | 把圆角损耗的长度重分摊到各蛇形段（length matching） | **构建期算法** ❌ |
| `get_index_for_side1_meander` / `issideways` | 折点索引 / 叉积定侧 | 算法辅助 |

**关键**：RouteMeander 的几何是**算法的输出**，不是静态参数形状。`make()` 时要 (1) 去
`design.components[...].pins[...]` 拿两端 pin，(2) 解一个"既满足总长又满足间距"的蛇形排布问题。
`RoutePathfinder` 更进一步——对**整块芯片已有几何**跑 A\* 避障。

### 4.2 "移植 RouteMeander" 到底意味着什么

**不是写一个 `.geo` 宏**（静态宏做不到读别的元件、也做不了 A\*），而是：

- **几何发射那半（`make_elements`）** 早已具备——emit_geo 里 path→buffered polygon 就是这件事；
- **路径计算那半（`connect_meandered`/A\*）** 只能在 **Python Elaborator** 里重建。而这**和
  qiskit-metal 一模一样**——它的路由算法本来就跑在 Python `make()` 里，不在几何里。

### 4.3 要接入路由，需补三样现在没有的基础设施

1. **pin/port 注册表** —— 每个 cell 放置后暴露命名 pin 的坐标+朝向（现在的 `port::` marker 只占了
   名字，还没有"可被引用解析"的注册表）；
2. **`connections:` / `routes:` 块** —— `start: Q1.pad_a`, `end: R1.in`, `type: meander`,
   `total_length: 7mm` …（现在的 `cells:` 只能独立摆放，**没有网表**）；
3. **Python 路由器** —— 解析 pin → 跑 connect_meandered/A\* → 吐中心线 → 交给现成 path-buffer 出几何。

---

## 5. 其它 library 类：按"可移植度"分四层

| 层 | 类 | `make()` 依赖 | yaml+geo 可行性 |
|---|---|---|---|
| **T1 静态参数几何** | Sample Shapes、TransmonPocket/Cross/Interdigitated、StarQubit、Cap3/CapN Interdigital、ResonatorCoilRect、Launchpad、Open/ShortToGround | **仅自身 options** | ✅ **完全可移植**。叉指/螺旋用 `.geo` `For…EndFor`，圆角用 OCC `Fillet` |
| **T2 静态几何 + pin** | LineTee、CoupledLineTee、CapNInterdigitalTee | 自身几何 + 暴露 pin | ✅ 几何可移植；pin 待注册表 |
| **T3 含结/有源** | jj_dolan、jj_manhattan、SQUID_LOOP、SNAIL、TunableCoupler01/02 | 几何 + junction | ✅ **几何可移植**（JJ 已按 lumped：进 GDS layer20、不网格化）；非线性电感是**电路模型**的事 |
| **T4 路由/图依赖** | RouteStraight、RouteMeander、RouteMixed、RouteAnchors、**RoutePathfinder** | **读整个 design 的 pin/几何 + 构建期算法** | ⚠️ 静态 `.geo` **做不到**；须在 Python Elaborator 重建路由器 + 加网表/pin 注册表 |

> qiskit-metal 库里约 **5/7 的类是 T1–T3**（纯几何或几何+结），用 yaml+geo 原生做没有本质障碍；
> 只有 **Route\*（T4）** 是硬骨头。

---

## 6. 可实现的边界（一条清晰的线）

**边界 = 一个元件的几何是不是"仅由它自己的参数唯一确定"。**

- **线内（可原生实现）**：`make()` 是 `self.options → 几何` 的**纯函数**。→ 全部 T1/T2/T3。
  `.geo` 宏（命令式几何）+ YAML（声明式参数）+ OCC 布尔/Fillet/For 循环，完全够。
- **线外（不能塞进静态 geo，只能 Python 层重建）**：`make()` 需**读取其它元件的状态**（pin 位置、
  别处几何）或**跑构建期优化算法**（蛇形长度匹配、A\* 避障）。→ 全部 T4。

**叠加一条工程边界**（与项目分期吻合）：

- **静电电容矩阵阶段（当前）根本不需要 T4** —— 电容只看导体面，不看走线拓扑。
- Route\* 的价值在**本征模/驱动**（谐振器频率、S 参数、长度匹配）= **M4，已 defer**。
- 即：**现在把 T1–T3 做成真正 geo 原生的小 QLibrary，是完整闭环且够用**；T4 留到 M4，届时它落在
  Python Elaborator（网表 + 路由器），而**不是 `.geo` 宏**里。

**两个"能做但要单独投入"的灰区**：

- 叉指电容/螺旋的 `For` 循环 + 圆角的 OCC `Fillet`——技术支持，只是要写；
- 多岛/浮动 qubit、bus 耦合的**物理**（非几何）——已在 issue **#20**（Schur 消元），属电路模型边界，与库无关。

---

## 7. 建议（分两批落地）

1. **第一批（本阶段，对齐静电电容）**：走**路线 1**，把 `qlib.geo` 扩出 4–5 个参数化 cell
   （`transmon_pocket` / `cpw` / `launchpad` / `interdigital_cap` / `coupler_tee`，含 OCC `Fillet`
   圆角）+ YAML `cells:` 参数化，跑通 `build_geo` → C 矩阵。得到"够用、真正 geo 原生"的小 QLibrary。
2. **第二批（可选，对齐 M4）**：加 **pin 注册表 + `routes:` 块 + Python 路由器**，把 RouteMeander
   那类接进来。
3. **v3 YAML 模板保留做迁移参照/对照，不再扩它**（它不 geo 原生，扩它是走回头路）。

---

## 附：参考

- qcomponents gallery — <https://qiskit-community.github.io/qiskit-metal/qcomponents-gallery.html>
- RouteMeander 源码（meandered.py）— <https://qiskit-community.github.io/qiskit-metal/_modules/qiskit_metal/qlibrary/tlines/meandered.html>
- RouteMeander API — <https://qiskit-community.github.io/qiskit-metal/apidocs/qiskit_metal.qlibrary.RouteMeander.html>
- 本项目文件：`src/quantum_dsl/dsl/geo_emit.py`、`src/quantum_dsl/dsl_templates/qubits/transmon_pocket.yaml`、
  `examples/dsl/geo/qlib.geo`、`examples/dsl/geo/qm4q_transmon_cell.geo`
