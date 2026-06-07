# Quantum-DSL — Current Status

**This is an active, in-progress project.** Read this file *and* `plan.md` at the start of
every session before touching code. This file is the quick "where are we right now" snapshot;
`plan.md` is the full milestone checklist + the original-requirements map.

_Update this file whenever the headline state changes (milestone flips, branch merges, notable
commits, test-count changes)._

---

## At a glance
- **Active branch**: `feat/native-geo-dsl` (the native Gmsh `.geo` pivot — the primary path).
- **Current-phase scope** (2026-06-08, phased — not a final ceiling): rounded-corner polygon cells
  + an **electrostatic capacitance matrix**. Eigenmode/driven, lumped ports, and loss are out of
  *this* phase — staged for later, not ruled out.
- **Done**: **M1 `[x]`** (both branches end-to-end) and **M3 `[x]`** (live Palace C-matrix +
  `chip.results.yaml` write-back; conductors-as-voids `carve_conductors`).
- **Current milestone**: **M5a — emit_geo cell library** (lower v3 `transmon_pocket` etc. → flat
  positive-tone `.geo`; rounded corners via pre-sampled shapely buffers). It is the **next** task.
  M6 (circuit-model solve from the C-matrix) can run in parallel since a C-matrix already exists.
- **Tests**: full suite **251 passed, 1 skipped** in conda `metal-env` (the skip = gated live
  Palace test; run with `QDSL_RUN_PALACE=1`). See `CLAUDE.md` for how to run.
- **End-to-end**: `build_geo(two_pads.meta.yaml --run-palace)` → real C-matrix
  `[[24.73,-1.98],[-1.98,24.72]]` fF; `chip_layout` still needs disjoint authoring for a full-chip
  live solve (→ M5a).

## Plan re-org (2026-06-08)
Re-anchored `plan.md` to the **5 original requirements** (R1 group→circuit, R2 Palace→C-matrix ✅,
R3 circuit solve, R4 read QDA ✅, R5 GDSFactory) + verbal "电容矩阵就够":
- **Active path**: M5a (emit_geo, NEXT) → **M6** circuit-model solve (R1+R3) → **M7** GDSFactory (R5).
- **M2 / M4 / M5b deferred** — out of this phase, not ruled out (M2 ports/arc/qlib unneeded now;
  M4 eigenmode/driven later; M5b hierarchy/multi-layer/flip-chip later).
- emit_geo design + the 3 locked seam decisions: see `session/2606080224.md`.

## Recent notable commits
- `4b68c38` Merge PR #13 — native-geo-del-win.
- `1e91315` **M3**: live Palace capacitance write-back + conductors-as-voids mesh.
- `bfb2628` docs: add QDA reference materials (`refer/2511.10479v1*`).

## Open / next steps
- **M5a (NEXT)**: build `dsl/geo_emit.py` `emit_geo(design_ir)` + `cells:` sidecar block + Elaborator;
  synthesize one chip-wide ground (decision #1); pins → plain `port::` marker (decision #2);
  pre-sample buffers → polygons (decision #3); extend `carve_conductors` to carve the ground;
  golden byte-identical-names parity test.
- **M6 (parallel-eligible)**: C-matrix → LOM/circuit quantization → qubit params → results tier T2.
- `CLAUDE.md` no longer pins "M1–M5" — milestones are re-scoped per phase (see `plan.md`).
