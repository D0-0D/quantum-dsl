# 汇报材料

两套材料，按阶段分目录。当前一套覆盖 **2026-09-12 → 09-18**（提交 `50dc842` 起：版图编排、Chen 2025 模板与上云验证、自动布线）；
v4.0 阶段（2026-08-26，greenfield 重写 + sung 论文验证）的一套原样保留在 [`Aug27/`](Aug27/README.md)。

四份文档按**读者**分工：前三份是同一套内容的三个切面，第四份专讲论文外部验证这一条线。

| 文档 | 用途 | 谁看 / 何时看 |
|---|---|---|
| [`01-工作汇报.md`](01-工作汇报.md) | **展示用**。为什么要版图编排、架构增量（新几何源 + `layout.py` / `route.py`）、能力逐项（模板与版图 / 三种路由写法 / Chen 模板 / 分块与上云 / 拒绝静默）、端到端验证实测、本阶段决策记录、边界与后续 | 现场对外展示的主文档 |
| [`02-代码实现详解.md`](02-代码实现详解.md) | **准备用**。贴真实代码逐段讲编排器（加载 / 位姿 / 注入 / 认领 / 连接 / 手写 / 收尾）、自动布线规划器、分块与上云接口，附**预期问答** | 汇报人事先研读，应对追问 |
| [`03-复现与演示.md`](03-复现与演示.md) | **操作用**。Demo A–G：契约套件、Chen 3×3 版图、手写 = 模板、自动布线（含 raise）、块本机求解、十字上云、守卫；含**已确认可运行清单**与**故障预案** | 现场照着做；任何人复现 |
| [`04-论文验证闭环-chen.md`](04-论文验证闭环-chen.md) | **说明用**。对 Chen et al. 2025（Nat. Phys. 21, 1489）的完整账：论文三层真值（实测 α 表 / 设计值 / SI 电容表与其自身闭合）、几何从照片来、模型口径（flip-chip d）、三种几何各对什么、d = 4 / 5 / 7 与两档网格结果、**逐项偏差表**、归因、验证了什么 / 没验证什么 | 想弄清本仓对论文的预测精度与边界的人 |

配套的长期文档（真源，不是汇报材料）：[`../architecture.md`](../architecture.md)（架构）· [`../physics.md`](../physics.md)（物理口径与数值决策，§13–§14 = Chen 与内存预算）·
[`../grammar.md`](../grammar.md)（语法，§4 = 版图与模板）· [`../design/`](../design/)（设计稿 + 几何取证 + 自动布线设计稿）。

## 快速开始（完整演示流程见 `03`）

```bash
cd /home/administrator/quantum_dsl-v4
source ~/miniconda3/etc/profile.d/conda.sh && conda activate qdsl313
export PYTHONPATH=src

python -m pytest tests/ -q                  # 44 passed, 2 skipped, ~40 s (2026-09-18)
python -c "from quantum_dsl import build; print(build('examples/chen_2025_3x3.meta.yaml', 'build/report/chen', solve=False, blocks=['H01']))"
                                            # 3×3 GDS + PNG + H01 块网格/config, ~30 s
python -c "from quantum_dsl import build; build('examples/cpw_route_demo.meta.yaml', 'build/report/route', solve=False)"
                                            # 自动布线 demo GDS + PNG, ~3 s
```

> 所有 `文件:行号` 与数值于 2026-09-18 在 WSL2 + conda `qdsl313`（Python 3.13，gmsh 4.15.2，gdstk 1.0.1，Palace 0.16.0）实测核对；
> 上云数值来自 2026-09-18 阿里云 c24a1（64 核 / 128 G，spack Palace 0.16），产物归档 `.claude/chen-evidence/`。
