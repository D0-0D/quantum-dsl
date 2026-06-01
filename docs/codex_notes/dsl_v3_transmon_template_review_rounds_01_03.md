# DSL v3 Transmon Template Review: Rounds 01-03

Date: 2026-05-11

Reviewer: asynchronous review agent

Scope:

- Checkpoint commit: `a8aeaf41` (`Add DSL template infrastructure checkpoint`)
- Planning/progress docs:
  - `.codex/dsl_v3_transmon_template_final_implementation_plan.md`
  - `.codex/dsl_v3_transmon_template_progress.md`
  - `.codex/dsl_v3_transmon_template_round_01.md`
  - `.codex/dsl_v3_transmon_template_round_02.md`
  - `.codex/dsl_v3_transmon_template_round_03.md`
- Related implementation/tests at the checkpoint only. During review, the working tree already contained later, uncommitted edits such as `dsl/geometry_ops.py`; those are intentionally excluded from findings unless noted as review context.

## Overall Conclusion

Rounds 01-03 successfully establish the public facade, basic template registry/model, primitive-only template expansion, and a constrained expression evaluator. Existing primitive DSL tests and the new template tests pass at the checkpoint.

However, there are real correctness and architecture risks before later rounds build on this foundation:

- Template `merge_rules` are parsed and accumulated but never applied, so the planned `BaseQubit` `connection_pads` inheritance cannot work without reworking the option validation/merge path.
- Template schema accepts `geometry.operations` and `geometry.generators`, but round-03 expansion drops them silently. That makes invalid operations/generators appear valid and can hide authoring errors until much later.
- Expression evaluation leaks raw Python exceptions for some invalid but syntactically allowed expressions.
- Typed component metadata validation regressed for falsey non-mapping values.

These are not P0 failures for rounds 01-03 because the claimed completion is only 26%, but they should be fixed before YAML `base_qubit`/`transmon_pocket` templates are introduced.

## Findings

### P1: `merge_rules` are collected but never applied, blocking `connection_pads` inheritance

Location:

- `src/qiskit_metal/toolbox_metal/dsl/component_templates.py:44-53`
- `src/qiskit_metal/toolbox_metal/dsl/component_templates.py:116-124`

`expand_component_template()` accumulates `merge_rules` from the inheritance chain, but the value is never used. Option validation still recurses strictly against the raw default option tree before any map-entry inheritance is possible. With the planned `base_qubit` rule:

```yaml
merge_rules:
  connection_pads:
    each_entry_extends: _default_connection_pads
```

an instance override such as `connection_pads.readout.loc_W: 1` is rejected because `readout` is not already a key in default `connection_pads`. That prevents the intended `BaseQubit._set_options_connection_pads()` replacement path.

Impact:

- Future `base_qubit.yaml` cannot support arbitrary pad names like `readout`, `drive`, or multiple pads.
- `transmon_pocket` connection-pad generation will either fail at option validation or require weakening validation in an ad hoc later change.

Recommendation:

Implement merge-rule handling before nested option validation finalizes. For `each_entry_extends`, validate each map entry against the named default schema, merge missing fields into every entry, then remove `_default_connection_pads` from runtime resolved options as required by the plan.

### P1: Accepted `operations`/`generators` template fields are silently ignored at round 03

Location:

- `src/qiskit_metal/toolbox_metal/dsl/template_model.py:23-29`
- `src/qiskit_metal/toolbox_metal/dsl/component_templates.py:74-83`
- `src/qiskit_metal/toolbox_metal/dsl/builder.py:821-824`

The template model allows `geometry.operations` and `geometry.generators`, but the expansion path only carries `primitives`, `pins`, and `transform` into the component spec. Unknown or invalid operation/generator bodies therefore pass template validation and are discarded.

Impact:

- Violates the strict-validation rule in the plan for unknown operations, operation references, and generator variables.
- Makes future YAML recipes look accepted while producing missing geometry/pins.
- Creates a risky compatibility trap: invalid templates written during rounds 02-03 could later change behavior when operation support lands.

Recommendation:

Until operations/generators are implemented, either reject these keys explicitly with a "not supported yet" error or carry them into the component spec and validate them as unsupported. Once implemented, add tests proving invalid operation names and invalid generator shapes fail, rather than being ignored.

### P2: Expression evaluator leaks raw Python exceptions for arithmetic runtime errors

Location:

- `src/qiskit_metal/toolbox_metal/dsl/expression.py:164-167`

The AST evaluator calls `operator.truediv` and other arithmetic handlers directly. Expressions such as `${1 / 0}` raise `ZeroDivisionError`, not `DesignDslError`. The same pattern can expose other runtime exceptions from arithmetic on values that pass `_coerce_number()`.

Impact:

- Breaks the API contract that DSL parsing/export failures are reported as `DesignDslError`.
- Produces less useful diagnostics with no interpolation context.
- Can fail tests or callers that correctly catch `DesignDslError`.

Recommendation:

Wrap arithmetic operation application in `try/except Exception` and re-raise `DesignDslError` with the original expression and operator context. Add regression tests for divide-by-zero and unsupported arithmetic cases.

### P2: Typed component metadata silently accepts falsey non-mapping values

Location:

- `src/qiskit_metal/toolbox_metal/dsl/component_templates.py:55-59`

For typed components, `instance_metadata` is only type-checked when truthy:

```python
if instance_metadata and not isinstance(instance_metadata, Mapping):
```

Values such as `metadata: false`, `metadata: []`, or `metadata: ''` are silently treated as `{}` because they are falsey. Primitive-only components still reject these through `_optional_mapping()` later, so this is a behavioral inconsistency introduced by the template path.

Impact:

- Weakens strict validation specifically for typed components.
- User typos can be silently dropped from exported metadata.

Recommendation:

Check key presence rather than truthiness, e.g. if `"metadata" in component_spec and not isinstance(instance_metadata, Mapping)`. Add typed-component coverage mirroring `tests/test_design_dsl.py::test_rejects_non_mapping_component_metadata`.

### P2: Full-string interpolation now preserves non-string types in broad pre-template contexts

Location:

- `src/qiskit_metal/toolbox_metal/dsl/expression.py:77-94`
- `src/qiskit_metal/toolbox_metal/dsl/builder.py:997-1024`

Round 03 changed substitution from string-only replacement to typed full-string interpolation for all `_walk_substitute()` calls, including `circuit`, `hamiltonian`, `netlist`, `geometry.design`, and `geometry.transforms`. This is intentional for template-local arithmetic, but it is wider than the original primitive-only behavior and not covered by compatibility tests.

Example risk:

- A field that previously remained the string `"1"` after `${vars.layer}` can now become integer `1`.
- A field that previously remained `"False"` can now become boolean `False` if a user interpolates a YAML boolean.

Impact:

- May change metadata shape or downstream behavior for existing v3 files that rely on string-preserving interpolation outside numeric geometry fields.
- The effect is likely manageable, but it is a behavior change in a round described as preserving primitive-only behavior.

Recommendation:

Decide and document whether typed interpolation is allowed globally or only in template/geometry numeric contexts. If global typed interpolation is intended, add explicit regression tests for representative `circuit`, `hamiltonian`, `netlist`, design variables, chip settings, and metadata values.

## Test And Validation Gaps

Verified commands at checkpoint scope:

- `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q`
  - Result observed: `77 passed, 4 warnings`
- `C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py`
  - Result observed: `PASS: native DSL chain exported to Metal`

Missing or weak coverage:

- No tests for `merge_rules`, especially `connection_pads.each_entry_extends`.
- No tests asserting `geometry.operations` or `geometry.generators` are rejected or executed; at round 03 they are accepted by schema but ignored.
- No expression tests for runtime arithmetic failures such as divide-by-zero.
- No typed-component tests for invalid falsey `metadata` values.
- No tests for file-based component templates loaded by `ComponentTemplateRegistry`.
- No tests for built-in template ids currently registered but unavailable (`qcomponent`, `base_qubit`, `transmon_pocket`) beyond unknown-type behavior.
- No no-qlibrary-construction test yet. This is acceptable for round 03 but should be added before claiming TransmonPocket replacement parity.
- No TransmonPocket parity tests yet for geometry names, bounds, subtract flags, junction width, pins, netlist connection, or connection-pad defaults. This is expected from the progress checklist but remains the main future validation burden.

## Recommendations For Later Rounds

1. Fix the `merge_rules` semantics before adding `base_qubit.yaml`; do not defer this until after `transmon_pocket.yaml`, because the validation order affects every connection-pad override.
2. Treat accepted-but-unimplemented schema keys as errors until their implementation lands. This keeps template authoring failures loud.
3. Add a small "negative template schema" test group before expanding the DSL surface further: invalid metadata, invalid operations, invalid generators, invalid expression runtime errors, and file-template schema mismatch.
4. Keep operation/generator support generic, but wire it through `ComponentTemplateExpansion` explicitly so the component parser has one clear lowering point from template data to `PrimitiveIR`/`PinIR`.
5. Add parity tests incrementally as soon as each TransmonPocket slice appears: static pocket rows first, then normal-segment pins, then connection-pad generators and netlist connections.
6. Update the progress file carefully as later rounds continue. During this review, the working tree already contained later uncommitted geometry-operation work, so future reviewers should pin their review to the intended commit or explicitly separate concurrent worker changes.
