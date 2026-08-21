from __future__ import annotations

import os
import re
import shutil
import time
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List

from spec2code.core.artifacts import PipelineSettings, _copy_tree_flat, _ensure_dir, process_llm_generated_code
from spec2code.core.llm_output_parser import extract_llm_response_info
from spec2code.core.spec_injection import _inject_module_state_constants
from spec2code.pipeline_modules.filesystem_io import copy_files, export_json, write_file
from spec2code.pipeline_modules.runtime import Runtime
from src.spec2code.pipeline_modules.config_loader import PreparedConfig


def _now_stamp() -> str:
    return time.strftime("%H:%M:%S")


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


def _log(msg: str) -> None:
    print(f"[{_now_stamp()}] {msg}", flush=True)


def _llm_output_dir_name(llm_name: str) -> str:
    raw = str(llm_name or "").strip()
    if not raw:
        raw = "model"

    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._-")
    if not safe:
        safe = "model"

    if safe == raw and len(safe) <= 48:
        return safe

    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    base = safe[:24].rstrip("._-") or "model"
    return f"{base}-{digest}"


def _render_critic_timing_report(entry: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("Critic Timing Metrics")
    lines.append("=====================")
    lines.append("Definitions:")
    lines.append("- elapsed_time_s: wall-clock elapsed time measured around critic.run(...).")
    lines.append("- process_real_s: external command real time from `/usr/bin/time -p`.")
    lines.append("- process_user_s: CPU user time from `/usr/bin/time -p`.")
    lines.append("- process_sys_s: CPU kernel/system time from `/usr/bin/time -p`.")
    lines.append("")

    critics = list(entry.get("critics_results") or [])
    if not critics:
        lines.append("No critic results available.")
        return "\n".join(lines) + "\n"

    for r in critics:
        tool = str(r.get("tool", "unknown"))
        metrics = dict(r.get("metrics") or {})
        lines.append(f"[{tool}]")
        lines.append(f"elapsed_time_s={metrics.get('elapsed_time_s')}")
        lines.append(f"process_real_s={metrics.get('process_real_s')}")
        lines.append(f"process_user_s={metrics.get('process_user_s')}")
        lines.append(f"process_sys_s={metrics.get('process_sys_s')}")
        lines.append("")

    return "\n".join(lines) + "\n"


def _format_diagnostic_value(value: Any, *, indent: int = 0) -> List[str]:
    prefix = " " * indent

    if isinstance(value, dict):
        lines: List[str] = []
        for key, nested_value in value.items():
            if isinstance(nested_value, (dict, list)):
                lines.append(f"{prefix}- {key}:")
                lines.extend(_format_diagnostic_value(nested_value, indent=indent + 2))
            else:
                lines.append(f"{prefix}- {key}: {nested_value}")
        return lines

    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.extend(_format_diagnostic_value(item, indent=indent + 2))
            else:
                lines.append(f"{prefix}- {item}")
        return lines

    return [f"{prefix}{value}"]


def _format_diagnostic_payload_for_llm(diagnostic_payload: Dict[str, Any]) -> str:
    """
    Render critic diagnostics in a readable form for repair prompts.
    """

    lines: List[str] = [
        "Verification summary:",
        f"- Critics passed: {bool(diagnostic_payload.get('critics_success', False))}",
        f"- Critics score: {diagnostic_payload.get('critics_score')}",
        f"- Verification passed: {bool(diagnostic_payload.get('verify_success', False))}",
    ]

    verify_message = diagnostic_payload.get("verify_message")
    if verify_message:
        lines.append(f"- Verification message: {verify_message}")

    error = diagnostic_payload.get("error")
    if error:
        lines.extend(["", "Pipeline error:", str(error)])

    critics = [
        critic for critic in list(diagnostic_payload.get("critics_results") or [])
        if isinstance(critic, dict)
    ]
    lines.extend(["", "Failed critic diagnostics:"])

    if not critics:
        lines.append("- No failed critic diagnostics were captured.")
        return "\n".join(lines)

    for index, critic in enumerate(critics, start=1):
        tool = str(critic.get("tool") or f"critic_{index}")
        lines.extend(["", f"{index}. {tool}"])

        for key in ("summary", "findings", "metrics", "raw_output"):
            value = critic.get(key)
            if not value:
                continue

            title = key.replace("_", " ").title()
            if isinstance(value, (dict, list)):
                lines.append(f"{title}:")
                lines.extend(_format_diagnostic_value(value, indent=2))
            else:
                lines.append(f"{title}: {value}")

    return "\n".join(lines)


def _build_repair_prompt(
    *,
    original_prompt: str,
    attempt_entry: Dict[str, Any],
) -> str:
    """
    Builds an repair prompt based on the original prompt and critic feedback.

    Parameters
    ----------
    original_prompt:
        Original prompt created by the config loader.

    attempt_entry:
        Information about current generation attempt such as generated code and critic feedback.

    Returns
    -------
    str
        Modified repair prompt.
    """

    code = str(attempt_entry.get("code") or attempt_entry.get("code_raw_llm") or "")
    header = str(attempt_entry.get("generated_header") or "")
    critics_results = list(attempt_entry.get("critics_results") or [])
    failed_critics = [
        r for r in critics_results
        if isinstance(r, dict) and not bool(r.get("success", False))
    ]

    diagnostic_payload: Dict[str, Any] = {
        "critics_success": bool(attempt_entry.get("critics_success", False)),
        "critics_score": attempt_entry.get("critics_score"),
        "verify_success": bool(attempt_entry.get("verify_success", False)),
        "verify_message": attempt_entry.get("verify_message"),
    }

    # Extract diagnostics from critic results
    keep = ("tool", "summary", "findings", "metrics")

    critic_diagnostics: List[Dict] = []
    for critic in failed_critics:

        c_entry: Dict[str, Any] = {}
        for k in keep:

            value = critic.get(k, "")
            if not value:
                continue

            c_entry.update({k: value})
        
        critic_diagnostics.append(c_entry)

    diagnostic_payload["critics_results"] = critic_diagnostics

    if attempt_entry.get("error"):
        diagnostic_payload["error"] = attempt_entry.get("error")

    repair_prompt: List[str] = [
        "===== Original Task =====",
        "",
        original_prompt,
        "",
        "===== Previous Implementation =====",
        "",
        "Previous C code:",
        "```c",
        code,
        "```",
        ""
    ]

    if header:
        repair_prompt.extend([
            "Previous generated header:",
            "```c",
            header,
            "```",
            "",
        ])
    
    repair_prompt.extend([
        "===== Failed Verification =====",
        "",
        _format_diagnostic_payload_for_llm(diagnostic_payload),
        "",
        "===== Repair Objective =====",
        "",
        "Produce a corrected implementation that satisfies the original specification.",
        "Modify only what is necessary to resolve the reported verification failures.",
        "Return only the corrected implementation using the original output format."
    ])

    return "\n".join(repair_prompt)


@dataclass(frozen=True)
class PreparedPipelineConfig:
    cfg: Any
    case_study_inputs: Dict[str, Any]
    filled_prompt: str
    include_dirs_final: List[str]
    critics: List[Any]
    settings: PipelineSettings


def execute_pipeline_prepared(prep: PreparedConfig, *, runtime: Runtime) -> None:
    """
    Runs a pipeline from a PreparedConfig produced by config_loader.load_and_prepare_configs().

    Writes final results to llm_name/sample_xxx/ and intermediate attempts to llm_name/sample_xxx/attempt_xxx/

    Expected fields on `prep` (PreparedConfig):
      - name, case_study, selected_prompt_template, llms_used, n_programs_generated
      - output_folder, headers_dir, copy_headers_to_output, temperature
      - include_dirs (already absolute), critics (already validated)
      - timeout_s, debug
      - case_study_inputs: PreparedCaseStudyInputs with:
          input_natural_language_specification, input_interface,
          input_headers, input_types_header_filename, headers_dir
      - filled_prompt
    """

    cfg = prep

    _log("=" * 70)
    _log(f"Pipeline start: {cfg.name}")
    _log(f"Case study: {cfg.case_study} | LLMs: {len(cfg.llms_used)} | Programs/LLM: {cfg.n_programs_generated}")
    _log("=" * 70)

    csi = cfg.case_study_inputs
    case_study_inputs: Dict[str, Any] = {
        "input_natural_language_specification": csi.input_natural_language_specification,
        "input_interface": csi.input_interface,
        "input_headers": csi.input_headers,
        "input_types_header_filename": csi.input_types_header_filename,
        "headers_dir": csi.headers_dir,
        "module_state_header_filename": csi.module_state_header_filename,
    }

    filled_prompt = getattr(cfg, "filled_prompt", None)
    if not isinstance(filled_prompt, str) or not filled_prompt.strip():
        raise RuntimeError(
            "PreparedConfig is missing 'filled_prompt'. "
            "Compute it in config_loader and attach it to PreparedConfig."
        )

    include_dirs_final: List[str] = list(cfg.include_dirs)
    interface_text = str(case_study_inputs.get("input_interface", ""))
    if not interface_text.strip():
        raise ValueError("Prepared config error: input_interface is empty.")

    critics = getattr(cfg, "critics_instances", None)
    if critics is None:
        critics = getattr(cfg, "critics", None)
    if critics is None:
        raise RuntimeError(
            "PreparedConfig is missing critics instances."
        )

    timeout_s = int(getattr(cfg, "timeout_s", 60))
    settings = PipelineSettings(
        timeout_s=timeout_s,
        critic_context=dict(getattr(cfg, "critic_context", {}) or {}),
        critic_options=dict(getattr(cfg, "critic_options", {}) or {}),
    )

    start_time_total = time.perf_counter()

    llm_outputs: Dict[str, Any] = {}
    llm_outputs.update(case_study_inputs)
    llm_outputs.update(
        {
            "llms_used": cfg.llms_used,
            "n_programs_generated": cfg.n_programs_generated,
            "case_study": cfg.case_study,
            "name": cfg.name,
            "selected_prompt_template": cfg.selected_prompt_template,
            "filled_prompt": filled_prompt,
            "output_folder": cfg.output_folder,
            "temperature": cfg.temperature,
            "headers_dir": cfg.headers_dir,
            "include_dirs": include_dirs_final,
            "critics": getattr(cfg, "critics", None),
            "timeout_s": timeout_s,
        }
    )

    # Generate programs using specified LLMs
    for llm_name in cfg.llms_used:
        _log(f"LLM: {llm_name} (programs: {cfg.n_programs_generated})")

        llm_outputs[llm_name] = {}
        start_time_llm = time.perf_counter()
        program_times: List[float] = []

        llm_dir = os.path.join(cfg.output_folder, _llm_output_dir_name(llm_name))
        _ensure_dir(llm_dir)

        prompt_path = os.path.join(llm_dir, "prompt.txt")
        write_file(prompt_path, filled_prompt)

        for i in range(cfg.n_programs_generated):

            start_time_program = time.perf_counter()

            sample_dir = os.path.join(llm_dir, f"sample_{i:03d}")
            _ensure_dir(sample_dir)

            repair_prompt = filled_prompt
            max_generation_iterations = int(getattr(cfg, "max_generation_iterations", 1) or 1)
            max_generation_iterations = max(1, max_generation_iterations)

            attempts_made = 0

            entry: Dict[str, Any] = {}

            # Iterate code generation until all critics pass or reach limit
            for gen_iter in range(max_generation_iterations):
                _log(
                    f"  [program {i+1}/{cfg.n_programs_generated}] "
                    f"attempt {gen_iter+1}/{max_generation_iterations} | prompt -> {llm_name}"
                )

                attempts_made += 1

                start_time_attempt = time.perf_counter()

                attempt_dir = os.path.join(sample_dir, f"attempt_{gen_iter:03d}")
                _ensure_dir(attempt_dir)

                attempt_prompt_path = os.path.join(attempt_dir, "attempt_prompt.txt")
                write_file(attempt_prompt_path, repair_prompt)

                if cfg.headers_dir and cfg.copy_headers_to_output:
                    try:
                        if callable(copy_files):
                            copy_files(cfg.headers_dir, attempt_dir)
                        else:
                            _copy_tree_flat(cfg.headers_dir, attempt_dir)
                    except Exception as e:
                        print(f"Warning: failed to copy headers from {cfg.headers_dir} to {attempt_dir}: {e}")

                interface_path = getattr(cfg, "interface_path", None)
                if interface_path:
                    try:
                        shutil.copy2(interface_path, os.path.join(attempt_dir, os.path.basename(interface_path)))
                    except Exception as e:
                        print(f"Warning: failed to copy interface spec from {interface_path} to {attempt_dir}: {e}")

                output_llm = runtime.llms_available[llm_name].prompt(
                    repair_prompt,
                    stream=False,
                    temperature=cfg.temperature,
                )

                

                entry = {}
                entry.update(extract_llm_response_info(output_llm))
                entry["filled_prompt"] = repair_prompt
                entry["generation_iteration"] = gen_iter

                if "error" not in entry:
                    base = cfg.case_study
                    interface_path = str(getattr(cfg, "interface_path", "") or "").strip()
                    if interface_path:
                        stem = os.path.splitext(os.path.basename(interface_path))[0]
                        if stem:
                            base = stem
                    c_path = os.path.join(attempt_dir, f"{base}.c")

                    module_header_name = csi.module_state_header_filename
                    module_header_content = csi.module_state_header_content
                    if module_header_name and module_header_content:
                        entry["code"] = _inject_module_state_constants(
                            entry["code"],
                            module_header_name,
                            module_header_content,
                        )

                    entry.update(
                        process_llm_generated_code(
                            generated_code=entry["code"],
                            generated_header=entry.get("generated_header", ""),
                            file_path=c_path,
                            interface_text=interface_text,
                            verification_header_template_path=(
                                dict(getattr(cfg, "critic_options", {}) or {})
                                .get("framac-wp", {})
                                .get("verification_header_template_path")
                            ),
                            debug=bool(getattr(cfg, "debug", False)),
                            include_dirs=include_dirs_final,
                            critics=critics,
                            settings=settings,
                        )
                    )

                elapsed_attempt = time.perf_counter() - start_time_attempt
                entry["total_elapsed_time_attempt"] = elapsed_attempt
                entry["max_generation_iterations"] = max_generation_iterations

                stop: bool = False
                if bool(entry.get("critics_success", False)):
                    entry["generation_stop_reason"] = "all_critics_passed"
                    stop = True
                elif gen_iter >= max_generation_iterations - 1:
                    entry["generation_stop_reason"] = "max_generation_iterations_reached"
                    stop = True

                _log(
                    f"  [program {i+1}/{cfg.n_programs_generated}] "
                    f"attempt {gen_iter+1}/{max_generation_iterations} done in {_fmt_duration(elapsed_attempt)} "
                )

                export_json(os.path.join(attempt_dir, "output.json"), entry)
                write_file(os.path.join(attempt_dir, "output.txt"), _render_critic_timing_report(entry))
                
                if stop:
                    break

                repair_prompt = _build_repair_prompt(
                    original_prompt=filled_prompt,
                    attempt_entry=entry,
                )

            
            # Write final output statistics
            elapsed_program = time.perf_counter() - start_time_program
            program_times.append(elapsed_program)
            avg_program = sum(program_times) / len(program_times)
            remaining_programs = cfg.n_programs_generated - (i + 1)
            eta_programs = avg_program * remaining_programs
            entry["total_elapsed_time_program"] = elapsed_program
            entry["max_generation_iterations"] = max_generation_iterations
            entry["generation_attempt_count"] = attempts_made
            _log(
                f"  [program {i+1}/{cfg.n_programs_generated}] done in {_fmt_duration(elapsed_program)} "
                f"| avg {_fmt_duration(avg_program)} | eta {_fmt_duration(eta_programs)}"
            )
            llm_outputs[llm_name][i] = entry
            export_json(os.path.join(sample_dir, "output.json"), entry)
            write_file(os.path.join(sample_dir, "output.txt"), _render_critic_timing_report(entry))

        llm_elapsed = time.perf_counter() - start_time_llm
        llm_outputs[llm_name]["total_elapsed_time_llm"] = llm_elapsed
        export_json(os.path.join(llm_dir, "output.json"), llm_outputs[llm_name])
        _log(f"LLM done: {llm_name} in {_fmt_duration(llm_elapsed)}")

    total_elapsed = time.perf_counter() - start_time_total
    llm_outputs["total_elapsed_time"] = total_elapsed
    export_json(os.path.join(cfg.output_folder, "output_pipeline.json"), llm_outputs)

    _log("=" * 70)
    _log(f"Pipeline done: {cfg.name} in {_fmt_duration(total_elapsed)}")
    _log("=" * 70)
