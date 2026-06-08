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
- **Tests**: full suite **314 passed, 3 skipped** in conda `metal-env`. `gdsfactory` 9.2.2 now
  installed → the 2 gdsfactory-backend tests PASS; the 3 skips are now 1 gated live Palace test
  (passes with `QDSL_RUN_PALACE=1`) + 2 "gdsfactory-absent fallback" tests (mutually-exclusive,
  skip because gdsfactory is present). See `CLAUDE.md` for how to run.
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
