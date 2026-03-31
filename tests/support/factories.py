from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def write_shutdown_case_study(root: Path) -> Dict[str, Path]:
    case_dir = root / "case_studies" / "shutdown_algorithm"
    headers_dir = case_dir / "headers"
    headers_dir.mkdir(parents=True, exist_ok=True)

    natural_spec = case_dir / "nlspec.txt"
    interface = case_dir / "shutdown_algorithm.is"
    ver_header = headers_dir / "shutdown_algorithm_ver.h"
    module_state = headers_dir / "module_state_and_constants.h"
    safety_types = headers_dir / "safety_types.h"
    public_header = headers_dir / "shutdown_algorithm.h"

    natural_spec.write_text("The module updates shutdown state.\n", encoding="utf-8")
    interface.write_text(
        "Module shutdown_algorithm {\n"
        "  entry_functions: {\n"
        "    void ShutdownAlgorithm_10ms(void)\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    ver_header.write_text(
        "#include <shutdown_algorithm.c>\n"
        "/*@ requires \\true; assigns \\nothing; */\n"
        "void ShutdownAlgorithm_10ms(void);\n",
        encoding="utf-8",
    )
    module_state.write_text(
        "#ifndef SHUTDOWN_MODULE_STATE_AND_CONSTANTS_H\n"
        "#define SHUTDOWN_MODULE_STATE_AND_CONSTANTS_H\n"
        "#include \"safety_types.h\"\n"
        "static tB g_rs_state[4] = {false, false, false, false};\n"
        "static tB g_hysteresis_state[4] = {false, false, false, false};\n"
        "#endif\n",
        encoding="utf-8",
    )
    safety_types.write_text(
        "#ifndef SAFETY_TYPES_H\n"
        "#define SAFETY_TYPES_H\n"
        "#include <stdbool.h>\n"
        "typedef bool tB;\n"
        "typedef unsigned char tU08;\n"
        "#endif\n",
        encoding="utf-8",
    )
    public_header.write_text(
        "#ifndef SHUTDOWN_ALGORITHM_H\n"
        "#define SHUTDOWN_ALGORITHM_H\n"
        "void ShutdownAlgorithm_10ms(void);\n"
        "#endif\n",
        encoding="utf-8",
    )

    return {
        "case_dir": case_dir,
        "headers_dir": headers_dir,
        "natural_spec_path": natural_spec,
        "interface_path": interface,
        "verification_header_path": ver_header,
    }


def build_config_dict(paths: Dict[str, Path], output_folder: str = "output/test_runs/shutdown") -> Dict[str, Any]:
    headers_dir = paths["headers_dir"]
    return {
        "name": "config_shutdown_algorithm_zero-shot",
        "case_study": "shutdown_algorithm",
        "selected_prompt_template": "zero-shot",
        "llms_used": ["test-llm-shutdown"],
        "n_programs_generated": 1,
        "output_folder": output_folder,
        "natural_spec_path": str(paths["natural_spec_path"]),
        "interface_path": str(paths["interface_path"]),
        "verification_header_path": str(paths["verification_header_path"]),
        "include_dirs": [str(headers_dir)],
        "headers_dir": str(headers_dir),
        "headers_manifest": {
            "safety_types.h": "Types.",
            "module_state_and_constants.h": "State.",
            "shutdown_algorithm.h": "Public API.",
        },
        "critics": ["compile"],
    }


def write_config(path: Path, configs: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(configs, indent=2), encoding="utf-8")
