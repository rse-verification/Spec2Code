# Installing and Running spec2code

This page is the canonical setup and run guide.

## Recommended: Docker

### 1) Build image

```bash
docker build -f dockerfile -t spec2code:local .
```

Notes:

- Vernfr (`tools/nfrcheck`) is built by default.
- Optional Bedrock CLI in image:

```bash
docker build -f dockerfile --build-arg INSTALL_AWSCLI=1 -t spec2code:local .
```

- Optional skip Vernfr build:

```bash
docker build -f dockerfile --build-arg BUILD_NFRCHECK=0 -t spec2code:local .
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
docker run --rm -it -p 8080:8080 -v "$(pwd)":/workspace spec2code:local bash
cd /workspace
PYTHONPATH=src python -m spec2code.gui.run_server --host 0.0.0.0 --port 8080
```

Open:

- `http://127.0.0.1:8080/runner`
- `http://127.0.0.1:8080/results`

## Local Python (Optional)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python -m spec2code.cli.run_pipeline --config config/gui_templates/shutdown-algorithm-template.json
```

If using Vernfr critics outside Docker:

```bash
eval "$(opam env --switch=ocaml5)"
cd tools/nfrcheck
dune build @install
dune install
```

## Runtime Paths

- Output root default: `../spec2code_output`
- Case-study root default: `../spec2code_case_studies`

Override with:

```bash
export SPEC2CODE_OUTPUT_ROOT=/absolute/path/to/spec2code_output
export SPEC2CODE_CASE_STUDIES_ROOT=/absolute/path/to/spec2code_case_studies
```
