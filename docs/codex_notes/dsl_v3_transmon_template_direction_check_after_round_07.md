# DSL v3 Transmon Template Direction Check After Round 07

Date: 2026-05-11

Role: independent direction/checkpoint reviewer.

Target worktree:

`D:\BaiduSyncdisk\vsCOde\circuit\qiskit\qiskit-metal-worktrees\dyk07-main`

Current code state reviewed:

- HEAD: `dc009420` (`Advance DSL template operations checkpoint`)
- Prior checkpoint: `a8aeaf41` (`Add DSL template infrastructure checkpoint`)
- Current worktree includes uncommitted round-07 changes.
- `.codex/` is ignored by git and remains local-only.

Documents reviewed:

- `.codex/dsl_v3_transmon_template_progress.md`
- `.codex/dsl_v3_transmon_template_final_implementation_plan.md`
- `.codex/dsl_v3_transmon_template_round_01.md`
- `.codex/dsl_v3_transmon_template_round_02.md`
- `.codex/dsl_v3_transmon_template_round_03.md`
- `.codex/dsl_v3_transmon_template_round_04.md`
- `.codex/dsl_v3_transmon_template_round_05.md`
- `.codex/dsl_v3_transmon_template_round_06.md`
- `.codex/dsl_v3_transmon_template_round_07.md`
- `.codex/dsl_v3_transmon_template_review_rounds_01_03.md`
- `.codex/dsl_v3_transmon_template_review_rounds_01_05.md`

Implementation files checked:

- `src/qiskit_metal/toolbox_metal/design_dsl.py`
- `src/qiskit_metal/toolbox_metal/dsl/__init__.py`
- `src/qiskit_metal/toolbox_metal/dsl/builder.py`
- `src/qiskit_metal/toolbox_metal/dsl/component_templates.py`
- `src/qiskit_metal/toolbox_metal/dsl/geometry_ops.py`
- `src/qiskit_metal/toolbox_metal/dsl/template_model.py`
- `src/qiskit_metal/toolbox_metal/dsl/template_registry.py`
- `src/qiskit_metal/toolbox_metal/dsl_templates/core/qcomponent.yaml`
- `src/qiskit_metal/toolbox_metal/dsl_templates/core/base_qubit.yaml`
- `src/qiskit_metal/toolbox_metal/dsl_templates/qubits/transmon_pocket.yaml`
- `tests/test_design_dsl_templates.py`
- original `src/qiskit_metal/qlibrary/qubits/transmon_pocket.py`
- original `src/qiskit_metal/qlibrary/core/qubit.py`
- original `src/qiskit_metal/qlibrary/core/base.py`

No core code was modified by this review.

## Short Conclusion

The current development is on the correct road.

The implementation is still replacing qlibrary components as the DSL authoring/build target, not deleting Metal core and not secretly bringing back the Python `TransmonPocket` class. The DSL path is:

```text
YAML design/type/options
-> built-in YAML templates
-> generic template/generator/operation expansion
-> ComponentIR/PrimitiveIR/PinIR
-> NativeComponent/QComponent export
-> qgeometry/pins/net_info
```

That matches the intended interpretation of the original requirement:

> remove qlibrary-like Python component templates from the DSL construction path, while keeping Metal core as the export/runtime substrate.

The round-07 work is directionally sound and usefully advances the TransmonPocket replacement. It adds generic YAML generator support and expresses connection-pad geometry/pins in `transmon_pocket.yaml`, not in component-specific Python code.

There are two qlibrary parity corrections that should be made before claiming TransmonPocket parity or cutting the round-07 checkpoint as "complete":

1. Generated TransmonPocket pin `gap` currently uses `cpw_gap`, but original qlibrary `TransmonPocket` does not pass `gap` to `add_pin`, so `QComponent.add_pin()` defaults it to `0.6 * cpw_width`.
2. Built-in `transmon_pocket` connection pads currently require top-level DSL `vars.cpw_width` and `vars.cpw_gap` when those defaults remain symbolic. Original qlibrary resolves the same strings through `DesignPlanar`/Metal design variables, so a default `connection_pads: {readout: {}}` should work without explicitly adding root `vars`.

These are fixable parity gaps, not direction failures.

## Original Requirement Alignment

Original requirement:

> Start to extend the file format to Hamiltonian-Circuit-Netlist-Geometry full chain, and the information of circuit can be passed up and down. (Next: remove Qiskit library like TransmonPocket) to do: to remove Qiskit library like TransmonPocket

Current alignment:

- The file format now supports the Hamiltonian/Circuit/Netlist/Geometry sections from the original v3 slice.
- Typed YAML component templates can read local `vars`, `circuit`, `hamiltonian`, `netlist`, `component`, and `options` context.
- TransmonPocket geometry is now authored as YAML template data, not as a qlibrary class.
- Netlist can connect generated pins from YAML `transmon_pocket` components.
- Export still targets Metal qgeometry/pins/net_info through `NativeComponent`, which is the right level to keep.

Current limitation:

- Hamiltonian and circuit propagation remains mostly structural/interpolation-based. The work has not yet added physics-aware Hamiltonian extraction from generated geometry, junction symbols, capacitance estimates, or coupling models. That is acceptable at this phase because the immediate target is qlibrary template replacement, not full solver integration.

## Direction Check

### Is qlibrary being replaced as DSL authoring/build target?

Yes.

Evidence:

- `type: transmon_pocket` resolves through `ComponentTemplateRegistry` to `dsl_templates/qubits/transmon_pocket.yaml`.
- The registry maps built-in template ids to YAML files:
  - `qcomponent`
  - `base_qubit`
  - `transmon_pocket`
- `component_templates.py` expands type/options generically.
- `builder.py` still rejects `class` entries in native components and primitives.
- `tests/test_design_dsl_templates.py` monkeypatches `TransmonPocket.__init__` to fail and verifies DSL `type: transmon_pocket` still builds.

No component-specific Python branch such as `if type == "transmon_pocket": ...` was found in the expansion/build path.

### Is Metal core being kept rather than deleted?

Yes.

Current export still correctly relies on:

- `QDesign`
- `NativeComponent(QComponent)`
- `design.qgeometry.add_qgeometry`
- `component.add_pin`
- `design.connect_pins`

That is intentional and correct. The goal is not to remove `QComponent` or the Metal design model.

### Has Python `TransmonPocket` been secretly reintroduced?

No.

The only observed uses of qlibrary `TransmonPocket` are:

- docstrings/comments referring to the class as something not instantiated
- tests that import it as a reference/monkeypatch target
- manual review probes against qlibrary for parity

That is acceptable.

## Behavior Consistency Review

### QComponent Layer

Original behavior:

- `QComponent.default_options` defines `pos_x`, `pos_y`, `orientation`, `chip`, and `layer`.
- `QComponent` owns lifecycle, component id, design registration, pins, and qgeometry export helpers.

Current YAML/template behavior:

- `qcomponent.yaml` defines:
  - `pos_x: 0.0um`
  - `pos_y: 0.0um`
  - `orientation: 0.0`
  - `chip: main`
  - `layer: 1`
- It supplies inherited component transform:
  - translate by `pos_x`, `pos_y`
  - rotate by `orientation`
- Runtime lifecycle remains in `NativeComponent/QComponent`.

Assessment:

Correct. YAML models the reusable defaults and transform intent. It does not try to reimplement QComponent lifecycle in YAML.

### BaseQubit Layer

Original behavior:

- `BaseQubit.default_options` adds:
  - `connection_pads`
  - `_default_connection_pads`
- `_set_options_connection_pads()` deep-copies `_default_connection_pads` into every named pad and merges per-pad overrides.
- `_default_connection_pads` is removed from final runtime options.

Current YAML/template behavior:

- `base_qubit.yaml` extends `qcomponent`.
- It defines `connection_pads` and `_default_connection_pads`.
- Its merge rule:

```yaml
connection_pads:
  each_entry_extends: _default_connection_pads
  remove_from_resolved_options:
    - _default_connection_pads
```

- Tests verify arbitrary pad names such as `readout` and `drive` inherit defaults and override selected fields.

Assessment:

Correct and on-plan. This is the right generic replacement for `BaseQubit._set_options_connection_pads()`.

### Static TransmonPocket Geometry

Original `make_pocket()` creates:

- `pad_top`
- `pad_bot`
- `rect_pk`
- `rect_jj`
- `rect_pk` subtract geometry
- `rect_jj` junction geometry with width `inductor_width`
- rotation by `orientation`
- translation by `pos_x`, `pos_y`

Current YAML behavior:

- `transmon_pocket.yaml` extends `base_qubit`.
- It defines original default values:
  - `pad_gap`
  - `inductor_width`
  - `pad_width`
  - `pad_height`
  - `pocket_width`
  - `pocket_height`
  - `_default_connection_pads`
- It generates:
  - `pad_top`
  - `pad_bot`
  - `rect_pk`
  - `rect_jj`
- Row names, kinds, subtract flag, layer, chip, and junction width are tested.
- Rotation/translation are applied once through inherited `qcomponent` transform.

Assessment:

Correct. The static pocket path is consistent with original qlibrary behavior.

### Connection Pad Geometry

Original `make_connection_pad(name)` creates:

- `{name}_connector_pad` as poly
- `{name}_wire` as path
- `{name}_wire_sub` as path with `width = cpw_width + 2 * cpw_gap`, `subtract=True`
- pin named `{name}`
- scale by `loc_W`, `loc_H`
- translate by pad/pocket offsets
- rotate/position by `orientation`, `pos_x`, `pos_y`

Current YAML behavior:

- `transmon_pocket.yaml` uses a generic `generators.connection_pads` block.
- Generator iterates over `options.connection_pads`.
- It creates:
  - `readout_connector_pad`
  - `readout_wire`
  - `readout_wire_sub`
  - pin `readout`
- `transform_group` handles generic local scale/translate.
- The inherited component transform applies `orientation`, `pos_x`, `pos_y`.
- Tests cover generated rows, widths, subtract flags, normal-segment pins, per-pad overrides, and netlist connection.
- Additional review probes against qlibrary matched qlibrary path/pin output at:
  - `orientation=45`
  - `orientation=90`
  - `orientation=180`
  - `orientation=270`
  - nonzero `pos_x`, `pos_y`

Assessment:

Direction and implementation are good. The transform model is equivalent to original qlibrary behavior in the sampled cases.

Remaining gap:

- Pin gap semantics differ when `cpw_gap != 0.6 * cpw_width`; see P1 finding below.

### Pin Semantics

Original qlibrary behavior:

- `TransmonPocket.make_connection_pad()` calls:

```python
self.add_pin(name,
             points=points[-2:],
             width=cpw_width,
             input_as_norm=True,
             chip=chip)
```

- It does not pass `gap`.
- `QComponent.add_pin()` therefore defaults `gap` to `width * 0.6`.
- With default Metal variables `cpw_width=10um`, `cpw_gap=6um`, this equals CPW gap by coincidence.

Current YAML behavior:

- `normal_segment` mode now correctly transforms normal points first and recomputes edge points in the same style as `QComponent.add_pin(input_as_norm=True)`.
- IR, derived metadata, and exported Metal pins now match for non-right-angle rotations.
- However, `transmon_pocket.yaml` currently sets generated pin `gap` to `${pad.value.cpw_gap}`.

Assessment:

The normal/tangent/point semantics are now correct. The generated pin gap is not fully qlibrary-compatible for override cases.

Example probe:

- qlibrary with `cpw_width=12um`, `cpw_gap=7um` exported pin gap: `0.0072`
- current YAML exported pin gap: `0.007`

This should be fixed before claiming parity.

### Netlist/Pins

Current behavior:

- Generated `readout` pins are present on `NativeComponent` components.
- `design.connect_pins` connects generated pins.
- Tests verify `Q1.readout` to `Q2.readout` net id.

Assessment:

Correct.

### qgeometry Metadata

Current behavior:

- Static rows:
  - `pad_top`
  - `pad_bot`
  - `rect_pk`
  - `rect_jj`
- Connection rows:
  - `{pad}_connector_pad`
  - `{pad}_wire`
  - `{pad}_wire_sub`
- Kinds and subtract flags match the original component's intended rows.
- `rect_jj.width` and path widths are set.
- Export remains direct through `design.qgeometry.add_qgeometry`, consistent with v3's primitive exporter.

Assessment:

Good for this phase.

Known intentional difference:

- Current v3 exporter does not inject renderer qgeometry defaults through `QComponent.add_qgeometry`. Existing tests explicitly assert this. Keep it unchanged unless renderer integration becomes a later explicit goal.

## Findings

### P1: Generated TransmonPocket pin gap does not match qlibrary override behavior

Current YAML generated pin:

```yaml
gap: "${pad.value.cpw_gap}"
```

Original qlibrary `TransmonPocket` does not pass `gap` to `add_pin`, so `QComponent.add_pin()` uses:

```python
gap = width * 0.6
```

Impact:

- Default `cpw_width=10um`, `cpw_gap=6um` looks correct because both are `0.006mm`.
- Override cases diverge, for example:
  - `cpw_width=12um`
  - `cpw_gap=7um`
  - qlibrary pin gap: `7.2um`
  - YAML pin gap: `7um`

Required correction:

- Remove `gap` from the generated TransmonPocket pin YAML, or add a template-level expression that exactly reproduces `0.6 * cpw_width`.
- For strict qlibrary parity, prefer omitting `gap` so the existing exporter path calls `component.add_pin(..., gap=None)` and lets `QComponent` compute the default.

Required tests:

- Add a qlibrary parity test where `cpw_width` and `cpw_gap` are intentionally not in a `0.6` ratio.
- Assert exported YAML pin gap matches qlibrary, not `cpw_gap`.

### P1: Built-in TransmonPocket connection pad defaults do not resolve Metal design variables unless root `vars` are supplied

Original qlibrary defaults:

```python
cpw_width='cpw_width'
cpw_gap='cpw_gap'
```

These are resolved through Metal design variables. A default `DesignPlanar` provides:

- `cpw_width = 10 um`
- `cpw_gap = 6 um`

Current YAML behavior:

- `transmon_pocket.yaml` correctly preserves these symbolic defaults:
  - `cpw_width: cpw_width`
  - `cpw_gap: cpw_gap`
- However, if the DSL file has no top-level `vars.cpw_width` / `vars.cpw_gap`, a generated connection pad fails during expression evaluation:

```text
DesignDslError Expression ${pad.value.pad_cpw_shift + pad.value.cpw_width / 2}
requires numeric values; got 'cpw_width'
```

Impact:

- Current tests usually add root `vars.cpw_width` and `vars.cpw_gap`, so this gap is hidden.
- qlibrary users expect default connection pads to build with default design variables.

Required correction:

- Make the template expression variable context include Metal design variables for the selected design, or add an equivalent DSL variable default layer that gives built-in templates access to `cpw_width` and `cpw_gap`.
- Precedence should be:
  1. Metal/design defaults
  2. `geometry.design.variables`
  3. root `vars`
  4. API overrides

At minimum:

- `type: transmon_pocket` with `connection_pads: {readout: {}}` should build without requiring root `vars`.

Required tests:

- Build `transmon_pocket` with a default `readout` pad and no root `vars`; assert it uses default `cpw_width=10um`, `cpw_gap=6um`.
- Build with root vars overriding `cpw_width/cpw_gap`; assert overrides are used.

### P2: Full Hamiltonian/Circuit semantic propagation is still future work

Current v3 supports structural flow and interpolation, not physics-aware Hamiltonian/circuit derivation.

This is acceptable for the current TransmonPocket template milestone. Do not let this block the qlibrary-template replacement path.

### P2: `builder.py` remains large

`design_dsl.py` is now correctly reduced to a facade. The implementation logic moved into `dsl/builder.py`, which still contains many responsibilities.

This is acceptable for the current milestone, but after TransmonPocket parity stabilizes, consider splitting:

- IR/schema
- primitive parsing
- pin parsing
- netlist
- export
- builder orchestration

Do not prioritize this above the two P1 parity fixes.

### P2: Expression runtime cleanup remains

The previous review noted some arithmetic runtime errors can still leak raw Python exceptions. This remains a cleanup item after the parity fixes.

## Verification Performed

Command:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q
```

Result:

```text
105 passed, 5 warnings
```

Additional manual probes:

- qlibrary `TransmonPocket` versus YAML `type: transmon_pocket` path and pin coordinates at `orientation=45`, `90`, `180`, and `270` with nonzero `pos_x`, `pos_y`: matched.
- qlibrary pin gap versus YAML pin gap with `cpw_width=12um`, `cpw_gap=7um`: mismatch found, documented as P1.
- YAML `connection_pads: {readout: {}}` without root `vars.cpw_width/cpw_gap`: currently fails, documented as P1.

## Recommended Next Action

Before committing round 07 as a completed checkpoint, either fix the two P1 parity gaps or explicitly record the checkpoint as "directionally correct but parity-incomplete." My recommendation is to fix them before the checkpoint.

Next implementation slice:

1. Fix generated TransmonPocket pin gap to match qlibrary `add_pin(input_as_norm=True)` default behavior.
2. Add Metal/design variable defaults into template expression resolution so default `cpw_width` and `cpw_gap` work without top-level `vars`.
3. Add tests for both fixes.
4. Then proceed to the two-transmon example and README update.

## Final Direction Decision

Direction is correct.

Round 07 should be treated as a strong and mostly successful implementation step toward YAML-native `TransmonPocket`, with two concrete parity corrections required before declaring TransmonPocket behavior aligned with qlibrary.
