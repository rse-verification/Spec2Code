import os
import re
from typing import Any, Dict, List, Optional

from spec2code.pipeline_modules.subprocess_creator import run_command
from spec2code.pipeline_modules.critics.critics_interface import CriticInput, CriticResult, Finding


class FramaCWPCritic:
    """
    Frama-C WP critic.

    ACSL Importer disabled.
    """
    name = "framac-wp"

    def __init__(
        self,
        solvers: List[str],
        wp_timeout: int,
        smoke_tests: bool = False,
        timeout: int = 60,
        model: Optional[Any] = "real",
        rte: bool = True,
    ):
        self.solvers = solvers
        self.wp_timeout = wp_timeout
        self.smoke_tests = smoke_tests
        self.timeout = timeout
        self.model = model
        self.rte = rte

    def run(self, inp: CriticInput) -> CriticResult:
        c_file_path = inp["c_file_path"]
        timeout = inp.get("timeout", self.timeout)

        ctx = inp.get("context") or {}
        interface_text = ctx.get("interface_text")

        solvers = self.solvers or ["Alt-Ergo"]
        solvers_string = ",".join(solvers)

        parts: List[str] = ["frama-c"]

        native_extra: Dict[str, Any] = {}

        inline_targets = self._extract_inline_targets(interface_text)
        if inline_targets:
            native_extra["inline_targets"] = inline_targets

        # No -then or inlining; run WP directly on the selected file.
        parts += [f"'{c_file_path}'", "-wp"]
        if self.rte:
            parts += ["-wp-rte"]
        if ctx.get("framac_wp_no_let"):
            parts += ["-wp-no-let"]
        parts += [
            "-wp-status",
            f"-wp-prover {solvers_string}",
            f"-wp-timeout {int(self.wp_timeout)}",
        ]
        if self.smoke_tests:
            parts += ["-wp-smoke-tests"]
        if self.model:
            parts += [f"-wp-model {self.model}"]

        frama_c_command = " ".join(parts).strip()

        workdir = os.path.dirname(c_file_path) or None
        res = run_command(frama_c_command, timeout, cwd=workdir)
        timing: Dict[str, float] = {}
        if isinstance(res, tuple) and len(res) >= 5:
            stdout_str, stderr_str, completed, _exit_code, timing = res[0], res[1], res[2], res[3], dict(res[4] or {})
        elif isinstance(res, tuple) and len(res) == 4:
            stdout_str, stderr_str, completed, _exit_code = res
        else:
            stdout_str, stderr_str, completed = res  # type: ignore[misc]
        raw_output = (stdout_str or "") + "\n" + (stderr_str or "")

        # no ACSL preprocessing

        if not completed:
            return self._result(
                success=False,
                proved=0,
                total=0,
                summary="Timeout",
                raw_output=raw_output,
                findings=[
                    {
                        "tool": self.name,
                        "severity": "error",
                        "message": "Frama-C timed out.",
                        "location": {"file": c_file_path},
                        "rule": None,
                    }
                ],
                native={
                    "completed": False, 
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "command": frama_c_command,
                    "cwd": workdir,
                    "use_acsl_import": False,
                    "acsl_import_path": None,
                    "c_file_path": c_file_path,
                    "rte": self.rte,
                    "wp_timeout": self.wp_timeout,
                    "timeout": timeout,
                    "process_real_s": timing.get("real"),
                    "process_user_s": timing.get("user"),
                    "process_sys_s": timing.get("sys"),
                    **native_extra,
                },
            )

        return self._analyze_output(
            raw_output,
            c_file_path,
            frama_c_command,
                native_extra={
                "cwd": workdir,
                "use_acsl_import": False,
                "acsl_import_path": None,
                "c_file_path": c_file_path,
                "rte": self.rte,
                "wp_timeout": self.wp_timeout,
                    "timeout": timeout,
                    "process_real_s": timing.get("real"),
                    "process_user_s": timing.get("user"),
                    "process_sys_s": timing.get("sys"),
                    **native_extra,
                },
        )

    # -------------------------
    # Internal helpers
    # -------------------------

    def _bad_input(self, c_file_path: str, msg: str) -> CriticResult:
        return self._result(
            success=False,
            proved=0,
            total=0,
            summary="Invalid critic input.",
            raw_output="",
            findings=[
                {
                    "tool": self.name,
                    "severity": "error",
                    "message": msg,
                    "location": {"file": c_file_path},
                    "rule": None,
                }
            ],
            native={"bad_input": True},
        )

    def _analyze_output(
        self,
        output: str,
        c_file_path: str,
        command: str,
        *,
        native_extra: Optional[Dict[str, Any]] = None,
    ) -> CriticResult:
        native_base: Dict[str, Any] = {"command": command}
        if native_extra:
            native_base.update(native_extra)
        if "Syntax error" in output or "invalid user input" in output:
            cleaned = re.sub(r"\[kernel\].*?\n", "", output)
            return self._result(
                success=False,
                proved=0,
                total=0,
                summary=f"Syntax error detected:\n{cleaned}",
                raw_output=output,
                findings=[
                    {
                        "tool": self.name,
                        "severity": "error",
                        "message": "Syntax error / invalid input.",
                        "location": {"file": c_file_path},
                        "rule": None,
                    }
                ],
                native=native_base,
            )

        if "fatal error" in output:
            return self._result(
                success=False,
                proved=0,
                total=0,
                summary=f"Fatal error detected:\n{output}",
                raw_output=output,
                findings=[
                    {
                        "tool": self.name,
                        "severity": "error",
                        "message": "Fatal error.",
                        "location": {"file": c_file_path},
                        "rule": None,
                    }
                ],
                native=native_base,
            )

        proved, total = self._extract_verified_goals(output)

        if self._has_timeouts(output):
            timeout_details, timeout_findings = self._extract_timeout_details(output, c_file_path)
            return self._result(
                success=False,
                proved=proved,
                total=total,
                summary=timeout_details,
                raw_output=output,
                findings=timeout_findings,
                native={"timed_out_goals": True, **native_base},
            )

        success = (total > 0 and proved == total)
        summary = "Verification succeeded." if success else "Verification failed."

        findings: List[Finding] = []
        if not success:
            findings.append(
                {
                    "tool": self.name,
                    "severity": "error",
                    "message": "Not all goals proved.",
                    "location": {"file": c_file_path},
                    "rule": None,
                }
            )

        return self._result(
            success=success,
            proved=proved,
            total=total,
            summary=summary,
            raw_output=output,
            findings=findings,
            native=native_base,
        )

    def _has_timeouts(self, output: str) -> bool:
        m = re.search(r"(?m)^\s*Timeout:\s*(\d+)\b", output)
        if m:
            try:
                return int(m.group(1)) > 0
            except Exception:
                return True
        if re.search(r"(?m)^\s*Timeout\b", output):
            return True
        return "[Timeout]" in output

    def _extract_verified_goals(self, output: str) -> tuple[int, int]:
        try:
            proved_str = output.split("Proved goals:")[1].split("/")[0].strip()
            total_str = output.split("Proved goals:")[1].split("/")[1].strip().split("\n")[0].strip()
            return int(proved_str), int(total_str)
        except Exception:
            return 0, 0

    def _extract_timeout_details(self, output: str, c_file_path: str) -> tuple[str, List[Finding]]:
        timeout_lines: List[str] = []
        findings: List[Finding] = []

        for line in output.split("\n"):
            if "Goal" in line and "(file " in line:
                line_s = line.strip()
                timeout_lines.append(line_s)

                loc: Dict[str, Any] = {"file": c_file_path}
                m = re.search(r"line\s+(\d+)", line)
                if m:
                    loc["line"] = int(m.group(1))

                findings.append(
                    {
                        "tool": self.name,
                        "severity": "error",
                        "message": f"Timeout on: {line_s}",
                        "location": loc,
                        "rule": None,
                    }
                )

        if timeout_lines:
            summary = "Verification timed out. The following goals caused timeouts:\n" + "\n".join(timeout_lines)
        else:
            summary = "Verification timed out."

        return summary, findings

    def _extract_inline_targets(self, interface_text: Any) -> List[str]:
        if not isinstance(interface_text, str) or not interface_text.strip():
            return []

        entry_block = None
        m = re.search(r"entry_functions\s*:\s*\{(.*?)\}", interface_text, re.DOTALL)
        if m:
            entry_block = m.group(1)

        def extract_names(text: str) -> List[str]:
            out: List[str] = []
            for line in text.splitlines():
                s = line.strip().rstrip(",;")
                if not s:
                    continue
                tokens = re.findall(r"([A-Za-z_]\w*)\s*\(", s)
                if tokens:
                    out.append(tokens[-1])
            return out

        if entry_block:
            names = extract_names(entry_block)
            if names:
                return names

        prototype_rx = re.compile(
            r"(?m)^\s*(?:extern\s+)?(?:static\s+)?[A-Za-z_]\w*(?:\s+[*\w]+)*\s+[A-Za-z_]\w*\s*\([^;]*\)\s*;\s*$"
        )
        matches = [m.group(0).strip() for m in prototype_rx.finditer(interface_text)]
        names: List[str] = []
        for sig in matches:
            tokens = re.findall(r"([A-Za-z_]\w*)\s*\(", sig)
            if tokens:
                names.append(tokens[-1])
        return names


    def _result(
        self,
        success: bool,
        proved: int,
        total: int,
        summary: str,
        raw_output: str,
        findings: List[Finding],
        native: Optional[Dict[str, Any]] = None,
    ) -> CriticResult:
        score = 1.0 if success else (float(proved) / float(total) if total > 0 else 0.0)

        metrics: Dict[str, Any] = {
            "proved_goals": proved,
            "total_goals": total,
            "goals_ratio": f"{proved} / {total}",
        }
        if native is not None:
            metrics["native"] = native

        return {
            "tool": self.name,
            "success": success,
            "score": score,
            "summary": summary,
            "metrics": metrics,
            "findings": findings,
            "raw_output": raw_output,
        }
