from __future__ import annotations

from pathlib import Path

import pytest

from spec2code.pipeline_modules.critics import critics_vernfr


def _write_file(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.unit
@pytest.mark.critics
def test_vernfr_run_missing_input_file_fails(tmp_path):
    critic = critics_vernfr.VernfrCritic(default_script_path=str(tmp_path / "runner.sh"))
    result = critic.run({"c_file_path": str(tmp_path / "missing.c")})

    assert result["success"] is False
    assert "File does not exist" in result["summary"]


@pytest.mark.unit
@pytest.mark.critics
def test_vernfr_run_missing_script_path_fails(tmp_path):
    c_file = _write_file(tmp_path / "main.c", "int main(void){return 0;}\n")
    critic = critics_vernfr.VernfrCritic(default_script_path=None)

    result = critic.run({"c_file_path": str(c_file)})

    assert result["success"] is False
    assert "Missing context['script_path']" in result["summary"]


@pytest.mark.unit
@pytest.mark.critics
def test_vernfr_run_script_not_found_fails(tmp_path):
    c_file = _write_file(tmp_path / "main.c", "int main(void){return 0;}\n")
    critic = critics_vernfr.VernfrCritic(default_script_path=str(tmp_path / "missing.sh"))

    result = critic.run({"c_file_path": str(c_file)})

    assert result["success"] is False
    assert "Script not found" in result["summary"]


@pytest.mark.unit
@pytest.mark.critics
def test_vernfr_run_timeout_fails(tmp_path, monkeypatch):
    c_file = _write_file(tmp_path / "main.c", "int main(void){return 0;}\n")
    script = _write_file(tmp_path / "runner.sh", "#!/bin/bash\n")

    monkeypatch.setattr(
        critics_vernfr,
        "run_command",
        lambda cmd, timeout: ("", "timed out", False, None),
    )

    critic = critics_vernfr.VernfrCritic(default_script_path=str(script))
    result = critic.run({"c_file_path": str(c_file), "timeout": 11})

    assert result["success"] is False
    assert result["summary"] == "Tool timeout"
    assert result["metrics"]["timeout"] == 11


@pytest.mark.unit
@pytest.mark.critics
def test_vernfr_run_non_zero_exit_code_fails_with_findings(tmp_path, monkeypatch):
    c_file = _write_file(tmp_path / "main.c", "int main(void){return 0;}\n")
    script = _write_file(tmp_path / "runner.sh", "#!/bin/bash\n")

    raw = "Checking rule R1\nERROR: violation detected\n"
    monkeypatch.setattr(
        critics_vernfr,
        "run_command",
        lambda cmd, timeout: (raw, "", True, 2),
    )

    critic = critics_vernfr.VernfrCritic(default_script_path=str(script))
    result = critic.run({"c_file_path": str(c_file)})

    assert result["success"] is False
    assert result["metrics"]["exit_code"] == 2
    assert len(result["findings"]) >= 1
    assert result["findings"][0]["rule"] == "R1"


@pytest.mark.unit
@pytest.mark.critics
def test_vernfr_run_heuristic_error_without_exit_code_fails(tmp_path, monkeypatch):
    c_file = _write_file(tmp_path / "main.c", "int main(void){return 0;}\n")
    script = _write_file(tmp_path / "runner.sh", "#!/bin/bash\n")

    monkeypatch.setattr(
        critics_vernfr,
        "run_command",
        lambda cmd, timeout: ("some output\nfailed to verify\n", "", True, None),
    )

    critic = critics_vernfr.VernfrCritic(default_script_path=str(script))
    result = critic.run({"c_file_path": str(c_file)})

    assert result["success"] is False
    assert result["score"] == 0.0
    assert "failed" in result["summary"].lower() or "error" in result["summary"].lower()


@pytest.mark.unit
@pytest.mark.critics
def test_vernfr_run_success_path(tmp_path, monkeypatch):
    c_file = _write_file(tmp_path / "main.c", "int main(void){return 0;}\n")
    script = _write_file(tmp_path / "runner.sh", "#!/bin/bash\n")

    monkeypatch.setattr(
        critics_vernfr,
        "run_command",
        lambda cmd, timeout: ("all checks passed\n", "", True, 0),
    )

    critic = critics_vernfr.VernfrCritic(default_script_path=str(script))
    result = critic.run({"c_file_path": str(c_file)})

    assert result["success"] is True
    assert result["score"] == 1.0
    assert result["summary"] == "VernFr checks passed."
    assert result["findings"] == []


@pytest.mark.unit
@pytest.mark.critics
def test_vernfr_run_builds_command_with_context_and_extra_args(tmp_path, monkeypatch):
    c_file = _write_file(tmp_path / "module file.c", "int main(void){return 0;}\n")
    script = _write_file(tmp_path / "scripts" / "runner.sh", "#!/bin/bash\n")
    folder = _write_file(tmp_path / "input dir" / "x.txt", "x").parent

    seen = {}

    def _fake_run_command(cmd, timeout):
        seen["cmd"] = cmd
        seen["timeout"] = timeout
        return "ok\n", "", True, 0

    monkeypatch.setattr(critics_vernfr, "run_command", _fake_run_command)

    critic = critics_vernfr.VernfrCritic(default_script_path=str(script), timeout=90)
    result = critic.run(
        {
            "c_file_path": str(c_file),
            "extra_args": ["--from-input"],
            "context": {
                "folder": str(folder),
                "modname": "mod_custom",
                "main": "entry_main",
                "extra_args": ["--from-context"],
            },
        }
    )

    assert result["success"] is True
    assert seen["timeout"] == 90
    assert "bash" in seen["cmd"]
    assert "--folder" in seen["cmd"]
    assert "--modname mod_custom" in seen["cmd"]
    assert "--main entry_main" in seen["cmd"]
    assert "--from-context" in seen["cmd"]
    assert "--from-input" in seen["cmd"]


@pytest.mark.unit
@pytest.mark.critics
def test_vernfr_run_infers_main_from_interface_text_when_missing(tmp_path, monkeypatch):
    c_file = _write_file(tmp_path / "sgmm.c", "int main(void){return 0;}\n")
    script = _write_file(tmp_path / "runner.sh", "#!/bin/bash\n")

    seen = {}

    def _fake_run_command(cmd, timeout):
        seen["cmd"] = cmd
        return "ok\n", "", True, 0

    monkeypatch.setattr(critics_vernfr, "run_command", _fake_run_command)

    iface = """
    module sgmm {
      entry_functions: {
        void Sgmm_10ms(void),
        void Sgmm_100ms(void)
      }
    }
    """
    critic = critics_vernfr.VernfrCritic(default_script_path=str(script))
    result = critic.run({"c_file_path": str(c_file), "context": {"interface_text": iface}})

    assert result["success"] is True
    assert "--main Sgmm_10ms" in seen["cmd"]


@pytest.mark.unit
@pytest.mark.critics
def test_vernfr_helper_extract_findings_and_fallback_message():
    raw = "Checking rule RULE_X\nException: boom\n"
    findings = critics_vernfr._extract_findings("vernfr", raw, "main.c")
    assert findings[0]["rule"] == "RULE_X"
    assert findings[0]["severity"] == "error"

    fallback = critics_vernfr._extract_findings("vernfr", "", "main.c")
    assert fallback[0]["message"] == "VernFr failed."


@pytest.mark.unit
@pytest.mark.critics
def test_vernfr_helper_has_error_and_join_output_and_infer_modname():
    assert critics_vernfr._has_error("line\nerror: bad\n") is True
    assert critics_vernfr._has_error("Unexpected error (Parser_lib.Ispec_parser.MenhirBasics.Error).") is True
    assert critics_vernfr._has_error("all good\n") is False

    joined = critics_vernfr._join_output("a\n", "b\n")
    assert joined.endswith("\n")
    assert "a" in joined and "b" in joined

    assert critics_vernfr._infer_modname("/tmp/foo.c") == "foo"
    assert critics_vernfr._infer_modname("/tmp/foo.txt") == "foo"
    assert critics_vernfr._infer_main_from_interface_text("entry_functions: { void Foo_bar(void) }") == "Foo_bar"


@pytest.mark.unit
@pytest.mark.critics
def test_vernfr_run_nonzero_exit_code_fails_even_if_output_looks_clean(tmp_path, monkeypatch):
    c_file = _write_file(tmp_path / "main.c", "int main(void){return 0;}\n")
    script = _write_file(tmp_path / "runner.sh", "#!/bin/bash\n")

    monkeypatch.setattr(
        critics_vernfr,
        "run_command",
        lambda cmd, timeout: ("all checks passed\n", "", True, 1),
    )

    critic = critics_vernfr.VernfrCritic(default_script_path=str(script))
    result = critic.run({"c_file_path": str(c_file)})

    assert result["success"] is False
    assert result["score"] == 0.0
    assert result["metrics"]["exit_code"] == 1


@pytest.mark.unit
@pytest.mark.critics
def test_vernfr_run_parser_crash_output_without_exit_code_fails(tmp_path, monkeypatch):
    c_file = _write_file(tmp_path / "main.c", "int main(void){return 0;}\n")
    script = _write_file(tmp_path / "runner.sh", "#!/bin/bash\n")

    raw = "Unexpected error (Parser_lib.Ispec_parser.MenhirBasics.Error).\nPlease report as 'crash'\n"
    monkeypatch.setattr(
        critics_vernfr,
        "run_command",
        lambda cmd, timeout: (raw, "", True),
    )

    critic = critics_vernfr.VernfrCritic(default_script_path=str(script))
    result = critic.run({"c_file_path": str(c_file)})

    assert result["success"] is False
    assert result["score"] == 0.0
    assert len(result["findings"]) >= 1
