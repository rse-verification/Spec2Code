import os
import re
import shlex
import shutil
import subprocess
import threading
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from spec2code.pipeline_modules.critics.critics_interface import CriticInput, CriticResult, Finding


class CppcheckMisraCritic:
    name = "cppcheck-misra"

    def __init__(
        self,
        misra_rules_path: str,
        timeout: int = 600,
        *,
        enable_all: bool = False,
        inconclusive: bool = True,
        check_level: str = "exhaustive",
        platform: str = "unix64",
        max_ctu_depth: int = 10,
        jobs: int = 0,
        gate_warnings: bool = True,
        addons: Optional[List[str]] = None,
    ):
        self.misra_rules_path = misra_rules_path
        self.timeout = timeout
        self.enable_all = enable_all
        self.inconclusive = inconclusive
        self.check_level = check_level
        self.platform = platform
        self.max_ctu_depth = max_ctu_depth
        self.jobs = jobs
        self.gate_warnings = gate_warnings
        self.addons = list(addons or [])

    def _dump_command(self, c_file_path: str, ctx: Dict[str, Any]) -> str:
        enable_all = bool(ctx.get("cppcheck_enable_all", self.enable_all))
        enabled = "all" if enable_all else "warning,style,performance,portability,information,missingInclude"
        parts = [
            "cppcheck",
            f"--enable={enabled}",
            "--language=c",
            "--std=c11",
            "--force",
            "--xml",
            "--xml-version=2",
            "--dump",
        ]
        if bool(ctx.get("cppcheck_inconclusive", self.inconclusive)):
            parts.append("--inconclusive")
        check_level = str(ctx.get("cppcheck_check_level", self.check_level) or "").strip()
        if check_level:
            parts.append(f"--check-level={check_level}")
        platform = str(ctx.get("cppcheck_platform", self.platform) or "").strip()
        if platform:
            parts.append(f"--platform={platform}")
        max_ctu_depth = int(ctx.get("cppcheck_max_ctu_depth", self.max_ctu_depth) or 0)
        if max_ctu_depth > 0:
            parts.append(f"--max-ctu-depth={max_ctu_depth}")
        jobs = int(ctx.get("cppcheck_jobs", self.jobs) or 0)
        if jobs > 0:
            parts.extend(["-j", str(jobs)])
        if bool(ctx.get("cppcheck_check_library", True)):
            parts.append("--check-library")
        for include_dir in ctx.get("include_dirs", []) or []:
            parts.extend(["-I", str(include_dir)])
        for define in ctx.get("defines", []) or []:
            parts.append(f"-D{define}")
        addons = ctx.get("cppcheck_addons", self.addons)
        if isinstance(addons, str):
            addons = [item.strip() for item in addons.split(",") if item.strip()]
        for addon in addons or []:
            parts.append(f"--addon={addon}")
        parts.append(c_file_path)
        return " ".join(shlex.quote(part) for part in parts)

    def run(self, inp: CriticInput) -> CriticResult:
        c_file_path = inp["c_file_path"]
        timeout = int(inp.get("timeout", self.timeout))
        ctx: Dict[str, Any] = dict(inp.get("context", {}))
        debug = bool(ctx.get("debug", False))

        # Stream logs in debug or if explicitly enabled
        stream_logs = bool(ctx.get("stream_cppcheck_logs", False) or debug)

        workdir = os.path.dirname(c_file_path) or None

        dump_cmd = self._dump_command(c_file_path, ctx)
        if debug:
            print(f"[cppcheck-misra] dump command: {dump_cmd}")

        dump_res = _run_command_streaming(
            dump_cmd,
            timeout_s=timeout,
            cwd=workdir,
            stream=stream_logs,
            prefix="[cppcheck-misra][dump] ",
        )
        if isinstance(dump_res, tuple) and len(dump_res) >= 5:
            dump_stdout, dump_stderr, dump_timed_out, dump_rc, dump_timing = dump_res[0], dump_res[1], dump_res[2], dump_res[3], dict(dump_res[4] or {})
        else:
            dump_stdout, dump_stderr, dump_timed_out, dump_rc = dump_res  # type: ignore[misc]
            dump_timing = {}

        dump_log = (dump_stdout or "") + "\n" + (dump_stderr or "")
        self._write_log(workdir, "cppcheck_dump.log", dump_log)

        # Dump must succeed (rc == 0) and not time out
        if dump_timed_out or dump_rc != 0:
            return self._result_from_counts(
                success=False,
                required=0,
                advisory=0,
                undefined=0,
                raw_output=dump_log,
                summary=f"cppcheck dump failed (rc={dump_rc}, timed_out={dump_timed_out}):\n{dump_log}",
                native={
                    "dump_completed": not dump_timed_out,
                    "dump_returncode": dump_rc,
                    "dump_timed_out": dump_timed_out,
                    "dump_stdout": dump_stdout,
                    "dump_stderr": dump_stderr,
                    "dump_command": dump_cmd,
                    "dump_timeout_s": timeout,
                    "dump_real_s": dump_timing.get("real"),
                    "dump_user_s": dump_timing.get("user"),
                    "dump_sys_s": dump_timing.get("sys"),
                    "dump_log_path": self._log_path(workdir, "cppcheck_dump.log"),
                    "cwd": workdir,
                },
            )

        dump_path = f"{c_file_path}.dump"
        if not os.path.exists(dump_path):
            return self._result_from_counts(
                success=False,
                required=0,
                advisory=0,
                undefined=0,
                raw_output=dump_log,
                summary=f"cppcheck did not create dump file: {dump_path}\n{dump_log}",
                native={
                    "dump_completed": True,
                    "dump_returncode": dump_rc,
                    "dump_stdout": dump_stdout,
                    "dump_stderr": dump_stderr,
                    "dump_path_missing": dump_path,
                    "dump_command": dump_cmd,
                    "dump_timeout_s": timeout,
                    "dump_log_path": self._log_path(workdir, "cppcheck_dump.log"),
                    "cwd": workdir,
                },
            )

        misra_script = self._find_misra_script(str(ctx.get("misra_script_path") or ""))
        rule_texts_path = str(ctx.get("misra_rules_path") or self.misra_rules_path)
        if not os.path.isabs(rule_texts_path):
            rule_texts_path = os.path.abspath(rule_texts_path)
        if not os.path.isfile(rule_texts_path):
            return self._result_from_counts(
                success=False,
                required=0,
                advisory=0,
                undefined=0,
                raw_output=dump_log,
                summary=f"MISRA rules file not found: {rule_texts_path}",
                native={
                    "dump_completed": True,
                    "dump_returncode": dump_rc,
                    "dump_timed_out": dump_timed_out,
                    "dump_stdout": dump_stdout,
                    "dump_stderr": dump_stderr,
                    "dump_command": dump_cmd,
                    "dump_timeout_s": timeout,
                    "dump_real_s": dump_timing.get("real"),
                    "dump_user_s": dump_timing.get("user"),
                    "dump_sys_s": dump_timing.get("sys"),
                    "dump_log_path": self._log_path(workdir, "cppcheck_dump.log"),
                    "cwd": workdir,
                    "misra_rules_path": rule_texts_path,
                },
            )

        # Run misra.py from workdir so basename(dump) resolves
        misra_cmd = (
            f"python3 '{misra_script}' '{os.path.basename(dump_path)}' "
            f"--rule-texts='{rule_texts_path}'"
        )
        misra_timeout = int(ctx.get("misra_timeout", 300))
        if debug:
            print(f"[cppcheck-misra] misra command: {misra_cmd}")
        print(f"[cppcheck-misra] running: {misra_cmd}")

        misra_res = _run_command_streaming(
            misra_cmd,
            timeout_s=misra_timeout,
            cwd=workdir,
            stream=stream_logs,
            prefix="[cppcheck-misra][misra] ",
        )
        if isinstance(misra_res, tuple) and len(misra_res) >= 5:
            misra_stdout, misra_stderr, misra_timed_out, misra_rc, misra_timing = misra_res[0], misra_res[1], misra_res[2], misra_res[3], dict(misra_res[4] or {})
        else:
            misra_stdout, misra_stderr, misra_timed_out, misra_rc = misra_res  # type: ignore[misc]
            misra_timing = {}

        misra_log = (misra_stdout or "") + "\n" + (misra_stderr or "")
        self._write_log(workdir, "cppcheck_misra.log", misra_log)

        # IMPORTANT: misra.py often returns non-zero when violations are found.
        # Treat ONLY timeouts as non-completion.
        if misra_timed_out:
            return self._result_from_counts(
                success=False,
                required=0,
                advisory=0,
                undefined=0,
                raw_output=misra_log,
                summary=f"cppcheck MISRA run timed out:\n{misra_log}",
                native={
                    "misra_completed": False,
                    "misra_returncode": misra_rc,
                    "misra_timed_out": misra_timed_out,
                    "misra_stdout": misra_stdout,
                    "misra_stderr": misra_stderr,
                    "misra_command": misra_cmd,
                    "misra_timeout_s": misra_timeout,
                    "misra_real_s": misra_timing.get("real"),
                    "misra_user_s": misra_timing.get("user"),
                    "misra_sys_s": misra_timing.get("sys"),
                    "misra_log_path": self._log_path(workdir, "cppcheck_misra.log"),
                    "cwd": workdir,
                },
            )
        if misra_rc != 0 and "[misra-c2012-" not in misra_log:
            return self._result_from_counts(
                success=False,
                required=0,
                advisory=0,
                undefined=0,
                raw_output=misra_log,
                summary=f"cppcheck MISRA addon failed (rc={misra_rc}):\n{misra_log}",
                native={
                    "misra_returncode": misra_rc,
                    "misra_stdout": misra_stdout,
                    "misra_stderr": misra_stderr,
                    "misra_command": misra_cmd,
                    "cwd": workdir,
                },
            )

        # -------------------------
        # Scope definitions
        # -------------------------
        # "allowed_files" = what you want to gate on (typically the generated .c plus generated header).
        allowed_files: List[str] = [c_file_path]
        header_path = ctx.get("generated_header_path")
        if isinstance(header_path, str) and header_path.strip():
            allowed_files.append(header_path)

        # The C artifact being analysed is always a generated/gated artifact.
        # Additional generated files may be supplied to cover generated headers
        # or other source files.  This also makes staging-safe scope decisions:
        # callers can pass original paths while cppcheck analyses a staged copy.
        generated_files: List[str] = [c_file_path]
        gen_list = ctx.get("generated_files")
        if isinstance(gen_list, list):
            for p in gen_list:
                if isinstance(p, str) and p.strip() and p not in generated_files:
                    generated_files.append(p)
        # The optional generated header is also gated.
        if isinstance(header_path, str) and header_path.strip() and header_path not in generated_files:
            generated_files.append(header_path)

        result = self._analyze_output(
            misra_log,
            command=misra_cmd,
            allowed_files=allowed_files,
            generated_files=generated_files,
        )

        try:
            cppcheck_findings = self._parse_cppcheck_xml(dump_stderr, generated_files, workdir)
        except (ET.ParseError, ValueError) as exc:
            return self._result_from_counts(
                success=False,
                required=0,
                advisory=0,
                undefined=0,
                raw_output=dump_log,
                summary=f"Failed to parse Cppcheck XML output: {exc}",
                native={"dump_command": dump_cmd, "dump_returncode": dump_rc, "cwd": workdir},
            )

        gate_warnings = bool(ctx.get("cppcheck_gate_warnings", self.gate_warnings))
        gating_cppcheck = [
            finding
            for finding in cppcheck_findings
            if finding["severity"] == "error"
            or (gate_warnings and finding["severity"] == "warning")
        ]
        misra_success = bool(result["success"])
        result["success"] = misra_success and not gating_cppcheck
        cppcheck_weight = sum(3 if finding["severity"] == "error" else 1 for finding in gating_cppcheck)
        combined_weight = int(result["metrics"].get("weighted_violations_generated", 0)) + cppcheck_weight
        result["score"] = 1.0 if result["success"] else 1.0 / (1.0 + float(combined_weight))
        result["findings"] = cppcheck_findings + list(result.get("findings", []))
        native_summary = (
            f"Cppcheck reported {len(cppcheck_findings)} generated-code finding(s); "
            f"{len(gating_cppcheck)} gated."
        )
        result["summary"] = native_summary + " " + str(result["summary"])
        native_output = "\n".join(finding["message"] for finding in cppcheck_findings)
        result["raw_output"] = "\n".join(
            part for part in [native_output, str(result.get("raw_output", ""))] if part.strip()
        )

        # Attach native execution info
        result_metrics = dict(result.get("metrics", {}))
        result_metrics["native"] = {
            "dump_command": dump_cmd,
            "dump_stdout": dump_stdout,
            "dump_stderr": dump_stderr,
            "dump_returncode": dump_rc,
            "dump_timed_out": dump_timed_out,
            "dump_timeout_s": timeout,
            "dump_real_s": dump_timing.get("real"),
            "dump_user_s": dump_timing.get("user"),
            "dump_sys_s": dump_timing.get("sys"),
            "dump_path": dump_path,
            "dump_log_path": self._log_path(workdir, "cppcheck_dump.log"),
            "misra_command": misra_cmd,
            "misra_stdout": misra_stdout,
            "misra_stderr": misra_stderr,
            "misra_returncode": misra_rc,
            "misra_timed_out": misra_timed_out,
            "misra_timeout_s": misra_timeout,
            "misra_real_s": misra_timing.get("real"),
            "misra_user_s": misra_timing.get("user"),
            "misra_sys_s": misra_timing.get("sys"),
            "misra_log_path": self._log_path(workdir, "cppcheck_misra.log"),
            "misra_rules_path": rule_texts_path,
            "cwd": workdir,
            "allowed_files": allowed_files,
            "generated_files": generated_files,
        }
        result["metrics"] = result_metrics
        result["metrics"].update(
            {
                "cppcheck_findings_generated": len(cppcheck_findings),
                "cppcheck_errors_generated": sum(f["severity"] == "error" for f in cppcheck_findings),
                "cppcheck_warnings_generated": sum(f["severity"] == "warning" for f in cppcheck_findings),
                "cppcheck_information_generated": sum(f["severity"] == "info" for f in cppcheck_findings),
                "cppcheck_gating_findings": len(gating_cppcheck),
                "cppcheck_gate_warnings": gate_warnings,
            }
        )
        result["metrics"]["process_real_s"] = float(dump_timing.get("real", 0.0)) + float(misra_timing.get("real", 0.0))
        result["metrics"]["process_user_s"] = float(dump_timing.get("user", 0.0)) + float(misra_timing.get("user", 0.0))
        result["metrics"]["process_sys_s"] = float(dump_timing.get("sys", 0.0)) + float(misra_timing.get("sys", 0.0))
        return result

    # -------------------------
    # Internal helpers
    # -------------------------

    def _find_misra_script(self, configured: str = "") -> str:
        if configured:
            return os.path.abspath(configured)
        executable = shutil.which("cppcheck")
        candidates = [
            "/usr/local/share/cppcheck/addons/misra.py",
            "/usr/share/cppcheck/addons/misra.py",
            "/usr/lib/x86_64-linux-gnu/cppcheck/addons/misra.py",
            "/usr/lib/aarch64-linux-gnu/cppcheck/addons/misra.py",
        ]
        if executable:
            candidates.insert(
                0,
                os.path.abspath(os.path.join(os.path.dirname(executable), "..", "share", "cppcheck", "addons", "misra.py")),
            )
        return next((path for path in candidates if os.path.isfile(path)), candidates[0])

    def _parse_cppcheck_xml(
        self,
        output: str,
        generated_files: List[str],
        workdir: Optional[str],
    ) -> List[Finding]:
        start = output.find("<?xml")
        if start < 0:
            start = output.find("<results")
        end = output.rfind("</results>")
        if start < 0 or end < start:
            raise ValueError("Cppcheck did not emit a complete XML results document")
        root = ET.fromstring(output[start : end + len("</results>")])
        generated = {self._canonical_path(path, workdir) for path in generated_files}
        findings: List[Finding] = []
        for error in root.findall("./errors/error"):
            locations = error.findall("location")
            selected = None
            for location in locations:
                file_path = location.get("file") or location.get("file0")
                if file_path and self._canonical_path(file_path, workdir) in generated:
                    selected = location
                    break
            if locations and selected is None:
                continue

            native_severity = (error.get("severity") or "warning").lower()
            severity = "error" if native_severity == "error" else (
                "info" if native_severity in {"information", "debug"} else "warning"
            )
            message = error.get("verbose") or error.get("msg") or "Cppcheck reported a finding."
            finding: Finding = {
                "tool": self.name,
                "severity": severity,
                "message": message,
                "rule": error.get("id") or "cppcheck",
            }
            if selected is not None:
                location_data: Dict[str, Any] = {"file": selected.get("file") or selected.get("file0") or ""}
                if (selected.get("line") or "").isdigit():
                    location_data["line"] = int(selected.get("line") or 0)
                if (selected.get("column") or "").isdigit():
                    location_data["column"] = int(selected.get("column") or 0)
                finding["location"] = location_data
            findings.append(finding)
        return findings

    def _canonical_path(self, path: str, workdir: Optional[str]) -> str:
        value = path
        if not os.path.isabs(value) and workdir:
            value = os.path.join(workdir, value)
        return os.path.normcase(os.path.realpath(os.path.abspath(value)))

    def _log_path(self, workdir: Optional[str], filename: str) -> str:
        base = workdir or os.getcwd()
        return os.path.join(base, filename)

    def _write_log(self, workdir: Optional[str], filename: str, content: str) -> None:
        path = self._log_path(workdir, filename)
        try:
            with open(path, "w", encoding="utf-8", errors="replace") as f:
                f.write(content or "")
        except Exception as e:
            print(f"[cppcheck-misra] warning: failed to write log {path}: {e}")

    def _analyze_output(
        self,
        output: str,
        *,
        command: str,
        allowed_files: Optional[List[str]] = None,
        generated_files: Optional[List[str]] = None,
    ) -> CriticResult:
        lines = output.splitlines()

        # MISRA violation lines (misra.py format commonly starts with "[")
        violation_lines = [
            line for line in lines
            if "[misra-c2012-" in line and line.strip().startswith("[")
        ]

        # Filtered views
        allowed_violations = self._filter_violation_lines(violation_lines, allowed_files)
        generated_violations = self._filter_violation_lines(violation_lines, generated_files)

        allowed_output_lines = self._filter_output_lines(lines, allowed_files)
        generated_output_lines = self._filter_output_lines(lines, generated_files)

        # Counts by severity (allowed, generated, non-generated within allowed)
        req_allowed, adv_allowed, undef_allowed = self._count_by_severity(allowed_violations)
        req_gen, adv_gen, undef_gen = self._count_by_severity(generated_violations)

        # non-generated within allowed = allowed minus generated (best-effort by path)
        non_generated_violations: List[str] = []
        gen_norm = set(self._normalize_paths(generated_files or []))
        for line in allowed_violations:
            p = self._extract_path_from_violation(line)
            if not p:
                continue
            if self._normalize_path(p) not in gen_norm:
                non_generated_violations.append(line)
        req_non, adv_non, undef_non = self._count_by_severity(non_generated_violations)

        # Gate on generated scope only
        success = (len(generated_violations) == 0)
        summary = (
            "MISRA-C:2012: no violations found (generated files)."
            if success
            else "MISRA-C:2012 violations (generated files):\n" + "\n".join(generated_violations)
        )

        findings: List[Finding] = []
        for line in generated_violations:
            rule_match = re.search(r"\[(misra-c2012-[^\]]+)\]", line)
            sev = "error" if "(Required)" in line else "warning"
            location = self._extract_location_from_violation(line)
            findings.append(
                {
                    "tool": self.name,
                    "severity": sev,
                    "message": line.strip(),
                    "location": location,
                    "rule": rule_match.group(1) if rule_match else None,
                }
            )

        weighted_generated = 3 * req_gen + 1 * adv_gen + 2 * undef_gen
        score = 1.0 if success else (0.0 if weighted_generated == 0 else (1.0 / (1.0 + float(weighted_generated))))

        # Return both raw and filtered outputs + stats
        return {
            "tool": self.name,
            "success": success,
            "score": score,
            "summary": summary,
            "metrics": {
                "command": command,

                "violations_total": len(violation_lines),
                "violations_allowed": len(allowed_violations),
                "violations_generated": len(generated_violations),
                "violations_non_generated": len(non_generated_violations),

                "misra_required_allowed": req_allowed,
                "misra_advisory_allowed": adv_allowed,
                "misra_undefined_allowed": undef_allowed,

                "misra_required_generated": req_gen,
                "misra_advisory_generated": adv_gen,
                "misra_undefined_generated": undef_gen,

                "misra_required_non_generated": req_non,
                "misra_advisory_non_generated": adv_non,
                "misra_undefined_non_generated": undef_non,

                "weighted_violations_generated": weighted_generated,

                "output_lines_total": len(lines),
                "output_lines_allowed": len(allowed_output_lines),
                "output_lines_generated": len(generated_output_lines),
                "raw_output_allowed": "\n".join(allowed_output_lines).strip(),
                "raw_output_generated": "\n".join(generated_output_lines).strip(),
            },
            "findings": findings,
            "raw_output": "\n".join(generated_output_lines).strip(),
        }

    def _normalize_path(self, p: str) -> str:
        return p.replace("\\", "/")

    def _normalize_paths(self, paths: List[str]) -> List[str]:
        return [self._normalize_path(p) for p in paths if isinstance(p, str)]

    def _filter_violation_lines(self, lines: List[str], allowed_files: Optional[List[str]]) -> List[str]:
        if not allowed_files:
            return lines

        allowed_norm = self._normalize_paths(allowed_files)
        out: List[str] = []
        for line in lines:
            path = self._extract_path_from_violation(line)
            if not path:
                continue
            path_norm = self._normalize_path(path)
            if any(path_norm == a or path_norm.endswith(a) or a.endswith(path_norm) for a in allowed_norm):
                out.append(line)
        return out

    def _filter_output_lines(self, lines: List[str], allowed_files: Optional[List[str]]) -> List[str]:
        if not allowed_files:
            return lines

        allowed_norm = self._normalize_paths(allowed_files)
        out: List[str] = []
        for line in lines:
            path = self._extract_path_from_violation(line)
            if not path:
                continue
            path_norm = self._normalize_path(path)
            if any(path_norm == a or path_norm.endswith(a) or a.endswith(path_norm) for a in allowed_norm):
                out.append(line)
        return out

    def _extract_path_from_violation(self, line: str) -> Optional[str]:
        s = line.strip()

        # Common misra.py format uses bracketed location: [path:line:col]
        bracket_matches = re.findall(r"\[([^\]]+):\d+(?::\d+)?\]", s)
        if bracket_matches:
            return bracket_matches[-1]

        # Fallback: file:line:col:
        m = re.match(r"^(?P<file>.+?):\d+(?::\d+)?:", s)
        if m:
            return m.group("file")

        return None

    def _extract_location_from_violation(self, line: str) -> Optional[Dict[str, Any]]:
        s = line.strip()
        m = re.search(r"\[(?P<file>[^\]]+?):(?P<line>\d+)(?::(?P<col>\d+))?\]", s)
        if not m:
            m = re.match(r"^(?P<file>.+?):(?P<line>\d+)(?::(?P<col>\d+))?:", s)
        if not m:
            return None

        loc: Dict[str, Any] = {"file": m.group("file"), "line": int(m.group("line"))}
        if m.groupdict().get("col"):
            loc["column"] = int(m.group("col"))
        return loc

    def _count_by_severity(self, lines: List[str]) -> tuple[int, int, int]:
        required = 0
        advisory = 0
        undefined = 0
        for line in lines:
            if "(Required)" in line:
                required += 1
            elif "(Advisory)" in line:
                advisory += 1
            elif "(Undefined)" in line:
                undefined += 1
        return required, advisory, undefined

    def _result_from_counts(
        self,
        success: bool,
        required: int,
        advisory: int,
        undefined: int,
        raw_output: str,
        summary: str,
        native: Optional[Dict[str, Any]] = None,
    ) -> CriticResult:
        weighted = 3 * required + 1 * advisory + 2 * undefined
        score = 1.0 if success else (0.0 if weighted == 0 else (1.0 / (1.0 + float(weighted))))

        metrics: Dict[str, Any] = {
            "misra_required": required,
            "misra_advisory": advisory,
            "misra_undefined": undefined,
            "weighted_violations": weighted,
        }
        if native is not None:
            metrics["native"] = native

        return {
            "tool": self.name,
            "success": success,
            "score": score,
            "summary": summary,
            "metrics": metrics,
            "findings": [],
            "raw_output": raw_output,
        }


def _run_command_streaming(
    cmd: str,
    *,
    timeout_s: int,
    cwd: Optional[str],
    stream: bool,
    prefix: str,
) -> Tuple[str, str, bool, int, Dict[str, float]]:
    """
    Runs `cmd` via `/usr/bin/time -p bash -lc`, streams output live (if stream=True), and returns:
      (stdout, stderr, timed_out, returncode, {real,user,sys})

    NOTE: A non-zero return code is not treated as a timeout. Linters often return
    non-zero when findings exist. Callers decide how to interpret returncode.
    """
    timed_cmd = f"/usr/bin/time -p bash -lc {shlex.quote(cmd)}"
    proc = subprocess.Popen(
        ["bash", "-lc", timed_cmd],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,  # line-buffered
        universal_newlines=True,
    )

    stdout_lines: List[str] = []
    stderr_lines: List[str] = []

    def _reader(pipe, acc: List[str], tag: str) -> None:
        try:
            for line in iter(pipe.readline, ""):
                acc.append(line)
                if stream:
                    print(f"{prefix}{tag}{line.rstrip()}", flush=True)
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    t_out = threading.Thread(target=_reader, args=(proc.stdout, stdout_lines, ""), daemon=True)
    t_err = threading.Thread(target=_reader, args=(proc.stderr, stderr_lines, "ERR: "), daemon=True)
    t_out.start()
    t_err.start()

    timed_out = False
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            proc.kill()
        except Exception:
            pass

    # Ensure reader threads finish
    t_out.join(timeout=1)
    t_err.join(timeout=1)

    stderr_text = "".join(stderr_lines)
    cleaned_stderr, timing = _strip_time_lines(stderr_text)

    rc = proc.returncode if proc.returncode is not None else (-9 if timed_out else -1)
    return ("".join(stdout_lines), cleaned_stderr, timed_out, rc, timing)


def _strip_time_lines(stderr_text: str) -> tuple[str, Dict[str, float]]:
    rx = re.compile(r"^\s*(real|user|sys)\s+([0-9]+(?:\.[0-9]+)?)\s*$")
    timing: Dict[str, float] = {}
    kept: List[str] = []
    for line in (stderr_text or "").splitlines():
        m = rx.match(line)
        if m:
            try:
                timing[m.group(1)] = float(m.group(2))
            except Exception:
                pass
            continue
        kept.append(line)
    out = "\n".join(kept)
    if stderr_text.endswith("\n") and out:
        out += "\n"
    return out, timing
