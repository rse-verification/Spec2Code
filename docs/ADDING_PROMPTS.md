# Adding Prompt Templates

Prompt templates are loaded in `src/spec2code/pipeline_modules/experiment_parameters.py`.

## Add a New Prompt Template

1. Create a prompt file in `prompts/`.
2. Register it in `load_prompt_templates()`.
3. Use its key in config as `selected_prompt_template`.

## Placeholder Inputs

Prompt formatting uses placeholders from prepared case-study/config inputs, such as:

- `{{input_natural_language_specification}}`
- `{{input_interface}}`
- `{{input_type_definitions}}`
- `{{input_headers_json}}`
- `{{input_types_header_filename}}`

Keep templates backward compatible with existing placeholders when possible.

## Validation

- Run one template-driven pipeline execution.
- Confirm prompt resolves without missing placeholders.
- Verify generated outputs and critic sections are still emitted.
