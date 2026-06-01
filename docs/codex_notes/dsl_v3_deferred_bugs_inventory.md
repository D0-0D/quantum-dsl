# DSL v3 Deferred Bugs And Cleanup Inventory

Date: 2026-05-11

Agent: Agent A, review/documentation only

Worktree:

`D:\BaiduSyncdisk\vsCOde\circuit\qiskit\qiskit-metal-worktrees\dyk07-main`

## Scope

This inventory de-duplicates the deferred bug, risk, cleanup, residual-risk,
remaining-gap, and test-gap items recorded across the DSL v3 Transmon template
workflow documents in `.codex/`.

Primary sources reviewed:

- `.codex/dsl_v3_transmon_template_progress.md`
- `.codex/dsl_v3_transmon_template_final_implementation_plan.md`
- `.codex/dsl_v3_transmon_template_round_01.md` through `_round_10.md`
- `.codex/dsl_v3_transmon_template_round_07_parity_fix.md`
- `.codex/dsl_v3_transmon_template_review_rounds_01_03.md`
- `.codex/dsl_v3_transmon_template_review_rounds_01_05.md`
- `.codex/dsl_v3_transmon_template_review_rounds_01_07.md`
- `.codex/dsl_v3_transmon_template_direction_check_after_round_07.md`
- `.codex/dsl_v3_transmon_template_direction_check_recheck_after_round_07.md`
- `.codex/dsl_v3_transmon_template_plan_feasibility.md`
- `.codex/dsl_v3_template_evaluation.md`
- `.codex/dsl_v3_commit_plan_evaluation.md`

Light code/test location checks were limited to:

- `src/qiskit_metal/toolbox_metal/dsl/expression.py`
- `src/qiskit_metal/toolbox_metal/dsl/builder.py`
- `src/qiskit_metal/toolbox_metal/dsl/template_registry.py`
- `tests/test_design_dsl_templates.py`
- `tests/test_design_dsl_transmon_pocket.py`

No core code was modified.

## Summary

Total current deferred items: 14

Recommended Agent B priority this round:

1. Fix DSL error-contract bugs in expression arithmetic and numeric parsing.
2. Add focused regression coverage for file-based component-template lookup.
3. Optionally add a small regression/documentation test for `build_ir()` design
   variable-context side effects if time remains.

Do not prioritize broad Hamiltonian/Circuit semantics, renderer strategy,
template package/versioning, or large `builder.py` refactors in a short bug-fix
round.

## Inventory

### 1. Expression arithmetic runtime failures leak raw Python exceptions

Classification: true bug

Severity: P2 / medium

Source documents:

- `.codex/dsl_v3_transmon_template_review_rounds_01_03.md`
- `.codex/dsl_v3_transmon_template_review_rounds_01_05.md`
- `.codex/dsl_v3_transmon_template_direction_check_after_round_07.md`
- `.codex/dsl_v3_transmon_template_review_rounds_01_07.md`
- `.codex/dsl_v3_transmon_template_round_08.md`
- `.codex/dsl_v3_transmon_template_round_09.md`
- `.codex/dsl_v3_transmon_template_round_10.md`
- `.codex/dsl_v3_transmon_template_progress.md`

Current location:

- `src/qiskit_metal/toolbox_metal/dsl/expression.py`, around `_eval_ast()`
  unary and binary operator application.

Impact:

Expressions such as `${1 / 0}` can raise `ZeroDivisionError` instead of
`DesignDslError`. This breaks the DSL error contract and gives template authors
diagnostics without expression context.

Suggested fix:

Wrap `_UNARY_OPS[...]` and `_BIN_OPS[...]` calls in `try/except Exception` and
re-raise `DesignDslError` with the expression and operator context.

Recommended tests:

- Negative expression test for `${1 / 0}`.
- A second runtime arithmetic failure if one is easy to produce.
- Assert the exception type is `DesignDslError` and the message includes the
  expression.

Suitable for Agent B this round: yes. This is the top bug-fix candidate.

### 2. Invalid numeric fields leak `ValueError`, and booleans can be accepted as numbers

Classification: true bug

Severity: P2 / medium

Source documents:

- `.codex/dsl_v3_transmon_template_review_rounds_01_07.md`
- `.codex/dsl_v3_transmon_template_round_08.md`
- `.codex/dsl_v3_transmon_template_round_09.md`
- `.codex/dsl_v3_transmon_template_round_10.md`
- `.codex/dsl_v3_transmon_template_progress.md`

Current locations:

- `src/qiskit_metal/toolbox_metal/dsl/builder.py`, around `_parse_number()`,
  `_parse_angle()`, and `_layer()`.

Impact:

Malformed YAML can escape as raw `ValueError`, for example invalid
`orientation` or `layer` values. Boolean values can also pass through numeric
paths, for example a path `width: true` becoming `1.0`. That weakens strict
validation and can silently create valid-looking but unintended geometry.

Suggested fix:

Reject booleans explicitly in numeric helpers. Wrap string and numeric
conversion failures in `DesignDslError` with owner/context. Prefer a single
small helper for numeric conversion so angle/layer/width behavior is consistent.

Recommended tests:

- Invalid `orientation: nope` on a typed component.
- Invalid primitive `layer: nope`.
- Boolean numeric fields such as `width: true`, `layer: true`, and possibly
  `orientation: true`.
- Assert `DesignDslError`, not `ValueError`.

Suitable for Agent B this round: yes. This should be fixed with item 1.

### 3. `build_ir()` instantiates the selected design class to gather variables

Classification: architecture cleanup / residual behavior risk

Severity: P2 / medium

Source documents:

- `.codex/dsl_v3_transmon_template_review_rounds_01_07.md`
- `.codex/dsl_v3_transmon_template_round_08.md`
- `.codex/dsl_v3_transmon_template_round_09.md`
- `.codex/dsl_v3_transmon_template_round_10.md`
- `.codex/dsl_v3_transmon_template_progress.md`

Current locations:

- `src/qiskit_metal/toolbox_metal/dsl/builder.py`, around
  `_design_variable_context()` and `build_ir()`.

Impact:

`build_ir()` now constructs the selected design class so template parsing can
see defaults such as `cpw_width` and `cpw_gap`. `build_design()` then constructs
the design again for export. Custom registered design classes may therefore run
constructor side effects during IR-only builds, or pay unexpected construction
cost even with renderers disabled.

Suggested fix:

Either document this behavior as intentional and stable, or refactor variable
lookup behind a smaller API that can read defaults without full design
construction where possible.

Recommended tests:

- Register a test design class that counts constructor calls.
- Assert the current behavior explicitly for `build_ir()` and `build_design()`,
  then decide whether the expected count should remain or change.

Suitable for Agent B this round: partial. A small regression/documentation test
is suitable; a refactor is lower priority than the error-contract bugs.

### 4. File-based component-template lookup lacks dedicated regression coverage

Classification: test gap

Severity: P2 / low-medium

Source documents:

- `.codex/dsl_v3_transmon_template_review_rounds_01_03.md`
- `.codex/dsl_v3_transmon_template_review_rounds_01_05.md`
- `.codex/dsl_v3_transmon_template_review_rounds_01_07.md`
- `.codex/dsl_v3_template_evaluation.md`

Current locations:

- `src/qiskit_metal/toolbox_metal/dsl/template_registry.py`
- `tests/test_design_dsl_templates.py`

Impact:

Inline and built-in component templates are well covered, but standalone
component-template YAML files resolved through `ComponentTemplateRegistry`
`base_dir` are lightly exercised. Regressions in local template file lookup,
id mismatch handling, duplicate-key handling, or file parse errors could slip
through.

Suggested fix:

Add focused tests using `tmp_path` and a design YAML file whose component
`type` points to a sibling component-template YAML file.

Recommended tests:

- Successful standalone template file lookup.
- Template file declaring the wrong `id`.
- Duplicate key or malformed YAML in a template file.
- Optional: template inheritance across two local files.

Suitable for Agent B this round: yes, especially after items 1 and 2.

### 5. Global typed full-string interpolation behavior is still under-decided and under-tested

Classification: compatibility risk / test gap

Severity: P2 / low-medium

Source documents:

- `.codex/dsl_v3_transmon_template_review_rounds_01_03.md`
- `.codex/dsl_v3_transmon_template_round_05.md`
- `.codex/dsl_v3_template_evaluation.md`
- `.codex/dsl_v3_commit_plan_evaluation.md`

Current locations:

- `src/qiskit_metal/toolbox_metal/dsl/expression.py`
- `src/qiskit_metal/toolbox_metal/dsl/builder.py`, `_walk_substitute()` call
  sites.

Impact:

Full-string interpolation can preserve non-string values across broad
pre-template contexts such as `circuit`, `hamiltonian`, `netlist`,
`geometry.design`, and transforms. That is useful for numeric template work but
can change metadata shape or downstream behavior for older primitive-native DSL
files that expected string-like substitution.

Suggested fix:

Decide and document whether typed interpolation is intended globally or only in
template/geometry numeric contexts. If global typed interpolation remains the
intended behavior, keep it but add compatibility tests.

Recommended tests:

- Representative interpolation in `circuit`, `hamiltonian`, `netlist`,
  `geometry.design.variables`, chip settings, and metadata.
- Cases where interpolated values are numeric, boolean, and string-like.

Suitable for Agent B this round: maybe. Good for a small test/documentation
slice, but not as urgent as items 1 and 2.

### 6. `builder.py` remains large and mixes many DSL responsibilities

Classification: architecture cleanup

Severity: P2 / low

Source documents:

- `.codex/dsl_v3_transmon_template_direction_check_after_round_07.md`
- `.codex/dsl_v3_transmon_template_final_implementation_plan.md`
- `.codex/dsl_v3_commit_plan_evaluation.md`

Current location:

- `src/qiskit_metal/toolbox_metal/dsl/builder.py`

Impact:

The public `design_dsl.py` facade split is complete, but `dsl/builder.py` still
owns loading, schema checks, substitution, primitive parsing, pin parsing,
netlist handling, design instantiation, export, and orchestration. This raises
maintenance cost as future component templates and DSL semantics are added.

Suggested fix:

After bug-fix stabilization, split by responsibility, likely around schema,
primitive parsing, pin parsing, netlist, derived metadata, export, and builder
orchestration.

Recommended tests:

- No new behavior tests required for the refactor beyond running the current DSL
  suites.
- Add focused tests only if extraction changes public error paths.

Suitable for Agent B this round: no, unless Agent B is explicitly assigned a
refactor round.

### 7. Full Hamiltonian/Circuit semantic propagation remains future work

Classification: future enhancement

Severity: P2 / medium, but not a Transmon template blocker

Source documents:

- `.codex/dsl_v3_transmon_template_direction_check_after_round_07.md`
- `.codex/dsl_v3_template_evaluation.md`
- `.codex/dsl_v3_commit_plan_evaluation.md`
- `.codex/dsl_v3_transmon_template_plan_feasibility.md`

Impact:

Current v3 supports structural Hamiltonian/Circuit/Netlist/Geometry sections,
interpolation, primitive export, and generic derived geometry metadata. It does
not yet provide physics-aware Hamiltonian or circuit derivation, template-
published circuit defaults, Hamiltonian defaults, junction symbols, capacitance
hints, coupling metadata, or model-aware upward propagation.

Suggested fix:

Design a staged metadata-first contribution mechanism for component templates
before attempting solver-level semantics. Define how template defaults, user
overrides, derived geometry, and Hamiltonian/circuit model data interact.

Recommended tests:

- Template-published circuit defaults.
- Template-published Hamiltonian defaults.
- User override precedence.
- Derived geometry feeding named circuit/Hamiltonian metadata in a controlled,
  non-solver-specific way.

Suitable for Agent B this round: no. This is a later design/feature slice.

### 8. Circuit/Hamiltonian/geometry/netlist consistency and conflict precedence are undefined

Classification: future enhancement / architecture risk

Severity: medium

Source documents:

- `.codex/dsl_v3_commit_plan_evaluation.md`
- `.codex/dsl_v3_template_evaluation.md`

Impact:

The DSL currently treats `circuit` and `hamiltonian` mostly as arbitrary
mappings. There is no optional validation that Hamiltonian subsystem names match
circuit components, that circuit/netlist/geometry component names align, or
that conflicting values in `circuit` and `geometry.components.*.options` are
resolved by a documented precedence model.

Suggested fix:

Add optional consistency validation or a documented strict mode. Define
precedence before allowing the same physical parameter to be set from both
circuit and geometry/component options.

Recommended tests:

- Matching and mismatching circuit/geometry component names.
- Hamiltonian subsystem names that do and do not correspond to components.
- Conflicting `circuit.Q1.pad_width` versus
  `geometry.components.Q1.options.pad_width`.

Suitable for Agent B this round: no. Needs a schema/design decision first.

### 9. Netlist roles, ports, coupling metadata, and endpoint reuse policy remain future schema work

Classification: future enhancement

Severity: low-medium

Source documents:

- `.codex/dsl_v3_template_evaluation.md`
- `.codex/dsl_v3_commit_plan_evaluation.md`

Impact:

`netlist.connections` intentionally accepts only `{from, to}` today. That keeps
the current v3 surface strict, but future circuit/Hamiltonian semantics will
need roles/types such as readout, drive, coupler, capacitance hints, or coupling
metadata. Endpoint reuse is also globally rejected, which is acceptable now but
may be too strict for future multi-pin or multi-net modeling.

Suggested fix:

Treat roles and endpoint reuse as explicit schema evolution. Add only after the
template resolver and TransmonPocket parity are stable.

Recommended tests:

- Current strict rejection of extra netlist keys remains until schema evolves.
- Future role metadata acceptance/rejection by schema version.
- Endpoint reuse cases once a policy exists.

Suitable for Agent B this round: no.

### 10. Metadata/provenance model does not yet separate raw source, resolved state, and export results

Classification: architecture cleanup / future enhancement

Severity: medium

Source documents:

- `.codex/dsl_v3_template_evaluation.md`
- `.codex/dsl_v3_commit_plan_evaluation.md`
- `.codex/dsl_v3_transmon_template_plan_feasibility.md`

Impact:

`design.metadata["dsl_chain"]` records useful resolved data and derived output,
but future debugging and round-trip editing need clearer separation between raw
source, source path/checksum, resolved document, inherited defaults, user
overrides, generated primitive/pin IR, derived geometry, and export results such
as net IDs. Current export also enriches derived netlist entries with `net_id`,
so pre-export and post-export IR-derived metadata can differ.

Suggested fix:

Define a metadata contract with separate raw/resolved/generated/derived/export
sections and minimal provenance categories such as template default, design
default, instance override, and API override.

Recommended tests:

- Resolved options provenance for inherited template defaults and user
  overrides.
- Raw source path/checksum or equivalent debug metadata.
- Export net IDs stored in a clearly named export-result section.

Suitable for Agent B this round: no, except for a very small documentation-only
decision.

### 11. First-class template package/discovery/versioning is still minimal

Classification: future enhancement

Severity: low-medium

Source documents:

- `.codex/dsl_v3_template_evaluation.md`
- `.codex/dsl_v3_commit_plan_evaluation.md`
- `.codex/dsl_v3_transmon_template_plan_feasibility.md`

Impact:

The current registry supports inline templates, built-ins, and local file
lookup. That is enough for the TransmonPocket milestone, but future YAML
qlibrary equivalents will need predictable import names, versioning, dependency
resolution, and possibly external template libraries.

Suggested fix:

Do not add a full package manager yet. First add regression coverage for local
file templates, then design a small versioned discovery mechanism when more
templates exist.

Recommended tests:

- Local file lookup now.
- Future version mismatch and missing dependency diagnostics once package
  metadata is introduced.

Suitable for Agent B this round: no, beyond item 4's local file tests.

### 12. List/primitive/pin override granularity remains fragile for future templates

Classification: architecture cleanup / future enhancement

Severity: low-medium

Source documents:

- `.codex/dsl_v3_template_evaluation.md`
- `.codex/dsl_v3_commit_plan_evaluation.md`

Impact:

Map-entry inheritance for `connection_pads` has been implemented, but list
fields generally still replace whole lists. Future templates that need to
override one primitive or pin without repeating all primitives/pins may become
verbose or fragile.

Suggested fix:

For override-heavy structures, consider representing primitives, pins, ports,
and couplers as maps keyed by stable names during template expansion, then lower
to ordered lists after resolution.

Recommended tests:

- Override one primitive from a parent template without repeating siblings.
- Override one pin from a parent template without repeating siblings.
- Preserve deterministic ordering after map-to-list lowering.

Suitable for Agent B this round: no.

### 13. Renderer and qgeometry table compatibility strategy is still intentionally deferred

Classification: future enhancement / architecture risk

Severity: low-medium

Source documents:

- `.codex/dsl_v3_transmon_template_final_implementation_plan.md`
- `.codex/dsl_v3_transmon_template_plan_feasibility.md`
- `.codex/dsl_v3_commit_plan_evaluation.md`
- `.codex/dsl_v3_template_evaluation.md`
- `.codex/dsl_v3_transmon_template_direction_check_after_round_07.md`

Impact:

The current exporter intentionally bypasses `QComponent.add_qgeometry()` renderer
default injection and writes directly to `design.qgeometry.add_qgeometry()`.
Existing tests intentionally assert renderer defaults are not injected. That is
correct for this phase, but future templates may need renderer-specific options
or qgeometry tables beyond `poly`, `path`, and `junction`.

Suggested fix:

Keep direct qgeometry export for now. Later, define how table usage and
renderer-specific options are represented in YAML templates and how
`NativeComponent.component_metadata` advertises them.

Recommended tests:

- Renderer-focused smoke tests once renderer options are added.
- Metadata/table-advertisement tests for any future qgeometry tables.
- Regression that current TransmonPocket migration does not accidentally inject
  renderer defaults unless the schema explicitly changes.

Suitable for Agent B this round: no.

### 14. Study-style comments remain in the active development DSL builder path

Classification: cleanup

Severity: low

Source documents:

- `.codex/dsl_v3_template_evaluation.md`
- `.codex/dsl_v3_transmon_template_round_01.md`
- `.codex/dsl_v3_transmon_template_final_implementation_plan.md`

Current location:

- `src/qiskit_metal/toolbox_metal/dsl/builder.py`, near `build_ir()`.

Impact:

The round-01 split preserved earlier Chinese study comments by carrying them
from `design_dsl.py` into `dsl/builder.py`. This may be intentional local study
context, but the active development worktree now contains reading-note style
comments in core implementation code rather than in the study copy or docs.

Suggested fix:

Decide whether these comments should stay, be converted into concise production
comments, or move to study notes. Do not change them as part of an unrelated bug
fix.

Recommended tests:

- None. This is a style/ownership cleanup only.

Suitable for Agent B this round: no.

## Items Explicitly Excluded Because They Were Fixed

These earlier findings are not listed as current deferred work because later
round documents and tests record them as fixed or validated:

- `merge_rules.connection_pads.each_entry_extends` collected but unused.
- Template `geometry.generators` accepted and silently ignored before generator
  support existed.
- Falsey typed-component `metadata` values silently accepted.
- Non-right-angle `normal_segment` IR/export pin mismatch.
- Malformed template `geometry.operations`, `geometry.transform`, and typed
  component `operations` not strictly validated.
- Generated TransmonPocket connection-pad pin `gap` using `cpw_gap` instead of
  qlibrary's `0.6 * cpw_width` default behavior.
- Built-in TransmonPocket default `cpw_width` and `cpw_gap` requiring root
  `vars` instead of resolving through selected Metal design variables.
- Missing two-transmon YAML example, demo runner, README update, focused
  TransmonPocket parity tests, and no-qlibrary-construction coverage.

