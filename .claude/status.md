# Quantum-DSL — Current Status

**This is an active, in-progress project.** Read this file *and* `plan.md` at the start of
every session before touching code. This file is the quick "where are we right now" snapshot;
`plan.md` is the full milestone checklist (M1–M5).

_Update this file whenever the headline state changes (milestone flips, branch merges, notable
commits, test-count changes)._

---

## At a glance
- **Active branch**: `feat/native-geo-dsl` (the native Gmsh `.geo` pivot — the primary path).
- **Current milestone**: **M1 complete `[x]`** → next up **M2** (authoring ergonomics +
  metadata-schema hardening). See `plan.md` for the M2–M5 breakdown.
- **Tests**: full suite **236 passed, 0 failed** in conda `metal-env` (see `CLAUDE.md` for how to run).
- **End-to-end**: `build_geo(chip_layout.meta.yaml)` produces `chip.gds` + `chip.msh` + Palace
  `chip.json`, and Palace `--dry-run` passes under WSL (spack Palace 0.16).

## Recent notable commits
- **`bfb2628` docs: add QDA reference materials** — added the QDA paper reference set under
  `refer/` (arXiv `2511.10479v1`): AI-readable Markdown derived from both the PDF text layer
  (`refer/2511.10479v1.md`) and the LaTeX source bundle (`refer/2511.10479v1.source.md`, TeX math +
  figure links preserved), plus `refer/2511.10479v1.index.md` as the lookup index. Use these as
  background/domain reference; they are docs only and don't affect the build or tests.
- `aac7e4c` docs(session): WSL env renamed `quantum_dsl` → `metal-env` (matches Windows + CLAUDE.md).
- `ba8165f` docs(session): record WSL env setup + 236-pass verification.

## Open / next steps
- M2 work has not started. First items: finalize the `*.meta.yaml` sidecar schema validation +
  docs, geo-mode port-by-group binding, curved-boundary GDS fidelity. (Full list in `plan.md` → M2.)
