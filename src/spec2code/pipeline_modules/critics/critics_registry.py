from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List

from spec2code.pipeline_modules.critics.critics_interface import Critic
from spec2code.pipeline_modules.critics.critics_compile import CompileCritic
from spec2code.pipeline_modules.critics.critics_cppcheck_misra import CppcheckMisraCritic
from spec2code.pipeline_modules.critics.critics_framac_wp import FramaCWPCritic
from spec2code.pipeline_modules.critics.critics_vernfr import VernfrCritic
from spec2code.pipeline_modules.critics.critics_valgrind import ValgrindCritic
from spec2code.pipeline_modules.critics.critics_binary_size import BinarySizeCritic


_REPO_ROOT = Path(__file__).resolve().parents[4]

DEFAULT_MISRA_RULES_PATH = "src/spec2code/pipeline_modules/critics/misra_rules_2012.txt"
_VERNFR_SCRIPTS_DIR = (
    (_REPO_ROOT / "tools" / "nfrcheck" / "scripts")
    if (_REPO_ROOT / "tools" / "nfrcheck" / "scripts").is_dir()
    else (_REPO_ROOT / "tools" / "vernfr" / "scripts")
)
DEFAULT_VERNFR_CONTROL_SCRIPT = (
    "tools/nfrcheck/scripts/control-flow-check.sh"
    if (_REPO_ROOT / "tools" / "nfrcheck" / "scripts").is_dir()
    else "tools/vernfr/scripts/control-flow-check.sh"
)
DEFAULT_VERNFR_DATA_SCRIPT = (
    "tools/nfrcheck/scripts/data-flow-check.sh"
    if (_REPO_ROOT / "tools" / "nfrcheck" / "scripts").is_dir()
    else "tools/vernfr/scripts/data-flow-check.sh"
)
DEFAULT_FRAMAC_FORMAL_PATH = "case_studies/shutdown_algorithm/headers/shutdown_algorithm_ver.h"
DEFAULT_VERNFR_INTERFACE_PATH = "case_studies/shutdown_algorithm/shutdown_algorithm.is"

_MISRA_RULES_PATH_ABS = str(Path(__file__).with_name("misra_rules_2012.txt"))
_CONTROL_FLOW_SCRIPT_ABS = str(_VERNFR_SCRIPTS_DIR / "control-flow-check.sh")
_DATA_FLOW_SCRIPT_ABS = str(_VERNFR_SCRIPTS_DIR / "data-flow-check.sh")


CriticBuilder = Callable[[Dict[str, Any], list, int], Critic]


def _build_compile(_opts: Dict[str, Any], _solvers: list, _timeout: int) -> Critic:
    return CompileCritic()


def _build_cppcheck_misra(opts: Dict[str, Any], _solvers: list, timeout: int) -> Critic:
    rules_path = str(opts.get("misra_rules_path", _MISRA_RULES_PATH_ABS))
    critic_timeout = int(opts.get("timeout", timeout))
    return CppcheckMisraCritic(misra_rules_path=rules_path, timeout=critic_timeout)


def _build_framac_wp(opts: Dict[str, Any], solvers: list, timeout: int) -> Critic:
    critic_timeout = int(opts.get("timeout", timeout))
    wp_timeout = int(opts.get("wp_timeout", 2))
    smoke_tests = bool(opts.get("smoke_tests", False))
    model = opts.get("model", "real")
    rte = bool(opts.get("rte", True))
    return FramaCWPCritic(
        solvers=solvers,
        wp_timeout=wp_timeout,
        smoke_tests=smoke_tests,
        timeout=critic_timeout,
        model=model,
        rte=rte,
    )


def _build_vernfr_control(opts: Dict[str, Any], _solvers: list, timeout: int) -> Critic:
    script = str(opts.get("script_path", _CONTROL_FLOW_SCRIPT_ABS))
    critic_timeout = int(opts.get("timeout", timeout))
    critic = VernfrCritic(default_script_path=script, timeout=critic_timeout)
    setattr(critic, "name", "vernfr-control-flow")
    return critic


def _build_vernfr_data(opts: Dict[str, Any], _solvers: list, timeout: int) -> Critic:
    script = str(opts.get("script_path", _DATA_FLOW_SCRIPT_ABS))
    critic_timeout = int(opts.get("timeout", timeout))
    critic = VernfrCritic(default_script_path=script, timeout=critic_timeout)
    setattr(critic, "name", "vernfr-data-flow")
    return critic

def _build_valgrind(opts: Dict[str, Any], _solvers: list, _timeout: int) -> Critic:
    use_massif = bool(opts.get("massif", False))
    use_memcheck = bool(opts.get("memcheck", True))
    return ValgrindCritic(massif=use_massif, memcheck=use_memcheck)

def _build_binary_size(opts: Dict[str, Any], _solvers: list, _timeout: int) -> Critic:
    limit = int(opts.get("binary_size_limit_bytes", 1024))
    return BinarySizeCritic(binary_size_limit_bytes=limit)

CRITIC_BUILDERS: Dict[str, CriticBuilder] = {
    "compile": _build_compile,
    "cppcheck-misra": _build_cppcheck_misra,
    "framac-wp": _build_framac_wp,
    "vernfr-control-flow": _build_vernfr_control,
    "vernfr-data-flow": _build_vernfr_data,
    "valgrind": _build_valgrind,
    "binary_size": _build_binary_size,
}


DEFAULT_CRITIC_NAMES: List[str] = [
    "compile",
    "cppcheck-misra",
    "framac-wp",
    "vernfr-control-flow",
    "vernfr-data-flow",
]


GUI_CRITICS_CATALOG: List[Dict[str, Any]] = [
    {
        "name": "compile",
        "label": "Compile",
        "default_enabled": True,
        "options": [
            {"key": "timeout", "type": "int", "label": "Timeout (s)", "default": 60},
            {
                "key": "test_harness_path",
                "type": "path",
                "label": "Test Harness C Path (optional)",
                "default": "",
                "ext": ".c",
            },
            {
                "key": "test_harness_source_name",
                "type": "string",
                "label": "Expected Source Name (from test harness)",
                "default": "",
            },
        ],
    },
    {
        "name": "cppcheck-misra",
        "label": "Cppcheck MISRA",
        "default_enabled": True,
        "options": [
            {"key": "timeout", "type": "int", "label": "Timeout (s)", "default": 60},
            {
                "key": "misra_rules_path",
                "type": "path",
                "label": "MISRA Rules Path",
                "default": DEFAULT_MISRA_RULES_PATH,
            },
        ],
    },
    {
        "name": "framac-wp",
        "label": "Frama-C WP",
        "default_enabled": True,
        "options": [
            {"key": "timeout", "type": "int", "label": "Timeout (s)", "default": 60},
            {"key": "wp_timeout", "type": "int", "label": "WP Timeout (s)", "default": 2},
            {"key": "solvers", "type": "string", "label": "Solvers (comma-separated)", "default": "Alt-Ergo"},
            {
                "key": "formal_c_path",
                "type": "path",
                "label": "Formal Spec Path",
                "default": DEFAULT_FRAMAC_FORMAL_PATH,
                "ext": ".c,.h",
            },
            {"key": "framac_wp_no_let", "type": "bool", "label": "No Let", "default": False},
            {"key": "model", "type": "string", "label": "Model", "default": "real"},
            {"key": "rte", "type": "bool", "label": "Enable RTE", "default": True},
            {"key": "smoke_tests", "type": "bool", "label": "Smoke Tests", "default": False},
        ],
    },
    {
        "name": "vernfr",
        "label": "Vernfr",
        "default_enabled": False,
        "options": [
            {"key": "timeout", "type": "int", "label": "Timeout (s)", "default": 60},
            {"key": "control_flow", "type": "bool", "label": "Enable Control Flow", "default": True},
            {"key": "data_flow", "type": "bool", "label": "Enable Data Flow", "default": True},
            {
                "key": "interface_path",
                "type": "path",
                "label": "Interface Path",
                "default": DEFAULT_VERNFR_INTERFACE_PATH,
                "ext": ".is",
            },
            {"key": "main", "type": "string", "label": "Main Function (optional)", "default": ""},
            {"key": "modname", "type": "string", "label": "Module Name (optional)", "default": ""},
            {
                "key": "control_script_path",
                "type": "path",
                "label": "Control Script Path",
                "default": DEFAULT_VERNFR_CONTROL_SCRIPT,
            },
            {
                "key": "data_script_path",
                "type": "path",
                "label": "Data Script Path",
                "default": DEFAULT_VERNFR_DATA_SCRIPT,
            },
        ],
    },
    {
        "name": "valgrind",
        "label": "Valgrind",
        "default_enabled": False,
        "options": [
            {"key": "timeout", "type": "int", "label": "Timeout (s)", "default": 60},
            {"key": "memcheck", "type": "bool", "label": "Memcheck", "default": True},
            {"key": "massif", "type": "bool", "label": "Massif", "default": False},
            {
                "key": "executable_args",
                "type": "string",
                "label": "Executable Args",
                "default": "",
            },
        ],
    },
    {
        "name": "binary_size",
        "label": "Binary Size",
        "default_enabled": True,
        "options": [
            {"key": "timeout", "type": "int", "label": "Timeout (s)", "default": 60},
            {"key": "binary_size_limit_bytes", "type": "int", "label": "Binary Size Limit (bytes)", "default": 1024},
        ],
    },
]
