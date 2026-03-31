from __future__ import annotations

import inspect
import os
import re
import shutil
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from spec2code.core.llm_output_parser import extract_llm_response_info
from spec2code.core.spec_injection import _inject_module_state_constants
from spec2code.pipeline_modules.critics.critics_runner import run_critics_on_artifacts
from spec2code.pipeline_modules.filesystem_io import copy_files, export_json, write_file


def _ensure_dir(path: str) -> None:
    if os.path.exists(path) and not os.path.isdir(path):
        try:
            os.remove(path)
        except OSError as e:
            raise RuntimeError(f"Expected directory but found file: {path}") from e
    try:
        os.makedirs(path, exist_ok=True)
    except FileNotFoundError:
        # Defensive retry for transient/mounted-filesystem races where parent
        # creation visibility lags behind a recursive makedirs call.
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        os.makedirs(path, exist_ok=True)
    except NotADirectoryError as e:
        raise RuntimeError(f"Expected directory path but found non-directory segment in: {path}") from e
    except FileExistsError:
        if os.path.exists(path) and os.path.isdir(path):
            return
        if os.path.exists(path) and not os.path.isdir(path):
            try:
                os.remove(path)
                os.makedirs(path, exist_ok=True)
                return
            except OSError as e:
                raise RuntimeError(f"Expected directory but found file: {path}") from e
        raise


def _copy_tree_flat(src_dir: str, dst_dir: str, *, extensions: Optional[List[str]] = None) -> None:
    _ensure_dir(dst_dir)
    for name in os.listdir(src_dir):
        sp = os.path.join(src_dir, name)
        if not os.path.isfile(sp):
            continue
        if extensions and not any(name.endswith(ext) for ext in extensions):
            continue
        shutil.copy2(sp, os.path.join(dst_dir, name))


def _materialize_verification_header(*, template_path: str, output_path: str, generated_c_filename: str) -> None:
    text = ""
    with open(template_path, "r", encoding="utf-8") as f:
        text = f.read()

    include_line = f'#include "{generated_c_filename}"'
    include_rx = re.compile(r'(?m)^\s*#\s*include\s*[<"]\s*[^>"\n]*\.c\s*[>"]\s*$')

    if include_rx.search(text):
        text = include_rx.sub(include_line, text, count=1)
    else:
        text = include_line + "\n\n" + text

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)


@dataclass(frozen=True)
class ArtifactPaths:
    raw_c: str
    raw_h: str
    compiled_out: str


@dataclass(frozen=True)
class PipelineSettings:
    timeout_s: int = 60
    remove_compiled: bool = True
    critic_targets: Optional[Dict[str, str]] = None
    critic_context: Optional[Dict[str, Any]] = None
    critic_options: Optional[Dict[str, Dict[str, Any]]] = None

    def __post_init__(self):
        if self.critic_targets is None:
            object.__setattr__(self, "critic_targets", {
                "compile": "raw",
                "cppcheck-misra": "raw",
                "framac-wp": "raw",
                "vernfr": "raw",
            })
        if self.critic_context is None:
            object.__setattr__(self, "critic_context", {})
        if self.critic_options is None:
            object.__setattr__(self, "critic_options", {})


def _run_critics_compat(*, critics, raw_c_path, compiled_output_path, remove_compiled, timeout,
                        include_dirs, critic_targets, base_context) -> Dict[str, Any]:
    sig = inspect.signature(run_critics_on_artifacts)
    kwargs = {
        "critics": critics,
        "raw_c_path": raw_c_path,
        "compiled_output_path": compiled_output_path,
        "remove_compiled": remove_compiled,
        "timeout": timeout,
        "include_dirs": include_dirs,
        "critic_targets": critic_targets,
        "base_context": base_context,
    }

    if "spec_c_path" in sig.parameters:
        kwargs["spec_c_path"] = None
    elif "spec_c_file_path" in sig.parameters:
        kwargs["spec_c_file_path"] = None

    return run_critics_on_artifacts(**kwargs)


def verify_artifacts(*, critics, paths, include_dirs, settings) -> Dict[str, Any]:
    t0 = time.perf_counter()
    critics_out = _run_critics_compat(
        critics=critics,
        raw_c_path=paths.raw_c,
        compiled_output_path=paths.compiled_out,
        remove_compiled=settings.remove_compiled,
        timeout=settings.timeout_s,
        include_dirs=include_dirs,
        critic_targets=settings.critic_targets,
        base_context={},
    )
    critics_out["verify_elapsed_time"] = time.perf_counter() - t0
    critics_out["verify_success"] = bool(critics_out.get("critics_success", False))
    critics_out["verify_message"] = "All critics passed." if critics_out["verify_success"] else "At least one critic failed."
    return critics_out


def process_llm_generated_code(
    *,
    generated_code: str,
    generated_header: str,
    file_path: str,
    interface_text: Optional[str] = None,
    verification_header_template_path: Optional[str] = None,
    debug: bool = False,
    include_dirs: List[str],
    critics: List[Any],
    settings: Optional[PipelineSettings] = None,
) -> Dict[str, Any]:
    settings = settings or PipelineSettings()

    out: Dict[str, Any] = {
        "code_raw_llm": generated_code,
        "generated_file_path": file_path,
    }

    try:
        out_dir = os.path.dirname(file_path) or "."
        _ensure_dir(out_dir)

        raw_c = file_path
        raw_h = os.path.splitext(file_path)[0] + ".h"
        compiled_out = os.path.splitext(file_path)[0] + ".out"

        if not write_file(raw_c, generated_code):
            raise RuntimeError("Failed to write raw .c to disk.")

        if not isinstance(generated_header, str) or not generated_header.strip():
            raise RuntimeError("LLM did not return a header (.h) content.")
        if not write_file(raw_h, generated_header):
            raise RuntimeError("Failed to write header to disk.")

        verification_header_path = None
        if verification_header_template_path:
            ver_name = os.path.basename(verification_header_template_path)
            verification_header_path = os.path.join(os.path.dirname(file_path), ver_name)
            _materialize_verification_header(
                template_path=verification_header_template_path,
                output_path=verification_header_path,
                generated_c_filename=os.path.basename(raw_c),
            )

    except Exception as e:
        out["error"] = str(e)
        return out

    out["write_success"] = True
    out["generated_header_path"] = raw_h
    out["header_write_success"] = True
    if verification_header_template_path:
        out["verification_header_path"] = verification_header_path

    t0 = time.perf_counter()
    use_ver_header = bool(verification_header_template_path)
    base_context: Dict[str, Any] = {}
    if interface_text:
        base_context["interface_text"] = interface_text
    if debug:
        base_context["debug"] = True
    base_context.update(dict(getattr(settings, "critic_context", {}) or {}))
    base_context["generated_header_path"] = raw_h

    critic_targets = dict(settings.critic_targets or {})
    if use_ver_header:
        critic_targets["framac-wp"] = "spec"

    critics_out = run_critics_on_artifacts(
        critics=critics,
        raw_c_path=raw_c,
        spec_c_path=verification_header_path if use_ver_header else None,
        compiled_output_path=compiled_out,
        remove_compiled=settings.remove_compiled,
        timeout=settings.timeout_s,
        include_dirs=include_dirs,
        critic_targets=critic_targets,
        base_context=base_context,
        critic_configs=dict(getattr(settings, "critic_options", {}) or {}),
    )

    out.update(critics_out)
    out["verify_elapsed_time"] = time.perf_counter() - t0
    out["verify_success"] = bool(out.get("critics_success", False))
    out["verify_message"] = "All critics passed." if out["verify_success"] else "At least one critic failed."
    return out
