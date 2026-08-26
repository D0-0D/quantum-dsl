# 汇报材料（quantum_dsl v4.0）

本目录是为「向不熟悉代码的听众汇报 v4」准备的一整套材料。三份文档按**读者**分工，同一套内容三个切面：

| 文档 | 用途 | 谁看 / 何时看 |
|---|---|---|
| [`01-工作汇报.md`](01-工作汇报.md) | **展示用**。按**功能**组织：为什么 greenfield 重写、整体架构（数据流 + 模块地图 + 绑定键）、能力逐项、端到端验证实测（回归锚 + 论文外部锚）、本次收口的历史问题、当前边界 | 现场对外展示的主文档 |
| [`02-代码实现详解.md`](02-代码实现详解.md) | **准备用**。把真实代码片段贴进来逐段讲：每个模块做什么、为什么、关键代码在哪、具体数据与坑，附**预期问答** | 汇报人事先研读，应对追问 |
| [`03-复现与演示.md`](03-复现与演示.md) | **操作用**。与 01 逐段对应：每段展示什么、敲什么命令、预期输出长什么样、指哪里看，含**故障预案** | 现场照着做；任何人复现 |

配套的长期文档（不是汇报材料，是真源）：[`../architecture.md`](../architecture.md)（架构）·
[`../physics.md`](../physics.md)（物理口径与数值决策）· [`../grammar.md`](../grammar.md)（语法）。

## 快速开始（完整演示流程见 `03`）

```bash
cd /home/administrator/quantum_dsl          # 或任何 checkout 了 main 的目录
source ~/miniconda3/etc/profile.d/conda.sh && conda activate qdsl313
export PYTHONPATH=src

python -m pytest tests/ -q                  # 28 passed, 2 skipped, ~12 s
python -c "from quantum_dsl import build; print(build('examples/two_pads.meta.yaml', 'build/report/two_pads'))"
                                            # GDS + 网格 + Palace config + manifest, ~4 s
QDSL_RUN_PALACE=1 python -m pytest tests/test_live.py -k two_pads -q    # 真实求解回归 (~2 min, 开场前先跑)
```

> 所有 `文件:行号` 与数值结果均于 v4.0（2026-08-26）在 WSL2 + conda `qdsl313`（Python 3.13.14，gmsh 4.15.2，
> gdstk 1.0.1，Palace 0.16.0）实测核对。sung 外部验证的数值来自 2026-08-25 在 96 核 / 384 G 远端机的实测，
> 原始 CSV 归档在 `v4-dev` 分支 `.claude/n15-evidence/`。
