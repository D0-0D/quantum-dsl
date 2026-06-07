# Quantum-DSL — Native Gmsh `.geo` Geometry DSL + GDSII + Palace

Progress tracker for the geometry-layer pivot:
**Layer-1 physics metadata (`*.meta.yaml`)** → **Layer-2 native Gmsh `.geo`** →
{ Gmsh mesh → **Palace** (Electrostatic), gdstk → **GDSII** }.

Full design + binding contract: `C:\Users\Administrator\.claude\plans\gmsh-dsl-expressive-perlis.md`.
Status legend: `[x]` done · `[~]` in progress · `[ ]` not started.

---

## M1 — Both branches end-to-end on a tiny example  `[x]`
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

## M2 — Authoring ergonomics + metadata schema hardening  `[ ]`
- [ ] Finalize sidecar schema (gds map + solver block) validation & docs.
- [ ] Geo-mode port-by-group binding (`port::layer::comp::pin` → physical-group name).
- [ ] Curved-boundary GDS fidelity (arc/fillet sampling at `arc_tol_um`, sagitta-based segment count).
- [ ] Expand `qlib.geo` macros (fillets, multi-loop ground cutouts) + parametric `For`-loop chain example.

## M3 — Capacitance results + verification loop  `[ ]`
- [ ] `parse_capacitance_matrix()` reading `terminal-Cm.csv` / `terminal-C.csv` / `domain-E.csv`.
- [ ] Two-conductor reference design with known-sign C-matrix assertions (symmetric, +diag, −offdiag).
- [ ] End-to-end harness: `.geo` → mesh → JSON → Palace → C-matrix (gated on Palace availability).

## M4 — Richer solvers + metadata  `[ ]`
- [ ] `SOLVER_TYPES` += `Eigenmode`, `Driven`; per-type `build_*_config` reusing the name→attr binding.
- [ ] Consume port impedance/value (lumped ports) and dielectric `tan_delta` loss.
- [ ] Re-verify msh format/attribute compatibility per solver via `--dry-run`.

## M5 — Hierarchy, standard-cell library, legacy bridge  `[ ]`
- [ ] Reusable macro / standard-cell library (transmon pocket, resonators, couplers).
- [ ] Optional hierarchical GDS cells (child cell per component); flat remains default.
- [ ] Multi-metal-layer / flip-chip z-offset support in `populate_tracker_from_geo`.
- [ ] `emit_geo(ir)`: lower a legacy `DesignIR` to a `.geo` (migration on-ramp).

---

## Session logs
- [`session/2606072216.md`](session/2606072216.md) — 2026-06-07 · Plan + **M1 complete**: foundation +
  5-agent workflow; mesh-size clamp & JJ-lumped fixes; **236/236 tests pass**; `build_geo` produces
  GDS + mesh + Palace JSON and **Palace `--dry-run` passes** (WSL).
- [`session/2606072302.md`](session/2606072302.md) — 2026-06-07 · Pulled `feat/native-geo-dsl`, carried
  over local WIP fixes: local `_require_gmsh` (qiskit-metal 0.5.1 dropped the export — confirmed
  load-bearing), `parse_number` expression fallback, **port-resolve moved after `fragment`** (both
  pipelines; geo guard dormant til M5), `.gitignore` local gmsh SDK. Notebook discarded (format churn).
  Configured WSL env (conda **`quantum_dsl`** + spack **Palace 0.16**, `PALACE_BIN` persisted) and fixed
  cross-platform `_to_wsl_path`. ✅ **236 passed**; `geo_build --run-palace --dry-run` passes.
