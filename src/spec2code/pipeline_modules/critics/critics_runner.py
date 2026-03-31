from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from spec2code.pipeline_modules.critics.critics_interface import Critic, CriticInput, CriticResult
from spec2code.pipeline_modules.critics.critics_cppcheck_misra import CppcheckMisraCritic
from spec2code.pipeline_modules.critics.critics_framac_wp import FramaCWPCritic
from spec2code.pipeline_modules.critics.critics_compile import CompileCritic
from spec2code.pipeline_modules.critics.critics_vernfr import VernfrCritic


_MISRA_RULES_PATH = str(Path(__file__).with_name("misra_rules_2012.txt"))

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CONTROL_FLOW_SCRIPT = str(_REPO_ROOT / "tools" / "nfrcheck" / "scripts" / "control-flow-check.sh")
_DATA_FLOW_SCRIPT = str(_REPO_ROOT / "tools" / "nfrcheck" / "scripts" / "data-flow-check.sh")


def _fmt_duration(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def build_default_critics(
    *,
    solvers: list,
    timeout: int = 60,
    critic_options: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Critic]:
    opts = dict(critic_options or {})
    framac_opts = dict(opts.get("framac-wp", {}))
    framac_wp_timeout_s = int(framac_opts.get("wp_timeout", 2))
    framac_smoke_tests = bool(framac_opts.get("smoke_tests", False))
    framac_model = framac_opts.get("model", "real")
    framac_rte = bool(framac_opts.get("rte", True))

    return [
        CompileCritic(),
        CppcheckMisraCritic(misra_rules_path=_MISRA_RULES_PATH, timeout=timeout),
        FramaCWPCritic(
            solvers=solvers,
            wp_timeout=framac_wp_timeout_s,
            smoke_tests=framac_smoke_tests,
            timeout=timeout,
            model=framac_model,
            rte=framac_rte,
        ),
        VernfrCritic(
            default_script_path=_CONTROL_FLOW_SCRIPT,
            timeout=timeout,
        ),
        VernfrCritic(
            default_script_path=_DATA_FLOW_SCRIPT,
            timeout=timeout,
        ),
    ]


def build_critics_from_names(
    *,
    names: List[str],
    solvers: list,
    timeout: int = 60,
    critic_options: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Critic]:
    out: List[Critic] = []
    opts = dict(critic_options or {})

    for n in names:
        n_opts = dict(opts.get(n, {}))
        critic_timeout = int(n_opts.get("timeout", timeout))

        if n == "compile":
            out.append(CompileCritic())
        elif n == "cppcheck-misra":
            rules_path = str(n_opts.get("misra_rules_path", _MISRA_RULES_PATH))
            out.append(CppcheckMisraCritic(misra_rules_path=rules_path, timeout=critic_timeout))
        elif n == "framac-wp":
            wp_timeout = int(n_opts.get("wp_timeout", 2))
            smoke_tests = bool(n_opts.get("smoke_tests", False))
            model = n_opts.get("model", "real")
            rte = bool(n_opts.get("rte", True))
            out.append(
                FramaCWPCritic(
                    solvers=solvers,
                    wp_timeout=wp_timeout,
                    smoke_tests=smoke_tests,
                    timeout=critic_timeout,
                    model=model,
                    rte=rte,
                )
            )
        elif n == "vernfr-control-flow":
            script = str(n_opts.get("script_path", _CONTROL_FLOW_SCRIPT))
            critic = VernfrCritic(
                default_script_path=script,
                timeout=critic_timeout,
            )
            setattr(critic, "name", "vernfr-control-flow")
            out.append(critic)
        elif n == "vernfr-data-flow":
            script = str(n_opts.get("script_path", _DATA_FLOW_SCRIPT))
            critic = VernfrCritic(
                default_script_path=script,
                timeout=critic_timeout,
            )
            setattr(critic, "name", "vernfr-data-flow")
            out.append(critic)
        else:
            raise ValueError(f"Unknown critic name: {n}")

    return out


def run_critics_on_artifacts(
    *,
    critics,
    raw_c_path,
    spec_c_path: Optional[str] = None,
    compiled_output_path: Optional[str] = None,
    remove_compiled: Optional[bool] = None,
    timeout: int = 60,
    base_context: Optional[Dict[str, Any]] = None,
    include_dirs: Optional[List[str]] = None,
    defines: Optional[List[str]] = None,
    critic_targets: Optional[Dict[str, str]] = None,
    critic_configs: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Runs critics with consistent timing + aggregation.

    Targets:
      - "raw"  -> raw_c_path
      - "spec" -> spec_c_path (must be provided)
    """
    ctx_base: Dict[str, Any] = dict(base_context or {})
    if include_dirs:
        ctx_base["include_dirs"] = list(include_dirs)
    if defines:
        ctx_base["defines"] = list(defines)
    if compiled_output_path is not None:
        ctx_base["compiled_output_path"] = compiled_output_path
    if remove_compiled is not None:
        ctx_base["remove_compiled"] = remove_compiled

    targets = dict(critic_targets or {})
    configs = dict(critic_configs or {})
    if not targets:
        targets = {
            "compile": "raw",
            "cppcheck-misra": "raw",
            "framac-wp": "raw",
            "vernfr": "raw",
        }

    results: List[CriticResult] = []
    overall_success = True
    overall_score = 1.0

    critics_list = list(critics)
    total_critics = len(critics_list)
    if total_critics:
        print(f"[critics] running {total_critics} critic(s)...")

    for idx, critic in enumerate(critics_list, start=1):
        name = getattr(critic, "name", "") or "unknown"
        print(f"[critics] {idx}/{total_critics} start: {name}")

        n_cfg = dict(configs.get(name, {}))
        critic_timeout = int(n_cfg.get("timeout", timeout))

        which = targets.get(name, "raw")
        if which == "spec":
            if not spec_c_path:
                r: CriticResult = {
                    "tool": name,
                    "success": False,
                    "score": 0.0,
                    "summary": "Critic target missing.",
                    "metrics": {"message": "spec_c_path is required for this critic"},
                    "findings": [{
                        "tool": name,
                        "severity": "error",
                        "message": "spec_c_path is required for this critic",
                        "location": {"file": raw_c_path},
                        "rule": None,
                    }],
                    "raw_output": "",
                }
                results.append(r)
                overall_success = False
                overall_score = 0.0
                continue
            c_path = spec_c_path
        else:
            c_path = raw_c_path

        inp: CriticInput = {
            "c_file_path": c_path,
            "timeout": critic_timeout,
            "context": {**dict(ctx_base), **n_cfg},
        }

        t0 = time.perf_counter()
        r = critic.run(inp)
        elapsed = time.perf_counter() - t0

        r["metrics"] = dict(r.get("metrics", {}))
        r["metrics"]["elapsed_time_s"] = elapsed
        r["elapsed_time_s"] = elapsed

        results.append(r)
        overall_success = overall_success and bool(r["success"])
        overall_score = min(overall_score, float(r.get("score", 0.0)))

        status = "ok" if r.get("success") else "fail"
        print(f"[critics] {idx}/{total_critics} done: {name} {status} ({_fmt_duration(elapsed)})")

    return {
        "critics_success": overall_success,
        "critics_score": overall_score if results else 0.0,
        "critics_results": results,
    }
