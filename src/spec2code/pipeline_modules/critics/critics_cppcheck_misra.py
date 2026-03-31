import os
import re
import shlex
import subprocess
import threading
from typing import Any, Dict, List, Optional, Tuple

from spec2code.pipeline_modules.critics.critics_interface import CriticInput, CriticResult, Finding


class CppcheckMisraCritic:
    name = "cppcheck-misra"

    def __init__(self, misra_rules_path: str, timeout: int = 600):
        self.misra_rules_path = misra_rules_path
        self.timeout = timeout

    def run(self, inp: CriticInput) -> CriticResult:
        c_file_path = inp["c_file_path"]
        timeout = int(inp.get("timeout", self.timeout))
        ctx: Dict[str, Any] = dict(inp.get("context", {}))
        debug = bool(ctx.get("debug", False))

        # Stream logs in debug or if explicitly enabled
        stream_logs = bool(ctx.get("stream_cppcheck_logs", False) or debug)

        workdir = os.path.dirname(c_file_path) or None

        dump_cmd = (
            "cppcheck --enable=all --language=c --std=c11 "
            f"--force --dump '{c_file_path}'"
        )
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

        misra_script = "/usr/lib/x86_64-linux-gnu/cppcheck/addons/misra.py"
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

        # -------------------------
        # Scope definitions
        # -------------------------
        # "allowed_files" = what you want to gate on (typically the generated .c plus generated header).
        allowed_files: List[str] = [c_file_path]
        header_path = ctx.get("generated_header_path")
        if isinstance(header_path, str) and header_path.strip():
            allowed_files.append(header_path)

        # "generated_files" = files generated by the LLM (use explicit list if provided)
        generated_files: List[str] = []
        gen_list = ctx.get("generated_files")
        if isinstance(gen_list, list):
            generated_files.extend([p for p in gen_list if isinstance(p, str) and p.strip()])
        # Backward-compatible: if only header path is provided, consider it generated too
        if isinstance(header_path, str) and header_path.strip() and header_path not in generated_files:
            generated_files.append(header_path)
        # If no explicit generated_files were passed, default to allowed_files
        if not generated_files:
            generated_files = list(allowed_files)

        result = self._analyze_output(
            misra_log,
            command=misra_cmd,
            allowed_files=allowed_files,
            generated_files=generated_files,
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
        result["metrics"]["process_real_s"] = float(dump_timing.get("real", 0.0)) + float(misra_timing.get("real", 0.0))
        result["metrics"]["process_user_s"] = float(dump_timing.get("user", 0.0)) + float(misra_timing.get("user", 0.0))
        result["metrics"]["process_sys_s"] = float(dump_timing.get("sys", 0.0)) + float(misra_timing.get("sys", 0.0))
        return result

    # -------------------------
    # Internal helpers
    # -------------------------

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
                    print(f"{prefix}{tag}{line.rstrip()}")
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
