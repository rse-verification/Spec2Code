# Reports, project input and model selection

## Critic statistics and figures

The Results page and generated `reports/last-run.html` share a **Statistics & figures** dashboard. It works with existing sample `output.json` files and does not require a chart CDN.

Figures cover critic outcomes, per-critic scores, measured runtime, diagnostic severity, findings per critic, frequent rules, source hotspots, proof obligations, and reported binary/memory usage and limits. New pipeline runs also retain a compact `generation_attempts` history for repair progress and attempt-duration charts.

Each populated figure has an exact-value table and **Download SVG** for use in documents. Summary statistics include the pass rate, failed/unknown counts, distinct affected source lines, unlocated diagnostics, total measured critic time, median time, and timing coverage.

Statistics describe the displayed sample's final attempt, rather than combining models or samples. A critic's explicit `success` flag takes precedence over its numeric score. Missing timings/scores are not interpreted as zero, and empty critic results are not a pass. Tool-specific scores are not averaged into a quality grade. Proof and resource figures show an empty state when their critics did not report measurements. Repair history is available only for newly generated sample results.

## Choose a folder or files

In Runner **Project Mode**:

1. Choose **Choose folder** or **Choose files**. This uses your browser's file picker and works when the server runs in Docker.
2. Review the project name and the detected requirements file, `.is` interface, headers directory, and optional verification header. Select a different file from the dropdown when detection is ambiguous. Requirements may have any filename; no renaming or handwritten JSON is needed.
3. Click **Import selected files**. The server preserves filenames and relative directories, writes a project manifest, and derives include paths and prompt headers. Imported files are kept in the managed workspace.
4. Select models and critics, then run. Advanced path overrides remain available.

Browser import accepts up to 5000 files totaling 50 MB. Existing project names are not overwritten; choose a new name to import another version. ZIP import remains available. A requirements file alone is not sufficient: generation also needs an interface and a headers directory (which may be the project root).

Individual **Pick** buttons now open an explicit choice of existing server paths, **Upload file**, or **Native picker**. Native pickers run on the server machine; browser uploads read files from your computer. For related C/header files, project import preserves their relative include structure.

## Model discovery and compatibility

Runner uses searchable checkboxes, grouped by provider. Selections survive filtering and refresh. Known embedding, image/audio/video, reranking, legacy completion-only and specialized tool-workflow models are disabled with a reason. Provider YAML aliases are also selectable when their credentials are configured.

Discovery and invocation use the same `OPENAI_BASE_URL`. Keyless vLLM endpoints use the same placeholder API key for both operations. OpenAI reasoning models omit unsupported temperature settings; Codex/pro variants use Responses. Explicit unsupported-temperature or token-parameter responses have bounded compatibility retries. Authentication, quota and other errors are not treated as parameter errors. Bedrock discovery retains active inference profiles and on-demand text model IDs, and reports separate profile/foundation discovery errors.

**Selectable** means that the configuration and known API capabilities are compatible. Model listing does not test inference permissions, subscription access, context limits or available quota. No inference requests are made just to populate the selection list.

## Developer checks

```text
python -m pytest tests/unit/gui tests/unit/pipeline_modules/test_llms.py tests/unit/core/test_pipeline_executor.py tests/unit/test_workspace.py -q
node --test tests/unit/gui/test_analytics.cjs
```

The optional Playwright test exercises folder upload, file roles, model selection, submitted configuration, live charts, SVG download and the offline report. With Playwright and its Chromium browser installed, set `SPEC2CODE_BROWSER_TESTS=1` and run `python -m pytest tests/unit/gui/test_browser_workflows.py -q`. To use a compatible system browser instead, set `SPEC2CODE_BROWSER_CHANNEL` (for example, `msedge`).
