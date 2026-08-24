# CLAUDE.md

Guidance for AI agents working in this repository.

> **v4 greenfield 重写, 从空白开始, TDD。** 契约 = [`SPEC.md`](SPEC.md);
> 可执行需求 = `tests/test_spec.py`(N0–N14, 起点全红)。**全部翻绿 +
> `QDSL_RUN_PALACE=1` 下 N7 通过 = 完成。** 开工前读 `.claude/status.md` 与
> `.claude/plan.md` —— 不要臆测项目状态。碰 mesh/Palace/物理数学的(V4-2/3/6)
> 再加 [`.claude/physics-pipeline.md`](.claude/physics-pipeline.md)(架构决策 +
> 实测 + 失效防线;外部文献出处在 [`.claude/palace-lit-survey.md`](.claude/palace-lit-survey.md))。

## 项目

`quantum_dsl` v4 — 超导量子芯片版图 DSL(src-layout, `src/quantum_dsl/`):
native Gmsh `.geo`(OCC, **µm**)+ `*.meta.yaml` sidecar → { gdstk→GDS ·
gmsh→mesh→Palace 静电→C 矩阵 } → 拼装(共享节点+Schur)→ 电路模型(逆电容
LOM / SQUID / TL+χ / CPW)。绑定键 = Physical 名 `role::layer::component::primitive`
的 **component 段**。金属 = **零厚度片 imprint** 进衬底/真空界面(不是 v3 的
挖空), Terminal 挂内部边界面。无 qiskit_metal(3.13 下装不上, 平台即护栏)。

## Commands

conda env **`qdsl313`**(Python 3.13 + gmsh + gdstk + shapely + numpy + pytest):

```bash
~/miniconda3/envs/qdsl313/bin/python -m pytest tests/ -q          # 契约套件
QDSL_RUN_PALACE=1 ~/miniconda3/envs/qdsl313/bin/python -m pytest tests/ -q  # 含 live 解
```

- ⚠ **任何 MPI 程序(Palace)必须 `HWLOC_COMPONENTS=-gl`**(已持久化进 qdsl313;
  新建 env 必须照做, 否则 hwloc 的 gl 插件 TCP 探测 X display 会把 MPI_Init 挂死)。
- Palace 0.16 经 spack 装在 WSL, `PALACE_BIN` 已在 env 里。

## 参考(旧实现)

主 worktree `~/quantum_dsl`(branch main)是 v3 实现。算法可搬(逆电容 LOM、
Schur、AGM-K)—— 但**逐文件审后再搬**: 禁止带入 qiskit_metal 依赖、
`.metal.yaml` 路径、v3 模板引擎。

旧仓 `.claude/status.md` 的「已了结, 别重新踩」表: hwloc/MPI 那条仍然有效,
其余大半(OCC 共面布尔、ε-nudge、fragment shape-heal、scale ladder)是 v3
**挖空**架构的对策 —— v4 零厚度片路线下这些失效类已结构性消失, **别照搬**,
先读 `.claude/physics-pipeline.md` §4。

## Project journaling — KEEP THESE UP TO DATE

约定与 v3 相同: `.claude/status.md`(快照)· `.claude/plan.md`(里程碑,
底部 Session-logs 索引)· `.claude/session/<yyMMddhhmm>.md`(每会话一篇)。
会话开始先读 status → plan; headline 变了就刷新。
