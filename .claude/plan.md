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
