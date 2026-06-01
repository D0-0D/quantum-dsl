# DSL v3 Transmon Template Round 06

Date: 2026-05-11

Worker: DSL v3 Transmon YAML template loop worker, round 6

## Slice Chosen

Added the first built-in YAML component templates and pushed slightly beyond the
recommended round-6 slice because the already-completed round-5 merge-rule work
made the next two template layers straightforward.

This round added:

- `qcomponent.yaml`
- `base_qubit.yaml`
- static core geometry in `transmon_pocket.yaml`

The connection-pad generator was not implemented in this round. The static
`transmon_pocket` template therefore supports the pocket body geometry
(`pad_top`, `pad_bot`, `rect_pk`, `rect_jj`) but does not yet generate
`readout_connector_pad`, `readout_wire`, `readout_wire_sub`, or pins from
`options.connection_pads`.

## Initial State

Command run first:

```text
git status --short
```

Initial status:

```text
```

The worktree was clean at the start of the round after checkpoint `dc009420`.

## Context Read

Required documents read before editing:

- `.codex/dsl_v3_transmon_template_final_implementation_plan.md`
- `.codex/dsl_v3_transmon_template_progress.md`
- `.codex/dsl_v3_transmon_template_review_rounds_01_03.md`
- `.codex/dsl_v3_transmon_template_round_04.md`
- `.codex/dsl_v3_transmon_template_round_05.md`

Checked for:

- `.codex/dsl_v3_transmon_template_review_rounds_01_03_recheck_after_05.md`

No recheck content was present.

## P0/High Review Handling

No remaining P0/high review issue required a fix in this round.

The review P1/high blockers from rounds 01-03 had already been addressed by
round 05:

- `merge_rules.connection_pads.each_entry_extends` is applied.
- unimplemented template `geometry.generators` fail loudly instead of being
silently ignored.

This round used that fixed foundation for `base_qubit.yaml` and left the
remaining review P2 items for later cleanup.

## Changes Made

### Built-in `qcomponent.yaml`

Added:

```text
src/qiskit_metal/toolbox_metal/dsl_templates/core/qcomponent.yaml
```

The template provides the generic `QComponent` option layer in YAML:

- `pos_x`
- `pos_y`
- `orientation`
- `chip`
- `layer`

It also defines the inherited component transform:

- translate by `pos_x`, `pos_y`
- rotate by `orientation`

No Python component-specific behavior was added.

### Built-in `base_qubit.yaml`

Added:

```text
src/qiskit_metal/toolbox_metal/dsl_templates/core/base_qubit.yaml
```

The template extends `qcomponent` and provides the qubit option layer:

- `connection_pads: {}`
- `_default_connection_pads: {}`
- metadata `short_name: Q`
- `merge_rules.connection_pads.each_entry_extends: _default_connection_pads`
- removal of `_default_connection_pads` from resolved runtime options

This uses the generic round-05 merge-rule infrastructure. It does not add
qubit-specific Python branches.

### Built-in Static `transmon_pocket.yaml`

Added:

```text
src/qiskit_metal/toolbox_metal/dsl_templates/qubits/transmon_pocket.yaml
```

The template extends `base_qubit` and adds the static pocket geometry portion of
`TransmonPocket.make_pocket()`:

- default TransmonPocket pocket options
- `_default_connection_pads` option defaults for later generator support
- metadata `short_name: Pocket`
- metadata `qgeometry_tables: [poly, path, junction]`
- `pad_top`
- `pad_bot`
- `rect_pk` with `subtract: true`
- `rect_jj` as a `junction.line` with width from `options.inductor_width`

All transmon-specific names and formulas were kept in YAML. Python continues to
provide only the generic template, expression, transform, primitive, pin, and
export infrastructure.

### Tests

Updated:

```text
tests/test_design_dsl_templates.py
```

Added coverage for:

- built-in `qcomponent` inheritance by a child template
- YAML-sourced `pos_x`, `pos_y`, `orientation`, `chip`, and `layer`
- built-in `base_qubit` inheritance and `connection_pads` default merging
- removal of `_default_connection_pads` from resolved component options
- built-in `transmon_pocket` static primitive names and options
- `pad_top`, `pad_bot`, `rect_pk`, and `rect_jj` geometry basics
- `rect_pk` subtract flag
- `rect_jj` junction width and length
- export of static TransmonPocket qgeometry rows into Metal
- no qlibrary `TransmonPocket` construction by monkeypatching
  `TransmonPocket.__init__` to fail

## Verification

Template test slice:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl_templates.py -q
```

Result:

```text
27 passed, 5 warnings in 6.85s
```

Primitive-only regression plus template tests:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q
```

Result:

```text
96 passed, 5 warnings in 7.36s
```

Existing demo:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py
```

Result:

```text
schema       : qiskit-metal/design-dsl/3
components   : ['Q1', 'Q2', 'bus']
poly rows    : 6
path rows    : 2
junction rows: 2
net rows     : 4
derived keys : ['circuit', 'netlist']
PASS: native DSL chain exported to Metal
```

## Current State After Round

This round updated:

- `.codex/dsl_v3_transmon_template_progress.md`
- `.codex/dsl_v3_transmon_template_round_06.md`
- `src/qiskit_metal/toolbox_metal/dsl_templates/core/qcomponent.yaml`
- `src/qiskit_metal/toolbox_metal/dsl_templates/core/base_qubit.yaml`
- `src/qiskit_metal/toolbox_metal/dsl_templates/qubits/transmon_pocket.yaml`
- `tests/test_design_dsl_templates.py`

## Remaining Work

Recommended next round:

Implement generic YAML generator support for `connection_pads`, including
operation-local generator variables and generated primitive/pin names. Then
wire the TransmonPocket connection-pad recipe in YAML and cover:

- `readout_connector_pad`
- `readout_wire`
- `readout_wire_sub`
- generated normal-segment pin `readout`
- multiple pads
- netlist connection through generated pins

Later rounds should add:

- two-transmon example
- README updates
- stronger TransmonPocket parity tests against qlibrary bounds
- any remaining P2 cleanup from the review, especially expression runtime error
  wrapping
