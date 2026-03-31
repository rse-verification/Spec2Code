# pipeline_modules/pipeline.py
from __future__ import annotations

import inspect

import json
import os
import re
import shutil
import time
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from spec2code.pipeline_modules.critics.critics_runner import run_critics_on_artifacts
from spec2code.pipeline_modules.filesystem_io import copy_files, export_json, write_file
from spec2code.pipeline_modules.runtime import Runtime

_JSON_BLOCK_RX = re.compile(r"\{.*\}", re.DOTALL)

# =============================================================================
# Small utilities
# =============================================================================
def _ensure_dir(path: str) -> None:
    if os.path.exists(path) and not os.path.isdir(path):
        try:
            os.remove(path)
        except OSError as e:
            raise RuntimeError(f"Expected directory but found file: {path}") from e
    try:
        os.makedirs(path, exist_ok=True)
    except FileExistsError:
        if os.path.exists(path) and os.path.isdir(path):
            return
        # Handle a file blocking the directory creation.
        if os.path.exists(path) and not os.path.isdir(path):
            try:
                os.remove(path)
                os.makedirs(path, exist_ok=True)
                return
            except OSError as e:
                raise RuntimeError(f"Expected directory but found file: {path}") from e
        raise


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

    if safe == raw and len(safe) <= 80:
        return safe

    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    base = safe[:60].rstrip("._-") or "model"
    return f"{base}-{digest}"


def _first_significant_line(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s
    return ""


def _remove_header_include(lines: List[str], header_name: str) -> List[str]:
    out: List[str] = []
    for line in lines:
        s = line.strip()
        if s.startswith("#include") and header_name in s:
            continue
        out.append(line)
    return out


def _inject_module_state_constants(c_code: str, header_name: str, header_content: str) -> str:
    if not header_content.strip():
        return c_code

    signature = _first_significant_line(header_content)
    if signature and signature in c_code:
        return c_code

    lines = c_code.splitlines()
    lines = _remove_header_include(lines, header_name)

    insert_at = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("#include"):
            insert_at = i + 1
        elif insert_at > 0:
            break

    injected = []
    injected.extend(lines[:insert_at])
    if insert_at > 0 and (injected and injected[-1].strip()):
        injected.append("")
    injected.append(header_content.rstrip())
    injected.append("")
    injected.extend(lines[insert_at:])
    return "\n".join(injected).strip("\n") + "\n"


def _copy_tree_flat(src_dir: str, dst_dir: str, *, extensions: Optional[List[str]] = None) -> None:
    """Fallback: copy files from src_dir into dst_dir (non-recursive)."""
    _ensure_dir(dst_dir)
    for name in os.listdir(src_dir):
        sp = os.path.join(src_dir, name)
        if not os.path.isfile(sp):
            continue
        if extensions and not any(name.endswith(ext) for ext in extensions):
            continue
        shutil.copy2(sp, os.path.join(dst_dir, name))


# =============================================================================
# Extract signature from interface + inject formal spec
# =============================================================================
_PROTOTYPE_RX = re.compile(
    r"(?m)^\s*(?:extern\s+)?(?:static\s+)?[A-Za-z_]\w*(?:\s+[*\w]+)*\s+[A-Za-z_]\w*\s*\([^;]*\)\s*;\s*$"
)


def extract_signature_from_interface(*, interface_text: str) -> str:
    """
    Finds exactly one C function prototype in interface_text and returns it (trimmed),
    e.g. "void sgmm_10ms(void);".
    """
    if not isinstance(interface_text, str) or not interface_text.strip():
        raise ValueError("Interface text is empty; cannot extract function signature.")

    matches = [m.group(0).strip() for m in _PROTOTYPE_RX.finditer(interface_text)]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one function prototype in interface; found {len(matches)}.")
    return matches[0]


def _signature_to_definition_regex(signature: str) -> re.Pattern:
    sig = (signature or "").strip()
    if not sig.endswith(";"):
        raise ValueError("Extracted signature must end with ';'")
    sig = sig[:-1].strip()

    esc = re.escape(sig).replace(r"\ ", r"\s+")
    return re.compile(rf"(?m)^(?P<def>(?:static\s+)?{esc})\s*\{{")


def inject_formal_spec_before_definition(*, c_code: str, interface_text: str, formal_spec: str) -> str:
    if not isinstance(c_code, str) or not c_code.strip():
        raise ValueError("Empty C code from LLM.")
    if not isinstance(formal_spec, str) or not formal_spec.strip():
        raise ValueError("Empty formal spec.")

    signature = extract_signature_from_interface(interface_text=interface_text)
    rx = _signature_to_definition_regex(signature)
    matches = list(rx.finditer(c_code))
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one function definition match for extracted signature; found {len(matches)}."
        )

    m = matches[0]
    insert_at = m.start("def")
    return c_code[:insert_at] + formal_spec.strip() + "\n" + c_code[insert_at:]


# =============================================================================
# LLM output parsing
# =============================================================================
def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()

def _find_key(text: str, key: str) -> int:
    # find "key" ignoring spaces around
    m = re.search(rf'"{re.escape(key)}"\s*:', text)
    return m.start() if m else -1

def _skip_ws(text: str, i: int) -> int:
    n = len(text)
    while i < n and text[i] in " \t\r\n":
        i += 1
    return i

def _parse_loose_string(text: str, i: int) -> Tuple[str, int]:
    """
    Parses either a JSON double-quoted string or a single-quoted string.
    Tolerates raw newlines/tabs inside the string by converting them to \n/\t.
    Returns (value, next_index_after_string).
    """
    n = len(text)
    if i >= n or text[i] not in ('"', "'"):
        raise ValueError("Expected string opening quote.")
    quote = text[i]
    i += 1

    out_chars = []
    while i < n:
        ch = text[i]

        if ch == quote:
            return "".join(out_chars), i + 1

        if ch == "\\":
            # keep common escapes if present; otherwise keep the escaped char
            i += 1
            if i >= n:
                break
            esc = text[i]
            if esc == "n":
                out_chars.append("\n")
            elif esc == "t":
                out_chars.append("\t")
            elif esc == "r":
                out_chars.append("\r")
            elif esc == "\\":
                out_chars.append("\\")
            elif esc == '"':
                out_chars.append('"')
            elif esc == "'":
                out_chars.append("'")
            else:
                out_chars.append(esc)
            i += 1
            continue

        # tolerate raw control chars inside strings
        if ch == "\n":
            out_chars.append("\n")
            i += 1
            continue
        if ch == "\t":
            out_chars.append("\t")
            i += 1
            continue
        if ch == "\r":
            i += 1
            continue

        out_chars.append(ch)
        i += 1

    raise ValueError("Unterminated string while parsing model output.")

def _extract_field(text: str, key: str) -> str:
    pos = _find_key(text, key)
    if pos < 0:
        raise ValueError(f"Missing key '{key}' in model output.")
    # move to after colon
    colon = text.find(":", pos)
    if colon < 0:
        raise ValueError(f"Malformed key '{key}' (no colon).")
    j = _skip_ws(text, colon + 1)
    val, _ = _parse_loose_string(text, j)
    return val

def _parse_jsonish_object(raw: str) -> Dict[str, Any]:
    raw = _strip_code_fences(raw)

    # First try strict JSON quickly (when it works, it is best)
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and "c" in obj and "h" in obj:
            return obj
    except Exception:
        pass

    # Otherwise: extract only c/h fields, even if the wrapper is broken
    c = _extract_field(raw, "c")
    h = _extract_field(raw, "h")

    # Optional extra field
    model = None
    try:
        model = _extract_field(raw, "model")
    except Exception:
        model = None

    out: Dict[str, Any] = {"c": c, "h": h}
    if model is not None:
        out["model"] = model
    return out

def _repair_json_with_raw_newlines(s: str) -> str:
    # Only attempt repair if it looks like {"c": " ... } style
    # Replace raw newlines inside any double-quoted string with \n
    out = []
    in_str = False
    esc = False
    for ch in s:
        if in_str:
            if esc:
                out.append(ch)
                esc = False
            else:
                if ch == '\\':
                    out.append(ch)
                    esc = True
                elif ch == '"':
                    out.append(ch)
                    in_str = False
                elif ch == '\n':
                    out.append('\\n')
                elif ch == '\r':
                    # drop or normalize
                    continue
                else:
                    out.append(ch)
        else:
            out.append(ch)
            if ch == '"':
                in_str = True
    return "".join(out)

def _extract_between(text: str, start: str, end: str) -> Optional[str]:
    i = text.find(start)
    if i < 0:
        return None
    i += len(start)
    j = text.find(end, i)
    if j < 0:
        return None
    return text[i:j].strip("\n")

def _get_model_text(output_llm: Any) -> str:
    # 1) preferred: output_llm.text()
    try:
        t = output_llm.text()
        if isinstance(t, str) and t.strip():
            return t
    except Exception:
        pass

    # 2) bedrock wrapper style: output_llm.json()["response"]["content"][0]["text"]
    try:
        j = output_llm.json()
        if isinstance(j, dict):
            resp = j.get("response")
            if isinstance(resp, dict):
                content = resp.get("content")
                if isinstance(content, list) and content:
                    t = content[0].get("text")
                    if isinstance(t, str) and t.strip():
                        return t
            # some wrappers might put it directly
            t = j.get("text")
            if isinstance(t, str) and t.strip():
                return t
    except Exception:
        pass

    return ""

def extract_llm_response_info(output_llm: Any) -> Dict[str, Any]:
    raw_text = _get_model_text(output_llm)
    if not raw_text.strip():
        raise ValueError("Model returned empty text output.")

    # 1) NEW format: sentinel blocks
    c = _extract_between(raw_text, "BEGIN_C\n", "\nEND_C")
    h = _extract_between(raw_text, "BEGIN_H\n", "\nEND_H")
    if c is not None and h is not None:
        return {
            "raw_output": raw_text,
            "code": c.strip(),
            "generated_header": h.strip(),
            "exact_model_used": "unknown",
        }

    # 2) fallback: strict JSON (old prompt)
    try:
        obj = json.loads(raw_text)
        return {
            "raw_output": raw_text,
            "code": (obj.get("c") or "").strip(),
            "generated_header": (obj.get("h") or "").strip(),
            "exact_model_used": obj.get("model", "unknown"),
        }
    except Exception as e:
        raise ValueError(
            "Model output was neither sentinel-block format nor valid JSON. "
            f"First 200 chars:\n{raw_text[:200]}"
        ) from e

# =============================================================================
# Settings containers
# =============================================================================
@dataclass(frozen=True)
class ArtifactPaths:
    raw_c: str
    raw_h: str
    compiled_out: str


@dataclass(frozen=True)
class PipelineSettings:
    timeout_s: int = 60
    remove_compiled: bool = True
    critic_targets: Optional[Dict[str, str]] = None  # critic.name -> "raw" | "spec"
    critic_context: Optional[Dict[str, Any]] = None
    critic_options: Optional[Dict[str, Dict[str, Any]]] = None

    def __post_init__(self):
        if self.critic_targets is None:
            object.__setattr__(self, "critic_targets", {
                "compile": "raw",
                "cppcheck-misra": "raw",
                "framac-wp": "raw",   # CHANGED
                "vernfr": "raw",
            })
        if self.critic_context is None:
            object.__setattr__(self, "critic_context", {})
        if self.critic_options is None:
            object.__setattr__(self, "critic_options", {})

# =============================================================================
# Artifacts + critics orchestration
# =============================================================================
def _materialize_artifacts(
    *,
    generated_code: str,
    generated_header: str,
    file_path: str,
) -> ArtifactPaths:
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

    return ArtifactPaths(raw_c=raw_c, raw_h=raw_h, compiled_out=compiled_out)

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
    """
    Writes:
      - RAW .c and .h (as returned by LLM)
    Runs critics via critics_runner:
      - compile/misra/vernfr on RAW
      - Frama-C WP on verification header when configured
    """
    settings = settings or PipelineSettings()

    out: Dict[str, Any] = {
        "code_raw_llm": generated_code,
        "generated_file_path": file_path,
    }

    # --- materialize artifacts ---
    try:
        out_dir = os.path.dirname(file_path) or "."
        _ensure_dir(out_dir)

        raw_c = file_path
        raw_h = os.path.splitext(file_path)[0] + ".h"
        acsl_path = os.path.splitext(file_path)[0] + ".acsl"
        compiled_out = os.path.splitext(file_path)[0] + ".out"

        # RAW .c
        if not write_file(raw_c, generated_code):
            raise RuntimeError("Failed to write raw .c to disk.")

        # RAW .h
        if not isinstance(generated_header, str) or not generated_header.strip():
            raise RuntimeError("LLM did not return a header (.h) content.")
        if not write_file(raw_h, generated_header):
            raise RuntimeError("Failed to write header to disk.")

        verification_header_path = None
        if verification_header_template_path:
            ver_name = os.path.basename(verification_header_template_path)
            verification_header_path = os.path.join(os.path.dirname(file_path), ver_name)
            shutil.copy2(verification_header_template_path, verification_header_path)

    except Exception as e:
        out["error"] = str(e)
        return out

    out["write_success"] = True
    out["generated_header_path"] = raw_h
    out["header_write_success"] = True
    if verification_header_template_path:
        out["verification_header_path"] = verification_header_path

    # --- run critics ---
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
        critic_targets=critic_targets,  # allow "framac-wp": "spec"
        base_context=base_context,  # FramaCWPCritic must consume this
        critic_configs=dict(getattr(settings, "critic_options", {}) or {}),
    )

    out.update(critics_out)
    out["verify_elapsed_time"] = time.perf_counter() - t0
    out["verify_success"] = bool(out.get("critics_success", False))
    out["verify_message"] = "All critics passed." if out["verify_success"] else "At least one critic failed."
    return out

# =============================================================================
# Prepared pipeline execution (Option 2)
# =============================================================================
@dataclass(frozen=True)
class PreparedPipelineConfig:
    """
    Output of config_loader.load_and_prepare_configs(...)
    """
    cfg: Any
    case_study_inputs: Dict[str, Any]
    filled_prompt: str
    include_dirs_final: List[str]
    critics: List[Any]
    settings: PipelineSettings


def execute_pipeline_prepared(prep, *, runtime: Runtime) -> None:
    """
    Runs a pipeline from a PreparedConfig produced by config_loader.load_and_prepare_configs().

    Expected fields on `prep` (PreparedConfig):
      - name, case_study, selected_prompt_template, llms_used, n_programs_generated
      - output_folder, headers_dir, copy_headers_to_output, temperature
      - include_dirs (already absolute), critics (already validated)
      - timeout_s, debug
      - case_study_inputs: PreparedCaseStudyInputs with:
          input_natural_language_specification, input_interface,
          input_headers_json, input_type_definitions, input_types_header_filename, headers_dir
      - (your config_loader can also precompute filled_prompt; if not, add it there)
    """

    cfg = prep  # PreparedConfig

    _log("=" * 70)
    _log(f"Pipeline start: {cfg.name}")
    _log(f"Case study: {cfg.case_study} | LLMs: {len(cfg.llms_used)} | Programs/LLM: {cfg.n_programs_generated}")
    _log("=" * 70)

    # Config loader should already have loaded these
    csi = cfg.case_study_inputs
    case_study_inputs: Dict[str, Any] = {
        "input_natural_language_specification": csi.input_natural_language_specification,
        "input_interface": csi.input_interface,
        "input_type_definitions": csi.input_type_definitions,
        "input_headers_json": csi.input_headers_json,
        "input_types_header_filename": csi.input_types_header_filename,
        "headers_dir": csi.headers_dir,
        "module_state_header_filename": csi.module_state_header_filename,
        "module_state_header_content": csi.module_state_header_content,
    }

    # If your loader already builds filled_prompt, use that.
    # Otherwise, import format_prompt + load templates and do it here.
    # Recommended: have loader compute it to keep this "prepared".
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

    # Critics should be built in the loader; if you instead store names, build them here.
    critics = getattr(cfg, "critics_instances", None)
    if critics is None:
        critics = getattr(cfg, "critics", None)
    if critics is None:
        raise RuntimeError(
            "PreparedConfig is missing critics instances. "
            "Build critics in config_loader and attach as 'critics_instances' "
            "(or change this function to build them from names)."
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
            _log(f"  [program {i+1}/{cfg.n_programs_generated}] prompt -> {llm_name}")

            output_llm = runtime.llms_available[llm_name].prompt(
                filled_prompt,
                stream=False,
                temperature=cfg.temperature,
            )

            entry: Dict[str, Any] = {}
            entry.update(extract_llm_response_info(output_llm))
            entry["filled_prompt"] = filled_prompt
            

            sample_dir = os.path.join(llm_dir, f"sample_{i:03d}")
            _ensure_dir(sample_dir)

            # Copy headers into each sample folder (Option A)
            if cfg.headers_dir and cfg.copy_headers_to_output:
                try:
                    if callable(copy_files):
                        copy_files(cfg.headers_dir, sample_dir)
                    else:
                        _copy_tree_flat(cfg.headers_dir, sample_dir)
                except Exception as e:
                    print(f"Warning: failed to copy headers from {cfg.headers_dir} to {sample_dir}: {e}")

            interface_path = getattr(cfg, "interface_path", None)
            if interface_path:
                try:
                    shutil.copy2(interface_path, os.path.join(sample_dir, os.path.basename(interface_path)))
                except Exception as e:
                    print(f"Warning: failed to copy interface spec from {interface_path} to {sample_dir}: {e}")

            if "error" not in entry:
                base = cfg.case_study
                c_path = os.path.join(sample_dir, f"{base}.c")

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

            elapsed_program = time.perf_counter() - start_time_program
            program_times.append(elapsed_program)
            avg_program = sum(program_times) / len(program_times)
            remaining_programs = cfg.n_programs_generated - (i + 1)
            eta_programs = avg_program * remaining_programs
            entry["total_elapsed_time_program"] = elapsed_program
            _log(
                f"  [program {i+1}/{cfg.n_programs_generated}] done in {_fmt_duration(elapsed_program)} "
                f"| avg {_fmt_duration(avg_program)} | eta {_fmt_duration(eta_programs)}"
            )
            llm_outputs[llm_name][i] = entry
            export_json(os.path.join(sample_dir, "output.json"), entry)

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

    # only pass the spec arg if the callee supports it; we do not use it anymore
    if "spec_c_path" in sig.parameters:
        kwargs["spec_c_path"] = None
    elif "spec_c_file_path" in sig.parameters:
        kwargs["spec_c_file_path"] = None

    return run_critics_on_artifacts(**kwargs)
