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
- **Done**: **M1 `[x]`** (both branches end-to-end), **M3 `[x]`** (live Palace C-matrix +
  `chip.results.yaml` write-back; conductors-as-voids `carve_conductors`), **M5a `[x]`** (emit_geo
  cell-library bridge: v3 templates → flat positive-tone `.geo`, rounded corners via pre-sampled
  shapely buffers, carved metal ground), and **M6 `[x]`** (circuit-model solve: C-matrix → transmon
  Hamiltonian via lumped-oscillator inverse-cap method; tier-2 `hamiltonian` write-back).
- **Current milestone**: **M7 — GDSFactory visualization** (R5). It is the **next** task.
- **Tests**: full suite **302 passed, 1 skipped** in conda `metal-env` (the skip = gated live
  Palace test; verified separately with `QDSL_RUN_PALACE=1` → passes). See `CLAUDE.md` for how to run.
- **End-to-end**: `build_geo(two_pads.meta.yaml --run-palace)` → real C-matrix
  `[[24.73,-1.98],[-1.98,24.72]]` fF → (M6) tier-2 `hamiltonian` (2 grounded transmons, L_J=10nH:
  E_C≈0.788 GHz, f01≈9.36 GHz, g≈375 MHz). (M5a) a `cells:` sidecar elaborates v3 template
  instances → `<stem>.elaborated.geo` → GDS + mesh + carved-ground Palace config.

## Plan re-org (2026-06-08)
Re-anchored `plan.md` to the **5 original requirements** (R1 group→circuit ✅, R2 Palace→C-matrix ✅,
R3 circuit solve ✅, R4 read QDA ✅, R5 GDSFactory) + verbal "电容矩阵就够":
- **Active path**: ~~M5a (emit_geo)~~ ✅ **DONE** → ~~M6 circuit-model solve (R1+R3)~~ ✅ **DONE** →
  **M7** GDSFactory (R5) ← NEXT.
- **M2 / M4 / M5b deferred** — out of this phase, not ruled out (M2 ports/arc/qlib unneeded now;
  M4 eigenmode/driven later; M5b hierarchy/multi-layer/flip-chip later).
- emit_geo design + the 3 locked seam decisions: see `session/2606080224.md`.
- M6 design (inverse-cap LOM, `circuit_model` sidecar block, tier-2): see `session/2606080308.md`.
- M5a impl (emit_geo bridge, carved ground): see `session/2606080338.md`.

## Recent notable commits
- _(merge)_ **M5a + M6 integrated** into `feat/native-geo-dsl` — full suite 302 passed, 1 skipped.
- `5e13311` **M5a**: emit_geo cell-library bridge + carved metal ground.
- `6ad6845` **M6**: circuit-model solve — Palace C-matrix → transmon Hamiltonian (R1+R3).
- `1e91315` **M3**: live Palace capacitance write-back + conductors-as-voids mesh.

## Open / next steps
- **M7 (NEXT)**: optional lazy `gdsfactory` dep; read `chip.gds` → preview/plot (matplotlib /
  KLayout); keep **gdstk** as the emitter; `import quantum_dsl` must not pull it in.
- **M5a follow-ups**: full-chip live Palace solve on an emit_geo ground design (gated); connection-pad
  transmons may overlap the ground (clean-disjoint cells are the tested path); ε-vacuum-gap artifact
  under carved metal.
- **M6 follow-ups**: multi-island (floating/differential) qubits (schema accepts, solver defers);
  run on an emit_geo transmon now that M5a has landed.
- `CLAUDE.md` no longer pins "M1–M5" — milestones are re-scoped per phase (see `plan.md`).
