# Case Study: shutdown_algorithm

## Status

- Supported in this OSS package.
- Included GUI template: `config/gui_templates/shutdown-algorithm-template.json`.

## Required Assets

Expected under `<SPEC2CODE_CASE_STUDIES_ROOT>/shutdown_algorithm`:

- `nlspec.txt`
- `shutdown_algorithm.is`
- `headers/shutdown_algorithm_ver.h`
- `headers/*.h` used by compile/verification

## Run

```bash
PYTHONPATH=src python -m spec2code.cli.run_pipeline --config config/gui_templates/shutdown-algorithm-template.json
```

The template defaults to mock model `test-llm-shutdown` for credential-free smoke runs.
