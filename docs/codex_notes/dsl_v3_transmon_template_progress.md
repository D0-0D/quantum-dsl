# DSL v3 Transmon Template Implementation Progress

Plan:

`D:\BaiduSyncdisk\vsCOde\circuit\qiskit\qiskit-metal-worktrees\dyk07-main\.codex\dsl_v3_transmon_template_final_implementation_plan.md`

Worktree:

`D:\BaiduSyncdisk\vsCOde\circuit\qiskit\qiskit-metal-worktrees\dyk07-main`

Python:

`C:\ProgramData\anaconda3\envs\metal-env\python.exe`

## Loop State

- Status: completed
- Current round: 10
- Completion: 100%
- Last updated by: round-10
- Last updated at: 2026-05-11

## Stop Rules

The main agent should keep launching one worker subagent per round until one of these is true:

- Completion reaches 100%.
- Round count exceeds 16.
- Round count exceeds 10 and completion is still below 50%.

## Worker Protocol

Each worker must:

- Read this progress file first.
- Read the final implementation plan.
- Inspect local git status before editing.
- Choose a coherent slice that can be completed in this round.
- Preserve unrelated user or agent changes.
- Update this progress file before finishing.
- Write a detailed round report to `.codex/dsl_v3_transmon_template_round_XX.md`.
- Return to the main agent only the final completion percentage for the overall task.

Workers are not alone in the codebase. Do not revert edits made by users or other agents; adapt to the current worktree state.

## Recommended Round Slices

- Round 1: establish baseline status, split `design_dsl.py` into a package facade without behavior change, preserve tests.
- Round 2: add template model and registry, without TransmonPocket-specific Python behavior.
- Round 3: add safe expression/local context support needed by templates.
- Round 4: add generic geometry operation registry.
- Round 5: add pin modes needed for TransmonPocket, especially normal-segment pins.
- Round 6: add `qcomponent.yaml` and template inheritance foundation.
- Round 7: add `base_qubit.yaml` and map-entry inheritance for `connection_pads`.
- Round 8: add static `transmon_pocket.yaml` pocket geometry.
- Round 9: add YAML generator support for `connection_pads`.
- Round 10: add two-transmon example and README updates.
- Round 11: add parity/no-qlibrary-construction tests.
- Rounds 12-16: integration cleanup, bug fixes, parity gaps, documentation polish.

Workers may choose a different slice if the current repository state makes another slice more appropriate.

## Checklist

- [x] Baseline test command confirmed.
- [x] `design_dsl.py` is a facade only.
- [x] New `qiskit_metal.toolbox_metal.dsl` package exists.
- [x] Existing primitive-only v3 behavior still passes.
- [x] Template dataclasses/model added.
- [x] Built-in/file template registry added.
- [x] Template inheritance and option merge implemented.
- [x] Unknown template types/options are rejected.
- [x] Safe expression/local context support added.
- [x] Generic geometry operation registry added.
- [x] Primitive exporter remains primitive-only.
- [x] Pin parser supports tangent-point pins.
- [x] Pin parser supports normal-segment pins.
- [x] `qcomponent.yaml` added.
- [x] `base_qubit.yaml` added.
- [x] `transmon_pocket.yaml` added.
- [x] `connection_pads` map-entry inheritance implemented.
- [x] `connection_pads` generator implemented.
- [x] Two-transmon template example added.
- [x] README documents YAML-native templates.
- [x] Tests cover template expansion.
- [x] Tests cover no qlibrary `TransmonPocket` instantiation.
- [x] Tests cover generated pins and netlist connection.
- [x] Tests cover TransmonPocket geometry row names.
- [x] Tests cover circuit/hamiltonian/netlist interpolation through templates.
- [x] `python -m pytest tests/test_design_dsl.py -q` passes with the conda Python.
- [x] `python examples/dsl/run_chain_demo.py` passes with the conda Python.
- [x] `python -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py tests/test_design_dsl_transmon_pocket.py -q` passes with the conda Python.
- [x] `python examples/dsl/run_transmon_pocket_demo.py` passes with the conda Python.

## Independent Direction Check After Round 07

Document:

`.codex/dsl_v3_transmon_template_direction_check_after_round_07.md`

Conclusion:

- Direction is correct.
- The work is still replacing qlibrary components as the DSL authoring/build target.
- Metal core remains correctly preserved through `NativeComponent/QComponent`, qgeometry, pins, and net_info.
- Python `TransmonPocket` is not reintroduced as a construction target.

Before the round-07 checkpoint is treated as TransmonPocket-parity complete, fix these P1 parity gaps:

- [x] Generated TransmonPocket connection-pad pin `gap` now matches original qlibrary behavior by omitting explicit YAML `gap` and letting the generic pin path use the `QComponent.add_pin()` default of `0.6 * cpw_width`.
- [x] Built-in `transmon_pocket` connection pads now resolve symbolic `cpw_width` and `cpw_gap` through the selected Metal design variables, so `connection_pads: {readout: {}}` builds without explicit root vars.

Parity fix report:

`.codex/dsl_v3_transmon_template_round_07_parity_fix.md`

## Round Log

- Round 01: Established the conda Python baseline, moved the existing native DSL implementation into `src/qiskit_metal/toolbox_metal/dsl/builder.py`, added `dsl/__init__.py`, and reduced `design_dsl.py` to a backward-compatible public facade. Preserved the pre-existing Chinese study comments by carrying them into `builder.py`. Verified with `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py -q` (`69 passed, 4 warnings`) and `C:\ProgramData\anaconda3\envs\metal-env\python.exe examples/dsl/run_chain_demo.py` (`PASS: native DSL chain exported to Metal`). Detailed report: `.codex/dsl_v3_transmon_template_round_01.md`.
- Round 02: Added shared DSL errors, component template dataclass/schema validation, a template registry with inline/file/built-in lookup scaffolding, and generic `type` + `options` expansion into the existing primitive-only IR path. Added `ComponentIR` template fields and local `component`/`options` interpolation roots. Added template tests for expansion, overrides, inheritance, unknown types/options, metadata, and NativeComponent export. Verified with `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q` (`74 passed, 4 warnings`) and `C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py` (`PASS: native DSL chain exported to Metal`). Detailed report: `.codex/dsl_v3_transmon_template_round_02.md`.
- Round 03: Added shared safe expression/interpolation helpers in `dsl/expression.py`, replacing the old dotted-path-only substitution path while preserving primitive-only behavior. Expressions now support local roots (`vars`, `circuit`, `hamiltonian`, `netlist`, `component`, `options`), numeric/unit arithmetic, unary operators, parentheses, typed full-string interpolation, and clear rejection of unknown names or unsupported syntax. Added template tests covering arithmetic and circuit/hamiltonian/netlist interpolation through templates. Verified with `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q` (`77 passed, 4 warnings`) and `C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py` (`PASS: native DSL chain exported to Metal`). Detailed report: `.codex/dsl_v3_transmon_template_round_03.md`.
- Round 04: Added generic `dsl/geometry_ops.py` with a reusable operation registry and component-local operation evaluation for rectangle, polyline, line, polygon, buffer, scale, translate, rotate, rotate_position, and last_segment. Wired template/component `operations` into primitive parsing through `poly.from_operation`, `path.from_operation`, and `junction.from_operation`, with strict errors for unknown operations/references and shapely type mismatches. Added tests for template operations, component-level operations, and operation error reporting. Verified with `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q` (`81 passed, 5 warnings`) and `C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py` (`PASS: native DSL chain exported to Metal`). Detailed report: `.codex/dsl_v3_transmon_template_round_04.md`.
- Round 05: Added explicit pin modes while preserving existing tangent-point behavior, including `normal_segment` pins sourced from component-local operation geometry and exported through `NativeComponent.add_pin(..., input_as_norm=True)`. Implemented generic template `merge_rules.connection_pads.each_entry_extends` with strict per-entry validation and resolved-option removal support, so future `base_qubit.yaml` can accept arbitrary pad names such as `readout`. Addressed the high review gap where accepted template `geometry.generators` were silently ignored by making them fail loudly until generator support lands. With user confirmation, also kept the small typed-component falsey metadata validation fix from the review P2 list. Verified with `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q` (`92 passed, 5 warnings`) and `C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py` (`PASS: native DSL chain exported to Metal`). Detailed report: `.codex/dsl_v3_transmon_template_round_05.md`.
- Round 06: Added built-in YAML templates for `qcomponent`, `base_qubit`, and the static pocket geometry of `transmon_pocket`. The new `qcomponent.yaml` supplies YAML-owned `pos_x`, `pos_y`, `orientation`, `chip`, `layer`, and inherited transform behavior. The new `base_qubit.yaml` extends it with `connection_pads` and generic map-entry inheritance. The new `transmon_pocket.yaml` extends `base_qubit` and generates `pad_top`, `pad_bot`, `rect_pk`, and `rect_jj` from YAML formulas, with `rect_pk` subtraction and junction width preserved. Added tests for built-in inheritance, static transmon row names, Metal export, and no qlibrary `TransmonPocket` construction. Connection-pad generator support remains future work. Verified with `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q` (`96 passed, 5 warnings`) and `C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py` (`PASS: native DSL chain exported to Metal`). Detailed report: `.codex/dsl_v3_transmon_template_round_06.md`.
- Round 07: Fixed the remaining high-priority review gaps from rounds 01-05 by making `normal_segment` IR/derived pin points match exported Metal pins after non-right-angle transforms, and by strictly validating malformed template `geometry.operations`, `geometry.transform`, and typed-component instance `operations`. Added generic YAML `generators` support with per-entry local context, operation namespacing, generated primitives/pins, and a reusable `transform_group` operation. Extended `transmon_pocket.yaml` so `options.connection_pads` generates connector pad/path/subtract rows and normal-segment pins entirely from YAML, with per-pad overrides and netlist connection coverage. Verified with `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl_templates.py -q` (`36 passed, 5 warnings`), `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q` (`105 passed, 5 warnings`), and `C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py` (`PASS: native DSL chain exported to Metal`). Detailed report: `.codex/dsl_v3_transmon_template_round_07.md`.
- Round 07 parity fix: Resolved the two P1 qlibrary parity gaps identified by the independent direction check before the round-07 checkpoint. Generated TransmonPocket connection-pad pins no longer set `gap` from `cpw_gap`; they use the qlibrary-equivalent `0.6 * cpw_width` default. Template numeric parsing now includes selected Metal design variables before `geometry.design.variables` and root `vars`, allowing `connection_pads: {readout: {}}` to build with default `DesignPlanar` `cpw_width`/`cpw_gap` and no root vars. Verified with `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl_templates.py -q` (`37 passed, 5 warnings`) and `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q` (`106 passed, 5 warnings`). Detailed report: `.codex/dsl_v3_transmon_template_round_07_parity_fix.md`.
- Round 08: Added the user-facing YAML-native TransmonPocket example and documentation slice. New `examples/dsl/transmon_pocket_2q.metal.yaml` builds two `type: transmon_pocket` components with generated `readout` pads and a netlist connection. New `examples/dsl/run_transmon_pocket_demo.py` prints qgeometry row counts/names, generated pins, net info, and template inheritance metadata, while asserting both components are exported as `NativeComponent` and connected through `readout`. Updated `examples/dsl/README.md` to document primitive-native components, continued qlibrary `class` rejection, and `type: transmon_pocket` as the YAML-native replacement path that expands to primitive IR before export. The rounds 01-07 review had no P0/high findings; remaining P2 cleanup items were recorded but not fixed. Verified with `C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_transmon_pocket_demo.py` (`PASS: YAML-native TransmonPocket template exported to Metal`), `C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py` (`PASS: native DSL chain exported to Metal`), and `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q` (`106 passed, 5 warnings`). Detailed report: `.codex/dsl_v3_transmon_template_round_08.md`.
- Round 09: Added a focused TransmonPocket parity/integration test file, `tests/test_design_dsl_transmon_pocket.py`, while preserving the round-08 example and README changes already in the worktree. The new tests build `examples/dsl/transmon_pocket_2q.metal.yaml`, assert both YAML-native transmons export as `NativeComponent`, verify generated qgeometry rows/pins/netlist/template metadata, and compare YAML `type: transmon_pocket` geometry and generated `readout` pin data against qlibrary `TransmonPocket` references for multiple orientations and pad quadrants. The qlibrary class is used only as a test reference, not as the DSL construction target. The rounds 01-07 review had no P0/high findings; remaining P2 cleanup items were recorded but not fixed. Verified with `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl_transmon_pocket.py -q` (`4 passed, 7 warnings`), `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py tests/test_design_dsl_transmon_pocket.py -q` (`110 passed, 8 warnings`), `C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_transmon_pocket_demo.py` (`PASS: YAML-native TransmonPocket template exported to Metal`), and `C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py` (`PASS: native DSL chain exported to Metal`). Detailed report: `.codex/dsl_v3_transmon_template_round_09.md`.
- Round 10: Performed the final closeout pass. Re-read the final implementation plan, progress file, rounds 08 and 09 reports, and the rounds 01-07 review. Confirmed the current worktree still only carries the expected examples/README/tests changes, with `.codex/` ignored by `.gitignore`. Rechecked the user-facing two-transmon YAML example, demo runner, README, focused TransmonPocket parity tests, and built-in `transmon_pocket.yaml`. No P0/high review findings remain; the only recorded review leftovers are P2 cleanup risks around expression/numeric error contracts and `build_ir()` design-variable context behavior. Verified with `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py tests/test_design_dsl_transmon_pocket.py -q` (`110 passed, 8 warnings`), `C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py` (`PASS: native DSL chain exported to Metal`), and `C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_transmon_pocket_demo.py` (`PASS: YAML-native TransmonPocket template exported to Metal`). The functional Definition of Done is satisfied, so this progress file is marked completed at 100%. Detailed report: `.codex/dsl_v3_transmon_template_round_10.md`.
