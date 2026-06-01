# DSL v3 Transmon Template Round 04

Date: 2026-05-11

Worker: DSL v3 Transmon YAML template loop worker, round 4

## Slice Chosen

Added the generic geometry operation registry and wired operation outputs into
template/native component primitive generation.

This follows the recommended Round 4 slice from the progress file. I did not
work on pin modes, built-in YAML templates, TransmonPocket formulas, or
connection-pad generators in this round.

## Initial State

Command run first:

```text
git status --short
```

Initial status:

```text
```

The worktree was clean at the start of this round, after checkpoint
`a8aeaf41`.

## Changes Made

- Added `src/qiskit_metal/toolbox_metal/dsl/geometry_ops.py`.
  - Defines `GeometryOperationRegistry`.
  - Defines `DEFAULT_GEOMETRY_OPERATIONS`.
  - Adds generic operation evaluation through
    `evaluate_geometry_operations()`.
  - Adds operation reference resolution through
    `resolve_operation_reference()`.
  - Registers component-agnostic operations:
    - `rectangle`
    - `polyline`
    - `line`
    - `polygon`
    - `buffer`
    - `scale`
    - `translate`
    - `rotate`
    - `rotate_position`
    - `last_segment`
  - Wraps Metal `draw` helpers where appropriate and uses shapely
    `LineString`/`Polygon` constructors for basic geometry creation.
  - Rejects unknown operations, unknown operation references, invalid operation
    names, invalid source geometry, and unknown operation keys.
- Updated `src/qiskit_metal/toolbox_metal/dsl/component_templates.py`.
  - Merges `geometry.operations` through template inheritance.
  - Allows instance-level `operations` to extend/override template operations.
  - Keeps template primitive/pin merging behavior unchanged.
- Updated `src/qiskit_metal/toolbox_metal/dsl/builder.py`.
  - Allows component-level `operations`.
  - Allows primitive `operation` references.
  - Evaluates operations per component after expression interpolation and before
    primitive parsing.
  - Adds `poly.from_operation`, `path.from_operation`, and
    `junction.from_operation`.
  - Keeps component transforms applied after operation geometry is selected, so
    existing component transform behavior remains consistent.
  - Validates that operation-backed poly primitives use polygons and
    path/junction primitives use line strings.
- Updated public facades:
  - `src/qiskit_metal/toolbox_metal/dsl/__init__.py`
  - `src/qiskit_metal/toolbox_metal/design_dsl.py`
  - Re-exported the generic operation registry helpers.
- Updated `tests/test_design_dsl_templates.py`.
  - Added template operation coverage for rectangle, translate, polyline,
    last-segment extraction, buffer, and `*.from_operation` primitives.
  - Added component-level operation coverage without a component template.
  - Added clear-error tests for unknown operation names and missing operation
    references.

This round did not add TransmonPocket-specific formulas or option defaults to
Python. The operation infrastructure is generic and local to component/template
expansion.

## Verification

Template tests:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl_templates.py -q
```

Result:

```text
12 passed, 5 warnings in 6.61s
```

Primitive-only regression plus template tests:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q
```

Result:

```text
81 passed, 5 warnings in 7.50s
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

Status after edits:

```text
 M src/qiskit_metal/toolbox_metal/design_dsl.py
 M src/qiskit_metal/toolbox_metal/dsl/__init__.py
 M src/qiskit_metal/toolbox_metal/dsl/builder.py
 M src/qiskit_metal/toolbox_metal/dsl/component_templates.py
 M tests/test_design_dsl_templates.py
?? src/qiskit_metal/toolbox_metal/dsl/geometry_ops.py
```

Notes:

- The exporter remains primitive-only and still instantiates only
  `NativeComponent`.
- No qlibrary `TransmonPocket` class is imported or instantiated by this path.
- Operation names are evaluated in component-local order; later operations can
  reference earlier outputs.
- `transform_group` is not implemented yet. The current generic transform
  operations can transform a list/dict source through the existing Metal draw
  helpers, but there is not yet a dedicated YAML `transform_group` operation
  wrapper. That likely belongs with the connection-pad generator round.

## Remaining Work

Recommended next round:

Add pin modes needed for TransmonPocket, especially `normal_segment`, while
preserving existing explicit tangent-point pin behavior.

Later rounds should add:

- `qcomponent.yaml`
- `base_qubit.yaml`
- static `transmon_pocket.yaml` pocket geometry
- connection-pad map-entry inheritance
- connection-pad generator support
- two-transmon example and README updates
- parity/no-qlibrary-construction tests
