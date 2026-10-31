# Managed Workspaces

The recommended Spec2Code workflow uses one persistent workspace instead of
separate input, case-study, and output mounts.

```text
spec2code-workspace/
  projects/
    controller/
      nlspec.txt
      controller.is
      headers/
        controller.h
        controller_ver.h
        types.h
      spec2code.project.json  # optional
  input/
  output/
```

Start the application with:

```bash
docker compose up --build
```

Open `http://127.0.0.1:8080/runner`, leave **Project Mode** selected, and
import a project ZIP. The ZIP may contain the project files directly or one
wrapper directory.

## Automatic Discovery

Without a manifest, Spec2Code detects:

- `nlspec.txt`, `spec.txt`, or `requirements.txt` as the natural specification;
- a single `*.is` file as the interface;
- `headers/` as the header and include directory;
- a single `*_ver.h` file as the Frama-C verification header;
- all non-verification `*.h` files as prompt headers.

If a project has an ambiguous or non-standard layout, add
`spec2code.project.json`:

```json
{
  "spec": "requirements.txt",
  "interface": "controller.is",
  "headers": "headers",
  "verification_header": "headers/controller_ver.h",
  "include_dirs": ["headers"],
  "prompt_headers": {
    "types.h": "Primitive project types.",
    "controller.h": "Public controller interface."
  }
}
```

Manifest paths must remain inside the project directory.

## Compatibility

Existing configurations and environment variables remain supported. Explicit
run fields override project discovery, and manifest values override automatic
discovery:

```text
explicit run field > project manifest > automatic discovery
```

The legacy `SPEC2CODE_OUTPUT_ROOT`, `SPEC2CODE_INPUT_ROOT`, and
`SPEC2CODE_CASE_STUDIES_ROOT` variables can still override individual roots.
New deployments should normally set only `SPEC2CODE_WORKSPACE_ROOT`.
