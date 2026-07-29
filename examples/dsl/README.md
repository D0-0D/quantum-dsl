# 示例 — 原生 Gmsh `.geo` 路径

每个示例是一对 **`*.meta.yaml`（Layer-1 物理元数据）+ `.geo`（Layer-2 几何, µm）**，经
`quantum_dsl.dsl.geo_build` 分叉成 **GDS**（gdstk）和 **Palace 网格 + config**（Gmsh →
Electrostatic）。详见仓库根 `README.md`。

## 目录

```
examples/dsl/
├── README.md            本文件
└── geo/
    ├── chip_layout.geo        手写 .geo：CPW bus + 2 对 qubit 焊盘 + 2 条 JJ + 蚀刻 ground
    ├── chip_layout.meta.yaml  其物理 sidecar（layer_stack / airbox / mesh / gds / solver）
    ├── qlib.geo               .geo 宏库（PAD / CPW / JUNCTION / GROUND_CUTOUT），被上面 Include
    ├── cells_2q.meta.yaml     M5a emit_geo：用 cells: 块生成 .geo（无需手写几何）
    ├── sung_2021_device.geo         Sung 2021 三体可调耦合器（整片解）
    ├── sung_2021_device.meta.yaml   其 sidecar（含与论文的逐项对标表）
    └── sung_2021_device_blocks.meta.yaml
                               M8 分块提取：同一份 .geo，3 个 extract.blocks 分别解再拼装
```

> 干净、可复现的 **求解参考** 在 `tests/fixtures/`：`two_pads.*`（2 导体，已验过 live C 矩阵
> `[[24.73,-1.98],[-1.98,24.73]]` fF）与 `tiny_chip.*`（最小 smoke）。

## 跑起来

从仓库根、在 conda `metal-env` 里（`src` 非 pip-installed → 设 `PYTHONPATH`）：

```bash
# 1) 手写 .geo（M1）→ GDS + 网格 + Palace config + PNG 预览
PYTHONPATH=src python -m quantum_dsl.dsl.geo_build \
    examples/dsl/geo/chip_layout.meta.yaml --out-dir build/chip_layout --png

# 2) emit_geo cell 桥（M5a）→ 先生成 cells_2q.elaborated.geo，再走同一条链路
PYTHONPATH=src python -m quantum_dsl.dsl.geo_build \
    examples/dsl/geo/cells_2q.meta.yaml --out-dir build/cells_2q

# 3) 真正解电容矩阵（需要 Palace + PALACE_BIN）：用 two_pads 参考
PYTHONPATH=src python -m quantum_dsl.dsl.geo_build \
    tests/fixtures/two_pads.meta.yaml --out-dir build/two_pads --run-palace

# 4) 分块提取 + 拼装（M8）：每块一次独立解，再按共享节点名拼成一个系统
QDSL_MESH_ALGO3D=10 PYTHONPATH=src python -m quantum_dsl.dsl.geo_build \
    examples/dsl/geo/sung_2021_device_blocks.meta.yaml \
    --out-dir build/sung_blocks --run-palace --np 8
# 只看派生出的块几何（不划网格、不跑 Palace），用来在 gmsh GUI 里逐块目视检视：
PYTHONPATH=src python -m quantum_dsl.dsl.geo_build \
    examples/dsl/geo/sung_2021_device_blocks.meta.yaml \
    --out-dir build/sung_blocks --no-solve
```

产物：`chip.gds` / `chip.msh` / `chip.json`（+ `--png` 时的 `chip.png`；`--run-palace` 非
dry-run 时的 `chip.results.yaml`）。`cells_2q` 还会写出 `cells_2q.elaborated.geo`。
带 `extract:` 时每块另出一份 `block_<name>.geo`（落在 `out_dir`，进 `chip.manifest.yaml`
带 sha256）+ `block_<name>/{chip.msh,chip.json,postpro/}`。

## 分块提取：想在哪切，就在那里分 component

带 `extract:` 的 sidecar 把 **mesh 分支**改成「每块一次独立提取」（GDS 分支始终是完整图）。
两条硬规则，写在这里以免踩坑：

1. **切割面只能落在 component 边界。** 块 = component 名的集合，几何层只做「渲染 / 不渲染」，
   **不引入任何新的 OCC 布尔切割**（`occ.fragment` 对近邻不重叠几何本身就脆弱）。所以
   **想在哪切，就在那里分 component**。
2. **跨块的耦合只能靠共享节点名**（`nodes:` 把两块的 terminal 重命名成同一个名字，电容在那里
   叠加）。共享节点表达的是「同一个导体被两块各画了一半」——**不是**两块分离导体之间的互电容。
   所以：**想保住哪两个导体之间的耦合，就把它们放进同一个块。**

`ground::` 的孔（pocket / CPW gap）在派生块几何时**按窗口整体保留**，不论那个孔属于哪个
component —— 被排除的 component 留下一个「有洞、没金属」的空真空腔，等价于 qiskit-metal
`add_endcaps()`。若按 component 过滤孔集合，ground 金属会侵入本该是真空腔的区域，对地电容
静默偏高（实测在一个双 pocket 算例上 ground 面积 +7.1%）。

实测代价（`tests/fixtures/two_pads_blocks.meta.yaml`，与整片同 order/同网格的干净对照）：
自电容对角 **+1.03% / +1.06%**，而互电容 −1.98 fF → **0**（结构必然，见规则 2）。

## 两种写法

**手写 `.geo`**（`chip_layout.geo`）：OpenCASCADE kernel，正向金属 tone，CPW gap 用
`BooleanDifference` 从 ground sheet 蚀刻；每个面用 `Physical Surface("role::layer::comp::prim")`
标注（绑定 key，见根 README）。`qlib.geo` 提供 `PAD` / `CPW` / `JUNCTION` / `GROUND_CUTOUT` 宏。

**`cells:` 块**（`cells_2q.meta.yaml`）：列出 v3 组件模板实例，`emit_geo` 复用 `build_ir`
把它们 lower 成扁平、**带圆角**（预采样 shapely buffer）的 `.elaborated.geo`：

```yaml
cells:
  - cell_type: transmon_pocket
    component: Q1
    x: "-700um"
    params: {connection_pads: {}}
  - cell_type: transmon_pocket
    component: Q2
    x: "700um"
    params: {connection_pads: {}}
```
