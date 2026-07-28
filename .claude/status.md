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
- **Tests** (2607290110): full suite **368 passed, 3 skipped — 0 failed, 0 errors, 0 deselected**
  in conda `metal-env` (2 min 30 s). Run it as
  `PYTHONPATH=src python -m pytest tests/ -q`
  and **without** `QDSL_MESH_ALGO3D` exported — see the ⚠ notes in `CLAUDE.md`.
  - The `--deselect` ritual is **gone**: the live-Palace `skipif` marker had drifted onto
    `test_build_geo_archives_inputs_and_writes_manifest` (which needs no Palace) while the real
    live test `test_two_pads_live_capacitance_matrix` had no gate at all. Fixed in 2607290110.
    The 3 skips are now 2 × viz (`gdsfactory` absent) + 1 × gated live Palace.
  - Reconciliation: 349 passed + 1 hand-deselected = 350 → +15 SQUID +1 `--np` +2 nan/inf = 368.
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
- _(branch `main` — 2607021950, 已提交 `30a241e`)_ **静默空网格根因修复 + qm4q 汇报稿**:新 gmsh 构建
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
  the singular-guard item in **#15** is now resolved. See `session/2606081710.md`. _(已合并进 `main`。)_
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
- ✅ **MPI 挂死已修**(根因非 openmpi): hwloc 的 `gl` 插件会**通过 TCP** 探测 X display
  `:0…:N`(127.0.0.1:6000+N) 来枚举 NVIDIA GPU; 本机 127.0.0.1:6001 黑洞掉 SYN(无 listener、
  无 RST —— WSL2 localhost 转发), `connect()` 永久阻塞 → **任何** MPI 程序在 `MPI_Init` 返回前
  就挂死且零输出。修法 `HWLOC_COMPONENTS=-gl`, 已用 `conda env config vars set` 持久化进
  `metal-env` 与 `quantum-metal`(新建 env 必须照做)。取证见 `session/2607280204.md`。
  ⚠ 早先「因为 `DISPLAY` 为空所以不是 X11」的判断是错的。
  **三笔实解回归欠账**:
  1. ✅ `two_pads` —— 实测 `[[24.7288,-1.976],[-1.976,24.7293]]` fF vs 基线
     `[[24.73,-1.98],[-1.98,24.72]]`, **max |rel dev| 0.202%**; tier-2 `C_Σ=24.571 fF,
     E_C=0.7883 GHz, f01=9.365 GHz, g=374.2 MHz`。`FRAGMENT_SCALE_LADDER` 与 `ground_faces`
     细化**没有移动电容值**。⚠ 但该测试**只断言结构/符号**, 上面这组数是手工核对的 ——
     数值断言待补, 连同未被利用的 `terminal-Cinv.csv` 交叉校验记在 **#28**。(该测试目前只断言结构/符号, **数值断言仍待补**, 带容差。)
  2. ✅ **`sung_2021_device` Palace ↔ Elmer ↔ 论文 三方闭环** (2607280204 §7)。Palace p=1 / 8 rank /
     50.9 s: C_Σ **110.69 / 252.80 / 111.03 fF** vs Elmer **102.1 / 232.8 / 102.1** vs 论文
     **99.3 / 227.9 / 101.9**; **Palace/Elmer = 1.084 / 1.086 / 1.087**。三个 qubit 上高度一致
     → **系统性偏移而非噪声**, 最可能是网格收敛(我们 `max_size 80` vs Elmer 侧 `max 30`, 而 Elmer
     自身 5/50→2/30 就降 6%), 次因是外边界不等价(自然 Neumann vs `Electric Infinity BC`)。
     **表述: 两个独立求解器在较粗一方的网格收敛不确定度之内互相印证。** A4 的 1.03/1.02/1.00
     仍以 Elmer 为准(网格更细), Palace 这组是佐证不是替代。
     ⚠ 口径是 **order 1**, 而 sidecar 声明 `order: 2` —— 见下。
  3. 🔴 `ground_faces` 细化对 C 的量化影响 = issue **#18** 的正题, **仍欠**(已在 #18 留进展评论)。(2607290110 的
     ε-nudge 重标定量化的是**另一个**旋钮 —— 衬底顶面的 ε 缝, 不是 ground 腔壁的网格细化。)
- 🔴 **order 2 在多 rank 下解不出来**(2607280204 §7): 16 rank 三次尝试都在第 2 个 terminal
  静默掉 rank; order 1 / 8 rank 干净跑完。已排除场输出、OOM、vader/CMA(那只是 `ptrace_scope=1`
  触发的噪音症状)。剩余怀疑: 误差估计器的 `RT (p=2): 14151282` 空间。**后果: 这个例子当前无法在
  本机跑出它自己声明的精度。** 下一步: 降到 2 rank / 单 rank 加长 timeout, 区分「rank 间通信」
  与「order 2 本身」。→ **#22**。
- **参考侧对照已可跑**: ElmerFEM 9.0 装在 `~/opt/elmer`(`export PATH=$HOME/opt/elmer/bin:$PATH`),
  conda env `quantum-metal` = quantum-metal 0.7.6(editable 自 `~/metal/qiskit-metal`)。
  复用脚本(scratchpad, 见 session log): `qm_sung.py`(qiskit-metal 重建 + Elmer)、
  `analyze.py`(Elmer→Maxwell→我们的 circuit_model + 论文对比)、`lom2.py`(LOM 2.0 + Hcpb)。
  两个上游坑要绕: `ElmerRunner` 假定相对路径布局; `_get_capacitance_matrix` 用 pandas 链式赋值设
  Maxwell 对角, 在 pandas ≥2 下静默失效。qm4q 的原定「与 qiskit-metal 自带解对比」可以补做了。
- **`occ.fragment` 对近邻但不重叠的 pocket carve 退化**(A4 实测): pocket 重叠 30/40 µm 干净,
  重叠 10 µm 与完全不重叠都抛 `Boolean fragments failed`, 且 scale 1/1e2/1e3 皆然 → 是 boolean
  本身。重画例子几何时留意, 已写进 `sung_2021_device.geo` header。
- **ε-nudge 已重新标定** (2607290110): 默认 `CARVED_GROUND_SUBSTRATE_GAP_SI` **1 µm → 0.01 µm**。
  实测(`two_pads` + 一张 carved ground 环, 只变 ε, 8-rank Palace 实解): 旧的 1 µm 默认值
  **压低 C_AA 29.1%、压低耦合 C_AB 40.3%**; 0.01 µm 只差 0.03%。所以历史上那个「~30% 误差」
  **是默认值比需要的大三个数量级造成的, 不是挖空的内在代价**。ε=0 不是万能解: 该几何在任何
  coordinate scale 下都 fragment 失败; ε=0.5 更产出损坏拓扑(被 A1 的不变量拦住) → OCC 共面
  布尔的抽风是**非单调**的。完整 ε 阶梯表在 `_gmsh_geo_source.CARVED_GROUND_SUBSTRATE_GAP_SI`
  的注释里。适用面: 只在**有 carved ground** 且走 **auto-substrate** 时触发 —— `two_pads`
  (没有 `ground::`)与 `qm4q`/`sung`(显式 `substrate_gap_um: 0`)一直都是物理精确的,
  受影响的只有 `chip_layout` 与 `tiny_chip` fixture。
- **feature 缺口**(编号沿用 2607280204 的提出顺序):
  - ✅ ⑤ **SQUID / 磁通可调 E_J** —— 2607290110 落地。`squid: {E_J1, E_J2, flux}` 子块,
    `E_J,eff = E_JΣ·sqrt(cos²(πΦ/Φ0) + d²sin²(πΦ/Φ0))`(Koch 2007 的无奇点等价形式,
    教科书的 `|cos|·sqrt(1+d²tan²)` 在 Φ=0.5Φ0 处 tan 发散 → nan)。`L_J`/`E_J`/`squid` 三选一。
  - ✅ **⑦(新)** `geo_build --np N` —— `run_palace` 一直支持 `num_procs`, 但 `geo_build` 硬编码
    不传 → `--run-palace` 永远单 rank。2607290110 落地。
  - 🔴 ① `targets:` 验收块 → **#23**(性价比最高; 2607280204 那次事故的根因级预防)。
  - 🔴 ② Elmer 第二求解器后端 → **#25**(含 ElmerFEM 9.0 的构建坑与 qiskit-metal 两个上游 bug)。
  - 🔴 ③ `mesh.conductor_mode: void|volume`(现在只有 conductors-as-voids 一条路) —— 代价是
    OCC 布尔在共面输入上脆弱(见上一条 bullet), 而 ε-nudge 只是绕开它的标定旋钮。volume 模式
    (零厚度面 `fragment` **进**界面, Palace 自己的 CPW 例子与 qiskit-metal 的 Elmer 流程都这么做)
    根本不需要共面布尔, 既是退路, 也是第一次能让两条路的 C 互相对照。→ **#24**。
  - 🔴 ④ 网格收敛扫描 `--converge` → **#26**。
  - 🔴 ⑥ 浮动 bus 的 Schur 消元 → **#20** 的剩余部分。**不能**用 σ 那套办法: qubit 两焊盘与外界
    无电荷交换故丢掉 σ 正确, 而浮动 bus 是真正的动力学自由度、同时耦合两个 qubit, 必须正确积掉
    (消元会重整化 qubit-qubit 耦合)。
  - 🟡 **`run_palace` / Palace config 三处待整理** → **#27**(另含场输出硬编码): `dry_run` 完全吞掉 `num_procs`
    (Palace `--dry-run` 本意就是按 rank 数试划分, 故 `--np 8 --dry-run` 现在验不到 8 路划分);
    native 分支无条件追加 `-np N` 而 WSL 分支只在 `>1` 时前置 `mpirun -np N`。
- **#14 re-review follow-ups**: 那 3 个 critical fix **已在 `main`**
  (`git branch --merged main` 含 `fix/review-critical-robustness`; nan/inf 拒绝在
  `palace_adapter.py:539`, scale-relative 奇异守卫在 `circuit_model._invert_matrix`,
  carve 分裂真空 raise 在 `_gmsh_layers`)。仍 open: **#18** / **#19** / **#15** 的剩余项。
- **viz**: install the `viz` extra (`gdsfactory`) to exercise that backend live — it is absent in
  metal-env, so its 2 tests are gated/skipped (the matplotlib fallback IS verified).
- **M5a follow-ups**: full-chip live Palace solve on an emit_geo ground design (gated); connection-pad
  transmons may overlap the ground (clean-disjoint cells are the tested path); ε-vacuum-gap artifact
  under carved metal.
- **#20 现状**(2607280204 更新, 三条里两条已了结): ✅ 多岛浮动/差分 transmon **已实现**
  (`a8e3ed7`, 与 LOM 2.0 吻合 <0.1%); ✅ 「meta→tier-2 wiring bug」经核实**本就不存在**
  (`_parse_qubit_entry` 早已把 `island:` 归一成 `islands`, `L_J: 10nH` 走 `_parse_unit_value`)
  —— 已补测试钉住; 🔴 仅剩**浮动 bus 被硬接地**(需 Schur 消元)。
- **chip_layout.geo** (example): 2-transmon + coupling-bus 布局(焊盘在真空孤岛里, 下焊盘经
  neck+paddle 电容耦合到 bus)。**改动已提交** (`cfce32f`)。tier-1 已验证; tier-2 仍卡在 #20
  的浮动 bus 那一半。
- `CLAUDE.md` no longer pins "M1–M5" — milestones are re-scoped per phase (see `plan.md`).
