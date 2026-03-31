from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from spec2code.pipeline_modules.subprocess_creator import run_command
from spec2code.pipeline_modules.critics.critics_interface import CriticInput, CriticResult, Finding


class VernfrCritic:
    """
    Runs VernFr checks via a bash script.

    Success criteria:
      - If run_command exposes exit code: exit_code == 0
      - Otherwise: no obvious error patterns in (stdout+stderr)
    """

    name = "vernfr"

    def __init__(self, default_script_path: Optional[str] = None, timeout: int = 60):
        self.default_script_path = default_script_path
        self.timeout = int(timeout)

    def run(self, inp: CriticInput) -> CriticResult:
        c_file_path = inp["c_file_path"]
        timeout = int(inp.get("timeout", self.timeout))
        ctx: Dict[str, Any] = dict(inp.get("context", {}))

        if not os.path.exists(c_file_path):
            msg = f"File does not exist: {c_file_path}"
            return _fail(self.name, msg, c_file_path, metrics={"message": msg})

        folder = str(ctx.get("folder") or os.path.dirname(c_file_path) or ".")
        modname = str(ctx.get("modname") or _infer_modname(c_file_path))
        main = str(ctx.get("main") or "").strip()
        if not main:
            main = _infer_main_from_interface_text(str(ctx.get("interface_text") or "")) or "main"

        script_path = str(ctx.get("script_path") or self.default_script_path or "")
        if not script_path:
            msg = "Missing context['script_path'] (path to your bash runner)."
            return _fail(self.name, msg, c_file_path, metrics={"message": msg})

        if not os.path.exists(script_path):
            msg = f"Script not found: {script_path}"
            return _fail(self.name, msg, c_file_path, metrics={"message": msg, "script_path": script_path})

        # Build command
        cmd_parts: List[str] = [
            "bash",
            script_path,
            "--folder",
            folder,
            "--modname",
            modname,
            "--main",
            main,
        ]

        extra_args = list(ctx.get("extra_args", [])) + list(inp.get("extra_args", []))
        cmd_parts += [str(a) for a in extra_args]

        cmd = " ".join(_quote_if_needed(p) for p in cmd_parts)

        # If you can, update run_command to return (stdout, stderr, completed, exit_code)
        res = run_command(cmd, timeout)

        exit_code: Optional[int] = None
        timing: Dict[str, float] = {}
        if isinstance(res, tuple) and len(res) >= 5:
            stdout_str, stderr_str, completed, exit_code, timing = res[0], res[1], res[2], res[3], dict(res[4] or {})
        elif isinstance(res, tuple) and len(res) == 4:
            stdout_str, stderr_str, completed, exit_code = res
        else:
            stdout_str, stderr_str, completed = res  # type: ignore[misc]

        raw = _join_output(stdout_str, stderr_str)

        if not completed:
            msg = "Tool timeout"
            return _fail(
                self.name,
                msg,
                c_file_path,
                metrics={"message": msg, "command": cmd, "timeout": timeout},
                raw_output=raw,
            )

        # Prefer exit code if available
        if exit_code is not None and exit_code != 0:
            findings = _extract_findings(self.name, raw, c_file_path)
            summary = findings[0]["message"] if findings else f"VernFr failed (exit code {exit_code})."
            return {
                "tool": self.name,
                "success": False,
                "score": 0.0,
                "summary": summary,
                "metrics": {
                    "command": cmd,
                    "folder": folder,
                    "modname": modname,
                    "main": main,
                    "timeout": timeout,
                    "exit_code": exit_code,
                    "process_real_s": timing.get("real"),
                    "process_user_s": timing.get("user"),
                    "process_sys_s": timing.get("sys"),
                },
                "findings": findings,
                "raw_output": raw.strip(),
            }

        # Fallback heuristic when we do not have exit code:
        # treat any error-ish line anywhere in output as failure.
        error_like = _has_error(raw)
        if error_like:
            findings = _extract_findings(self.name, raw, c_file_path)
            summary = findings[0]["message"] if findings else "VernFr checks failed."
            return {
                "tool": self.name,
                "success": False,
                "score": 0.0,
                "summary": summary,
                "metrics": {
                    "command": cmd,
                    "folder": folder,
                    "modname": modname,
                    "main": main,
                    "timeout": timeout,
                    "exit_code": exit_code,
                    "process_real_s": timing.get("real"),
                    "process_user_s": timing.get("user"),
                    "process_sys_s": timing.get("sys"),
                },
                "findings": findings,
                "raw_output": raw.strip(),
            }

        return {
            "tool": self.name,
            "success": True,
            "score": 1.0,
            "summary": "VernFr checks passed.",
            "metrics": {
                "command": cmd,
                "folder": folder,
                "modname": modname,
                "main": main,
                "timeout": timeout,
                "exit_code": exit_code,
                "process_real_s": timing.get("real"),
                "process_user_s": timing.get("user"),
                "process_sys_s": timing.get("sys"),
            },
            "findings": [],
            "raw_output": raw.strip(),
        }


# -----------------------
# helpers
# -----------------------

def _infer_modname(c_file_path: str) -> str:
    base = os.path.basename(c_file_path)
    if base.endswith(".c"):
        return base[:-2]
    return os.path.splitext(base)[0]


def _infer_main_from_interface_text(interface_text: str) -> Optional[str]:
    txt = str(interface_text or "")
    if not txt.strip():
        return None

    m = re.search(r"entry_functions\s*:\s*\{(?P<body>.*?)\}", txt, flags=re.IGNORECASE | re.DOTALL)
    search_body = m.group("body") if m else txt

    m_fn = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", search_body)
    if m_fn:
        return m_fn.group(1)
    return None


def _quote_if_needed(s: str) -> str:
    return f"'{s}'" if any(ch.isspace() for ch in s) else s


def _join_output(stdout_str: Optional[str], stderr_str: Optional[str]) -> str:
    a = (stdout_str or "").rstrip()
    b = (stderr_str or "").rstrip()
    if a and b:
        return a + "\n" + b + "\n"
    return (a or b) + ("\n" if (a or b) else "")


def _fail(tool: str, msg: str, c_file_path: str, metrics: Dict[str, Any], raw_output: str = "") -> CriticResult:
    return {
        "tool": tool,
        "success": False,
        "score": 0.0,
        "summary": msg,
        "metrics": metrics,
        "findings": [{
            "tool": tool,
            "severity": "error",
            "message": msg,
            "location": {"file": c_file_path},
            "rule": None,
        }],
        "raw_output": raw_output,
    }


def _has_error(raw: str) -> bool:
    for line in raw.splitlines():
        if _looks_like_error(line):
            return True
    return False


def _extract_findings(tool: str, raw: str, c_file_path: str) -> List[Finding]:
    findings: List[Finding] = []

    current_rule: Optional[str] = None
    for line in raw.splitlines():
        m = re.search(r"Checking rule\s+([A-Za-z0-9_-]+)", line)
        if m:
            current_rule = m.group(1)
            continue

        if _looks_like_error(line):
            findings.append({
                "tool": tool,
                "severity": "error",
                "message": line.strip(),
                "location": {"file": c_file_path},
                "rule": current_rule,
            })

    if not findings:
        snippet = raw.strip().splitlines()[-1] if raw.strip() else "VernFr failed."
        findings.append({
            "tool": tool,
            "severity": "error",
            "message": snippet,
            "location": {"file": c_file_path},
            "rule": None,
        })

    return findings


def _looks_like_error(line: str) -> bool:
    s = line.strip().lower()
    if not s:
        return False
    return (
        "error:" in s
        or "unexpected error" in s
        or "backtrace" in s
        or "please report as 'crash'" in s
        or "please report as \"crash\"" in s
        or "fatal" in s
        or "assert" in s
        or "invalid" in s
        or "exception" in s
        or "failed" in s
        or "file not found" in s
        or "no such file" in s
    )
