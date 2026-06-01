# DSL v3 Transmon Template Round 09

Date: 2026-05-11

Worker: DSL v3 Transmon YAML template loop worker, round 9

## Slice Chosen

Continued from the round-08 state. The user-facing two-transmon YAML example,
demo runner, and README documentation were already present as uncommitted
changes, so this round chose the next most useful final-integration slice:

- add a focused TransmonPocket parity test file
- cover the new example YAML as a test fixture
- compare YAML-native `type: transmon_pocket` output against qlibrary
  `TransmonPocket` as a reference in tests

No source behavior changes were made in this round.

## Initial State

Command run first:

```text
git status --short
```

Initial status:

```text
 M examples/dsl/README.md
?? examples/dsl/run_transmon_pocket_demo.py
?? examples/dsl/transmon_pocket_2q.metal.yaml
```

These files match the round-08 report and were treated as prior-round work
products. They were preserved and reused. `.codex/` remains ignored by
`.gitignore`.

## Required Context Read

Read before editing:

- `.codex/dsl_v3_transmon_template_final_implementation_plan.md`
- `.codex/dsl_v3_transmon_template_progress.md`
- `.codex/dsl_v3_transmon_template_round_08.md`
- `.codex/dsl_v3_transmon_template_review_rounds_01_07.md`
- `.codex/dsl_v3_transmon_template_round_07.md`
- `.codex/dsl_v3_transmon_template_round_07_parity_fix.md`
- `.codex/dsl_v3_transmon_template_direction_check_recheck_after_round_07.md`

Also inspected:

- `examples/dsl/README.md`
- `examples/dsl/run_transmon_pocket_demo.py`
- `examples/dsl/transmon_pocket_2q.metal.yaml`
- existing TransmonPocket-related tests in `tests/test_design_dsl_templates.py`
- qlibrary reference implementation in
  `src/qiskit_metal/qlibrary/qubits/transmon_pocket.py`

## P0/High Review Handling

The rounds 01-07 review document reports no current P0/P1 issue at checkpoint
`9879755d`.

The only remaining review findings are P2 cleanup items:

- expression arithmetic runtime errors can leak raw Python exceptions
- invalid numeric fields can leak raw `ValueError`, and booleans can be
  accepted as numeric values
- `build_ir()` instantiates the selected design class to gather default design
  variables

Per the round instructions, only P0/high findings were to interrupt mainline
work. These P2 items were recorded but not fixed in this round.

## Mainline Changes

### Focused TransmonPocket parity tests

Added:

```text
tests/test_design_dsl_transmon_pocket.py
```

The new test file keeps the growing generic template tests from carrying all
TransmonPocket-specific final validation. It adds two focused groups.

First, the round-08 user-facing YAML example is now used as a test fixture:

- builds IR from `examples/dsl/transmon_pocket_2q.metal.yaml`
- builds a Metal design from the same YAML
- asserts both components are `NativeComponent`
- asserts both components resolve to `type: transmon_pocket`
- asserts generated qgeometry row names for poly/path/junction tables
- asserts both generated `readout` pins exist
- asserts the netlist connection assigns the same net id to both readout pins
- asserts `design.metadata["dsl_chain"]` records the resolved template type

Second, YAML-native TransmonPocket output is compared directly to a qlibrary
`TransmonPocket` reference for several orientations and pad quadrants:

- `(orientation=0, loc_W=1, loc_H=1)`
- `(orientation=45, loc_W=-1, loc_H=1)`
- `(orientation=123.4, loc_W=1, loc_H=-1)`

The test compares:

- `pad_top`
- `pad_bot`
- `rect_pk`
- `readout_connector_pad`
- `readout_wire`
- `readout_wire_sub`
- `rect_jj`
- subtract flags
- path and junction widths
- generated pin points, middle, normal, tangent, width, and gap

The qlibrary class is used only as a test reference. The DSL build path remains
YAML template -> primitive IR -> `NativeComponent`.

## Verification

Focused new test file:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl_transmon_pocket.py -q
```

Result:

```text
4 passed, 7 warnings
```

Combined DSL regression suite:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py tests/test_design_dsl_transmon_pocket.py -q
```

Result:

```text
110 passed, 8 warnings
```

New TransmonPocket example:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_transmon_pocket_demo.py
```

Result:

```text
PASS: YAML-native TransmonPocket template exported to Metal
```

Existing chain demo:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py
```

Result:

```text
PASS: native DSL chain exported to Metal
```

## Current State After Round

This round updated:

- `.codex/dsl_v3_transmon_template_progress.md`
- `.codex/dsl_v3_transmon_template_round_09.md`
- `tests/test_design_dsl_transmon_pocket.py`

The worktree also still contains the round-08 example and README changes:

- `examples/dsl/README.md`
- `examples/dsl/run_transmon_pocket_demo.py`
- `examples/dsl/transmon_pocket_2q.metal.yaml`

No source files under `src/` were changed in this round.

## Remaining Work

Recommended next round:

- optionally address the P2 error-contract cleanup items from the review
- consider adding a small regression test documenting the current
  design-variable context behavior in `build_ir()`
- perform final checklist pass and prepare a checkpoint if the main agent wants
  these round-08 and round-09 changes committed

The core TransmonPocket template implementation, example, README path, generated
pin/netlist coverage, no-qlibrary-construction coverage, and qlibrary parity
coverage are now in place.
