# Extending spec2code

This index links to focused implementation guides for common extension tasks.

## Guides

- Add providers and models: `docs/ADDING_LLMS.md`
- Add critics: `docs/ADDING_CRITICS.md`
- Add prompt templates: `docs/ADDING_PROMPTS.md`
- Add config/runtime capabilities: `docs/ADDING_PIPELINE_FEATURES.md`

## Reliability Checks Before Merge

Run at least:

```bash
PYTHONPATH=src python -m spec2code.cli.run_pipeline --config config/gui_templates/shutdown-algorithm-template.json
```

Verify:

- pipeline starts and completes
- outputs are written to configured `output_folder`
- `output.json` includes critic sections and raw response metadata

## Public-Repo Safety Checklist

Before pushing:

- no credentials in tracked files
- no cloud account IDs/ARNs hardcoded unless intentionally public and approved
- secrets only via environment variables
- prefer mock models for CI/smoke tests
