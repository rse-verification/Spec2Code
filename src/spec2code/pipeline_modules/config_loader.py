# pipeline_modules/config_loader.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from spec2code.pipeline_modules.experiment_parameters import format_prompt
from spec2code.pipeline_modules.critics.critics_runner import build_critics_from_names


REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = Path(os.getenv("SPEC2CODE_OUTPUT_ROOT", str(REPO_ROOT.parent / "spec2code_output"))).resolve()
CASE_STUDIES_ROOT = Path(
    os.getenv("SPEC2CODE_CASE_STUDIES_ROOT", str(REPO_ROOT.parent / "spec2code_case_studies"))
).resolve()
GUI_TEMPLATES_DIR = (REPO_ROOT / "config" / "gui_templates").resolve()


def _abspath(base_dir: str, path: str) -> str:
    if os.path.isabs(path):
        return os.path.normpath(path)

    normalized = path.replace("\\", "/")
    local_candidate = os.path.normpath(os.path.join(base_dir, path))

    if normalized.startswith("case_studies/"):
        if os.path.exists(local_candidate):
            return local_candidate
        suffix = normalized.split("/", 1)[1]
        return os.path.normpath(str(CASE_STUDIES_ROOT / suffix))

    if normalized.startswith("output/"):
        try:
            if Path(base_dir).resolve() == GUI_TEMPLATES_DIR:
                suffix = normalized.split("/", 1)[1]
                return os.path.normpath(str(OUTPUT_ROOT / suffix))
        except Exception:
            pass

    return local_candidate


def _require_str(cfg: Dict[str, Any], key: str) -> str:
    v = cfg.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"Config error: '{key}' is missing or not a non-empty string.")
    return v.strip()


def _require_int(cfg: Dict[str, Any], key: str) -> int:
    v = cfg.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError(f"Config error: '{key}' is missing or not an int.")
    return v


def _require_list_str(cfg: Dict[str, Any], key: str) -> List[str]:
    v = cfg.get(key)
    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
        raise ValueError(f"Config error: '{key}' is missing or not a list of non-empty strings.")
    return [x.strip() for x in v]


def _require_dict_str_str(cfg: Dict[str, Any], key: str) -> Dict[str, str]:
    v = cfg.get(key)
    if not isinstance(v, dict):
        raise ValueError(f"Config error: '{key}' is missing or not an object/dict.")
    out: Dict[str, str] = {}
    for k, val in v.items():
        if not isinstance(k, str) or not k.strip():
            raise ValueError(f"Config error: '{key}' has a non-string/empty filename key.")
        if not isinstance(val, str):
            raise ValueError(f"Config error: '{key}[{k}]' description must be a string.")
        out[k.strip()] = val
    return out


def _optional_bool(cfg: Dict[str, Any], key: str, default: bool) -> bool:
    v = cfg.get(key, default)
    if not isinstance(v, bool):
        raise ValueError(f"Config error: '{key}' must be boolean if present.")
    return v


def _optional_float(cfg: Dict[str, Any], key: str, default: float) -> float:
    v = cfg.get(key, default)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise ValueError(f"Config error: '{key}' must be a number if present.")
    return float(v)


def _optional_int(cfg: Dict[str, Any], key: str, default: int) -> int:
    v = cfg.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError(f"Config error: '{key}' must be int if present.")
    return int(v)


def _optional_bool_or_false(cfg: Dict[str, Any], key: str) -> bool:
    v = cfg.get(key, False)
    if not isinstance(v, bool):
        raise ValueError(f"Config error: '{key}' must be boolean if present.")
    return v


def _optional_path(cfg: Dict[str, Any], key: str, base_dir: str) -> Optional[str]:
    v = cfg.get(key)
    if v is None:
        return None
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"Config error: '{key}' must be a non-empty string if present.")
    return _abspath(base_dir, v.strip())


def _optional_dict_str_any(cfg: Dict[str, Any], key: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    v = cfg.get(key, default if default is not None else {})
    if not isinstance(v, dict):
        raise ValueError(f"Config error: '{key}' must be an object/dict if present.")
    out: Dict[str, Any] = {}
    for k, val in v.items():
        if not isinstance(k, str) or not k.strip():
            raise ValueError(f"Config error: '{key}' has a non-string/empty key.")
        out[k.strip()] = val
    return out


def _require_file(path: str, label: str) -> None:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Config error: {label} not found: {path}")


def _require_dir(path: str, label: str) -> None:
    if not os.path.isdir(path):
        raise FileNotFoundError(f"Config error: {label} directory not found: {path}")


def _read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _load_headers_from_manifest(headers_dir: str, manifest: Dict[str, str]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for filename, provides in manifest.items():
        hdr_path = os.path.join(headers_dir, filename)
        _require_file(hdr_path, f"header '{filename}' (from headers_manifest)")
        content = _read_text_file(hdr_path)
        items.append(
            {
                "filename": filename,
                "provides": provides or "",
                "content": content,
            }
        )
    return items


def _find_header_by_name(headers_items: List[Dict[str, str]], filename: str) -> Optional[Dict[str, str]]:
    for item in headers_items:
        if str(item.get("filename", "")) == filename:
            return item
    return None


def _extract_type_defs_concat(headers_items: List[Dict[str, str]]) -> str:
    parts: List[str] = []
    for item in headers_items:
        fn = str(item.get("filename", "header.h"))
        content = str(item.get("content", ""))
        if content.strip():
            parts.append(f"/* === BEGIN {fn} === */\n{content}\n/* === END {fn} === */\n")
    return "\n".join(parts).strip()


def _pick_types_header_filename(headers_items: List[Dict[str, str]]) -> str:
    fns = [str(it.get("filename", "")) for it in headers_items]
    if "defined_types.h" in fns:
        return "defined_types.h"
    if "scania_types.h" in fns:
        return "scania_types.h"
    return fns[0] if fns else "defined_types.h"


@dataclass(frozen=True)
class PreparedCaseStudyInputs:
    input_natural_language_specification: str
    input_interface: str
    input_type_definitions: str

    input_headers: List[Dict[str, str]]
    input_headers_json: str
    input_types_header_filename: str

    headers_dir: str
    module_state_header_filename: Optional[str]
    module_state_header_content: Optional[str]


@dataclass(frozen=True)
class PreparedConfig:
    raw_config: Dict[str, Any]
    base_dir: str

    name: str
    case_study: str
    selected_prompt_template: str
    llms_used: List[str]
    n_programs_generated: int
    output_folder: str
    natural_spec_path: str
    interface_path: str
    include_dirs: List[str]
    headers_dir: str
    headers_manifest: Dict[str, str]
    critics: List[str]
    temperature: float
    debug: bool
    timeout_s: int
    copy_headers_to_output: bool
    critic_context: Dict[str, Any]
    critic_options: Dict[str, Dict[str, Any]]

    # Loaded + prepared
    case_study_inputs: PreparedCaseStudyInputs
    filled_prompt: str
    critics_instances: List[Any]


def _validate_and_prepare_one(cfg: Dict[str, Any], base_dir: str, *, solvers: list) -> PreparedConfig:
    name = _require_str(cfg, "name")
    case_study = _require_str(cfg, "case_study")
    selected_prompt_template = _require_str(cfg, "selected_prompt_template")
    llms_used = _require_list_str(cfg, "llms_used")
    n_programs_generated = _require_int(cfg, "n_programs_generated")

    output_folder = _abspath(base_dir, _require_str(cfg, "output_folder"))

    include_dirs = [_abspath(base_dir, p) for p in _require_list_str(cfg, "include_dirs")]
    for p in include_dirs:
        _require_dir(p, "include_dirs entry")

    headers_dir = _abspath(base_dir, _require_str(cfg, "headers_dir"))
    _require_dir(headers_dir, "headers_dir")

    headers_manifest = _require_dict_str_str(cfg, "headers_manifest")

    critics = cfg.get("critics", ["compile"])
    if not isinstance(critics, list) or not all(isinstance(x, str) and x.strip() for x in critics):
        raise ValueError("Config error: 'critics' must be a list of non-empty strings if present.")
    critics = [x.strip() for x in critics]

    temperature = _optional_float(cfg, "temperature", 0.7)
    debug = _optional_bool(cfg, "debug", False)
    timeout_s = _optional_int(cfg, "timeout_s", 60)
    copy_headers_to_output = _optional_bool(cfg, "copy_headers_to_output", True)

    critic_context = _optional_dict_str_any(cfg, "critic_context", {})
    raw_critic_options = _optional_dict_str_any(cfg, "critic_options", {})
    critic_options: Dict[str, Dict[str, Any]] = {}
    for critic_name, options in raw_critic_options.items():
        if not isinstance(options, dict):
            raise ValueError(
                f"Config error: 'critic_options[{critic_name}]' must be an object/dict."
            )
        critic_options[critic_name] = dict(options)

    # Backward compatibility for legacy Frama-C specific keys.
    if "framac_wp_timeout_s" in cfg:
        framac_wp_timeout_s = _optional_int(cfg, "framac_wp_timeout_s", 2)
        framac_opts = dict(critic_options.get("framac-wp", {}))
        framac_opts.setdefault("wp_timeout", framac_wp_timeout_s)
        critic_options["framac-wp"] = framac_opts

    if "framac_wp_no_let" in cfg:
        framac_wp_no_let = _optional_bool(cfg, "framac_wp_no_let", False)
        if framac_wp_no_let:
            critic_context.setdefault("framac_wp_no_let", True)

    # Frama-C verification header can be provided directly in critic_options.
    framac_opts = dict(critic_options.get("framac-wp", {}))
    vht = framac_opts.get("verification_header_template_path")
    if vht is not None:
        if not isinstance(vht, str) or not vht.strip():
            raise ValueError(
                "Config error: 'critic_options[framac-wp][verification_header_template_path]' "
                "must be a non-empty string."
            )
        resolved_vht = _abspath(base_dir, vht.strip())
        _require_file(resolved_vht, "critic_options[framac-wp][verification_header_template_path]")
        framac_opts["verification_header_template_path"] = resolved_vht

    # Backward compatibility: map top-level verification_header_path into critic_options.
    legacy_verification_header_path = _optional_path(cfg, "verification_header_path", base_dir)
    if legacy_verification_header_path:
        _require_file(legacy_verification_header_path, "verification_header_path")
        framac_opts.setdefault("verification_header_template_path", legacy_verification_header_path)

    if framac_opts:
        critic_options["framac-wp"] = framac_opts


    # Required spec/interface paths (NO signature_path)
    natural_spec_path = _abspath(base_dir, _require_str(cfg, "natural_spec_path"))
    interface_path = _abspath(base_dir, _require_str(cfg, "interface_path"))

    _require_file(natural_spec_path, "natural_spec_path")
    _require_file(interface_path, "interface_path")

    # Headers: ONLY manifest ones; each must exist
    headers_items = _load_headers_from_manifest(headers_dir, headers_manifest)
    headers_json = json.dumps(headers_items)

    module_state_header = _find_header_by_name(headers_items, "module_state_and_constants.h")
    module_state_header_filename = module_state_header["filename"] if module_state_header else None
    module_state_header_content = module_state_header.get("content") if module_state_header else None

    prepared_inputs = PreparedCaseStudyInputs(
        input_natural_language_specification=_read_text_file(natural_spec_path),
        input_interface=_read_text_file(interface_path),
        input_type_definitions=_extract_type_defs_concat(headers_items),
        input_headers=headers_items,
        input_headers_json=headers_json,
        input_types_header_filename=_pick_types_header_filename(headers_items),
        headers_dir=headers_dir,
        module_state_header_filename=module_state_header_filename,
        module_state_header_content=module_state_header_content,
    )

    if not prepared_inputs.input_natural_language_specification.strip():
        raise ValueError(f"Config error: natural spec file is empty: {natural_spec_path}")
    if not prepared_inputs.input_interface.strip():
        raise ValueError(f"Config error: interface file is empty: {interface_path}")

    # Build prompt inputs dict for format_prompt
    prompt_inputs: Dict[str, str] = {
        "input_natural_language_specification": prepared_inputs.input_natural_language_specification,
        "input_interface": prepared_inputs.input_interface,
        "input_type_definitions": prepared_inputs.input_type_definitions,
        "input_headers_json": prepared_inputs.input_headers_json,
        "input_types_header_filename": prepared_inputs.input_types_header_filename,
    }
    filled_prompt = format_prompt(selected_prompt_template, prompt_inputs)

    # Build critic instances now (plug & play)
    critics_instances = build_critics_from_names(
        names=critics,
        solvers=solvers,
        timeout=timeout_s,
        critic_options=critic_options,
    )

    return PreparedConfig(
        raw_config=cfg,
        base_dir=base_dir,
        name=name,
        case_study=case_study,
        selected_prompt_template=selected_prompt_template,
        llms_used=llms_used,
        n_programs_generated=n_programs_generated,
        output_folder=output_folder,
        natural_spec_path=natural_spec_path,
        interface_path=interface_path,
        include_dirs=include_dirs,
        headers_dir=headers_dir,
        headers_manifest=headers_manifest,
        critics=critics,
        temperature=temperature,
        debug=debug,
        timeout_s=timeout_s,
        copy_headers_to_output=copy_headers_to_output,
        critic_context=critic_context,
        critic_options=critic_options,
        case_study_inputs=prepared_inputs,
        filled_prompt=filled_prompt,
        critics_instances=critics_instances,
    )


def load_and_prepare_configs(config_path: str, *, solvers: list) -> List[PreparedConfig]:
    abs_config_path = os.path.abspath(config_path)
    base_dir = os.path.dirname(abs_config_path) or os.getcwd()

    with open(abs_config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Config error: top-level JSON must be a list of configs.")

    prepared: List[PreparedConfig] = []
    for i, cfg in enumerate(data):
        if not isinstance(cfg, dict):
            raise ValueError(f"Config error: item {i} must be an object/dict.")
        prepared.append(_validate_and_prepare_one(cfg, base_dir, solvers=solvers))

    return prepared
