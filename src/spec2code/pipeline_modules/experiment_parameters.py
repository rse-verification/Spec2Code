import os
import json
from pathlib import Path
from typing import Dict, List, Any, Optional

import spec2code.pipeline_modules.llms as llms
import spec2code.pipeline_modules.llms_test as llms_test
from spec2code.pipeline_modules.filesystem_io import read_file, list_files

# ----------------------------
# LLM + Case study configuration
# ----------------------------

MOCK_LLM_NAMES: List[str] = [
    "test-llm-shutdown",
    "test-llm",
    "test-llm-fs",
    "test-llm-main",
    "test-llm-brak",
    "test-llm-sgmm",
    "test-llm-sfld",
]

VALID_CASE_STUDIES: List[str] = ["sfld", "sgmm", "sgmm_full", "brak", "test", "brak-ghost", "sfld-ghost"]

REPO_ROOT = Path(__file__).resolve().parents[3]
CASE_STUDIES_ROOT = Path(
    os.getenv("SPEC2CODE_CASE_STUDIES_ROOT", str(REPO_ROOT.parent / "spec2code_case_studies"))
).resolve()


# ----------------------------
# Prompt templates
# ----------------------------

def load_prompt_templates() -> Dict[str, str]:
    """
    Loads prompt templates from the file system.
    """
    repo_root = Path(__file__).resolve().parents[3]
    prompt_path = repo_root / "prompts" / "zero-shot.txt"
    return {
        "zero-shot": read_file(str(prompt_path)) or "",
    }


# ----------------------------
# Model initialization
# ----------------------------

def initialize_llms(names: Optional[List[str]] = None) -> Dict[str, object]:
    """
    Initializes available LLM models.

    Returns:
        Dict[str, object]: A dictionary containing initialized LLM models.
    """
    # Build real models from the registry
    available = set(llms.available_model_names())
    if names is None:
        model_names = list(available)
    else:
        # Accept dynamic Bedrock ids discovered at runtime via GUI/API.
        model_names = [
            n
            for n in names
            if (n in available) or n.startswith("bedrock/") or n.startswith("bedrock:") or n.startswith("bedrock-profile/")
        ]
    models: Dict[str, object] = llms.build_models(model_names)

    # Add mock models (optional)
    mock_map = llms_test.build_mock_models()
    if names is None:
        models.update(mock_map)
    else:
        for name in names:
            if name in mock_map:
                models[name] = mock_map[name]

    return models


# ----------------------------
# Headers loading (multiple headers)
# ----------------------------

def load_input_headers(headers_dir: str) -> str:
    """
    Returns a JSON string of:
      [{"filename": "...", "provides": "...", "content": "..."}, ...]
    """
    if not headers_dir or not os.path.isdir(headers_dir):
        return "[]"

    items: List[Dict[str, str]] = []
    for fn in sorted(list_files(headers_dir)):
        if not fn.endswith(".h"):
            continue
        path = os.path.join(headers_dir, fn)
        content = read_file(path) or ""
        items.append({
            "filename": fn,
            "provides": "",  # fill later if you want (manual or LLM-generated)
            "content": content,
        })
    return json.dumps(items)


def _find_defined_types_filename(headers_dir: str) -> str:
    """
    Prefer 'defined_types.h' if present, else the first header in the folder.
    Used only to set an include filename hint for the prompt.
    """
    if not headers_dir or not os.path.isdir(headers_dir):
        return "defined_types.h"

    headers = [fn for fn in sorted(list_files(headers_dir)) if fn.endswith(".h")]
    if "defined_types.h" in headers:
        return "defined_types.h"
    return headers[0] if headers else "defined_types.h"


def _extract_type_defs_from_headers_json(headers_json: str) -> str:
    """
    Produces a single string with ALL header contents concatenated, so you can
    keep using the existing {{input_type_definitions}} placeholder.
    """
    try:
        arr = json.loads(headers_json)
        if not isinstance(arr, list):
            return ""
    except Exception:
        return ""

    parts: List[str] = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        fn = str(item.get("filename", "header.h"))
        content = str(item.get("content", ""))
        if not content.strip():
            continue
        parts.append(f"/* === BEGIN {fn} === */\n{content}\n/* === END {fn} === */\n")
    return "\n".join(parts).strip()


# ----------------------------
# Case study inputs
# ----------------------------

def get_case_study_inputs(case_study: str) -> Dict[str, str]:
    if case_study not in VALID_CASE_STUDIES:
        raise ValueError(f"Error: {case_study} is not a valid case study.")

    base_dir = CASE_STUDIES_ROOT / case_study
    legacy_dir = REPO_ROOT / "case_studies" / case_study
    if not base_dir.exists() and legacy_dir.exists():
        base_dir = legacy_dir

    base_path = str(base_dir)
    headers_path = str(base_dir / "headers")

    headers_json = load_input_headers(headers_path)
    types_include = _find_defined_types_filename(headers_path)
    type_defs_concat = _extract_type_defs_from_headers_json(headers_json)

    return {
        "input_natural_language_specification": read_file(os.path.join(base_path, "nlspec.txt")) or "",
        "input_interface": read_file(os.path.join(base_path, "interface.txt")) or "",
        # Backwards-compatible: keep old placeholder name, but now it contains ALL headers
        "input_type_definitions": type_defs_concat,
        "input_signature": read_file(os.path.join(base_path, "signature.txt")) or "",
        # New: give the LLM structured header files + a strong include hint
        "input_headers_json": headers_json,
        "input_types_header_filename": types_include,
        # For pipeline compile/copy steps
        "headers_dir": headers_path,
    }


# ----------------------------
# Prompt formatting
# ----------------------------

def format_prompt(template_type: str, case_study_inputs: Dict[str, str]) -> str:
    templates = load_prompt_templates()

    if template_type not in templates:
        raise ValueError(f"Unknown template type: {template_type}. Available: {list(templates.keys())}")
    selected_template = templates[template_type]
    if selected_template is None or selected_template.strip() == "":
        raise ValueError(
            f"Template '{template_type}' is empty. Check the file path in load_prompt_templates() "
            f"and ensure it contains content."
        )

    for key, value in case_study_inputs.items():
        selected_template = selected_template.replace(f"{{{{{key}}}}}", value)

    return selected_template


# ----------------------------
# Supported LLM validation
# ----------------------------

def ensure_supported_llms(llms_list: List[str]) -> None:
    """
    Ensures that the specified LLMs are supported.

    Supports:
      - any key in SUPPORTED_LLMs
      - dynamic Bedrock ids of the form "bedrock/<modelId>", "bedrock:<modelId>",
        or "bedrock-profile/<inferenceProfileArnOrId>" (optional feature)
    """
    supported = set(llms.available_model_names()) | set(MOCK_LLM_NAMES)

    for name in llms_list:
        # Optional: allow direct bedrock ids without registering them
        if name.startswith("bedrock-profile/"):
            if not name.split("bedrock-profile/", 1)[1].strip():
                raise ValueError("Bad Bedrock entry: expected 'bedrock-profile/<inferenceProfileArnOrId>'")
            continue
        if name.startswith("bedrock/"):
            if not name.split("bedrock/", 1)[1].strip():
                raise ValueError("Bad Bedrock entry: expected 'bedrock/<modelId>'")
            continue
        if name.startswith("bedrock:"):
            if not name.split("bedrock:", 1)[1].strip():
                raise ValueError("Bad Bedrock entry: expected 'bedrock:<modelId>'")
            continue

        if name not in supported:
            raise ValueError(
                f"Error: {name} is not a supported LLM. Supported LLMs are: {sorted(supported)}."
            )
