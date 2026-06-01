# DSL v3 Transmon Template Review: Rounds 01-05

Date: 2026-05-11

Reviewer: asynchronous review agent

Scope:

- Checkpoint commit: `dc009420` (`Advance DSL template operations checkpoint`)
- Planning/progress docs:
  - `.codex/dsl_v3_transmon_template_final_implementation_plan.md`
  - `.codex/dsl_v3_transmon_template_progress.md`
  - `.codex/dsl_v3_transmon_template_round_01.md`
  - `.codex/dsl_v3_transmon_template_round_02.md`
  - `.codex/dsl_v3_transmon_template_round_03.md`
  - `.codex/dsl_v3_transmon_template_round_04.md`
  - `.codex/dsl_v3_transmon_template_round_05.md`
  - `.codex/dsl_v3_transmon_template_review_rounds_01_03.md`
- Related implementation and tests, read-only.

## Overall Conclusion

Rounds 01-05 made solid incremental progress: `design_dsl.py` is now a facade, the new `dsl/` package exists, typed component templates can expand into primitive IR, expression interpolation is centralized, generic geometry operations are wired into `*.from_operation` primitives, `normal_segment` pins exist, and `merge_rules.connection_pads.each_entry_extends` is implemented. The earlier rounds-01-03 P1 issues around unused `merge_rules` and silently ignored template generators have mostly been addressed.

The checkpoint is still not ready to build `qcomponent.yaml`, `base_qubit.yaml`, or `transmon_pocket.yaml` on top without cleanup. The main risks are:

- `normal_segment` pin IR/metadata diverges from the actual exported Metal pin for non-axis-aligned orientations.
- Template operation/transform validation still has holes that can silently ignore malformed YAML or leak raw Python exceptions.
- Expression arithmetic still leaks runtime exceptions instead of `DesignDslError`.

These are not P0 issues because the implementation is only at round 5 / 43% completion and TransmonPocket YAML has not landed yet. They should be fixed before claiming TransmonPocket parity.

## Findings

### P1: `normal_segment` IR pin points diverge from exported Metal pins for arbitrary rotations

Location:

- `src/qiskit_metal/toolbox_metal/dsl/builder.py:679-694`
- `src/qiskit_metal/toolbox_metal/dsl/builder.py:745-749`
- `src/qiskit_metal/toolbox_metal/dsl/builder.py:1231-1237`

`_points_from_normal_segment()` computes tangent edge points before component/pin transforms are applied. `_pin_from_spec()` then rotates/translates those precomputed edge points. During export, however, `export_ir_to_metal()` ignores `pin.points` for `input_as_norm=True` and passes `pin.normal_points` to `QComponent.add_pin(..., input_as_norm=True)`, which recomputes the edge points after the normal segment has already been transformed.

Those two paths are equivalent for the current tests at 0 and 90 degrees, but they diverge for arbitrary orientations because `QComponent.add_pin()` rounds the rotated normal direction before multiplying by `width / 2`.

Observed probe:

- Component operation segment: `[0, 0] -> [100um, 0]`
- Component rotate: `45`
- Width: `20um`
- IR/metadata `pin.points`: `[[0.0636396, 0.0777817], [0.0777817, 0.0636396]]`
- Exported `design.components["Q1"].pins["readout"].points`: approximately `[[0.0607107, 0.0807107], [0.0807107, 0.0607107]]`

Impact:

- `DesignIR`, derived metadata, and `design.metadata["dsl_chain"]` can report pin edge points that do not match the actual Metal component pins.
- Future TransmonPocket parity tests for arbitrary `orientation` will fail or, worse, compare against the wrong source.
- Any downstream consumer using IR/metadata pin points for routing, diagnostics, or validation will see stale geometry.

Recommendation:

For `normal_segment`, transform the normal segment first, then compute `pin.points` from transformed `normal_points` using the same algorithm as `QComponent.add_pin(input_as_norm=True)`. Add a regression test at a non-right-angle orientation such as 45 degrees that compares IR points, derived metadata points, and exported Metal pin points.

### P1: Malformed typed-component/template operations and template transforms are not strictly validated

Location:

- `src/qiskit_metal/toolbox_metal/dsl/template_model.py:88-96`
- `src/qiskit_metal/toolbox_metal/dsl/component_templates.py:75-78`
- `src/qiskit_metal/toolbox_metal/dsl/component_templates.py:91-93`

The generic component-level path rejects non-mapping `operations` through `_optional_mapping()`, but the typed template path converts operations with `dict(... or {})` before that validation. This creates inconsistent behavior:

- `geometry.operations: []` in a component template is silently treated as `{}`.
- `geometry.operations: false` in a component template is silently treated as `{}`.
- `geometry.operations: "bad"` raises raw `ValueError`, not `DesignDslError`.
- An instance `operations: []` on a typed component is also silently dropped.
- `geometry.transform: []` in a component template is silently ignored because `_deep_merge([], {})` returns `{}`.

Impact:

- Violates the plan's strict-validation rule for template geometry keys.
- Built-in YAML templates added in later rounds can contain shape mistakes that either disappear silently or crash with non-DSL exceptions.
- This is especially risky before `qcomponent.yaml`, because `geometry.transform` is the mechanism intended to carry inherited `pos_x`, `pos_y`, and `orientation`.

Recommendation:

Validate `geometry.operations` and `geometry.transform` in `component_template_from_mapping()`: `operations` must be a mapping when present, `transform` must be a mapping when present, and false/list/string values should fail with `DesignDslError`. In `expand_component_template()`, avoid `dict(value or {})` on unvalidated user data. Add negative tests for malformed template operations, typed-component instance operations, and template transforms.

### P2: Expression arithmetic runtime errors still leak raw Python exceptions

Location:

- `src/qiskit_metal/toolbox_metal/dsl/expression.py:164-167`

The expression evaluator applies arithmetic operators directly. Runtime arithmetic failures therefore escape as raw exceptions. For example, `${1 / 0}` raises `ZeroDivisionError` instead of `DesignDslError`.

Impact:

- Breaks the DSL error contract used by tests and callers.
- Produces diagnostics without expression context.
- Leaves one of the rounds-01-03 review findings unresolved.

Recommendation:

Wrap unary/binary operator application in `try/except Exception` and re-raise `DesignDslError` with the original expression and operator context. Add regression tests for divide-by-zero and unsupported arithmetic combinations.

### P2: Non-orthogonal `normal_segment` parity is not covered by tests

Location:

- `tests/test_design_dsl_templates.py:400-467`

The current pin tests cover an unrotated normal segment and a 90-degree component rotation. Both cases hide the edge-point divergence described above. There is no test comparing IR/derived pin data to exported `QComponent.add_pin(input_as_norm=True)` output for arbitrary angles.

Impact:

- The implementation appears qlibrary-compatible while missing a common `orientation` case for TransmonPocket.
- Future TransmonPocket tests may only catch this after more template work has been stacked on top.

Recommendation:

Add a `normal_segment` test with `rotate: 45` or `orientation: 45`, asserting:

- `pin.normal_points`
- `pin.points`
- `ir.derived["circuit"]["geometry"][component]["pins"][pin]["points"]`
- exported `design.components[component].pins[pin].points`

## Validation Performed

Commands run against checkpoint `dc009420`:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q
```

Observed result:

```text
94 passed, 5 warnings in 8.20s
```

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py
```

Observed result:

```text
PASS: native DSL chain exported to Metal
```

Additional read-only probes confirmed:

- `${1 / 0}` raises `ZeroDivisionError`, not `DesignDslError`.
- Template `geometry.operations: []` and `geometry.operations: false` are silently accepted.
- Template `geometry.operations: "bad"` raises raw `ValueError`.
- Template `geometry.transform: []` is silently ignored.
- `normal_segment` pin points differ between IR metadata and exported Metal pins at 45 degrees.

## Test And Verification Gaps

Missing or weak coverage:

- No non-right-angle `normal_segment` parity test against exported Metal pins.
- No negative tests for malformed template `geometry.operations`.
- No negative tests for malformed typed-component instance `operations`.
- No negative tests for malformed template `geometry.transform`.
- No expression runtime-error tests, such as divide-by-zero.
- No file-based component template tests through `ComponentTemplateRegistry(base_dir=...)`.
- No built-in template file tests yet, because `qcomponent.yaml`, `base_qubit.yaml`, and `transmon_pocket.yaml` are not present.
- No no-qlibrary-construction test for `TransmonPocket` yet.
- No TransmonPocket parity tests for row names, bounds, subtract flags, junction width, generated pins, netlist connection, or connection-pad defaults.
- No tests for the future generator-local context needed by `connection_pads`.

## Recommendations For Later Rounds

1. Fix the `normal_segment` IR/export mismatch before adding `transmon_pocket.yaml`; otherwise orientation parity will be built on a shaky pin model.
2. Tighten template schema validation before adding built-in YAML files. `qcomponent.yaml` will rely on inherited `geometry.transform`, so invalid transform handling should be loud now.
3. Wrap expression arithmetic failures in `DesignDslError` while the expression module is still small and isolated.
4. Add a small negative-validation test group for templates before expanding the DSL surface further.
5. When implementing generators, keep generator-local operations isolated per iteration and add tests for two pads with different `loc_W`, `loc_H`, `cpw_width`, and `cpw_gap`.
6. Add parity tests incrementally in the same order as future work: `qcomponent` transform inheritance, `base_qubit` connection-pad option merge, static TransmonPocket pocket geometry, connection-pad geometry/pin generation, netlist connection, then no-qlibrary construction.

