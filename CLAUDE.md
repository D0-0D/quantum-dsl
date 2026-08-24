# CLAUDE.md

Guidance for AI agents working in this repository.

> **v4 greenfield 重写, 从空白开始, TDD。** 契约 = [`SPEC.md`](SPEC.md);
> 可执行需求 = `tests/test_spec.py`(N0–N14, 起点全红)。**全部翻绿 +
> `QDSL_RUN_PALACE=1` 下 N7 通过 = 完成。** 开工前读 `.claude/status.md` 与
> `.claude/plan.md` —— 不要臆测项目状态。

## 项目

`quantum_dsl` v4 — 超导量子芯片版图 DSL(src-layout, `src/quantum_dsl/`):
native Gmsh `.geo`(OCC, **µm**)+ `*.meta.yaml` sidecar → { gdstk→GDS ·
gmsh→mesh→Palace 静电→C 矩阵 } → 拼装(共享节点+Schur)→ 电路模型(逆电容
LOM / SQUID / TL+χ / CPW)。绑定键 = Physical 名 `role::layer::component::primitive`
的 **component 段**。无 qiskit_metal(3.13 下装不上, 平台即护栏)。

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
Schur、AGM-K、carve/fragment 的 OCC 坑全趟过)—— 但**逐文件审后再搬**:
禁止带入 qiskit_metal 依赖、`.metal.yaml` 路径、v3 模板引擎。趟坑记录在旧仓
`.claude/status.md` 的「已了结, 别重新踩」表(hwloc/MPI、OCC 共面布尔、
ε-nudge、fragment shape-heal)。

## Project journaling — KEEP THESE UP TO DATE

约定与 v3 相同: `.claude/status.md`(快照)· `.claude/plan.md`(里程碑,
底部 Session-logs 索引)· `.claude/session/<yyMMddhhmm>.md`(每会话一篇)。
会话开始先读 status → plan; headline 变了就刷新。
