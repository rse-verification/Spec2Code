# Case Study: SFLD

## Status

- `sfld` / `sfld-ghost` names are recognized by some legacy code paths.
- Not shipped as ready-to-run OSS template/assets in this package.

## Why It May Not Work Out of the Box

- No maintained SFLD GUI template is included under `config/gui_templates/`.
- Expected external case-study files may be missing from `<SPEC2CODE_CASE_STUDIES_ROOT>/sfld*`.

## If You Want To Enable It

1. Provide SFLD assets under `<SPEC2CODE_CASE_STUDIES_ROOT>/sfld/` (or the desired variant).
2. Add a dedicated config template in `config/gui_templates/`.
3. Validate header/include paths and optional verification headers.
4. Run and verify critics output before treating it as supported.
