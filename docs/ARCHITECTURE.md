# Architecture Overview

This document explains the runtime flow and key reusable modules in `spec2code`.

## Runtime Flow

1. CLI entrypoint parses args and logging setup.
   - `src/spec2code/cli/run_pipeline.py`
2. Runner initializes solvers and loads prepared configs.
   - `src/spec2code/core/runner.py`
3. Config loader validates JSON and prepares prompt inputs.
   - `src/spec2code/pipeline_modules/config_loader.py`
4. Runtime builder initializes models and critics.
   - `src/spec2code/pipeline_modules/runtime.py`
5. Pipeline executor drives per-model/per-sample generation.
   - `src/spec2code/core/pipeline_executor.py`
6. Artifacts module parses output, writes files, runs critics.
   - `src/spec2code/core/artifacts.py`
7. Report utility renders latest run as HTML.
   - `src/spec2code/gui/report.py`

## Component Responsibilities

- `cli/`
  - User-facing flags and process exit behavior.
- `core/`
  - Orchestration, execution order, output aggregation.
- `pipeline_modules/`
  - Integrations: LLMs, critics, config handling, tooling wrappers.
- `gui/`
  - Viewer to inspect generated run artifacts.

## Reusable Building Blocks

- Provider abstraction for LLM backends:
  - `src/spec2code/pipeline_modules/llms.py`
- Strict config validation and normalization:
  - `src/spec2code/pipeline_modules/config_loader.py`
- Plug-in style critics dispatch:
  - `src/spec2code/pipeline_modules/critics/critics_runner.py`
- Generic run-output viewer pattern:
  - `src/spec2code/gui/index.html`

## Extension Entry Points

- Add provider/model support:
  - `config/llm_providers.yaml`
  - `src/spec2code/pipeline_modules/llms.py`
- Add a critic:
  - `src/spec2code/pipeline_modules/critics/`
- Add a prompt template:
  - `prompts/`
  - `src/spec2code/pipeline_modules/experiment_parameters.py`

See `docs/EXTENDING.md` for the extension index and links to focused implementation guides.
