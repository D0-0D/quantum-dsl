# DSL v3 Transmon Template Direction Check Recheck After Round 07

Date: 2026-05-11

Target worktree:

`D:\BaiduSyncdisk\vsCODE\circuit\qiskit\qiskit-metal-worktrees\dyk07-main`

Reviewed checkpoint:

`9879755d Add YAML TransmonPocket template checkpoint`

Purpose:

Recheck the two qlibrary parity issues identified in:

`.codex/dsl_v3_transmon_template_direction_check_after_round_07.md`

No core code was modified during this recheck.

## Short Result

Both parity points are resolved at checkpoint `9879755d`.

1. Generated TransmonPocket connection-pad pin gap now matches qlibrary `QComponent.add_pin()` default behavior: `0.6 * cpw_width`.
2. Built-in `transmon_pocket` connection pad defaults now resolve Metal design variables, so `connection_pads: {readout: {}}` works without root `vars.cpw_width` or `vars.cpw_gap`.

## Worktree State

`git status --short` was clean.

`git log --oneline --decorate -6` showed:

```text
9879755d (HEAD -> full_chain) Add YAML TransmonPocket template checkpoint
dc009420 Advance DSL template operations checkpoint
a8aeaf41 Add DSL template infrastructure checkpoint
99772d82 (origin/full_chain) fixing dsl v3-0
1d0399e9 dsl v3-0
9d87c54f Update references to user folders in gitignore
```

## Recheck 1: Pin Gap Parity

Previous issue:

- `transmon_pocket.yaml` generated the connection-pad pin with `gap: "${pad.value.cpw_gap}"`.
- Original qlibrary `TransmonPocket.make_connection_pad()` does not pass `gap` to `add_pin`, so `QComponent.add_pin()` defaults to `0.6 * cpw_width`.

Current implementation:

- `src/qiskit_metal/toolbox_metal/dsl_templates/qubits/transmon_pocket.yaml` no longer specifies `gap` on the generated normal-segment pin.
- `builder.py` keeps the generic pin default behavior:

```python
gap=_parse_optional_number(spec.get("gap"), variables)
if "gap" in spec else width * 0.6
```

Current tests:

- `tests/test_design_dsl_templates.py::test_builtin_transmon_pocket_generates_connection_pad_geometry_and_pin` now expects:
  - `pin.gap == pytest.approx(0.0072)` for `cpw_width=12um`
  - exported Metal pin gap also `0.0072`

Manual qlibrary probe:

- qlibrary `TransmonPocket` with `cpw_width=12um`, `cpw_gap=7um` exported pin gap: `0.0072`
- YAML `type: transmon_pocket` with same effective options exported pin gap: `0.0072`
- delta: `0.0`

Conclusion:

Resolved.

## Recheck 2: Metal Design Variable Defaults

Previous issue:

- Built-in `transmon_pocket` preserved qlibrary symbolic defaults:
  - `cpw_width: cpw_width`
  - `cpw_gap: cpw_gap`
- But generated connection-pad expressions could not resolve those symbols unless root `vars.cpw_width` and `vars.cpw_gap` were provided.
- Original qlibrary resolves them through `DesignPlanar` design variables.

Current implementation:

- `builder.py` adds `_design_variable_context()`.
- It instantiates the selected design class with renderer startup disabled and builds the numeric variable context from:
  1. selected design default variables
  2. `geometry.design.variables`
  3. root `vars`
- `build_ir()` now calls:

```python
variable_context = _design_variable_context(design_spec, vars_table)
component_ctx = {
    **variable_context,
    "vars": variable_context,
    "circuit": circuit,
    "hamiltonian": hamiltonian,
    "netlist": netlist,
}
components = _parse_components(..., variable_context)
```

Current tests:

- `tests/test_design_dsl_templates.py::test_builtin_transmon_pocket_default_connection_pad_uses_design_variables` builds:

```yaml
geometry:
  design: {class: DesignPlanar}
  components:
    Q1:
      type: transmon_pocket
      options:
        connection_pads:
          readout: {}
```

without root `vars`.

It verifies:

- `readout_wire.width == 0.010`
- `readout_wire_sub.width == 0.022`
- generated pin width `0.010`
- generated/exported pin gap `0.006`

Manual probe:

- YAML `connection_pads: {readout: {}}` without root vars now builds.
- Observed:
  - default wire width: `0.01`
  - default wire_sub width: `0.022`
  - default pin gap: `0.006`

Conclusion:

Resolved.

## Focused Test Command

Command:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl_templates.py -q -k "transmon_pocket and (gap or default_connection_pad or connection_pad)"
```

Result:

```text
4 passed, 33 deselected, 4 warnings
```

## Final Recheck Decision

Both previously flagged qlibrary parity points are fixed in checkpoint `9879755d`.

The remaining direction remains correct:

- qlibrary `TransmonPocket` is not used as the DSL build target;
- the component recipe is in YAML;
- Metal core remains preserved through `NativeComponent/QComponent`, qgeometry, pins, and net_info.
