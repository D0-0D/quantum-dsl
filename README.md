# quantum_dsl

一个面向 **超导量子芯片版图** 的 DSL。它用一条 **原生 Gmsh `.geo` 几何 + 物理元数据
sidecar** 的双层描述，分叉产出两路工件：

- **gdstk → `chip.gds`**（2D 版图，绕过网格）
- **Gmsh → `chip.msh` → Palace**（Electrostatic）→ **电容矩阵** → 电路模型（transmon
  Hamiltonian）→ `chip.results.yaml`

GDS 可再经 **GDSFactory / matplotlib** 预览成 PNG。

> 这是一个 **持续演进中** 的项目。当前阶段聚焦：*带圆角的多边形 cell + 静电学电容矩阵*。
> 本体一路一直在动 —— 权威的"现在到哪了"看 `.claude/status.md`，里程碑清单看 `.claude/plan.md`。

---

## 两条几何前端，一个共享物理模型

```
                         ┌─ gdstk ──────────────→ chip.gds  ──(可选)→ PNG 预览
 Layer-1  *.meta.yaml ─┐ │
 (物理元数据)           ├─┤  共享 physical-group 模型
 Layer-2  *.geo ───────┘ │
 (几何, µm)              └─ Gmsh → chip.msh → Palace(Electrostatic)
                                              └→ C 矩阵 → 电路模型 → chip.results.yaml
```

1. **原生 Gmsh `.geo` 路径（主线，本次 pivot）**
   - **Layer-1 物理元数据**：独立的 `*.meta.yaml` sidecar（材料、`eps_r`、mesh、GDS 层映射、
     solver），复用 `simulation.gmsh` 词表 + `gds` / `solver` 小节。
   - **Layer-2 几何**：原生 Gmsh `.geo`（OpenCASCADE kernel），以 **微米 (µm)** 书写。
   - 入口：`quantum_dsl.dsl.geo_build` / `build_geo()`。

2. **Legacy YAML 路径（次要，仍保留）**：`.metal.yaml` 设计 DSL（`build_ir` / `build_design`）
   → qiskit-metal `QDesign`，并可经 `gmsh_adapter.build_mesh` → `.msh`。其中 `build_ir`
   被主线的 **emit_geo cell 桥** 复用（见下）。

### 绑定 key

几何 / GDS / Palace / Layer-1 元数据之间，靠作者在 `.geo` 里写的 **一个结构化 Gmsh physical
名** 绑定：

```
"<role>::<layer>::<component>::<primitive>"
```

`role ∈ {metal, ground, jj, substrate}`（面）或 `{port, symmetry}`（marker）；`layer` 是
`meta.yaml` 里 `layer_stack` 的整数 key。loader 把这些名字映射到既有的 `PHYSICAL_GROUP_NAMING`
字符串，`assign_physical_groups` 在 `fragment` 之后逐组重新登记，所以 **输出名与 legacy 路径
逐字节一致**（Palace 对几何来源无感）。

> ⚠ **JJ 是 lumped 元件**：会写进 GDS（layer 20），但在静电学路径里 **不作为导体网格化**
> （`populate_tracker_from_geo` 把它移除 —— 否则会把焊盘对短路、毁掉四面体网格）。

---

## 目录结构

```
quantum_dsl/
├── pyproject.toml
├── README.md
├── gmsh_dsl_notes.md             # Gmsh .geo 语言速查
├── src/quantum_dsl/
│   ├── __init__.py               # 懒加载公共 API（gmsh/gdstk/gdsfactory 不会被 eager import）
│   └── dsl/                      # 核心实现子包
│       ├── geo_build.py          # ★ 主入口 build_geo() + CLI
│       ├── _gmsh_geo_source.py   # .geo ingest：load_geo / split_geo_name / populate_tracker_from_geo
│       ├── geo_emit.py           # M5a：emit_geo + elaborate_cells（v3 模板 → 扁平 .geo，纯 shapely）
│       ├── gds_adapter.py        # gdstk → GDSII（µm verbatim, unit=1e-6）
│       ├── palace_adapter.py     # Palace Electrostatic config / run_palace / WSL 回退
│       ├── circuit_model.py      # M6：C 矩阵 → transmon Hamiltonian（逆电容 LOM）
│       ├── gds_viz.py            # M7：preview_gds（gdsfactory + matplotlib 回退）
│       ├── gmsh_adapter.py + _gmsh_*.py   # geometry / layers / mesh / physical groups
│       ├── builder.py            # legacy build_ir / build_design（build_ir 被 emit_geo 复用）
│       ├── parsers/ schema.py ir.py _units.py …
│       └── …
│   └── dsl_templates/            # 内置组件模板 YAML（必须是 dsl/ 的同级目录）
│       ├── core/{qcomponent,base_qubit}.yaml
│       └── qubits/transmon_pocket.yaml
├── examples/dsl/                 # 见 examples/dsl/README.md（geo/ 主线示例）
└── tests/                        # pytest 套件 + tests/fixtures/（含 two_pads 参考）
```

> 不变量：`template_registry._builtin_template_root()` 用 `Path(__file__).parent.parent /
> "dsl_templates"` 定位模板，所以 `dsl_templates/` 必须始终是 `dsl/` 子包的同级目录。

---

## 安装

需要 Python `>=3.10,<3.13`（验证于 3.11）。**测试与端到端链路在 conda `metal-env` 里跑**
（qiskit-metal 0.5.1 + gmsh 4.11.1 + gdstk 0.9.62 + shapely 2.0.7 + gdsfactory 9.2.2；
Palace 0.16 经 spack）。

> ⚠ **qiskit-metal 0.5.x 只在 conda-forge，PyPI 上没有**（PyPI 停在 0.1.5）。先用 conda 建好带
> qiskit-metal 的环境，再 `pip install`。完整、跨平台的版本约束见仓库根 `requirements.txt`
> （含每条上下界的理由：gdsfactory 须 `<9.3` 否则拉 numpy≥1.26 破坏 qiskit-metal 的 `numpy~=1.24`；
> kfactory 1.2.2 在 pydantic≥2.11 下 import 失败，故 `pydantic<2.11`）。

```bash
# 跨平台推荐路径（Windows / Linux 同）：
conda create -n metal-env -c conda-forge python=3.11 qiskit-metal
conda activate metal-env
pip install -r requirements.txt   # gmsh + gdstk + gdsfactory(<9.3) + pydantic(<2.11) + pytest

# 或者按需装可编辑包 + extras（从仓库根目录）：
pip install -e .
pip install -e ".[gmsh]"   # Gmsh 网格分支
pip install -e ".[gds]"    # GDSII 分支（gdstk）
pip install -e ".[viz]"    # GDSFactory 预览后端（已带 <9.3 / pydantic<2.11 约束；缺失时回退 matplotlib）
pip install -e ".[test]"   # pytest
```

可选依赖均 **懒加载**：`import quantum_dsl` 不会拉入 gmsh / gdstk / gdsfactory。
**Palace** 需单独安装（这里经 WSL spack 提供 `palace` 0.16，`PALACE_BIN` 持久化在 env 里；
`run_palace` 会在 Windows 上自动回退到 WSL）。

---

## 端到端用法

### CLI

```bash
# 物理 sidecar 的 `geo:` 键指向配套 .geo；输出落在 --out-dir。
PYTHONPATH=src python -m quantum_dsl.dsl.geo_build \
    examples/dsl/geo/chip_layout.meta.yaml --out-dir build/geo_demo --png

#   --geo PATH      显式覆盖 sidecar 的 geo（cells: 块存在时 geo 可省）
#   --run-palace    生成 config 后真的调用 Palace（非 --dry-run 才会解出 C 矩阵）
#   --dry-run       只让 Palace 校验/划分，不求解
#   --png [PATH]    把 chip.gds 渲染成 PNG 预览
```

实际产物（`chip_layout` 示例）：

```
GDS         : build/geo_demo/chip.gds
MSH         : build/geo_demo/chip.msh
Palace JSON : build/geo_demo/chip.json
physical_groups (9): ['BUS_trace_sfs', 'Q1_pad_bot_sfs', 'Q1_pad_top_sfs',
  'Q2_pad_bot_sfs', 'Q2_pad_top_sfs', 'gnd_layer1_sfs', 'substrate_layer3',
  'vacuum', 'vacuum_outer']
Preview     : build/geo_demo/chip.png (backend=matplotlib, layers=[(1, 0), (20, 0)])
```

加 `--run-palace`（非 dry-run）会真正解出电容矩阵并写回 `chip.results.yaml`。`two_pads`
参考（`tests/fixtures/two_pads.*`，干净的 2 导体）解得 Maxwell C 矩阵
`[[24.73, -1.98], [-1.98, 24.73]]` fF（对角 +、非对角 −、对称），若 sidecar 带 `circuit_model:`
块则进一步导出 tier-2 transmon Hamiltonian（`L_J=10 nH`：`E_C≈0.79 GHz`、`f01≈9.37 GHz`、
两 qubit 间 `g≈374 MHz`），写进 `chip.results.yaml`。

### Python

```python
from quantum_dsl.dsl.geo_build import build_geo

result = build_geo(
    meta_path="examples/dsl/geo/chip_layout.meta.yaml",
    out_dir="build/geo_demo",
    run_palace=False,
)
print(result["gds"], result["msh"], result["palace_json"])
```

### emit_geo cell 桥（M5a）

不手写 `.geo` 也行：在 sidecar 里写 `cells:` 块，列出 v3 组件模板实例
（`cell_type` + 唯一 `component` + `x/y/rot/layer` + `params`）。`elaborate_cells` 对每个实例
跑一遍 `build_ir`（复用整个 v3 前端），用 **预采样的 shapely buffer** 生成 **带圆角** 的
多边形，concat 成一份 `<stem>.elaborated.geo`，再喂给上面同一条链路 —— Palace 名字保持逐字节
一致。例：`examples/dsl/geo/cells_2q.meta.yaml`。

---

## 测试

```bash
# conda metal-env，src 不是 pip-installed → 设 PYTHONPATH
PYTHONPATH=src python -m pytest tests/ -q
# 单文件：
PYTHONPATH=src python -m pytest tests/test_geo_pipeline.py -q
```

当前：**314 passed, 3 skipped**。`metal-env` 已装 gdsfactory 9.2.2，故 gdsfactory 后端的 2 个测试
（`to_gdsfactory_component` / `preview_gdsfactory_backend`）**通过**。3 个 skip = 1 个门控 live Palace
测试（`QDSL_RUN_PALACE=1` 时通过）+ 2 个 “gdsfactory 缺失时回退 matplotlib” 路径测试（因 gdsfactory
已装而互斥跳过）。

---

## Provenance / 许可证

`quantum_dsl` 的 legacy YAML DSL 与组件模板抽取自
[qiskit-metal](https://github.com/qiskit-community/qiskit-metal) 的
`qiskit_metal.toolbox_metal.dsl`；运行期仍 `import qiskit_metal`（单位解析、`draw` 几何助手、
`QComponent`）。许可证继承 qiskit-metal 的 **Apache-2.0**。
