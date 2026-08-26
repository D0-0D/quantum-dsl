# CLAUDE.md

Guidance for AI agents working in this repository.

> **v4.0 已发布（2026-08-26）。** 契约 = [`SPEC.md`](SPEC.md)（N0–N15 ↔ `tests/`）。开工前读
> `.claude/status.md` → `.claude/plan.md`（backlog）—— 不要臆测项目状态。碰 mesh / Palace / 物理公式 / 容差
> 之前**必读** [`docs/physics.md`](docs/physics.md)；改代码前读 [`docs/architecture.md`](docs/architecture.md)。

## 项目

`quantum_dsl` — 超导量子芯片版图 DSL（src-layout, `src/quantum_dsl/`, 1 950 行）:
native Gmsh `.geo`（OCC, **µm**）+ `*.meta.yaml` sidecar → { gdstk→GDS · gmsh→mesh→Palace 静电→C 矩阵 }
→ 拼装（共享节点 + Schur）→ 电路模型（逆电容 LOM / SQUID / TL+χ / CPW）。
绑定键 = Physical 名 `role::layer::component::primitive` 的 **component 段**（= 电学岛）。
金属 = **零厚度片 imprint** 进衬底/真空界面（不是 v3 的挖空），Terminal 挂内部边界面。
无 qiskit_metal（3.13 下装不上, 平台即护栏）。只有 Python API, 没有 CLI。

文档地图: [`docs/README.md`](docs/README.md)。例子: [`examples/README.md`](examples/README.md)。

## Commands

conda env **`qdsl313`**（Python 3.13 + gmsh + gdstk + shapely + pytest; `PALACE_BIN` 与 `HWLOC_COMPONENTS=-gl` 已持久化）:

```bash
~/miniconda3/envs/qdsl313/bin/python -m pytest tests/ -q                       # 28 passed, 2 skipped, ~12 s
QDSL_RUN_PALACE=1 ~/miniconda3/envs/qdsl313/bin/python -m pytest tests/test_live.py -k two_pads -q   # ~2 min
# sung 外部锚: QDSL_RUN_PALACE_SUNG=1 + PALACE_BIN=tools/palace_remote.sh + 384G 远端机 (峰值内存 154 G)
```

## 硬约束

- ⚠ **任何 MPI 程序（Palace）在 WSL 必须 `HWLOC_COMPONENTS=-gl`**（`build()` 自动注入; 手动跑要自己带;
  新建 env 必须照做, 否则 hwloc gl 插件探测 X display 会把 MPI_Init 挂死）。
- 无 qiskit_metal、无 `.metal.yaml`、无 v3 模板引擎; `import quantum_dsl` 不拉 gmsh/gdstk/shapely（测试在子进程查）。
- 内部单位 µm; GDS µm verbatim; **唯一 µm→m 换算点 = Palace config `Model.L0=1e-6`**。JJ 是集总元件（进 GDS 不进网格）。
- `Solver.Order=2` 是承重件; golden 不锚参考实现, 只锚物理与闭式（改 golden 先读 physics.md §7 / §12 的翻案账）。
- gmsh session 进程级共享、从不 finalize（`_gmsh.py`）; 每个调用点显式设全自己依赖的 `gmsh.option`。
- 拒绝静默: 未知 meta 键 / 未认领 label / keep 拼错 / NaN 一律 raise, 不要"修"成静默默认。

## 分支

`main` = v4 产品; `v3` = 旧实现（只读参考, 算法可搬但逐文件审）; `v4-dev` = v4 开发痕迹与原始调研存档
（session logs、codex 文献取证、N15 原始 CSV、原型脚本）—— 追出处时去那里查, 不要搬回 main。

## Project journaling — KEEP THESE UP TO DATE

`.claude/status.md`（快照）· `.claude/plan.md`（backlog + 已了结别重踩）· `.claude/session/<yyMMddhhmm>.md`
（每会话一篇, 本分支从 v4.0 起新开）。会话开始先读 status → plan; headline 变了就刷新。
