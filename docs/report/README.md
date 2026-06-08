# 汇报材料（quantum_dsl）

本目录是为「向不熟悉代码的汇报人」准备的一整套汇报材料。三份文档分工明确：

| 文档 | 用途 | 谁看 / 何时看 |
|---|---|---|
| [`01-工作汇报.md`](01-工作汇报.md) | **展示用**。按**功能**组织：重构取舍、整体架构（数据流 + **指令入口调用链** + 模块依赖 + 绑定 key）、能力逐项（几何/两路产物/电容求解/哈密顿量/可视化）+ 代码 `文件:行号` 引用 + 实测结果 | 现场对外展示的主文档 |
| [`02-代码实现详解.md`](02-代码实现详解.md) | **准备用**。用人话讲清每个模块怎么实现、为什么、关键代码在哪，附**预期问答** | 汇报人事先研读，应对追问 |
| [`03-汇报流程与演示.md`](03-汇报流程与演示.md) | **操作用**。与 01 逐段对应：每段展示什么、敲什么命令、怎么操作、指哪看，含 Gmsh GUI / GDSFactory 窗口 | 现场照着做 |

辅助：
- [`demo_gui.sh`](demo_gui.sh) — 演示助手脚本（自动激活 `metal-env` + WSLg GUI）。`bash docs/report/demo_gui.sh help` 看子命令。
- [`img/`](img/) — 已生成的演示参考图（各示例的 GDS 预览 + 3D 网格截图）。

## 快速开始

```bash
cd /home/administrator/quantum_dsl
bash docs/report/demo_gui.sh check          # 自检环境 + GUI
bash docs/report/demo_gui.sh build-chip     # 跑手写 .geo 示例
bash docs/report/demo_gui.sh solve-twopads  # 真实电容求解（~2-3 分钟，开场前先跑）
```

> 权威进度来源仍是 `.claude/status.md`（快照）与 `.claude/plan.md`（里程碑清单）。本目录是面向汇报的二次整理，
> 所有 `文件:行号` 与数值结果均经本次实测核对。
