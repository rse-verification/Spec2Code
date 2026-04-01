# Case Study: SGMM

## Status

- `sgmm` / `sgmm_full` names are recognized by some legacy code paths.
- Not shipped as ready-to-run OSS template/assets in this package.

## Why It May Not Work Out of the Box

- No maintained SGMM GUI template is included under `config/gui_templates/`.
- Expected external case-study files may be missing from `<SPEC2CODE_CASE_STUDIES_ROOT>/sgmm*`.

## If You Want To Enable It

1. Provide SGMM assets under `<SPEC2CODE_CASE_STUDIES_ROOT>/sgmm_full/` with the standard layout (`nlspec`, interface, headers).
2. Create a dedicated config template in `config/gui_templates/`.
3. Validate `natural_spec_path`, `interface_path`, `headers_dir`, and verify header paths.
4. Run with mock or configured real LLM model and verify critics behavior.
