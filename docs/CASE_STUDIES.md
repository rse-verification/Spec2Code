# Case Studies

This page documents what is runnable in this OSS package and what is legacy/experimental.

## Paths and Layout

Runtime looks for case-study assets under:

- `<SPEC2CODE_CASE_STUDIES_ROOT>` (default: `../spec2code_case_studies`)

Expected layout per case study:

```text
<SPEC2CODE_CASE_STUDIES_ROOT>/<case_study>/
  nlspec.txt
  interface.txt or <module>.is
  headers/
    *.h
```

Template-driven runs in this repo currently rely on explicit paths in
`config/gui_templates/shutdown-algorithm-template.json`.

## Status

- `shutdown_algorithm`: supported and documented.
- `sgmm`, `sgmm_full`: legacy/experimental identifiers; not shipped as ready-to-run assets/templates in this OSS package.
- `sfld`, `sfld-ghost`: legacy/experimental identifiers; not shipped as ready-to-run assets/templates in this OSS package.
- `brak`, `brak-ghost`, `test`: internal/testing identifiers.

See per-case-study notes:

- `docs/CASE_STUDY_SHUTDOWN.md`
- `docs/CASE_STUDY_SGMM.md`
- `docs/CASE_STUDY_SFLD.md`
