from __future__ import annotations

import json
import os
import shlex
import shutil
import uuid
from collections import Counter
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import unquote, urljoin, urlparse

from spec2code.pipeline_modules.critics.critics_interface import CriticInput, CriticResult, Finding
from spec2code.pipeline_modules.subprocess_creator import run_command


_SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2}
_SARIF_LEVEL_TO_SEVERITY = {
    "none": "info",
    "note": "info",
    "info": "info",
    "warning": "warning",
    "error": "error",
}


def _output_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _normalize_options(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [str(item) for item in value]
    raise ValueError("extra_options must be a shell-style string or list")


def _normalize_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _normalize_path(path: str, base_dir: Optional[str] = None) -> str:
    value = os.path.expanduser(path)
    if not os.path.isabs(value) and base_dir:
        value = os.path.join(base_dir, value)
    return os.path.normcase(os.path.realpath(os.path.abspath(value)))


def _command_exists(command: str) -> bool:
    expanded = os.path.expanduser(command)
    if os.path.dirname(expanded):
        return os.path.isfile(expanded) and os.access(expanded, os.X_OK)
    return shutil.which(expanded) is not None


def _command_text(parts: Sequence[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts)


def _is_timeout(completed: Any, exit_code: Any, stderr: str) -> bool:
    return completed is False or exit_code is None or "timed out" in stderr.lower()


def _run_timing(metadata: Optional[Mapping[str, Any]]) -> Dict[str, float]:
    metadata = metadata or {}
    return {
        "wall_seconds": float(metadata.get("real", 0.0) or 0.0),
        "user_seconds": float(metadata.get("user", 0.0) or 0.0),
        "sys_seconds": float(metadata.get("sys", 0.0) or 0.0),
    }


def _unpack_run_result(result: Tuple[Any, ...]) -> Tuple[Any, Any, Any, Any, Mapping[str, Any]]:
    if len(result) == 5:
        stdout, stderr, completed, exit_code, metadata = result
        return stdout, stderr, completed, exit_code, metadata if isinstance(metadata, Mapping) else {}
    if len(result) == 4:
        stdout, stderr, completed, exit_code = result
        return stdout, stderr, completed, exit_code, {}
    raise ValueError(f"Unexpected run_command result length: {len(result)}")


def _merge_outputs(stdout: str, stderr: str) -> str:
    chunks = []
    if stdout.strip():
        chunks.append(stdout.strip())
    if stderr.strip():
        chunks.append(stderr.strip())
    return "\n".join(chunks)


def _read_sarif(path: str) -> Mapping[str, Any]:
    with open(path, "r", encoding="utf-8-sig") as handle:
        document = json.load(handle)
    if not isinstance(document, Mapping) or not isinstance(document.get("runs"), list):
        raise ValueError("export is not a SARIF document with a runs array")
    return document


def _message_text(message: Any) -> str:
    if isinstance(message, str):
        return message.strip()
    if not isinstance(message, Mapping):
        return "Polyspace reported a finding."
    text = message.get("text") or message.get("markdown")
    if text:
        return str(text).strip()
    message_id = message.get("id")
    if message_id:
        return str(message_id).strip()
    return "Polyspace reported a finding."


def _rule_index(run: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    tool = run.get("tool")
    if not isinstance(tool, Mapping):
        return {}
    driver = tool.get("driver")
    extensions = tool.get("extensions")
    components = [driver] if isinstance(driver, Mapping) else []
    if isinstance(extensions, list):
        components.extend(item for item in extensions if isinstance(item, Mapping))
    rules: Dict[str, Mapping[str, Any]] = {}
    for component in components:
        for rule in component.get("rules", []) or []:
            if isinstance(rule, Mapping) and rule.get("id"):
                rules[str(rule["id"])] = rule
    return rules


def _rule_id(result: Mapping[str, Any], rules: Mapping[str, Mapping[str, Any]]) -> str:
    rule_id = result.get("ruleId")
    if rule_id:
        return str(rule_id)
    rule = result.get("rule")
    if isinstance(rule, Mapping):
        if rule.get("id"):
            return str(rule["id"])
        index = rule.get("index")
        if isinstance(index, int):
            rule_ids = list(rules)
            if 0 <= index < len(rule_ids):
                return rule_ids[index]
    return "polyspace_finding"


def _severity(result: Mapping[str, Any], rule: Optional[Mapping[str, Any]]) -> str:
    level = result.get("level")
    if not level and isinstance(rule, Mapping):
        default_configuration = rule.get("defaultConfiguration")
        if isinstance(default_configuration, Mapping):
            level = default_configuration.get("level")
    return _SARIF_LEVEL_TO_SEVERITY.get(str(level or "warning").lower(), "warning")


def _decode_file_uri(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme.lower() != "file":
        return unquote(uri)
    path = unquote(parsed.path)
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        path = f"//{parsed.netloc}{path}"
    if os.name == "nt" and len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return path


def _artifact_uri(
    artifact_location: Mapping[str, Any],
    artifacts: Sequence[Any],
) -> Tuple[str, Optional[str]]:
    uri = artifact_location.get("uri")
    uri_base_id = artifact_location.get("uriBaseId")
    index = artifact_location.get("index")
    if not uri and isinstance(index, int) and 0 <= index < len(artifacts):
        artifact = artifacts[index]
        if isinstance(artifact, Mapping):
            indexed_location = artifact.get("location")
            if isinstance(indexed_location, Mapping):
                uri = indexed_location.get("uri")
                uri_base_id = uri_base_id or indexed_location.get("uriBaseId")
    return str(uri or ""), str(uri_base_id) if uri_base_id else None


def _resolve_artifact_path(
    artifact_location: Mapping[str, Any],
    run: Mapping[str, Any],
    base_dir: str,
) -> Optional[str]:
    artifacts = run.get("artifacts") if isinstance(run.get("artifacts"), list) else []
    uri, uri_base_id = _artifact_uri(artifact_location, artifacts)
    if not uri:
        return None

    original_bases = run.get("originalUriBaseIds")
    base_uri = ""
    if uri_base_id and isinstance(original_bases, Mapping):
        base_entry = original_bases.get(uri_base_id)
        if isinstance(base_entry, Mapping):
            base_uri = str(base_entry.get("uri") or "")
    if base_uri:
        uri = urljoin(base_uri if base_uri.endswith("/") else base_uri + "/", uri)

    decoded = _decode_file_uri(uri)
    if urlparse(uri).scheme and urlparse(uri).scheme.lower() != "file":
        return None
    if not os.path.isabs(decoded):
        decoded = os.path.join(base_dir, decoded)
    return os.path.abspath(os.path.normpath(decoded))


def _location_for_result(
    result: Mapping[str, Any],
    run: Mapping[str, Any],
    base_dir: str,
) -> Tuple[Dict[str, Any], Optional[str]]:
    locations = result.get("locations")
    if not isinstance(locations, list):
        return {}, None
    for location in locations:
        if not isinstance(location, Mapping):
            continue
        physical = location.get("physicalLocation")
        if not isinstance(physical, Mapping):
            continue
        artifact_location = physical.get("artifactLocation")
        if not isinstance(artifact_location, Mapping):
            continue
        file_path = _resolve_artifact_path(artifact_location, run, base_dir)
        if not file_path:
            continue
        output: Dict[str, Any] = {"file": file_path}
        region = physical.get("region")
        if isinstance(region, Mapping):
            line = region.get("startLine")
            column = region.get("startColumn")
            if isinstance(line, int) and line > 0:
                output["line"] = line
            if isinstance(column, int) and column > 0:
                output["column"] = column
        return output, _normalize_path(file_path)
    return {}, None


def _parse_sarif_findings(
    document: Mapping[str, Any],
    allowed_files: Set[str],
    base_dir: str,
) -> List[Finding]:
    findings: List[Finding] = []
    for run in document.get("runs", []):
        if not isinstance(run, Mapping):
            continue
        rules = _rule_index(run)
        results = run.get("results")
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, Mapping):
                continue
            location, normalized_file = _location_for_result(result, run, base_dir)
            if normalized_file and normalized_file not in allowed_files:
                continue
            rule_id = _rule_id(result, rules)
            rule = rules.get(rule_id)
            finding: Finding = {
                "rule": rule_id,
                "severity": _severity(result, rule),
                "message": _message_text(result.get("message")),
            }
            if location:
                finding["location"] = location
            findings.append(finding)
    return findings


def _failure(
    summary: str,
    raw_output: str,
    *,
    metrics: Optional[Dict[str, Any]] = None,
    rule: str = "polyspace_tool_error",
) -> CriticResult:
    return {
        "tool": "polyspace-bug-finder",
        "success": False,
        "score": 0.0,
        "summary": summary,
        "findings": [{"rule": rule, "severity": "error", "message": summary}],
        "raw_output": raw_output,
        "metrics": metrics or {},
    }


class PolyspaceBugFinderCritic:
    """Run a mounted, licensed Polyspace Bug Finder installation and parse SARIF."""

    name = "polyspace-bug-finder"

    def __init__(
        self,
        *,
        executable: str = "polyspace-bug-finder",
        exporter: str = "polyspace-results-export",
        timeout: int = 900,
        options_file: str = "",
        extra_options: Any = None,
        fail_on: str = "any",
        results_root: str = "",
    ) -> None:
        self.executable = str(executable)
        self.exporter = str(exporter)
        self.timeout = int(timeout)
        self.options_file = str(options_file or "")
        self.extra_options = _normalize_options(extra_options)
        self.fail_on = str(fail_on or "any").strip().lower()
        self.results_root = str(results_root or "")
        if self.fail_on not in {"any", "warning", "error"}:
            raise ValueError("fail_on must be one of: any, warning, error")

    @staticmethod
    def _analysis_command(
        *,
        executable: str,
        c_file_path: str,
        results_dir: str,
        include_dirs: Sequence[str],
        defines: Sequence[str],
        options_file: str,
        extra_options: Sequence[str],
    ) -> str:
        parts = [executable, "-sources", c_file_path, "-results-dir", results_dir]
        if options_file:
            parts.extend(["-options-file", options_file])
        for include_dir in include_dirs:
            parts.extend(["-I", include_dir])
        for define in defines:
            parts.extend(["-D", define])
        parts.extend(extra_options)
        return _command_text(parts)

    @staticmethod
    def _export_command(exporter: str, results_dir: str, sarif_path: str) -> str:
        return _command_text(
            [
                exporter,
                "-results-dir",
                results_dir,
                "-format",
                "sarif",
                "-output-name",
                sarif_path,
            ]
        )

    def _gates(self, finding: Finding, fail_on: str) -> bool:
        if fail_on == "any":
            return True
        return _SEVERITY_RANK.get(str(finding.get("severity", "warning")), 1) >= _SEVERITY_RANK[fail_on]

    def run(self, critic_input: CriticInput) -> CriticResult:
        c_file_path = os.path.abspath(str(critic_input["c_file_path"]))
        context = critic_input.get("context") or {}
        if not isinstance(context, Mapping):
            context = {}

        executable = str(context.get("polyspace_executable") or self.executable)
        exporter = str(context.get("polyspace_results_export") or self.exporter)
        timeout = int(context.get("polyspace_timeout", self.timeout))
        options_file = str(context.get("polyspace_options_file") or self.options_file)
        fail_on = str(context.get("polyspace_fail_on") or self.fail_on).strip().lower()
        extra_options = self.extra_options + _normalize_options(context.get("polyspace_extra_options"))

        if fail_on not in {"any", "warning", "error"}:
            return _failure(
                f"Invalid Polyspace fail_on value: {fail_on!r}.",
                "Expected one of: any, warning, error.",
            )
        if not os.path.isfile(c_file_path):
            return _failure(f"Generated C file not found: {c_file_path}", "")
        if options_file and not os.path.isfile(options_file):
            return _failure(f"Polyspace options file not found: {options_file}", "")
        if not _command_exists(executable):
            return _failure(
                f"Polyspace Bug Finder command not found: {executable}",
                "Mount a licensed Linux Polyspace installation and configure its executable path.",
            )
        if not _command_exists(exporter):
            return _failure(
                f"Polyspace results export command not found: {exporter}",
                "Mount a licensed Linux Polyspace installation and configure its exporter path.",
            )

        include_dirs = _normalize_string_list(context.get("include_dirs"))
        defines = _normalize_string_list(context.get("defines"))
        header_path = str(context.get("generated_header_path") or "").strip()
        allowed_files = {_normalize_path(c_file_path)}
        if header_path:
            allowed_files.add(_normalize_path(header_path, os.path.dirname(c_file_path)))

        root = str(context.get("polyspace_results_root") or self.results_root).strip()
        if not root:
            root = os.path.join(os.path.dirname(c_file_path), ".polyspace")
        root = os.path.abspath(root)
        os.makedirs(root, exist_ok=True)
        run_dir = os.path.join(root, f"{os.path.splitext(os.path.basename(c_file_path))[0]}-{uuid.uuid4().hex[:12]}")
        results_dir = os.path.join(run_dir, "results")
        sarif_path = os.path.join(run_dir, "polyspace.sarif")
        os.makedirs(run_dir, exist_ok=False)

        analysis_command = self._analysis_command(
            executable=executable,
            c_file_path=c_file_path,
            results_dir=results_dir,
            include_dirs=include_dirs,
            defines=defines,
            options_file=options_file,
            extra_options=extra_options,
        )
        analysis_stdout_raw, analysis_stderr_raw, analysis_completed, analysis_exit, analysis_meta = _unpack_run_result(
            run_command(
                analysis_command,
                timeout=timeout,
                cwd=os.path.dirname(c_file_path),
            )
        )
        analysis_stdout = _output_text(analysis_stdout_raw)
        analysis_stderr = _output_text(analysis_stderr_raw)
        analysis_output = _merge_outputs(analysis_stdout, analysis_stderr)
        analysis_metrics: Dict[str, Any] = {
            "results_dir": results_dir,
            "analysis_exit_code": analysis_exit,
            "analysis_timing": _run_timing(analysis_meta if isinstance(analysis_meta, Mapping) else None),
        }
        if _is_timeout(analysis_completed, analysis_exit, analysis_stderr):
            return _failure(
                f"Polyspace Bug Finder timed out after {timeout} seconds.",
                analysis_output,
                metrics=analysis_metrics,
                rule="polyspace_timeout",
            )
        if analysis_exit != 0:
            diagnostic = analysis_output or f"Polyspace exited with status {analysis_exit}."
            return _failure(
                "Polyspace Bug Finder analysis failed. Check installation and license diagnostics.",
                diagnostic,
                metrics=analysis_metrics,
            )

        export_command = self._export_command(exporter, results_dir, sarif_path)
        export_stdout_raw, export_stderr_raw, export_completed, export_exit, export_meta = _unpack_run_result(
            run_command(
                export_command,
                timeout=timeout,
                cwd=run_dir,
                stream=False,
            )
        )
        export_stdout = _output_text(export_stdout_raw)
        export_stderr = _output_text(export_stderr_raw)
        export_output = _merge_outputs(export_stdout, export_stderr)
        metrics = {
            **analysis_metrics,
            "sarif_path": sarif_path,
            "export_exit_code": export_exit,
            "export_timing": _run_timing(export_meta if isinstance(export_meta, Mapping) else None),
        }
        combined_output = _merge_outputs(analysis_output, export_output)
        if _is_timeout(export_completed, export_exit, export_stderr):
            return _failure(
                f"Polyspace SARIF export timed out after {timeout} seconds.",
                combined_output,
                metrics=metrics,
                rule="polyspace_timeout",
            )
        if export_exit != 0:
            return _failure(
                "Polyspace SARIF export failed.",
                combined_output or f"Exporter exited with status {export_exit}.",
                metrics=metrics,
            )
        if not os.path.isfile(sarif_path):
            return _failure(
                "Polyspace SARIF export did not create the expected file.",
                combined_output,
                metrics=metrics,
            )

        try:
            document = _read_sarif(sarif_path)
            findings = _parse_sarif_findings(document, allowed_files, os.path.dirname(c_file_path))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return _failure(
                f"Failed to read Polyspace SARIF output: {exc}",
                combined_output,
                metrics=metrics,
            )

        severity_counts = Counter(str(finding.get("severity", "warning")) for finding in findings)
        gating_findings = [finding for finding in findings if self._gates(finding, fail_on)]
        metrics.update(
            {
                "findings_total": len(findings),
                "gating_findings": len(gating_findings),
                "severity_counts": dict(severity_counts),
                "fail_on": fail_on,
            }
        )
        success = not gating_findings
        if findings:
            summary = (
                f"Polyspace Bug Finder reported {len(findings)} generated-code finding(s); "
                f"{len(gating_findings)} met the {fail_on!r} failure threshold."
            )
        else:
            summary = "Polyspace Bug Finder reported no findings in generated code."
        return {
            "tool": self.name,
            "success": success,
            "score": 1.0 if success else 0.0,
            "summary": summary,
            "findings": findings,
            "raw_output": combined_output,
            "metrics": metrics,
        }
