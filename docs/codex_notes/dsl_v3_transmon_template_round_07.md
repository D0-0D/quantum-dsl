# DSL v3 Transmon Template Round 07

Date: 2026-05-11

Worker: DSL v3 Transmon YAML template loop worker, round 7

## Slice Chosen

Continued from the round-06 state. Because round 06 had already added
`base_qubit.yaml` and the static `transmon_pocket.yaml` pocket geometry, this
round chose the next highest-value mainline slice:

- implement generic YAML generator support for template-driven repeated
  geometry
- use it to add `TransmonPocket.make_connection_pads()` behavior to
  `transmon_pocket.yaml`
- add generated pin and netlist coverage

This round also handled the P1/high findings from the rounds 01-05 review
before expanding the TransmonPocket template surface.

## Initial State

Command run first:

```text
git status --short
```

Initial status:

```text
 M tests/test_design_dsl_templates.py
?? src/qiskit_metal/toolbox_metal/dsl_templates/
```

These were treated as prior-round work products. No unrelated user or other
agent changes were reverted.

## Context Read

Required documents read before editing:

- `.codex/dsl_v3_transmon_template_final_implementation_plan.md`
- `.codex/dsl_v3_transmon_template_progress.md`
- `.codex/dsl_v3_transmon_template_review_rounds_01_05.md`
- `.codex/dsl_v3_transmon_template_round_06.md`

Also checked for:

- `.codex/dsl_v3_transmon_template_review_rounds_01_03_recheck_after_05.md`

The recheck file existed but contained no content.

## P0/High Review Handling

No P0 findings were present.

Fixed both remaining P1/high review issues from the rounds 01-05 review:

1. `normal_segment` IR/export mismatch for non-right-angle transforms

   Previously, `PinIR.points` for `normal_segment` pins were computed before
   the component transform, while export passed transformed normal points into
   `QComponent.add_pin(..., input_as_norm=True)`, allowing IR metadata and
   exported Metal pins to diverge at angles such as 45 degrees.

   This round changed the pin path so normal points are transformed first, then
   tangent edge points are recomputed from the transformed normal segment using
   the same rounding behavior as `QComponent.add_pin(input_as_norm=True)`.

   Added regression coverage comparing:

   - `PinIR.normal_points`
   - `PinIR.points`
   - derived metadata pin points
   - exported Metal component pin points

   at a 45 degree component rotation.

2. Malformed template geometry maps not strictly validated

   Tightened template validation so template `geometry.operations`,
   `geometry.transform`, and `geometry.generators` must be mappings when
   present. Also removed the typed-component expansion pattern that converted
   falsey/list values through `dict(value or {})`, which had allowed malformed
   `operations: []` or `operations: false` to disappear silently.

   Added negative tests for:

   - malformed template `geometry.operations`
   - malformed template `geometry.transform`
   - malformed typed-component instance `operations`

Medium/low/P2 review items were left for later cleanup unless naturally touched
by this round.

## Mainline Changes

### Generic generator expansion

Updated:

```text
src/qiskit_metal/toolbox_metal/dsl/builder.py
src/qiskit_metal/toolbox_metal/dsl/component_templates.py
src/qiskit_metal/toolbox_metal/dsl/template_model.py
```

Added generic component/template `generators` support with:

- strict generator key validation
- `for_each` over mappings or lists
- configurable local variable name via `as`
- per-entry local context shaped as `{key, value}`
- generator-local operation evaluation
- generated primitive/pin name interpolation
- automatic namespacing of generated operation references so multiple entries
  can use the same local operation names
- clear errors for unknown iterator expressions, duplicate keys, and operation
  namespace conflicts

The implementation is component-agnostic. It does not branch on
`transmon_pocket`.

### Generic `transform_group` operation

Updated:

```text
src/qiskit_metal/toolbox_metal/dsl/geometry_ops.py
```

Added a reusable `transform_group` operation that applies a sequence of generic
transform steps to multiple source operations and returns a mapping of
transformed outputs. Supported steps are the already generic transform
operations:

- `scale`
- `translate`
- `rotate`
- `rotate_position`

This lets YAML templates express "transform these related objects together"
without component-specific Python code.

### TransmonPocket connection-pad YAML

Updated:

```text
src/qiskit_metal/toolbox_metal/dsl_templates/qubits/transmon_pocket.yaml
```

Added the YAML generator recipe for `options.connection_pads`. For a pad such as
`readout`, the template now generates:

- `readout_connector_pad`
- `readout_wire`
- `readout_wire_sub`
- pin `readout`

The transmon-specific names and formulas remain in YAML. Python only supplies
the generic generator, operation, primitive, and pin infrastructure.

The YAML recipe intentionally applies only the per-pad local scale/translate in
the generator. The inherited `qcomponent.yaml` component transform then applies
`orientation`, `pos_x`, and `pos_y` once to all primitives and pins. A read-only
probe against qlibrary `TransmonPocket` confirmed that the generated readout
wire and pin coordinates match qlibrary behavior for `pos_x=1mm`, `pos_y=2mm`,
`orientation=90`.

### Tests

Updated:

```text
tests/test_design_dsl_templates.py
```

Added coverage for:

- non-right-angle `normal_segment` IR/export parity
- strict malformed template map validation
- generic generator expansion into multiple primitives and pins
- generated pins participating in `design.connect_pins`
- built-in `transmon_pocket` generating connection-pad qgeometry rows
- `readout_wire` and `readout_wire_sub` widths/subtract flags
- generated normal-segment pin geometry
- per-pad overrides for `cpw_width` and `cpw_gap`
- two YAML `transmon_pocket` components connected through generated `readout`
  pins
- component transform being applied once to generated connection-pad geometry

## Verification

Template test slice:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl_templates.py -q
```

Result:

```text
36 passed, 5 warnings
```

Primitive-only regression plus template tests:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q
```

Result:

```text
105 passed, 5 warnings
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

Additional read-only parity probe:

- built a qlibrary `TransmonPocket` at `pos_x=1mm`, `pos_y=2mm`,
  `orientation=90`
- confirmed qlibrary `readout_wire` coordinates match the YAML-generated test
  expectation:
  `[(0.869, 2.2275), (0.869, 2.2525), (0.804, 2.32), (0.804, 2.425)]`
- confirmed qlibrary pin middle/normal match the generated normal-segment pin
  semantics

## Current State After Round

This round updated:

- `.codex/dsl_v3_transmon_template_progress.md`
- `.codex/dsl_v3_transmon_template_round_07.md`
- `src/qiskit_metal/toolbox_metal/dsl/builder.py`
- `src/qiskit_metal/toolbox_metal/dsl/component_templates.py`
- `src/qiskit_metal/toolbox_metal/dsl/geometry_ops.py`
- `src/qiskit_metal/toolbox_metal/dsl/template_model.py`
- `src/qiskit_metal/toolbox_metal/dsl_templates/qubits/transmon_pocket.yaml`
- `tests/test_design_dsl_templates.py`

## Remaining Work

Recommended next round:

- add the two-transmon YAML example
- add/update the DSL README with the YAML-native template authoring path
- broaden TransmonPocket parity tests against qlibrary bounds/rows where useful

Later cleanup:

- address remaining P2 review items, especially wrapping expression arithmetic
  runtime failures such as divide-by-zero into `DesignDslError`
- consider moving the growing template tests into a separate
  `tests/test_design_dsl_transmon_pocket.py` file for readability
