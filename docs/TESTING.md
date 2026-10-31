# Testing spec2code

## Setup

Use a virtual environment and install the runtime plus test dependencies:

```sh
python -m pip install -r requirements-test.txt
```

JavaScript tests use Node 24's built-in runner. For browser tests, also install the Playwright browser matching the installed Python package:

```sh
python -m playwright install chromium
```

On a Linux CI machine, `python -m playwright install --with-deps chromium` also installs browser system dependencies.

## Test commands

Portable Python unit and integration tests (no installed C tools or browser needed):

```sh
python -m pytest -m "not native and not e2e" -q
node --test tests/unit/gui/test_analytics.cjs
```

Full Python suite, including native-tool tests where tools are installed:

```sh
python -m pytest -q -ra
```

Browser tests are opt-in. PowerShell:

```powershell
$env:SPEC2CODE_BROWSER_TESTS = "1"
python -m pytest -m e2e -q
```

Linux:

```sh
SPEC2CODE_BROWSER_TESTS=1 python -m pytest -m e2e -q
python -m pytest -m "native and not slow" -q -ra
```

Polyspace remains opt-in through `POLYSPACE_INTEGRATION=1` and requires an installed licensed toolchain. Use `-ra` to review skipped tests rather than treating unavailable tools as successful checks.

## Classification and isolation

- `tests/unit/` tests default to the `unit` marker unless explicitly marked `integration`, `e2e`, or `contracts`. The default is applied **before** `-m` filtering.
- Tests under `tests/integration/` default to `integration`.
- Existing integration tests marked `critics` are also marked `native`. New tests needing external C tools should explicitly use `native`.
- Unknown markers are errors. New test directories must have a matching category or explicit test-category markers.
- Tests clear inherited provider credentials and disable `.env` loading. GUI tests use temporary settings and model caches. Python socket connections are limited to loopback; even a swallowed attempt to contact a remote endpoint fails the test.
- Dependencies must actually be installed. The suite no longer substitutes a fake `boto3` module when it is missing.

## CLI integration tests

`tests/integration/test_cli_pipeline.py` runs the real CLI entrypoint, configuration loading, OpenAI-compatible SDK, response parser, artifact writer, critic runner, repair loop, and report generator. A loopback HTTP server supplies deterministic model responses.

Portable cases use a fixture critic to test first-attempt success, malformed-output repair, critic-failure repair, exhausted attempt budgets, and multiple models/samples. They validate saved evidence and report assets. A separate native test launches `python -m spec2code.cli.run_pipeline` in a child process and uses real GCC to reject a faulty implementation, then compile its repair.

The CLI currently returns zero when orchestration completes, including exhausted repair attempts. Verification success is recorded in `critics_success`/`verify_success`, and the tests explicitly check this distinction.

## Model-output contract

Accepted responses contain either one complete pair of `BEGIN_C`/`END_C` and `BEGIN_H`/`END_H` blocks, or a JSON object with nonempty string fields `c` and `h`. A single fenced JSON block may have surrounding explanatory text. Sentinel delimiters must appear on their own lines; CRLF and CR line endings are normalized. Duplicate JSON keys and multiple alternative implementations are rejected.

Malformed output produces `ModelOutputError`, retaining the original response. The pipeline saves that attempt with a failed verdict, skips critics, and includes the parse error and raw response in a repair prompt while attempts remain. Provider/network exceptions are distinct from malformed model output.

## Defaults and process behavior

Frama-C uses a **60-second process timeout** and **2-second per-goal timeout** by default in the GUI. The registry test checks those defaults against the constructed critic and checks explicit overrides. The old assertion for a 180-second default and the unsupported `framac_wp_no_let` option were stale.

`run_command` accepts shell strings for existing critics and argument lists for portable, shell-free execution. Tests cover exit codes, concurrent stdout/stderr draining, literal shell metacharacters, streaming, and timeout termination of descendant processes on Windows and POSIX.

## Coverage and CI

```sh
python -m coverage run -m pytest -m "not native and not e2e" -q
python -m coverage report
python -m coverage html
```

`.coveragerc` measures statements and branches across `src/spec2code`, with an initial combined coverage floor of **65%**. This includes legacy modules; the threshold is a baseline, not a claim that every feature is fully tested.

The GitHub Actions workflow runs:

1. Portable Python and JavaScript checks on Windows and Linux with Python 3.11 and 3.12.
2. Native critic tests on Linux with GCC, Clang, and Cppcheck.
3. The opt-in browser workflow with Chromium.

JUnit results and coverage XML are uploaded as CI artifacts. Paid model inference and licensed tools are not required by these jobs.

The workflow runs on pull requests and pushes to `main`, and supports manual
dispatch from the GitHub Actions page after it is merged. New pushes cancel
superseded runs for the same PR/ref. Reports are retained for 14 days.
The final **Test gate** check succeeds only when all three test jobs succeed;
it provides a stable check name for repository branch-protection rules.
