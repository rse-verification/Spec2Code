# Adding Critics

This guide covers the full path for a new critic: runtime class, runner registration, GUI controls, external tool placement, and tests.

## 1) Implement the Critic Interface

Create your critic in `src/spec2code/pipeline_modules/critics/critics_<name>.py`.

Contract is defined in `src/spec2code/pipeline_modules/critics/critics_interface.py`:

- input shape: `CriticInput`
- output shape: `CriticResult`
- protocol: `Critic` with `name` and `run(inp)`

Minimum class skeleton:

```python
from __future__ import annotations

from spec2code.pipeline_modules.critics.critics_interface import CriticInput, CriticResult


class MyToolCritic:
    name = "my-tool"

    def run(self, inp: CriticInput) -> CriticResult:
        c_file_path = inp["c_file_path"]
        timeout = int(inp.get("timeout", 60))
        ctx = dict(inp.get("context", {}))

        # run your checker here
        ok = True
        raw = ""

        return {
            "tool": self.name,
            "success": ok,
            "score": 1.0 if ok else 0.0,
            "summary": "My tool passed." if ok else "My tool failed.",
            "metrics": {"timeout": timeout},
            "findings": [],
            "raw_output": raw,
        }
```

Notes:

- `tool` should match `name`.
- `findings` should be structured and actionable (`severity`, `message`, `location`, `rule`).
- If your tool can fail with partial output, still return valid `CriticResult`.

## 2) Register the Critic in Runner

Edit `src/spec2code/pipeline_modules/critics/critics_runner.py`:

1. Import your class.
2. Add a `build_critics_from_names(...)` branch for your critic name.
3. Optionally include it in `build_default_critics(...)`.

Typical branch pattern:

```python
elif n == "my-tool":
    bin_path = str(n_opts.get("bin_path", _MY_TOOL_BIN))
    out.append(MyToolCritic(bin_path=bin_path, timeout=critic_timeout))
```

This is how config `critic_options["my-tool"]` gets into your critic.

## 3) Expose the Critic in GUI (Runner/Verify)

The GUI critic form is catalog-driven, so in most cases you only change one backend constant.

Primary file: `src/spec2code/gui/run_server.py`

Add your entry in `CRITICS_CATALOG`:

```python
{
    "name": "my-tool",
    "label": "My Tool",
    "default_enabled": False,
    "options": [
        {"key": "timeout", "type": "int", "label": "Timeout (s)", "default": 60},
        {"key": "bin_path", "type": "path", "label": "Tool binary", "default": "tools/my_tool/bin/check.sh"},
        {"key": "strict", "type": "bool", "label": "Strict mode", "default": False},
    ],
}
```

How it works:

- `/api/critics` returns this catalog.
- `src/spec2code/gui/critics-ui.js` renders controls automatically.
- On run, selected values are sent as `critic_options[critic_name][key]`.

Supported option types in the dynamic GUI renderer:

- `int`
- `float`
- `bool`
- `string`
- `path`

Use `type: "path"` for files/scripts to get the file picker button.

## 4) Add Verify-Specific Wiring Only If Needed

Most critics need no extra verify wiring.

Only edit `_run_verify_files(...)` in `src/spec2code/gui/run_server.py` when your critic needs:

- staged/generated helper files,
- option expansion into multiple internal critics,
- special validation before calling `build_critics_from_names(...)`.

Example in repo: `vernfr` is expanded into `vernfr-control-flow` and `vernfr-data-flow` with staged `.is` and header inputs.

## 5) Where External Tools Should Live

Use this structure for bundled tools:

- source/tool project: `tools/<tool_name>/`
- runnable scripts: `tools/<tool_name>/scripts/`
- defaults in Python should point to repo-relative paths like `tools/<tool_name>/scripts/check.sh`

If the tool needs build/install in Docker:

- add build step in `dockerfile`
- document opt-out build args if expensive/optional
- document local (non-Docker) build commands in `README.md`

Vernfr is the reference pattern (`tools/nfrcheck`).

## 6) Config Usage

After registration, users enable it in config JSON:

```json
{
  "critics": ["compile", "my-tool"],
  "critic_options": {
    "my-tool": {
      "timeout": 45,
      "strict": true,
      "bin_path": "tools/my_tool/scripts/check.sh"
    }
  }
}
```

## 7) Tests You Should Add

- critic unit tests: `tests/unit/pipeline_modules/critics/test_critics_<name>.py`
- runner mapping tests (if needed): `tests/unit/pipeline_modules/critics/test_critics_runner.py`
- GUI verify flow tests when special wiring exists: `tests/unit/gui/test_run_server_verify.py`

At minimum test:

- success path
- non-zero tool failure path
- timeout path
- missing required file/tool path
