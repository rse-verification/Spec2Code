# Installing and Running spec2code

This page is the canonical setup and run guide.

## Recommended: Docker

The easiest setup uses one managed workspace:

```bash
docker compose up --build
```

Open `http://127.0.0.1:8080/runner`, import a project ZIP in Project Mode, and
run it. Compose persists projects, settings, outputs, reports, and temporary
files under `./spec2code-workspace`. See [WORKSPACES.md](WORKSPACES.md).

### 1) Build image

```bash
docker build -f dockerfile -t spec2code:local .
```

Notes:

- Default image critics: compile (GCC), no-loops, Cppcheck/MISRA, Frama-C/WP, and VerNFR.
- Optional critics: Valgrind and ESBMC are omitted unless explicitly enabled.
- Polyspace Bug Finder is a licensed, runtime-mounted integration and is disabled by default.
- Optional Bedrock CLI in image:

```bash
docker build -f dockerfile --build-arg INSTALL_AWSCLI=1 -t spec2code:local .
```

- Optional Valgrind and ESBMC critics:

```bash
docker build -f dockerfile --build-arg INSTALL_VALGRIND=1 --build-arg INSTALL_ESBMC=1 -t spec2code:local .
```

- Tool versions are configurable build arguments. The defaults are
  `DEBIAN_VERSION=trixie`, `OCAML_VERSION=5.4.1`, `OPAM_VERSION=2.5.2`, `Z3_VERSION=4.16.0`,
  `CVC5_VERSION=1.2.0`, `CPPCHECK_VERSION=2.21.0`, and `ESBMC_VERSION=7.6`.
  For example:

```bash
docker build -f dockerfile \
  --build-arg DEBIAN_VERSION=trixie \
  --build-arg OCAML_VERSION=5.4.1 \
  --build-arg OPAM_VERSION=2.5.2 \
  --build-arg CPPCHECK_VERSION=2.21.0 \
  --build-arg Z3_VERSION=4.16.0 \
  --build-arg CVC5_VERSION=1.2.0 \
  --build-arg ESBMC_VERSION=7.6 \
  -t spec2code:local .
```

### 2) Start container

```bash
docker run --rm -it -v "$(pwd)":/workspace spec2code:local bash
```

### 3) Run pipeline

```bash
cd /workspace
PYTHONPATH=src python3 -m spec2code.cli.run_pipeline --config config/gui_templates/shutdown-algorithm-template.json
```

### 4) Run GUI

```bash
docker run --rm -it -p 127.0.0.1:8080:8080 -v "$(pwd)":/workspace spec2code:local bash
cd /workspace
PYTHONPATH=src python -m spec2code.gui.run_server --host 0.0.0.0 --port 8080
```

Open:

- `http://127.0.0.1:8080/runner`
- `http://127.0.0.1:8080/settings`
- `http://127.0.0.1:8080/results`

## Polyspace Bug Finder (Optional)

Polyspace is proprietary and is not copied into the spec2code image. Install a
Linux release of MATLAB/Polyspace on the host, then mount that release root
read-only. The mounted directory must contain
`polyspace/bin/polyspace-bug-finder` and
`polyspace/bin/polyspace-results-export`.

For a network license:

```bash
docker run --rm -it \
  -p 127.0.0.1:8080:8080 \
  -v "$(pwd)":/workspace \
  -v /path/to/MATLAB/R20XXx:/opt/polyspace:ro \
  -e POLYSPACE_ROOT=/opt/polyspace \
  -e MLM_LICENSE_FILE=27000@license-server \
  spec2code:local bash
```

Use the appropriate MathWorks license environment for your installation if it
does not use `MLM_LICENSE_FILE`. The container must be able to resolve and
reach the license server. Confirm that your Polyspace release supports the
container's Debian version; use a MathWorks-supported base image for a
dedicated worker if it does not.

Enable `polyspace-bug-finder` in the GUI or configuration. By default, any
finding attributed to the generated C source or generated header fails the
critic and is supplied to repair feedback:

```json
{
  "critics": ["compile", "polyspace-bug-finder"],
  "critic_options": {
    "polyspace-bug-finder": {
      "timeout": 900,
      "fail_on": "any",
      "options_file": "/workspace/config/polyspace-options.txt",
      "extra_options": ""
    }
  }
}
```

`fail_on` accepts `any`, `warning`, or `error`. Set `executable` and `exporter`
when commands are outside `POLYSPACE_ROOT/polyspace/bin`. Each run retains the
Polyspace result directory and exported SARIF file; the Results page links to
the SARIF evidence.

The normal test suite mocks Polyspace. Run the licensed smoke test explicitly:

```bash
POLYSPACE_INTEGRATION=1 PYTHONPATH=src pytest -m integration \
  tests/unit/pipeline_modules/critics/test_critics_polyspace_bug_finder.py
```

## Local Python (Optional)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python -m spec2code.cli.run_pipeline --config config/gui_templates/shutdown-algorithm-template.json
```

If using Vernfr critics outside Docker:

```bash
opam switch create ocaml5 ocaml-base-compiler.5.4.1
bash tools/install_optional_vernfr.sh
```

`spec2code.opam` is a virtual package that records the compatible OPAM dependencies for the Frama-C/WP and VerNFR critics. It pins VerNFR to a tested upstream revision. The installer runs `opam install --deps-only ./spec2code.opam`; set `SPEC2CODE_OPAM_SWITCH` before running it to use a switch other than `ocaml5`.

Verify the installed VerNFR plugin:

```bash
eval "$(opam env --switch=ocaml5)"
frama-c -plugins | grep -i vernfr
```

## Runtime Paths

- Output root default: `../spec2code_output`
- Case-study root default: `../spec2code_case_studies`
- Input root default: `../spec2code_input`

Override with:

```bash
export SPEC2CODE_OUTPUT_ROOT=/absolute/path/to/spec2code_output
export SPEC2CODE_CASE_STUDIES_ROOT=/absolute/path/to/spec2code_case_studies
export SPEC2CODE_INPUT_ROOT=/absolute/path/to/spec2code_input
```
