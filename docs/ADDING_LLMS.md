# Adding LLM Providers and Models

This guide covers both provider-level integrations and simple model additions.

## Add a New Provider Type

Provider implementations live in `src/spec2code/pipeline_modules/llms.py`.

Current provider classes include:

- `BedrockProvider`
- `OpenAICompatibleProvider`
- `OllamaProvider`

To add another provider type:

1. Implement a provider class with `generate(model_id, prompt, temperature, max_tokens)` returning `_SimpleLLMResponse`.
2. Register the provider in the provider factory (`_build_provider(...)`).
3. Define provider config schema keys consumed from `config/llm_providers.yaml`.
4. Add at least one model entry that references the new provider.

## Add a New Model (No Code Changes)

Most additions are config-only updates in `config/llm_providers.yaml`.

Example:

```yaml
models:
  my-new-model:
    provider: openai_default
    model: gpt-4o-mini
    max_tokens: 2048
```

Then use it in pipeline config JSON:

```json
"llms_used": ["my-new-model"]
```

## GUI Model Discovery Notes

- GUI server model listing is handled in `src/spec2code/gui/run_server.py`.
- Runtime model initialization is handled in `src/spec2code/pipeline_modules/experiment_parameters.py`.
- Dynamic Bedrock model/profile entries are supported through normalized model names.

## Validation

Smoke test with:

```bash
PYTHONPATH=src python -m spec2code.cli.run_pipeline --config config/gui_templates/shutdown-algorithm-template.json
```

If using GUI, also verify `/runner` lists your new model and run completes.
