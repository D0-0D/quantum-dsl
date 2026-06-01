# Speaker Guide — DSL v3 + Gmsh 演示

> **使用方式**：
> - 右半屏放 `dslv3_gmsh_presentation.html` 导出的 PDF（或直接打开 HTML）。
> - 左半屏放 **`examples/dsl/notebooks/dslv3_demo_commands.ipynb`**（用 metal-env kernel）和 PowerShell 终端各一份。
> - notebook 的 cell 是按幻灯片顺序排的，演讲时直接 Shift+Enter 就行；终端用来跑全屏的 GUI demo。
> - 本文件**不要展示给观众**；它是给主讲人的脚本。
>
> **背景速记**：
> - 听众和我自己都不太熟 Gmsh —— 凡是涉及 OCC / mesh field / physical group 的概念，**先讲一句"用人话说"**，再切代码。
> - YAML / IR / kwarg 单位都是 **mm float**，adapter 入口 × 1e-3 转 SI —— 单位是常被问的点，第一次提到就要强调。
> - 不实例化 qlibrary、不走 `QGmshRenderer` —— 这是和"以前的玩法"最大的差异，每一页都可以顺手提一句。
>
> **环境提示**：演示用 conda env `metal-env`（Python 3.10-3.12 + qiskit-metal + gmsh + meshio）。
> ```powershell
> C:\ProgramData\anaconda3\envs\metal-env\python.exe ...
> ```

---

## Slide 1 — Cover

**说什么**（30 秒）：
> 这个分支 `full_chain` 上做了一件事：让 qiskit-metal 直接吃 YAML，不绕 Python qlibrary。同一份 YAML 出两条线 —— 左路出 Metal QDesign（GUI/GDS），右路出 Gmsh 网格喂给 EM 求解器。今天讲实现，最后给个端到端 demo。

**不要做**：
- 不要展开介绍 qiskit-metal 是什么。听众假设是项目内人员。

---

## Slide 2 — DSL v3 是什么 / 边界

**左屏打开**：
- `src/qiskit_metal/toolbox_metal/dsl/schema.py` —— 滚到 L40-L46，让大家看 `CURRENT_SCHEMA` 和 `ROOT_KEYS`。
- 说"所有顶层 key 在这里枚举，加新段就要更新这个 set"。

**重点说**（边界部分，**这是问答区**）：
- "DSL v3 **不**是 qlibrary 的封装层" —— 它直接写 `qgeometry` 表，跳过 `TransmonPocket(design, ...)` 这种 Python 实例化。
- "DSL **不**依赖 `QGmshRenderer`" —— 这是关键，因为 `QGmshRenderer` 假设 design 已经存在；我们要让 YAML → mesh 不经过 Metal design 也能跑（轻装环境）。

**预期问题**：
- Q: "那 transmon_pocket 模板怎么办？" → A: "我们有自己的 component template 系统（`template_registry.py` L20-25），把 transmon_pocket 写成 YAML 模板，递归 `$extend: qcomponent → base_qubit → transmon_pocket`，Slide 6 会展开。"

---

## Slide 3 — 模块结构

**目标**：让听众建立"哪段代码在哪个文件"的索引。

**说什么**：
- DSL 核心 vs Gmsh adapter 两块，分别在同一目录下；命名前缀 `_gmsh_*.py` 的是 adapter 私有。
- 三段下方 examples 是"既是文档又是 smoke test"。`run_chain_gmsh_demo.py` 末尾的 assert（Slide 14 会跑）就是契约锁。

**左屏可以做**：
- 在终端 `ls src/qiskit_metal/toolbox_metal/dsl/` 让目录可视。
- `git log --oneline -5 src/qiskit_metal/toolbox_metal/dsl/` 显示最近 commits（可选，秀活儿）。

---

## Slide 4 — Workflow diagram (重点页, 慢讲)

**这是核心页**。建议在这里花 3-4 分钟。

**讲法**（自上而下顺着箭头走，不要跳）：
1. **顶部两个紫框** —— 两种 YAML 写法，左 primitive-native，右组件模板。强调"同一条流水线吃两种风格的输入"。
2. **build_ir 入口** —— `builder.py:393-488`。"唯一入口；从这里往下都是同步串行"。
3. **1 → 2 → 3 三步** 是**字符串层**：YAML 解析（拒重复 key）→ `$include` 递归 → `walk_substitute` 把 `${...}` 替换成具体值。**这一段没碰任何 shapely**。
4. **第 4 步 `_parse_components`** 是分叉点：YAML 里写 `type:` → 走模板路径（看 slide 5）；否则直接走 `_primitive_from_spec` 出 shapely。右上虚线框指向 slide 5。
5. **5 → 6** 顺次：`_derive` 算 bounds/路径长度/pin middle，`_parse_simulation` 校验 gmsh schema。
6. **DesignIR**：纯 dataclass，可以 pickle、可以 print。**枢纽**——下一页讲完模板细节后才接到 build_design / build_mesh。

**左屏 notebook**：跑 "Slide 4 — build_ir 主流水线" 两格，让 IR 真的打印出来。

**问答预案**：
- Q: "为什么不用 pydantic？" → A: "schema 校验在解析器里直接 raise，单位转换在 `_normalize_options` 集中；引入 pydantic 多一层 schema 维护成本，目前 dataclass 够用。"

---

## Slide 5 — transmon_pocket 模板继承链 (新增页)

**这页是 slide 4 第 4 步"type: ..." 分支的展开**。如果听众都没问过 transmon_pocket，可以快讲；问到了就慢讲。

**讲法**：
1. 左上 YAML：用户只写 `type: transmon_pocket` + `options:`。
2. `_parse_components` 看到 `type:` → 调 `expand_component_template`（component_templates.py:25）。
3. `inheritance_chain` 递归 resolve `extends` 字段；查 `BUILTIN_COMPONENT_TEMPLATE_PATHS`（template_registry.py:20-25）把三个 YAML 文件依次加载：
   - ① `qcomponent.yaml` —— 通用 transform（pos_x / pos_y / orientation）
   - ② `base_qubit.yaml` —— 加 `connection_pads` 容器和 `_default_connection_pads` 容器；声明 `each_entry_extends` merge rule
   - ③ `transmon_pocket.yaml` —— pad/pocket/junction 的具体几何 + connection_pads 的默认参数
4. 然后 `_deep_merge` 走四种属性：options（覆盖语义）、metadata（同）、geometry（**primitives/pins 是 concat，不是覆盖**！）、merge_rules（决定 connection_pads 子项怎么继承默认）。
5. 输出 `ComponentTemplateExpansion` → 再变成普通 `ComponentIR`，从这里和 primitive-native 路径汇合。
6. 关键点：**用 type 写法不会绕过任何后续 stage**，slide 4 之后的 5/6/DesignIR/两条出口完全一样。

**左屏 notebook**：跑 "Slide 5 — transmon_pocket 模板继承链" 三格。第三格演示 `design_tp.components['Q1'].metadata['template']['inherited']` 真的有三个名字。

**问答预案**：
- Q: "用户能自己写一个新 component template 吗？" → A: "可以，写一个 YAML 放任意位置，在 build_ir 调用时通过 `templates:` 注入；template_registry 的 `_inline_specs` 和 `base_dir` 路径都会查。"
- Q: "merge_rules 是干啥的？" → A: "看 base_qubit.yaml 的 `each_entry_extends: _default_connection_pads`。意思是用户写 `connection_pads.readout: {loc_W: 1}` 时，自动把 `_default_connection_pads` 的所有默认值并进 readout 这个 entry。`_apply_merge_rules`（component_templates.py:221）干的活。"

---

## Slide 6 — YAML schema 顶层

**说什么**：
- 一段一段过 vars → hamiltonian → ... → simulation。**重点是 vars 是怎么穿到 geometry 的**：左屏打开 `examples/dsl/yaml/chain_2q_native.metal.yaml` 滚到 L62-L75 的 `templates.transmon_pad_pair`，指 `"${circuit.Q1.pad_width}"`：
  > "你看这个字符串，YAML 里它是 str；进 IR 时 `walk_substitute` 把它替换成 `circuit.Q1.pad_width` 的解析结果。整字段是 `${...}` → IR 里保留原对象类型（float）；包含其它字符（比如 `"-${qx}"`）→ 字符串化等表达式 evaluator 再处理。"

**左屏 notebook**：跑 "Slide 6 — YAML 顶层" + "Slide 4 — build_ir 主流水线" 第一格的 `ir.circuit` 让大家看 `${c_q}` 真的解成 `6.5e-14`。

---

## Slide 7 — 表达式 / 模板 / 单位

**这一页主要是"为什么 YAML 里写 `"-${qx} + ${bus_attach}"` 不会变成字符串"。**

**左屏打开** `src/qiskit_metal/toolbox_metal/dsl/expression.py`：
- 滚到 L91-L108 `substitute_string`，指 `preserve_type` 分支。
- 滚到 L140-L195 `_eval_ast`，强调"AST 受限：只允许 Constant / Name / Attribute / Subscript / +−×÷。没有 import、没有函数调用、没有 lambda"。**这点对审计/安全是个好卖点。**
- 滚到 L126-L137 `_replace_unit_literals`，演示一个表达式里有 `12um` 时正则会替换成 `parse_value` 结果。

**左屏 notebook**：跑 "Slide 7 — `${...}` 表达式"，三个返回值分别是 `0.012`（float）、字符串 `"-1.2 + 0.34"`、`0.86`（AST 算出来）。

**单位说明（必讲）**：
> "整个 DSL 内单位是 mm float。`12um` 在 IR 里是 `0.012`，`18GHz` 是 `18e9`。直到 `gmsh_adapter._normalize_options` 入口，才一次性 × 1e-3 把长度转 SI 米。这条约定贯穿 YAML / kwarg / IR；Slide 16 会讲踩过什么坑。"

---

## Slide 8 — IR dataclasses

**说什么**：
- 4 个 dataclass，从小到大：`PrimitiveIR` → `PinIR` → `ComponentIR` → `DesignIR`。
- `PrimitiveIR.geometry` 是 shapely 对象（Polygon/LineString），单位 mm。
- `DesignIR.derived` 是计算出来的字段（bounds / path lengths / pin middles / 拆出来的 netlist endpoints），所有"二次信息"都在这里。

**左屏 notebook**：跑 "Slide 8 — DesignIR.derived" 两格 — 第一格是 Q1 的 bounds / center / pins，第二格是 connections 列表已经被拆成 `{component, pin}`。

---

## Slide 9 — build_design path

**说什么**：
- 这页是"左路"的全部 —— 把 IR 写进 `design.qgeometry` 三张表（path/poly/junction），再 `connect_pins`，最后把整个 IR 写进 `design.metadata['dsl_chain']`。
- `NativeComponent`（builder.py:138-148）是个**外壳**：`make()` 留空，数据在 `export_ir_to_metal` 里推；这样 GUI/GDS/EPR 这些下游不知道这个 design 是 DSL 出的。

**左屏 notebook**：跑 "Slide 9 — build_design (左路)" 三格 — 看 poly/path/junction 行数 + qgeometry 表 + net_info。

**可选终端命令**（如果有 GUI 时间）：

```powershell
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\scripts\run_chain_demo.py
```
**注意：开 MetalGUI 前关掉 jupyter kernel，PySide6 和 jupyter 容易抢端口。**

---

## Slide 10 — Gmsh primer (听众科普, 慢讲)

**这页是给"完全不熟 gmsh"的听众的。** 慢点。

**讲法**：
1. 先说"Gmsh **不是** 一个 EM 求解器" —— 这是最常见误解。它只生成几何 + mesh，物理量交给 Elmer / palace / HFSS 去算。
2. **三层概念**逐个解释，配上比喻：
   - **OCC kernel** = "AutoCAD 的核" —— 真正做 3D 布尔运算的引擎。我们调 `addBox / cut / extrude / fragment` 都是在调 OCC。
   - **Physical group** = "给一堆几何元素贴个标签"。下游求解器看到的不是 dimtag，是名字（"vacuum"、"gnd_layer1_sfs"）。改名 = 改契约。
   - **Mesh** = "把几何切成有限元单元"。size field 控制密度，generate(3) 跑算法。
3. 命名对照表：让听众建立"我们项目里 X 对应 gmsh 里的 Y"的索引。

**左屏 notebook**：跑 "Slide 10 — Gmsh 入门: 最小 OCC 调用"。一个 1×1×1 立方体，看 dimtag 输出 + node count。

**问答预案**：
- Q: "为什么不直接用 QGmshRenderer？" → A: "Renderer 假设 QDesign 已经存在；它会从 design.ls / LayerStackHandler 取信息。我们想让 YAML 在没装 PySide6 / 没有 design 实例的环境也能出 mesh —— adapter 的依赖白名单（slide 12）就是为了这个。"

---

## Slide 11 — EM 工具链中的位置

**说什么**：
- SVG 7 步是"YAML 到结果"的全链路。我们覆盖前 4 步（红色虚线框）。
- 后 3 步是真正的 EM 求解器，是**别人的代码**。我们的产物（`.msh` + named physical groups）就是和他们的接口。

**底部"什么时候不需要 build_mesh"** —— 这个三选一是常见决策：
- 只看 GUI / 导 GDS → 左路。
- 用 HFSS 自带 mesher → 左路 + QHFSSRenderer。
- 跑 Elmer / palace / 自己的 mesh 控制 → 右路（build_mesh）。

---

## Slide 12 — gmsh_adapter 模块分工

**说什么**：
- 5 个私有模块，每个管 1-2 个 stage。**`build_mesh` 是唯一对外入口**。
- 强调底部的依赖白名单 —— 这是架构的硬约束。

**左屏 notebook**：跑 "Slide 12 — adapter 依赖白名单"。会扫所有 `_gmsh_*.py` + `gmsh_adapter.py`，每个文件都应该是 `OK 0 hits`。当场证明白名单。

---

## Slide 13 — 7-stage pipeline (重点页)

**这是 gmsh adapter 最核心的一页。慢讲。**

**讲法**：
- 一行一行过 stage。每行用一句话说清楚"做什么"。
- **重点提**：
  - Stage B（GeomTracker）—— "OCC 的 fragment 会**改 tag**，我们必须有个表把旧 tag 映射到新 tag。`tracker.remap()` 就是这个。"
  - Stage E fragment —— "fragment 是 OCC 的'缝合'操作；两个共面的体放进 fragment，会被切成共享面的两个体。这步必须最后做，否则前面的 cut 拿到的 tag 是失效的。"
  - Stage F physical groups —— "名字 = 契约，改名通知下游"。
- 底部红字"顺序硬约束"是**最常被新人破坏的规则**。不按顺序，gmsh 会沉默地出错（mesh 跑出来但拓扑断了）。

**左屏可以做**（如果时间允许）：
- 打开 `src/qiskit_metal/toolbox_metal/dsl/gmsh_adapter.py` 跳到 `build_mesh` L355-L467，让大家看 stage A→G 在代码里的顺序，对照表格。

先读一下 speaker_guide.md 的内容。

Now let me look at the actual `build_mesh` code to understand the 7 stages in detail.

Let me check the GeomTracker and key helper functions to give you accurate detail.

好了，代码和 speaker guide 都看完了。我来把 Slide 13 这7个 stage 逐一讲清楚。

------

## Slide 13 — 7-stage Gmsh Pipeline 详解

`build_mesh()` 是唯一对外入口（[`gmsh_adapter.py:355`](https://claude.ai/epitaxy/src/qiskit_metal/toolbox_metal/dsl/gmsh_adapter.py)），里面顺序执行 A → G 七个 stage，**顺序是硬约束，不能乱**。

------

### Stage A — 2D 面片：IR primitives → `addPlaneSurface`

**做什么**：遍历每个 component 的 `PrimitiveIR`，把 shapely Polygon/LineString 转成 Gmsh 的 `addPlaneSurface()`。

**关键点**：

- 这一步还是纯 2D，没有厚度，相当于"在 XY 平面上描轮廓"
- 单位在进入 adapter 时已经统一乘 1e-3 转成 SI（米），YAML/IR 里一直是 mm

**比喻**：就像在白纸上描 qubit pad、bus 的轮廓线，还没有"厚度"这个概念。

------

### Stage B — 3D 挤出 + `GeomTracker` 登记

**做什么**：对每个 2D 面调 `extrude()`，按 `layer_stack` 里的 `thickness` 挤出成 3D 体（volume）。每创建一个 volume，就往 `GeomTracker` 里登记 `(component_name, primitive_name) → [volume_tag]`。

**为什么需要 GeomTracker**： OCC（OpenCASCADE）的 `fragment` 操作（Stage E）会**重新分配所有 dimtag**——你之前拿到的 tag 在 fragment 之后可能已经无效或被分裂成多个。GeomTracker 的 `remap()` 方法就是在 fragment 结束后，把旧的 `(dim, old_tag)` 映射到新的 `(dim, new_tag_list)`（见 [`_gmsh_geometry.py:103`](https://claude.ai/epitaxy/src/qiskit_metal/toolbox_metal/dsl/_gmsh_geometry.py)），让后续的所有操作都用正确的 tag。

**比喻**：每挖一块积木，就在本子上记"这块叫 Q1_pad_left"。Fragment 之后积木可能被切碎，用本子重新对号入座。

------

### Stage B' — Endcap + Port box（Fragment 之前的准备）

这是附属步骤，不算独立 stage，但很重要：open-pin endcap（开路引脚的封口）和 lumped port box 在这里画出来，**但不切**，等 Stage D 一起处理。

------

### Stage C — Ground plane + Vacuum box

**做什么**：

- `render_layer_grounds()` — 按 bounding box + layer_stack，为每层金属画一整片接地面（一个大矩形体）
- `render_vacuum_box()` — 在 chip 外围画一个真空盒（比 chip 大一圈，大小由 `airbox.side_buffer` 控制）

**为什么这时候才画**：ground plane 要比所有 qubit primitive 都大，必须在知道总 bounding box 之后才能定尺寸。

------

### Stage D — Boolean Subtract（cut）

**做什么**：`apply_cuts()` —— 把 qubit pad、bus trace 等 primitive 从 ground plane 里**"掏空"**（Boolean subtract）。

**关键点**：

- 所有标记了 `subtract=True` 的 primitive 都在这里从 ground 里减掉
- endcap box 也在这步从 ground 里减
- **cut 必须在 fragment 之前**——如果先 fragment 再 cut，tag 就乱了，且 OCC 拿到的 ground 是已经被缝合的体，行为不可预测

**比喻**：整片铜皮（ground），用 qubit 轮廓做"饼干切模"，把 qubit 下面那一块铜掏掉，留出绝缘间隙。

------

### Stage D' — 端口面解析（cut 后、fragment 前）

**做什么**：`resolve_port_surfaces()` —— cut 完之后，ground 上的"缺口边界"就暴露出来了，从这里筛出 port 的实际 face tag，存到 `tracker.ports`。

**为什么卡在这个位置**：cut 之后缺口才存在；fragment 之后 face tag 又会被重映射。所以必须精准地插在两者之间。

------

### Stage E — Fragment（核心！重映射）

**做什么**：`fragment_everything(tracker)` —— 把所有体一次性扔进 `gmsh.model.occ.fragment()`。

**fragment 是什么**：OCC 的"缝合"操作。两个相邻的体如果有共面，fragment 之后它们共享同一张面（而不是各自有一张重叠面）。这是 FEM 求解器要求的——网格节点必须在界面上对齐，不能有"两张重叠面各自有自己的节点"的情况。

**为什么重要**：

- fragment 完成后，`gmsh` 返回新的 dimtag 列表
- 代码里立刻调 `tracker.remap(old_to_new)` 把所有内部 tag 表更新
- 没有这一步，后面的 physical group 分配会挂在失效的 tag 上

**顺序硬约束来源**：cut 必须在 fragment 之前，因为 fragment 之后整个几何是缝合状态，再做 cut 行为未定义。

------

### Stage F — Physical Groups（契约）

**做什么**：`assign_physical_groups()` —— 把 tracker 里所有的 volume/surface tag 按命名规则打上 gmsh physical group 标签（名字）。

**命名规则**（Slide 14 的表格）：

- `{component}_{primitive}` — 组件的 3D 体
- `{component}_{primitive}_sfs` — 该体的外表面（`_sfs` = surfaces）
- `gnd_layer1`、`vacuum`、`substrate_layer3` — 特殊结构
- `{port_name}_lumped_port` — lumped port 面

**为什么叫"契约"**：下游 Elmer/Palace 的 SIF 文件里写的是 physical group **名字**（比如 `Target Bodies(1) = $ vacuum`）。改名 = 改 API，必须通知下游。

------

### Stage G — Size fields + `generate(3)` + 写文件

**做什么**：

1. `define_size_fields()` — 设 mesh 密度场（细节区域更密，真空区域更稀）
2. `generate_mesh(dim=3)` — 真正跑 Gmsh 的 meshing 算法，生成四面体
3. `write_mesh()` — 写 `.msh` 文件（可选，`output_path=None` 时跳过）

------

## 顺序约束总结

```
A(2D面) → B(extrude+登记) → C(ground+vacuum) → D(cut) → D'(port面解析) → E(fragment+remap) → F(physical groups) → G(mesh)
```

**最常见的破坏点**：把 E（fragment）提前放到 D（cut）之前 —— gmsh 不报错，但 mesh 拓扑断了（共面体各自有重叠面，FEM solver 算出的场在界面处不连续）。这是"沉默地出错"，最难排查。

---

## Slide 14 — physical group 命名

**说什么**：
- 11 行表格 = 全部命名约定，没有别的。
- 重点：**`{component}_{primitive}` 是 component 体；`{component}_{primitive}_sfs` 是它的外表面**。`_sfs` 后缀是"surface"。
- `_sanitize` 把 `Q1.bus.pad_left` 这种 dotted 名转成 gmsh 合法的 `Q1_bus_pad_left`。
- **重名直接 raise** —— 这是设计选择，宁可炸不静默叠加。

**左屏 notebook**：跑 "Slide 14 — _sanitize 行为"。`Q1.bus.pad_left → Q1_bus_pad_left`，`2um_pad → g_2um_pad`，空串 → `unnamed`；最后打印 `PHYSICAL_GROUP_NAMING` 全部 11 条模板。

---

## Slide 15 — 端到端 demo (现场跑!)

**这是 hero moment。在这里现场跑 demo。**

**左屏 notebook**：跑 "Slide 15 — 端到端 build_mesh" 两格 (build_mesh + meshio 回读)。在 jupyter inline 模式下安全。

**终端备选**（更有"现场感"）：
```powershell
# 进 worktree, 跑 demo (15-20 秒, 写出 mesh)
cd D:\BaiduSyncdisk\vsCOde\circuit\qiskit\qiskit-metal-worktrees\dyk07-main
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\scripts\run_chain_gmsh_demo.py --output examples\dsl\outputs\chain_2q.msh
```

预期输出（应该和幻灯片左侧的截图基本一致）：
```
schema           : qiskit-metal/design-dsl/3
components       : ['Q1', 'Q2', 'bus']
bounding_box (m) : xmin=-0.0018, ymin=-0.00046, xmax=0.0018, ymax=0.00046
mesh file        : build/chain_2q.msh
mesh size (bytes): 101_768
physical groups  : 17
  - Q1_jj_jj (dim=2, n_tags=1)
  ...
PASS: native DSL chain meshed via gmsh_adapter
```

**然后**（视觉冲击）：
```powershell
# 打开 Gmsh GUI 看几何 + 物理组
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\scripts\run_chain_gmsh_demo.py --gui
```
在 Tools → Visibility → Physical groups 里 toggle 几个 group 显示，比如：
- 关掉 `vacuum`，露出真空盒里的 chip 结构。
- 单独显示 `gnd_layer1` —— 整片接地。
- 单独显示 `Q1_pad_left` —— 一对 qubit pad 之一。
- 单独显示 `bus_center_trace` —— bus CPW 中心导体。

**右侧 Elmer SIF 片段说明**：
- 求解器只认 physical group 名字。`Target Bodies(1) = $ vacuum` 就是"对名为 vacuum 的体施加 Material 1"。
- 这是我们和下游的接口 —— 改名要通知。

**问答预案**：
- Q: "fine mesh 怎么开？" → A: "`--fine` flag，用 YAML 里 `simulation.gmsh.mesh` 的细 mesh 设置；会跑出 ~130MB 文件，10 多分钟。**演示绝对别开**。"

---

## Slide 16 — 单位 / 踩坑落字

**说什么**：
- 这一页是"防呆指南"。
- 重点：**kwarg 和 IR 同语义都是 mm 字符串/float，不是 SI**。`build_mesh(yaml, options={"mesh": {"max_size": 0.001}})` 是 0.001 mm = 1 μm，**不是** 1 mm。
- `_check_mesh_length_mm` (L174-191) 在 [10 nm, 10 cm] 之外直接 raise，这是经验值（小于 10 nm 比单原子还细，大于 10 cm 比 chip 还大，都是单位误用）。
- Windows kernel 安全是个**真实踩过的坑**：matplotlib 必须先 import + 跑一次 plt.subplots 预热，再 `gmsh.initialize()`。否则 gmsh 的 freetype / OpenMP DLL 抢占 native symbol，下一次 plt 调用 segfault。
  - **这条已经写进 user memory** (`feedback_gmsh_matplotlib_dll_order`)，notebook 里也有体现。

**左屏 notebook**：跑 "Slide 16 — 单位防呆"。会真的 raise `ValueError("outside the sane range")`。

**可选**：打开 `examples/dsl/notebooks/gmsh_mesh_demo.ipynb` 滚到第一个 code cell，让大家看 `KMP_DUPLICATE_LIB_OK` 和 matplotlib warm-up。

---

## Slide 17 — 测试覆盖

**说什么**：
- 两个测试文件 ~1290 行，把"哪些不变性必须成立"硬编码下来：
  - **左**：DSL 核心 —— IR 解析、模板展开、netlist 校验、derived 字段。
  - **右**：Gmsh adapter —— input 校验、SI 单位、layer_stack schema、必出 physical group、lumped port 单顶面、symmetry plane truncation。
- 重点提**契约测试** —— `test_m3_required_physical_groups` 锁了 `gnd_layer1 / substrate_layer3 / vacuum` 三个名字。改名要同步改测试。

**左屏 notebook**：跑 "Slide 17 — 跑测试"（subprocess 包了 pytest 调用）。~5 秒，PASS。

---

## Slide 18 — 总结 / 下一步

**说什么**（30 秒收尾）：
> 三件事记住：(1) **一份 YAML，两条出口** —— 左路 QDesign，右路 .msh。(2) **IR 是枢纽** —— 纯 dataclass，没有 gmsh / qiskit / matplotlib 依赖。(3) **physical group 名字是契约** —— 改名通知下游。
>
> 下一步是 M6：真正接 Elmer 跑 capacitance，把 C 矩阵 round-trip 回 hamiltonian —— 那时整个 full_chain 才闭环。

**问答**：留 5-10 分钟。

---

## 通用回退 / 救场

| 情况 | 怎么办 |
|------|--------|
| gmsh GUI 卡住不出 | Ctrl+C 杀掉，回到幻灯片 14 左侧的截图，"假装"演示。 |
| `build_mesh` 跑出 ValueError | 八成是 mesh kwarg 单位错了；快速看 `_check_mesh_length_mm` 报的范围。 |
| 找不到 metal-env conda | 改用 `python -m pip install gmsh meshio shapely qiskit-metal` 在临时 venv 里跑，不过 PySide6 会缺。 |
| 听众卡在"OCC 是什么" | 切到 Slide 9，重新讲 OCC kernel = "Open CASCADE Technology, OpenSCAD/AutoCAD 那种 3D 几何核"。 |
| 听众卡在"physical group 和 dimtag 区别" | dimtag 是 OCC 给的内部 ID；physical group 是我们给一组 dimtag 取的**名字**。求解器看名字，OCC 看 ID。 |

## 时间分配建议（总 30 分钟）

| 段 | Slide | 时间 |
|----|-------|------|
| Intro | 1-3 | 3 分钟 |
| Workflow + 模板继承 | 4-5 | 5 分钟（慢讲, 含 transmon_pocket 分叉） |
| YAML / 表达式 / IR | 6-8 | 6 分钟 |
| build_design | 9 | 2 分钟 |
| **Gmsh primer** | 10-11 | **4 分钟**（听众不熟） |
| Adapter 内部 | 12-14 | 4 分钟 |
| **现场 demo** | 15 | **4 分钟**（含 GUI） |
| 收尾 | 16-18 | 2 分钟 |

---

## 演示前 5 分钟 checklist

- [ ] `metal-env` conda 激活，`python -c "import gmsh; print(gmsh.__version__)"` 能跑
- [ ] `cd` 到 worktree 根目录（`dyk07-main/`），不是 sibling `qiskit-metal/`
- [ ] `examples/dsl/outputs/` 目录可写（清空旧 `.msh` 文件）
- [ ] 打开 `examples/dsl/notebooks/dslv3_demo_commands.ipynb`，metal-env kernel，先把 setup cell 跑一遍预热
- [ ] VS Code 打开几个关键文件备用：`schema.py`, `ir.py`, `gmsh_adapter.py`, `yaml/chain_2q_native.metal.yaml`, `yaml/transmon_pocket_2q.metal.yaml`, `dsl_templates/qubits/transmon_pocket.yaml`
- [ ] 关掉所有其它 Jupyter kernel（避免 PySide6 抢端口）
- [ ] 把 HTML / PDF 放右半屏；左半屏：上面 jupyter notebook，下面 PowerShell
- [ ] 跑一次 `scripts/run_chain_gmsh_demo.py` 预热（gmsh 第一次 initialize 慢）
