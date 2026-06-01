# DSL v3 Transmon Template Round 05

Date: 2026-05-11

Worker: DSL v3 Transmon YAML template loop worker, round 5

## Slice Chosen

Added the pin modes needed by the TransmonPocket template path, with special
focus on qlibrary-compatible `normal_segment` pins.

I also fixed the review P1/high issues that block upcoming YAML
`base_qubit`/`transmon_pocket` work:

- `merge_rules` are now applied for map-entry inheritance.
- Template `geometry.generators` are no longer accepted and silently ignored
  before generator support exists.

After the user confirmed "修了就修了...", I kept the small falsey
typed-component metadata validation fix from the review P2 list. I did not work
on any other medium/low/P2 findings.

## Initial State

Command run first:

```text
git status --short
```

Initial status:

```text
 M .codex/dsl_v3_transmon_template_progress.md
 M src/qiskit_metal/toolbox_metal/design_dsl.py
 M src/qiskit_metal/toolbox_metal/dsl/__init__.py
 M src/qiskit_metal/toolbox_metal/dsl/builder.py
 M src/qiskit_metal/toolbox_metal/dsl/component_templates.py
 M tests/test_design_dsl_templates.py
?? .codex/dsl_v3_transmon_template_review_rounds_01_03.md
?? .codex/dsl_v3_transmon_template_round_04.md
?? src/qiskit_metal/toolbox_metal/dsl/geometry_ops.py
```

Those files include previous-round and review artifacts. I treated them as
existing work and did not revert unrelated changes.

## Changes Made

- Updated `src/qiskit_metal/toolbox_metal/dsl/builder.py`.
  - Added explicit pin `mode` support.
  - Preserved the existing explicit point behavior as `tangent_points`.
  - Added `normal_segment` pins:
    - source a `LineString` from `from_operation` or `operation`
    - currently support `segment: last`
    - use the last two line coordinates as the normal input segment
    - compute the tangent edge points using the same rotate-and-round behavior
      as `QComponent.add_pin(..., input_as_norm=True)`
    - apply component/pin transforms to both tangent points and normal input
      points
  - Added `PinIR.input_as_norm` and `PinIR.normal_points`.
  - Export now calls `component.add_pin(..., input_as_norm=True)` for
    `normal_segment` pins, while still exporting ordinary pins as before.
  - Kept the exporter path on `NativeComponent`; no qlibrary component class is
    instantiated.
- Updated `src/qiskit_metal/toolbox_metal/dsl/component_templates.py`.
  - Implemented generic option merge-rule handling.
  - Added support for:

    ```yaml
    merge_rules:
      connection_pads:
        each_entry_extends: _default_connection_pads
        remove_from_resolved_options:
          - _default_connection_pads
    ```

  - Validation now permits arbitrary entry names under a rule-controlled map
    such as `connection_pads.readout`, while still rejecting unknown fields
    inside each entry after defaults are known.
  - Applied `remove_from_resolved_options` after entry defaults are merged, so
    `_default_connection_pads` can be removed from runtime resolved options.
  - Made template `geometry.generators` fail with a clear "not supported yet"
    error. This fixes the review issue where accepted generators could be
    silently ignored before round 9 support lands.
  - Kept the small typed-component metadata fix: falsey non-mapping values such
    as `metadata: false`, `metadata: []`, and `metadata: ''` now fail
    consistently.
- Updated `tests/test_design_dsl_templates.py`.
  - Added normal-segment pin tests for IR and exported Metal pins.
  - Added transform coverage for normal-segment pins.
  - Added clear-error tests for invalid pin mode usage.
  - Added `merge_rules.each_entry_extends` tests for inherited
    `connection_pads` and unknown field rejection.
  - Added generator-not-supported coverage so unimplemented generator recipes
    cannot disappear silently.
  - Added typed-component falsey metadata validation coverage.

## Review Findings Addressed

From `.codex/dsl_v3_transmon_template_review_rounds_01_03.md`:

- P1 `merge_rules` collected but never applied:
  - Fixed in this round.
  - Future `base_qubit.yaml` can now define `_default_connection_pads` and let
    arbitrary `connection_pads.<pad_name>` entries inherit those defaults.
- P1 accepted `operations`/`generators` fields silently ignored:
  - `operations` had already been wired by round 04.
  - `generators` now fail explicitly until generator support is implemented.

P2 falsey typed-component metadata:

- Fixed after user confirmation during the round.

P2 expression arithmetic runtime errors and typed interpolation scope:

- Not changed in this round.
- Still tracked as later cleanup/risk.

## Verification

Template test slice:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl_templates.py -q
```

Result:

```text
23 passed, 5 warnings in 6.95s
```

Primitive-only regression plus template tests:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q
```

Final result after keeping the user-approved metadata fix:

```text
92 passed, 5 warnings in 8.18s
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
- `.codex/dsl_v3_transmon_template_round_05.md`
- `src/qiskit_metal/toolbox_metal/dsl/builder.py`
- `src/qiskit_metal/toolbox_metal/dsl/component_templates.py`
- `tests/test_design_dsl_templates.py`

The worktree also still contains previous-round changes:

- `src/qiskit_metal/toolbox_metal/design_dsl.py`
- `src/qiskit_metal/toolbox_metal/dsl/__init__.py`
- `src/qiskit_metal/toolbox_metal/dsl/geometry_ops.py`
- `.codex/dsl_v3_transmon_template_review_rounds_01_03.md`
- `.codex/dsl_v3_transmon_template_round_04.md`

## Remaining Work

Recommended next round:

Add `qcomponent.yaml` and the built-in template file foundation, using the
existing template inheritance and generic transform behavior.

Then:

- Add `base_qubit.yaml` using the now-working `connection_pads`
  map-entry inheritance.
- Add static `transmon_pocket.yaml` pocket geometry.
- Implement YAML generator support for `connection_pads`.
- Add two-transmon example, README updates, and TransmonPocket parity/no
  qlibrary-construction tests.
- Later cleanup can address the remaining review P2 expression/runtime and
  global typed-interpolation risks.
