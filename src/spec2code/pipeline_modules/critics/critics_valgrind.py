from __future__ import annotations

from spec2code.pipeline_modules.critics.critics_interface import CriticInput, CriticResult

import os
import re
from typing import Any, Dict, List, Tuple

from spec2code.pipeline_modules.subprocess_creator import run_command
from spec2code.pipeline_modules.critics.critics_interface import CriticInput, CriticResult, Finding

class ValgrindCritic:
    name = "valgrind"

    def run(self, inp: CriticInput) -> CriticResult:
        c_file_path = inp["c_file_path"]
        timeout = int(inp.get("timeout", 60))
        ctx: Dict[str, Any] = dict(inp.get("context", {}))

        compiled_output_path = ctx["compiled_output_path"]

        # Where to write massif report
        workdir = os.path.dirname(c_file_path) or None
        massif_path = os.path.join(workdir or ".", "massif.out")

        cmd_parts: List[str] = [
            "valgrind",
            "--tool=massif",
            f"--massif-out-file={massif_path}",
            "--stacks=yes",
            compiled_output_path,
        ]

        cmd = " ".join(cmd_parts).strip()

        res = run_command(cmd, timeout, cwd=workdir)

        timing: Dict[str, float] = {}

        if isinstance(res, tuple) and len(res) >= 5:
            stdout_str, stderr_str, completed, _exit_code, timing = res[0], res[1], res[2], res[3], dict(res[4] or {})
        elif isinstance(res, tuple) and len(res) == 4:
            stdout_str, stderr_str, completed, _exit_code = res
        else:
            stdout_str, stderr_str, completed = res  # type: ignore[misc]

        raw_output = (stdout_str or "") + "\n" + (stderr_str or "")

        if not completed:
            msg = "Valgrind timeout"
            return {
                "tool": self.name,
                "success": False,
                "score": 0.0,
                "summary": "Valgrind analysis failed.",
                "metrics": {
                    "message": msg,
                    "command": cmd,
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

        success = massif_analysis["peak_heap_bytes"] != None

        try:
            if os.path.exists(massif_path):
                os.remove(massif_path)
        except OSError:
            pass
        
        return {
            "tool": self.name,
            "success": success,
            "score": 1.0 if success else 0.0,
            "summary": massif_analysis["summary"],
            "metrics": {
                "command": cmd,
                "exit_code": _exit_code,
                "massif_report": massif_path,
                **massif_analysis["metrics"],
                "process_real_s": timing.get("real"),
                "process_user_s": timing.get("user"),
                "process_sys_s": timing.get("sys"),
            },
            "findings": massif_analysis["findings"],
            "raw_output": raw_output.strip(),
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
                f"Massif analysis completed. Peak heap: {peak_heap} bytes; "
                f"peak total memory including heap overhead and stacks: {peak_total} bytes."
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