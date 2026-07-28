# Quantum-DSL — Current Status

**This is an active, in-progress project.** Read this file *and* `plan.md` at the start of
every session before touching code. This file is the quick "where are we right now" snapshot;
`plan.md` is the full milestone checklist + the original-requirements map.

_Update this file whenever the headline state changes (milestone flips, branch merges, notable
commits, test-count changes)._

---

## At a glance
- **Active branch**: `main` (the native Gmsh `.geo` pivot landed via PR #14, commit `931b8ec`).
- **Current-phase scope** (2026-06-08, phased — not a final ceiling): rounded-corner polygon cells
  + an **electrostatic capacitance matrix**. Eigenmode/driven, lumped ports, and loss are out of
  *this* phase — staged for later, not ruled out.
- **Done**: **M1 `[x]`** (both branches end-to-end), **M3 `[x]`** (live Palace C-matrix +
  `chip.results.yaml` write-back; conductors-as-voids `carve_conductors`), **M5a `[x]`** (emit_geo
  cell-library bridge: v3 templates → flat positive-tone `.geo`, rounded corners via pre-sampled
  shapely buffers, carved metal ground), and **M6 `[x]`** (circuit-model solve: C-matrix → transmon
  Hamiltonian via lumped-oscillator inverse-cap method; tier-2 `hamiltonian` write-back), and
  **M7 `[x]`** (GDSFactory visualization: `dsl/gds_viz.py` — read `chip.gds` → preview via a
  gdsfactory bridge + an always-available matplotlib fallback; CLI `--png`).
- **Status**: **current phase COMPLETE** — R1–R5 + R+ all met; PR #14 (`feat/native-geo-dsl` →
  `main`) **merged** (`931b8ec`). Post-merge (2606080906): docs/examples cleaned up for the native
  path (see below).
- **Tests** (2607280204): full suite **349 passed, 3 skipped, 1 deselected — 0 failed, 0 errors**
  in conda `metal-env` (2 min 25 s). Run it as
  `PYTHONPATH=src python -m pytest tests/ -q --deselect tests/test_geo_pipeline.py::test_two_pads_live_capacitance_matrix`
  and **without** `QDSL_MESH_ALGO3D` exported — see the two ⚠ notes in `CLAUDE.md`.
  - The `1 deselected` is the gated live-Palace test: it **cannot run at all right now**, `mpirun`
    is wedged on this host (see Open/next steps).
  - _Previously this file claimed `319 passed, 3 skipped` — that was stale by a wide margin. The
    real state at `5737011` was **8 failed / 313 passed / 2 errors**: session 2607021950's
    empty-mesh guard had **exposed** (not caused) a total breakage of the legacy YAML→gmsh path,
    which until then silently wrote empty meshes. Fixed in 2607280204; do not let this line rot again._
- **End-to-end**: `build_geo(two_pads.meta.yaml --run-palace)` → real C-matrix
  `[[24.73,-1.98],[-1.98,24.72]]` fF → (M6) tier-2 `hamiltonian` (2 grounded transmons, L_J=10nH:
  E_C≈0.788 GHz, f01≈9.36 GHz, g≈375 MHz). (M5a) a `cells:` sidecar elaborates v3 template
  instances → `<stem>.elaborated.geo` → GDS + mesh + carved-ground Palace config.

## Plan re-org (2026-06-08)
Re-anchored `plan.md` to the **5 original requirements** (R1 group→circuit ✅, R2 Palace→C-matrix ✅,
R3 circuit solve ✅, R4 read QDA ✅, R5 GDSFactory) + verbal "电容矩阵就够":
- **Active path**: ~~M5a (emit_geo)~~ ✅ **DONE** → ~~M6 circuit-model solve (R1+R3)~~ ✅ **DONE** →
  ~~M7 GDSFactory (R5)~~ ✅ **DONE** — current phase complete.
- **M2 / M4 / M5b deferred** — out of this phase, not ruled out (M2 ports/arc/qlib unneeded now;
  M4 eigenmode/driven later; M5b hierarchy/multi-layer/flip-chip later).
- emit_geo design + the 3 locked seam decisions: see `session/2606080224.md`.
- M6 design (inverse-cap LOM, `circuit_model` sidecar block, tier-2): see `session/2606080308.md`.
- M5a impl (emit_geo bridge, carved ground): see `session/2606080338.md`.

## Recent notable commits
- _(branch `main` — 2607280204)_ **`5737011` review 的修复落地** (6 个 commit: `8e45507` `d07b087`
  `ab94a13` `e61f324` `6db8134` + 收尾)。全套 `8 failed/313 passed/2 errors` → **`349 passed,
  3 skipped, 1 deselected, 0 failed`**。四条:
  1. **fragment 的 dilate 往返不是单位换算而是意外 shape-heal** (`occ.dilate` =
     `BRepBuilderAPI_GTransform`, 会重建每条曲线/曲面并放大容差)。`s=1`(坐标不变但仍重建) 与
     `s=1e2` 治好 qm4q 的效果完全一样, 而这次重建对另 6 个设计是纯损伤 → 改成
     **`FRAGMENT_SCALE_LADDER = (1.0, 1e2)`**, 1.0 档完全不 dilate, 仅 boolean 抛异常才升档。
     **legacy YAML 路径 9 个失败全清。**
  2. **fragment 后拓扑不变量** (负质量面/体、体积和超 bbox、carve 面面积上界) + `resolve_conductor_faces`
     加 bbox 包含判定 —— 原先整张 z=0 衬底/真空界面会被误标成 `gnd_layer1_sfs`(静默错解)。
  3. **浮动/差分多岛 transmon**: `C' = BᵀC_S B` 后求完整逆取 θθ 块; 全接地逐位向后兼容;
     与 qiskit-metal LOM 2.0 独立吻合 **<0.1%**。
  4. `_conductor_surface_tags` 补 `ground_faces`(#18 的机制)、`QDSL_MESH_ALGO3D` 分支补空网格守卫、
     `max_size_jj` 死开关告警、两个回退测试 `delenv` 该变量。
  **例子 `sung_2021_device` 现在端到端跑通并按论文标定**: C_Σ 102.1/232.8/102.1 fF vs 论文
  99.3/227.9/101.9 (比值 1.03/1.02/1.00), E_C 0.190/0.083/0.190 vs 0.195/0.085/0.190,
  q–c 无量纲耦合 1.07× —— 原先 E_C 差 4.4–6.7×、耦合差 20×。唯一未达标: 直接 q–q 电容 C_12
  低 ~50×(已在 header 如实写明)。See `session/2607280204.md`。
- _(branch `main` — 2607280204, review 阶段)_ **`5737011`
  (sung_2021_device 例子) review + qiskit-metal/Elmer 交叉验算**。例子 **端到端跑不通**:
  3D 网格生成在 5 种 Algorithm3D × 3 种 min_size × 2 种 `substrate_gap_um` × 7 种几何简化变体下
  **全部失败**;同 env 同命令的 `qm4q_transmon_cell` 正常,qiskit-metal 自己的 `QGmshRenderer`
  也能把同一份版图网格化(449k tets)→ 失败在我们的 carve/fragment 段(几何相关脆弱性)。
  取证发现库级 **silent-wrong-result**: `substrate_gap_um: 0` 时 `fragment_everything` 静默
  产出损坏模型(dielectric 体被复制、出现负面积 face),且 `resolve_conductor_faces` 只按质心
  bbox 判定 → 把整张 z=0 衬底/真空界面(1.6e6 µm²)误标成 `gnd_layer1_sfs`;fragment 后**没有任何
  拓扑不变量检查**。另: `generate_mesh` 的 `QDSL_MESH_ALGO3D` 覆盖分支绕过 2607021950 新加的
  空网格守卫(而演示命令恰恰要求带这个环境变量)。物理侧: 本机源码装好 **ElmerFEM 9.0**
  (`~/opt/elmer`),在 qiskit-metal 0.7.6 里 1:1 重建器件 → Elmer 电容 + LOM 2.0 + `Hcpb` 显示
  E_C 比论文大 **4.5–6.9×**、无量纲耦合小 **20×/42×**(几何未按论文标定);例子的单岛
  `circuit_model` 写法在自己的几何上也有 **1.85×** 误差(#20)。See `session/2607280204.md`。
- _(branch `main`, **未提交** — 2607021950)_ **静默空网格根因修复 + qm4q 汇报稿**:新 gmsh 构建
  (metal-env 已重建为 conda 4.11.1;qmetal-src pip 4.15.2)对共面 PLC 失败**不抛异常**,旧
  `generate_mesh` 的 HXT 回退永不触发 → qm4q 静默产出 533B 空网格(`build/qm4q/chip.msh` 即此),
  Palace abort。修复:空 3D 网格也触发回退、回退仍空则 raise;+2 回归测试
  (`test_geo_pipeline.py` **12 passed, 1 skipped**)。**演示/复现命令必须
  `export QDSL_MESH_ALGO3D=10`**(失败-Delaunay 后的进程内回退在新 gmsh 下无效,从头 HXT 两 env 均稳)。
  端到端重验 `build/qm4q_demo`(pad_top 103.5 fF,与 6/27 基线 <2%)。新增
  `docs/report/qm4q_talk_script.md`(对着念/操作的汇报稿)。See `session/2607021950.md`。
- _(branch `main` — 2606300056)_ **build 结果归档 + 文件指纹清单**: `build_geo()` 现在每次 build
  都把 `meta.yaml` + `.geo` 复制进 `out_dir`(保留原名),并写一个 `chip.manifest.yaml` —— 登记
  输入副本 + 全部产物(gds/msh/json/results)的 sha256 指纹、字节数、修改时间(UTC)。纯附加,
  未碰 results schema / provenance。新增 `_file_record()` helper、return dict 加 `"manifest"` 键、
  CLI 多打印 `Manifest` 行。+2 测试;`tests/test_geo_pipeline.py` **10 passed, 1 skipped**(was 9/1)。
  See `session/2606300056.md`.
- _(branch `fix/review-critical-robustness` — 2606081710)_ **xhigh re-review of #14 → 3 critical
  fixes** (silent-wrong-result hardening, each + regression test; all 3 adversarially verified
  "sound"): `carve_conductors` now **raises** on a split vacuum (was warn-and-continue → incomplete
  Palace domain); `circuit_model._invert_matrix` singular guard is now **scale-relative** (farad-scale
  ill-conditioned matrices raise, not invert to garbage); Palace C-matrix CSV parser **rejects
  nan/inf**. Full suite **319 passed, 3 skipped** (was 314/3, +5 new tests, 0 regressions). Deferred
  findings filed as **#18** (carved-ground mesh refinement → biased C) + **#19** (robustness checklist);
  the singular-guard item in **#15** is now resolved. See `session/2606081710.md`. _(branch not yet
  merged/pushed.)_
- _(branch `chore/viz-deps-and-cleanup` — 2606080906)_ **docs/examples cleanup + viz deps**:
  `examples/dsl/` is now geo-only (deleted `.note`/`notebooks`/`scripts`/`outputs`/`yaml` +
  `docs/codex_notes/dsl_v3_*`); the 2 test-referenced `.metal.yaml` moved to `tests/fixtures/`;
  `README.md` + `examples/dsl/README.md` rewritten for the native-geo path; `refer/` untracked +
  gitignored; local gmsh SDK removed. **Installed gdsfactory 9.2.2** (viz extra) — needed
  `gdsfactory<9.3` (keeps numpy~=1.24) + `pydantic<2.11` (kfactory 1.2.2 import); added cross-platform
  `requirements.txt` + capped the `viz` extra. v3 engine + all 5 legacy test files kept (314 passed,
  3 skipped). See `session/2606080906.md`.
- _(PR #14)_ **M7**: `dsl/gds_viz.py` GDSFactory visualization (gdsfactory bridge + matplotlib
  fallback, CLI `--png`) — full suite 314 passed, 3 skipped.
- `f376b0e` **merge**: M5a + M6 integrated into `feat/native-geo-dsl` (302 passed, 1 skipped).
- `5e13311` **M5a**: emit_geo cell-library bridge + carved metal ground.
- `6ad6845` **M6**: circuit-model solve — Palace C-matrix → transmon Hamiltonian (R1+R3).
- `1e91315` **M3**: live Palace capacitance write-back + conductors-as-voids mesh.

## Open / next steps
- 🔴 **BLOCKER — 本机 MPI 坏了, Palace 完全不可用**。`mpirun` 挂死在 `orte_ess_hnp` 的 init 内部
  (`ess` 能选中 `hnp` 组件, 之后 `plm`/`oob`/`odls`/`rml` 的 verbose 一个字都不吐);
  直接跑 `palace-x86_64.bin`(含 `OMPI_MCA_ess=singleton`) 同样挂 → 卡在 `MPI_Init` 本身。
  已排除残留进程/磁盘/IPC/fd 上限/oob 网卡/IPv6 开关/TMPDIR/MCA 配置/hostfile/`plm isolated`。
  建议先 `wsl --shutdown` 重启, 不行再重装 `openmpi-bin`。
  **修好后必须补的实解回归**(现在完全没有实解覆盖):
  1. `two_pads` C 矩阵是否仍为 `[[24.73,-1.98],[-1.98,24.72]]` fF —— 验证
     `FRAGMENT_SCALE_LADDER` 与 `ground_faces` 细化没有移动电容值(目前只验到 `chip.json` 逐字节
     相同 + physical group 不变 + `chip.msh` 尺寸差 0.3%);
  2. `sung_2021_device` 用我们自己的 Palace 解一次, 与 Elmer 的 102.1/232.8/102.1 fF 对照
     (现在这三个数**只有 Elmer 一侧的证据**);
  3. `ground_faces` 细化对 C 的量化影响 = issue **#18** 的正题。
- **参考侧对照已可跑**: ElmerFEM 9.0 装在 `~/opt/elmer`(`export PATH=$HOME/opt/elmer/bin:$PATH`),
  conda env `quantum-metal` = quantum-metal 0.7.6(editable 自 `~/metal/qiskit-metal`)。
  复用脚本(scratchpad, 见 session log): `qm_sung.py`(qiskit-metal 重建 + Elmer)、
  `analyze.py`(Elmer→Maxwell→我们的 circuit_model + 论文对比)、`lom2.py`(LOM 2.0 + Hcpb)。
  两个上游坑要绕: `ElmerRunner` 假定相对路径布局; `_get_capacitance_matrix` 用 pandas 链式赋值设
  Maxwell 对角, 在 pandas ≥2 下静默失效。qm4q 的原定「与 qiskit-metal 自带解对比」可以补做了。
- **`occ.fragment` 对近邻但不重叠的 pocket carve 退化**(A4 实测): pocket 重叠 30/40 µm 干净,
  重叠 10 µm 与完全不重叠都抛 `Boolean fragments failed`, 且 scale 1/1e2/1e3 皆然 → 是 boolean
  本身。重画例子几何时留意, 已写进 `sung_2021_device.geo` header。
- **提出但未实施的 feature 缺口**(按性价比): ① `targets:` 验收块(meta 里声明期望 C/E_C/g + 容差,
  求解后写 `validation:` 段并打印偏差 —— 本次事故的根因级预防) ② Elmer 作为第二求解器后端做交叉
  验证 ③ `mesh.conductor_mode: void|volume`(现在只有 conductors-as-voids 一条路)
  ④ 网格收敛扫描 `--converge`(实测 5/50→2/30 差 6%, 而 `tier` 只描述完整度不描述精度)
  ⑤ SQUID/磁通可调 E_J(论文的 CPLR/QB2 是非对称 SQUID, 现在只能填零磁通最大值, 也是本次
  g 偏高 1.4× 的主因) ⑥ 浮动 bus 的 Schur 消元(#20 另一半, 现在被硬接地)。
- **#14 re-review follow-ups**: 3 critical fixes landed on `fix/review-critical-robustness`
  (push + PR pending). Deferred: **#18** (carved-ground mesh refinement → biased C; needs a
  live-Palace re-validation since it moves the C numbers), **#19** (robustness/silent-failure
  checklist), and the remaining items in **#15**.
- **viz**: install the `viz` extra (`gdsfactory`) to exercise that backend live — it is absent in
  metal-env, so its 2 tests are gated/skipped (the matplotlib fallback IS verified).
- **M5a follow-ups**: full-chip live Palace solve on an emit_geo ground design (gated); connection-pad
  transmons may overlap the ground (clean-disjoint cells are the tested path); ε-vacuum-gap artifact
  under carved metal.
- **M6 follow-ups**: multi-island (floating/differential) qubits (schema accepts, solver defers) —
  now tracked in **#20**, together with the floating-bus grounding bug (non-qubit terminals are
  hard-grounded, killing bus-mediated coupling → needs Schur-complement) and the meta→tier-2 wiring
  bug (`geo_build` reads `islands` but `two_pads.meta.yaml` has `island:`; `L_J: 10nH` never
  unit-parsed). Surfaced while fixing `chip_layout.geo` (see `session/2606081754.md`).
- **chip_layout.geo** (example): now a proper 2-transmon + coupling-bus layout (pads isolated in
  vacuum pockets; lower pad capacitively coupled to the bus via a neck+paddle). tier-1 verified;
  tier-2 blocked on **#20**. Changes uncommitted on `fix/review-critical-robustness`.
- `CLAUDE.md` no longer pins "M1–M5" — milestones are re-scoped per phase (see `plan.md`).
