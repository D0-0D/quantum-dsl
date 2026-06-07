# Quantum-DSL — Current Status

**This is an active, in-progress project.** Read this file *and* `plan.md` at the start of
every session before touching code. This file is the quick "where are we right now" snapshot;
`plan.md` is the full milestone checklist + the original-requirements map.

_Update this file whenever the headline state changes (milestone flips, branch merges, notable
commits, test-count changes)._

---

## At a glance
- **Active branch**: `feat/native-geo-dsl`. **M5a is being landed on worktree branch
  `feat/m5a-emit-geo`** (branched from HEAD; merge back when ready).
- **Current-phase scope** (2026-06-08, phased — not a final ceiling): rounded-corner polygon cells
  + an **electrostatic capacitance matrix**. Eigenmode/driven, lumped ports, and loss are out of
  *this* phase — staged for later, not ruled out.
- **Done**: **M1 `[x]`** (both branches end-to-end), **M3 `[x]`** (live Palace C-matrix +
  `chip.results.yaml`; conductors-as-voids), and **M5a `[x]`** (emit_geo cell-library bridge —
  delivers R+ rounded-corner cells).
- **M5a (DONE)**: `dsl/geo_emit.py` `emit_geo` (shapely-only) lowers a resolved v3 `DesignIR` → flat
  positive-tone `.geo` (poly + buffered rounded paths + OCC-`BooleanDifference` chip-wide ground);
  `elaborate_cells` Elaborator + `cells:` sidecar (`geo` now optional) wired into `geo_build`; metal
  ground now **carved** (`gnd_layer{N}_sfs`, geo-path-only/additive) so full-chip ground designs mesh.
  See `session/2606080338.md`.
- **Current milestone**: **M6 — circuit-model solve (R1+R3)** is next (C-matrix already exists).
- **Tests**: full suite **263 passed, 1 skipped** in conda `metal-env` (251 → 263: +12 in new
  `test_geo_emit.py` incl. golden parity; 2 tiny_chip geo-path assertions updated for the carved ground).
- **End-to-end**: `build_geo(two_pads --run-palace)` → real C-matrix `[[24.73,-1.98],[-1.98,24.72]]`
  fF (unchanged); `build_geo(cells_2q.meta.yaml)` → GDS + msh + Palace config with 4 carved qubit-pad
  terminals + carved chip ground (full-chip **live** solve not yet run, gated `QDSL_RUN_PALACE`).

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
- **Merge** worktree `feat/m5a-emit-geo` → `feat/native-geo-dsl` once reviewed.
- **M6 (NEXT)**: read `chip.results.yaml` maxwell C-matrix → LOM/circuit quantization → qubit params
  (E_C/f01/α/couplings) → results tier T2. A C-matrix already exists (M3), so M6 is unblocked.
- **M5a follow-ups** (non-blocking): run a full-chip **live** Palace solve on an emit_geo ground
  design (gated `QDSL_RUN_PALACE`); connection-pad transmon cells (non-empty `connection_pads`) emit
  fine but may need a connector-pad subtract gap for a clean disjoint live solve; the carved-ground
  substrate z-nudge leaves a small ε-vacuum-gap (capacitance artifact) — refine if precision matters.
- `CLAUDE.md` no longer pins "M1–M5" — milestones are re-scoped per phase (see `plan.md`).
