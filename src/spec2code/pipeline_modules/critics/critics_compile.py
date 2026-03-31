from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Tuple

from spec2code.pipeline_modules.subprocess_creator import run_command
from spec2code.pipeline_modules.critics.critics_interface import CriticInput, CriticResult, Finding


class CompileCritic:
    """
    GCC compile critic.

    Uses inp["c_file_path"].
    Optional via inp.get("context", {}):
      - compiled_output_path: str   (default: "<c_file_path>.o")
      - remove_compiled: bool       (default: True)
      - gcc: str                    (default: "gcc")
      - gcc_flags: List[str]        (default: ["-c"])
      - include_dirs: List[str]     (default: [])
      - defines: List[str]          (default: [])
    """

    name = "compile"

    def run(self, inp: CriticInput) -> CriticResult:
        c_file_path = inp["c_file_path"]
        timeout = int(inp.get("timeout", 60))
        ctx: Dict[str, Any] = dict(inp.get("context", {}))

        compiled_output_path = str(ctx.get("compiled_output_path", f"{c_file_path}.o"))
        remove_compiled = bool(ctx.get("remove_compiled", True))
        gcc = str(ctx.get("gcc", "gcc"))
        gcc_flags: List[str] = list(ctx.get("gcc_flags", ["-c"]))
        include_dirs: List[str] = list(ctx.get("include_dirs", []))
        defines: List[str] = list(ctx.get("defines", []))
        extra_args: List[str] = list(inp.get("extra_args", []))

        if not os.path.exists(c_file_path):
            msg = f"File does not exist: {c_file_path}"
            return {
                "tool": self.name,
                "success": False,
                "score": 0.0,
                "summary": "Compilation failed.",
                "metrics": {"message": msg, "compiled_output_path": compiled_output_path},
                "findings": [{
                    "tool": self.name,
                    "severity": "error",
                    "message": msg,
                    "location": {"file": c_file_path},
                    "rule": None,
                }],
                "raw_output": msg,
            }

        out_dir = os.path.dirname(compiled_output_path) or "."
        os.makedirs(out_dir, exist_ok=True)

        inc_args = [f"-I{d}" for d in include_dirs]
        def_args = [f"-D{d}" for d in defines]

        cmd_parts: List[str] = (
            [gcc]
            + gcc_flags
            + def_args
            + inc_args
            + [c_file_path, "-o", compiled_output_path]
            + extra_args
        )

        # quote only when needed
        cmd = " ".join(f"'{p}'" if any(ch.isspace() for ch in p) else p for p in cmd_parts)

        res = run_command(cmd, timeout)
        timing: Dict[str, float] = {}
        if isinstance(res, tuple) and len(res) >= 5:
            stdout_str, stderr_str, completed, _exit_code, timing = res[0], res[1], res[2], res[3], dict(res[4] or {})
        elif isinstance(res, tuple) and len(res) == 4:
            stdout_str, stderr_str, completed, _exit_code = res
        else:
            stdout_str, stderr_str, completed = res  # type: ignore[misc]
        raw = (stdout_str or "") + ("\n" if (stdout_str and stderr_str) else "") + (stderr_str or "")
        diagnostics = _extract_diagnostics(raw)

        if not completed:
            msg = "Compilation timeout"
            return {
                "tool": self.name,
                "success": False,
                "score": 0.0,
                "summary": "Compilation failed.",
                "metrics": {
                    "message": msg,
                    "command": cmd,
                    "compiled_output_path": compiled_output_path,
                    "timeout": timeout,
                    "process_real_s": timing.get("real"),
                    "process_user_s": timing.get("user"),
                    "process_sys_s": timing.get("sys"),
                },
                "findings": [{
                    "tool": self.name,
                    "severity": "error",
                    "message": msg,
                    "location": {"file": c_file_path},
                    "rule": None,
                }],
                "raw_output": raw.strip() or msg,
            }

        has_error = bool(diagnostics["errors"])
        has_warning = bool(diagnostics["warnings"])

        if not has_error and remove_compiled:
            try:
                if os.path.exists(compiled_output_path):
                    os.remove(compiled_output_path)
            except OSError:
                pass

        if not has_error and not has_warning:
            return {
                "tool": self.name,
                "success": True,
                "score": 1.0,
                "summary": "Compilation succeeded.",
                "metrics": {
                    "command": cmd,
                    "compiled_output_path": compiled_output_path,
                    "timeout": timeout,
                    "process_real_s": timing.get("real"),
                    "process_user_s": timing.get("user"),
                    "process_sys_s": timing.get("sys"),
                },
                "findings": [],
                "raw_output": raw.strip(),
            }

        if not has_error and has_warning:
            warning_findings: List[Finding] = [
                self._warning_finding(line, c_file_path) for line in diagnostics["warnings"]
            ]
            return {
                "tool": self.name,
                "success": True,
                "score": 0.9,
                "summary": "Compilation completed with warnings.",
                "metrics": {
                    "message": "Compilation warnings detected.",
                    "command": cmd,
                    "compiled_output_path": compiled_output_path,
                    "timeout": timeout,
                    "warnings": len(diagnostics["warnings"]),
                    "process_real_s": timing.get("real"),
                    "process_user_s": timing.get("user"),
                    "process_sys_s": timing.get("sys"),
                },
                "findings": warning_findings,
                "raw_output": raw.strip(),
            }

        msg = ("\n".join(diagnostics["errors"]) or raw or "Compilation failed.").strip()
        err_loc = self._parse_gcc_location(diagnostics["errors"][0]) if diagnostics["errors"] else None
        return {
            "tool": self.name,
            "success": False,
            "score": 0.0,
            "summary": "Compilation failed.",
            "metrics": {
                "message": msg,
                "command": cmd,
                "compiled_output_path": compiled_output_path,
                "timeout": timeout,
                "process_real_s": timing.get("real"),
                "process_user_s": timing.get("user"),
                "process_sys_s": timing.get("sys"),
            },
            "findings": [{
                "tool": self.name,
                "severity": "error",
                "message": msg,
                "location": err_loc or {"file": c_file_path},
                "rule": None,
            }],
            "raw_output": raw.strip() or msg,
        }

    def _parse_gcc_location(self, line: str) -> Dict[str, Any] | None:
        m = re.match(r"^(?P<file>.+?):(?P<line>\d+):(?P<col>\d+):\s*(?:warning|error):", line.strip())
        if not m:
            m = re.match(r"^(?P<file>.+?):(?P<line>\d+):\s*(?:warning|error):", line.strip())
        if not m:
            return None
        loc: Dict[str, Any] = {"file": m.group("file"), "line": int(m.group("line"))}
        if m.groupdict().get("col"):
            loc["column"] = int(m.group("col"))
        return loc

    def _warning_finding(self, line: str, default_file: str) -> Finding:
        loc = self._parse_gcc_location(line) or {"file": default_file}
        return {
            "tool": self.name,
            "severity": "warning",
            "message": line,
            "location": loc,
            "rule": None,
        }


def _extract_diagnostics(raw: str) -> Dict[str, List[str]]:
    warnings: List[str] = []
    errors: List[str] = []
    for line in (raw or "").splitlines():
        s = line.strip()
        if not s:
            continue
        lower = s.lower()
        if "warning:" in lower:
            warnings.append(s)
            continue
        if "error:" in lower or "fatal error" in lower or "undefined reference" in lower:
            errors.append(s)
    return {"warnings": warnings, "errors": errors}
