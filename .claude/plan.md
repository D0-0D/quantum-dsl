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
| R5 | Add GDSFactory for visualization | `[ ]` | **M7** |
| R+ | Cells = polygons **with rounded corners** | `[ ]` | **M5a** (emit_geo, pre-sampled shapely buffers) |

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

### M5a — emit_geo cell library (rounded-corner cells)  `[ ]`  ← NEXT
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

- [ ] `dsl/geo_emit.py` `emit_geo(design_ir, out_path, *, arc_tol_um)` → `.geo` text (imports **no** gmsh/gdstk).
- [ ] Positive primitives → OCC `Plane Surface` + call-site `Physical Surface("role::layer::comp::prim")`
      (`junction.*`→`jj`, else `metal`); paths/junctions buffered to closed polygons at `width/2`.
- [ ] Synthesized chip-ground + aggregated subtract-as-holes (decision #1).
- [ ] Pins → plain `port::` dim-1 marker (decision #2).
- [ ] `cells:` sidecar block (cell_type + globally-unique component + x/y/rot/layer + params) + an
      **Elaborator** (`build_ir` per instance → `emit_geo` → concat one `<stem>.elaborated.geo`;
      assert unique `<component>` so `load_geo`'s duplicate-name guard never trips); substitute the
      elaborated path at `geo_build.py:72` so BOTH forks consume it.
- [ ] Extend `carve_conductors` to also carve the synthesized **ground** sheet (M3 scope note → full-chip live solve).
- [ ] **Golden parity test**: elaborated `.geo` physical names + final `assign_physical_groups` names
      byte-identical to a hand-authored equivalent; GDS layers match; full suite stays green (≥251).

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

### M7 — GDSFactory visualization (R5)  `[ ]`
- [ ] Optional lazy `gdsfactory` dep; read `chip.gds` → preview/plot (matplotlib / KLayout).
- [ ] Keep **gdstk** as the emitter; gdsfactory is **visualization-only**, additive, optional
      (`import quantum_dsl` must not pull it in).

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
