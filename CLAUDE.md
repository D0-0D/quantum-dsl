# CLAUDE.md

Guidance for AI agents working in this repository.

## Project

`quantum_dsl` — a DSL for **superconducting quantum-chip layout** (src-layout package under `src/quantum_dsl/`).
Two geometry front-ends feed a shared physical-group model that forks to multiple backends:

1. **Legacy YAML→shapely path**: a `.metal.yaml` design DSL (`build_ir` / `build_design`) → a
   qiskit-metal `QDesign`, and (via `gmsh_adapter.build_mesh`) → a Gmsh `.msh`.
2. **Native Gmsh `.geo` path (primary, the pivot)**:
   - **Layer 1 — physics metadata**: a standalone `*.meta.yaml` sidecar (materials, `eps_r`, ports,
     solver, GDS layer map) — reuses the `simulation.gmsh` vocabulary + `gds`/`solver` blocks.
   - **Layer 2 — geometry**: a native Gmsh `.geo` (OpenCASCADE kernel), authored in **microns**.
   - Forks to: **gdstk → `chip.gds`** (2D, bypasses the mesh) and **Gmsh → `chip.msh` → Palace**
     (Electrostatic). Entry point: `quantum_dsl.dsl.geo_build` / `build_geo()`.

**The binding key** between geometry, GDS, Palace, and Layer-1 metadata is one structured Gmsh
physical name authored in the `.geo`: `"<role>::<layer>::<component>::<primitive>"`
(roles: `metal`/`ground`/`jj`/`substrate` surfaces, `port`/`symmetry` markers). The loader maps these
to the existing `PHYSICAL_GROUP_NAMING` strings and `assign_physical_groups` re-registers every group
after `fragment`, so output names are byte-identical to the legacy path (Palace stays source-agnostic).

## Commands

Tests are **not** runnable from the default python — use conda **`metal-env`** (has qiskit_metal +
gmsh 4.15.2 + gdstk 0.9.62 + shapely). `quantum_dsl` is not pip-installed, so set `PYTHONPATH`.

```powershell
# Full suite (gmsh/gdstk/Palace verification all run here):
$env:PYTHONPATH = "src"; python -m pytest tests/ -q
# One file:
$env:PYTHONPATH = "src"; python -m pytest tests/test_geo_pipeline.py -q
# End-to-end geo pipeline (GDS + mesh + Palace JSON, optional dry-run):
$env:PYTHONPATH = "src"; python -m quantum_dsl.dsl.geo_build examples/dsl/geo/chip_layout.meta.yaml --out-dir build/geo_demo [--run-palace --dry-run]
```

- `metal-env-old` (Python 3.9) has an OLD qiskit_metal that can't import the gmsh adapter — gmsh/gdstk
  tests are gated with `pytest.importorskip`. Prefer `metal-env`.
- **Palace** is installed in WSL via spack (0.16); `run_palace` falls back to WSL automatically.

## Layout & conventions

- `src/quantum_dsl/dsl/` — core. `schema.py` (keyword/role/enum constants), `ir.py` (dataclasses),
  `builder.py` (`build_ir`/`build_design`), `parsers/`, `_units.py` (internal unit = **µm**,
  `SI_PER_INTERNAL = 1e-6`). Gmsh pipeline: `gmsh_adapter.py` + `_gmsh_geometry/_gmsh_layers/`
  `_gmsh_mesh/_gmsh_physical.py`. Native-geo path: `_gmsh_geo_source.py`, `gds_adapter.py` (+`_gds_layers.py`),
  `palace_adapter.py`, `geo_build.py`.
- `src/quantum_dsl/dsl_templates/` MUST stay a sibling of `dsl/` (template registry locates it via
  `Path(__file__).parent.parent / "dsl_templates"`).
- Internal lengths are **µm**; the mesh branch dilates µm→m at the OCC boundary (Palace `L0=1.0`); the
  GDS branch keeps µm verbatim (`gdstk.Library(unit=1e-6)`). Never double-scale.
- Style: `from __future__ import annotations`, frozen dataclasses for results, raise `DesignDslError`,
  optional deps (`gmsh`/`gdstk`) imported lazily — `import quantum_dsl` must not pull them in.
- The JJ is a **lumped element**: emitted to GDS (layer 20) but NOT meshed as a conductor in the
  electrostatic path (`populate_tracker_from_geo` removes it).

## Project journaling — KEEP THESE UP TO DATE

This repo tracks progress in `.claude/`. As an agent working here you MUST maintain them:

1. **`.claude/plan.md`** — the milestone progress tracker (checklist **M1–M5**, legend
   `[x]` done / `[~]` in progress / `[ ]` not started).
   - At the **start** of a session, read it to see current state.
   - As work lands, update the relevant checklist items (flip `[ ]`→`[~]`→`[x]`, edit the bullet text
     to reflect what was actually built/verified).
   - The **bottom** of `plan.md` has a **`## Session logs`** index — add one line per session log.
2. **`.claude/session/<yyMMddhhmm>.md`** — a per-session log (timestamp via
   `Get-Date -Format 'yyMMddHHmm'`). Record: goal, locked decisions, work done, verification results
   (commands + pass/fail), and any open issues / next steps. Append a "Resolution" section when an
   open issue is closed.
   - Create a **new** session-log file for a new working session; **append** within the same session.
   - After creating/updating a session log, add/refresh its line in the `plan.md` Session-logs index.

Keep both concise and factual. The full design reference for the geometry pivot lives at
`C:\Users\Administrator\.claude\plans\gmsh-dsl-expressive-perlis.md`.
