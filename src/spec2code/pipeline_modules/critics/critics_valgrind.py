from __future__ import annotations

import os
import re
import shlex
from typing import Any, Dict, List

from spec2code.pipeline_modules.subprocess_creator import run_command
from spec2code.pipeline_modules.critics.critics_interface import CriticInput, CriticResult, Finding

class ValgrindCritic:
    name = "valgrind"

    def __init__(
        self,
        massif: bool = False,
        memcheck: bool = True,
    ):
        self.massif = massif
        self.memcheck = memcheck

    def run(self, inp: CriticInput) -> CriticResult:
        c_file_path = inp["c_file_path"]
        timeout = int(inp.get("timeout", 60))
        ctx: Dict[str, Any] = dict(inp.get("context", {}))

        compiled_output_path = ctx["compiled_output_path"]
        workdir = os.path.dirname(c_file_path) or None
        quoted_exe = shlex.quote(compiled_output_path)
        findings: List[Finding] = []
        metrics: Dict[str, Any] = {}
        summaries: List[str] = []
        raw_outputs: List[str] = []
        commands: Dict[str, str] = {}
        exit_codes: Dict[str, Any] = {}
        process_timing: Dict[str, float] = {}
        success = True

        # ----- Run massif -----
        massif_analysis = {}
        massif_cmd = ""
        massif_path = ""

        if self.massif:

            # Where to write massif report
            massif_path = os.path.join(workdir or ".", "massif.out")

            cmd_parts: List[str] = [
                "valgrind",
                "--tool=massif",
                f"--massif-out-file={shlex.quote(massif_path)}",
                "--stacks=yes",
                quoted_exe,
            ]

            massif_cmd = " ".join(cmd_parts).strip()
            commands["massif"] = massif_cmd

            res = run_command(massif_cmd, timeout, cwd=workdir)

            timing: Dict[str, float] = {}

            if isinstance(res, tuple) and len(res) >= 5:
                stdout_str, stderr_str, completed, _exit_code, timing = res[0], res[1], res[2], res[3], dict(res[4] or {})
            elif isinstance(res, tuple) and len(res) == 4:
                stdout_str, stderr_str, completed, _exit_code = res
            else:
                stdout_str, stderr_str, completed = res  # type: ignore[misc]

            raw_output = (stdout_str or "") + "\n" + (stderr_str or "")
            raw_outputs.append(raw_output)
            exit_codes["massif"] = _exit_code
            for key, value in timing.items():
                process_timing[f"massif_{key}_s"] = value

            if not completed:
                msg = "Valgrind massif timeout"
                return {
                    "tool": self.name,
                    "success": False,
                    "score": 0.0,
                    "summary": "Valgrind analysis failed.",
                    "metrics": {
                        "message": msg,
                        "command": massif_cmd,
                        "timeout": timeout,
                        "process_real_s": timing.get("real"),
                        "process_user_s": timing.get("user"),
                        "process_sys_s": timing.get("sys"),
                    },
                    "findings": [{
                        "tool": self.name,
                        "severity": "error",
                        "message": msg,
                        "location": {"file": compiled_output_path},
                        "rule": None,
                    }],
                    "raw_output": raw_output.strip() or msg,
                }
            
            massif_analysis = self._analyze_massif(massif_path)
            success = success and massif_analysis["peak_heap_bytes"] is not None
            summaries.append(massif_analysis["summary"])
            metrics.update(massif_analysis["metrics"])
            findings.extend(massif_analysis["findings"])

            try:
                if os.path.exists(massif_path):
                    os.remove(massif_path)
            except OSError:
                pass

        # ----- Run memcheck -----
        if self.memcheck:
            memcheck_cmd = " ".join([
                "valgrind",
                "--tool=memcheck",
                "--leak-check=full",
                "--show-leak-kinds=all",
                "--errors-for-leak-kinds=definite,indirect,possible",
                "--error-exitcode=99",
                quoted_exe,
            ])
            commands["memcheck"] = memcheck_cmd

            res = run_command(memcheck_cmd, timeout, cwd=workdir)

            timing = {}
            if isinstance(res, tuple) and len(res) >= 5:
                stdout_str, stderr_str, completed, _exit_code, timing = res[0], res[1], res[2], res[3], dict(res[4] or {})
            elif isinstance(res, tuple) and len(res) == 4:
                stdout_str, stderr_str, completed, _exit_code = res
            else:
                stdout_str, stderr_str, completed = res  # type: ignore[misc]
                _exit_code = None

            raw_output = (stdout_str or "") + "\n" + (stderr_str or "")
            raw_outputs.append(raw_output)
            exit_codes["memcheck"] = _exit_code
            for key, value in timing.items():
                process_timing[f"memcheck_{key}_s"] = value

            if not completed:
                msg = "Valgrind memcheck timeout"
                return {
                    "tool": self.name,
                    "success": False,
                    "score": 0.0,
                    "summary": "Valgrind analysis failed.",
                    "metrics": {
                        "message": msg,
                        "commands": commands,
                        "timeout": timeout,
                        **process_timing,
                    },
                    "findings": [{
                        "tool": self.name,
                        "severity": "error",
                        "message": msg,
                        "location": {"file": compiled_output_path},
                        "rule": "memcheck-timeout",
                    }],
                    "raw_output": raw_output.strip() or msg,
                }

            memcheck_analysis = self._analyze_memcheck(raw_output, compiled_output_path)
            success = success and memcheck_analysis["success"]
            summaries.append(memcheck_analysis["summary"])
            metrics.update(memcheck_analysis["metrics"])
            findings.extend(memcheck_analysis["findings"])

        if not self.massif and not self.memcheck:
            success = False
            summaries.append("No Valgrind tools enabled.")
            findings.append({
                "tool": self.name,
                "severity": "warning",
                "message": "No Valgrind tools enabled.",
                "location": {"file": compiled_output_path},
                "rule": "valgrind-no-tools-enabled",
            })

        return {
            "tool": self.name,
            "success": success,
            "score": 1.0 if success else 0.0,
            "summary": " ".join(summaries),
            "metrics": {
                "commands": commands,
                "exit_codes": exit_codes,
                "massif_report": massif_path or None,
                **metrics,
                **process_timing,
            },
            "findings": findings,
            "raw_output": "\n".join(output.strip() for output in raw_outputs if output.strip()),
        }

    @staticmethod
    def _analyze_massif(report_path: str) -> Dict[str, Any]:
        if not os.path.exists(report_path):
            return {
                "summary": "Massif output file was not created.",
                "peak_heap_bytes": None,
                "metrics": {},
                "findings": [{
                    "tool": "valgrind",
                    "severity": "error",
                    "message": f"Missing Massif report: {report_path}",
                    "location": {"file": report_path},
                    "rule": "massif-report-missing",
                }],
            }

        snapshots: List[Dict[str, Any]] = []
        current: Dict[str, Any] = {}

        with open(report_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()

                if line.startswith("snapshot="):
                    if current:
                        snapshots.append(current)
                    current = {"snapshot": int(line.split("=", 1)[1])}

                elif "=" in line and current is not None:
                    key, value = line.split("=", 1)
                    if key in {
                        "time",
                        "mem_heap_B",
                        "mem_heap_extra_B",
                        "mem_stacks_B",
                    }:
                        try:
                            current[key] = int(value)
                        except ValueError:
                            current[key] = value
                    else:
                        current[key] = value

        if current:
            snapshots.append(current)

        if not snapshots:
            return {
                "summary": "Massif report contained no snapshots.",
                "peak_heap_bytes": None,
                "metrics": {"snapshot_count": 0},
                "findings": [{
                    "tool": "valgrind",
                    "severity": "error",
                    "message": "Massif report contained no snapshots.",
                    "location": {"file": report_path},
                    "rule": "massif-empty-report",
                }],
            }

        peak = max(
            snapshots,
            key=lambda s: int(s.get("mem_heap_B", 0))
        )

        peak_heap = int(peak.get("mem_heap_B", 0))
        peak_extra = int(peak.get("mem_heap_extra_B", 0))
        peak_stacks = int(peak.get("mem_stacks_B", 0))
        peak_total = peak_heap + peak_extra + peak_stacks

        findings = [{
            "tool": "valgrind",
            "severity": "info",
            "message": (
                f"Peak heap usage was {peak_heap} bytes."
            ),
            "location": {"file": report_path},
            "rule": "massif-peak-heap",
        }]

        return {
            "summary": (
                f"Massif analysis completed. Peak heap: {peak_heap} bytes."
            ),
            "peak_heap_bytes": peak_heap,
            "metrics": {
                "snapshot_count": len(snapshots),
                "peak_snapshot": peak.get("snapshot"),
                "peak_time": peak.get("time"),
                "peak_heap_bytes": peak_heap,
                "peak_heap_extra_bytes": peak_extra,
                "peak_stack_bytes": peak_stacks,
                "peak_total_bytes": peak_total,
            },
            "findings": findings,
        }

    @staticmethod
    def _analyze_memcheck(raw_output: str, location_file: str) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {}

        error_match = re.search(r"ERROR SUMMARY:\s+(\d+)\s+errors?", raw_output)
        error_count = int(error_match.group(1)) if error_match else None
        metrics["memcheck_error_count"] = error_count

        leak_keys = {
            "definitely": "definitely_lost_bytes",
            "indirectly": "indirectly_lost_bytes",
            "possibly": "possibly_lost_bytes",
            "still reachable": "still_reachable_bytes",
            "suppressed": "suppressed_bytes",
        }
        for label, key in leak_keys.items():
            match = re.search(rf"{re.escape(label)} lost:\s+([\d,]+)\s+bytes", raw_output)
            if not match and label in {"still reachable", "suppressed"}:
                match = re.search(rf"{re.escape(label)}:\s+([\d,]+)\s+bytes", raw_output)
            metrics[key] = int(match.group(1).replace(",", "")) if match else 0

        lost_bytes = (
            metrics["definitely_lost_bytes"]
            + metrics["indirectly_lost_bytes"]
            + metrics["possibly_lost_bytes"]
        )
        success = error_count == 0 and lost_bytes == 0

        findings: List[Finding] = []
        if success:
            findings.append({
                "tool": "valgrind",
                "severity": "info",
                "message": "Memcheck found no memory errors or actionable leaks.",
                "location": {"file": location_file},
                "rule": "memcheck-clean",
            })
            summary = "Memcheck completed with no memory errors or actionable leaks."
        else:
            if error_count is None:
                message = "Memcheck output did not include an error summary."
                rule = "memcheck-missing-summary"
            else:
                message = f"Memcheck found {error_count} errors and {lost_bytes} leaked bytes."
                rule = "memcheck-errors-or-leaks"
            findings.append({
                "tool": "valgrind",
                "severity": "error",
                "message": message,
                "location": {"file": location_file},
                "rule": rule,
            })
            summary = message

        return {
            "summary": summary,
            "success": success,
            "metrics": metrics,
            "findings": findings,
        }
