import json
import os
from typing import List, Dict, Optional, Any


def create_configuration(
    *,
    name: str,
    case_study: str,
    selected_prompt_template: str,
    llms_used: List[str],
    n_programs_generated: int,
    output_folder: str,
    temperature: float = 0.7,
    debug: bool = False,
    # new (optional) pipeline fields:
    headers_dir: Optional[str] = None,
    include_dirs: Optional[List[str]] = None,
    copy_headers_to_output: bool = True,
    headers_manifest: Optional[Dict[str, str]] = None,
    critics: Optional[List[str]] = None,
    timeout_s: int = 60,
) -> Dict[str, Any]:
    """
    Creates a pipeline configuration dict matching PipelineConfig.from_dict(...).

    Keep it plug & play:
      - critics: list of critic names, e.g. ["compile", "cppcheck-misra", ...]
      - headers_dir/include_dirs are optional; if omitted, you can still compile if headers are in default include paths.
    """
    cfg: Dict[str, Any] = {
        "name": name,
        "case_study": case_study,
        "selected_prompt_template": selected_prompt_template,
        "llms_used": llms_used,
        "n_programs_generated": n_programs_generated,
        "output_folder": output_folder,
        "temperature": temperature,
        "debug": debug,
        "timeout_s": timeout_s,
        "copy_headers_to_output": copy_headers_to_output,
    }

    if headers_dir is not None:
        cfg["headers_dir"] = headers_dir

    if include_dirs:
        cfg["include_dirs"] = list(include_dirs)

    if headers_manifest:
        cfg["headers_manifest"] = dict(headers_manifest)

    if critics:
        cfg["critics"] = list(critics)

    return cfg


def generate_systematic_configurations(
    *,
    case_studies: List[str],
    prompt_templates: List[str],
    llms_list: List[str],
    n_programs: int,
    base_output_folder: str = "./output",
    temperature: float = 0.7,
    debug: bool = False,
    # optional shared settings:
    case_studies_root: str = "../case_studies",
    include_dirs_extra: Optional[List[str]] = None,
    copy_headers_to_output: bool = True,
    headers_manifest: Optional[Dict[str, str]] = None,
    critics: Optional[List[str]] = None,
    timeout_s: int = 60,
) -> List[Dict[str, Any]]:
    """
    Systematically generates configurations.
    Assumes headers live at: {case_studies_root}/{case_study}/headers
    """
    configurations: List[Dict[str, Any]] = []
    count = 1

    include_dirs_extra = list(include_dirs_extra or [])

    for prompt_template in prompt_templates:
        for case_study in case_studies:
            config_name = f"config_{case_study}_{prompt_template}_{count}"
            output_folder = os.path.join(base_output_folder, config_name)

            headers_dir = os.path.join(case_studies_root, case_study, "headers")

            include_dirs = list(include_dirs_extra)
            # add headers_dir as an include dir (so gcc can find copied or original headers)
            include_dirs.append(headers_dir)

            configurations.append(
                create_configuration(
                    name=config_name,
                    case_study=case_study,
                    selected_prompt_template=prompt_template,
                    llms_used=llms_list,
                    n_programs_generated=n_programs,
                    output_folder=output_folder,
                    temperature=temperature,
                    debug=debug,
                    headers_dir=headers_dir,
                    include_dirs=include_dirs,
                    copy_headers_to_output=copy_headers_to_output,
                    headers_manifest=headers_manifest,
                    critics=critics,
                    timeout_s=timeout_s,
                )
            )
            count += 1

    return configurations


def save_configurations(configurations: List[Dict[str, Any]], file_path: str) -> None:
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(configurations, file, indent=2)
    print(f"Configurations saved to {file_path}")


def main() -> None:
    prompt_templates = ["zero-shot"]
    llms_list = ["gpt-4o"]
    case_studies = ["sgmm"]
    n_programs = 1

    headers_manifest = {
        "defined_types.h": "Project-wide typedefs/macros used everywhere. Always include this first via other headers.",
        "rtdb.h": "RTDB globals for inputs/outputs (extern declarations) used by the function under test.",
        "signals.h": "Signal status helpers/macros (if used).",
    }

    critics = [
        "compile",
        "cppcheck-misra",
        "framac-wp",
        "vernfr-control-flow",
        "vernfr-data-flow",
    ]

    configurations = generate_systematic_configurations(
        case_studies=case_studies,
        prompt_templates=prompt_templates,
        llms_list=llms_list,
        n_programs=n_programs,
        base_output_folder="../output",
        temperature=0.7,
        debug=True,
        case_studies_root="../case_studies",
        headers_manifest=headers_manifest,
        critics=critics,
        timeout_s=60,
    )

    save_configurations(configurations, "input/test-config.json")


if __name__ == "__main__":
    main()
