# Quantum-DSL — Native Gmsh `.geo` → GDS + Palace (electrostatic capacitance)

Progress tracker for the geometry-layer pivot, **re-anchored to the original requirements** (2026-06-08).

**Layer-1 physics metadata (`*.meta.yaml`)** → **Layer-2 native Gmsh `.geo`** →
{ Gmsh mesh → **Palace** (Electrostatic) → C-matrix → circuit model · gdstk → **GDSII** → GDSFactory viz }.

Full design + binding contract: `C:\Users\Administrator\.claude\plans\gmsh-dsl-expressive-perlis.md`.
emit_geo cell-migration design + the 3 locked seam decisions: `session/2606080224.md`.
Status legend: `[x]` done · `[~]` in progress · `[ ]` not started · `[defer]` deferred (out of the current phase, not ruled out).

---

## Current-phase requirements

The original requirements are **phased** — the list below is *this* phase's target, not a final
ceiling. For now: rounded-corner polygon cells + an electrostatic capacitance matrix (verbal:
*"画出多边形 with 圆角, 静电学求解电容矩阵就足够了"*). Eigenmode/driven, lumped ports, and loss are
**out of this phase**, not rejected — later phases can pick them up. The M-numbers below are stable
IDs; the **Active path** section is the order for now.

| # | Requirement | Status | Where |
|---|---|---|---|
| R1 | Connect Gmsh physical group → circuit model | `[x]` | binding (M1 `::` + M3 `terminal_bindings`) + circuit-model half (**M6**: island group → qubit Hamiltonian) |
| R2 | Run Palace on the `.geo` mesh → capacitance matrix | `[x]` | **M3** (live C-matrix on `two_pads`) |
| R3 | Run circuit-model solver with the C-matrix, save it | `[x]` | **M6** (inverse-cap LOM → tier-2 `hamiltonian` in `chip.results.yaml`) |
| R4 | Read the QDA review — how/why we compute capacitance | `[x]` | GHz qubit, λ≈cm ≫ footprint≈100µm → lumped model valid → C-matrix → qubit Hamiltonian via circuit quantization + charge-crosstalk (QDA §Layout-sim/Electrostatic + §Hamiltonian derivation) |
| R5 | Add GDSFactory for visualization | `[x]` | **M7** (`gds_viz`: gdsfactory bridge + matplotlib fallback) |
| R+ | Cells = polygons **with rounded corners** | `[x]` | **M5a** (emit_geo: pre-sampled shapely buffers → rounded-corner polygons) |

---

## Done

### M1 — Both branches end-to-end on a tiny example  `[x]`
Goal: one `.geo` + sidecar → `chip.gds` **and** `chip.msh` (msh2.2) + Palace Electrostatic JSON.

- [x] **Foundation**: `schema.py` geo/gds/solver constants; `_gmsh_physical` integer-attribute
      capture + `geo_name_to_group()`; `assign_physical_groups → (groups, attrs)`;
      `GmshMeshResult.physical_attributes`; `pyproject` `gds=[gdstk]` extra.
- [x] **GEO ingest** `dsl/_gmsh_geo_source.py`: `load_geo` / `split_geo_name` / `surface_outline_um` /
      `populate_tracker_from_geo` / `compute_chip_bbox_from_geo` / `ensure_dielectric_substrates`.
- [x] **Examples**: `examples/dsl/geo/{qlib.geo, chip_layout.geo, chip_layout.meta.yaml}`,
      `tests/fixtures/tiny_chip.{geo, meta.yaml}`.
- [x] **GDS backend** `dsl/gds_adapter.py` (+ `_gds_layers.py`): `build_gds` / `verify_roundtrip` /
      `GDS_LAYER_MAP` (microns verbatim, `unit=1e-6`).
- [x] **Palace backend** `dsl/palace_adapter.py`: `build_palace_config` / `validate_config` /
      `run_palace` / `_to_wsl_path` (Electrostatic, `L0=1.0`).
- [x] **Wiring/CLI** `dsl/gmsh_adapter.build_mesh_from_geo`, `parsers/simulation.py`
      (`parse_geo_meta_sidecar` + `gds`/`solver` parsing), `dsl/geo_build.py` CLI, lazy package exports.
- [x] **Tests**: pure + `importorskip`-guarded `tests/test_geo_*.py` — **65 passed**.
- [x] Regression: `import quantum_dsl` no eager gmsh/gdstk; full suite **236 passed, 0 failed**.
- [x] **End-to-end demo**: `build_geo(chip_layout.meta.yaml)` → `chip.gds` (metal/ground L1 + JJ L20,
      µm verbatim) + `chip.msh` (15 groups, msh2.2) + `chip.json`. Two real bug fixes:
      (a) `_gmsh_mesh.define_size_fields` clamped `MeshSizeMin` above `max_size_jj` → now
      `min(min_size, max_size_jj)`; (b) JJ treated as a **lumped element** in the geo mesh branch
      (`populate_tracker_from_geo` removes it — meshing it shorts the pads & breaks the tet mesh),
      still emitted to GDS layer 20.
- [x] `palace --dry-run` end-to-end (WSL spack Palace 0.16): *"No errors detected in configuration
      file chip.json"*. Fixed `geo_build` so `Model.Mesh` is relative to the config dir.
- [x] Cleanup: fixed pre-existing stale `examples/dsl/` → `examples/dsl/yaml/` paths in
      `test_design_dsl.py`, `test_design_dsl_transmon_pocket.py`, `test_design_dsl_gmsh.py` (5 → green).

### M3 — Capacitance results + verification loop  `[x]`
- [x] **Results write-back design locked** (3-lens workflow): OUTPUT-ONLY artifact
      `out_dir/chip.results.yaml` (schema `qiskit-metal/design-results/1`); NOT in
      `*.meta.yaml`, `GEO_META_ROOT_KEYS` untouched. Completeness `tier:` ladder
      T0–T4; full Hamiltonian needs NO new authored layer (inputs→Layer-1 sub-blocks,
      outputs→results artifact). See `session/2606072351.md`.
- [x] `parse_capacitance_matrix(postpro_dir, terminals=())` — real parser for BOTH
      `terminal-C.csv` (Maxwell, +diag/−offdiag) and `terminal-Cm.csv` (mutual,
      all-positive), F→fF, header-keyed, asserts square + row order + #terminals.
      `domain-E.csv` (energy) not yet parsed.
- [x] `TerminalBinding` + `terminal_bindings()` = matrix row/col **single source of
      truth**; `build_palace_config` refactored to share it. `write_results_sidecar`
      emits the artifact + provenance (sha256 of geo/mesh/config, solver, label→index).
      `geo_build` wires it after a non-dry-run solve. **Full suite 250 passed.**
- [x] Parser verified against **real Palace 0.16 CSV output** (verbatim PoC fixtures);
      `tests/fixtures/two_pads.{geo,meta.yaml}` clean 2-conductor reference added.
- [x] **Conductors-as-voids (Approach A)** — live solve UNBLOCKED. `carve_conductors`
      (occ.cut metal terminals OUT of the vacuum) + `resolve_conductor_faces` (post-fragment
      bbox re-key → `conductor_faces`), so every Terminal face is EXTERIOR (Palace's
      invariant). `assign_physical_groups` re-emits `{C}_{P}_sfs` byte-identical;
      `vacuum_outer` = domain combined-boundary − cavity walls. **Geo-path-only** (legacy
      slab path + GDS untouched). 6 files; `tiny_chip` cutout enlarged → disjoint pad.
- [x] **Two-conductor reference + known-sign C-matrix**: `tests/fixtures/two_pads.*` →
      live Palace solve → `chip.results.yaml` maxwell `[[24.73,-1.98],[-1.98,24.72]]` fF
      (+diag/−offdiag/symmetric), mutual all-positive. Gated test
      `test_two_pads_live_capacitance_matrix` (QDSL_RUN_PALACE=1) **passes**; full suite
      **251 passed, 1 skipped**.
- [x] **End-to-end harness**: `build_geo(--run-palace, non-dry-run)` parses postpro CSVs +
      writes the results artifact automatically. (`domain-E.csv` energy parse still TODO.)
- _Scope note (→ M5a/M6):_ only metal **terminals** are carved so far; ground-plane designs
      need the metal GROUND sheet carved too (→ **M5a**), `chip_layout` needs disjoint authoring for a
      full-chip live solve, and the legacy YAML path is still on the slab representation.
      `domain-E.csv` (field energy) not yet parsed (→ M6 if needed).

---

## Active path (correct order)

### M5a — emit_geo cell library (rounded-corner cells)  `[x]`  (DONE — merged)
Lower the v3 component templates (`transmon_pocket`, then `resonator`/`coupler`) → a flat,
positive-tone `.geo` so the existing GDS + mesh + Palace-electrostatic pipeline consumes
parametric, **rounded-corner** cells unchanged (delivers R+). Reuses the entire v3 front-end
(`build_ir` → resolved shapely `PrimitiveIR`); **no** qiskit-metal QComponent/QDesign instantiation;
**no** qlib macros (emit flat explicit geometry). The emitter runs strictly **upstream of `load_geo`**
(writes `<stem>.elaborated.geo`); nothing below `load_geo` changes → Palace names stay byte-identical
(geometry-source-agnostic), dual-branch µm/µm→m split preserved.

**Locked seam decisions (session `2606080224.md`):**
- **(#1 ground — ADOPTED)** synthesize **one chip-wide ground per layer**, extent from
  `compute_chip_bbox_from_geo` (sidecar floorplan may override); aggregate **all** `subtract:true`
  primitives (pocket + cpw-gaps, across all cells) into that one sheet via a single OCC
  `BooleanDifference` → `ground::N::chip::gnd`. **NOT** per-component differencing (would erase pads;
  `apply_cuts` cuts per-LAYER, `_gmsh_layers.py:254`). This is also what `carve_conductors` must carve.
- **(#2 ports — DEFERRED contract)** emit `PinIR` as a **plain `port::layer::comp::pin` dim-1 marker
  only**; the edge-topology / fragment-survival / lumped-port contract is **deferred** (electrostatic
  uses conductor surfaces, not 1D ports; M4 deferred too).
- **(#3 curves — ADOPTED)** **pre-sample** shapely buffers → polygon `Line` segments in Python
  (rounded corners come from the buffer); guarantees GDS == mesh parity, sidesteps loader arc sampling.

- [x] `dsl/geo_emit.py` `emit_geo(design_ir, out_path, *, arc_tol_um, ground_margin_um, chip_bbox,
      emit_ports, cap/join_style)` → `.geo` text (imports **only shapely** — no gmsh/gdstk).
- [x] Positive primitives → OCC `Plane Surface` + call-site `Physical Surface("role::layer::comp::prim")`
      (`junction.*`→`jj`, else `metal`); paths/junctions buffered to closed polygons (round joins =
      rounded corners; flat caps for the lumped JJ).
- [x] Synthesized chip-ground (one sheet per layer, bbox extent) + aggregated `subtract:true` holes via a
      single OCC `BooleanDifference` (decision #1). **Discovery:** a multi-loop `Plane Surface` extrudes
      its holes FILLED → emit the ground via `BooleanDifference` so the holed face extrudes to a true
      holed prism.
- [x] Pins → plain `port::` dim-1 marker (decision #2; off in mesh fixtures to keep free edges out).
- [x] `cells:` sidecar block (`cell_type` + globally-unique `component` + `x/y/rot/layer` + `params`) +
      an **Elaborator** `elaborate_cells` (`build_ir` per instance → `emit_geo` → concat one
      `<stem>.elaborated.geo`; asserts unique `<component>`); substituted in `geo_build` so BOTH forks
      consume it (`geo` becomes optional when `cells:` is present).
- [x] Extended `carve_conductors` to also carve the synthesized **ground** sheet (`ground_solids`/
      `ground_faces` → `gnd_layer{N}_sfs`; legacy YAML slab path untouched). **Discovery:** a carved
      ground coplanar with the substrate top at z=0 destabilises OCC `fragment` → drop the auto substrate
      top by ε (`CARVED_GROUND_SUBSTRATE_GAP_SI`, 1µm) only when a carved ground is present; `two_pads`
      (no ground) untouched → its verified C-matrix preserved.
- [x] **Golden parity test** + `test_geo_emit.py` (11 tests): authored ids + GDS layers + final
      `assign_physical_groups` names byte-identical to a hand-authored `.geo`; pure-shapely import;
      Elaborator placement/unique-guard; sidecar parse (geo-optional); `build_geo` cells end-to-end
      (GDS + msh + carved terminals + carved ground). Example `examples/dsl/geo/cells_2q.meta.yaml`.
      Worktree suite **262 passed**; **302 passed, 1 skipped** after merge with M6.

### M6 — Circuit-model solve (R1 + R3)  `[x]`
Consume the C-matrix → qubit Hamiltonian parameters → save (closes "physical group → circuit model").
- [x] `dsl/circuit_model.py` (pure: math + dataclasses, NO gmsh/gdstk/numpy/scipy) reads the
      Maxwell C-matrix → **lumped-oscillator INVERSE-capacitance** quantization. Per qubit:
      `E_C=(e²/2)[C⁻¹]_ii`, `C_Σ=1/[C⁻¹]_ii`, `E_J=(ħ/2e)²/L_J`, `f01=√(8·E_C·E_J)−E_C`, `α=−E_C`;
      pairwise `g` from `[C⁻¹]_ij`. Reduces EXACTLY to `e²/2C_ii` for a single isolated island and
      to `½(C_g/√(C_iC_j))√(f_if_j)` for N=2, but stays rigorous for N≥3 (naive Maxwell-diagonal
      C_Σ double-counts coupling caps — caught by the physics-review workflow). Constants exact-SI-2019,
      `ħ` derived. `EJ_over_EC` + `validity` note emitted (regime-aware).
- [x] **Optional Layer-1 sub-block** = NEW top-level `circuit_model:` sidecar key (NOT `circuit`/
      `hamiltonian` — those are legacy full-DSL keys; no collision). `circuit_model.qubits:
      [{name, island|islands, L_J|E_J}]`, parsed by `_parse_circuit_model`; new SI-prefix unit parser
      `_parse_unit_value` (`10nH`→Henry, `16GHz`→Joule via ×h; explicit unit required). Derived
      Hamiltonian → results artifact **tier T2** (descending ladder; `write_results_sidecar` emits a
      `hamiltonian:` section + derives `tier=2 if circuit_model else 3` + a `tier_meaning` note).
      Wired in `geo_build` after the C-matrix parse. Closed-form (no scqubits/qiskit-metal dep);
      OPTIONAL gated cross-check vs qiskit-metal `Hcpb` exact CPB diagonalisation.
- [x] Verified on `two_pads` (37 pure tests, golden values closed-form-verified; gated live solve
      now also asserts the tier-2 Hamiltonian). On an emit_geo transmon → once M5a lands.
- [x] islands future-proofed as a tuple; solver gated to single-island (multi-island raises a clear
      "not supported yet"). Adversarial impl-review (4-agent workflow) → fixed 1 bug (non-transmon
      regime f01≤0 leaked a bare ValueError → now a clear DesignDslError) + nits. Full suite
      **290 passed, 1 skipped**; live solve (QDSL_RUN_PALACE=1) verified.

### M7 — GDSFactory visualization (R5)  `[x]`
NEW `dsl/gds_viz.py` (visualization-only, additive). `preview_gds(gds_path, *, out_png, backend,
dpi, layer_colors)` → `GdsPreview` (layers / polygon_counts / bbox_um / top_cell; renders a PNG
when `out_png` is given). `read_gds_layers` introspection; `to_gdsfactory_component`
(= `gf.import_gds`) is the R5 bridge into the gdsfactory ecosystem.
- [x] Backends: **matplotlib** (gdstk read + headless Agg canvas — the always-available default)
      + **gdsfactory** (optional `viz` extra; `backend="auto"` picks it when importable). All heavy
      deps imported **lazily** → `import quantum_dsl` stays clean (purity test).
- [x] **gdstk stays the emitter**; gds_viz only READS a finished `chip.gds`. `pyproject`
      `viz = ["gdsfactory"]`; lazy exports in both `__init__.py`; `geo_build` CLI `--png [PATH]`
      renders the produced `chip.gds`.
- [x] `tests/test_gds_viz.py` (14): matplotlib render + real-`chip.gds` integration + lazy exports
      + purity + error paths (**12 passed**); gdsfactory backend **2 gated** (skip — `gdsfactory`
      absent in metal-env, so that path is implemented-but-unverified-here). CLI `--png` verified
      end-to-end (`two_pads` → real 1397×657 PNG). Full suite **314 passed, 3 skipped**, no regressions.

### M8 — LOM parity: 分块提取 + 拼装层（对标 New LOM / LOM 2.0）
Spec: **`.claude/lom-parity-spec.md`**（v3；对标基线 = `lom_core_analysis.py` + tutorial 4.04/4.05，
理论 arXiv:2103.10344）。目标是让 `meta.yaml + .geo` 路径具备 qiskit-metal LOM 流程的**基本功能面**。
Legend 同上。**P0 = M8a–M8d 已全部完成**（`session/2607290329.md`）；P1/P2 切后续 phase。

- [x] **M8a — P0-A 子集提取**：`geo_emit.emit_block_geo()` 从完整 `.geo` 派生并**落盘**
      `block_<name>.geo`（G1：严格在 `load_geo` 上游，下游一行不改 → Palace 的 physical group 名
      byte-identical）。**S2 pocket 保留改成 shapely 求交**（`ground_poly ∩ 块窗口` 自动保留窗口内
      全部孔，与哪个 component 入选无关）→ spec 的头号 silent-wrong 风险 R1 从「要小心」变成
      「结构上写不错」；`keep_all_subtractive=False` 只作故意错的护栏路径。**S4 airbox 零代码**
      （由 `compute_chip_bbox_from_geo(块几何)` 派生）。顺带放宽 `build_palace_config` 的
      ≥2 Terminal → ≥1（单导体块合法；0 个仍 raise）。
      验收：`two_pads` 分块 vs 整片对角 **+1.03%/+1.06%**（<2% ✓）；`block_*.geo` 落盘+manifest
      +sha256+名字逐字；S4 bbox 收缩 `chip_layout` −40.5%；S2 护栏 ground 面积 +7.14%/孔 2→1。
      ⚠ **§7 的 S2 live Palace 护栏未跑** —— 需要 pocket 互不相连的设计。
- [x] **M8b — P0-C 文件/inline 矩阵注入**：`palace_adapter.capacitance_from_file/​_inline`
      （Palace CSV + Q3D txt + inline；互容↔Maxwell 显式判定，不用上游那段 pandas 链式赋值）；
      `CapacitanceResult` 加 `source`/`sha256`（R4）；CLI `--no-solve`。
      验收：**Q3D 解析对参考 `load_q3d_capacitance_matrix` 逐位一致**；`_SUNG_MAXWELL` 往返恒等逐位。
- [x] **M8c — P0-B 拼装层**（核心）：新 `dsl/assemble.py`（纯 stdlib）—— 电容图按**共享节点名累加**
      + **Schur 消元**非动力学节点（eq 7b）+ 审计。**Schur 在 node 基做，不复刻 `S_n`**；结基变换
      仍归 M6 的 `C' = BᵀC_S B` → **M6 一行不改**。非动力学节点用**结构判定**（spec §12 第 2 项的
      裁决），已对参考 `get_nodes_keep()` 逐项比对。
      验收：**对 4.05 golden 的 `C_k` 偏差 7.7e-16**（<0.1% ✓）；`C_n` 累加逐位；
      **issue #20 / 缺口 ⑥ 收尾** —— 硬接地把跨 cell `g` 25.14 MHz **删成 0.00**，块内 C_Σ +0.9%。
      fixture `tests/fixtures/lom405/`（4.05 两份矩阵，Apache-2.0 + `SOURCE.md`）。
- [x] **M8d — P0-D/E/F**：`TL_RESONATOR` 子系统 + χ（Koch 2007 eq.3.10，`chi_method: perturbative`；
      **`f_bare` 与 `f_loaded` 都输出** —— 裸/dressed 语义陷阱 R5）、`C_j`（**结基对角、求逆之前**，
      spec §4 P0-E 那个标量式是老 LOM 的、对耦合系统错）、新 `dsl/cpw_analytic.py`
      （纯 math，AGM 实现的 K 替 `scipy.special.ellipk`，**含动力学电感**）。
      验收：CPW 对参考**最大偏差 9.2e-16**（<1% ✓）；`C_j=0` 逐位不动 + 与 New LOM 的 node 基
      折入 `==` 逐位；λ/4 系数方向已从源码确认。
      ⚠ **χ 对老 LOM −16.1%，未达 §7 的 <5%** —— 已分解成两个已知定义差（g 定义 −8.50% +
      数值 CPB 谱 −8.33%，乘积 0.8388 ≈ 实测 0.8392；χ 的**公式本身**对参考逐位一致）。
      关掉谱那一半需要 **P1-H**。
- [x] **编排 + sidecar**：`schema.py`/`parsers/simulation.py` 新顶层块 `extract:`/`assemble:`/
      `subsystems:`（**不做** `sweep` —— P2）；`geo_build.py` 块循环 → assemble → circuit_model →
      系统级 `chip.results.yaml`（provenance 带 `assembly` 段：每 cell 的 source/sha256、被消掉的
      节点、审计）；**「拼装后每个保留节点必须被某个 subsystem 认领，否则 raise」**（#20 的静默
      接地守卫放在编排层）。新例子 `examples/dsl/geo/sung_2021_device_blocks.meta.yaml` +
      `examples/dsl/README.md` 的「想在哪切，就在那里分 component」。
- [ ] **M8e — P1-G Purcell `T1` + P1-H 精确 CPB 对角化**（`dsl/cpb_numeric.py`，numpy 可选/lazy）。
      P1-H 是关掉 χ 那 −8.33% 的唯一途径。
- [ ] **M8f — P2-J 参数扫描**（⚠ 必须遵守 G2/G3：扫描声明写在 sidecar 里，每个值物化一份完整
      快照 + 一次独立 build，**不能**用命令行改几何参数）+ **P2-K 网格收敛扫描**（= 缺口 ④/#26；
      sung 的 order 1→2 差 **21%** 说明我们从来不知道离收敛多远，而这直接决定分块误差能不能测
      → 现在性价比最高的一项）。
- [ ] **M8g — §8 legacy 路径退役**（`.metal.yaml` 输入 / `build_design` / `export_ir_to_metal` /
      `gmsh_adapter.build_mesh` slab / `design_dsl.py` 打 UNMAINTAINED 横幅 + 一次性 warning +
      `@pytest.mark.legacy`；`build_ir`/`PrimitiveIR`/`parsers/` 保留为内部库）+ 文档同步。
- [ ] **P2-I `FLUXONIUM` 子系统**（schema 已能容纳：`subsystems[].type`）。

> **明确不做**（spec §6，理由已记）：scqubits / qutip `HilbertSpace` 数值对角化（χ 走解析式，
> 代价是强耦合/近共振精度，results 标 `chi_method: perturbative`）；v1 的 `links:` / `cross` 块
> （跨 cell 连通只靠**共享节点名**）；新的 OCC 布尔切割；块的并行求解（gmsh 进程级全局状态）。
>
> **分块的两条固有代价**（写进 `examples/dsl/README.md`，不是 bug）：① 切割面只能落在 component
> 边界；② 跨块耦合只能靠共享节点名（= 同一导体被两块各画一半），**两块分离导体之间的互电容
> 一定丢**。所以「想保哪两个导体的耦合，就把它们放进同一个块」。
> **R8 成立**：分块总墙钟**没降**（3 块合计 2.19M 未知量 ≈ 整片 order 2 的 2.24M），
> 降的是**单次**求解规模 2.24M → 0.6~1.0M，于是 order 2 才跑得起。

---

## Deferred — out of the current phase (not ruled out)

### M2 — Authoring ergonomics  `[defer]`
- Sidecar schema validation + docs: optional housekeeping; do opportunistically.
- Port-by-group binding: **deferred** (this phase's electrostatic solve uses conductor surfaces, not 1D ports; returns with the driven/eigenmode phase).
- Curved-boundary loader arc fidelity: **subsumed** for now by M5a pre-sampling (rounded corners are emit_geo polygons).
- `qlib.geo` macro expansion: **not needed** for the emit_geo path (it emits flat explicit geometry, not qlib `Call`s).

### M4 — Richer solvers (Eigenmode/Driven, ports, loss)  `[defer]`
Out of this phase — the target now is the electrostatic capacitance matrix. Picks back up in a
later phase if mode frequencies / driven S-params / Q-loss are needed; the name→attr binding is
already solver-agnostic, so it's additive when it returns.

### M5b — Hierarchy / multi-metal / flip-chip  `[defer]`
- Hierarchical GDS cells (child cell per component); flat remains default.
- Multi-metal-layer / flip-chip z-offset support in `populate_tracker_from_geo`.
Single metal layer + dielectric substrate is the scope; defer until a multi-layer design is needed.

---

## Session logs
- [`session/2606072216.md`](session/2606072216.md) — 2026-06-07 · Plan + **M1 complete**: foundation +
  5-agent workflow; mesh-size clamp & JJ-lumped fixes; **236/236 tests pass**; `build_geo` produces
  GDS + mesh + Palace JSON and **Palace `--dry-run` passes** (WSL).
- [`session/2606072302.md`](session/2606072302.md) — 2026-06-07 · Pulled `feat/native-geo-dsl`, carried
  over local WIP fixes: local `_require_gmsh` (qiskit-metal 0.5.1 dropped the export — confirmed
  load-bearing), `parse_number` expression fallback, **port-resolve moved after `fragment`** (both
  pipelines; geo guard dormant til M5), `.gitignore` local gmsh SDK. Notebook discarded (format churn).
  Configured WSL env (conda **`metal-env`**, renamed from `quantum_dsl` to match Windows + spack
  **Palace 0.16**, `PALACE_BIN` persisted) and fixed cross-platform `_to_wsl_path`. ✅ **236 passed**;
  `geo_build --run-palace --dry-run` passes.
- [`session/2606072321.md`](session/2606072321.md) — 2026-06-07 · Converted
  `refer/2511.10479v1.pdf` plus `refer/arXiv-2511.10479v1.tar.gz` into AI-readable reference files:
  source-derived Markdown with TeX math + figure links, plus PDF-layout fallback text/Markdown.
- [`session/2606072351.md`](session/2606072351.md) — 2026-06-07 · **M3 COMPLETE**: results write-back
  (OUTPUT-only `chip.results.yaml`, tier ladder, no new Hamiltonian layer) — dual-matrix parser
  (`terminal-C/Cm.csv`, F→fF) + `terminal_bindings` SSOT + `write_results_sidecar` + `geo_build` wiring.
  Found live-solve blocker (conductor-as-slab) → scoped 3 approaches → implemented **Approach A
  (conductors-as-voids `occ.cut`)** geo-path-only (6 files). Live Palace solve on `two_pads` →
  real C-matrix `[[24.73,-1.98],…]` fF. **251 passed, 1 skipped** (gated live test passes w/ QDSL_RUN_PALACE=1).
- [`session/2606080224.md`](session/2606080224.md) — 2026-06-08 · Read QDA §Cell-library/Cell-characterization;
  10-agent workflow on **where/how to migrate the v3 template cell library into the `.geo` path** →
  **emit_geo bridge** (reuse v3 engine, flat positive-tone `.geo`). **Re-anchored plan.md to the 5
  original (phased) requirements**: M5a (emit_geo, NEXT) → M6 (circuit-model solve) →
  M7 (GDSFactory); **M2 / M4 / M5b deferred — out of this phase, not ruled out**. Locked 3 emit_geo seam decisions
  (#1 chip-wide bbox ground / #2 plain port marker, edge-contract deferred / #3 pre-sample buffers).
- [`session/2606080308.md`](session/2606080308.md) — 2026-06-08 · **M6 COMPLETE** (R1+R3): circuit-model
  solve. 8-agent recon+critique workflow first — physics lens caught a blocker (naive Maxwell-diagonal
  C_Σ double-counts coupling) → adopted **lumped-oscillator inverse-capacitance** method (rigorous,
  reduces to `e²/2C_ii` for one island). NEW pure `circuit_model.py` (no numpy/scqubits) + `circuit_model`
  sidecar block + SI-prefix unit parser + tier-2 `hamiltonian` write-back + `geo_build` wiring. 37 new
  tests (golden values closed-form-verified + gated `Hcpb` cross-check); **288 passed, 1 skipped**, no regressions.
- [`session/2606080338.md`](session/2606080338.md) — 2026-06-08 · **M5a COMPLETE** (R+): emit_geo
  cell-library bridge in a worktree. NEW `dsl/geo_emit.py` (`emit_geo` + `elaborate_cells`, pure-shapely)
  lowers v3 templates → flat positive-tone `.geo`; rounded corners from pre-sampled shapely buffers;
  `cells:` sidecar (geo-optional) + Elaborator; carved metal **ground** (`carve_conductors` extended,
  `gnd_layer{N}_sfs`). Two OCC discoveries (multi-loop Plane-Surface fills holes → `BooleanDifference`;
  carved-ground/substrate z=0 coplanarity destabilises `fragment` → ε z-nudge). 11 new tests incl. golden
  byte-identical parity; worktree **262 passed**.
- [`session/2606080420.md`](session/2606080420.md) — 2026-06-08 · **Integrated M5a + M6 + M7** (phase
  close-out). Waited on the two worktree agents (poll-to-commit; their long think-pauses defeated
  idle-based detection). Merged `5e13311` (M5a) into `6ad6845` (M6) → `f376b0e` (union-resolved
  `schema.py`/`simulation.py`/journaling; `geo_build.py`/`test_geo_pipeline.py` auto-merged) →
  302 passed. Then **M7** NEW `dsl/gds_viz.py` (R5): `preview_gds` matplotlib (verified) + gdsfactory
  (gated) backends, `viz` extra, lazy exports, CLI `--png`. Full suite **314 passed, 3 skipped**.
  PR `feat/native-geo-dsl` → `main`.
- [`session/2606080906.md`](session/2606080906.md) — 2026-06-08 · **Post-PR#14 docs/examples cleanup**
  (on `main`). `examples/dsl/` → geo-only (removed `.note`/`notebooks`/`scripts`/`outputs`/`yaml` +
  `docs/codex_notes/dsl_v3_*`); moved 2 test `.metal.yaml` → `tests/fixtures/`; rewrote `README.md` +
  `examples/dsl/README.md` for the native-geo path; `refer/` untracked + gitignored; removed local
  gmsh SDK; synced stale `AGENTS.md`. v3 engine + 5 legacy test files kept. Re-ran whole pipeline
  (chip_layout + cells_2q + **live two_pads Palace solve** → C-matrix + tier-2 Hamiltonian) and full
  suite **314 passed, 3 skipped**. 3-agent verify workflow caught + fixed 3 stale fixture-header refs.
  **Follow-up:** installed **gdsfactory 9.2.2** (viz extra) — resolved a 2-layer dep conflict
  (`gdsfactory<9.3` to keep `numpy~=1.24`; `pydantic<2.11` for kfactory 1.2.2 import; pyaedt caps
  `<2.12`). gdsfactory R5 bridge now verified (2 gated tests pass; `--png` → `backend=gdsfactory`);
  added cross-platform `requirements.txt` + capped `pyproject` `viz` extra. Suite still 314/3.
- [`session/2606081015.md`](session/2606081015.md) — 2026-06-08 · **汇报材料**（无代码改动）。新增 `docs/report/`：
  `01-工作汇报.md`（覆盖整个 plan.md + 核对过的 `文件:行号` 引用）/ `02-代码实现详解.md`（含预期问答）/
  `03-汇报流程与演示.md`（与 01 逐段对应 + GUI 操作）+ `demo_gui.sh`（WSLg 演示助手）+ `img/` 6 张图。
  9-agent workflow 逐模块走查取证；主控抽查行号全中。重跑验证：全套 **314 passed, 3 skipped**、
  chip_layout/cells_2q 端到端、**live two_pads** C 矩阵 + tier-2 哈密顿量、Gmsh GUI + GDSFactory 窗口（WSLg/xcb）均确认可运行。
- [`session/2606081710.md`](session/2606081710.md) — 2026-06-08 · **xhigh re-review of #14 → fix
  critical, issue the rest** (branch `fix/review-critical-robustness`). 3 surgical correctness fixes
  (carve→raise on split vacuum; scale-relative singular guard; Palace-CSV nan/inf reject), each +
  regression test, all 3 adversarially "sound". Full suite **319 passed, 3 skipped** (was 314/3).
  Deferred findings → **#18** (carved-ground mesh refinement) + **#19** (robustness checklist);
  **#15** singular-guard item resolved. Branch not yet merged.
- [`session/2606081754.md`](session/2606081754.md) — 2026-06-08 · **chip_layout.geo 外观修复**: 焊盘原本
  嵌进 ground (短路 / 在 GDS 里被 union 吞掉) → 加 `GROUND_POCKET` 把每对焊盘挖成真空孤岛; 再加 `COUPLER`
  (neck+paddle, `BooleanUnion` 成单导体) 让下焊盘电容耦合到 bus (非 galvanic, qubit 悬浮)。坑: neck 必须用
  `Rectangle` 而非 CPW `Plane Surface`，否则 union 退化成 fragment。tier-1 验证: GDS 6 多边形 + 6 个独立网格
  导体 + 单一连通真空; geo 套件 **73 passed, 3 skipped**。Palace 按用户要求不跑。剩余物理 → **#20**
  (tier-2 不支持浮动多岛 transmon + 浮动 bus 被错误接地而非 Schur 消元; 外加 meta→tier-2 接线 bug)。
  例改动 (chip_layout.geo + qlib.geo) 未提交。
- [`session/2606272333.md`](session/2606272333.md) — 2026-06-27 · **qm4q repro: 核实 spec + 多真空体 carve 修复**
  (分支 `fix/carve-multi-vacuum`)。核实结论: spec 阻塞点是**内部**的、非外部依赖 (外部依赖全 OK; gmsh 实为
  4.11.1 非 4.15.2; spec 把症状/修复都讲错, 号称的 `_exp_d.geo` 不存在)。建权威参考 env **qmetal-src**
  (quantum-metal 0.7.3 + gmsh 4.15.2, libGLU 坑用 conda libglu 解), metal-env 不动。修 qm4q `.geo` tag 碰撞
  (ground 先建 + 显式高位 tag → 6 导体齐, `37ff0fe`)。实现**多真空体 carve 支持** (`38092df`: carve 不再因
  >1 真空报错, 全部赋 vacuum 材料)。**未完**: two_pads 实解回归 (remap 修复后) 未重验; qm4q v2 仍卡在 gmsh
  mesh.generate "overlapping facets"。下一步建议先做参考侧 Elmer (必产物 + 学 qiskit-metal 怎么干净划网格)。
- [`session/2606300056.md`](session/2606300056.md) — 2026-06-30 · **build 结果归档 + 文件指纹清单**
  (分支 `main`)。`build_geo()` 每次 build 把 `meta.yaml` + `.geo` 复制进 `out_dir`(保留原名),并写
  `chip.manifest.yaml` —— 登记输入副本 + 全部产物(gds/msh/json/results)的 sha256/字节数/修改时间(UTC)。
  新增 `_file_record()` helper(复用 `_sha256_file`)、return dict 加 `"manifest"` 键、CLI 多打印 `Manifest` 行;
  纯附加,未碰 results schema/provenance。+2 测试;`tests/test_geo_pipeline.py` **10 passed, 1 skipped**(was 9/1)。
- [`session/2607021950.md`](session/2607021950.md) — 2026-07-02 · **qm4q 汇报稿 + 静默空网格根因修复**。
  发现当前仓库复现不了 walkthrough:共面 PLC 失败在新 gmsh 构建(4.11.1/4.15.2)不抛异常 → HXT 回退
  永不触发 → 静默写 533B 空网格、Palace abort。修 `generate_mesh`(空 3D 网格也触发回退;回退仍空则
  raise)+2 回归测试(**12 passed, 1 skipped**);实测演示命令须带 `QDSL_MESH_ALGO3D=10`(两 env 均稳)。
  端到端重验:`build/qm4q_demo` 新解 pad_top 103.5 fF,与 6/27 基线 <2%。新文档
  `docs/report/qm4q_talk_script.md`(对着念/操作的分幕汇报稿,含行号指引 + 保底预案)。
- [`session/2607280204.md`](session/2607280204.md) — 2026-07-28 · **review `5737011`
  (sung_2021_device 例子) + 库正确性 + qiskit-metal/Elmer 交叉验算**(无代码改动)。
  例子 **跑不起来**(5 种 Algorithm3D × 3 种 min_size × 2 种 substrate_gap × 7 种几何变体全失败;
  对照 `qm4q` 与 qiskit-metal 自己的 QGmshRenderer 都能出网格 → 是 carve/fragment 的几何相关脆弱性)。
  取证发现 **silent-wrong-result 级库缺陷**: `substrate_gap_um: 0` 下 fragment 静默产出损坏模型
  (衬底体被复制 / 负面积 face / 整张 z=0 界面被 `resolve_conductor_faces` 误标成 `gnd_layer1_sfs`),
  fragment 后无任何拓扑不变量检查; 且 `generate_mesh` 的 `QDSL_MESH_ALGO3D` 分支绕过了空网格守卫。
  **本机从源码装好 ElmerFEM 9.0** (`~/opt/elmer`) 并在 qiskit-metal 0.7.6 里 1:1 重建该器件 →
  Elmer 电容 + LOM 2.0 + Hcpb 实测: E_C 比论文大 4.4–6.7×、无量纲耦合小 20×/~40× → 几何未按论文标定;
  例子的单岛 `circuit_model` 写法在同一张网格上有 1.70× 误差。
  **同 session 内 4-agent 编排修复全部落地** (`8e45507` `d07b087` `ab94a13` `e61f324` `6db8134`):
  fragment 的 dilate 往返被查明是**意外 shape-heal**(非单位换算) → 改 `FRAGMENT_SCALE_LADDER=(1.0,1e2)`;
  fragment 后拓扑不变量 + `resolve_conductor_faces` 收紧; 浮动/差分多岛 transmon(与 LOM 2.0 吻合 <0.1%);
  `ground_faces` 细化 + env-override 空网格守卫。全套 `8 failed/313 passed/2 errors` → **`349 passed,
  3 skipped, 1 deselected, 0 failed`**。例子端到端跑通且按论文标定 (C_Σ 比值 1.03/1.02/1.00,
  q–c 耦合 1.07×; 唯一未达标 C_12 低 ~50×, 已如实写进 header)。
  🔴 遗留: 本机 MPI 挂死 → 全程**无实解覆盖**, 修好后必须补 two_pads / sung 的 Palace 回归。
- [`session/2607290110.md`](session/2607290110.md) — 2026-07-29 · **feature 缺口 ⑦ + ⑤ 落地**
  (2 个并行 subagent, 同一主工作树, 文件域分开): `geo_build --np N`(`run_palace` 一直支持
  `num_procs`, 但 `geo_build` 硬编码不传 → `--run-palace` 永远单 rank; sung 的 order-2 /
  2.24M 未知量单 rank 90 分钟解不完就是这么来的) + **磁通可调非对称 SQUID**
  (`squid: {E_J1, E_J2, flux}`, Koch 2007 的**无奇点**形式 `E_JΣ·sqrt(cos²+d²sin²)` —— 教科书
  写法的 tan 在 Φ=0.5Φ0 发散成 nan; 这是 sung 那次 g 偏高 1.4× 的主因)。
  顺手修两个 subagent 报告的 bug: **`L_J`/`E_J` 放行 nan/inf** → 结果整条 nan 且绕过
  non-transmon 守卫、静默写进 `chip.results.yaml`(`nan <= 0` 为 False; YAML 侧 `1e400H` 溢出同样
  能踩到) ; **live-Palace 的 `skipif` marker 错位**在不需要 Palace 的 manifest 测试上, 而真正的
  活解测试没有 gate —— 这就是「1 skipped + 手工 `--deselect`」那个仪式的来源, 修完不再需要。
  全套 **368 passed, 3 skipped, 0 failed/0 errors/0 deselected**。
  MPI 挂死已在上一 session 查明并修好(hwloc `gl` 插件 TCP 探测 X display → `HWLOC_COMPONENTS=-gl`);
  two_pads 实解回归通过(max |rel dev| 0.202%); **sung 的 Palace vs Elmer 对照已移交他人**。
- [`session/2607290329.md`](session/2607290329.md) — 2026-07-29 · **M8 P0 全部落地**
  (`.claude/lom-parity-spec.md` 的 P0-A…F = M8a–M8d)。**6 个并行 subagent**(同一主工作树、
  文件域互不重叠) + 主控做数据契约 / `geo_build` 编排 / 实解验证。§12 四项待确认由主控裁决
  (不引 scqubits · Schur 用结构判定 · 4.05 矩阵拷入当 fixture · `emit_block_geo` 放 `geo_emit`),
  另修正 spec 三处机制(S2 改 shapely 求交 · S4 零代码 · Schur 在 node 基 → M6 一行不改)。
  抓到并收口一处**跨 agent 冲突**: `C_j` 被 `assemble` 与 `circuit_model` 各实现一遍会**双计**
  → 收到 `circuit_model` 的结基对角、求逆之前(spec §4 P0-E 那个标量式是老 LOM 的、对耦合系统错;
  已在真实耦合矩阵上实证与 New LOM 的 node 基折入 `==` 逐位)。
  新模块 `dsl/assemble.py`(累加 + **Schur 消元**, 对 4.05 的 `C_k` **7.7e-16**) 与
  `dsl/cpw_analytic.py`(对参考 **9.2e-16**); `emit_block_geo` 落盘 `block_*.geo`(G1);
  sidecar 新增 `extract:`/`assemble:`/`subsystems:`; `C_j` / `TL_RESONATOR` + χ / 文件+inline 注入。
  **issue #20 / 缺口 ⑥ 收尾**(硬接地把跨 cell `g` 25.14 MHz **删成 0.00**)。
  实解: `two_pads` 分块对角 **+1.03%/+1.06%**(<2% ✓); `sung` 三块 order 2 对 Elmer
  **−3.2%/−2.9%/−3.2%**(<5% ✓) —— ⚠ 但 order-1 对照显示这是**两个大误差反向抵消**
  (同 order 下分块本身 +12~15%, order 1→2 −21%), sung 上无法干净分离(#22 + 网格未收敛),
  可信数字是 two_pads 的 +1.03%。**R8 成立**: 总墙钟没降(2.19M ≈ 整片 2.24M), 降的是单次规模
  (→ order 2 才跑得起)。χ 对老 LOM **−16.1% 未达 5%**, 已分解成两个已知定义差(公式本身逐位一致)。
  全套 **368 → 619 passed, 3 skipped, 0 failed**(+251 测试)。
  🔴 欠: §7 的 **S2 live Palace 护栏未跑**(需要 pocket 互不相连的设计)。
- [`session/2607292213.md`](session/2607292213.md) — 2026-07-29 · **M8 P0 的 code review +
  `status.md` 压缩**(无代码改动)。全套复跑证实 **619 passed, 3 skipped, 0 failed**(156.78 s);
  P0-A…F 六项确认落地, 4.05 golden 是**参考实现独立生成**的(`expected.yaml` 同时存
  带/不带 `cj_dict` 两组 → `C_j` 两种折入方式的等价性用参考实现自己的两次运行验证)。
  8 条 finding: 🔴 **F1 `from: file` 读 Palace CSV 时终端名自动生成 `t1..tN` → 两个块被
  当成共享节点静默合并**(实测对角 20/30 → 40/60 fF, 零警告); 🟡 F2 块窗口(S3)与 airbox(S4)
  复用同一个 `airbox.side_buffer` 且**叠加** → 调 airbox 会静默改动块的 ground 外延, 且 sung
  的分块 A/B 对照并非「同 airbox」(two_pads 不受影响, +1.03% 仍成立); 🟡 F3 `ground_node`
  拼错是静默 no-op; 🟡 F4 file/inline 块的报错给出错的可寻址终端列表; 🟢 F5–F8
  (块内同名合并少一项 C_ij[当前不可达] / g 用加载 C + 裸 ω 的混搭 / gmsh model 只增不删 /
  `units:` 在 Palace CSV 上被静默忽略)。spec 的 7 条偏离逐条复核**都成立**;
  四条不利结果(sung 误差抵消 · R8 墙钟没降 · χ −16.1% · S2 live 护栏没跑)都主动记录, 无隐瞒。
  `status.md` **254 → 85 行**: 逐 session 叙事删掉(plan.md 已有)、Open 段压成 issue 表
  (#15/#18/#19/#20/#22–#28 只留一行指针)、已了结的坑压成「别重新踩」表、新增「读数前必看」
  数值可信边界表。
