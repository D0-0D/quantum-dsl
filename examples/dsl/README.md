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
    └── cells_2q.meta.yaml     M5a emit_geo：用 cells: 块生成 .geo（无需手写几何）
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
```

产物：`chip.gds` / `chip.msh` / `chip.json`（+ `--png` 时的 `chip.png`；`--run-palace` 非
dry-run 时的 `chip.results.yaml`）。`cells_2q` 还会写出 `cells_2q.elaborated.geo`。

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
