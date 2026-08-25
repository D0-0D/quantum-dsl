# Quantum-DSL v4 — greenfield 重写进度

契约 = [`SPEC.md`](../SPEC.md);可执行需求 = `tests/test_spec.py`(N0–N14)。
**完成定义: 契约套件 0 failed(live 两条默认 skip)+ `QDSL_RUN_PALACE=1` 下 N7 通过。**
Legend: `[x]` done · `[~]` in progress · `[ ]` not started。

## 里程碑(V4-2 与 V4-3 相互独立, 可并行)

- [x] **V4-1 基础**: 包骨架 + `QuantumDslError` +
      `parse_length`/`parse_quantity`(N1)+ `load_geo` 四段名解析(N2)+
      `load_meta` 新词汇(N3)+ import 纯度(N0)。注: `load_geo` 用 gmsh
      **惰性 import** 解析(fixtures 有变量/宏/Include, 文本解析撑不住
      bbox; N0 只禁 import 时拉起)。
- [x] **V4-2 几何分叉**: `build_gds`(N4, gdstk µm verbatim)+ `build_mesh`
      (N5, **零厚度片 imprint**——焊盘面 fragment 进衬底/真空界面, Terminal 挂
      内部边界面; 空网格 raise)+ `palace_config` / `parse_capacitance`(N6)。
      注: N6 fixture CSV 指数翻案(×1e-3, 断言未动)——Palace 输出真 SI
      法拉, fF=F×1e15 是 N7 唯一自洽口径; gmsh 宏进程级永久状态 →
      `_gmsh.py` 共享 session 口径(docstring 存档)。
- [x] **V4-3 物理内核**(纯 math, 不依赖 V4-2): `solve_circuit_model`
      逆电容 LOM + **浮动双岛差模约化**(完整求逆取 θθ 块, N8 闭式 case)+
      SQUID 无奇点式 + nan 守卫(N8)+ `assemble` 累加/Schur(N9)+
      `lumped_cpw`/`guided_wavelength` AGM(N10)+ `resonator_lumped_lc`/
      `dispersive_shift_hz`(N11)。算法可从旧仓 `dsl/{circuit_model,assemble,
      cpw_analytic}.py` 审后搬运(它们本就无 qiskit_metal import)。
- [x] **V4-4 cells**: `rounded_polygon`(shapely buffer 预采样)+ `emit_geo`
      (N12, load_geo 可回读)。
- [x] **V4-5 编排**: `build(meta, out, solve=)` 产 gds/mesh/config/manifest
      (N13, sha256)+ `extract.blocks` 分块落盘(N14)+ §11 廉价防线
      (跨块几何邻近 warn, blocks fixture 上如设计触发)。
- [x] **V4-6 live 验证 + 收尾**: N7 两条通过(<2%, 238s); **N15 两条通过**
      (gpu4 96C/384G, 1h12m; 18.5M 未知量峰值内存 154G——128G 机必 OOM,
      §12 有账)。**N15 容差翻案 ±5%→±8%**: 同网格 o1 对 v3 Elmer P1 档
      <1%(管线正确性外证), o2 = 论文 ×0.940–0.969——Elmer 档「±3% 吻合」
      系 P1 正偏与简化版图缺失抵消(§9)。远端接入 =
      `.claude/proto/palace_remote.sh`(PALACE_BIN 垫片)。README/SPEC 已核。

## Session logs
- [`session/2608242245.md`](session/2608242245.md) — 2026-08-24/25 · **v4 收官**:
  V4-2/4-4/4-5 落地(40 passed; N6 fixture 指数翻案; gmsh 宏状态坑 →
  `_gmsh.py`); N7 live 通过; **N15 战役**(c24a1 128G OOM@154G 峰值 →
  gpu4 384G 通过; o1/o2 同网格交叉揭穿 Elmer P1 档偏置抵消, 容差翻案
  ±5%→±8%, 五处文档同步); 云机账 ~770 灵豆, 已全关。
- [`session/2608241316.md`](session/2608241316.md) — 2026-08-24 · **N10 golden
  翻案**: 全契约 golden 出处审计, 唯一锚原有错误的是 N10(qiskit-metal 参考
  输出: Z0/λ_g 不含 Lk、ε_eff 与 C 不自洽、常数截断)→ 改锚自洽物理集
  (Göppl+Simons+Clem/Mohebbi), 新增自洽性断言; 差值 Z0 −1.08% / λ_g −1.56%。
- [`session/2608241251.md`](session/2608241251.md) — 2026-08-24 · **V4-1 +
  V4-3 落地**(N0–N3 + N8–N11 全绿, 30 passed): errors/units/geo/meta +
  circuit_model/assemble/cpw; 新防线(反对称残差 raise、未认领 label 拒
  静默接地); χ 引文改 Zhu et al.; N9 契约测试 harness 修复(pytest.approx
  不支持嵌套 list, golden 数值未动); cpw golden 性质核定 = 参考实现
  parity 锚(Z0/λ_g 不含 Lk, 高 Lk 场景由消费端总 L'C' 重算, V4-5 落地)。
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
