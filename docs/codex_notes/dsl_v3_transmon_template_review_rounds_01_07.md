# DSL v3 Transmon Template Review: Rounds 01-07

Date: 2026-05-11

Reviewer: asynchronous review agent

Scope:

- Checkpoint commit: `9879755d` (`Add YAML TransmonPocket template checkpoint`)
- Planning/progress docs:
  - `.codex/dsl_v3_transmon_template_final_implementation_plan.md`
  - `.codex/dsl_v3_transmon_template_progress.md`
  - `.codex/dsl_v3_transmon_template_round_01.md` through `_round_07.md`
  - `.codex/dsl_v3_transmon_template_round_07_parity_fix.md`
  - `.codex/dsl_v3_transmon_template_direction_check_after_round_07.md`
  - earlier review docs where relevant
- Related implementation and tests, read-only except for writing this review document.

## Overall Conclusion

Rounds 01-07 are directionally correct and the checkpoint is a credible YAML-native `TransmonPocket` milestone.

The implementation now follows the intended path:

```text
YAML type/options
-> built-in YAML templates
-> generic template/merge/generator/operation expansion
-> ComponentIR/PrimitiveIR/PinIR
-> NativeComponent/QComponent export
-> qgeometry/pins/net_info
```

I did not find a P0/P1 issue in the current checkpoint. The two P1 parity gaps identified after round 07 are fixed:

- generated connection-pad pin `gap` now matches qlibrary `add_pin(..., gap=None)` behavior by defaulting to `0.6 * width`;
- symbolic `cpw_width` / `cpw_gap` defaults now resolve through selected Metal design variables, so `connection_pads: {readout: {}}` builds without root `vars`.

The implementation still has P2 cleanup risks around error-contract consistency, validation strictness for numeric fields, and the new design-variable context mechanism instantiating the selected design during `build_ir()`. These should be addressed before the DSL surface grows much further, but they do not invalidate the round-07 checkpoint.

## Findings

### P2: Expression arithmetic runtime failures still leak raw Python exceptions

Location:

- `src/qiskit_metal/toolbox_metal/dsl/expression.py:160-167`

The expression evaluator directly applies unary/binary operators after numeric coercion. Runtime arithmetic errors are not wrapped in `DesignDslError`. For example, a template expression such as:

```yaml
center: ["${1 / 0}", 0mm]
```

raises:

```text
ZeroDivisionError: float division by zero
```

instead of a DSL-scoped error with expression context.

Impact:

- Violates the strict DSL error contract used elsewhere in the builder.
- Produces less actionable diagnostics for template authors.
- Keeps one earlier review P2 item unresolved.

Recommendation:

Wrap `_UNARY_OPS[...]` and `_BIN_OPS[...]` calls in `try/except Exception` and re-raise `DesignDslError` with the original expression and operator context. Add regression tests for divide-by-zero and any unsupported arithmetic combinations that currently leak raw exceptions.

### P2: Invalid numeric fields can leak `ValueError`, and boolean numeric values can be accepted

Location:

- `src/qiskit_metal/toolbox_metal/dsl/builder.py:424-428`
- `src/qiskit_metal/toolbox_metal/dsl/builder.py:452-462`
- `src/qiskit_metal/toolbox_metal/dsl/builder.py:490-495`

Several parser helpers still delegate conversion directly to `float()` / `int()` or accept Python booleans through `isinstance(bool, int)`.

Observed probes:

- `options: {orientation: nope}` on `type: transmon_pocket` raises raw `ValueError: could not convert string to float: 'nope'`.
- `layer: nope` on a primitive raises raw `ValueError`.
- `width: true` on a path primitive is accepted as `1.0`.

Impact:

- Malformed user YAML can escape as non-DSL exceptions.
- Boolean-as-number acceptance weakens strict validation and can silently create tiny but valid-looking geometry widths/layers.

Recommendation:

Update numeric helpers to reject booleans and wrap conversion failures in `DesignDslError`. Add negative tests for invalid `orientation`, invalid `layer`, and boolean numeric fields.

### P2: `build_ir()` now instantiates the selected design class to read default variables

Location:

- `src/qiskit_metal/toolbox_metal/dsl/builder.py:1233-1251`
- `src/qiskit_metal/toolbox_metal/dsl/builder.py:1344-1358`

The round-07 parity fix adds `_design_variable_context()`, which instantiates the selected `QDesign` class during `build_ir()` so template parsing can see defaults such as `cpw_width` and `cpw_gap`. `build_design()` later instantiates the design again for export.

This is generic and does not reintroduce Python `TransmonPocket`, but it does make IR construction less pure than before.

Impact:

- Custom registered design classes can run constructor side effects even when callers only request IR.
- Constructors may be expensive or rely on runtime resources even with `enable_renderers=False`.
- The test suite does not currently exercise this behavior with a side-effecting custom design.

Recommendation:

Either document this as intentional, or isolate it behind a smaller variable-source API in a later refactor. Add a regression test using a registered design class that counts constructor calls, so the behavior is explicit and future changes do not surprise callers.

## Positive Checks

No qlibrary `TransmonPocket` construction path was found in the DSL implementation. The only qlibrary `TransmonPocket` usages are tests/probes for parity.

The facade split is intact:

- `src/qiskit_metal/toolbox_metal/design_dsl.py` is a compatibility facade.
- public DSL symbols are re-exported from `src/qiskit_metal/toolbox_metal/dsl/__init__.py`.

The built-in YAML templates hold the transmon-specific defaults and formulas:

- `src/qiskit_metal/toolbox_metal/dsl_templates/core/qcomponent.yaml`
- `src/qiskit_metal/toolbox_metal/dsl_templates/core/base_qubit.yaml`
- `src/qiskit_metal/toolbox_metal/dsl_templates/qubits/transmon_pocket.yaml`

No component-specific Python branch such as `if type == "transmon_pocket"` was found in the build path.

## Validation Performed

Command:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q
```

Result:

```text
106 passed, 5 warnings in 11.49s
```

Command:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py
```

Result:

```text
PASS: native DSL chain exported to Metal
```

Additional read-only probes:

- Compared YAML `type: transmon_pocket` against qlibrary `TransmonPocket` for `orientation` values `0`, `30`, `45`, `90`, `123.4`, `180`, and `270`, with all four `loc_W`/`loc_H` combinations. Core geometry names, bounds, area, length, and generated pin points/gap matched within tolerance.
- Verified `geometry.design.variables` override design defaults, and root `vars` override `geometry.design.variables`, for default `connection_pads`.
- Verified `connection_pads: {readout: {}}` builds without root `vars`, using default `cpw_width=10um` and `cpw_gap=6um`.
- Verified `${1 / 0}` currently raises `ZeroDivisionError`.
- Verified invalid `orientation` and `layer` currently raise raw `ValueError`.
- Verified `width: true` is currently accepted as `1.0`.

## Test And Verification Gaps

Missing or weak coverage:

- No divide-by-zero or arithmetic runtime-error tests for `DesignDslError`.
- No invalid `orientation` / invalid `layer` / boolean numeric field tests.
- No explicit test documenting that `build_ir()` instantiates the selected design class to gather variables.
- No file-template test through `ComponentTemplateRegistry(base_dir=...)` for standalone component-template YAML files. Inline and built-in templates are covered, but path-based template lookup remains lightly exercised.
- No dedicated `tests/test_design_dsl_transmon_pocket.py`; the template test file is now large and mixes generic template infrastructure with transmon parity.
- No new two-transmon example or README update yet; these remain planned next-round work.

## Recommendations For Later Rounds

1. Fix the P2 error-contract issues while the expression/numeric parser surface is still manageable.
2. Add a side-effecting registered-design test for `build_ir()` variable-context behavior, then decide whether to keep or refactor that mechanism.
3. Split the large template test file into generic template tests and TransmonPocket parity tests before adding more component templates.
4. Add the planned two-transmon YAML example and README update next; the implementation is ready enough for user-facing documentation.
5. Keep future qlibrary-template migrations under the same rule that worked here: component-specific defaults/formulas in YAML, generic operations in Python, primitive-only export.

