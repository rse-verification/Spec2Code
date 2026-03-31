# Extending spec2code

This guide explains how to add new capabilities to `spec2code` safely and predictably.

## 1) Add a New LLM Provider Type

Provider implementations live in:

- `src/spec2code/pipeline_modules/llms.py`

Current types are:

- `BedrockProvider`
- `OpenAICompatibleProvider`
- `OllamaProvider`

To add another provider:

1. Implement a class with `generate(model_id, prompt, temperature, max_tokens)` returning `_SimpleLLMResponse`.
2. Register the type in `_build_provider(...)`.
3. Add provider config schema keys to `config/llm_providers.yaml`.
4. Add at least one sample `models:` entry using the new provider.

## 2) Add a New Model (No Code Changes)

Most model additions only require YAML updates.

Edit `config/llm_providers.yaml`:

```yaml
models:
  my-new-model:
    provider: openai_default
    model: gpt-4o-mini
    max_tokens: 2048
```

Then select it in your run config JSON:

```json
"llms_used": ["my-new-model"]
```

## 3) Add a New Critic

Critic implementations live in:

- `src/spec2code/pipeline_modules/critics/`

Steps:

1. Implement a class compatible with `Critic` in `critics_interface.py`.
2. Add construction logic in `build_critics_from_names(...)` and optionally `build_default_critics(...)` in `critics_runner.py`.
3. Use the critic name in JSON config `critics` list.

Example critics already in project:

- compile: `critics_compile.py`
- Frama-C WP: `critics_framac_wp.py`
- MISRA: `critics_cppcheck_misra.py`
- non-functional checks: `critics_vernfr.py`

## 4) Add Prompt Templates

Prompt loading is in:

- `src/spec2code/pipeline_modules/experiment_parameters.py`

Current prompt file location:

- `prompts/zero-shot.txt`

To add a new template:

1. Create a new prompt file in `prompts/`.
2. Register it in `load_prompt_templates()`.
3. Set `selected_prompt_template` in JSON config.

## 5) Add New Config Fields

Config validation/parsing is centralized in:

- `src/spec2code/pipeline_modules/config_loader.py`

When adding fields:

1. Validate type with `_require_*` or `_optional_*` helpers.
2. Add the field to `PreparedConfig` dataclass.
3. Thread it through runtime/execution where needed.

## 6) Add New Output Parsing Rules

LLM response extraction/parsing is in:

- `src/spec2code/core/llm_output_parser.py`

If you support a new model output format:

1. Add parser logic there.
2. Keep backward compatibility with existing sentinel format and JSON flow.
3. Verify generated `output.json` still contains required keys.

## 7) Add a New Pipeline Capability

Execution pipeline is split by responsibility:

- orchestration: `src/spec2code/core/runner.py`
- per-run execution: `src/spec2code/core/pipeline_executor.py`
- artifact handling and critics invocation: `src/spec2code/core/artifacts.py`

Recommended approach:

1. Add config flag in `config_loader.py`.
2. Add behavior in `pipeline_executor.py` or `artifacts.py`.
3. Keep `runner.py` focused on orchestration only.

## 8) Reliability Checks Before Merge

Run at least:

```bash
PYTHONPATH=src python -m spec2code.cli.run_pipeline --config config/gui_templates/shutdown-algorithm-template.json
```

And verify:

- pipeline starts and completes
- outputs are written to configured `output_folder`
- `output.json` includes critic sections and raw response metadata

## 9) Public-Repo Safety Checklist

Before pushing:

- no credentials in tracked files
- no cloud account IDs/ARNs hardcoded unless intentionally public and approved
- secrets only via environment variables
- prefer mock models for CI/smoke tests
