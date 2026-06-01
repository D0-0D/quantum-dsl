# DSL v3 Transmon Template Round 07 Parity Fix

Date: 2026-05-11

Worker: DSL v3 Transmon YAML template parity correction worker

Scope: round 7 checkpoint-prep parity fix, not a round 8 slice.

## Required Context Read

Read before editing:

- `.codex/dsl_v3_transmon_template_direction_check_after_round_07.md`
- `.codex/dsl_v3_transmon_template_progress.md`
- `.codex/dsl_v3_transmon_template_final_implementation_plan.md`
- `.codex/dsl_v3_transmon_template_round_07.md`

Initial worktree state was inspected with `git status --short`. Existing
round-07 uncommitted changes were preserved.

## Fix 1: TransmonPocket Generated Pin Gap Parity

Issue:

- The built-in YAML `transmon_pocket` generated connection-pad pin explicitly
  set `gap: "${pad.value.cpw_gap}"`.
- Original qlibrary `TransmonPocket.make_connection_pad()` calls
  `add_pin(..., width=cpw_width, input_as_norm=True, chip=chip)` and does not
  pass `gap`.
- `QComponent.add_pin()` therefore defaults gap to `0.6 * width`.

Change:

- Removed the explicit generated pin `gap` field from
  `src/qiskit_metal/toolbox_metal/dsl_templates/qubits/transmon_pocket.yaml`.
- This keeps the component-specific behavior in YAML while letting the generic
  DSL pin parser/export path preserve the same default as `QComponent.add_pin`.

Test coverage:

- Updated the built-in connection-pad test so `cpw_width=12um` and
  `cpw_gap=7um` intentionally are not in a 0.6 ratio.
- Asserted IR and exported Metal pin gap are `0.0072`, matching
  `0.6 * 12um`, not `0.007`.

## Fix 2: Symbolic CPW Defaults Resolve Through Design Variables

Issue:

- Built-in `transmon_pocket` defaults keep qlibrary-style symbolic values:
  `cpw_width: cpw_width` and `cpw_gap: cpw_gap`.
- Before this fix, template expression evaluation only received root DSL
  `vars`, so `connection_pads: {readout: {}}` failed unless root
  `vars.cpw_width` and `vars.cpw_gap` were supplied.
- Original qlibrary resolves those symbols through the selected Metal design's
  variables. `DesignPlanar` provides `cpw_width = 10 um` and
  `cpw_gap = 6 um`.

Change:

- Added a generic design-variable context path in
  `src/qiskit_metal/toolbox_metal/dsl/builder.py`.
- The numeric/template parse variable context now starts from the selected
  design's variables, then applies `geometry.design.variables`, then root
  `vars`.
- `build_ir()` constructs the selected design class with renderers disabled
  only to read default design variables. This is generic design infrastructure;
  it does not instantiate qlibrary `TransmonPocket`, does not add a
  `transmon_pocket` branch, and does not move transmon formulas into Python.
- `export_ir_to_metal()` still instantiates the actual export design through
  the normal path.

Precedence implemented for template numeric parsing:

1. selected Metal design defaults
2. `geometry.design.variables`
3. root `vars`

This matches the direction-check requirement for the current code path. API
`overrides` are already merged into the source spec before parsing, so they
participate through the same root/design fields.

Test coverage:

- Added a built-in `transmon_pocket` test with no root `vars` and
  `connection_pads: {readout: {}}`.
- Asserted generated `readout_wire` width is `0.010`.
- Asserted generated `readout_wire_sub` width is `0.022`.
- Asserted IR and exported Metal pin width/gap are `0.010` and `0.006`.

## Verification

Template test slice:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl_templates.py -q
```

Result:

```text
37 passed, 5 warnings
```

Required combined test command:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q
```

Result:

```text
106 passed, 5 warnings
```

## Direction Constraints Checked

- Did not modify core qlibrary Python components.
- Did not reintroduce Python `TransmonPocket` as a DSL construction target.
- Did not add component-specific Python branching such as
  `if type == "transmon_pocket"`.
- Kept transmon-specific geometry/default formulas in
  `dsl_templates/qubits/transmon_pocket.yaml`.
- Kept the exporter primitive-only through `NativeComponent/QComponent`.

## Progress Impact

This resolves the two P1 parity corrections required by the direction check
before treating the round-07 checkpoint as TransmonPocket-parity complete.

Overall progress moved from 76% to 78%. The current round remains round 7.
