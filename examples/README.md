# examples/ — 可运行的例子

每个例子 = 一份几何源（手写 `.geo`，或版图 `*.layout.yaml` + `lib/` 模板）+ 一份 `*.meta.yaml`（材料 / 计算域 /
网格 / 求解器 / 结参数）。它们同时是测试套件（`tests/`）的输入，所以永远与代码同步、拿来就能跑。
语法参考见 [`../docs/grammar.md`](../docs/grammar.md)（§2 手写 `.geo`，§3 meta，§4 版图，**§4.2 模板文件**）。

## 例子清单

| 例子 | 是什么 | 用来看什么 | Palace 规模 |
|---|---|---|---|
| `two_pads.{geo,meta.yaml}` | 两块分离的 80×80 µm 焊盘，各挂 10 nH 结 | 整条管线的最小闭环；**回归锚**（C 矩阵实测 golden 写在头注） | 单核 ~4 min，内存 <2 G |
| `two_pads_blocks.meta.yaml` | 同一几何切成 A / B 两块 | 分块提取 `extract.blocks`，以及「跨块直接互容 = 结构性零」告警 | 不需要求解 |
| `two_pads.layout.yaml` + `two_pads_layout.meta.yaml` | 同一 two_pads，用**版图**写：两个 `pad` 模板实例 | 版图路线的最小例子：与手写 `.geo` 逐字等价（GDS / 网格标签相同，测试断言） | 同 two_pads |
| `xmon_readout.{layout.yaml,meta.yaml}` + `xmon_readout_launch.geo` | `xmon` 模板（岛 + moat + 结 + 读出桨）→ λ/4 定长蛇形 `cpw_meander` → 手写发射焊盘，`ground: sheet` | 框架演示：模板 / 手写 `.geo` / 路由在同一模型混用；手写步骤声明端口给路由接；结自动进 circuit_model；长度闭环 | 粗网格秒级（演示件） |
| `cpw_route_demo.{layout.yaml,meta.yaml}` | 三对 `xmon` 的读出桨，同一对几何（Q_odd.RO 朝 +x → Q_even 转 90° 桨朝 +y，错位 900 × 900）右移三次只换环境：**R1** 默认横平竖直（骨架 L，蛇形在横臂上，腿上短下长）；**R2** `region` 是两个矩形的并集（右上角挖掉）→ L 淘汰、3 转弯绕路，腿按缝的形状不等长；**R3** `axis: free` 斜轴（Dubins RSR）。都是 fixed 3000 µm、腿数自动、两端 `lead` 60 µm；两端外挂面 → 总线 net = 步骤名；`ground: sheet` | `planner: cpw` v2（`docs/design/auto-route.md`）；`region:`（矩形并集）/ `axis:` 步骤键；`subsystems` 多出 `route_primitives`；region 太小 / 长度装不下都 raise | 粗网格十几秒（演示件） |
| `chen_2025_3x3.{layout.yaml,meta.yaml}` | Chen et al. 2025 (Nat. Phys. 21, 1489) 圆盘比特方格阵列的 3×3 切片：9 个 `disc_transmon` + 12 个 `bar_coupler`，几何全部是 Fig. 1a 照片量出值（`../docs/design/paper-chen2025-geometry.md`），无读出结构 | flip-chip 口径：顶片无地 `ground: none`，载片地 = `airbox.top_um: 5`（唯一物理旋钮）；21 个浮动结条目自动生成；`extract.blocks` = 12 个 SI §D 口径的孤立 QCQ 块（6 terminal） | 单块 100/4 order-2 ≈75 万 tets，本机 8 rank ~10 min：`build(m, out, solve=True, blocks=["H01"])`；整片 42 导体 ~9M tets 上云 |
| `chen_2025_3x3_hand.{layout.yaml,meta.yaml}` + `chen_2025_3x3_bars.geo` + `chen_2025_3x3_bar_macros.geo` | 同一 Chen 3×3，**几何逐点相同**的另一种写法：9 个 `disc_transmon` 照抄，12 个 `bar_coupler` 换成一步手写 `.geo`（从端口变量 `Q00_E_x…` 起画）+ `connect:` 认领爪；12 条耦合器的结写在 meta `circuit_model.qubits` | 「模板 vs 手写」对照件：手写步骤 `connect:`（grammar §4.1）；宏必须放 `Include` 文件；Physical 名 / GDS 多边形 / 结条目与模板路线相同（`test_chen_2025.py` 断言） | 同 chen |
| `chen_2025_cross.{layout.yaml,meta.yaml}` | Chen 2025「十字」：中心 Q11 四爪全开 + 四臂比特各留一只朝中心的爪 + 4 个 `bar_coupler` = 18 导体 / 9 个浮动结，**整片一次解**（meta 无 `extract.blocks`）。中心比特的 C_Σ 是真晶格口径（↔ Table SI 实测 α −192 ± 6 MHz），臂比特只有一只爪 = SI §D 孤立 QCQ 的比特侧口径，同一张网格作差 = 周边结构效应。100/4 网格 2.4 M tets，上云解（`.claude/session/2609180210.md`） |
| `sung_2021_device.{geo,meta.yaml}` | Sung et al., PRX 11, 021058 三体 tunable-coupler 的简化重现（手写 `.geo` + `qlib.geo` 宏） | **外部物理锚**：三个浮动 transmon 的 C_Σ、β 对论文；`ground::` 角色 + 开放边界 + `Include` 宏库 | 18.5M 未知量，**峰值内存 ~154 G** |
| `sung_2021_xmon.{geo,meta.yaml}` | 同一论文器件的**真拓扑**（接地 Xmon ×2 + 梳齿 coupler），~20 个照片量出参数，无调参 | 对论文的**无调参预测**（分清「标定命中」与「预测精度」，`docs/report/Aug27/04` §8）；`XMON` 宏；接地单岛写法 `island:` | 80/2 order-2 ~13M tets，需 384 G 远端机 |
| `sung_2021_xmon_traced.{geo,meta.yaml}` | 同一照片的逐点描摹（`tools/micrograph_to_geo.py` 生成，426 顶点） | 参数化版的保真参照；`POLY` 宏 | 15.4M tets，峰值 168 G |
| `qlib.geo` | 手写路线的 OCC 宏库：`PAD` / `POLY` / `XMON` / `CPW` / `JUNCTION` / `GROUND_CUTOUT`，面 tag 回 `sret` | 被 sung 例子 `Include`；纯几何宏，Physical 名由调用点打；⚠ `Call X;` 独占一行 | — |
| `lib/` | **模板库**：6 个模板（各 = `.yaml` 接口 + `.geo` 局部坐标几何）+ 宏库 `cpw_macros.geo` | 见下一节 | — |

## `lib/` 模板库

模板 = **同名两个文件**：`<name>.yaml` 是接口（参数默认值、层槽位、哪些输出面是岛 / 外挂 / 蚀刻、结、端口、记账量），
`<name>.geo` 在局部坐标画几何、**不打 Physical 名、不定义 Macro**，把面 tag 表 / 端口 / 长度写进输出变量。
版图里 `templates: [lib]` 后按名字实例化；编排器写入参数 → merge → 变换到位 → 读回输出 → 按实例名挂 Physical。全部语法在 grammar §4.2。

| 模板 | 类型 | 岛（component 名） | 外挂面 / 端口 | 结 | 主要参数 | 用在 |
|---|---|---|---|---|---|---|
| `pad` | 放置 | 1（= 实例名） | 端口 E/N/W/S = 四边中点，宽 = 边长 | — | `w` `h`；`gap` > 0 出蚀刻 pocket | `two_pads.layout.yaml` |
| `xmon` | 放置 | 1（= 实例名） | 可选读出桨 RO（外挂面 + 同名端口，`ro` 开关） | 北臂端 → 地 → `island:` 条目 | `arm_w` `arm_L` `gap` `jj_w` `ro_*` | `xmon_readout.layout.yaml` |
| `cpw_meander` | **连接** | 1 = 路由体（并入端点 net） | 两端由 `from` / `to` 给定，宽度继承 | — | `R` `n_legs` `gap`；步骤 `length:` 定长 | `xmon_readout.layout.yaml` |
| `cpw_route` | **连接 + 自动布线**（`planner: cpw`） | 1 = 路由体（并入端点 net） | 两端由 `from` / `to` 给定，**不必正对**，宽度继承；步骤可给 `region:`（矩形或矩形并集）与 `axis:`（框架角，默认 0 横平竖直；`free` = Dubins） | — | `R` 最小弯半径、`n_legs`（0 = 按余量自动取最小可行）、`gap`、`lead` 端口引出直段（弧从其后开始，0 = 关）；步骤 `length:` 定长（骨架直段上放蛇形，每个弯按余量独立外推，腿可不等长）；几何 = 引出 + 端弧 + 直段 / 圆角 + 蛇形，`docs/design/auto-route.md` | `cpw_route_demo.layout.yaml` |
| `disc_transmon` | 放置 | 2：`<实例>_a` / `<实例>_b` 两半盘 | 4 只可选爪 E/N/W/S（外挂面 + 同名端口，`claw_*` 开关），电学归接上来的耦合器 | 跨缝 a → b → `islands:` 浮动条目 | `dia` `slot` `slot_deg` `gap` `claw_t` `claw_deg` `stub` `bar_w` `jj_w` | `chen_2025_3x3.layout.yaml` |
| `bar_coupler` | **连接**，2 岛 | `body: bar`（= 步骤名，含两端爪）+ `<步骤名>_pent` | 两端接 `disc_transmon` 的爪端口 | 条 → 板 → `islands: [H, H_pent]` | `pent_w` `pent_wall` `pent_h` `pent_gap` `pent_off` `jj_w`；`mirror: x` 翻五边形侧 | `chen_2025_3x3.layout.yaml` |
| `cpw_macros.geo` | 宏库 | — | — | — | `LIB_CPW` / `LIB_CPW_ARC` / `LIB_CPW_MEANDER`，入参出参 `_lib_*` | 被 `cpw_meander.geo` / `disc_transmon.geo` `Include` |

用法一眼看：

```yaml
templates: [lib]
steps:
  - {template: xmon, name: Q1, at: [0, 0], layers: {metal: m1, jj: jj}, E_J: 12.2GHz}          # 放置型: at / rot / mirror
  - {template: disc_transmon, name: Q00, at: [0, 0], layers: {metal: ta, jj: jj}, E_J: 12.4GHz,
     params: {claw_W: 0, claw_S: 0}}                                                            # 没邻居的方向关掉爪
  - {template: bar_coupler, name: H00, from: Q00.E, to: Q10.W, layers: {metal: ta, jj: jj}, E_J: 21.1GHz}   # 连接型: from / to
  - {template: cpw_meander, name: R1, from: Q1.RO, to: F0, params: {gap: 6}, length: {mode: quarter_wave, f_r: 7GHz, film_nm: 200}}
```

- **层**：模板只声明槽位（`metal: conductor`、`jj: junction`），实例上 `layers: {metal: <芯片层>, jj: <芯片层>}` 映到 meta `layers:` 表；层的性质由芯片决定。
- **结**：模板有 `junction` 的步骤必给 `E_J` / `L_J` / `squid` 之一，编排器自动生成 `circuit_model.qubits` 条目（meta 不用再写）。
- **外挂面**：桨 / 爪由模板画，电学归属由连上来的路由决定；画了没人连 → raise，用 `params: {ro: 0}` / `{claw_W: 0}` 关掉。
- **看形状**：`build_gds(compile_layout(m), m, out)` + `render_gds_png`，或直接 `build(m, out)` 出 `<stem>.gds.png`。

**写自己的模板**（照抄样板）：

| 要做的 | 抄哪个 | grammar |
|---|---|---|
| 单岛放置型 | `pad`（最小完整对） | §4.2.1 |
| 岛 + 蚀刻 + 结 + 可选外挂 | `xmon` | §4.2.4 |
| 端口到端口的定长路由（两口正对） | `cpw_meander` | §4.2.5 |
| 两口不正对的自动布线（区域可拼接、定长、横平竖直或自由角） | `cpw_route`（`planner: cpw`，几何由 `route.py` 规划、`.geo` 只逐段 Call 宏） | §4.2.2 `planner` / `docs/design/auto-route.md` |
| 多岛 + 多只可选外挂 + 浮动结 | `disc_transmon` | §4.2.6 |
| 连接型多岛（`body:`）+ 跨岛结 | `bar_coupler` | §4.2.5 |
| 复用几何宏 | `cpw_macros.geo`：include guard、`LIB_` / `_lib_` 前缀、`Call` 独占一行 | §4.2.7 |

`.geo` 侧三条硬规矩：不打 Physical 名；不定义 Macro（宏放 include-guard 库里）；临时变量 `_` 前缀。
输出变量漏赋会被 NaN 置毒抓到，条件输出（`If (flag != 0)`）在 yaml 里挂同一个 `if: flag`。

## 跑起来

v4 只有 Python API（没有 CLI），入口是 `quantum_dsl.build`：

```bash
# conda env qdsl313 (Python 3.13 + gmsh + gdstk + shapely); 仓库根目录执行
P=~/miniconda3/envs/qdsl313/bin/python
export PYTHONPATH=src

# 1) 不求解: GDS (+ PNG 预览) + 3D 网格 + Palace config + manifest (几秒)
$P -c "from quantum_dsl import build; print(build('examples/two_pads.meta.yaml', 'build/two_pads'))"

# 2) 分块提取: 派生 block_A.geo / block_B.geo 各自网格与 config, 并对 A↔B 告警
$P -W always -c "from quantum_dsl import build; build('examples/two_pads_blocks.meta.yaml', 'build/blocks')"

# 3) 真实求解 → 电容矩阵 → 哈密顿量 (需要 Palace; WSL 上 build() 自动注入 HWLOC_COMPONENTS=-gl)
PALACE_BIN=/path/to/palace $P -c "from quantum_dsl import build; \
  r = build('examples/two_pads.meta.yaml', 'build/two_pads', solve=True); \
  print(r['capacitance'].maxwell_fF); print(open(r['results']).read())"

# 4) 版图例子只解一块 (跳过整片网格): 写 build/chen/block_H01.results.yaml
QDSL_PALACE_NP=8 PALACE_BIN=/path/to/palace $P -c "from quantum_dsl import build; \
  build('examples/chen_2025_3x3.meta.yaml', 'build/chen', solve=True, blocks=['H01'])"
```

预期（3）：`maxwell_fF ≈ [[24.53, -1.95], [-1.95, 24.54]]`（对头注 golden <2%），
`results.yaml` 里 `f01_GHz ≈ 9.40 / 9.40`、`g_MHz ≈ 376`。

sung 例子的跑法（远端大内存机）见 [`../docs/report/Aug27/03-复现与演示.md`](../docs/report/Aug27/03-复现与演示.md)
Demo F；`tools/palace_remote.sh` 是把 Palace 调用透明转到远端的 `PALACE_BIN` 垫片。

## 写自己的例子

**版图路线（推荐，grammar §4）**：`lib/` 里挑模板，写 `<name>.layout.yaml`（steps：放置 / 连接 / 手写 `geo:` 步骤）+ meta
（`layout:` 顶替 `geo:`，加 `layers:` 表，其余字段不变），`build()` 一样跑。始终是两个文件：版图 = 几何源，meta = 物理与计算域。
库里没有的形状先用手写 `geo:` 步骤补（只增不改，可 `frame:` 到某实例局部坐标，可声明端口给路由接——`xmon_readout_launch.geo` 就是），
用顺手了再升级成模板放进 `lib/`。

**手写路线（grammar §2）**：

1. 画 `.geo`：每个语义面挂 `Physical Surface("role::layer::component::primitive")`，role ∈ {metal, ground, jj}；
   **component 段 = 电学岛（net）**，浮动 transmon 的两块 pad 必须是不同 component（如 `QB1_t` / `QB1_b`），器件归组写在 meta 的 `circuit_model.islands`。
2. 写 `*.meta.yaml`：照 `two_pads.meta.yaml` 抄骨架；有片上 ground 时可用 `solver: {outer_boundary: open}`（见 sung）。
3. `build(meta, out, solve=False)` 先看 GDS 与网格对不对，再 `solve=True`。
4. 报数前做两档网格（如 40/4 与 20/2）——单网格数字在复杂几何上有百分位级不确定度。
