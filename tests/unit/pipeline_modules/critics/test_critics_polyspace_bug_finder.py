from __future__ import annotations

import json
import os
import shlex
import shutil
from pathlib import Path

import pytest

from spec2code.pipeline_modules.critics import critics_polyspace_bug_finder as polyspace
from spec2code.pipeline_modules.critics.critics_registry import CRITIC_BUILDERS, GUI_CRITICS_CATALOG


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "generated.c"
    source.write_text("int step(void) { return 0; }\n", encoding="utf-8")
    return source


def _sarif(*results: dict, rules: list[dict] | None = None) -> dict:
    return {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "Polyspace Bug Finder", "rules": rules or []}},
                "results": list(results),
            }
        ],
    }


def _result(uri: str, *, rule: str = "DIV_ZERO", level: str = "error", line: int = 4, column: int = 7) -> dict:
    return {
        "ruleId": rule,
        "level": level,
        "message": {"text": "Division by zero."},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": uri},
                    "region": {"startLine": line, "startColumn": column},
                }
            }
        ],
    }


def _run_with_sarif(tmp_path: Path, monkeypatch, sarif: dict, **critic_kwargs):
    source = _source(tmp_path)
    calls = []
    monkeypatch.setattr(polyspace, "_command_exists", lambda command: True)

    def fake_run(command, timeout, cwd=None, stream=True):
        calls.append((command, timeout, cwd, stream))
        parts = shlex.split(command)
        if "polyspace-results-export" in parts:
            output_path = Path(parts[parts.index("-output-name") + 1])
            output_path.write_text(json.dumps(sarif), encoding="utf-8")
        return "completed", "", True, 0, {"real": 0.2, "user": 0.1, "sys": 0.01}

    monkeypatch.setattr(polyspace, "run_command", fake_run)
    critic = polyspace.PolyspaceBugFinderCritic(results_root=str(tmp_path / "results"), **critic_kwargs)
    return source, calls, critic.run({"c_file_path": str(source)})


@pytest.mark.unit
@pytest.mark.critics
def test_polyspace_passes_when_sarif_has_no_findings(tmp_path, monkeypatch):
    source, calls, result = _run_with_sarif(tmp_path, monkeypatch, _sarif())

    assert result["success"] is True
    assert result["score"] == 1.0
    assert result["findings"] == []
    assert result["metrics"]["findings_total"] == 0
    assert Path(result["metrics"]["sarif_path"]).is_file()
    assert str(source) in calls[0][0]
    assert calls[1][3] is False


@pytest.mark.unit
@pytest.mark.critics
def test_polyspace_fails_on_any_generated_finding_and_filters_external_headers(tmp_path, monkeypatch):
    source = tmp_path / "generated.c"
    source.write_text("int step(void) { return 0; }\n", encoding="utf-8")
    external = tmp_path / "external.h"
    sarif = _sarif(_result(source.as_uri()), _result(external.as_uri(), rule="EXTERNAL", level="warning"))

    _, _, result = _run_with_sarif(tmp_path, monkeypatch, sarif)

    assert result["success"] is False
    assert result["score"] == 0.0
    assert len(result["findings"]) == 1
    assert result["findings"][0]["rule"] == "DIV_ZERO"
    assert result["findings"][0]["location"] == {"file": str(source), "line": 4, "column": 7}
    assert result["metrics"]["gating_findings"] == 1


@pytest.mark.unit
@pytest.mark.critics
def test_polyspace_error_threshold_keeps_warning_as_non_gating_finding(tmp_path, monkeypatch):
    source = tmp_path / "generated.c"
    source.write_text("int step(void) { return 0; }\n", encoding="utf-8")
    _, _, result = _run_with_sarif(tmp_path, monkeypatch, _sarif(_result(source.as_uri(), level="warning")), fail_on="error")

    assert result["success"] is True
    assert result["findings"][0]["severity"] == "warning"
    assert result["metrics"]["gating_findings"] == 0


@pytest.mark.unit
@pytest.mark.critics
def test_polyspace_includes_generated_header_findings(tmp_path, monkeypatch):
    source = _source(tmp_path)
    header = tmp_path / "generated.h"
    header.write_text("int value;\n", encoding="utf-8")
    monkeypatch.setattr(polyspace, "_command_exists", lambda command: True)

    def fake_run(command, timeout, cwd=None, stream=True):
        parts = shlex.split(command)
        if "polyspace-results-export" in parts:
            Path(parts[parts.index("-output-name") + 1]).write_text(
                json.dumps(_sarif(_result(header.as_uri(), rule="HEADER_DEFECT"))), encoding="utf-8"
            )
        return "", "", True, 0

    monkeypatch.setattr(polyspace, "run_command", fake_run)
    critic = polyspace.PolyspaceBugFinderCritic(results_root=str(tmp_path / "results"))
    result = critic.run({"c_file_path": str(source), "context": {"generated_header_path": str(header)}})

    assert result["success"] is False
    assert result["findings"][0]["location"]["file"] == str(header)


@pytest.mark.unit
@pytest.mark.critics
def test_polyspace_builds_quoted_commands_with_context_options(tmp_path):
    source = tmp_path / "source folder" / "generated.c"
    results = tmp_path / "results folder"
    command = polyspace.PolyspaceBugFinderCritic._analysis_command(
        executable="/opt/Polyspace/bin/polyspace-bug-finder",
        c_file_path=str(source),
        results_dir=str(results),
        include_dirs=[str(tmp_path / "header folder")],
        defines=["VALUE=two words"],
        options_file=str(tmp_path / "options file.txt"),
        extra_options=["-misra3", "all"],
    )

    parts = shlex.split(command)
    assert parts[0] == "/opt/Polyspace/bin/polyspace-bug-finder"
    assert parts[parts.index("-sources") + 1] == str(source)
    assert parts[parts.index("-I") + 1].endswith("header folder")
    assert parts[parts.index("-D") + 1] == "VALUE=two words"
    assert parts[-2:] == ["-misra3", "all"]


@pytest.mark.unit
@pytest.mark.critics
def test_polyspace_reports_missing_commands(tmp_path, monkeypatch):
    source = _source(tmp_path)
    monkeypatch.setattr(polyspace, "_command_exists", lambda command: False)

    result = polyspace.PolyspaceBugFinderCritic().run({"c_file_path": str(source)})

    assert result["success"] is False
    assert result["findings"][0]["rule"] == "polyspace_tool_error"
    assert "command not found" in result["summary"]


@pytest.mark.unit
@pytest.mark.critics
@pytest.mark.parametrize(
    ("analysis_result", "expected"),
    [
        (("", "timeout", False, None), "timed out"),
        (("", "license checkout failed", True, 1), "analysis failed"),
    ],
)
def test_polyspace_reports_analysis_failures(tmp_path, monkeypatch, analysis_result, expected):
    source = _source(tmp_path)
    monkeypatch.setattr(polyspace, "_command_exists", lambda command: True)
    monkeypatch.setattr(polyspace, "run_command", lambda command, timeout, cwd=None, stream=True: analysis_result)

    result = polyspace.PolyspaceBugFinderCritic(results_root=str(tmp_path / "results")).run({"c_file_path": str(source)})

    assert result["success"] is False
    assert expected in result["summary"].lower()
    assert "license" in result["raw_output"] or "timeout" in result["raw_output"]


@pytest.mark.unit
@pytest.mark.critics
def test_polyspace_reports_export_failure(tmp_path, monkeypatch):
    source = _source(tmp_path)
    monkeypatch.setattr(polyspace, "_command_exists", lambda command: True)
    responses = iter([("", "", True, 0), ("", "export failed", True, 2)])
    monkeypatch.setattr(polyspace, "run_command", lambda command, timeout, cwd=None, stream=True: next(responses))

    result = polyspace.PolyspaceBugFinderCritic(results_root=str(tmp_path / "results")).run({"c_file_path": str(source)})

    assert result["success"] is False
    assert "export failed" in result["summary"].lower()
    assert result["metrics"]["export_exit_code"] == 2


@pytest.mark.unit
@pytest.mark.critics
def test_polyspace_reports_malformed_sarif(tmp_path, monkeypatch):
    source = _source(tmp_path)
    monkeypatch.setattr(polyspace, "_command_exists", lambda command: True)

    def fake_run(command, timeout, cwd=None, stream=True):
        parts = shlex.split(command)
        if "polyspace-results-export" in parts:
            Path(parts[parts.index("-output-name") + 1]).write_text("not-json", encoding="utf-8")
        return "", "", True, 0

    monkeypatch.setattr(polyspace, "run_command", fake_run)
    result = polyspace.PolyspaceBugFinderCritic(results_root=str(tmp_path / "results")).run({"c_file_path": str(source)})

    assert result["success"] is False
    assert "Failed to read" in result["summary"]


@pytest.mark.unit
@pytest.mark.critics
def test_polyspace_parses_artifact_index_and_uri_base(tmp_path):
    source = tmp_path / "generated file.c"
    sarif = _sarif(_result("ignored.c"))
    run = sarif["runs"][0]
    run["originalUriBaseIds"] = {"SRCROOT": {"uri": tmp_path.as_uri() + "/"}}
    run["artifacts"] = [{"location": {"uri": "generated%20file.c"}}]
    run["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"] = {"index": 0, "uriBaseId": "SRCROOT"}

    findings = polyspace._parse_sarif_findings(sarif, {polyspace._normalize_path(str(source))}, str(tmp_path))

    assert findings[0]["location"]["file"] == str(source)


@pytest.mark.unit
@pytest.mark.critics
def test_polyspace_registry_and_catalog_are_opt_in(monkeypatch):
    monkeypatch.setenv("POLYSPACE_ROOT", "/opt/Polyspace/R2026a")
    critic = CRITIC_BUILDERS["polyspace-bug-finder"]({"timeout": 321, "fail_on": "any"}, [], 60)
    entry = next(item for item in GUI_CRITICS_CATALOG if item["name"] == "polyspace-bug-finder")

    assert isinstance(critic, polyspace.PolyspaceBugFinderCritic)
    assert critic.timeout == 321
    assert critic.executable.replace("\\", "/").endswith("polyspace/bin/polyspace-bug-finder")
    assert entry["default_enabled"] is False
    assert {option["key"] for option in entry["options"]} >= {"executable", "exporter", "timeout", "fail_on"}


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.critics
def test_polyspace_live_clean_source(tmp_path):
    if os.getenv("POLYSPACE_INTEGRATION") != "1":
        pytest.skip("set POLYSPACE_INTEGRATION=1 to use a licensed Polyspace installation")
    executable = os.getenv("POLYSPACE_BUG_FINDER", "polyspace-bug-finder")
    exporter = os.getenv("POLYSPACE_RESULTS_EXPORT", "polyspace-results-export")
    if not (_command_available(executable) and _command_available(exporter)):
        pytest.skip("Polyspace commands are not available")
    source = _source(tmp_path)

    result = polyspace.PolyspaceBugFinderCritic(
        executable=executable,
        exporter=exporter,
        timeout=900,
        results_root=str(tmp_path / "results"),
    ).run({"c_file_path": str(source)})

    assert result["metrics"].get("sarif_path")
    assert all(finding["rule"] != "polyspace_tool_error" for finding in result["findings"])


def _command_available(command: str) -> bool:
    return Path(command).is_file() if os.path.sep in command else shutil.which(command) is not None
