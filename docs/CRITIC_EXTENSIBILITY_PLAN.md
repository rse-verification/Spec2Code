# Critic Extensibility Plan

This roadmap tracks how to make critic integration progressively more plug-and-play.

## What Is Improved Now

- Single registry source for critic builders and GUI option schema:
  - `src/spec2code/pipeline_modules/critics/critics_registry.py`
- `critics_runner.py` now builds critics from registry entries.
- GUI catalog (`/api/critics`) now comes from the same registry metadata.

Result: adding a typical critic no longer requires editing both runner and GUI server.

## Next Improvements (Planned)

1. Add per-critic preflight hooks in registry (path checks, required files, option validation).
2. Add optional verify-preprocessor hooks in registry so special cases like Vernfr expansion are plugin-driven.
3. Add typed option schema validation and user-facing error messages generated from schema.
4. Add critic self-test command support (e.g., `python -m spec2code.cli.check_critics`) to verify tool availability.
5. Add docs/autogen step to render critic reference table from registry metadata.

## Longer-Term Direction

- External plugin loading (entry points) so critics can be added from separate packages.
- Versioned critic capability contracts for stable integrations.
- Optional GUI grouping/tabs generated from metadata (safety, style, formal, non-functional).
