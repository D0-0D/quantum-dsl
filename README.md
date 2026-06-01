# quantum_dsl

一个面向超导电路版图的 **原生 YAML 设计 DSL**。它把单个 `.metal.yaml`
文件解析、模板继承展开、`${...}` 插值之后，直接导出成 qiskit-metal 的
`QDesign`（并可选地经 Gmsh 适配器产出 `.msh` 网格），整个过程 **不实例化
qlibrary 的组件 Python 类**（不走 `TransmonPocket(...)`）。

本仓库是从 [qiskit-metal](https://github.com/qiskit-community/qiskit-metal)
的 `qiskit_metal.toolbox_metal.dsl` 抽取出来、独立成包的版本。实现代码保持
原样（仅把导入路径从 `qiskit_metal.toolbox_metal.dsl` 改写为 `quantum_dsl`），
qiskit-metal 作为第三方运行时依赖。

## 与原仓库的关系 / Provenance

- 来源：`qiskit-metal`（worktree 分支 `full_chain_pre`）下的
  `src/qiskit_metal/toolbox_metal/dsl{,_templates}`、`design_dsl.py`、
  `tests/test_design_dsl*.py`、`examples/dsl/` 以及 `.codex/dsl_v3_*.md`。
- 改动：只改写了导入路径与示例/笔记本里探测仓库根的 `src/qiskit_metal`
  片段；DSL 内部逻辑、模板 YAML、测试断言均未改。
- `quantum_dsl` 仍然 `import qiskit_metal`（用于单位解析 `parse_value`、
  `draw` 几何助手、`QComponent`、以及可选的 Gmsh renderer 工具）。

## 目录结构

```
quantum_dsl/
├── pyproject.toml
├── README.md
├── src/
│   └── quantum_dsl/
│       ├── __init__.py            # 重新导出公共 API（build_ir / build_design ...）
│       ├── design_dsl.py          # 兼容 facade（原 toolbox_metal/design_dsl.py）
│       ├── dsl/                    # 实现子包（相对导入，逻辑未改）
│       │   ├── builder.py          # build_ir(yaml) / build_design(yaml)
│       │   ├── component_templates.py / template_registry.py / template_model.py
│       │   ├── expression.py        # ${...} 插值 + 安全 AST 求值
│       │   ├── geometry_ops.py / parsers/
│       │   ├── schema.py / ir.py / errors.py / _helpers.py
│       │   └── gmsh_adapter.py + _gmsh_*.py   # 可选：DSL → Gmsh 网格
│       └── dsl_templates/          # 内置组件模板 YAML（必须是 dsl/ 的同级目录）
│           ├── core/{qcomponent,base_qubit}.yaml
│           └── qubits/transmon_pocket.yaml
├── tests/                          # test_design_dsl*.py
├── examples/dsl/                   # yaml / scripts / notebooks / outputs / .note
└── docs/codex_notes/               # 历次设计评审笔记（.codex/dsl_v3_*.md）
```

> 重要不变量：`template_registry._builtin_template_root()` 用
> `Path(__file__).parent.parent / "dsl_templates"` 定位模板，因此
> `dsl_templates/` 必须始终是 `dsl/` 子包的同级目录（即都在
> `src/quantum_dsl/` 下）。移动目录时请保持该关系。

## 安装

需要 Python `>=3.10,<3.13`（与 qiskit-metal 支持范围一致）。

```bash
# 在已装好 qiskit-metal 的环境里（推荐 conda 的 metal-env），从仓库根目录：
pip install -e .
# 需要 Gmsh 网格功能时：
pip install -e ".[gmsh]"
# 跑测试：
pip install -e ".[test]"
```

如果还没装 qiskit-metal（例如全新的 WSL Python）：

```bash
pip install qiskit-metal   # 会拉入 numpy / shapely / geopandas / pyside6 等较重依赖
```

## 用法

```python
import quantum_dsl

# 只解析到中间表示（IR）：模板/插值展开 + primitive/pin/derived 计算
ir = quantum_dsl.build_ir("examples/dsl/yaml/chain_2q_native.metal.yaml")
print(ir.components, ir.derived)

# 导出成真实的 Metal QDesign（写 qgeometry 表、pins、connect_pins）
design = quantum_dsl.build_design("examples/dsl/yaml/chain_2q_native.metal.yaml")

# 可选：绕过 QDesign，直接产出 Gmsh 网格
from quantum_dsl.dsl.gmsh_adapter import build_mesh
build_mesh("examples/dsl/yaml/chain_2q_native.metal.yaml", output="chain_2q.msh")
```

DSL 文件头：`schema: qiskit-metal/design-dsl/3`；顶层小节：`vars`、
`hamiltonian`、`circuit`、`netlist`、`geometry`（含 `design`、`templates`、
`components`、`transforms`）。组件可用 `type:` + `options:`（模板）或
`primitives:` + `pins:`（primitive-native）两种写法。

## 示例与测试

```bash
# 示例脚本（脚本会把 src/ 自举进 sys.path，无需先 pip install）
python examples/dsl/scripts/run_chain_demo.py
python examples/dsl/scripts/run_transmon_pocket_demo.py
python examples/dsl/scripts/run_chain_gmsh_demo.py --output build/chain_2q.msh

# 测试（需要 qiskit-metal 已安装）
pytest
```

`examples/dsl/notebooks/` 下的 notebook 同样会自举 `sys.path` 指向本仓库的
`src/`，并以 `import quantum_dsl` 的方式调用。

## 许可证

继承自 qiskit-metal 的 Apache-2.0。
