from __future__ import annotations
import os
import re
from typing import Any, Dict, List, Sequence
import shlex

from spec2code.pipeline_modules.critics.critics_interface import CriticInput, CriticResult
from spec2code.pipeline_modules.subprocess_creator import run_command


class ESBMCCritic:
    """
    ESBMC Critic
    
    Runs ESBMC on the input C file and reports verification failures,
    including violated properties and associated counterexamples when present.

    Uses inp["c_file_path"].\n
    Optional via inp.get("context", {}):
      - include_dirs: List[str]         (default: [])
      - entry_functions: List[str]      (default: [])
      - function_names: List[str]|str   (default: [])
      - esbmc_options: List[str]|str    (default: [])

    Each interface entry function is checked independently. An optional function_names
    critic option overrides the interface entry-function list.
    """
    name = "esbmc"

    def __init__(
            self, 
            *, 
            esbmc_options: Sequence[str] | str | None = None,
            function_names: Sequence[str] | str | None = None,
            ):
        self.esbmc_options = _normalize_esbmc_options(esbmc_options)
        self.function_names = _normalize_function_names(function_names)

    def run(self, inp: CriticInput) -> CriticResult:
        c_file_path = inp["c_file_path"]
        timeout = int(inp.get("timeout", 60))
        ctx = dict(inp.get("context", {}))

        include_dirs: List[str] = list(ctx.get("include_dirs", []))
        esbmc_options = _normalize_esbmc_options(ctx.get("esbmc_options", self.esbmc_options))

        configured_function_names = _normalize_function_names(
            ctx.get("function_names", self.function_names)
        )
        function_names = configured_function_names or _normalize_function_names(
            ctx.get("entry_functions")
        )

        if not os.path.exists(c_file_path):
            msg = f"File does not exist: {c_file_path}"
            return {
                "tool": self.name,
                "success": False,
                "score": 0.0,
                "summary": "Could not find C file.",
                "metrics": {"message": msg},
                "findings": [{
                    "tool": self.name,
                    "severity": "error",
                    "message": msg,
                    "location": {"file": c_file_path},
                    "rule": None,
                }],
                "raw_output": msg,
            }

        if not function_names:
            msg = "No entry functions or function_names override were provided."
            return {
                "tool": self.name,
                "success": False,
                "score": 0.0,
                "summary": "No functions to analyze with ESBMC.",
                "metrics": {"message": msg},
                "findings": [{
                    "tool": self.name,
                    "severity": "error",
                    "message": msg,
                    "location": {"file": c_file_path},
                    "rule": None,
                }],
                "raw_output": msg,
            }
        
        runs: List[CriticResult] = []
        for function_name in function_names:
            runs.append(self._run_entry_function(
                c_file_path=c_file_path,
                timeout=timeout,
                include_dirs=include_dirs,
                esbmc_options=esbmc_options,
                entry_function=function_name,
            ))

        if len(runs) == 1:
            return runs[0]
        return _aggregate_esbmc_runs(function_names, runs)

    def _run_entry_function(
        self,
        *,
        c_file_path: str,
        timeout: int,
        include_dirs: List[str],
        esbmc_options: List[str],
        entry_function: str,
    ) -> CriticResult:
        include_args: List[str] = ["-I " + i for i in include_dirs]

        cmd_parts: List[str] = (
            ["esbmc"] +
            [c_file_path] +
            include_args +
            esbmc_options +
            ["--function", entry_function]
        )

        cmd = " ".join(shlex.quote(p) for p in cmd_parts)

        res = run_command(cmd, timeout)

        timing: Dict[str, float] = {}
        if isinstance(res, tuple) and len(res) >= 5:
            stdout_str, stderr_str, completed, _exit_code, timing = res[0], res[1], res[2], res[3], dict(res[4] or {})
        elif isinstance(res, tuple) and len(res) == 4:
            stdout_str, stderr_str, completed, _exit_code = res
        else:
            stdout_str, stderr_str, completed = res  # type: ignore[misc]
        raw = (stdout_str or "") + ("\n" if (stdout_str and stderr_str) else "") + (stderr_str or "")

        if not completed:
            msg = "ESBMC timeout"
            return {
                "tool": self.name,
                "success": False,
                "score": 0.0,
                "summary": msg,
                "metrics": {
                    "message": msg,
                    "command": cmd,
                    "entry_function": entry_function,
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
        parsed = _parse_esbmc_output(raw)
        findings = parsed["findings"]
        if findings:
            for finding in findings:
                if finding.get("location") is None:
                    finding["location"] = {"file": c_file_path}

        metrics = {
            "command": cmd,
            "entry_function": entry_function,
            "timeout": timeout,
            "process_real_s": timing.get("real"),
            "process_user_s": timing.get("user"),
            "process_sys_s": timing.get("sys"),
            **parsed["metrics"],
        }

        return {
            "tool": self.name,
            "success": parsed["success"],
            "score": 1.0 if parsed["success"] else 0.0,
            "summary": parsed["summary"],
            "metrics": metrics,
            "findings": findings,
            "raw_output": raw.strip(),
        }
    
    
# -----------------------
# helpers
# -----------------------


def _normalize_esbmc_options(value: Sequence[str] | str | None) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return shlex.split(stripped) if stripped else []
    return [str(part) for part in value if str(part).strip()]


def _normalize_function_names(value: Any) -> List[str]:
    if isinstance(value, str):
        values: Sequence[Any] = [value]
    elif isinstance(value, Sequence):
        values = value
    else:
        return []

    function_names: List[str] = []
    for item in values:
        for part in str(item).split(","):
            function_name = part.strip()
            if function_name and function_name not in function_names:
                function_names.append(function_name)
    return function_names


def _aggregate_esbmc_runs(
    entry_functions: List[str],
    runs: List[CriticResult],
) -> CriticResult:
    successful_runs = sum(1 for run in runs if run["success"])
    success = successful_runs == len(runs)
    findings: List[Dict[str, Any]] = []
    run_reports: List[Dict[str, Any]] = []
    raw_outputs: List[str] = []
    commands: Dict[str, str] = {}
    violations = 0

    for entry_function, run in zip(entry_functions, runs):
        run_metrics = dict(run.get("metrics", {}))
        command = run_metrics.get("command")
        if command:
            commands[entry_function] = str(command)

        run_violations = run_metrics.get("violations", 0)
        if isinstance(run_violations, int):
            violations += run_violations

        tagged_findings: List[Dict[str, Any]] = []
        for finding in run.get("findings", []):
            tagged_finding = dict(finding)
            tagged_finding["entry_function"] = entry_function
            tagged_finding["message"] = f"[{entry_function}] {finding.get('message', '')}".rstrip()
            tagged_findings.append(tagged_finding)
            findings.append(tagged_finding)

        raw_output = str(run.get("raw_output", ""))
        raw_outputs.append(f"===== ESBMC entry function: {entry_function} =====\n{raw_output}".rstrip())
        run_reports.append({
            "entry_function": entry_function,
            "success": bool(run["success"]),
            "score": float(run.get("score", 0.0)),
            "summary": str(run.get("summary", "")),
            "metrics": run_metrics,
            "findings": tagged_findings,
            "raw_output": raw_output,
        })

    summaries = "; ".join(
        f"{entry_function}: {run.get('summary', '')}"
        for entry_function, run in zip(entry_functions, runs)
    )

    return {
        "tool": ESBMCCritic.name,
        "success": success,
        "score": 1.0 if success else 0.0,
        "summary": f"ESBMC entry-function results: {summaries}",
        "metrics": {
            "verification_status": "successful" if success else "failed",
            "violations": violations,
            "entry_functions": list(entry_functions),
            "total_runs": len(runs),
            "successful_runs": successful_runs,
            "failed_runs": len(runs) - successful_runs,
            "commands": commands,
            "runs": run_reports,
        },
        "findings": findings,
        "raw_output": "\n\n".join(raw_outputs),
    }

def _parse_esbmc_output(output: str) -> Dict[str, Any]:
    text = output or ""
    stripped = text.strip()
    lower = text.lower()

    findings: List[Dict[str, Any]] = []
    metrics: Dict[str, Any] = {
        "verification_status": "unknown",
        "violations": 0,
    }

    if not stripped:
        return {
            "success": False,
            "summary": "ESBMC produced no output.",
            "metrics": metrics,
            "findings": [{
                "tool": ESBMCCritic.name,
                "severity": "error",
                "message": "ESBMC produced no output.",
                "location": None,
                "rule": None,
            }],
        }
    
    if "parsing error" in lower:
        return {
            "success": False,
            "summary": "ESBMC failed to parse C-file.",
            "metrics": metrics,
            "findings": [{
                "tool": ESBMCCritic.name,
                "severity": "error",
                "message": "Parsing error.",
                "location": None,
                "rule": None,
            }],
        }
    
    if "verification successful" in lower:
        metrics["verification_status"] = "successful"
        return {
            "success": True,
            "summary": "ESBMC verification succeeded.",
            "metrics": metrics,
            "findings": [],
        }

    

    violated = _extract_violation_findings(text)
    if "verification failed" in lower or violated:
        metrics["verification_status"] = "failed"
        metrics["violations"] = len(violated) or 1

        findings = violated or [{
            "tool": ESBMCCritic.name,
            "severity": "error",
            "message": "ESBMC verification failed.",
            "location": None,
            "rule": None,
        }]
        
        return {
            "success": False,
            "summary": "ESBMC verification failed.",
            "metrics": metrics,
            "findings": findings,
        }

    if "verification unknown" in lower:
        metrics["verification_status"] = "unknown"
        return {
            "success": False,
            "summary": "ESBMC verification result is unknown.",
            "metrics": metrics,
            "findings": [{
                "tool": ESBMCCritic.name,
                "severity": "error",
                "message": _first_relevant_line(text) or "ESBMC verification result is unknown.",
                "location": None,
                "rule": None,
            }],
        }
    
    

    error_line = _first_error_line(text)
    if error_line:
        metrics["verification_status"] = "error"
        return {
            "success": False,
            "summary": "ESBMC failed.",
            "metrics": metrics,
            "findings": [{
                "tool": ESBMCCritic.name,
                "severity": "error",
                "message": error_line,
                "location": _parse_location(error_line),
                "rule": None,
            }],
        }

    return {
        "success": False,
        "summary": "ESBMC output did not contain a verification result.",
        "metrics": metrics,
        "findings": [{
            "tool": ESBMCCritic.name,
            "severity": "error",
            "message": _first_relevant_line(text) or "ESBMC output did not contain a verification result.",
            "location": None,
            "rule": None,
        }],
    }


def _extract_violation_findings(output: str) -> List[Dict[str, Any]]:
    lines = output.splitlines()
    findings: List[Dict[str, Any]] = []
    i = 0
    counterexample_start: int | None = None
    while i < len(lines):
        if _is_counterexample_header(lines[i]):
            counterexample_start = i
            i += 1
            continue

        if "violated property" not in lines[i].lower():
            i += 1
            continue

        detail: List[str] = []
        j = i + 1
        while j < len(lines) and len(detail) < 5:
            line = lines[j].strip()
            if line:
                detail.append(line)
            elif detail:
                break
            j += 1

        message = "Violated property"
        if detail:
            message = f"{message}: " + " | ".join(detail)

        block = "\n".join([lines[i], *detail])
        counterexample = (
            _extract_counterexample_block(lines, counterexample_start, j)
            if counterexample_start is not None
            else ""
        )
        finding: Dict[str, Any] = {
            "tool": ESBMCCritic.name,
            "severity": "error",
            "message": message,
            "location": _parse_location(block),
            "rule": None,
        }
        if counterexample:
            finding["counter_example"] = _counterexample_format(counterexample)
        findings.append(finding)
        counterexample_start = None
        i = j

    return findings


def _is_counterexample_header(line: str) -> bool:
    return line.strip().lower() == "[counterexample]"


def _extract_counterexample_block(
    lines: List[str],
    start: int | None,
    end: int,
) -> str:
    if start is None:
        return ""

    block: List[str] = []
    for line in lines[start:end]:
        if block and _is_counterexample_header(line):
            break
        block.append(line.rstrip())

    return "\n".join(block).strip()


def _counterexample_format(counterexample: str) -> Dict[str, Any]:
    lines = counterexample.splitlines()
    states: List[Dict[str, Any]] = []
    current_state: Dict[str, Any] | None = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line == "[counterexample]":
            continue
        if set(line) == {"-"}:
            continue

        state_match = re.match(
            r"^State\s+(?P<state>\d+)"
            r"(?:\s+file\s+(?P<file>.+?)\s+line\s+(?P<line>\d+))?"
            r"(?:\s+function\s+(?P<function>\S+))?"
            r"(?:\s+thread\s+(?P<thread>\d+))?",
            line,
            flags=re.IGNORECASE,
        )
        if state_match:
            current_state = {
                "state": int(state_match.group("state")),
                "details": [],
            }
            file_name = state_match.group("file")
            line_number = state_match.group("line")
            function_name = state_match.group("function")
            thread_id = state_match.group("thread")

            if file_name:
                location: Dict[str, Any] = {"file": file_name.strip()}
                if line_number:
                    location["line"] = int(line_number)
                current_state["location"] = location
            if function_name:
                current_state["function"] = function_name
            if thread_id:
                current_state["thread"] = int(thread_id)

            states.append(current_state)
            continue

        if current_state is not None:
            current_state["details"].append(line)

    metric: Dict[str, Any] = {
        "state_count": len(states),
        "states": states
    }

    return metric

def _parse_location(text: str) -> Dict[str, Any] | None:
    m = re.search(r"\bfile\s+(.+?)\s+line\s+(\d+)(?:\s+column\s+(\d+))?", text)
    if m:
        loc: Dict[str, Any] = {"file": m.group(1).strip(), "line": int(m.group(2))}
        if m.group(3):
            loc["column"] = int(m.group(3))
        return loc

    m = re.search(r"(?m)([^:\s][^:\n]*):(\d+):(\d+)", text)
    if m:
        return {"file": m.group(1).strip(), "line": int(m.group(2)), "column": int(m.group(3))}

    m = re.search(r"(?m)([^:\s][^:\n]*):(\d+)", text)
    if m:
        return {"file": m.group(1).strip(), "line": int(m.group(2))}

    return None


def _first_error_line(output: str) -> str:
    for line in output.splitlines():
        s = line.strip()
        lower = s.lower()
        if s and ("error:" in lower or lower.startswith("error ") or "fatal error" in lower):
            return s
    return ""


def _first_relevant_line(output: str) -> str:
    for line in output.splitlines():
        s = line.strip()
        if s:
            return s
    return ""
