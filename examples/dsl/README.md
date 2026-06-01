# DSL v3 示例

Qiskit Metal 的 native YAML DSL（v3）。一个 `.metal.yaml` 描述芯片设计，
`build_ir()` 解析为中间表示，`build_design()` 导出到 Metal `QDesign`，
`build_mesh()` 直接出 Gmsh `.msh` 喂给 EM 求解器。

## 目录结构

```
examples/dsl/
├── README.md                  本文件
├── yaml/                      DSL v3 配置 YAML
│   ├── native_2q_minimal.metal.yaml     最小示例
│   ├── chain_2q_native.metal.yaml       完整示例（primitive-native）
│   └── transmon_pocket_2q.metal.yaml    模板示例（type: transmon_pocket）
├── scripts/                   命令行 demo / smoke test
│   ├── run_chain_demo.py
│   ├── run_chain_gmsh_demo.py
│   ├── run_transmon_pocket_demo.py
│   └── bidirectional_traversal_proof.py
├── notebooks/                 Jupyter 演示
│   ├── primitive_native_demo.ipynb
│   ├── transmon_pocket_demo.ipynb
│   ├── bidirectional_traversal_proof.ipynb
│   └── gmsh_mesh_demo.ipynb
├── outputs/                   运行产物（.msh 等，已 .gitignore）
└── .note/                     开发笔记 / 演示材料（不影响运行）
```

## 从哪开始

最快路径：打开一个 notebook 跑一遍。

1. **`notebooks/primitive_native_demo.ipynb`** — 手写每个 pad / junction / bus 的 primitive。适合理解 DSL 基本结构。
2. **`notebooks/transmon_pocket_demo.ipynb`** — 组件模板。写 `type: transmon_pocket` 自动生成几何 + pin。
3. **`notebooks/gmsh_mesh_demo.ipynb`** — 端到端：YAML → DesignIR → `build_mesh()` → `.msh` → meshio 回读 + Elmer SIF 片段。

只想读 YAML 不跑代码？从 **`yaml/native_2q_minimal.metal.yaml`** 开始，最短最清晰。

## 运行命令行 demo

从 worktree 根目录跑（scripts 内部用 `_HERE.parents[3]` 找到 worktree 根，自动把 `src/` 加入 `sys.path`）：

```powershell
# build_design 路径（左路）— 出 Metal QDesign
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\scripts\run_chain_demo.py
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\scripts\run_transmon_pocket_demo.py

# build_mesh 路径（右路）— 出 Gmsh .msh
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\scripts\run_chain_gmsh_demo.py --output examples\dsl\outputs\chain_2q.msh
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\scripts\run_chain_gmsh_demo.py --gui

# 链路双向追踪 (circuit ↔ geometry ↔ netlist round-trip)
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\scripts\bidirectional_traversal_proof.py
```

## 运行 notebook

Notebook 启动时通过 `_HERE.parents` 上溯找 `src/qiskit_metal/`，不需要 pip install。
用 `metal-env` 的 kernel 打开 `notebooks/*.ipynb` 直接跑。

## 两种 YAML 写法

**Primitive-native**（手写每个几何元素，灵活但啰嗦）：

```yaml
Q1:
  primitives:
    - {name: pad, type: poly.rectangle, center: [0mm, 0mm], size: [420um, 90um]}
  pins:
    - {name: bus, points: [[0.34mm, -6um], [0.34mm, 6um]], width: 12um}
```

**组件模板**（写 type 和 options，模板生成几何 + pin）：

```yaml
Q1:
  type: transmon_pocket   # 解析继承链 qcomponent → base_qubit → transmon_pocket
  options:
    pos_x: -1.2mm
    connection_pads:
      readout: {loc_W: 1, loc_H: 1}
```

两种写法都**不**走 qlibrary 的 Python class（不写 `class: TransmonPocket`），导出物都是标准 Metal `QDesign`。
