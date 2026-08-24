# Quantum-DSL v4 — greenfield 重写进度

契约 = [`SPEC.md`](../SPEC.md);可执行需求 = `tests/test_spec.py`(N0–N14)。
**完成定义: 契约套件 0 failed(live 两条默认 skip)+ `QDSL_RUN_PALACE=1` 下 N7 通过。**
Legend: `[x]` done · `[~]` in progress · `[ ]` not started。

## 里程碑(V4-2 与 V4-3 相互独立, 可并行)

- [ ] **V4-1 基础**(纯 python, 无重依赖): 包骨架 + `QuantumDslError` +
      `parse_length`/`parse_quantity`(N1)+ `load_geo` 四段名解析(N2)+
      `load_meta` 新词汇(N3)+ import 纯度(N0)。
- [ ] **V4-2 几何分叉**: `build_gds`(N4, gdstk µm verbatim)+ `build_mesh`
      (N5, **零厚度片 imprint**——焊盘面 fragment 进衬底/真空界面, Terminal 挂
      内部边界面; 空网格 raise)+ `palace_config` / `parse_capacitance`(N6)。
      ⚠ 先读 [`physics-pipeline.md`](physics-pipeline.md) §4–§6(配方/单位/网格实测);
      旧仓「别重新踩」表大半是挖空路线的对策, 不适用。
- [ ] **V4-3 物理内核**(纯 math, 不依赖 V4-2): `solve_circuit_model`
      逆电容 LOM + SQUID 无奇点式 + nan 守卫(N8)+ `assemble` 累加/Schur(N9)+
      `lumped_cpw`/`guided_wavelength` AGM(N10)+ `resonator_lumped_lc`/
      `dispersive_shift_hz`(N11)。算法可从旧仓 `dsl/{circuit_model,assemble,
      cpw_analytic}.py` 审后搬运(它们本就无 qiskit_metal import)。
- [ ] **V4-4 cells**: `rounded_polygon`(shapely buffer 预采样)+ `emit_geo`
      (N12, load_geo 可回读)。
- [ ] **V4-5 编排**: `build(meta, out, solve=)` 产 gds/mesh/config/manifest
      (N13, sha256)+ `extract.blocks` 分块落盘(N14)。分块语义与廉价防线
      (几何邻近但结构性零耦合 → warn)见 [`physics-pipeline.md`](physics-pipeline.md) §11。
- [ ] **V4-6 live 验证 + 收尾**: N7 两条(Palace 0.16, golden <2%)+ README/SPEC
      核对 + journaling。运行面口径(多 rank 可用、AMR 试点条件、域尺寸扫)
      见 [`physics-pipeline.md`](physics-pipeline.md) §12。

## Session logs
- [`session/2608240435.md`](session/2608240435.md) — 2026-08-24 · **物理管线
  de-risk + 定架构 + 预研收口**: 原仓 issues #1–#28 调研([`v3-issue-survey.md`](v3-issue-survey.md));
  gmsh→Palace 原型 6 组实测; **零厚度片 imprint 定为 v4 金属表示**(v3
  "Palace 拒内部面 Terminal" 系误诊, ε-nudge/scale-ladder 失效类随之消失);
  N7 golden 重钉为零厚度片配方实测值; 设计文档
  [`physics-pipeline.md`](physics-pipeline.md) §1–§12; 后半程: 分块拼装
  取证(SPEC 措辞收紧)、Palace 运行面与 LOM 公式口径双跑取证(χ 引文修正,
  g 口径分叉钉死)、64C 裸机实测(order2 多 rank 无恙, v3 #22 = 环境问题)。
  V4-3 数学对 golden 逐位复算通过。四份原始取证归档 `.claude/*-survey.md`。
- [`session/2608240352.md`](session/2608240352.md) — 2026-08-24 · **v4 立项**(空白 orphan 分支):
  SPEC.md 契约 + `tests/test_spec.py` 可执行需求(N0–N14, 全红起点)+ fixtures
  (two_pads.geo/meta 新词汇/Palace verbatim CSV)+ pyproject(py≥3.13)+
  qdsl313 env。golden 锚点取自 v3 实测与闭式手算。
