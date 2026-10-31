from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, List

from spec2code.pipeline_modules.critics.critics_interface import Critic
from spec2code.pipeline_modules.critics.critics_compile import CompileCritic
from spec2code.pipeline_modules.critics.critics_cppcheck_misra import CppcheckMisraCritic
from spec2code.pipeline_modules.critics.critics_framac_wp import FramaCWPCritic
from spec2code.pipeline_modules.critics.critics_vernfr import VernfrCritic
from spec2code.pipeline_modules.critics.critics_valgrind import ValgrindCritic
from spec2code.pipeline_modules.critics.critics_binary_size import BinarySizeCritic
from spec2code.pipeline_modules.critics.critics_esbmc import ESBMCCritic
from spec2code.pipeline_modules.critics.critics_no_loops import NoLoopsCritic
from spec2code.pipeline_modules.critics.critics_polyspace_bug_finder import PolyspaceBugFinderCritic


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
    addons_value = opts.get("cppcheck_addons", "")
    if isinstance(addons_value, str):
        addons = [item.strip() for item in addons_value.split(",") if item.strip()]
    else:
        addons = [str(item) for item in addons_value or []]
    return CppcheckMisraCritic(
        misra_rules_path=rules_path,
        timeout=critic_timeout,
        enable_all=bool(opts.get("cppcheck_enable_all", False)),
        inconclusive=bool(opts.get("cppcheck_inconclusive", True)),
        check_level=str(opts.get("cppcheck_check_level", "exhaustive")),
        platform=str(opts.get("cppcheck_platform", "unix64")),
        max_ctu_depth=int(opts.get("cppcheck_max_ctu_depth", 10)),
        jobs=int(opts.get("cppcheck_jobs", 0)),
        gate_warnings=bool(opts.get("cppcheck_gate_warnings", True)),
        addons=addons,
    )


def _build_framac_wp(opts: Dict[str, Any], solvers: list, timeout: int) -> Critic:
    critic_timeout = int(opts.get("timeout", timeout))
    wp_timeout = int(opts.get("wp_timeout", 2))
    smoke_tests = bool(opts.get("smoke_tests", False))
    model = opts.get("model", "real")
    rte = bool(opts.get("rte", True))
    inline_calls = opts.get("inline-calls", opts.get("inline_calls"))
    configured_solvers = opts.get("solvers")
    if configured_solvers is None:
        framac_solvers = list(solvers or [])
    elif isinstance(configured_solvers, str):
        framac_solvers = [
            solver.strip() for solver in configured_solvers.split(",") if solver.strip()
        ]
    elif isinstance(configured_solvers, (list, tuple)):
        framac_solvers = [
            str(solver).strip() for solver in configured_solvers if str(solver).strip()
        ]
    else:
        raise ValueError("framac-wp option 'solvers' must be a list or comma-separated string")
    return FramaCWPCritic(
        solvers=framac_solvers,
        wp_timeout=wp_timeout,
        smoke_tests=smoke_tests,
        timeout=critic_timeout,
        model=model,
        rte=rte,
        inline_calls=inline_calls,
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
    heap_limit_bytes = int(opts.get("heap_limit_bytes", 0) or 0)
    stack_limit_bytes = int(opts.get("stack_limit_bytes", 0) or 0)
    use_massif = bool(opts.get("massif", False))
    use_memcheck = bool(opts.get("memcheck", True))
    return ValgrindCritic(
        massif=use_massif,
        memcheck=use_memcheck,
        heap_limit_bytes=heap_limit_bytes,
        stack_limit_bytes=stack_limit_bytes,
    )

def _build_binary_size(opts: Dict[str, Any], _solvers: list, _timeout: int) -> Critic:
    limit = int(opts.get("binary_size_limit_bytes", 1024))
    return BinarySizeCritic(binary_size_limit_bytes=limit)

def _build_esbmc(opts: Dict[str, Any], _solvers: list, _timeout: int) -> Critic:
    return ESBMCCritic(
        esbmc_options=opts.get("esbmc_options"),
        function_names=opts.get("function_names"),
        uninitialised_vars_check=bool(opts.get("uninitialised_vars_check", False)),
        struct_fields_check=bool(opts.get("struct_fields_check", False)),
        strict_types=bool(opts.get("strict_types", False)),
        ub_shift_check=bool(opts.get("ub_shift_check", False)),
        unsigned_overflow_check=bool(opts.get("unsigned_overflow_check", False)),
        stack_limit=opts.get("stack_limit"),
    )


def _build_no_loops(opts: Dict[str, Any], _solvers: list, timeout: int) -> Critic:
    return NoLoopsCritic(
        clang=str(opts.get("clang", "clang")),
        timeout=int(opts.get("timeout", timeout)),
    )


def _polyspace_command(opts: Dict[str, Any], key: str, command: str) -> str:
    configured = str(opts.get(key, "") or "").strip()
    if configured:
        return configured
    root = os.getenv("POLYSPACE_ROOT", "").strip()
    if root:
        return str(Path(root) / "polyspace" / "bin" / command)
    return command


def _build_polyspace_bug_finder(opts: Dict[str, Any], _solvers: list, timeout: int) -> Critic:
    return PolyspaceBugFinderCritic(
        executable=_polyspace_command(opts, "executable", "polyspace-bug-finder"),
        exporter=_polyspace_command(opts, "exporter", "polyspace-results-export"),
        timeout=int(opts.get("timeout", timeout)),
        options_file=str(opts.get("options_file", "") or ""),
        extra_options=opts.get("extra_options"),
        fail_on=str(opts.get("fail_on", "any") or "any"),
        results_root=str(opts.get("results_root", "") or ""),
    )

CRITIC_BUILDERS: Dict[str, CriticBuilder] = {
    "compile": _build_compile,
    "framac-wp": _build_framac_wp,
    "cppcheck-misra": _build_cppcheck_misra,
    "vernfr-control-flow": _build_vernfr_control,
    "vernfr-data-flow": _build_vernfr_data,
    "valgrind": _build_valgrind,
    "binary-size": _build_binary_size,
    "esbmc": _build_esbmc,
    "no-loops": _build_no_loops,
    "polyspace-bug-finder": _build_polyspace_bug_finder,
}


DEFAULT_CRITIC_NAMES: List[str] = [
    "compile",
    "no-loops",
    "framac-wp",
    "cppcheck-misra",
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
        "name": "framac-wp",
        "label": "Frama-C WP",
        "default_enabled": True,
        "options": [
            {"key": "timeout", "type": "int", "label": "Timeout (s)", "default": 60},
            {"key": "wp_timeout", "type": "int", "label": "WP Timeout (s)", "default": 2},
            {"key": "solvers", "type": "string", "label": "Solvers (comma-separated)", "default": "Alt-Ergo"},
            {
                "key": "inline-calls",
                "type": "string",
                "label": "Inline Calls (-inline-calls <arg>)",
                "default": "",
            },
            {
                "key": "formal_c_path",
                "type": "path",
                "label": "Formal Spec Path",
                "default": DEFAULT_FRAMAC_FORMAL_PATH,
                "ext": ".c,.h",
            },
            {"key": "framac_wp_no_qed", "type": "bool", "label": "Disable Qed", "default": False},
            {
                "key": "framac_wp_no_split_switch",
                "type": "bool",
                "label": "No Split Switch",
                "default": False,
            },
            {"key": "model", "type": "string", "label": "Model", "default": "real"},
            {"key": "rte", "type": "bool", "label": "Enable RTE", "default": True},
            {"key": "smoke_tests", "type": "bool", "label": "Smoke Tests", "default": False},
        ],
    },
    {
        "name": "cppcheck-misra",
        "label": "Cppcheck MISRA",
        "default_enabled": True,
        "options": [
            {"key": "timeout", "type": "int", "label": "Timeout (s)", "default": 120},
            {
                "key": "misra_rules_path",
                "type": "path",
                "label": "MISRA Rules Path",
                "default": DEFAULT_MISRA_RULES_PATH,
            },
            {
                "key": "cppcheck_enable_all",
                "type": "bool",
                "label": "Enable All (includes unused-function checks)",
                "default": False,
            },
            {"key": "cppcheck_inconclusive", "type": "bool", "label": "Inconclusive Findings", "default": True},
            {
                "key": "cppcheck_check_level",
                "type": "string",
                "label": "Check Level",
                "default": "exhaustive",
            },
            {"key": "cppcheck_platform", "type": "string", "label": "Target Platform", "default": "unix64"},
            {"key": "cppcheck_max_ctu_depth", "type": "int", "label": "Maximum CTU Depth", "default": 10},
            {"key": "cppcheck_jobs", "type": "int", "label": "Parallel Jobs (0 = Cppcheck default)", "default": 0},
            {
                "key": "cppcheck_check_library",
                "type": "bool",
                "label": "Check Library Models",
                "default": True,
            },
            {
                "key": "cppcheck_gate_warnings",
                "type": "bool",
                "label": "Fail on Warnings",
                "default": True,
            },
            {
                "key": "cppcheck_addons",
                "type": "string",
                "label": "Additional Addons (comma-separated)",
                "default": "",
            },
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
        "name": "binary-size",
        "label": "Binary Size",
        "default_enabled": False,
        "options": [
            {"key": "timeout", "type": "int", "label": "Timeout (s)", "default": 60},
            {"key": "binary_size_limit_bytes", "type": "int", "label": "Binary Size Limit (bytes)", "default": 1024},
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
            {"key": "heap_limit_bytes", "type": "int", "label": "Heap Limit (bytes)", "default": 0},
            {"key": "stack_limit_bytes", "type": "int", "label": "Stack Limit (bytes)", "default": 0},
            {
                "key": "executable_args",
                "type": "string",
                "label": "Executable Args",
                "default": "",
            },
        ],
    },
    {
        "name": "no-loops",
        "label": "No Loops, Goto, or Recursion",
        "default_enabled": True,
        "options": [
            {"key": "timeout", "type": "int", "label": "Timeout (s)", "default": 60},
            {"key": "clang", "type": "string", "label": "Clang Command", "default": "clang"},
        ],
    },
    {
        "name": "polyspace-bug-finder",
        "label": "Polyspace Bug Finder",
        "default_enabled": False,
        "options": [
            {"key": "timeout", "type": "int", "label": "Timeout (s)", "default": 900},
            {
                "key": "executable",
                "type": "path",
                "label": "Bug Finder Executable (optional)",
                "default": "",
            },
            {
                "key": "exporter",
                "type": "path",
                "label": "Results Export Executable (optional)",
                "default": "",
            },
            {
                "key": "options_file",
                "type": "path",
                "label": "Polyspace Options File (optional)",
                "default": "",
            },
            {
                "key": "extra_options",
                "type": "string",
                "label": "Additional Analysis Options",
                "default": "",
            },
            {
                "key": "fail_on",
                "type": "string",
                "label": "Fail On (any, warning, error)",
                "default": "any",
            },
            {
                "key": "results_root",
                "type": "path",
                "label": "Results Root (optional)",
                "default": "",
            },
        ],
    },
    {
        "name": "esbmc",
        "label": "ESBMC",
        "default_enabled": False,
        "options": [
            {"key": "timeout", "type": "int", "label": "Timeout (s)", "default": 60},
            {
                "key": "esbmc_options",
                "type": "string",
                "label": "ESBMC Options",
                "default": "",
            },
            {
                "key": "function_names",
                "type": "string",
                "label": (
                    "Function Names (optional; comma-separated; blank analyzes all "
                    "interface entry functions)"
                ),
                "default": "",
            },
            {
                "key": "uninitialised_vars_check",
                "type": "bool",
                "label": "Check Uninitialised Variables",
                "default": False,
            },
            {
                "key": "struct_fields_check",
                "type": "bool",
                "label": "Check Struct Field Reads",
                "default": False,
            },
            {
                "key": "strict_types",
                "type": "bool",
                "label": "Strict Types",
                "default": False,
            },
            {
                "key": "ub_shift_check",
                "type": "bool",
                "label": "Check Undefined Shift Behavior",
                "default": False,
            },
            {
                "key": "unsigned_overflow_check",
                "type": "bool",
                "label": "Check Unsigned Overflow",
                "default": False,
            },
            {
                "key": "stack_limit",
                "type": "int",
                "label": "Stack Limit (bits, optional)",
                "default": "",
            },
        ],
    },
]
