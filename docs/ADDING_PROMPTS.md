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
- `{{input_headers}}`
- `{{input_types_header_filename}}`

The prepared `input_headers` collection is the canonical source of header content. 
Each item contains its filename, a short description of what it provides, and its 
content.

## Validation

- Run one template-driven pipeline execution.
- Confirm prompt resolves without missing placeholders.
- Verify generated outputs and critic sections are still emitted.
