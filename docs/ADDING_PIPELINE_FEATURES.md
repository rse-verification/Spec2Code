# Adding Pipeline Features and Config Fields

Use this guide when introducing new behavior that spans config parsing, runtime setup, and execution.

## Main Modules

- Config validation: `src/spec2code/pipeline_modules/config_loader.py`
- Runtime setup: `src/spec2code/pipeline_modules/runtime.py`
- Orchestration: `src/spec2code/core/runner.py`
- Per-run execution: `src/spec2code/core/pipeline_executor.py`
- Artifact handling/critics call: `src/spec2code/core/artifacts.py`

## Add New Config Fields

1. Validate types in `config_loader.py` using `_require_*` / `_optional_*` helpers.
2. Extend `PreparedConfig` with the new field.
3. Thread the field into runtime and execution paths.
4. Add/update tests in `tests/unit/pipeline_modules/test_config_loader*.py`.

## Add New Runtime Behavior

1. Keep orchestration in `runner.py` minimal.
2. Put execution behavior in `pipeline_executor.py` or `artifacts.py`.
3. Keep output schema changes explicit and documented.

## Output and Path Conventions

- Runtime outputs use `SPEC2CODE_OUTPUT_ROOT` (default `../spec2code_output`).
- Case-study assets use `SPEC2CODE_CASE_STUDIES_ROOT` (default `../spec2code_case_studies`).

Preserve backward compatibility when changing path resolution behavior.

## Validation

- Add targeted unit tests for parser/runtime behavior.
- Run at least one CLI pipeline and confirm output artifacts/report generation.
