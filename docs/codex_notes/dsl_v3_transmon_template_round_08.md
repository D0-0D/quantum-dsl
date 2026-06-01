# DSL v3 Transmon Template Round 08

Date: 2026-05-11

Worker: DSL v3 Transmon YAML template loop worker, round 8

## Slice Chosen

Continued from checkpoint `9879755d`, where the static pocket geometry,
connection-pad generator, pin parity fixes, and template tests were already in
place. The progress file still listed the user-facing example and README update
as incomplete, so this round chose that mainline slice:

- add a two-transmon YAML-native `transmon_pocket` example
- add a runnable demo for that example
- update the DSL README to document primitive-native and YAML-template-native
  authoring

This keeps the implementation moving from internal parity toward documented
usage without changing DSL behavior.

## Initial State

Command run first:

```text
git status --short
```

Initial status:

```text

```

The worktree was clean. `.codex/` is ignored by `.gitignore`, so this round's
planning/progress documents remain untracked as requested.

## Required Context Read

Read before editing:

- `.codex/dsl_v3_transmon_template_final_implementation_plan.md`
- `.codex/dsl_v3_transmon_template_progress.md`
- `.codex/dsl_v3_transmon_template_round_07.md`
- `.codex/dsl_v3_transmon_template_round_07_parity_fix.md`
- `.codex/dsl_v3_transmon_template_direction_check_recheck_after_round_07.md`
- `.codex/dsl_v3_transmon_template_review_rounds_01_07.md`

Also inspected the existing example style in:

- `examples/dsl/README.md`
- `examples/dsl/run_chain_demo.py`
- `examples/dsl/chain_2q_native.metal.yaml`

## P0/High Review Handling

The rounds 01-07 review document reports no current P0/P1 issue at checkpoint
`9879755d`.

The remaining review findings are P2 cleanup items:

- expression arithmetic runtime errors can still leak raw Python exceptions
- invalid numeric fields can still leak raw `ValueError`, and boolean numeric
  values can be accepted
- `build_ir()` instantiates the selected design class to read default variables

Per the round instructions, only P0/high findings were to interrupt the mainline
slice. These P2 items were recorded here but not fixed in this round.

## Mainline Changes

### Two-transmon template YAML example

Added:

```text
examples/dsl/transmon_pocket_2q.metal.yaml
```

The example builds:

- `Q1` and `Q2` as `type: transmon_pocket`
- shared root variables for `qx`, `cpw_width`, `cpw_gap`, and simple circuit /
  hamiltonian values
- generated `readout` connection pads on both transmons
- a netlist connection from `Q1.readout` to `Q2.readout`

The YAML follows the final plan's intended authoring shape and uses the
YAML-native template path rather than any qlibrary `class` component.

### Runnable TransmonPocket demo

Added:

```text
examples/dsl/run_transmon_pocket_demo.py
```

The runner:

- builds IR and Metal design from `transmon_pocket_2q.metal.yaml`
- prints schema, components, resolved component types, template inheritance
  metadata, qgeometry row counts/names, generated pins, net row count, and
  metadata keys
- asserts both components are `NativeComponent`
- asserts both components resolve through the `transmon_pocket` template
- asserts expected generated rows:
  - two `pad_top`
  - two `pad_bot`
  - two `rect_pk`
  - two `readout_connector_pad`
  - two `readout_wire`
  - two `readout_wire_sub`
  - two `rect_jj`
- asserts both `readout` pins share the connected net

### README update

Updated:

```text
examples/dsl/README.md
```

The README now says:

- primitive-only components are still supported
- qlibrary `class` components remain rejected
- `type: transmon_pocket` is the YAML-native replacement path
- the template expands YAML defaults, connection-pad rules, geometry operations,
  and pins into primitive IR before export
- the new TransmonPocket YAML and demo are part of the example set

## Verification

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

Combined DSL regression suite:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q
```

Result:

```text
106 passed, 5 warnings
```

## Current State After Round

This round updated:

- `.codex/dsl_v3_transmon_template_progress.md`
- `.codex/dsl_v3_transmon_template_round_08.md`
- `examples/dsl/README.md`
- `examples/dsl/run_transmon_pocket_demo.py`
- `examples/dsl/transmon_pocket_2q.metal.yaml`

No code behavior was changed in `src/` or `tests/`.

## Remaining Work

Recommended next round:

- add or split a dedicated `tests/test_design_dsl_transmon_pocket.py` parity
  suite if the main agent wants stronger organization around the existing
  TransmonPocket checks
- address the P2 error-contract cleanup items from the rounds 01-07 review
  before expanding the template surface further

The major plan checklist items now remaining are integration cleanup and
documentation/test polish rather than core TransmonPocket functionality.
