# DSL v3 Deferred Bugs Agent B Fix Report

Date: 2026-05-11

Agent: Agent B

Worktree:

`D:\BaiduSyncdisk\vsCOde\circuit\qiskit\qiskit-metal-worktrees\dyk07-main`

## Initial State

- Ran `git status --short` before editing.
- Initial worktree status was clean.
- Read required inputs:
  - `.codex\dsl_v3_deferred_bugs_inventory.md`
  - `.codex\dsl_v3_transmon_template_progress.md`

## Fixed

### 1. Expression arithmetic runtime failures now keep the DSL error contract

Files:

- `src/qiskit_metal/toolbox_metal/dsl/expression.py`
- `tests/test_design_dsl_templates.py`

Changes:

- Wrapped unary and binary operator application in `_eval_ast()` with
  `DesignDslError`.
- Added operator and expression context to runtime arithmetic error messages.
- Wrapped numeric coercion parse failures from `parse_value()` in
  `DesignDslError`.
- Added regression coverage for `${1 / 0}` asserting a `DesignDslError` with
  expression context.

### 2. Invalid numeric fields now reject booleans and wrap conversion failures

Files:

- `src/qiskit_metal/toolbox_metal/dsl/builder.py`
- `tests/test_design_dsl.py`
- `tests/test_design_dsl_templates.py`

Changes:

- `_parse_number()` now explicitly rejects booleans and wraps parser failures in
  `DesignDslError`.
- `_parse_angle()` now rejects booleans and wraps invalid strings such as
  `nope` in `DesignDslError`.
- `_layer()` now rejects booleans and wraps invalid layer conversion failures in
  `DesignDslError`.
- Numeric helper call sites now pass owner/context strings for clearer
  diagnostics, including primitive width/layer, pin width/gap, transform rotate,
  and point coordinates.
- Added regression coverage for invalid primitive numeric fields:
  - `width: true`
  - `layer: nope`
  - `layer: true`
- Added regression coverage for typed template options reaching numeric paths:
  - `orientation: nope`
  - `orientation: true`
  - `layer: true`

### 3. File-based component-template lookup now has focused regression coverage

Files:

- `tests/test_design_dsl_templates.py`

Changes:

- Added `tmp_path`-based test for successful local component template file
  lookup through the design file directory.
- Added test for file template `id` mismatch diagnostics.
- Added test for duplicate YAML keys in a template file.

### 4. `build_ir()` design instantiation behavior is now documented by a test

Files:

- `tests/test_design_dsl.py`

Changes:

- Added `CountingDesign` test double.
- Added regression/documentation test confirming current constructor side
  effects:
  - `build_ir()` constructs the selected design class once.
  - `build_design()` constructs it twice more: once through `build_ir()` and
    once during export.

## Not Changed

- Did not modify qlibrary Python components.
- Did not reintroduce Python `TransmonPocket` as a DSL construction target.
- Did not change the broader Hamiltonian/Circuit semantics, renderer strategy,
  template package/versioning, or `builder.py` architecture beyond small
  numeric error-contract plumbing.
- Did not modify `.codex/` tracking rules. This report is for local coordination
  only and should remain untracked.

## Verification

Commands run:

- `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q`
  - Result: `116 passed, 5 warnings`
- `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py tests/test_design_dsl_transmon_pocket.py -q`
  - Result: `121 passed, 8 warnings`
- `C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py`
  - Result: `PASS: native DSL chain exported to Metal`
- `C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_transmon_pocket_demo.py`
  - Result: `PASS: YAML-native TransmonPocket template exported to Metal`
- `git diff --check`
  - Result: exit code 0; only Git CRLF normalization warnings for touched files.

## Current Worktree Notes

Modified tracked files:

- `src/qiskit_metal/toolbox_metal/dsl/builder.py`
- `src/qiskit_metal/toolbox_metal/dsl/expression.py`
- `tests/test_design_dsl.py`
- `tests/test_design_dsl_templates.py`

Untracked/ignored coordination report:

- `.codex\dsl_v3_deferred_bugs_agent_b_fix_report.md`

