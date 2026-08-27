# quantum_dsl 文档

> **本目录的定位**：v4 的全部人类可读文档，自成体系（不依赖任何开发期台账）。
> 代码怎么组织、怎么用 → [`architecture.md`](architecture.md) + [`grammar.md`](grammar.md)；
> 为什么这么算、数值可信到哪一位 → [`physics.md`](physics.md)；对外汇报与现场演示 → [`report/`](report/)。
> 所有 `文件:行号` 与数值均在 v4.0（2026-08-26，conda `qdsl313`）实测核对。

---

## 文档地图

| 文档 | 用途 | 谁看 / 何时看 |
|---|---|---|
| [`architecture.md`](architecture.md) | **架构**：数据流、模块地图与依赖图、绑定键、公共 API、`build()` 产物、设计原则、与 v3 的差异 | 上手开发；改任何模块之前 |
| [`physics.md`](physics.md) | **物理口径与数值决策**：为什么静电就够、零厚度片 imprint、单位与 `Model.L0`、`Order=2`、网格收敛实测、LOM/SQUID/χ/CPW 公式与逐式出处、失效防线、分块拼装边界、sung 外部验证、Palace 运行面 | 碰 mesh / Palace / 公式 / 容差之前**必读** |
| [`grammar.md`](grammar.md) | **语法参考**：`.geo` 作者约定 + `*.meta.yaml` 全字段（类型、默认值、必填）+ 最小可跑例子 + 常见坑 | 写版图 / 写 sidecar 的人 |
| [`report/`](report/README.md) | **汇报材料四篇**：01 展示用 · 02 备问用（贴真实代码逐段讲）· 03 现场演示手册（命令 + 预期输出 + 故障预案）· 04 sung 论文验证的完整账（标定的替代几何 vs 照片量出的真拓扑、真值怎么读、测量误差预算、Elmer 交叉、order 1/2、误差相抵） | 对外汇报、答辩、复现 |
| [`../SPEC.md`](../SPEC.md) | **契约**：目标与边界、Layer-1 词汇、公共 API 表（N0–N15 ↔ 测试）、验收 | 加需求 / 改测试时 |
| [`../examples/README.md`](../examples/README.md) | 例子清单、跑法、预期输出、怎么写自己的例子 | 第一次跑 |

## 安装

```bash
# Python ≥ 3.13。核心依赖只有 pyyaml / shapely；gmsh / gdstk 是 optional extra
pip install -e '.[gmsh,gds,test]'
# 本机既有 env: conda qdsl313 (Python 3.13.14 + gmsh 4.15.2 + gdstk 1.0.1 + shapely 2.1.2)
```

Palace（静电求解器）不是 pip 依赖：`build(solve=True)` 通过环境变量 `PALACE_BIN` 找二进制
（未设时回退到 `~/spack/opt/spack/*/palace-*/bin/palace`）。本机 Palace 0.16.0 经 spack 安装。
⚠ **WSL 上任何 MPI 程序必须 `HWLOC_COMPONENTS=-gl`**（`build()` 会自动注入；手动跑 Palace 时自己带上），
否则 hwloc 的 gl 插件探测 X display 会把 `MPI_Init` 挂死。

## 快速开始

```bash
P=~/miniconda3/envs/qdsl313/bin/python
export PYTHONPATH=src

$P -m pytest tests/ -q                       # 28 passed, 2 skipped (live 默认关)
$P -c "from quantum_dsl import build; print(build('examples/two_pads.meta.yaml', 'build/two_pads'))"
                                             # GDS + 3D 网格 + Palace config + manifest, ~4 s
QDSL_RUN_PALACE=1 $P -m pytest tests/test_live.py -k two_pads -q   # 真实求解回归 (~2 min)
```

一条链路：`.geo`（µm 几何）+ `*.meta.yaml`（材料/域/网格/结）→ GDS（gdstk）· 3D 网格（gmsh）→
Palace 静电 → Maxwell 电容矩阵 → 逆电容 LOM → `results.yaml`（E_C / f01 / α / g）。
